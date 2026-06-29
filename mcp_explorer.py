"""
MCP Tool Box -- tool definitions and MCP client/session plumbing for the single
agent's execution phase.

The agent doesn't know which workflow engine is behind the MCP server. It calls
the same tools regardless of backend (Parsl, PyCOMPSs, ADIOS).
"""

import os
import sys
import json
import asyncio
import time
from typing import Optional
from contextlib import AsyncExitStack

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.tools import tool
from rich.console import Console
from trace_logger import tracer, extract_usage, message_to_dict
from rich.panel import Panel

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

console = Console()

# __ MCP Server Config _________________________________________________________

_SERVERS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "servers")

ENGINE_SERVERS = {
    "parsl": os.path.join(_SERVERS_DIR, "parsl_server.py"),
    "pycompss": os.path.join(_SERVERS_DIR, "pycompss_server.py"),
    "adios": os.path.join(_SERVERS_DIR, "adios_server.py"),
}


# __ LangChain Tool Wrappers __________________________________________________
# These tools are bound to the LLM. When called, they delegate to the MCP session
# stored in _mcp_session (set during the execution loop's async run).

_mcp_session: Optional[ClientSession] = None
_event_loop: Optional[asyncio.AbstractEventLoop] = None


def _call_mcp_tool(tool_name: str, arguments: dict) -> str:
    """Synchronously call an MCP tool via the active session.

    Uses the event loop from the execution loop's async context to avoid
    creating new threads/loops per call.
    """
    if _mcp_session is None:
        return json.dumps({"error": "MCP session not connected"})

    async def _call():
        result = await _mcp_session.call_tool(tool_name, arguments)
        if result.content:
            texts = [block.text for block in result.content if hasattr(block, "text")]
            return "\n".join(texts) if texts else "{}"
        return "{}"

    # Use the execution loop's event loop directly
    if _event_loop and _event_loop.is_running():
        future = asyncio.run_coroutine_threadsafe(_call(), _event_loop)
        return future.result(timeout=600)
    else:
        return asyncio.run(_call())


# __ Skill file helpers ________________________________________________________

_SKILLS_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")


def _read_skill(rel_path: str, agent_name: str = "single_agent") -> str:
    """Read skills/<rel_path>.SKILL.md -- returns '' if not found."""
    full = os.path.join(_SKILLS_ROOT, rel_path + ".SKILL.md")
    found = os.path.isfile(full)
    tracer.log_skill_load(agent_name, rel_path, found)
    if found:
        with open(full) as f:
            return f.read()
    return ""


@tool
def submit_task(name: str, python_code: str, depends_on: list[str] | None = None, timeout: int = 1800) -> str:
    """Submit a Python task for execution via the workflow engine.

    The task runs in the local venv environment. Write complete, self-contained
    Python code with all imports at the top.

    Args:
        name: Descriptive name for this task (e.g. "run_lammps", "analyze_ovito")
        python_code: Python code to execute (multi-line string, all imports included)
        depends_on: List of task IDs that must complete before this task runs (optional)
        timeout: Max seconds to wait (default: 600)
    """
    args = {"name": name, "python_code": python_code, "timeout": timeout}
    if depends_on:
        args["depends_on"] = depends_on
    return _call_mcp_tool("submit_task", args)


@tool
def submit_shell_task(name: str, command: str, work_dir: str = "/app/work/run0", timeout: int = 1800) -> str:
    """Submit a shell command for execution in the local environment.

    Use this for file operations, system commands, and non-Python tasks.

    Args:
        name: Descriptive name (e.g. "copy_data_files", "create_directories")
        command: Shell command to execute (e.g. "mkdir -p /app/work/run0/frames")
        work_dir: Working directory (default: /app/work/run0)
        timeout: Max seconds to wait (default: 600)
    """
    return _call_mcp_tool("submit_shell_task", {
        "name": name, "command": command, "work_dir": work_dir, "timeout": timeout,
    })


@tool
def get_task_status(task_id: str) -> str:
    """Get the current status of a submitted task.

    Args:
        task_id: The task ID returned by submit_task or submit_shell_task
    """
    return _call_mcp_tool("get_task_status", {"task_id": task_id})


@tool
def get_task_result(task_id: str) -> str:
    """Get the full output (stdout/stderr) of a completed task.

    Args:
        task_id: The task ID returned by submit_task or submit_shell_task
    """
    return _call_mcp_tool("get_task_result", {"task_id": task_id})


@tool
def list_tasks() -> str:
    """List all submitted tasks and their current status."""
    return _call_mcp_tool("list_tasks", {})


@tool
def install_package(package: str) -> str:
    """Install a pip package into the local venv.

    Use when a required package is missing (ModuleNotFoundError).

    Args:
        package: Package name to install (e.g. "numpy", "ovito==3.10.0")
    """
    return _call_mcp_tool("install_package", {"package": package})


@tool
def check_package(package: str) -> str:
    """Check if a Python package is installed in the local venv.

    Args:
        package: Package name to check (e.g. "numpy", "lammps", "ovito")
    """
    return _call_mcp_tool("check_package", {"package": package})


@tool
def list_files(directory: str = "/app/work/run0") -> str:
    """List all files in a directory in the local environment.

    Use this to verify that expected output files were created after a task.

    Args:
        directory: Path to list (default: /app/work/run0)
    """
    return _call_mcp_tool("list_files", {"directory": directory})


@tool
def read_file(path: str, max_lines: int = 100) -> str:
    """Read the contents of a file in the local environment.

    Use this to inspect output files, check results, or debug errors.

    Args:
        path: Absolute path of the file
        max_lines: Maximum number of lines to return (default: 100)
    """
    return _call_mcp_tool("read_file", {"path": path, "max_lines": max_lines})


@tool
def get_resources() -> str:
    """Detect available compute resources (nodes, ranks, launcher) for this run.

    Always call this FIRST, before writing any MPI command and before deciding
    whether you're on a single local machine or inside a multi-node HPC allocation.

    Returns JSON with in_pbs, nnodes, ntasks, cpus_per_task, nodelist, launcher.
    If in_pbs is false, call load_skill("local"). If in_pbs is true, call
    load_skill("hpc") to learn the launcher conventions and storage paths.
    """
    return _call_mcp_tool("get_resources", {})


@tool
def submit_mpi_task(name: str, command: str, num_ranks: int = 0,
                     work_dir: str = "/app/work/run0", timeout: int = 1800) -> str:
    """Submit a command to run in parallel under MPI (mpirun/srun).

    Only use this after get_resources confirms in_pbs=true. Prepends the detected
    MPI launcher to the given command.

    Args:
        name: Descriptive name for this task
        command: The executable and its arguments, without the launcher prefix
                 (e.g. "lmp -in /app/work/run0/in.watbox")
        num_ranks: Number of MPI ranks. 0 (default) uses all ranks from get_resources.
        work_dir: Working directory (default: /app/work/run0)
        timeout: Max seconds to wait (default: 1800)
    """
    return _call_mcp_tool("submit_mpi_task", {
        "name": name, "command": command, "num_ranks": num_ranks,
        "work_dir": work_dir, "timeout": timeout,
    })


_KNOWLEDGE_SKILLS = {
    "local": "knowledge/local",
    "hpc":   "knowledge/lcrc",
}


@tool
def load_skill(name: str) -> str:
    """Load runtime-environment knowledge into your context: "local" or "hpc".

    Call this only after get_resources tells you which environment you're actually
    in -- do not load both. "local" covers single-machine constraints (no MPI,
    no PBS). "hpc" covers PBS/mpirun conventions and LCRC storage paths.

    Args:
        name: "local" or "hpc"
    """
    if name not in _KNOWLEDGE_SKILLS:
        return f"Unknown skill '{name}'. Use 'local' or 'hpc'."
    return _read_skill(_KNOWLEDGE_SKILLS[name]) or f"No '{name}' knowledge file found."


# All tools available during the execution phase
EXECUTION_TOOLS = [
    submit_task, submit_shell_task,
    get_task_status, get_task_result, list_tasks,
    install_package, check_package,
    list_files, read_file,
    get_resources, submit_mpi_task, load_skill,
]


# __ Execution loop (phase 3 of the single agent) ______________________________

async def run_execution_loop(messages: list[BaseMessage], engine: str,
                              agent_name: str = "single_agent",
                              max_iterations: int = 150) -> tuple[list[BaseMessage], list[dict]]:
    """Connect to the engine's MCP server and run a tool-calling ReAct loop,
    extending the given (already populated) message transcript.

    Unlike a fresh agent, `messages` arrives with the planning and install
    phases already in it -- the system prompt plus however many turns those
    phases produced. Context trimming below pins all of that and only slides
    a window over the tool-calling turns added in this loop.
    """
    global _mcp_session

    server_path = ENGINE_SERVERS.get(engine)
    if not server_path or not os.path.isfile(server_path):
        raise FileNotFoundError(f"Server not found for engine '{engine}': {server_path}")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[server_path],
        env={
            **os.environ,
            "HOST_REPO_PATH": os.environ.get(
                "HOST_REPO_PATH",
                os.path.dirname(os.path.abspath(__file__)),
            ),
        },
    )

    async with AsyncExitStack() as stack:
        stdio_transport = await stack.enter_async_context(stdio_client(server_params))
        read_stream, write_stream = stdio_transport
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()

        _mcp_session = session

        tools_result = await session.list_tools()
        available = [t.name for t in tools_result.tools]
        console.print(f"[dim cyan][single_agent] MCP server tools: {available}[/dim cyan]")

        console.print(Panel(
            f"[bold]Engine:[/bold] {engine}\n[bold]Transcript so far:[/bold] {len(messages)} messages",
            title="[bold cyan]Execution Phase Starting[/bold cyan]",
            border_style="cyan",
        ))

        llm = ChatOpenAI(
            model=os.getenv("CODER_MODEL_NAME", os.getenv("MODEL_NAME", "claudesonnet46")),
        )
        llm_with_tools = llm.bind_tools(EXECUTION_TOOLS)

        exploration_log: list[dict] = []
        iteration = 0

        _MAX_TOOL_RESULT_CHARS = 8_000  # cap per tool result added to messages
        _CONTEXT_WINDOW        = 20     # message slots kept beyond the pinned prefix
        _pinned_len            = len(messages)  # system + planning + install turns, never trimmed

        for iteration in range(max_iterations):
            console.print(f"\n[dim yellow][single_agent] execution iteration {iteration + 1}/{max_iterations}[/dim yellow]")

            # Trim context window: keep the pinned prefix + last _CONTEXT_WINDOW messages.
            # Scan forward past any leading ToolMessages to avoid orphaned tool results.
            if len(messages) > _pinned_len + _CONTEXT_WINDOW:
                tail = messages[-_CONTEXT_WINDOW:]
                start = next((i for i, m in enumerate(tail) if not isinstance(m, ToolMessage)), 0)
                messages = messages[:_pinned_len] + tail[start:]
                console.print(f"[dim yellow][single_agent] context trimmed to {len(messages)} messages[/dim yellow]")

            # Run LLM call in a thread (it's sync/blocking)
            _t0 = time.time()
            response = await asyncio.to_thread(llm_with_tools.invoke, messages)
            _latency_s = round(time.time() - _t0, 2)
            _usage = extract_usage(response)
            _model_name = getattr(llm, "model_name", None) or os.getenv(
                "CODER_MODEL_NAME", os.getenv("MODEL_NAME", ""))
            tracer.log_llm_call(
                agent_name, _model_name,
                [message_to_dict(m) for m in messages],
                response.content if hasattr(response, "content") else str(response),
                tool_calls=response.tool_calls or [],
                input_tokens=_usage["input_tokens"], output_tokens=_usage["output_tokens"],
                total_tokens=_usage["total_tokens"], latency_s=_latency_s, attempt=iteration + 1,
            )
            messages.append(response)

            if _usage:
                tracer.log_token_usage(agent_name, _usage["input_tokens"],
                                       _usage["output_tokens"], _usage["total_tokens"],
                                       model=getattr(llm, "model_name", ""))

            if not response.tool_calls:
                console.print(Panel(
                    response.content[:3000] if response.content else "(no content)",
                    title="[bold green]Execution Complete[/bold green]",
                    border_style="green",
                ))
                break

            mcp_broken = False
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_id = tool_call["id"]

                console.print(f"[dim cyan][single_agent] calling tool: {tool_name}({json.dumps(tool_args, indent=2)[:200]})[/dim cyan]")

                # load_skill is client-side (reads local skill files via _read_skill) --
                # no MCP server implements it as a tool, so it must run locally rather
                # than being forwarded to session.call_tool like every other tool below.
                if tool_name == "load_skill":
                    tool_result = load_skill.invoke(tool_args)
                    console.print(f"[green][single_agent] {tool_name} -> loaded locally[/green]")
                    exploration_log.append({
                        "iteration": iteration + 1,
                        "tool": tool_name,
                        "args": tool_args,
                        "result": tool_result[:2000],
                        "succeeded": True,
                    })
                    tracer.log_tool_call(agent_name, tool_name, tool_args, tool_result,
                                         True, iteration=iteration + 1)
                    messages.append(ToolMessage(
                        content=tool_result[:_MAX_TOOL_RESULT_CHARS],
                        tool_call_id=tool_id,
                    ))
                    continue

                # Call MCP tool with timeout protection
                try:
                    mcp_result = await asyncio.wait_for(
                        session.call_tool(tool_name, tool_args),
                        timeout=1800,  # 30 min max per tool call
                    )
                    if mcp_result.content:
                        texts = [block.text for block in mcp_result.content if hasattr(block, "text")]
                        tool_result = "\n".join(texts) if texts else "{}"
                    else:
                        tool_result = "{}"
                except asyncio.TimeoutError:
                    tool_result = json.dumps({
                        "error": f"Tool call timed out after 1800s",
                        "status": "timeout",
                    })
                    console.print(f"[bold red][single_agent] {tool_name} timed out -- skipping[/bold red]")
                except (BrokenPipeError, ConnectionError, EOFError) as e:
                    tool_result = json.dumps({
                        "error": f"MCP connection lost: {e}",
                        "status": "connection_lost",
                    })
                    console.print(f"[bold red][single_agent] MCP connection lost -- ending execution[/bold red]")
                    mcp_broken = True
                except Exception as e:
                    tool_result = json.dumps({"error": str(e)})

                # Determine success/failure from the result
                tool_succeeded = False
                display_status = "?"
                try:
                    parsed = json.loads(tool_result)
                    # A tool call succeeded if ANY of these are true:
                    # - "status" is "completed" or "success"
                    # - "exit_code" is 0
                    # - "installed" is True (check_package)
                    # - "files" key exists (list_files)
                    # - "content" key exists (read_file)
                    # - "error" key is absent
                    status_val = parsed.get("status")
                    exit_code = parsed.get("exit_code")
                    has_error = "error" in parsed

                    if status_val == "failed":
                        tool_succeeded = False
                        display_status = f"failed (exit {exit_code})"
                    elif has_error:
                        tool_succeeded = False
                        display_status = f"error: {parsed['error'][:80]}"
                    elif status_val in ("completed", "success"):
                        tool_succeeded = True
                        display_status = status_val
                    elif exit_code == 0:
                        tool_succeeded = True
                        display_status = "exit_code: 0"
                    elif parsed.get("installed") is True:
                        tool_succeeded = True
                        display_status = "installed"
                    elif parsed.get("installed") is False:
                        tool_succeeded = True  # query succeeded, package just isn't there
                        display_status = "not installed"
                    elif "files" in parsed:
                        tool_succeeded = True
                        display_status = f"{parsed.get('count', '?')} files"
                    elif "content" in parsed:
                        tool_succeeded = True
                        display_status = f"{parsed.get('total_lines', '?')} lines"
                    elif "version" in parsed:
                        tool_succeeded = True
                        display_status = f"v{parsed['version']}"
                    elif "tasks" in parsed:
                        tool_succeeded = True
                        display_status = f"{parsed.get('total', '?')} tasks"
                    elif "nnodes" in parsed:
                        # get_resources response — no status field, presence of nnodes = success
                        tool_succeeded = True
                        launcher = parsed.get("launcher") or "none"
                        display_status = f"nodes={parsed['nnodes']} ranks={parsed.get('ntasks',1)} launcher={launcher}"
                    else:
                        # Unknown response shape — treat as failure so errors are never silently swallowed
                        tool_succeeded = False
                        display_status = "unknown response"
                except (json.JSONDecodeError, AttributeError):
                    if tool_result.lower().startswith(("unknown tool", "error")):
                        # Plain-text error responses (e.g. a hallucinated tool name) must
                        # not be marked successful just because they aren't JSON.
                        tool_succeeded = False
                        display_status = tool_result[:80]
                    else:
                        tool_succeeded = True  # raw text response, not an error
                        display_status = "done"

                log_entry = {
                    "iteration": iteration + 1,
                    "tool": tool_name,
                    "args": tool_args,
                    "result": tool_result[:2000],
                    "succeeded": tool_succeeded,
                }
                exploration_log.append(log_entry)

                color = "green" if tool_succeeded else "red"
                console.print(f"[{color}][single_agent] {tool_name} -> {display_status}[/{color}]")

                # Log to trace (full result, not truncated -- needed for debugging failed runs)
                tracer.log_tool_call(agent_name, tool_name, tool_args,
                                     tool_result, tool_succeeded, iteration=iteration + 1)

                messages.append(ToolMessage(
                    content=tool_result[:_MAX_TOOL_RESULT_CHARS],
                    tool_call_id=tool_id,
                ))

                # If MCP connection is broken, stop the tool loop
                if mcp_broken:
                    break

            # If MCP connection is broken, stop the iteration loop
            if mcp_broken:
                console.print("[bold yellow][single_agent] MCP connection lost -- ending with partial results[/bold yellow]")
                break

        else:
            console.print("[bold red][single_agent] hit max iterations limit[/bold red]")

        # Cleanup MCP server
        console.print("[dim cyan][single_agent] cleaning up MCP server...[/dim cyan]")
        try:
            await session.call_tool("cleanup", {})
        except Exception:
            pass

        _mcp_session = None

        # Build summary
        total_calls = len(exploration_log)
        successes = sum(1 for e in exploration_log if e.get("succeeded", False))
        failures = total_calls - successes

        summary = (
            f"Execution complete: {total_calls} tool calls, "
            f"{successes} succeeded, {failures} failed, "
            f"{iteration + 1} iterations"
        )
        console.print(f"[dim cyan][single_agent] {summary}[/dim cyan]")

        # Record what was actually produced -- supports tier-1/tier-3 scoring
        # directly from the trace without re-deriving it from tool-call text.
        work_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "work")
        artifacts = []
        if os.path.isdir(work_dir):
            for dirpath, _, filenames in os.walk(work_dir):
                for fn in filenames:
                    full = os.path.join(dirpath, fn)
                    try:
                        size_bytes = os.path.getsize(full)
                    except OSError:
                        size_bytes = -1
                    artifacts.append({"path": full, "size_bytes": size_bytes})
        tracer.log_artifact_manifest(artifacts)

        return messages, exploration_log


def run_execution_loop_sync(messages: list[BaseMessage], engine: str,
                             agent_name: str = "single_agent",
                             max_iterations: int = 150) -> tuple[list[BaseMessage], list[dict]]:
    """Sync wrapper around run_execution_loop -- owns the dedicated event loop
    the MCP session needs for its lifetime."""
    global _event_loop
    loop = asyncio.new_event_loop()
    _event_loop = loop
    try:
        return loop.run_until_complete(
            run_execution_loop(messages, engine, agent_name, max_iterations)
        )
    finally:
        _event_loop = None
        loop.close()

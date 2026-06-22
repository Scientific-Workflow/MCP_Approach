"""
MCP Explorer Agent -- ReAct loop that calls workflow engine tools via MCP protocol.

The explorer receives tasks from the planner once the installer has finished
preparing the local venv, then iteratively calls tools (exposed by the MCP server) to complete each task:
submitting Python tasks, running shell commands, checking outputs, installing
missing packages, and recovering from errors.

The explorer doesn't know which workflow engine is behind the MCP server.
It calls the same tools regardless of backend (Parsl, PyCOMPSs, ADIOS).
"""

import os
import sys
import json
import asyncio
import time
from typing import Optional
from contextlib import AsyncExitStack

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
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
# stored in _mcp_session (set during the explorer's async run).

_mcp_session: Optional[ClientSession] = None


_event_loop: Optional[asyncio.AbstractEventLoop] = None


def _call_mcp_tool(tool_name: str, arguments: dict) -> str:
    """Synchronously call an MCP tool via the active session.
    
    Uses the event loop from the explorer's async context to avoid
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

    # Use the explorer's event loop directly
    if _event_loop and _event_loop.is_running():
        # Schedule the coroutine on the running loop and wait for result
        future = asyncio.run_coroutine_threadsafe(_call(), _event_loop)
        return future.result(timeout=600)
    else:
        return asyncio.run(_call())


# __ Skill file helpers ________________________________________________________

_SKILLS_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")


def _read_skill(rel_path: str, agent_name: str = "explorer") -> str:
    """Read skills/<rel_path>.SKILL.md -- returns '' if not found. Logs the load attempt."""
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
    content = _read_skill(_KNOWLEDGE_SKILLS.get(name, ""))
    return content or f"Unknown skill '{name}'. Use 'local' or 'hpc'."


# All tools available to the explorer
EXPLORER_TOOLS = [
    submit_task, submit_shell_task,
    get_task_status, get_task_result, list_tasks,
    install_package, check_package,
    list_files, read_file,
    get_resources, submit_mpi_task, load_skill,
]


# __ Explorer System Prompt ____________________________________________________

EXPLORER_SYSTEM_PROMPT = """\
You are the Explorer agent in a scientific workflow reproduction system. Your job is to
execute a computational workflow step by step using tools provided by a workflow engine
MCP server.

You receive:
- A list of tasks from the planner (what needs to be done)
- Literature findings (scientific context from the paper)
- Information about what software is installed in the venv

Your goal: complete every task successfully by calling tools, observing results, and
adapting your approach when things fail.

## Available Tools

| Tool | When to use |
|---|---|
| get_resources | **Call first.** Detects nodes/ranks/launcher (in_pbs true/false) |
| load_skill | Load "local" or "hpc" environment knowledge -- pick ONE based on get_resources |
| submit_task | Execute Python code (LAMMPS, OVITO, plotting, data processing) |
| submit_shell_task | Run shell commands (cp, mkdir, ls, file operations) |
| submit_mpi_task | Run an MPI-capable command (only if get_resources says in_pbs=true) |
| get_task_status | Check if a previously submitted task is done |
| get_task_result | Get full stdout/stderr from a completed task |
| list_tasks | See all tasks and their statuses |
| install_package | Install a missing pip package |
| check_package | Verify a package is installed |
| list_files | Check what files exist in a directory |
| read_file | Inspect file contents |

## Workflow

1. Call get_resources first. Then call load_skill("hpc") if in_pbs is true, or
   load_skill("local") if it is false -- load only the one that matches.
2. Review the tasks list and plan your execution order
3. Before running a task, check prerequisites (files exist, packages installed)
4. Use submit_shell_task for file operations (copy, mkdir)
5. Use submit_task for Python code (scientific computation, analysis, plotting)
6. Use submit_mpi_task instead of submit_task/submit_shell_task for MPI-capable
   executables, but only once get_resources has confirmed in_pbs=true
7. After each task, verify output (list_files, read_file)
8. If a task fails, diagnose and fix (install package, change code, retry)
9. Track task IDs -- use depends_on when tasks have dependencies

## Rules

- Execute tasks in dependency order
- Always verify output after each task
- Max 3 retries per task before giving up -- then MOVE ON to the next task
- Do NOT spend more than 3 attempts debugging any single issue (e.g. Qt rendering, display errors)
- If a visualization/rendering task fails due to display/Qt/GUI issues, SKIP it and move to the next task
- Use submit_task for Python code (ALL imports inside the script)
- Use submit_shell_task for shell commands
- Track task_ids from submit_task results for dependency chains
- When all executable tasks are done, STOP and provide your final summary -- do not keep retrying failed tasks
- Report what you accomplished and what failed in your final message

## Scientific Integrity Rules (CRITICAL)

- Do NOT generate synthetic, fake, or hardcoded data to simulate results from the paper
- Do NOT fabricate timing data, performance benchmarks, or scaling measurements
- Do NOT reproduce scaling plots, strong/weak scaling curves, or performance comparisons
  that require HPC infrastructure (MPI, multi-node, PBS) unavailable in the current environment
- ALL visualizations MUST use data produced by your own simulation runs in this session,
  not values copied from the paper or invented to look plausible
- If a task requires infrastructure you do not have (MPI, multi-node cluster, specific
  HPC hardware), SKIP it and explain why in your summary
- If the paper shows benchmark results on 40-1280 processes but you are running on a
  single machine, do NOT simulate those benchmarks -- skip them
- You CAN measure and plot actual single-machine timing of your own pipeline stages
  (e.g. how long particle generation, analysis, and visualization took on this run)

## Data Layout (MANDATORY -- do not deviate)

NOTE: /app/ paths are automatically resolved to the local repo directory at runtime.
You do not need an actual /app/ folder. Always use /app/ paths in your code --
the MCP server translates them to the correct local paths.

- Input data: /app/data/ (source files)
- Working directory: /app/work/run0/ (ALL output goes here)
- ALL output files, subdirectories, scripts, and results MUST be placed under /app/work/run0/
- Use consistent subdirectory names:
  - /app/work/run0/frames/       for simulation trajectory/frame output
  - /app/work/run0/renders/      for visualization images and GIFs
  - /app/work/run0/results.csv   for tabular analysis results
  - /app/work/run0/workflow.py   for generated workflow scripts
  - /app/work/run0/run_workflow.sh for launcher scripts
- Do NOT create output directories with arbitrary names (no "output/", "decaf_workflow_output/", 
  "smoketest/", etc.)
- Do NOT write files to /tmp/ -- always use /app/work/run0/
"""


# __ Explorer Node _____________________________________________________________

def explorer(state: dict) -> dict:
    """
    Explorer node -- connects to MCP server and runs a ReAct tool-calling loop
    to execute workflow tasks step by step.
    """
    global _mcp_session, _event_loop

    console.print("\n[dim cyan][explorer] starting interactive workflow execution...[/dim cyan]")
    tracer.log_agent_start("explorer", {"engine": state.get("engine", "parsl")})
    tracer.log_agent_input("explorer", {
        "tasks_count": len(state.get("tasks", [])),
        "findings_count": len(state.get("literature_findings", [])),
        "engine": state.get("engine", "parsl"),
    })

    engine = state.get("engine", "parsl")
    console.print(f"[dim cyan][explorer] connecting to {engine} MCP server...[/dim cyan]")

    # Create a dedicated event loop for the MCP session
    loop = asyncio.new_event_loop()
    _event_loop = loop

    try:
        result = loop.run_until_complete(_explorer_async(state, engine))
        return result
    finally:
        _event_loop = None
        loop.close()


async def _explorer_async(state: dict, engine: str) -> dict:
    """Async implementation of the explorer -- keeps MCP session alive throughout."""
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
        # Connect to MCP server
        stdio_transport = await stack.enter_async_context(stdio_client(server_params))
        read_stream, write_stream = stdio_transport
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()

        # Set global session so tools can use it
        _mcp_session = session

        # List available tools
        tools_result = await session.list_tools()
        available = [t.name for t in tools_result.tools]
        console.print(f"[dim cyan][explorer] MCP server tools: {available}[/dim cyan]")

        # Build context from state
        tasks = state.get("tasks", [])
        findings = state.get("literature_findings", [])
        stack_decision = state.get("stack_decision", [])

        data_files = state.get("selected_data_files", [])

        context_parts = []
        if data_files:
            context_parts.append("Available input data files (in /app/data/):\n" +
                                 "\n".join(f"  - {f}" for f in data_files))
        if findings:
            context_parts.append("Literature findings:\n" +
                                 "\n".join(f"  - {f}" for f in findings))
        if stack_decision:
            context_parts.append(f"Software stack in venv: {', '.join(stack_decision)}")
        if tasks:
            context_parts.append("Tasks to execute:\n" +
                                 "\n".join(f"  {i+1}. {t}" for i, t in enumerate(tasks)))

        # Load skill files
        _base_skill = _read_skill("agents/explorer")
        _uc_skill = ""
        # Auto-detect use case: scan all use_cases/*/explorer.SKILL.md files,
        # check if their description matches any package in stack_decision.
        # This replaces the hardcoded 'if "lammps"' check.
        _stack_lower = [p.lower() for p in stack_decision]
        _uc_dir = os.path.join(_SKILLS_ROOT, "use_cases")
        if os.path.isdir(_uc_dir):
            for uc_name in os.listdir(_uc_dir):
                content = _read_skill(f"use_cases/{uc_name}/explorer")
                if not content:
                    continue
                # Match if any stack package appears in the skill file description
                desc_lower = content[:500].lower()
                if any(pkg in desc_lower for pkg in _stack_lower):
                    _uc_skill = content
                    console.print(f"[dim cyan][explorer] loaded use case skill: {uc_name}[/dim cyan]")
                    break

        system_prompt = EXPLORER_SYSTEM_PROMPT
        if _base_skill:
            system_prompt = _base_skill + "\n\n---\n\n" + system_prompt
        if _uc_skill:
            system_prompt += "\n\n--- Use Case Context ---\n\n" + _uc_skill

        feedback = state.get("orchestrator_feedback", "")
        if feedback:
            context_parts.append(f"\nOrchestrator feedback -- address these issues:\n{feedback}")

        human_message = "\n\n".join(context_parts)

        console.print(Panel(
            f"[bold]Tasks:[/bold] {len(tasks)}\n"
            f"[bold]Findings:[/bold] {len(findings)}\n"
            f"[bold]Engine:[/bold] {engine}",
            title="[bold cyan]Explorer Starting[/bold cyan]",
            border_style="cyan",
        ))

        # Initialize LLM with tool binding
        llm = ChatOpenAI(
            model=os.getenv("CODER_MODEL_NAME", os.getenv("MODEL_NAME", "claudesonnet46")),
        )
        llm_with_tools = llm.bind_tools(EXPLORER_TOOLS)

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_message),
        ]

        # ReAct loop
        # LLM calls are sync (blocking), tool calls go through MCP async session.
        # We run LLM in a thread to avoid blocking the event loop.
        max_iterations = 100
        exploration_log = []
        iteration = 0

        _MAX_TOOL_RESULT_CHARS = 8_000  # cap per tool result added to messages
        _CONTEXT_WINDOW        = 20     # message slots kept beyond system + human

        for iteration in range(max_iterations):
            console.print(f"\n[dim yellow][explorer] iteration {iteration + 1}/{max_iterations}[/dim yellow]")

            # Trim context window: keep system + human + last _CONTEXT_WINDOW messages.
            # Scan forward past any leading ToolMessages to avoid orphaned tool results.
            if len(messages) > 2 + _CONTEXT_WINDOW:
                tail = messages[-_CONTEXT_WINDOW:]
                start = next((i for i, m in enumerate(tail) if not isinstance(m, ToolMessage)), 0)
                messages = messages[:2] + tail[start:]
                console.print(f"[dim yellow][explorer] context trimmed to {len(messages)} messages[/dim yellow]")

            # Run LLM call in a thread (it's sync/blocking)
            _t0 = time.time()
            response = await asyncio.to_thread(llm_with_tools.invoke, messages)
            _latency_s = round(time.time() - _t0, 2)
            _usage = extract_usage(response)
            _model_name = getattr(llm, "model_name", None) or os.getenv(
                "CODER_MODEL_NAME", os.getenv("MODEL_NAME", ""))
            tracer.log_llm_call(
                "explorer", _model_name,
                [message_to_dict(m) for m in messages],
                response.content if hasattr(response, "content") else str(response),
                tool_calls=response.tool_calls or [],
                input_tokens=_usage["input_tokens"], output_tokens=_usage["output_tokens"],
                total_tokens=_usage["total_tokens"], latency_s=_latency_s, attempt=iteration + 1,
            )
            messages.append(response)

            usage = extract_usage(response)
            if usage:
                tracer.log_token_usage("explorer", usage["input_tokens"],
                                       usage["output_tokens"], usage["total_tokens"],
                                       model=getattr(llm, "model_name", ""))

            if not response.tool_calls:
                console.print(Panel(
                    response.content[:3000] if response.content else "(no content)",
                    title="[bold green]Explorer Complete[/bold green]",
                    border_style="green",
                ))
                break

            mcp_broken = False
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_id = tool_call["id"]

                console.print(f"[dim cyan][explorer] calling tool: {tool_name}({json.dumps(tool_args, indent=2)[:200]})[/dim cyan]")

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
                    console.print(f"[bold red][explorer] {tool_name} timed out -- skipping[/bold red]")
                except (BrokenPipeError, ConnectionError, EOFError) as e:
                    tool_result = json.dumps({
                        "error": f"MCP connection lost: {e}",
                        "status": "connection_lost",
                    })
                    console.print(f"[bold red][explorer] MCP connection lost -- ending exploration[/bold red]")
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
                console.print(f"[{color}][explorer] {tool_name} -> {display_status}[/{color}]")

                # Log to trace (full result, not truncated -- needed for debugging failed runs)
                tracer.log_tool_call("explorer", tool_name, tool_args,
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
                console.print("[bold yellow][explorer] MCP connection lost -- ending with partial results[/bold yellow]")
                break

        else:
            console.print("[bold red][explorer] hit max iterations limit[/bold red]")

        # Cleanup MCP server
        console.print("[dim cyan][explorer] cleaning up MCP server...[/dim cyan]")
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
            f"Explorer completed: {total_calls} tool calls, "
            f"{successes} succeeded, {failures} failed, "
            f"{iteration + 1} iterations"
        )
        console.print(f"[dim cyan][explorer] {summary}[/dim cyan]")

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

        tracer.log_agent_output("explorer", {
            "total_tool_calls": total_calls,
            "successes": successes,
            "failures": failures,
            "iterations": iteration + 1,
        })
        tracer.log_agent_end("explorer")

        return {
            "exploration_log": exploration_log,
            "current_step": "explorer_complete",
        }

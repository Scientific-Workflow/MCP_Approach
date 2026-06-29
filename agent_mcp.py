"""
MAW Single-Agent Pipeline (Condition C)

One agent works through a single, continuous, growing conversation in three
phases: read the paper and decide what to build (planning), install the
decided stack (deterministic, no LLM call), then execute every task via
MCP tool calls against a workflow-engine server (execution). Tool-calling is
only available in the execution phase -- planning is structured-output only,
and there is no separate approval step before installing.

This repo exists solely to run this single-agent variant -- Condition C of
the ablation in maw_evaluation_plan.md. The sibling repo MCP_Approach runs
the four-role orchestrator/planner/installer/explorer pipeline for
conditions A and B.

Usage:
    python agent_mcp.py --paper 1 --combination b --goal "Reproduce this workflow..."
    python agent_mcp.py --paper YildizO_RAPIDS.pdf --combination a --goal "..."

--combination is required: a=PDF+Image+Desc, b=PDF+Desc, c=Image+Desc, d=Desc Only
(labels the planner inputs actually used this run; see run_archiver.py)
"""

import os
import base64
import json
import mimetypes
import re
import subprocess
import sys
import time
import warnings
from datetime import datetime
from typing import Annotated, Sequence
from typing_extensions import TypedDict
from pydantic import BaseModel
from pypdf import PdfReader
warnings.filterwarnings("ignore", module="pypdf")
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from mcp_explorer import run_execution_loop_sync
from trace_logger import tracer, extract_usage, message_to_dict
from run_archiver import archive_run

load_dotenv()

console = Console()


# __ LLM ______________________________________________________________________
model = ChatOpenAI(model=os.getenv("MODEL_NAME", "claudesonnet46"))


# __ Agent State _______________________________________________________________

class AgentState(TypedDict):
    messages:              Annotated[Sequence[BaseMessage], add_messages]
    goal:                  str
    pdf_path:              str
    literature_findings:   list[str]
    stack_decision:        list[str]
    tasks:                 list[str]
    exploration_log:       list[dict]       # execution-phase tool call records
    selected_data_files:   list[str]        # filenames chosen from data/ at startup
    requirements_content:  str
    image_path:            str              # path to user-uploaded image for planning (optional)
    current_step:          str
    engine:                str              # workflow engine: "parsl", "pycompss", etc.
    env:                   str              # execution environment: "local" or "hpc"


# __ Pydantic Schemas __________________________________________________________

class PlanOutput(BaseModel):
    literature_findings: list[str]
    stack_decision:      list[str]
    tasks:               list[str]
    skill_requests:      list[str] = []


# __ Agent Prompt ______________________________________________________________

SINGLE_AGENT_SYSTEM_PROMPT = """\
Your agent skill file contains your full operating instructions. Follow them.

You work through this task in three phases, in a single continuous conversation:

1. PLANNING -- you'll be given the paper text and a goal. Respond with ONLY a
   valid JSON object with exactly these keys:
   - literature_findings: list[str] -- specific, quantitative facts extracted from the paper
   - stack_decision:      list[str] -- packages to install into the local venv
   - tasks:               list[str] -- ordered, Python-API-level implementation steps
   - skill_requests:      list[str] -- skill paths to load (first call only; empty on subsequent calls)
   No markdown, no code fences, no explanation outside the JSON. No tools are available
   in this phase -- your stack_decision is final, there is no separate approval step.

2. INSTALL -- handled automatically from your stack_decision, no action needed from you.
   You'll see a report of what was installed before the next phase starts.

3. EXECUTION -- you'll be given tools and the task list. Call tools to execute every
   task, observing results and adapting as you go. There is no separate reviewer to
   tell you when to stop: when every task is done (or deliberately skipped, with
   justification), stop calling tools and give a final summary.

IMPORTANT CONSTRAINTS ON TASKS:
- Do NOT include tasks to reproduce performance benchmarks, scaling plots, or timing
  comparisons from the paper unless the environment knowledge confirms the resources exist.
- Do NOT include tasks that fabricate or simulate fake benchmark data to mimic the
  paper's performance results.
- DO include tasks that reproduce the actual scientific computation (simulation,
  analysis, visualization) using data generated by the workflow itself.
- All visualizations must use data produced by the workflow, not hardcoded values
  from the paper.
- Follow the environment knowledge injected into your context (local or HPC) for
  what parallelism, MPI, and job launcher commands are appropriate.
\
"""


# __ Project layout (injected into context) ____________________________________

PROJECT_LAYOUT = """\
Repo directory tree -- the repo root is mapped to /app/ at runtime:

/app/                                  <- repo root
+-- agent_mcp.py                       <- single-agent pipeline + graph
+-- mcp_explorer.py                    <- MCP tool definitions + session/loop plumbing
+-- servers/                           <- MCP server backends, one per workflow engine
|   +-- parsl_server.py
|   +-- pycompss_server.py
|   +-- adios_server.py
+-- requirements.txt
+-- .env
+-- data/
|   +-- in.watbox                      <- LAMMPS input script
|   +-- data.init                      <- LAMMPS initial atom positions
|   +-- AW.tersoff                     <- LAMMPS force field parameters
+-- Literature/
|   +-- *.pdf
+-- images/
|   +-- *.png / *.jpg                  <- optional planning diagrams/figures
+-- builds/
|   +-- requirements.txt               <- venv package list, written during the install phase
+-- work/                              <- execution-phase output goes here
    +-- run0/                          <- default working directory
\
"""


# __ Structured output helper __________________________________________________

def _invoke_structured(llm, schema, messages, agent_name, retries=5):
    """Call llm and parse the response as schema, tolerating preamble text before the JSON block."""
    import json as _json, re as _re
    last_err = None
    model_name = getattr(llm, "model_name", None) or os.getenv("MODEL_NAME", "")
    msg_dicts = [message_to_dict(m) for m in messages]
    for attempt in range(retries):
        _t0 = time.time()
        response = llm.invoke(messages)
        latency_s = round(time.time() - _t0, 2)
        text = response.content if hasattr(response, "content") else str(response)
        usage = extract_usage(response)
        tracer.log_llm_call(
            agent_name, model_name, msg_dicts, text,
            input_tokens=usage["input_tokens"], output_tokens=usage["output_tokens"],
            total_tokens=usage["total_tokens"], latency_s=latency_s, attempt=attempt + 1,
        )
        match = _re.search(r'\{.*\}', text, _re.DOTALL)
        if not match:
            last_err = ValueError(f"No JSON object found in model response:\n{text[:500]}")
            console.print(f"[yellow][_invoke_structured] attempt {attempt+1}: no JSON found, retrying...[/yellow]")
            continue
        try:
            return schema.model_validate(_json.loads(match.group(0)))
        except (_json.JSONDecodeError, Exception) as e:
            last_err = e
            console.print(f"[yellow][_invoke_structured] attempt {attempt+1}: parse error ({e}), retrying...[/yellow]")
    raise last_err


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

_ENV_KNOWLEDGE = {
    "local": "knowledge/local",
    "hpc":   "knowledge/lcrc",
}

def _slugify(path: str) -> str:
    """Turn a file path into a stable run-metadata id, e.g. for paper_id."""
    base = os.path.splitext(os.path.basename(path))[0] if path else "no_paper"
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", base).strip("_")
    return slug or "no_paper"

def _list_skills(folder: str) -> list:
    """List available names in skills/<folder>/: subdirectory names AND .SKILL.md base names."""
    d = os.path.join(_SKILLS_ROOT, folder)
    if not os.path.isdir(d):
        return []
    results = []
    for name in os.listdir(d):
        if os.path.isdir(os.path.join(d, name)):
            results.append(name)
        elif name.endswith(".SKILL.md"):
            results.append(name[: -len(".SKILL.md")])
    return results


# __ Install helper (phase 2 -- deterministic, no LLM call, no tools) __________

def _install_stack(stack: list[str]) -> tuple[bool, str]:
    """Write builds/requirements.txt from `stack` and pip install it into the
    current venv. No approval gate: the agent's own phase-1 decision is final."""
    build_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "builds")
    os.makedirs(build_dir, exist_ok=True)
    requirements_path = os.path.join(build_dir, "requirements.txt")

    packages = [pkg for pkg in stack if pkg]
    content = ("\n".join(packages) + "\n") if packages else ""
    with open(requirements_path, "w") as f:
        f.write(content)

    if not packages:
        console.print("[dim cyan][install] no packages to install[/dim cyan]")
        return True, "No packages in stack_decision -- nothing to install."

    console.print(f"[dim cyan][install] pip installing {len(packages)} packages...[/dim cyan]")
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install"] + packages,
        capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        console.print(f"[yellow][install] pip stderr:\n{proc.stderr[-2000:]}[/yellow]")
        return False, (
            f"Install FAILED for: {', '.join(packages)}\n"
            f"pip stderr (tail):\n{proc.stderr[-2000:]}"
        )
    console.print("[dim cyan][install] packages ready[/dim cyan]")
    return True, f"Installed {len(packages)} packages successfully: {', '.join(packages)}"


# __ Single Agent Node _________________________________________________________

def single_agent(state: AgentState) -> dict:
    try:
        console.print("\n[dim cyan][single_agent] starting run...[/dim cyan]")
        tracer.log_agent_start("single_agent", {"engine": state.get("engine", "parsl")})
        tracer.log_agent_input("single_agent", {"pdf_path": state["pdf_path"], "goal": state["goal"]})

        env = state.get("env", "local")
        engine = state.get("engine", "parsl")
        data_files = state.get("selected_data_files", [])

        # __ Build the one system prompt for the whole run __
        _base = _read_skill("agents/single_agent")
        _env_kn = _read_skill(_ENV_KNOWLEDGE.get(env, "knowledge/local"))
        _env_section = f"\n\n=== Environment Knowledge ===\n{_env_kn}" if _env_kn else ""
        _uc = _list_skills("use_cases")
        _sys = _list_skills("systems")
        _index = (f"\n\nAvailable skill contexts (set in skill_requests to load):"
                  f"\n  use_cases: {_uc}  -- request as \"use_cases/<name>/single_agent\""
                  f"\n  systems:   {_sys}  -- request as \"systems/<name>\"") if (_uc or _sys) else ""
        system_prompt = _base + _env_section + _index + "\n\n---\n\n" + SINGLE_AGENT_SYSTEM_PROMPT + "\n\n" + PROJECT_LAYOUT

        messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]

        # __ Phase 1: planning __
        console.print("[dim cyan][single_agent] phase 1/3 -- planning...[/dim cyan]")
        reader = PdfReader(state["pdf_path"])
        pdf_text = "\n".join(page.extract_text() for page in reader.pages if page.extract_text())
        console.print(f"[dim cyan][single_agent] loaded {len(reader.pages)} pages[/dim cyan]")

        _data_section = (f"\n\nAvailable input data files (in /app/data/):\n" +
                         "\n".join(f"  - {f}" for f in data_files)) if data_files else ""
        plan_text = f"Goal: {state['goal']}{_data_section}\n\nPaper:\n{pdf_text}"

        # Build human message -- multimodal if an image was provided
        if state.get("image_path"):
            console.print("[dim cyan][single_agent] loading image...[/dim cyan]")
            with open(state["image_path"], "rb") as _f:
                _img_bytes = _f.read()
            _b64 = base64.b64encode(_img_bytes).decode()
            _mime, _ = mimetypes.guess_type(state["image_path"])
            _mime = _mime or "image/png"
            plan_msg = HumanMessage(content=[
                {"type": "image_url", "image_url": {"url": f"data:{_mime};base64,{_b64}"}},
                {"type": "text", "text": plan_text},
            ])
            console.print(f"[dim cyan][single_agent] image loaded ({_mime}, {len(_img_bytes)//1024}KB)[/dim cyan]")
        else:
            plan_msg = HumanMessage(content=plan_text)

        messages.append(plan_msg)
        plan: PlanOutput = _invoke_structured(model, PlanOutput, messages, "single_agent")
        messages.append(AIMessage(content=json.dumps(plan.model_dump())))

        # Two-pass: if sub-skills requested, load them and re-invoke once, in-conversation
        if plan.skill_requests:
            _sub = "\n\n".join(filter(None, (_read_skill(r) for r in plan.skill_requests)))
            if _sub:
                messages.append(HumanMessage(
                    content=f"Loaded skills:\n{_sub}\n\nRespond again with the same JSON "
                             f"shape; do not set skill_requests this time."))
                plan = _invoke_structured(model, PlanOutput, messages, "single_agent")
                messages.append(AIMessage(content=json.dumps(plan.model_dump())))

        # ADIOS2 is the data-I/O layer for this engine -- don't leave it to LLM judgment
        # whether to request it. Without it, every task silently falls back to numpy I/O
        # (engine="adios2-fallback") with no real ADIOS2 transport ever exercised.
        if engine == "adios" and "adios2" not in plan.stack_decision:
            plan.stack_decision.append("adios2")

        console.print(f"[dim cyan][single_agent] produced {len(plan.tasks)} tasks[/dim cyan]")
        findings_str = "\n".join(f"  [cyan]*[/cyan] {f}" for f in plan.literature_findings)
        stack_str    = "\n".join(f"  [cyan]*[/cyan] {s}" for s in plan.stack_decision)
        tasks_str    = "\n".join(f"  [bold]{i+1}.[/bold] {t}" for i, t in enumerate(plan.tasks))
        console.print(Panel(
            f"[bold]Literature Findings[/bold]\n{findings_str}\n\n"
            f"[bold]Stack[/bold]\n{stack_str}\n\n"
            f"[bold]Tasks[/bold]\n{tasks_str}",
            title="[bold green]Planning Phase Output[/bold green]",
            border_style="green",
        ))
        tracer.log_agent_output("single_agent", {
            "phase": "planning",
            "findings_count": len(plan.literature_findings),
            "stack": plan.stack_decision,
            "tasks_count": len(plan.tasks),
        })

        # __ Phase 2: install (deterministic, no LLM call, no tools) __
        console.print("[dim cyan][single_agent] phase 2/3 -- installing stack...[/dim cyan]")
        install_ok, install_report = _install_stack(plan.stack_decision)
        messages.append(HumanMessage(content=f"Install report:\n{install_report}"))
        tracer.log_agent_output("single_agent", {
            "phase": "install", "ok": install_ok, "report": install_report,
        })

        # __ Phase 3: execution (tools unlock here) __
        console.print("[dim cyan][single_agent] phase 3/3 -- executing tasks...[/dim cyan]")

        # Auto-detect a use-case skill the same way the old explorer did, now matched
        # against use_cases/<name>/single_agent.SKILL.md instead of .../explorer.SKILL.md.
        _stack_lower = [p.lower() for p in plan.stack_decision]
        _uc_skill = ""
        _uc_dir = os.path.join(_SKILLS_ROOT, "use_cases")
        if os.path.isdir(_uc_dir):
            for uc_name in os.listdir(_uc_dir):
                content = _read_skill(f"use_cases/{uc_name}/single_agent")
                if not content:
                    continue
                desc_lower = content[:500].lower()
                if any(pkg in desc_lower for pkg in _stack_lower):
                    _uc_skill = content
                    console.print(f"[dim cyan][single_agent] loaded use case skill: {uc_name}[/dim cyan]")
                    break

        exec_parts = []
        if data_files:
            exec_parts.append("Available input data files (in /app/data/):\n" +
                              "\n".join(f"  - {f}" for f in data_files))
        if plan.literature_findings:
            exec_parts.append("Literature findings:\n" +
                              "\n".join(f"  - {f}" for f in plan.literature_findings))
        if plan.stack_decision:
            exec_parts.append(f"Software stack in venv: {', '.join(plan.stack_decision)}")
        if plan.tasks:
            exec_parts.append("Tasks to execute:\n" +
                              "\n".join(f"  {i+1}. {t}" for i, t in enumerate(plan.tasks)))
        if _uc_skill:
            exec_parts.append("=== Use Case Context ===\n" + _uc_skill)

        messages.append(HumanMessage(content="\n\n".join(exec_parts)))

        messages, exploration_log = run_execution_loop_sync(messages, engine, agent_name="single_agent")

        total = len(exploration_log)
        successes = sum(1 for e in exploration_log if e.get("succeeded", False))
        tracer.log_agent_output("single_agent", {
            "phase": "execution", "total_tool_calls": total, "successes": successes,
            "failures": total - successes,
        })
        tracer.log_agent_end("single_agent")

        return {
            "messages":             messages,
            "literature_findings":  plan.literature_findings,
            "stack_decision":       plan.stack_decision,
            "tasks":                plan.tasks,
            "requirements_content": "\n".join(plan.stack_decision),
            "exploration_log":      exploration_log,
            "current_step":         "single_agent_complete",
        }
    except Exception as e:
        console.print(f"[red][single_agent] ERROR: {e}[/red]")
        raise


# __ Graph _____________________________________________________________________

graph = StateGraph(AgentState)
graph.add_node("single_agent", single_agent)
graph.set_entry_point("single_agent")
graph.add_edge("single_agent", END)

app = graph.compile()


# __ Run _______________________________________________________________________

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MAW -- Single-Agent Pipeline (Condition C)")
    parser.add_argument("--paper", type=str, help="Path to the PDF paper or paper index (1-based)")
    parser.add_argument("--image", type=str, help="Path to image file (diagram/figure) to use for planning")
    parser.add_argument("--goal", type=str, help="Goal for the workflow")
    parser.add_argument("--engine", type=str, default="parsl",
                        choices=["parsl", "pycompss", "adios"],
                        help="Workflow engine to use (default: parsl)")
    parser.add_argument("--env", type=str, default="local",
                        choices=["local", "hpc"],
                        help="Execution environment: local (default) or hpc (LCRC/PBS)")
    parser.add_argument("--trial", type=int, default=1,
                        help="Trial number for repeated (paper, trial) runs (default: 1)")
    parser.add_argument("--domain", type=str, default="",
                        help="Paper domain label, e.g. molecular_nucleation (optional)")
    parser.add_argument("--combination", type=str, required=True,
                        choices=["a", "b", "c", "d"],
                        help="Planner input combination: a=PDF+Image+Desc, "
                             "b=PDF+Desc, c=Image+Desc, d=Desc Only")
    args = parser.parse_args()

    console.print(Panel(f"[bold blue]MAW -- Single-Agent Pipeline (Condition C)[/bold blue]\n[dim]Engine: {args.engine} | Env: {args.env}[/dim]", border_style="blue"))

    lit_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Literature")
    os.makedirs(lit_dir, exist_ok=True)

    pdfs = [f for f in os.listdir(lit_dir) if f.lower().endswith(".pdf")]
    if not pdfs:
        console.print("[red]No PDFs found in the Literature/ folder. Add a paper and try again.[/red]")
        raise SystemExit(1)

    console.print("\n[bold]Available papers:[/bold]")
    for i, name in enumerate(pdfs, 1):
        console.print(f"  {i}. {name}")

    # Handle paper selection
    if args.paper:
        choice = args.paper
        try:
            pdf_path = os.path.join(lit_dir, pdfs[int(choice) - 1])
        except (ValueError, IndexError):
            pdf_path = os.path.join(lit_dir, choice)
            if not os.path.isfile(pdf_path):
                console.print(f"[red]Paper not found: {choice}[/red]")
                raise SystemExit(1)
    else:
        choice = input("\nSelect a paper by number: ").strip()
        try:
            pdf_path = os.path.join(lit_dir, pdfs[int(choice) - 1])
        except (ValueError, IndexError):
            console.print("[red]Invalid selection.[/red]")
            raise SystemExit(1)

    console.print(f"[dim]Selected: {os.path.basename(pdf_path)}[/dim]")

    # Handle image selection
    _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    images_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
    os.makedirs(images_dir, exist_ok=True)

    if args.image:
        image_path = args.image if os.path.isabs(args.image) else os.path.join(images_dir, args.image)
        if not os.path.isfile(image_path):
            console.print(f"[red]Image not found: {args.image}[/red]")
            raise SystemExit(1)
        console.print(f"[dim]Image: {os.path.basename(image_path)}[/dim]")
    else:
        images = sorted(
            f for f in os.listdir(images_dir)
            if os.path.splitext(f)[1].lower() in _IMAGE_EXTS
        )
        if not images:
            image_path = ""
        else:
            console.print("\n[bold]Available images:[/bold]")
            for i, name in enumerate(images, 1):
                console.print(f"  {i}. {name}")
            console.print(f"  0. Skip -- no image")
            choice = input("\nSelect an image by number (or 0 to skip): ").strip()
            if choice == "0" or not choice:
                image_path = ""
                console.print("[dim]No image selected.[/dim]")
            else:
                try:
                    image_path = os.path.join(images_dir, images[int(choice) - 1])
                    console.print(f"[dim]Selected: {os.path.basename(image_path)}[/dim]")
                except (ValueError, IndexError):
                    console.print("[red]Invalid selection -- no image will be used.[/red]")
                    image_path = ""

    # Handle data file selection
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    all_data_files = sorted(f for f in os.listdir(data_dir) if os.path.isfile(os.path.join(data_dir, f))) if os.path.isdir(data_dir) else []

    if not all_data_files:
        console.print("[yellow]No files found in data/ -- the agent will have no input data.[/yellow]")
        selected_data_files = []
    else:
        console.print("\n[bold]Available data files:[/bold]")
        for i, name in enumerate(all_data_files, 1):
            console.print(f"  {i}. {name}")
        raw = input("\nSelect files by number (comma-separated, or Enter for all): ").strip()
        if not raw:
            selected_data_files = all_data_files
            console.print("[dim]Using all data files.[/dim]")
        else:
            selected_data_files = []
            for token in raw.split(","):
                token = token.strip()
                try:
                    selected_data_files.append(all_data_files[int(token) - 1])
                except (ValueError, IndexError):
                    console.print(f"[yellow]Skipping invalid selection: {token!r}[/yellow]")
            if not selected_data_files:
                console.print("[yellow]No valid files selected -- using all.[/yellow]")
                selected_data_files = all_data_files
            else:
                console.print(f"[dim]Selected: {', '.join(selected_data_files)}[/dim]")

    # Handle goal
    if args.goal:
        goal = args.goal
    else:
        goal = input("\nDescribe your goal for this workflow: ").strip()

    if not goal:
        console.print("[red]Goal cannot be empty.[/red]")
        raise SystemExit(1)

    runs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs")
    os.makedirs(runs_dir, exist_ok=True)
    _run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    initial_state = {
        "messages":              [],
        "goal":                  goal,
        "pdf_path":              pdf_path,
        "literature_findings":   [],
        "stack_decision":        [],
        "tasks":                 [],
        "exploration_log":       [],
        "selected_data_files":   selected_data_files,
        "requirements_content":  "",
        "image_path":            image_path,
        "current_step":          "start",
        "engine":                args.engine,
        "env":                   args.env,
    }

    trace_path = os.path.join(runs_dir, _run_id + "_trace.json")

    tracer.reset()   # before you run it, reset the tracer to clear any previous runs from the dashboard
    tracer.start_run(
        run_id=_run_id,
        condition="C",
        combination=args.combination,
        trial=args.trial,
        paper_id=_slugify(pdf_path) if pdf_path else "no_paper",
        paper_path=pdf_path,
        domain=args.domain,
        framework=args.engine,
        env=args.env,
        goal=goal,
        model=os.getenv("MODEL_NAME", "claudeopus48"),
    )

    try:
        app.invoke(initial_state) # write the node functions to log to the tracer, and then invoke the graph with the initial state
        tracer.finalize_run("completed")
    except Exception as e:
        import traceback as _traceback
        tracer.log_run_error(type(e).__name__, str(e), _traceback.format_exc())
        tracer.finalize_run("failed")
        tracer.save(trace_path)
        console.print(f"[red]Run failed: {e}[/red]")
        console.print(f"[dim]Trace saved (partial): {trace_path}[/dim]")
        archive_path = archive_run(tracer.run_metadata, trace_path)
        if archive_path:
            console.print(f"[dim]Run archived (failed): {archive_path}[/dim]")
        raise

    # Save trace
    tracer.save(trace_path)  #save the trace to a file for later analysis
    console.print(f"[dim]Trace saved: {trace_path}[/dim]")

    archive_path = archive_run(tracer.run_metadata, trace_path)
    if archive_path:
        console.print(f"[dim]Run archived: {archive_path}[/dim]")

    # Print interaction summary
    summary = tracer.get_summary()
    console.print(f"\n[bold]Trace Summary:[/bold]")
    console.print(f"  Agents: {', '.join(summary['agents_involved'])}")
    console.print(f"  Tool calls: {summary['tool_calls']} ({summary['tool_successes']} succeeded)")
    console.print(f"  Total time: {summary['total_duration_s']}s")

################################################################### TOKEN USAGE SUMMARY (CHECK runs folder: xxxxxxxx_trace.json) ##################################################################)
    # Print token usage
    total_in = summary.get('total_input_tokens', 0)
    total_out = summary.get('total_output_tokens', 0)
    if total_in or total_out:
        console.print(f"\n[bold]Token Usage:[/bold]")
        console.print(f"  Input tokens:  {total_in:,}")
        console.print(f"  Output tokens: {total_out:,}")
        console.print(f"  Total tokens:  {total_in + total_out:,}")
        tokens_by_agent = summary.get('tokens_by_agent', {})
        if tokens_by_agent:
            console.print(f"  By agent:")
            for agent, count in sorted(tokens_by_agent.items()):
                console.print(f"    {agent}: {count:,}")

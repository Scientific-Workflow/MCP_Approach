# PROJECT_CONTEXT.md
# MAW -- Multi-Agent Workflow (MCP Approach)

## Code Agent Prompt

You are a senior code and development assistant. Your job is to aid in development of certain features, brainstorm ideas with your users, and be a strict, realistic, and level headed coding agent. Do not implement, change, or manipulate the repository without the permission of the user.


## Project Vision

This is the **MCP (Model Context Protocol) approach** to the MAW agentic framework. It is a
parallel, independent implementation alongside the original artifact approach.

Both approaches share the same goal: automate end-to-end reproduction of scientific workflows
described in published research papers. The key difference:

**The workflow engine (Parsl, PyCOMPSs, etc.) is exposed as an MCP server that the agent
calls interactively, rather than generating standalone workflow scripts.**

| | Artifact Approach | MCP Approach (this repo) |
|---|---|---|
| Code generation | codegen generates complete workflow.py | No script generation |
| Execution | executor runs workflow.py all at once | explorer calls MCP server tools step by step |
| Error handling | Regenerate entire script, re-run | Fix only the failing step, retry |
| Workflow engine | Parsl embedded in generated script | Parsl exposed as MCP server |
| Engine swappable | No (hardcoded in codegen) | Yes (swap MCP server implementation) |

---

## Architecture (3 layers)

```
Agent Layer (LangGraph)
  Orchestrator -> Planner -> Installer -> Explorer -> End
                                            |
                                            | MCP protocol (JSON-RPC over stdio)
                                            v
Workflow Engine Layer (MCP Server)
  servers/parsl_server.py    -- Parsl MCP Server
  servers/pycompss_server.py -- (future) PyCOMPSs MCP Server
  servers/adios_server.py    -- (future) ADIOS MCP Server
                                            |
                                            | subprocess (venv)
                                            v
Execution Layer (Local Python Venv)
  Scientific packages installed in the local venv
  LAMMPS, OVITO, Parsl, numpy, matplotlib, etc.
```

---

## Repo Layout

```
MCP_Approach/
+-- agent_mcp.py                  <- Main entry point (orchestrator + planner + installer + graph)
+-- mcp_tools.py                  <- MCP client (connects to MCP server, wraps tool calls)
+-- mcp_explorer.py               <- Explorer agent (ReAct loop calling MCP server tools)
+-- run_archiver.py               <- Snapshots work/run0 + trace.json after every run, then wipes run0
+-- trace_logger.py / trace_schema.py  <- Per-run tracing (LLM calls, tool calls, routing, metadata)
+-- servers/
|   +-- __init__.py
|   +-- parsl_server.py           <- Parsl Workflow MCP Server
+-- requirements.txt              <- Agent dependencies (includes mcp SDK)
+-- .env                          <- API keys and model config (Argo endpoint)
+-- PROJECT_CONTEXT.md            <- This file
+-- data/
|   +-- in.watbox                 <- LAMMPS input script
|   +-- data.init                 <- LAMMPS initial atom positions
|   +-- AW.tersoff                <- LAMMPS force field parameters
+-- Literature/
|   +-- YildizO_RAPIDS.pdf        <- Primary paper
|   +-- cise-article-YILDIZ.pdf   <- Secondary paper
+-- builds/
|   +-- requirements.txt          <- Workflow venv package list
+-- work/                         <- Workflow runtime output
+-- runs/                         <- Run logs (JSONL)
+-- skills/
    +-- agents/
    |   +-- orchestrator.SKILL.md <- Orchestrator routing rules
    |   +-- planner.SKILL.md      <- Planner behavioral spec
    |   +-- installer.SKILL.md    <- Installer behavioral spec
    |   +-- explorer.SKILL.md     <- Explorer behavioral spec
    +-- knowledge/
    |   +-- workflow_context.SKILL.md
    +-- systems/
    |   +-- parsl.SKILL.md
    |   +-- pycompss.SKILL.md
    |   +-- adios.SKILL.md
    +-- use_cases/
        +-- molecular_nucleation/
            +-- orchestrator.SKILL.md
            +-- planner.SKILL.md
            +-- installer.SKILL.md
            +-- explorer.SKILL.md
```

---

## Agent Pipeline

```
orchestrator --> planner    --> orchestrator
             --> installer  (phase 1: read requirements.txt | phase 2: pip install)
             --> explorer   (connects to MCP server, ReAct loop with tool calls)
             --> END
```

---

## Run Archiving

`work/run0/` is a single fixed working directory shared by every run -- the
next run overwrites whatever the previous one left there. `run_archiver.py`
snapshots it automatically: right after the trace is saved (on both success
and failure paths in `agent_mcp.py`), it copies `work/run0/` and the run's
`trace.json` into a permanent folder **outside this repo**, then clears
`run0` for the next run.

Archive location: `/gpfs/fs1/home/jacob.oh/SULI/TEST_RUNS/mcp_approach/<folder>/`
(a `single_approach/` sibling is reserved for when the Artifact approach gets
the same treatment). Each `<folder>` contains `trace.json` and a `work/`
subfolder with everything that was in `run0`.

Folder naming: `<date>__<usecase>__<engine>__<condition>__<combination>__trial<trial>`

- `date` -- `YYYYMMDD` from the run's `run_id`
- `usecase` -- `--domain` if passed, else falls back to the paper's slug
- `engine` -- `--engine` (parsl/pycompss/adios)
- `condition` -- `--condition` (A/B/C, the skills/architecture ablation)
- `combination` -- **new required `--combination {a,b,c,d}` flag**: labels
  which planner inputs were actually used this run --
  a=PDF+Image+Desc, b=PDF+Desc, c=Image+Desc, d=Desc Only.
  (`--paper` is currently mandatory, so only a/b are reachable today; c/d
  become usable if paper selection is ever made optional.)
- `trial` -- `--trial`

Name collisions get a Windows-style ` (2)`, ` (3)`, ... suffix rather than
being overwritten.

---

## MCP Server Tools (exposed by servers/parsl_server.py)

| Tool | Description |
|---|---|
| submit_task | Submit Python code for execution via Parsl with dependency tracking |
| submit_shell_task | Run shell commands via the workflow engine |
| get_task_status | Check task status (pending/running/completed/failed) |
| get_task_result | Get full stdout/stderr from a completed task |
| list_tasks | List all submitted tasks and their statuses |
| install_package | pip install a package into the local venv |
| check_package | Verify a package is installed |
| list_files | List files in a directory |
| read_file | Read file contents |
| cleanup | Stop and clean up the MCP server process |

---

## How to Swap Workflow Engines

To add a new engine (e.g. PyCOMPSs):

1. Create `servers/pycompss_server.py` implementing the same tool interface
2. Add `"pycompss"` to the ENGINE_SERVERS dict in `mcp_tools.py`
3. Add `"pycompss"` to the `--engine` choices in `agent_mcp.py`
4. Run with `python agent_mcp.py --engine pycompss --paper 1 --combination b --goal "..."`

The explorer, orchestrator, planner, and installer are completely unchanged.

---

## Running the System

```bash
# With Parsl engine (default). --combination is required (a/b/c/d, see Run Archiving above)
python agent_mcp.py --paper 1 --combination b --goal "Reproduce this workflow using LAMMPS and OVITO"

# Specify engine explicitly
python agent_mcp.py --engine parsl --paper 1 --combination b --goal "..."
```

---

## Key Design Decisions

1. **MCP server as separate process**: The workflow engine MCP server runs as a subprocess
   started by the explorer. Communication is via stdio (JSON-RPC). This cleanly separates
   the agent logic from the engine logic.

2. **Persistent venv**: The MCP server runs as a single long-lived subprocess. Packages installed via `install_package` persist for the session, and the local venv persists across runs. This is more efficient and allows Parsl to manage state.

3. **skill_updater disabled**: During development, auto-updating skill files is turned off
   to avoid contaminating knowledge with incomplete-code errors.

4. **Engine-agnostic tools**: The MCP tool interface (submit_task, get_status, etc.) is
   the same regardless of backend engine. This enables engine swapping.

---

## Stack & Conventions

- Language: Python 3.11
- Agent framework: LangGraph (StateGraph with conditional edges)
- MCP SDK: mcp >= 1.0.0 (Anthropic's Model Context Protocol)
- LLM backend: Argonne Argo API (OpenAI-compatible endpoint)
- Sandbox: Local Python venv (packages listed in builds/requirements.txt)
- Console output: rich (Panel, color-coded per agent)

# PROJECT_CONTEXT.md
# MAW -- Single-Agent Pipeline (MCP Approach, Condition C)

## Code Agent Prompt

You are a senior code and development assistant. Your job is to aid in development of certain features, brainstorm ideas with your users, and be a strict, realistic, and level headed coding agent. Do not implement, change, or manipulate the repository without the permission of the user.


## Project Vision

This is the **MCP (Model Context Protocol) approach** to the MAW agentic framework. It is a
parallel, independent implementation alongside the original artifact approach.

The goal is the same as the artifact approach: automate end-to-end reproduction of scientific
workflows described in published research papers. The MCP-specific difference:

**The workflow engine (Parsl, PyCOMPSs, ADIOS) is exposed as an MCP server that the agent
calls interactively, rather than generating standalone workflow scripts.**

This repo specifically runs **Condition C** of the MAW ablation (see
`maw_evaluation_plan.md`): one agent does the work that the sibling repo `MCP_Approach` splits
across four roles (orchestrator, planner, installer, explorer), to test whether multi-agent
context-window isolation actually matters. There is no orchestrator here and no per-role
routing -- one agent works through planning, install, and execution in a single, continuous,
growing conversation. Tool-calling is only available during the execution phase.

| | Artifact Approach | MCP Approach, multi-agent (`MCP_Approach`) | MCP Approach, single-agent (this repo) |
|---|---|---|---|
| Code generation | codegen generates complete workflow.py | No script generation | No script generation |
| Execution | executor runs workflow.py all at once | explorer calls MCP server tools step by step | same agent calls MCP server tools step by step, once execution phase starts |
| Decomposition | single script | 4 roles + an orchestrator routing between them | 1 agent, 3 sequential phases, no router |
| Error handling | Regenerate entire script, re-run | Fix only the failing step, retry | Fix only the failing step, retry |
| Engine swappable | No (hardcoded in codegen) | Yes (swap MCP server implementation) | Yes (swap MCP server implementation) |

---

## Architecture (3 layers)

```
Agent Layer (LangGraph, single node)
  single_agent: planning -> install -> execution -> End
                                            |
                                            | MCP protocol (JSON-RPC over stdio),
                                            | execution phase only
                                            v
Workflow Engine Layer (MCP Server)
  servers/parsl_server.py    -- Parsl MCP Server
  servers/pycompss_server.py -- PyCOMPSs MCP Server
  servers/adios_server.py    -- ADIOS MCP Server
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
MCP_Approach_SINGLE/
+-- agent_mcp.py                  <- Single-agent pipeline (3 phases) + trivial 1-node graph
+-- mcp_explorer.py               <- MCP tool definitions + session/ReAct-loop plumbing (execution phase)
+-- servers/
|   +-- __init__.py
|   +-- parsl_server.py           <- Parsl Workflow MCP Server
|   +-- pycompss_server.py        <- PyCOMPSs Workflow MCP Server
|   +-- adios_server.py           <- ADIOS Workflow MCP Server
+-- requirements.txt              <- Agent dependencies (includes mcp SDK)
+-- .env                          <- API keys and model config (Argo endpoint)
+-- PROJECT_CONTEXT.md            <- This file
+-- maw_evaluation_plan.md        <- Ablation design this repo implements Condition C of
+-- data/
|   +-- in.watbox                 <- LAMMPS input script
|   +-- data.init                 <- LAMMPS initial atom positions
|   +-- AW.tersoff                <- LAMMPS force field parameters
+-- Literature/
|   +-- *.pdf
+-- builds/
|   +-- requirements.txt          <- Workflow venv package list, written during the install phase
+-- work/                         <- Workflow runtime output
+-- runs/                         <- Run logs + traces (JSON)
+-- skills/
    +-- agents/
    |   +-- single_agent.SKILL.md <- The one operating manual: planning, install, execution, and how to know you're done
    +-- knowledge/
    |   +-- workflow_context.SKILL.md
    |   +-- local.SKILL.md
    |   +-- lcrc.SKILL.md
    +-- systems/
    |   +-- parsl.SKILL.md
    |   +-- pycompss.SKILL.md
    |   +-- adios.SKILL.md
    +-- use_cases/
        +-- cosmology/
        |   +-- single_agent.SKILL.md
        +-- molecular_nucleation/
            +-- single_agent.SKILL.md
```

---

## Agent Pipeline

```
single_agent:
  phase 1  planning   -- structured output only, no tools (literature_findings, stack_decision, tasks)
  phase 2  install     -- deterministic pip install from stack_decision, no LLM call, no approval gate
  phase 3  execution   -- MCP tool-calling ReAct loop, same growing transcript as phases 1-2
  --> END
```

All three phases run inside one Python function (`single_agent` in `agent_mcp.py`) against one
growing `messages` list -- there is no LangGraph routing between separate nodes, because there
are no separate agents to route between.

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

To add a new engine:

1. Create `servers/<engine>_server.py` implementing the same tool interface
2. Add the engine name to the `ENGINE_SERVERS` dict in `mcp_explorer.py`
3. Add the engine name to the `--engine` choices in `agent_mcp.py`
4. Run with `python agent_mcp.py --engine <engine> --paper 1 --goal "..."`

The single agent's planning logic, install logic, and tool-calling loop are completely
unchanged -- only which MCP server it connects to during the execution phase changes.

---

## Running the System

```bash
# With Parsl engine (default)
python agent_mcp.py --paper 1 --goal "Reproduce this workflow using LAMMPS and OVITO"

# Specify engine explicitly
python agent_mcp.py --engine parsl --paper 1 --goal "..."
```

---

## Key Design Decisions

1. **MCP server as separate process**: The workflow engine MCP server runs as a subprocess
   started when the execution phase begins. Communication is via stdio (JSON-RPC). This
   cleanly separates the agent logic from the engine logic.

2. **Persistent venv**: The MCP server runs as a single long-lived subprocess. Packages installed via `install_package` persist for the session, and the local venv persists across runs. This is more efficient and allows Parsl to manage state.

3. **skill_updater disabled**: During development, auto-updating skill files is turned off
   to avoid contaminating knowledge with incomplete-code errors.

4. **Engine-agnostic tools**: The MCP tool interface (submit_task, get_status, etc.) is
   the same regardless of backend engine. This enables engine swapping.

---

## Stack & Conventions

- Language: Python 3.11
- Agent framework: LangGraph (single-node StateGraph -- kept for CLI/notebook/tracer integration, not for routing)
- MCP SDK: mcp >= 1.0.0 (Anthropic's Model Context Protocol)
- LLM backend: Argonne Argo API (OpenAI-compatible endpoint)
- Sandbox: Local Python venv (packages listed in builds/requirements.txt)
- Console output: rich (Panel, color-coded per phase)

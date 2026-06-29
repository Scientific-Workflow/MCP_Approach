---
name: knowledge/workflow_context
description: >
  Foundational reference for what "workflow" means in the MAW project. Covers the agent
  pipeline, local venv execution model, file layout conventions, and how the system
  differs from traditional HPC workflows.
---

# Workflow Context — MAW Project Reference

What "reproducing a scientific workflow" means in this project and how the system is designed to do it.

---

## What MAW Does

MAW (Multi-Agent Workflow) takes a research paper PDF and a goal, then uses an LLM agent to
automatically:
1. Extract the computational workflow described in the paper
2. Decide what to install and execute via MCP tool calls
3. Execute the code in a local venv via MCP tool calls
4. Return analysis results

The target output is a reproducible, executable workflow — not just a description of what the paper did.

This repo runs **Condition C** of the MAW ablation (one agent, no orchestrator routing between
separate roles) — see `maw_evaluation_plan.md` at the repo root for why.

---

## The Agent Pipeline

```
single_agent:
  planning  phase  (reads PDF → literature_findings, stack_decision, tasks; no tools)
  install   phase  (pip installs packages into the local venv; deterministic, no LLM call)
  execution phase  (executes workflow tasks step by step via MCP tool calls)
  ──▶ END
```

All three phases run in one continuous, growing conversation (one `messages` list) inside a
single Python function — there is no router deciding what runs next, because there's only one
agent and the phase order is fixed.

---

## Local Venv Execution Model

The MAW agent runs directly on the host machine. During the install phase it pip-installs
scientific packages (LAMMPS, OVITO, Parsl, etc.) into the local Python venv. During the
execution phase it submits tasks to a workflow engine MCP server, which executes them using
that same venv.

```
Host machine
└── agent process (single_agent: planning -> install -> execution)
    └── MCP server subprocess (parsl_server.py, pycompss_server.py, or adios_server.py),
        started only for the execution phase
        └── executes tasks in local venv (LAMMPS + OVITO + Parsl installed)
```

**KEY:** Paths like `/app/data/` and `/app/work/run0/` are aliases that the MCP server resolves to the actual repo path on disk using `HOST_REPO_PATH`.

---

## File Layout Convention

```
repo root (HOST_REPO_PATH on disk, aliased as /app/ in skill files)
├── agent_mcp.py               ← the single-agent pipeline (all 3 phases) + trivial 1-node graph
├── mcp_explorer.py            ← MCP tool definitions + session/ReAct-loop plumbing
├── data/                      ← input files (user-controlled, never modified by agents)
│   ├── in.watbox              ← simulation input script
│   ├── data.init              ← initial atom positions
│   └── AW.tersoff             ← force field parameters
├── builds/                    ← installer-generated files
│   └── requirements.txt       ← venv package list
├── work/                      ← simulation output (created at runtime, safe to delete)
│   └── run0/
│       ├── frames/            ← LAMMPS dump files
│       ├── results.csv        ← analysis output
│       └── renders/           ← visualization output
├── Literature/                ← drop PDF papers here
└── skills/                    ← agent skill files (this directory)
```

---

## Execution Environment

MAW supports two execution environments selected via `--env`:

| Flag | Knowledge skill loaded | What it allows |
|---|---|---|
| `--env local` (default) | `knowledge/local` | Single machine, serial/thread-parallel, no MPI |
| `--env hpc` | `knowledge/lcrc` | Multi-node PBS allocation, mpirun, MPI |

Agents receive the appropriate knowledge skill injected into their context and
must follow its constraints. When no `--env` is specified, local is assumed.

---

## Skill File System

Agent behavior is modulated by layered skill files:

| Layer | Path pattern | Purpose |
|---|---|---|
| Base agent skill | `skills/agents/{agent}.SKILL.md` | Domain-agnostic rules for the agent's job |
| Use-case skill | `skills/use_cases/{name}/{agent}.SKILL.md` | Workflow-specific rules and knowledge |
| System skill | `skills/systems/{name}.SKILL.md` | Framework-specific rules (Parsl, PyCOMPSs, ADIOS2) |
| Knowledge | `skills/knowledge/{name}.SKILL.md` | Shared reference (this file) |

Agents load their base skill on every call. They request use-case and system skills via `skill_requests` in their structured output when domain-specific context is needed.

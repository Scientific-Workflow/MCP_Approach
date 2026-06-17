---
name: knowledge/local
description: >
  Runtime environment knowledge for running MAW on a local machine (single node, no HPC).
  Covers execution constraints, path conventions, and what agents must NOT recommend.
  Load when --env is local (the default) or when no cluster environment is specified.
---

# Local Machine Environment — Knowledge Skill

## When to Use This Skill

Loaded automatically when `--env local` is set (the default). Applies to developer
machines, laptops, and any single-node execution outside of a cluster.

---

## Execution Model

MAW runs as a Python process on the local host. The MCP server executes tasks using
the local Python venv. All tasks run in a single process on a single machine.

```
Host machine (single node)
└── agent process (LangGraph)
    └── MCP server subprocess (parsl_server.py)
        └── tasks run in local venv
```

---

## Constraints — What Agents Must Not Recommend

- No PBS, LSF, or any job scheduler
- No MPI across nodes, no `mpirun`, no `srun`, no `mpi4py`
- No multi-node Parsl configs (no `PBSProProvider`, no `LSFProvider`)
- No GPU unless explicitly confirmed available on the host
- No `module load` commands — packages come from the venv

Use serial or thread-parallel single-process approaches only.

---

## Paths

| Alias | Resolves to |
|---|---|
| `/app/` | repo root on disk (`HOST_REPO_PATH`) |
| `/app/data/` | input data files |
| `/app/work/run0/` | default working directory for task output |

---

## Parsl Config

For Parsl config, load the `systems/parsl` skill — the local single-node config is documented there.

---

## Stack Rules

- All packages installed via pip into the local venv
- Never include: `mpi4py`, OpenMPI, MPICH, or any MPI-dependent package
- Headless rendering requires: `LIBGL_ALWAYS_SOFTWARE=1`, `PYOPENGL_PLATFORM=osmesa`

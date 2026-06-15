---
name: systems/pycompss
description: >
  PyCOMPSs workflow framework knowledge. Covers @task decorators, COMPSs runtime,
  compss_start/compss_stop lifecycle, compss_wait_on for synchronization, and
  differences from Parsl. Load this skill when the workflow uses PyCOMPSs.
---

# PyCOMPSs -- System Skill

PyCOMPSs is a task-based parallel programming model developed at BSC (Barcelona
Supercomputing Center). Tasks are defined with `@task` decorators and managed by
the COMPSs runtime. It supports automatic dependency detection, data locality
optimization, and heterogeneous resource management.

---

## Key API

```python
from pycompss.api.api import compss_start, compss_stop, compss_wait_on
from pycompss.api.task import task
from pycompss.api.parameter import INOUT, IN, OUT, FILE_IN, FILE_OUT

# Start runtime
compss_start()

# Define a task
@task(returns=int)
def compute(x, y):
    return x + y

# Submit and wait
result = compute(3, 4)          # returns a future
result = compss_wait_on(result) # blocks until done

# Stop runtime
compss_stop()
```

---

## Key Differences from Parsl

| Feature | Parsl | PyCOMPSs |
|---|---|---|
| Task decorator | `@python_app` | `@task` |
| Config/init | `parsl.load(Config(...))` | `compss_start()` |
| Future resolution | `future.result()` | `compss_wait_on(future)` |
| Shutdown | `parsl.clear()` | `compss_stop()` |
| Worker imports | Must be inside function body | Module-level OK |
| Dependency detection | Explicit via data flow | Automatic from parameters |
| Launch command | `python script.py` | `runcompss script.py` |

---

## MCP Server Behavior

The PyCOMPSs MCP server (`servers/pycompss_server.py`) operates in two modes:

1. **COMPSs mode** (runtime available): Tasks are wrapped with `@task` decorator,
   executed via `runcompss`, and synchronized with `compss_wait_on()`.

2. **Fallback mode** (runtime NOT available): Tasks execute as plain Python scripts.
   Same result, just no COMPSs orchestration. This allows development and testing
   on machines without COMPSs installed.

The `engine` field in task results indicates which mode was used:
- `"engine": "pycompss"` -- COMPSs runtime was used
- `"engine": "pycompss-fallback"` -- direct Python execution

---

## Running with COMPSs

On HPC systems with COMPSs installed:
```bash
module load COMPSs
python agent_mcp.py --engine pycompss --paper 1 --goal "..."
```

On local machines without COMPSs:
```bash
# Works fine -- falls back to direct execution
python agent_mcp.py --engine pycompss --paper 1 --goal "..."
```

---

## Notes

- PyCOMPSs requires Java + COMPSs runtime for full functionality
- The fallback mode ensures the MCP approach works anywhere
- On HPC, COMPSs handles task scheduling, data transfers, and fault tolerance
- Task results are identical in both modes -- only orchestration differs

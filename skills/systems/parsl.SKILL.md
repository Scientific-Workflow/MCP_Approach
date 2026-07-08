
---
name: systems/parsl
description: >
  Parsl parallel scripting library reference for MAW workflows. Covers @python_app/@bash_app
  rules, HighThroughputExecutor config for local single-node execution, common pitfalls,
  and the exact config skeleton used in this project.
---

# Parsl — System Skill

Parsl orchestrates workflow steps as asynchronous Python functions. In MAW, it manages the LAMMPS simulation and OVITO analysis as parallel tasks on a single local node.

---

## READ THIS FIRST: `submit_task` Already Runs Your Code Through Parsl

In the MCP tool-calling architecture, `submit_task`'s `python_code` argument is
**already executed as a Parsl `@python_app` by the server itself**, on a
persistent worker pool the server set up at startup
(`servers/parsl_server.py`: `_exec_command_app` is `@python_app`-decorated,
and every `submit_task`/`submit_shell_task` call routes through it). This
happens automatically, for every single task, with zero code from you.

**Never write `import parsl`, `from parsl.config import Config`,
`HighThroughputExecutor`, `LocalProvider`, or `parsl.load(...)` inside the
`python_code` string you pass to `submit_task`.** Doing so creates a second,
fully independent Parsl runtime *nested inside* a task that the server
already dispatched through its own Parsl runtime. Confirmed in a real run:
this nested config let Parsl auto-detect the node's full core count and spin
up **128 separate worker processes** to run what was meant to be one simple
function call -- multiple seconds of pure overhead, for nothing.

**If you need several independent units of work done concurrently** (e.g.
one render per output file), do **not** try to build that concurrency
yourself with `@python_app` inside one `submit_task` call. Instead, just call
`submit_task` **multiple times** -- once per unit of work -- as ordinary,
separate tool calls with plain Python in each one. The server's own
persistent worker pool already runs those concurrently; you get real
parallelism for free without writing a single line of Parsl code.

The API reference below (`Config`, `@python_app`, lifecycle) describes what
the *server* does under the hood, for your understanding -- it is not a
template to copy into `python_code`. The only context where you would
legitimately write this yourself is generating a *standalone* Parsl script
outside the MCP tool-calling flow (the "artifact" approach), which is a
different code path from this one.

---

## When to Use This Skill

Load when generating or debugging Parsl workflow code. Covers the exact config and API patterns used in this project.

---

## Overview

Parsl wraps Python functions with `@python_app` to run them as managed tasks. Tasks return `AppFuture` objects; call `.result()` to block and get the value. Workers run in separate processes — imports must be inside function bodies.

---

## Config — Local (single node)

```python
from parsl.config import Config
from parsl.executors import HighThroughputExecutor
from parsl.providers import LocalProvider
import parsl

config = Config(
    executors=[
        HighThroughputExecutor(
            label="local_htex",
            cores_per_worker=1,
            provider=LocalProvider(
                min_blocks=1,
                max_blocks=1,
                init_blocks=1,
            ),
        )
    ],
    strategy="none",
)
parsl.load(config)
```

**CRITICAL:** Do NOT add `max_workers`, `max_workers_per_node`, or any kwargs not shown. They cause `TypeError` in recent Parsl versions.

## Config — HPC (inside existing PBS job)

Scale workers to the number of allocated nodes. Do NOT submit new PBS jobs from within the agent.

```python
from parsl.config import Config
from parsl.executors import HighThroughputExecutor
from parsl.providers import LocalProvider
import parsl, os

n_workers = int(os.environ.get("PBS_NUM_NODES", 1))

config = Config(
    executors=[
        HighThroughputExecutor(
            label="htex_lcrc",
            cores_per_worker=1,
            provider=LocalProvider(
                min_blocks=n_workers,
                max_blocks=n_workers,
                init_blocks=n_workers,
            ),
        )
    ],
    strategy="none",
)
parsl.load(config)
```

---

## @python_app Rules

```python
@python_app
def my_step(arg1, arg2):
    import os      # ALL imports inside function body
    import shutil  # workers don't share main namespace
    return result  # must be picklable
```

- All imports go inside the function body
- No closures over mutable outer state
- `.result()` only in `main()`, never inside another app
- Return values must be picklable (strings, ints, simple dicts)

---

## Common Pitfalls

| Pitfall | Rule |
|---|---|
| Imports at module level inside @python_app | All imports must be inside the function body |
| Calling `.result()` inside an app | Deadlocks the worker — only call in main() |
| Extra kwargs in HighThroughputExecutor | Causes TypeError — copy config exactly |
| `strategy` not set to `"none"` | Can cause auto-scaling issues in local mode |
| `parsl.load()` called twice without `parsl.clear()` | Raises NoDataFlowKernelError |
| `WorkerLost` error | Worker process crashed — check stderr for the actual exception |
| Simulation task submitted more than once per run | Call the sim `@python_app`/`submit_task` exactly once per workflow invocation — re-submitting (e.g. on replan or retry) silently produces duplicate runs instead of reusing the result |

---

## Lifecycle

```python
parsl.load(config)      # call once at startup
# ... submit tasks ...
future = my_app(args).result()   # blocks until done
parsl.clear()           # call at end of main() to release workers
```

---

## AppFuture API

```python
future = my_app(args)
value = future.result()     # block and get return value
exc   = future.exception()  # returns exception or None
done  = future.done()       # bool, non-blocking
```

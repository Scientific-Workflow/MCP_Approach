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

## READ THIS FIRST: `submit_task` Already Wraps Your Code

In the MCP tool-calling architecture, `submit_task`'s `python_code` is
**already wrapped with `@task`/`compss_wait_on()` by the server itself**
before it runs (`servers/pycompss_server.py`: `_wrap_as_compss_task()`
injects this automatically around every submitted script). This happens for
every task, with zero code from you. Inside a PBS job, the wrapped script is
launched through the real `runcompss` binary, which owns the
`compss_start()`/`compss_stop()` lifecycle itself; outside a PBS job it runs
via a "direct link" mode where the wrapped script manages that lifecycle
instead (see MCP Server Behavior below) -- either way, it's the server's job,
not yours.

**Never write `compss_start()`, `@task`, `compss_wait_on()`, or
`compss_stop()` inside the `python_code` string you pass to `submit_task`.**
Depending on mode that either double-initializes a runtime `runcompss`/the
server already manages, or duplicates lifecycle calls the wrapper already
injects.

**For several independent units of work** (e.g. one render per output
file), don't try to build that concurrency yourself with `@task` inside one
`submit_task` call -- call `submit_task` **multiple times** instead, once per
unit of work, as separate tool calls with plain Python in each. Real
parallelism, zero PyCOMPSs code written by you.

The API reference below describes what the *server* does under the hood, for
understanding -- it is not a template to copy into `python_code`.

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

The PyCOMPSs MCP server (`servers/pycompss_server.py`) operates in three modes:

1. **`runcompss` mode** (runtime available AND running inside a PBS job): Tasks
   are wrapped with `@task`/`compss_wait_on()` (no `compss_start()`/`compss_stop()`
   in the script) and launched through the real `runcompss` binary against a
   `project.xml`/`resources.xml` pair generated for this node's own hostname
   (`_compss_config_files()`). `runcompss`'s own launcher owns the runtime
   lifecycle. This targets the node's real hostname rather than "localhost"
   because `runcompss`'s default local config launches its worker over SSH, and
   this cluster enforces SSH-key+Duo MFA on login nodes -- SSH between nodes
   *inside* an active PBS allocation isn't subject to that policy, confirmed by
   hand. Also confirmed by hand: the wrapped script must NOT itself call
   `compss_start()`/`compss_stop()` in this mode (that duplicates what
   `runcompss` already does) and must NOT wrap the `@task` call in
   `try/except` (PyCOMPSs's binding runs the script's top level once for task
   registration before the runtime link is up, then again for real; wrapping
   in `try/except` leaks that first pass's internal, expected
   `'NoneType' object has no attribute 'process_task'` into task output
   instead of the binding absorbing it silently).

2. **Direct-link mode** (runtime available, NOT in a PBS job): Tasks are
   wrapped with `@task` and synchronized with `compss_wait_on()`, then run via
   plain `VENV_PYTHON` -- the wrapped script self-manages `compss_start()`/
   `compss_stop()` itself, since there's no `runcompss` launcher owning that
   lifecycle here. Used because `runcompss`'s SSH-based worker launch would hit
   the same login-node Duo wall outside a job allocation.

3. **Fallback mode** (runtime NOT available): Tasks execute as plain Python scripts.
   Same result, just no COMPSs orchestration. This allows development and testing
   on machines without COMPSs installed.

The `engine` field in task results indicates which runtime was used:
- `"engine": "pycompss"` -- COMPSs runtime was used (either mode 1 or 2)
- `"engine": "pycompss-fallback"` -- direct Python execution (mode 3)

The `launched_via` field distinguishes mode 1 from mode 2:
- `"launched_via": "runcompss"` -- real `runcompss` binary launch
- `"launched_via": "direct"` -- direct-link, self-managed lifecycle
- `"launched_via": "fallback"` -- no COMPSs runtime at all

---

## Running with COMPSs

On Improv there is no `module load COMPSs` -- it was hand-built (see "How COMPSs
Got Installed on Improv" below) and lives at `~/.local/COMPSs`. `servers/pycompss_server.py`
hardcodes the required env vars (`PYTHONPATH`, `LD_LIBRARY_PATH`, `COMPSS_HOME`,
`JAVA_HOME`) into `TASK_ENV` with sensible defaults, so no manual setup is needed --
just run normally:
```bash
python agent_mcp.py --engine pycompss --paper 1 --goal "..."
```

On local machines / other clusters without COMPSs:
```bash
# Works fine -- falls back to direct execution
python agent_mcp.py --engine pycompss --paper 1 --goal "..."
```

---

## How COMPSs Got Installed on Improv

**`pip install pycompss` does not work reliably -- do not rely on it.** The PyPI
`pycompss` package is a thin wrapper whose `setup.py` downloads the real ~925MB
COMPSs distribution and runs its own install script as a side effect. Two bugs in
that wrapper, both confirmed by direct reproduction:
1. It silently installs to `~/.local/lib/.../site-packages` instead of the active
   venv if `VIRTUAL_ENV` isn't set in the environment -- calling `./venv3/bin/pip`
   directly (without `source venv3/bin/activate`) triggers this silently.
2. Even with `VIRTUAL_ENV` set correctly, its nested
   `pip install --no-build-isolation --target=... .` step for the Python bindings
   can fail with `KeyError: 'TARGET_OS'` depending on call context -- an env-var
   propagation bug in COMPSs's own `install.sh`/`setup.py`, not ours to fix.

**What actually works: run COMPSs's real installer directly**, bypassing the pip
wrapper entirely:
```bash
module load openjdk/21.0.0_35   # JAVA_HOME -- no module named "java", must use "openjdk"
module load boost/1.84.0        # for the C++ bindings-common build
# libxml2-devel has no module/package anywhere on Improv (no root, no spack CLI
# exposed) -- built from source instead, shared (not static) so it can link into
# COMPSs's .so targets:
#   curl -LO https://download.gnome.org/sources/libxml2/2.12/libxml2-2.12.9.tar.xz
#   ./configure --prefix=$HOME/.local/libxml2 --without-python && make -j4 && make install
export PATH="$HOME/.local/libxml2/bin:$PATH"
export CPATH="$HOME/.local/libxml2/include/libxml2:$CPATH"
export LIBRARY_PATH="$HOME/.local/libxml2/lib:$LIBRARY_PATH"
export LD_LIBRARY_PATH="$HOME/.local/libxml2/lib:$LD_LIBRARY_PATH"

curl -LO http://compss.bsc.es/repo/sc/stable/COMPSs_3.4.tar.gz
tar xzf COMPSs_3.4.tar.gz && cd COMPSs
bash install --no-tracing ~/.local/COMPSs
```
Confirmed end-to-end: `compss_start()` / `compss_stop()` round-trip cleanly against
this install. **COMPSs is not a site-packages install** -- its own installer puts the
Python bindings at `~/.local/COMPSs/Bindings/python/3/pycompss` (always major version
"3", regardless of the actual Python 3.x minor version) and expects activation via
`PYTHONPATH`/`LD_LIBRARY_PATH`/`COMPSS_HOME`, not `pip`. `pycompss_server.py` builds
these from `COMPSS_HOME` (defaults to `~/.local/COMPSs`, override via env var if
installed elsewhere) so this is reproducible without re-deriving any of the above.

---

## `runcompss` Requires COMPSs Env Vars in `~/.bashrc`, Not Just the Server's Subprocess Env

`pycompss_server.py` sets `COMPSS_HOME`/`JAVA_HOME`/`LD_LIBRARY_PATH`/`PYTHONPATH`/`PATH`
for its own subprocess (`TASK_ENV`), which covers the master-side `runcompss`
process. But `runcompss`'s worker launch opens a **separate SSH session** to
the target node, and SSH does not forward the master's shell env vars to that
session -- the worker instead gets whatever a fresh login shell sets up via
`~/.bashrc`. So `JAVA_HOME` (and `PATH` including `$JAVA_HOME/bin`) must also
be exported in `~/.bashrc` itself, or the SSH-launched worker JVM fails with
`Can't find JVM libraries in JAVA_HOME` or `setsid: failed to execute java: No
such file or directory` and the master hangs retrying forever. `~/.bashrc` on
this account now has this covered; if COMPSs is reinstalled elsewhere or on a
new account, replicate those exports there too, not just in `TASK_ENV`.

---

## Notes

- PyCOMPSs requires Java + COMPSs runtime for full functionality
- The fallback mode ensures the MCP approach works anywhere
- On HPC, COMPSs handles task scheduling, data transfers, and fault tolerance
- Task results are identical in both modes -- only orchestration differs

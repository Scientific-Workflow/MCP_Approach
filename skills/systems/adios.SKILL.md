---
name: systems/adios
description: >
  ADIOS2 (Adaptable Input/Output System) workflow framework knowledge. Covers
  high-performance I/O for scientific simulations, BP file format, SST streaming,
  Python bindings, and differences from Parsl/PyCOMPSs. Load this skill when
  the workflow uses ADIOS2 for data transport between pipeline stages.
---

# ADIOS2 -- System Skill

ADIOS2 is a high-performance I/O framework developed at ORNL (Oak Ridge National
Laboratory) for scientific simulations. It provides flexible data transport
between workflow stages, supporting file-based (BP format), streaming (SST),
and in-memory (DataMan) data exchange.

---

## READ THIS FIRST: Use `write_bp`/`read_bp`, Not Raw `submit_task`

Unlike Parsl/PyCOMPSs, the server **cannot** force real ADIOS2 usage the way
`@python_app`/`@task` wrapping does -- ADIOS2 is an I/O library, not a task
scheduler, so there's no single call-site to wrap around arbitrary code.
`submit_task` only pre-imports `adios2`; it does nothing to stop you from
importing it and then never calling it.

**Prefer `write_bp(name, bp_path, python_code)` / `read_bp(name, bp_path,
python_code)` instead of `submit_task` for any real ADIOS2 I/O.** These tools
have the server open a real `adios2.Stream(bp_path, "w"/"r")` for you --
`python_code` runs with `stream` already bound to it. Call
`stream.write(...)`/`stream.write_attribute(...)` (write mode) or
`stream.read(...)`/`stream.read_attribute(...)` (read mode) on it directly.
**Do not open your own Stream or `import adios2` yourself inside that code --
the server already did both.**

This is checked, not just suggested: every `submit_task`/`write_bp`/`read_bp`
call reports an `"engine"` field (see "MCP Server Behavior" below for the
full 4-state breakdown). The one that matters for `write_bp`/`read_bp`:
`"adios2-unused"` means ADIOS2 was available but your code never called the
pre-opened Stream -- even inside `write_bp`/`read_bp`'s wrapper, if you never
call `.write(`/`.read(` on it, you'll still get `"adios2-unused"`. This is
recorded in the trace and the orchestrator routes back to you if it sees
`"adios2-unused"` on a task that should have done real I/O.

---

## Key API

```python
import adios2
import numpy as np

# Write data to BP file
with adios2.open("output.bp", "w") as fw:
    for step in range(num_steps):
        fw.write("temperature", temperature_array, shape, start, count)
        fw.end_step()

# Read data from BP file
with adios2.open("output.bp", "r") as fr:
    for step in fr:
        data = step.read("temperature")
        # process data

# Streaming mode (SST) -- producer
adios = adios2.ADIOS()
io = adios.declare_io("SimOutput")
io.set_engine("SST")
writer = io.open("stream.bp", adios2.Mode.Write)
writer.begin_step()
writer.put(var, data)
writer.end_step()
writer.close()
```

---

## Key Differences from Parsl/PyCOMPSs

| Feature | Parsl | PyCOMPSs | ADIOS2 |
|---|---|---|---|
| Primary role | Task scheduling | Task scheduling | Data I/O & transport |
| Task decorator | `@python_app` | `@task` | None (I/O library) |
| Data exchange | File system | File system | BP files, SST streams, in-memory |
| Streaming support | No | No | Yes (SST, DataMan) |
| In-situ analysis | No | No | Yes |
| HPC optimized I/O | No | No | Yes (parallel BP, aggregation) |

---

## Data Formats

- **BP (Binary Pack)**: ADIOS2's native file format, optimized for parallel I/O
- **SST (Sustainable Staging Transport)**: Real-time streaming between processes
- **DataMan**: In-memory data exchange for tightly coupled workflows
- **HDF5**: ADIOS2 can also read/write HDF5 via its HDF5 engine

---

## MCP Server Behavior

The ADIOS2 MCP server (`servers/adios_server.py`) operates in four states,
reported via the `engine` field on every `submit_task`/`write_bp`/`read_bp`
response:

1. **`"adios2"`** -- ADIOS2 is installed AND the submitted code actually
   called a real API (`adios2.open`/`Stream`/`.declare_io`/`.begin_step`/
   `.end_step`/`.write(`/`.read(`, etc., depending on the tool). This is the
   only state that means real ADIOS2 I/O actually happened.
2. **`"adios2-unused"`** -- ADIOS2 is installed, the code shows intent to use
   it (an `import adios2` for `submit_task`, or just being inside `write_bp`/
   `read_bp`'s pre-opened Stream at all), but no real API call was detected
   (`adios_server.py::_adios_engine_state` scans for it). This is the exact
   "imported but never used" failure mode -- treat it as a task that needs to
   be redone, not a success.
3. **`"adios2-n/a"`** -- `submit_task`/`submit_shell_task`/`submit_mpi_task`
   only: ADIOS2 is installed but the code has nothing to do with it at all (no
   `import adios2`). Most tasks in an ADIOS run (LAMMPS, OVITO, rendering,
   GIF assembly, ...) legitimately fall here -- this is NOT a warning, it
   just means ADIOS2 usage wasn't expected for that task. Only
   `"adios2-unused"` (intent shown, never followed through) is a real
   problem. `write_bp`/`read_bp` never report this state -- every call to
   them is meant to do real I/O, so not calling `.write(`/`.read(` is always
   `"adios2-unused"`, never `"n/a"`.
4. **`"adios2-fallback"`** -- ADIOS2 isn't installed in this environment at
   all. Tasks execute as plain Python using numpy file I/O (.npy/.npz)
   instead of BP files -- same computational result, just without ADIOS2.
   Not your fault if you see this; it's an environment/install gap.

---

## Running with ADIOS2

On HPC systems with ADIOS2 installed:
```bash
module load adios2
python agent_mcp.py --engine adios --paper 1 --goal "..."
```

On local machines without ADIOS2:
```bash
# Works fine -- falls back to numpy I/O
python agent_mcp.py --engine adios --paper 1 --goal "..."
```

Installing ADIOS2 Python bindings:
```bash
pip install adios2       # may require system-level ADIOS2 installation
conda install -c conda-forge adios2
```

---

## Common Use Cases

- Reading large MD trajectory files in BP format
- Streaming simulation output in real-time (in-situ analysis)
- Coupled simulations (e.g., simulation + analytics pipeline)
- High-performance parallel I/O on HPC file systems
- Paired with LAMMPS via `dump adios` in the LAMMPS input script

---

## Notes

- ADIOS2 is primarily an I/O layer, not a task scheduler
- On HPC, it is often used together with Parsl or PyCOMPSs
- The fallback mode ensures the MCP approach works anywhere
- ADIOS2's streaming mode (SST) is particularly valuable for in-situ workflows
  where analytics run concurrently with simulation

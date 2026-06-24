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

## OPERATING DIRECTIVE (engine = adios) -- MANDATORY

When this engine is selected, ADIOS2 is the data-transport layer of the workflow.
You MUST use it; it is not optional decoration.

1. **Exchange array/grid/trajectory data between stages via ADIOS2 BP files**, not
   raw `.npy` / `.npz` / `.csv` / `.lammpstrj`. The stage that produces numerical
   data writes a `.bp` file with `adios2`; the stage that consumes it reads that
   `.bp` file with `adios2`.
2. **Every task that produces or consumes inter-stage numerical data must contain an
   `adios2.open(...)` call.** If you write a stage with plain numpy/CSV I/O for data
   that a later stage reads, you are NOT using the engine -- rewrite it with adios2.
3. Keep BP files under `/app/work/run0/` (e.g. `/app/work/run0/sim_output.bp`).
4. Small scalars/metadata and final human-facing artifacts (PNG plots, a summary CSV)
   may stay as normal files -- the directive is about **inter-stage data transport**.
5. If `import adios2` fails (ADIOS2 not installed), the run is in fallback mode: it is
   acceptable to fall back to numpy I/O, but state clearly in your summary that ADIOS2
   transport was unavailable.

### Minimal producer -> consumer pattern (follow this shape)

```python
# --- Producer stage: write per-step arrays to a BP file ---
import adios2, numpy as np
with adios2.open("/app/work/run0/sim_output.bp", "w") as fw:
    for step in range(n_steps):
        arr = compute_frame(step)              # np.ndarray, e.g. positions or a field
        fw.write("frame", arr, arr.shape, [0]*arr.ndim, arr.shape)
        fw.write("step", np.array(step))
        fw.end_step()

# --- Consumer stage: read them back for analysis ---
import adios2, numpy as np
with adios2.open("/app/work/run0/sim_output.bp", "r") as fr:
    for step in fr:
        arr = step.read("frame")
        analyze(arr)                           # OVITO/numpy analysis, accumulate results
```

For the LAMMPS nucleation pipeline specifically: have the simulation/extraction stage
write trajectory frames (positions, per-atom quantities) into `sim_output.bp`, and have
the OVITO/analysis stage read frames from `sim_output.bp` instead of re-reading
`.lammpstrj`. The final timeseries plot + `results.csv` are normal output files.

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

The ADIOS2 MCP server (`servers/adios_server.py`) operates in two modes:

1. **ADIOS2 mode** (runtime available): Tasks have `import adios2` pre-loaded,
   can use BP files and streaming for inter-task data transport.

2. **Fallback mode** (runtime NOT available): Tasks execute as plain Python
   scripts using numpy file I/O (.npy/.npz) instead of ADIOS2 BP files.
   Same computational result, just without ADIOS2's I/O optimizations.

The `engine` field in task results indicates which mode was used:
- `"engine": "adios2"` -- ADIOS2 runtime was used
- `"engine": "adios2-fallback"` -- numpy file I/O fallback

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

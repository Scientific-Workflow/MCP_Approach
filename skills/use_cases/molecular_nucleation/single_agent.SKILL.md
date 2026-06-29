---
name: use_cases/molecular_nucleation/single_agent
description: >
  Molecular nucleation rules for the single agent. Covers what to extract from LAMMPS
  water-crystallization papers, the exact pip-installable stack (LAMMPS itself is
  source-built, not pip), LAMMPS Python API usage, OVITO diamond structure detection,
  visualization rules, and known pitfalls across all three phases of the run.
---

# Molecular Nucleation -- Single Agent Skill

Domain-specific guidance for the water crystallization nucleation workflow (LAMMPS
molecular dynamics + OVITO diamond structure detection + Parsl orchestration of your
own task execution).

---

## When to Use This Skill

Load when the paper or goal describes a molecular nucleation or water crystallization
simulation via LAMMPS and OVITO.

---

## Planning Phase

### What to Extract from the Paper
- Temperature (K) -- e.g. "180 K undercooling"
- Timestep (ps) -- e.g. "dt = 0.01 ps"
- Run length (steps) -- e.g. "9000 steps"
- Ensemble -- NPT, NVT, NVE
- Pressure (atm or bar) -- for NPT runs
- Thermostat / barostat coupling constants
- Force field name -- e.g. "Tersoff AW potential", "TIP4P/Ice", "SPC/E"
- System size -- number of atoms or box dimensions
- Seed, if stated
- Software tools: MD engine (LAMMPS, always present here), structure analysis (OVITO
  with IdentifyDiamondModifier), workflow orchestration (Parsl), any post-processing

### Stack Decision
The venv provides exactly these pip-installable packages -- use only these:

| Package | Version constraint |
|---|---|
| ovito | (latest installed) |
| parsl | `parsl>=2024.0.0` |
| numpy | (latest installed) |
| matplotlib | (latest installed) |
| Pillow | (required for GIF generation) |

**LAMMPS is NOT in stack_decision.** It is source-built and pre-installed -- do NOT
list it as a pip package; installing it yourself in the execution phase isn't
possible either (see Execution Phase notes below).

**Do NOT add:** `lammps`, `scipy`, `ase`, `mdanalysis`, `h5py`, or anything else not
listed above. Add `mpi4py` only if the environment knowledge confirms MPI is available.

### Task Templates -- MCP Execution Style
Tasks describe what **you** execute via MCP tool calls, step by step, once execution
starts. There is no workflow.py, no `@python_app`, no `main()`, no bash launcher.

**Too vague (BAD):** "Run LAMMPS and analyze the output."

**Artifact approach (BAD -- do not write tasks like this):** "Write a Parsl
`@python_app` run_lammps that copies files and runs the simulation." / "Write a
`main()` function with argparse." / "Write a `run_workflow.sh` launcher."

**MCP approach (GOOD -- states what gets executed and the critical constraints):**
"Run LAMMPS via `submit_task`: `os.chdir('/app/work/run0')` MUST come before creating
the lammps instance because dump paths in `in.watbox` are relative to CWD. Use
`from lammps import lammps; lmp = lammps(cmdargs=['-screen','none']); lmp.file(...)`.
Do not modify `in.watbox`."

### Task List Template
```
1. Check that ovito, numpy, matplotlib, Pillow are installed via check_package.
2. Create /app/work/run0/frames/ and /app/work/run0/renders/ via submit_shell_task.
3. Copy AW.tersoff, data.init, in.watbox from /app/data/ to /app/work/run0/ via
   submit_shell_task -- always re-copy in.watbox fresh.
4. Run LAMMPS via run_lammps(script='in.watbox', work_dir='/app/work/run0'). The
   server picks mpirun+binary or Python API automatically. Never use submit_task
   for this.
5. Verify frames exist in /app/work/run0/frames/ via list_files before proceeding.
6. Run OVITO analysis via submit_task: IdentifyDiamondModifier, cubic = types 1+2+3,
   hexagonal = types 4+5+6, write results.csv.
7. Render frames via submit_task: matplotlib Agg backend, color by structure type,
   s=25 minimum atom size, save PNGs to renders/.
8. Assemble GIF via submit_task: Pillow, sorted PNGs -> animation.gif.
9. Plot timeseries via submit_task: results.csv -> nucleation_timeseries.png.
```

### Output Quality Checklist (before finalizing the plan)
- 10+ tasks, not 3
- No task says "write a @python_app", "write a main()", or "write a bash launcher"
- All paths use `/app/` -- never cluster-specific paths
- Every critical ordering requirement is its own task
- The LAMMPS task is explicitly `run_lammps`, not a generic `submit_task`
- Visualization colors, atom sizes, and output formats are specified per task

---

## Install Phase Notes

LAMMPS itself never goes through the automatic install step (it isn't in
`stack_decision` and pip can't install it for this use case) -- on HPC it's already
pre-built on the cluster with MPI support and only the Python bindings need to be on
the venv's path; locally it would need a serial (`BUILD_MPI=off`) source build ahead
of time. Either way, this is environment setup that happens outside your run, not
something to attempt as a task. If `from lammps import lammps` fails during
execution, that's an environment problem to report, not something to fix by trying to
pip install `lammps`.

---

## Execution Phase

### Domain-Specific Tools
| Tool | Purpose |
|---|---|
| `run_lammps` | Runs the LAMMPS simulation. Auto-selects mpirun+binary on HPC, Python API locally. Call directly -- never reimplement with `submit_task`. |

### Workflow Overview
Three stages: (1) LAMMPS simulation -> trajectory frames, (2) OVITO analysis -> ice
structure counts, (3) visualization -> rendered frames, animation, and a timeseries
plot.

### Stage 1: LAMMPS Simulation
```
mkdir -p /app/work/run0/frames /app/work/run0/renders
cp /app/data/AW.tersoff /app/work/run0/
cp /app/data/data.init /app/work/run0/
cp /app/data/in.watbox /app/work/run0/
```
Then call `run_lammps(script="in.watbox", work_dir="/app/work/run0")` directly.
Expected output: `/app/work/run0/frames/step.*.lammpstrj`, `/app/work/run0/log.lammps`.

### Stage 2: OVITO Analysis
```python
import os, csv
from ovito.io import import_file
from ovito.modifiers import IdentifyDiamondModifier

pipeline = import_file("/app/work/run0/frames/step.*.lammpstrj")
pipeline.modifiers.append(IdentifyDiamondModifier())

with open("/app/work/run0/results.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["frame", "timestep", "cubic_diamond_count", "hexagonal_diamond_count"])
    for i in range(pipeline.source.num_frames):
        data = pipeline.compute(i)
        struct = data.particles["Structure Type"]
        cubic = int(((struct == 1) | (struct == 2) | (struct == 3)).sum())
        hexag = int(((struct == 4) | (struct == 5) | (struct == 6)).sum())
        writer.writerow([i, data.attributes.get("Timestep", i), cubic, hexag])
```

**CRITICAL -- IdentifyDiamondModifier structure type mapping:**

| Type | Meaning |
|---|---|
| 0 | Other (liquid, amorphous water) |
| 1-3 | Cubic diamond (primary + two neighbor shells) |
| 4-6 | Hexagonal diamond / wurtzite ice (primary + two neighbor shells) |

Cubic = types 1+2+3 (not just type 1). Hexagonal = types 4+5+6 (not just type 4).
Counting only the primary type gives ~10% of the actual crystal count.

### Stage 3: Visualization (all three required, do not skip any)

**3a. Render frames** -- 3D matplotlib scatter per frame, color-coded:
liquid/other (type 0) `#00BFFF` cyan alpha>=0.3; cubic (1-3) `#0000FF` blue alpha>=0.8;
hexagonal (4-6) `#FF2200` red alpha>=0.8. Atom size `s=25` minimum -- default `s=2`
makes atoms invisible. Use `matplotlib.use("Agg")` for headless rendering. Do NOT use
OVITO's default yellow/white rendering. Save as `renders/frame_NNNN.png`.

**3b. Animation GIF** -- via Pillow: load sorted `frame_*.png`, save as
`renders/animation.gif` with `loop=0`, `duration=100` (ms per frame).

**3c. Nucleation timeseries** -- read `results.csv`, plot cubic count (`#0000FF`) and
hexagonal count (`#FF2200`) vs timestep, dashed black total-ice line, save as
`renders/nucleation_timeseries.png`.

### Error Recovery Patterns

| Error pattern | What to do |
|---|---|
| `exit 143` on `run_lammps` | MPI init failure -- `run_lammps` should handle this via the server's `TASK_ENV`. Check that `get_resources` was called first and `in_pbs` is true. |
| `WorkerLost` + MPI/ORTE | LAMMPS MPI init failure. `run_lammps` handles HPC/local selection -- do not use `submit_task` with the Python API for LAMMPS. |
| `ModuleNotFoundError: No module named 'lammps'` | Use `from lammps import lammps` -- the build is pre-installed. Do not try `pip install lammps`. |
| `ModuleNotFoundError: No module named 'PIL'` | Pillow installs as `Pillow` but imports as `PIL` -- `from PIL import Image`. |
| `frames/step.*.lammpstrj` not found / no frames | Ensure `os.chdir(work_dir)` happens BEFORE creating the lammps instance, and that `work_dir/frames/` exists. |
| `results.csv` missing after exit 0 | Check the `output_csv` path and that the `pipeline.compute()` loop actually ran. |
| OVITO counts are all zero | Use types 1+2+3 for cubic and 4+5+6 for hexagonal, not just 1 and 4. |
| matplotlib display error | Use `matplotlib.use("Agg")` for headless rendering. |
| LAMMPS can't find `data.init` | Copy ALL data files to `work_dir` BEFORE calling `run_lammps`. |

Maximum 3 retries per task, same as the general rule -- after that, move on and
report the failure.

---

## Input Files

- `/app/data/in.watbox` -- LAMMPS input script (`run 9000`, `timestep 0.01`,
  `variable T equal 180`, `variable P equal 1.0`). Never modify.
- `/app/data/data.init` -- initial atom positions
- `/app/data/AW.tersoff` -- Tersoff force field for water

## Output Files (in the work dir)

- `/app/work/run0/frames/step.*.lammpstrj` -- trajectory files
- `/app/work/run0/results.csv` -- frame, timestep, cubic_diamond_count, hexagonal_diamond_count
- `/app/work/run0/renders/frame_*.png` -- per-frame atom renders
- `/app/work/run0/renders/animation.gif` -- animated GIF of crystallization
- `/app/work/run0/renders/nucleation_timeseries.png` -- ice counts over time

## Notes

- After a successful run, expect exit 0, `results.csv`, and `animation.gif` present
  before considering the run complete -- this use case DOES expect a GIF/animation
  output, unlike `cosmology`.
- All paths in tasks and code MUST use `/app/` -- never `/lcrc/project/`, `/gpfs/`,
  or `/scratch/`.

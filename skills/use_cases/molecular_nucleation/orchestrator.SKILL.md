---
name: use_cases/molecular_nucleation/orchestrator
description: >
  Molecular nucleation routing rules for the orchestrator. Covers the venv setup flow,
  LAMMPS executor error pattern recognition, and requirements.txt approval behavior.
---

# Molecular Nucleation — Orchestrator Skill

Routing rules specific to the water crystallization / LAMMPS workflow.

---

## When to Use This Skill

Load when orchestrating a molecular nucleation workflow. Overrides generic routing heuristics with LAMMPS-specific error pattern recognition.

---

## Flow for This Project

```
planner → installer → explorer → end
```

The installer sets up the local venv (pip install from requirements.txt). Route to installer after planner completes.

---

## Executor Error Pattern Recognition

When the explorer reports tool call failures, use these patterns to decide where to route:

| Error pattern | Route to | Feedback |
|---|---|---|
| `unrecognized arguments` | explorer | "workflow.py uses wrong argparse interface. Must accept only --data-dir and --work-dir. Remove any other arguments." |
| `WorkerLost` + `MPI` / `ORTE` | explorer | "LAMMPS MPI init failure in Parsl worker. Do not use pip lammps wheel — use `from lammps import lammps` from the source-built install. Ensure LD_LIBRARY_PATH=/usr/local/lib is set before import." |
| `ModuleNotFoundError: No module named 'lammps'` | explorer | "LAMMPS not found. Use `from lammps import lammps` — the source build is at /usr/local/lib. Do not pip install lammps." |
| `ModuleNotFoundError: No module named 'PIL'` | explorer | "Pillow is installed as 'Pillow' not 'PIL'. Import with `from PIL import Image`." |
| `frames/step.*.lammpstrj` not found / no frames | explorer | "LAMMPS did not produce dump files. Ensure os.chdir(work_dir) is called BEFORE lammps() and that work_dir/frames/ exists." |
| `results.csv` missing after exit 0 | explorer | "analyze_with_ovito did not write results.csv. Check the output_csv path and that pipeline.compute() loop runs." |
| All other failures | explorer | Full stderr content |

---

## Requirements Approval

When the installer presents requirements.txt for approval, verify it contains:
- `ovito`
- `parsl>=2024.0.0`
- `numpy`
- `matplotlib`
- `Pillow`

**Do NOT approve** requirements.txt that includes `lammps` as a pip package — LAMMPS must be source-built (serial, `BUILD_MPI=off`). If `lammps` appears in the list, reject with feedback to remove it.

---

## Notes

- After a successful run (exit 0, results.csv present), route to "end"
- Explorer revision trigger: any tool call failure that is not a missing pip package
- Never route back to planner unless the task description itself was wrong (rare)

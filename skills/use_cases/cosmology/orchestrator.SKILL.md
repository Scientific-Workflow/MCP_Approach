---
name: use_cases/cosmology/orchestrator
description: >
  Cosmology (HACC) routing rules for the orchestrator. Covers the real-qsub
  architectural exception, requirements approval for this project, and
  HACC-specific error pattern recognition.
---

# Cosmology (HACC) — Orchestrator Skill

Routing rules specific to the HACC cosmological N-body workflow (Last Journey sample run).

---

## When to Use This Skill

Load when orchestrating a HACC / cosmology workflow (goal mentions HACC, qsub/qstat
against `/lcrc/project/PEDAL/jacoboh/HACC/`, GenericIO, FOF/SOD halo catalogs, or
"Last Journey").

---

## Flow for This Project

```
planner → installer → explorer → end
```

Same shape as other use cases. Route to installer after planner completes.

---

## Architectural Exception: Real `qsub` Is Allowed Here

The general LCRC rule is "the agent never submits a new PBS job — run inside the
existing interactive allocation instead." **This use case is an explicit, deliberate
exception**: the HACC simulation executable is a private/closed-source binary that
must be run via its own batch script (`subme.pbs`), so the explorer submitting a real
`qsub subme.pbs` (and polling with `qstat`) is correct behavior, not a violation to
flag or route back for correction. Do not give feedback telling the explorer to avoid
`qsub` for this project. This exception is specific to this use case — still enforce
the no-new-qsub rule for every other use case (e.g. `molecular_nucleation`).

---

## Requirements Approval

When the installer presents `requirements.txt`, verify it contains the basics:
- `numpy`
- `matplotlib`
- `mpi4py` (only if environment knowledge confirms MPI is available)

`adios2` may or may not appear depending on whether the planner decided to request it
for this engine — approve either way; if it's missing and `--engine adios` was
requested, that's fine, the workflow has a documented numpy-I/O fallback (see
`systems/adios` skill) rather than a hard requirement.

**Do NOT approve** a requirements.txt that includes `ovito`, `Pillow`, or `lammps` —
those belong to the `molecular_nucleation` use case, not this one; their presence
usually means a stale `requirements.txt` from a previous run leaked through.

**Do NOT approve** anything that tries to pip-install HACC itself, `pygio`, or
GenericIO bindings — those are pre-built cluster binaries/private code, never
pip-installable, and attempting to build them is a real installer risk (compiling a
C++ extension against GenericIO libs).

---

## Error Pattern Recognition

| Error pattern | Route to | Feedback |
|---|---|---|
| `ModuleNotFoundError: No module named 'pygio._version'` | explorer | "pygio is not built and should not be built. Use `GenericIOPrint` via subprocess instead." |
| `qsub` / `qstat` command not found or job ID not captured | explorer | "Re-run via submit_shell_task with `cd /lcrc/project/PEDAL/jacoboh/HACC/SampleRun_go && qsub subme.pbs` — qsub must run with that directory as cwd so $PBS_O_WORKDIR resolves." |
| Halo selection picks an unexpectedly small/odd halo | explorer | "Select most massive halo by `sod_halo_mass` (M_200c), excluding rows where `sod_halo_count == -101` — not by `fof_halo_mass`." |
| Visualization image missing or blank | explorer | "Verify density_slice data was actually computed (non-zero `sigma`) before rendering; check the halo's z-coordinate was passed through correctly as the slice center." |
| All other failures | explorer | Full stderr content |

---

## Notes

- After a successful run (PBS job completed, density slice image produced, summary
  written), route to "end"
- Never route back to planner unless the task list itself is structurally wrong (e.g.
  missing a required stage) — config-value mistakes should go back to explorer with
  feedback to re-read `params/indat.params`/`cosmotools-config.dat`, not to planner
- This is a single-trial-per-run workflow (no per-frame animation stage, unlike
  `molecular_nucleation`) — do not expect or require a GIF/animation output here

---
name: use_cases/cosmology/planner
description: >
  Cosmology (HACC) extraction rules for the planner. Covers what parameters to
  extract from cosmological N-body papers (Last Journey / HACC), the correct
  stack_decision for this project, the real-qsub exception, and MCP-style task
  templates for the producer -> analysis -> visualization pipeline.
---

# Cosmology (HACC) — Planner Skill

Extraction and task-writing rules specific to the HACC cosmological N-body workflow.

---

## When to Use This Skill

Load when planning a HACC / cosmological N-body workflow (paper mentions HACC, Mira,
Last Journey, FOF/SOD halo finding, or the goal references
`/lcrc/project/PEDAL/jacoboh/HACC/`).

---

## The Simulation Is a Private Black Box

The `hacc_tpm` executable is closed-source. Tasks must call the existing PBS script
and read its output — never write tasks that ask the explorer to "reimplement",
"recreate", or "regenerate" the simulation logic in Python. v1 scope is strictly
"call the existing binary, read its output."

---

## What to Extract from the Paper

- Box size `RL` and grid resolution `NG` (the SampleRun uses small downscaled values —
  confirm against `params/indat.params` rather than assuming the paper's full-scale
  values apply, e.g. the real Last Journey run is far larger than this sample)
- Cosmological parameters: `Omega_m`, `Omega_cdm`, `Omega_b`, `h`, `sigma_8`, `n_s`
- FOF linking length (`b`), FOF minimum particle count (`FOF_PMIN`)
- SOD overdensity multiple `Delta` (e.g. 200 -> M_200c/R_200c), `SOD_PMIN`
- Halo center convention (most-bound particle / min-potential vs center-of-mass)
- Which snapshot step is being targeted for visualization (the SampleRun has steps
  205/310/624 already populated; step 624 is the one used for the reproduction)

Treat the paper as descriptive ground truth for *what the pipeline should compute*,
but always confirm actual numeric config values against the real files in
`SampleRun_go/params/` rather than hardcoding paper values that may not match this
particular sample run.

---

## Stack Decision

```
numpy
matplotlib
mpi4py        (only if environment knowledge confirms MPI is available)
```

If `--engine adios` is selected, you MAY add `adios2` — but it's not mandatory: the
workflow has a documented numpy-I/O fallback (see `systems/adios` skill), so omitting
it is acceptable if you're unsure it's installable. Never add it as a hard requirement
that blocks the run.

**Do NOT add:** `ovito`, `Pillow`, `lammps`, `scipy`, `ase`, `h5py`, `pygio` — none of
these are needed, and `pygio`/HACC binaries are not pip-installable in the first place
(they're pre-built cluster executables or unbuildable in-tree extensions).

---

## Architectural Exception: This Use Case May `qsub`

Unlike every other use case, a task here is allowed to instruct the explorer to submit
a **real, new PBS batch job** via `qsub` (even from inside an already-running
interactive allocation) — because the simulation only runs through its own batch
script. State this explicitly in the relevant task rather than relying on the
explorer/orchestrator to infer it.

---

## Task List Template

```
1. "Call get_resources FIRST. Confirm in_pbs is true and report PBS_NP/PBS_NUM_NODES.
   If in_pbs is false, STOP and tell the user to start a PBS interactive job first.
   This run requires 8 MPI ranks for the HACC producer."

2. "Explore /lcrc/project/PEDAL/jacoboh/HACC/SampleRun_go/ before assuming anything:
   list subme.pbs, params/, output/, and analysis/. Report what executables, input
   decks, and analysis configs (FOF linking length, SOD Delta) actually exist. Do not
   fabricate config values not present in these files."

3. "Submit the simulation job via submit_shell_task: cd into
   /lcrc/project/PEDAL/jacoboh/HACC/SampleRun_go/ and run `qsub subme.pbs` from that
   directory so $PBS_O_WORKDIR resolves correctly (real qsub is explicitly allowed for
   this use case). Capture and report the returned job ID. Do not modify subme.pbs."

4. "Poll the job with `qstat <job_id>` via submit_shell_task until it reaches a
   completed state. Space polls out rather than busy-looping."

5. "Read the particle snapshot at output/full_snapshots/step_624/ using
   GenericIOPrint (at HACC_go/improv.cpu/frontend/bin/GenericIOPrint) via subprocess —
   do NOT use pygio, it is not built. Parse x,y,z,vx,vy,vz,phi; compute particle mass
   from Omega_m, rho_crit0, RL, NP. Save the parsed arrays for downstream stages."

6. "Read the existing halo catalog at
   analysis/haloproperties/step_624/m000p-624.haloproperties via GenericIOPrint.
   Parse the tab-separated header to get column names; do not hand-roll FOF/SOD
   linking — this catalog already exists from a prior run."

7. "Select the most massive halo by sod_halo_mass (M_200c), excluding rows where
   sod_halo_count == -101. Record its center (especially z) and R_200c/M_200c."

8. "Compute a projected dark-matter density slice: bin (x,y) into a 2D histogram
   weighted by particle mass, restricted to particles within +/-2 Mpc/h (4 Mpc/h
   total thickness) of the selected halo's z-coordinate."

9. "Render the density slice with matplotlib (LogNorm color scale), marking the
   halo's (x,y) position, and save as dm_density_slice.png."

10. "Write a summary.txt covering: PBS job ID and final state, config values actually
    used (with their source file), particle/halo counts, and the selected halo's
    M_200c/R_200c/center."
```

---

## Key Rules

- Source data paths (the PBS script, snapshot, halo catalog) are real LCRC paths under
  `/lcrc/project/PEDAL/jacoboh/HACC/SampleRun_go/` — these are external to the repo and
  must be referenced by their actual absolute path, not `/app/data/` (unlike use cases
  whose input data is staged into the repo's data directory).
- Never write a task that asks the explorer to modify `subme.pbs`, `indat.params`, or
  `cosmotools-config.dat` in place — if a derived param file is needed (e.g. for a
  slice tool), write a separate copy.
- This is a single producer -> analysis -> visualization pipeline per run, with no
  per-frame animation/GIF stage (that's specific to `molecular_nucleation`).

---

## Example Output

```json
{
  "literature_findings": [
    "Last Journey: gravity-only cosmological N-body simulation run with HACC on Mira; this is a downscaled 8-MPI-rank sample run",
    "Cosmology (Planck best-fit): Omega_m=0.310, h=0.6766, sigma_8=0.8102, n_s=0.9665",
    "Halo finding: FOF (linking length b) then SOD (grows sphere to Delta x critical density), most massive halo selected by M_200c",
    "Visualization: 4 Mpc/h-thick xy density slice centered on most massive halo's z-coordinate"
  ],
  "stack_decision": ["numpy", "matplotlib", "mpi4py"],
  "tasks": [
    "Call get_resources FIRST; confirm in_pbs true, 8 MPI ranks available.",
    "Explore SampleRun_go/ (subme.pbs, params/, output/, analysis/) before assuming config values.",
    "Submit `qsub subme.pbs` from SampleRun_go/ (real qsub allowed for this use case); capture job ID.",
    "Poll `qstat <job_id>` until completed.",
    "Read step_624 snapshot via GenericIOPrint (not pygio); parse positions/velocities/potential, compute mass.",
    "Read existing halo catalog via GenericIOPrint; parse header for column names.",
    "Select most massive halo by sod_halo_mass, excluding sod_halo_count == -101.",
    "Compute 4 Mpc/h-thick xy density slice centered on halo z via mass-weighted 2D histogram.",
    "Render dm_density_slice.png with LogNorm scale, mark halo position.",
    "Write summary.txt with job ID, config values used, halo properties."
  ]
}
```

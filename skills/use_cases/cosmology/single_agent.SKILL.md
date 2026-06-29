---
name: use_cases/cosmology/single_agent
description: >
  Cosmology (HACC) rules for the single agent. Covers the real-qsub architectural
  exception, the minimal pip-installable stack, GenericIO reading via CLI tools (no
  pygio), halo catalog parsing, density-slice rendering, and known pitfalls across
  all three phases of the run.
---

# Cosmology (HACC) -- Single Agent Skill

Domain-specific guidance for the HACC cosmological N-body workflow (producer
simulation -> FOF/SOD halo analysis -> dark-matter density slice visualization),
based on "The Last Journey" sample run.

---

## When to Use This Skill

Load when the paper or goal mentions HACC, Mira, Last Journey, FOF/SOD halo finding,
qsub/qstat against `/lcrc/project/PEDAL/jacoboh/HACC/`, or GenericIO.

---

## The Simulation Is a Private Black Box

The `hacc_tpm` executable is closed-source. Never write a task (or, in execution,
write code) that tries to read, regenerate, or reimplement its physics. Treat it
purely as: submit the existing PBS script, wait for it to finish, read its output.
Never modify `subme.pbs`, `params/indat.params`, or `cosmotools-config.dat` in place
-- if a derived param file is needed, write a separate copy.

---

## Architectural Exception: Real `qsub` Is Allowed Here

The general LCRC rule is "never submit a new PBS job -- run inside the existing
interactive allocation instead." **This use case is an explicit, deliberate
exception**, because the HACC executable must be run via its own batch script
(`subme.pbs`). Submitting a real `qsub subme.pbs` and polling with `qstat` is correct
behavior here. This exception is specific to this use case -- still follow the
no-new-qsub rule for every other use case (e.g. `molecular_nucleation`).

---

## Planning Phase

### What to Extract from the Paper
- Box size `RL` and grid resolution `NG` -- the SampleRun uses small downscaled
  values; confirm against `params/indat.params` rather than assuming the paper's
  full-scale values apply
- Cosmological parameters: `Omega_m`, `Omega_cdm`, `Omega_b`, `h`, `sigma_8`, `n_s`
- FOF linking length (`b`), FOF minimum particle count (`FOF_PMIN`)
- SOD overdensity multiple `Delta` (e.g. 200 -> M_200c/R_200c), `SOD_PMIN`
- Halo center convention (most-bound particle / min-potential vs center-of-mass)
- Which snapshot step is targeted for visualization (the SampleRun has steps
  205/310/624 already populated; step 624 is the one used for reproduction)

Treat the paper as descriptive ground truth for *what the pipeline should compute*,
but confirm actual numeric config values against the real files in
`SampleRun_go/params/` rather than hardcoding paper values that may not match this
particular sample run.

### Stack Decision
```
numpy
matplotlib
mpi4py        (only if environment knowledge confirms MPI is available)
```
If you're using the ADIOS engine you may add `adios2`, but it's not mandatory -- the
workflow has a documented numpy-I/O fallback (see `systems/adios` skill), so omitting
it is acceptable if you're unsure it's installable. Never treat it as a hard
requirement that blocks the run.

**Do NOT add:** `ovito`, `Pillow`, `lammps`, `scipy`, `ase`, `h5py`, `pygio` -- none of
these are needed, and `pygio`/HACC binaries are not pip-installable in the first place
(they're pre-built cluster executables or unbuildable in-tree extensions).

### Task List Template
```
1. Call get_resources FIRST. Confirm in_pbs is true and report PBS_NP/PBS_NUM_NODES.
   If in_pbs is false, STOP and report it. This run requires 8 MPI ranks.
2. Explore /lcrc/project/PEDAL/jacoboh/HACC/SampleRun_go/ before assuming anything:
   list subme.pbs, params/, output/, and analysis/. Report what executables, input
   decks, and analysis configs (FOF linking length, SOD Delta) actually exist.
3. Submit the simulation job via submit_shell_task: cd into SampleRun_go/ and run
   `qsub subme.pbs` from that directory so $PBS_O_WORKDIR resolves correctly. Capture
   and report the returned job ID. Do not modify subme.pbs.
4. Poll the job with `qstat <job_id>` via submit_shell_task until completed. Space
   polls out rather than busy-looping.
5. Read the particle snapshot at output/full_snapshots/step_624/ using GenericIOPrint
   via subprocess -- do NOT use pygio. Parse x,y,z,vx,vy,vz,phi; compute particle mass.
6. Read the existing halo catalog at analysis/haloproperties/step_624/ via
   GenericIOPrint. Parse the tab-separated header to get column names.
7. Select the most massive halo by sod_halo_mass (M_200c), excluding rows where
   sod_halo_count == -101. Record its center (especially z) and R_200c/M_200c.
8. Compute a projected dark-matter density slice: bin (x,y) into a 2D histogram
   weighted by mass, restricted to particles within 4 Mpc/h thickness of the halo's z.
9. Render the density slice with matplotlib (LogNorm color scale), marking the halo's
   (x,y) position, save as dm_density_slice.png.
10. Write summary.txt: PBS job ID and final state, config values actually used (with
    source file), particle/halo counts, selected halo's M_200c/R_200c/center.
```

This is a single producer -> analysis -> visualization pipeline per run, with no
per-frame animation/GIF stage (that's specific to `molecular_nucleation`).

---

## Execution Phase

### Stage 1: Submit the Simulation (real qsub)
```
submit_shell_task(
    name="submit_hacc_job",
    command="cd /lcrc/project/PEDAL/jacoboh/HACC/SampleRun_go && qsub subme.pbs",
)
```
- Must `cd` into `SampleRun_go/` **before** `qsub` -- the script does
  `cd $PBS_O_WORKDIR` and references `./params/indat.params` relatively.
- Capture the returned job ID, then poll with `qstat <job_id>` until state `C`
  (completed). Space polls out rather than busy-looping.
- Job uses 8 MPI ranks (2x2x2 decomposition), `walltime=01:00:00`, job name
  `runme_mini_8r`, merged stdout+stderr (`-j oe`) written to `SampleRun_go/`.
- A completed PBS job can disappear from `qstat` quickly -- also check for the
  `<jobname>.o<jobid>` log file and fresh files in the output snapshot directory as
  completion evidence.

### Stage 1b: Explore Before Assuming Anything
Before reading output, list/inspect the run directory. Config values (FOF linking
length, SOD Delta, box size `RL`, grid size `NG`) live in `params/indat.params` and
`params/cosmotools-config.dat` -- read them, never hardcode paper values without
confirming they match this sample run.

### Stage 2: Reading Snapshot & Halo Data -- Do NOT use pygio
`pygio` is **not built** -- importing it fails with
`ModuleNotFoundError: No module named 'pygio._version'`. Do not attempt to build it
(it means compiling a C++ extension against GenericIO libs). Use the pre-built CLI
binary directly via `subprocess`:
```
GIOP = "/lcrc/project/PEDAL/jacoboh/HACC/HACC_go/improv.cpu/frontend/bin/GenericIOPrint"
```

**Particle snapshot:**
```python
import subprocess, numpy as np
SNAP = "/lcrc/project/PEDAL/jacoboh/HACC/SampleRun_go/output/full_snapshots/step_624/m000p.full.mpicosmo.624"
out = subprocess.run([GIOP, SNAP], capture_output=True, text=True)
rows = []
for ln in out.stdout.splitlines():
    s = ln.strip()
    if s.startswith("#") or not s:
        continue
    parts = s.split()
    if len(parts) < 7:
        continue
    rows.append([float(parts[i]) for i in range(7)])  # x,y,z,vx,vy,vz,phi
arr = np.array(rows, dtype=np.float64)
```
- Pass the **master snapshot file** (e.g. `m000p.full.mpicosmo.624`), not a per-rank
  shard -- `GenericIOPrint` reads across all ranks for you.
- The `# physical coordinates: (0,0,0) -> (64,64,64)` comment line confirms box
  bounds -- use it to sanity-check `RL` from `indat.params`.
- Particle mass is not a column -- compute it:
  `mp = Omega_m * rho_crit0 * (RL/NP)**3` with `rho_crit0 = 2.77536627e11`
  (h^2 Msun/Mpc^3), `NP` = particles-per-side (`64` for this sample run).

**Halo catalog:**
```
HP = "/lcrc/project/PEDAL/jacoboh/HACC/SampleRun_go/analysis/haloproperties/step_624/m000p-624.haloproperties"
```
- The catalog **already exists** from a prior run -- do not hand-roll FOF/SOD
  linking; this file is the halo finder's output.
- `GenericIOPrint` on this file gives a tab-separated header line listing ~76 columns
  including `fof_halo_mass`, `fof_halo_center_x/y/z`, `sod_halo_mass`,
  `sod_halo_radius`, `sod_halo_center_x/y/z` -- parse the header for column order.
- **"Most massive halo" = row with max `sod_halo_mass` (M_200c)**, not
  `fof_halo_mass`. Exclude rows where `sod_halo_count == -101` (SOD never computed).
- Use the halo's center z-coordinate as the visualization slice center.

### Stage 3: Density Slice Visualization
**Pure-Python (confirmed working):** bin particle (x,y) into a 2D histogram weighted
by mass, restricted to particles within the slice thickness around the halo's z:
```python
NBINS = 256
edges = np.linspace(0, RL, NBINS + 1)
sel = np.abs(z - cz) <= thickness / 2.0
H, _, _ = np.histogram2d(x[sel], y[sel], bins=[edges, edges], weights=mass[sel])
sigma = H / (RL / NBINS) ** 2   # projected surface density, h^-1 Msun / (Mpc/h)^2
```
Render with matplotlib (`LogNorm`, `imshow`, mark the halo center), save as PNG --
this is a final human-facing artifact, plain `.png` is correct (no ADIOS2 needed).

An alternative `hacc_slice` binary exists (same `bin/` as `GenericIOPrint`) but is not
yet exercised end-to-end -- prefer the pure-Python approach unless you have a
specific reason to use it.

### ADIOS2 Engine Notes (when using the ADIOS engine)
The inter-stage numerical data the `systems/adios` skill's BP-file directive applies
to is: the parsed snapshot arrays (x,y,z,vx,vy,vz,phi,mass), the halo catalog arrays,
and the density-slice grid. The final `dm_density_slice.png` and `summary.txt` are
human-facing artifacts and stay as plain files regardless of engine mode.

---

## Common Pitfalls and Error Patterns

| Pitfall / error | What to do |
|---|---|
| `ModuleNotFoundError: No module named 'pygio._version'` | Expected -- it's not built. Use `GenericIOPrint` via `subprocess` instead; never try to build/install pygio. |
| `qsub`/`qstat` command not found or job ID not captured | Re-run via `submit_shell_task` with `cd .../SampleRun_go && qsub subme.pbs` -- qsub must run with that directory as cwd so `$PBS_O_WORKDIR` resolves. |
| GenericIOPrint output has no obvious "mass" column | Mass isn't stored per-particle here -- compute `mp` from `Omega_m`, `rho_crit0`, `RL`, `NP` and broadcast it. |
| Halo selection picks an unexpectedly small/odd halo | Select by `sod_halo_mass` (M_200c), excluding `sod_halo_count == -101` -- not by `fof_halo_mass`. |
| `qstat` shows the job immediately as gone | Check for the `<jobname>.o<jobid>` log file and fresh files in the output snapshot directory as completion evidence. |
| Visualization image missing or blank | Verify density_slice data was actually computed (non-zero `sigma`) before rendering; check the halo's z-coordinate was passed through correctly. |
| `hacc_slice` slice values look wrong / file size doesn't divide evenly | Check float32 vs float64 assumption first (`NG*NG*4` vs `NG*NG*8` bytes) rather than assuming a fixed dtype. |

---

## Output Files (in the work dir)

- `particles_step<N>.npz` / `.bp` -- raw snapshot arrays (x,y,z,vx,vy,vz,phi,mass)
- `halo_catalog.npz` / `.csv` -- parsed FOF+SOD halo catalog
- `most_massive_halo.npz` / `.txt` -- selected halo's M_200c, R_200c, center
- `density_slice.npy` / `.bp` + metadata -- the projected density grid
- `dm_density_slice.png` -- final rendered image (always a plain file, never `.bp`)
- `summary.txt` -- human-readable reproduction summary

## Notes

- Source data paths (the PBS script, snapshot, halo catalog) are real LCRC paths under
  `/lcrc/project/PEDAL/jacoboh/HACC/SampleRun_go/` -- external to the repo, reference
  by actual absolute path, not `/app/data/`.
- This is a single-trial-per-run workflow -- do not expect or require a GIF/animation
  output here, unlike `molecular_nucleation`.
- No source build step is needed for this use case -- everything HACC-related is
  already built on the cluster; install is fast (3-4 small packages).

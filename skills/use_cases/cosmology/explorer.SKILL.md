---
name: use_cases/cosmology/explorer
description: >
  Use-case-specific explorer rules for the HACC cosmology workflow (Last Journey
  sample run). Covers real qsub PBS submission, GenericIO reading via CLI tools
  (no pygio), halo catalog parsing, density-slice rendering, and known pitfalls.
---

# Cosmology (HACC) — Explorer Skill

Domain-specific guidance for the explorer agent when executing the HACC cosmological
N-body workflow (producer simulation -> FOF/SOD halo analysis -> dark-matter density
slice visualization), based on "The Last Journey" sample run.

---

## When to Use This Skill

Load this whenever the explorer is executing a workflow that submits/reads a HACC
run (paths under `/lcrc/project/PEDAL/jacoboh/HACC/`, `qsub`/`qstat`, GenericIO
snapshots, FOF/SOD halo catalogs).

---

## The Simulation Is a Private Black Box

The HACC executable (`hacc_tpm`) is closed-source. Never try to read, regenerate, or
reimplement its physics. Treat it purely as: submit the existing PBS script, wait for
it to finish, read its output. Do not modify `subme.pbs` or `params/indat.params`.

---

## Stage 1: Submit the Simulation (real qsub — this is an explicit exception)

**This is the one use case where submitting a brand-new PBS batch job via `qsub` is
allowed**, even from inside an already-running interactive PBS allocation. This
deliberately overrides the general LCRC rule ("never submit a new PBS job — run
inside the existing allocation instead"); that general rule still applies to every
other use case.

```
submit_shell_task(
    name="submit_hacc_job",
    command="cd /lcrc/project/PEDAL/jacoboh/HACC/SampleRun_go && qsub subme.pbs",
)
```

- Must `cd` into `SampleRun_go/` **before** `qsub` — the script does `cd $PBS_O_WORKDIR`
  and references `./params/indat.params` relatively, so `$PBS_O_WORKDIR` must equal
  `SampleRun_go/`.
- Capture the returned job ID, then poll with `qstat <job_id>` via `submit_shell_task`
  until the state is `C` (completed). Do not busy-loop with zero delay — space polls out.
- Job uses 8 MPI ranks (2x2x2 decomposition), `walltime=01:00:00`, job name
  `runme_mini_8r`, merged stdout+stderr (`-j oe`) written to `SampleRun_go/`.

---

## Stage 1b: Explore Before Assuming Anything

Before reading output, `list_files`/`submit_shell_task -c "ls -la ..."` the run
directory. Config values (FOF linking length, SOD Delta, box size `RL`, grid size
`NG`) live in `params/indat.params` and `params/cosmotools-config.dat` — read them,
never hardcode values from the paper without confirming they match this sample run.

---

## Stage 2: Reading Snapshot & Halo Data — Do NOT use pygio

`pygio` (in-tree at `HACC_go/submodules/genericio/python/pygio`) is **not built** —
importing it fails with `ModuleNotFoundError: No module named 'pygio._version'`.
Building it means compiling a C++ extension against the GenericIO libs — do not
attempt this. Instead use the pre-built CLI binaries directly via `subprocess`:

```
GIOP = "/lcrc/project/PEDAL/jacoboh/HACC/HACC_go/improv.cpu/frontend/bin/GenericIOPrint"
```

### Reading the particle snapshot
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
  shard — `GenericIOPrint` reads across all ranks for you.
- Header/comment lines start with `#`; the physical-coordinates line
  (`# physical coordinates: (0,0,0) -> (64,64,64)`) confirms the box bounds — use it
  to sanity-check `RL` from `indat.params` rather than trusting one source blindly.
- Particle mass is not a column — compute it: `mp = Omega_m * rho_crit0 * (RL/NP)**3`
  with `rho_crit0 = 2.77536627e11` (h^2 Msun/Mpc^3), `Omega_m` from cosmology params,
  `NP` = particles-per-side (`64` for this sample run, giving `64^3 = 262144` total).

### Reading the halo catalog
```python
HP = "/lcrc/project/PEDAL/jacoboh/HACC/SampleRun_go/analysis/haloproperties/step_624/m000p-624.haloproperties"
```
- The catalog **already exists** from a prior run under `analysis/haloproperties/step_<N>/`
  — do not hand-roll FOF/SOD linking in Python; this file is the halo finder's output.
- `GenericIOPrint` on this file gives a tab-separated header line listing ~76 columns
  including `fof_halo_count`, `fof_halo_mass`, `fof_halo_center_x/y/z`,
  `sod_halo_mass`, `sod_halo_radius`, `sod_halo_center_x/y/z`, etc. — parse the header
  to get column order rather than assuming a fixed schema.
- `fof_halo_center_*` is the min-potential center (most-bound particle), matching
  `USE_MBP_FINDER YES` in `cosmotools-config.dat`.
- **"Most massive halo" = row with max `sod_halo_mass` (M_200c)**, not `fof_halo_mass`.
  Rows with `sod_halo_count == -101` mean SOD was never computed for that (small) halo
  — exclude them before taking the max.
- Use the halo's center z-coordinate as the visualization slice center.

---

## Stage 3: Density Slice Visualization

Two valid approaches — pick whichever is simpler to get working; both are legitimate:

**A. Pure-Python (confirmed working)**: bin particle (x,y) into a 2D histogram weighted
by mass, restricted to particles within the slice thickness around the halo's z:
```python
NBINS = 256
edges = np.linspace(0, RL, NBINS + 1)
sel = np.abs(z - cz) <= thickness / 2.0
H, _, _ = np.histogram2d(x[sel], y[sel], bins=[edges, edges], weights=mass[sel])
sigma = H / (RL / NBINS) ** 2   # projected surface density, h^-1 Msun / (Mpc/h)^2
```

**B. `hacc_slice` binary (not yet exercised end-to-end, may need a slightly different
invocation)**: `hacc_slice <paramFile> <gioInBase> <outBase>` (in the same `bin/` as
`GenericIOPrint`/`hacc_tpm`) computes a CIC density grid directly from the raw
snapshot. `paramFile` must be a **copy** of `indat.params` (never edit the original)
with `SLICE_START`/`SLICE_STOP` appended — these are **fractions of the box in [0,1]
along z**, not Mpc/h: `SLICE_START=(z_h - T/2)/RL`, `SLICE_STOP=(z_h + T/2)/RL`. Output
is `<outBase>.slice`, a headerless raw binary of `NG*NG` floats written by rank 0 only
— disambiguate float32 vs float64 from file size (`NG*NG*4` vs `NG*NG*8` bytes), don't
assume.

Render with matplotlib (`LogNorm`, `imshow`, mark the halo center), save as PNG —
this is a final human-facing artifact, plain `.png` is correct (no ADIOS2 needed here).

---

## ADIOS2 Engine Notes (when `--engine adios`)

For this workflow specifically, the inter-stage numerical data that the `systems/adios`
skill's BP-file directive applies to is: the parsed snapshot arrays
(x,y,z,vx,vy,vz,phi,mass), the halo catalog arrays, and the density-slice grid. The
final `dm_density_slice.png` and `summary.txt` are human-facing artifacts and stay as
plain files regardless of engine mode (see that skill for the general producer/consumer
pattern and fallback behavior).

---

## Common Pitfalls

| Pitfall | Solution |
|---|---|
| `pygio` import fails (`No module named 'pygio._version'`) | Expected — it's not built. Use `GenericIOPrint` via `subprocess` instead; do not try to build/install pygio. |
| GenericIOPrint output has no obvious "mass" column | Mass isn't stored per-particle for this sample run — compute `mp` from `Omega_m`, `rho_crit0`, `RL`, `NP` (see above) and broadcast it. |
| Picking "most massive halo" by `fof_halo_mass` gives a different halo than expected | Use `sod_halo_mass` (M_200c), excluding rows where `sod_halo_count == -101`. |
| `qstat` shows the job immediately as gone | A completed PBS job can disappear from `qstat` quickly on some clusters — also check for the `<jobname>.o<jobid>` log file in `SampleRun_go/` as completion evidence, and check the output snapshot directory for fresh files. |
| `hacc_slice` slice values look wrong / file size doesn't divide evenly | Check float32 vs float64 assumption first (`NG*NG*4` vs `NG*NG*8` bytes) rather than assuming a fixed dtype. |

---

## Output Files (in the work dir)

- `particles_step<N>.npz` / `.bp` — raw snapshot arrays (x,y,z,vx,vy,vz,phi,mass)
- `halo_catalog.npz` / `.csv` — parsed FOF+SOD halo catalog
- `most_massive_halo.npz` / `.txt` — selected halo's M_200c, R_200c, center
- `density_slice.npy` / `.bp` + metadata — the projected density grid
- `dm_density_slice.png` — final rendered image (always a plain file, never `.bp`)
- `summary.txt` — human-readable reproduction summary (job ID, config values used, results)

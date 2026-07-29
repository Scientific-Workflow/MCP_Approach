#!/usr/bin/env python3
"""
analyze_and_render.py -- HACC Last Journey SampleRun analysis + visualization.
    
Runs standalone inside the PBS job right after hacc_tpm. Reads this run's OWN
freshly produced GenericIO snapshot and halo catalog via the GenericIOPrint CLI,
selects the most massive SOD halo, computes a 4 Mpc/h-thick xy density slice
centered on that halo's z, and renders dm_density_slice.png + summary.txt.
    
Uses REAL absolute paths (invoked directly by PBS, no MCP /app resolution).
"""
import os
import sys
import subprocess
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
    
# ---------------------------------------------------------------------------
# Absolute paths (this script runs standalone under PBS)
# ---------------------------------------------------------------------------
WORK  = "/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0"
SR    = "/lcrc/project/PEDAL/jacoboh/HACC/SampleRun_go"
GIOP  = "/lcrc/project/PEDAL/jacoboh/HACC/HACC_go/improv.cpu/frontend/bin/GenericIOPrint"
    
STEP  = 624   # final full snapshot / halo step from indat.params
SNAP  = os.path.join(SR, "output", "full_snapshots", "step_%d" % STEP,
                     "m000p.full.mpicosmo.%d" % STEP)
HALO  = os.path.join(SR, "analysis", "haloproperties", "step_%d" % STEP,
                     "m000p-%d.haloproperties" % STEP)
    
# ---------------------------------------------------------------------------
# Config values read from this run's params/indat.params
# ---------------------------------------------------------------------------
RL        = 64.0        # box length [Mpc/h]
NG        = 64          # grid
NP        = 64          # particles per side  -> NP**3 total
OMEGA_CDM = 0.26067
DEUT      = 0.02242     # Omega_b * h^2
HUBBLE    = 0.6766
OMEGA_B   = DEUT / HUBBLE**2
OMEGA_M   = OMEGA_CDM + OMEGA_B
RHO_CRIT0 = 2.77536627e11   # h^2 Msun / Mpc^3
SLICE_THICKNESS = 4.0       # Mpc/h
NBINS = 256
    
os.makedirs(WORK, exist_ok=True)
    
def die(msg):
    print("ERROR:", msg, file=sys.stderr)
    sys.exit(1)
    
# ---------------------------------------------------------------------------
# 1. Read the particle snapshot via GenericIOPrint
# ---------------------------------------------------------------------------
print("Reading snapshot:", SNAP, flush=True)
if not os.path.exists(SNAP):
    # try to discover the actual master file name in the step dir
    stepdir = os.path.dirname(SNAP)
    if os.path.isdir(stepdir):
        cands = [f for f in os.listdir(stepdir) if "#" not in f]
        print("Snapshot candidates in %s: %s" % (stepdir, cands), flush=True)
        if cands:
            globalname = os.path.join(stepdir, sorted(cands, key=len)[0])
            print("Using candidate:", globalname, flush=True)
            SNAP_USE = globalname
        else:
            die("No snapshot master file found in %s" % stepdir)
    else:
        die("Snapshot step dir does not exist: %s" % stepdir)
else:
    SNAP_USE = SNAP
    
out = subprocess.run([GIOP, SNAP_USE], capture_output=True, text=True)
if out.returncode != 0:
    print("GenericIOPrint stderr:\n", out.stderr[:3000], flush=True)
    die("GenericIOPrint failed on snapshot")
    
# Determine which columns are x,y,z from the header if possible.
header_cols = None
rows = []
for ln in out.stdout.splitlines():
    s = ln.strip()
    if not s:
        continue
    if s.startswith("#"):
        low = s.lower()
        # capture a header listing variable names like: # x y z vx vy vz phi
        if header_cols is None and (" x " in (" " + low + " ")) and " y " in (" " + low + " "):
            toks = s.lstrip("#").split()
            # only accept if it looks like column names (contains 'x','y','z')
            if "x" in toks and "y" in toks and "z" in toks:
                header_cols = toks
        continue
    parts = s.split()
    if len(parts) < 3:
        continue
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        continue
    rows.append(vals)
    
if not rows:
    print("Snapshot stdout head:\n", "\n".join(out.stdout.splitlines()[:40]), flush=True)
    die("No particle rows parsed from snapshot")
    
arr = np.array([r[:7] for r in rows if len(r) >= 7], dtype=np.float64)
if arr.shape[0] == 0:
    # fall back to at least x,y,z
    arr3 = np.array([r[:3] for r in rows if len(r) >= 3], dtype=np.float64)
    x, y, z = arr3[:, 0], arr3[:, 1], arr3[:, 2]
    vx = vy = vz = phi = np.zeros_like(x)
else:
    x, y, z, vx, vy, vz, phi = (arr[:, i] for i in range(7))
    
npart = x.shape[0]
print("Parsed %d particles" % npart, flush=True)
print("x range [%.3f, %.3f]  y [%.3f, %.3f]  z [%.3f, %.3f]" %
      (x.min(), x.max(), y.min(), y.max(), z.min(), z.max()), flush=True)
    
# Particle mass (not stored per-particle): mp = Omega_m * rho_crit0 * (RL/NP)^3
mp = OMEGA_M * RHO_CRIT0 * (RL / NP) ** 3
mass = np.full(npart, mp, dtype=np.float64)
print("Particle mass mp = %.6e h^-1 Msun (Omega_m=%.5f)" % (mp, OMEGA_M), flush=True)
    
# Save raw arrays (parsl engine -> .npz, no ADIOS)
np.savez(os.path.join(WORK, "particles_step%d.npz" % STEP),
         x=x, y=y, z=z, vx=vx, vy=vy, vz=vz, phi=phi, mass=mass)
    
# ---------------------------------------------------------------------------
# 2. Read the halo catalog, select most massive by sod_halo_mass
# ---------------------------------------------------------------------------
print("Reading halo catalog:", HALO, flush=True)
cz = RL / 2.0          # default slice center = box center
halo_mass = None
halo_pos = None
halo_info = "no halo catalog available; using box center for slice"
    
if os.path.exists(HALO):
    hout = subprocess.run([GIOP, HALO], capture_output=True, text=True)
    if hout.returncode != 0:
        print("GenericIOPrint halo stderr:\n", hout.stderr[:2000], flush=True)
    else:
        # parse header to get column order
        colnames = None
        hrows = []
        for ln in hout.stdout.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.startswith("#"):
                toks = s.lstrip("#").split()
                if ("sod_halo_mass" in toks) or ("fof_halo_mass" in toks):
                    colnames = toks
                continue
            parts = s.split()
            try:
                vals = [float(p) for p in parts]
            except ValueError:
                continue
            hrows.append(vals)
    
        if colnames and hrows:
            idx = {name: i for i, name in enumerate(colnames)}
            H = np.array([r for r in hrows if len(r) >= len(colnames)], dtype=np.float64)
            print("Parsed %d halos, columns=%d" % (H.shape[0], len(colnames)), flush=True)
            if H.shape[0] > 0 and "sod_halo_mass" in idx:
                sm = H[:, idx["sod_halo_mass"]]
                # exclude sod_halo_count == -101 (SOD not computed)
                if "sod_halo_count" in idx:
                    valid = H[:, idx["sod_halo_count"]] != -101
                else:
                    valid = sm > 0
                if valid.any():
                    Hv = H[valid]
                    smv = Hv[:, idx["sod_halo_mass"]]
                    k = int(np.argmax(smv))
                    halo_mass = float(smv[k])
                    def gc(name, default):
                        return float(Hv[k, idx[name]]) if name in idx else default
                    hx = gc("sod_halo_center_x", gc("fof_halo_center_x", cz))
                    hy = gc("sod_halo_center_y", gc("fof_halo_center_y", cz))
                    hz = gc("sod_halo_center_z", gc("fof_halo_center_z", cz))
                    r200 = gc("sod_halo_radius", float("nan"))
                    halo_pos = (hx, hy, hz)
                    cz = hz
                    halo_info = ("most massive SOD halo: M_200c=%.6e h^-1 Msun, "
                                 "R_200c=%.4f Mpc/h, center=(%.4f, %.4f, %.4f)" %
                                 (halo_mass, r200, hx, hy, hz))
                    print(halo_info, flush=True)
                else:
                    print("No valid SOD halos (all sod_halo_count==-101); using box center", flush=True)
            else:
                print("No sod_halo_mass column or no halos; using box center", flush=True)
        else:
            print("Could not parse halo header/rows; using box center", flush=True)
else:
    print("Halo catalog not found:", HALO, "-- using box center", flush=True)
    
# ---------------------------------------------------------------------------
# 3. Compute the 4 Mpc/h-thick xy density slice centered on halo z
# ---------------------------------------------------------------------------
edges = np.linspace(0.0, RL, NBINS + 1)
sel = np.abs(z - cz) <= (SLICE_THICKNESS / 2.0)
nsel = int(sel.sum())
print("Slice: cz=%.4f, thickness=%.1f Mpc/h, %d particles in slab" %
      (cz, SLICE_THICKNESS, nsel), flush=True)
    
Hgrid, _, _ = np.histogram2d(x[sel], y[sel], bins=[edges, edges], weights=mass[sel])
cell_area = (RL / NBINS) ** 2
sigma = Hgrid / cell_area   # projected surface density [h^-1 Msun / (Mpc/h)^2]
    
np.save(os.path.join(WORK, "density_slice.npy"), sigma)
    
# ---------------------------------------------------------------------------
# 4. Render
# ---------------------------------------------------------------------------
plt.style.use("dark_background")
fig, ax = plt.subplots(figsize=(8, 8))
disp = sigma.T.copy()
pos = disp[disp > 0]
vmin = pos.min() if pos.size else 1.0
vmax = disp.max() if disp.max() > 0 else 10.0
disp[disp <= 0] = vmin
im = ax.imshow(disp, origin="lower", extent=[0, RL, 0, RL],
               norm=LogNorm(vmin=vmin, vmax=vmax), cmap="inferno",
               interpolation="nearest")
if halo_pos is not None:
    ax.plot(halo_pos[0], halo_pos[1], marker="o", ms=14, mfc="none",
            mec="cyan", mew=1.8, label="most massive halo")
    ax.legend(loc="upper right", framealpha=0.3)
ax.set_xlabel("x [h$^{-1}$ Mpc]")
ax.set_ylabel("y [h$^{-1}$ Mpc]")
ax.set_title("HACC Last Journey SampleRun -- DM density slice (z=0, step %d)\n"
             "%.1f h$^{-1}$Mpc-thick slab at z=%.2f h$^{-1}$Mpc" %
             (STEP, SLICE_THICKNESS, cz))
cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
cb.set_label(r"$\Sigma$ [h$^{-1}$M$_\odot$ / (h$^{-1}$Mpc)$^2$]")
fig.tight_layout()
png = os.path.join(WORK, "dm_density_slice.png")
fig.savefig(png, dpi=130)
plt.close(fig)
print("Wrote", png, flush=True)
    
# ---------------------------------------------------------------------------
# 5. Summary
# ---------------------------------------------------------------------------
lines = []
lines.append("HACC Last Journey SampleRun -- reproduction summary")
lines.append("=" * 60)
lines.append("Snapshot step               : %d (z=0)" % STEP)
lines.append("Box length RL               : %.3f h^-1 Mpc" % RL)
lines.append("Grid NG                     : %d" % NG)
lines.append("Particles per side NP       : %d (%d total expected)" % (NP, NP**3))
lines.append("Particles parsed            : %d" % npart)
lines.append("Omega_cdm                   : %.5f" % OMEGA_CDM)
lines.append("Omega_b (=DEUT/h^2)         : %.5f" % OMEGA_B)
lines.append("Omega_m                     : %.5f" % OMEGA_M)
lines.append("Hubble h                    : %.4f" % HUBBLE)
lines.append("Particle mass mp            : %.6e h^-1 Msun" % mp)
lines.append("FOF linking length b        : 0.168")
lines.append("SOD overdensity Delta       : 200 (M_200c)")
lines.append("-" * 60)
lines.append("Most massive halo           : %s" % halo_info)
if halo_mass is not None:
    lines.append("  M_200c                    : %.6e h^-1 Msun" % halo_mass)
if halo_pos is not None:
    lines.append("  center (x,y,z)            : (%.4f, %.4f, %.4f) h^-1 Mpc" % halo_pos)
lines.append("-" * 60)
lines.append("Density slice thickness     : %.1f h^-1 Mpc" % SLICE_THICKNESS)
lines.append("Slice center z              : %.4f h^-1 Mpc" % cz)
lines.append("Particles in slab           : %d" % nsel)
lines.append("Slice grid                  : %d x %d bins" % (NBINS, NBINS))
lines.append("Output image                : dm_density_slice.png")
summary = os.path.join(WORK, "summary.txt")
with open(summary, "w") as f:
    f.write("\n".join(lines) + "\n")
print("Wrote", summary, flush=True)
print("\n".join(lines), flush=True)
print("DONE", flush=True)
    
import sys, os, traceback

os.makedirs("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0")

# ADIOS2 is available -- import it for use in task code
import adios2

try:
    # --- User task code (ADIOS2 mode) ---
    import os, textwrap
    
    script = r'''#!/usr/bin/env python3
    """
    analyze_and_render.py -- Last Journey (mini SampleRun_go) analysis + rendering.
    
    Reads THIS run's fresh HACC producer output via GenericIOPrint (the HACC
    genericIO text dumper), selects the most massive SO halo, and renders a
    4 Mpc/h-thick dark-matter density slice centered on that halo's z-coordinate.
    
    Config values are taken from the run's own param files (indat.params /
    cosmotools-config.dat), not fabricated.
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
    # Paths (real absolute paths; this runs standalone inside the PBS job)
    # ---------------------------------------------------------------------------
    RUNDIR   = "/lcrc/project/PEDAL/jacoboh/HACC/SampleRun_go"
    OUTDIR   = "/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0"
    ENVFILE  = "/lcrc/project/PEDAL/jacoboh/HACC/HACC_go/env/bashrc.improv.cpu"
    GIOPRINT = "/lcrc/project/PEDAL/jacoboh/HACC/HACC_go/improv.cpu/mpi/bin/GenericIOPrint"
    
    STEP = "624"                                   # final step, z ~ 0
    SNAP = os.path.join(RUNDIR, "output", "full_snapshots",
                        "step_%s" % STEP, "m000p.full.mpicosmo.%s" % STEP)
    HALO = os.path.join(RUNDIR, "analysis", "haloproperties",
                        "step_%s" % STEP, "m000p-%s.haloproperties" % STEP)
    
    os.makedirs(OUTDIR, exist_ok=True)
    PNG = os.path.join(OUTDIR, "dm_density_slice.png")
    SUMMARY = os.path.join(OUTDIR, "summary.txt")
    
    # ---------------------------------------------------------------------------
    # Cosmology / run config (from indat.params + cosmotools-config.dat)
    # ---------------------------------------------------------------------------
    OMEGA_CDM = 0.26067
    DEUT      = 0.02242        # Omega_b * h^2
    HUBBLE    = 0.6766         # h
    OMEGA_B   = DEUT / HUBBLE**2
    OMEGA_M   = OMEGA_CDM + OMEGA_B          # total matter
    RL        = 64.0          # box size [Mpc/h]
    NP        = 64            # particles per dimension
    NG        = 64
    FOF_B     = 0.168         # FOF linking length
    SOD_DELTA = 200.0         # SOD overdensity
    SLICE_THICKNESS = 4.0     # Mpc/h
    
    # rho_crit,0 in h^2 M_sun / Mpc^3  (G in these units): 2.77536627e11
    RHO_CRIT0 = 2.77536627e11
    # Per-particle mass [M_sun/h]:  m_p = Omega_m * rho_crit0 * (RL/NP)^3 ... in h^-1 units
    # In HACC units (RL in Mpc/h, masses in M_sun/h):
    #   total matter mass in box = Omega_m * rho_crit0 * RL^3   [M_sun/h]
    #   m_p = that / NP^3
    M_PARTICLE = OMEGA_M * RHO_CRIT0 * (RL**3) / (NP**3)
    
    print("[cfg] Omega_m=%.5f  Omega_b=%.5f  h=%.4f  RL=%.1f  NP=%d"
          % (OMEGA_M, OMEGA_B, HUBBLE, RL, NP))
    print("[cfg] per-particle mass m_p = %.4e M_sun/h" % M_PARTICLE)
    print("[cfg] FOF b=%.3f  SOD Delta=%.0f  slice=%.1f Mpc/h" % (FOF_B, SOD_DELTA, SLICE_THICKNESS))
    
    
    # ---------------------------------------------------------------------------
    # GenericIO reading via GenericIOPrint (tab-separated text dump)
    # ---------------------------------------------------------------------------
    def run_gioprint(path):
        """Run GenericIOPrint under the HACC build env; return stdout text."""
        if not (os.path.exists(path) or os.path.exists(path + "#0")):
            raise FileNotFoundError("GenericIO dataset not found: %s" % path)
        cmd = "source %s >/dev/null 2>&1; %s %s" % (ENVFILE, GIOPRINT, path)
        res = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True)
        if res.returncode != 0 and not res.stdout:
            raise RuntimeError("GenericIOPrint failed on %s:\n%s" % (path, res.stderr[-2000:]))
        return res.stdout
    
    
    def parse_gio_table(text):
        """
        Parse GenericIOPrint output. The variable-name header is the first '#'
        comment line that is a pure tab-separated list of column names (i.e. it
        contains a TAB and does NOT start with '# (' type line, and is not a
        'rank ...' or 'variables' descriptor). Data rows are the non-'#' lines.
        Returns (colnames list, 2D numpy float array).
        """
        lines = text.splitlines()
        colnames = None
        for ln in lines:
            if ln.startswith("#") and "\t" in ln:
                body = ln.lstrip("#").strip()
                toks = body.split("\t")
                # skip the type descriptor line like "(s32)\t(s64)\t..."
                if all(t.strip().startswith("(") for t in toks):
                    continue
                # skip descriptor lines like "x variables: x"
                if "variables:" in body or body.startswith("rank "):
                    continue
                if "physical coordinates" in body:
                    continue
                # This is the column-name header
                colnames = [t.strip() for t in toks]
                break
        if colnames is None:
            raise RuntimeError("Could not locate tab-separated column header in GenericIOPrint output")
    
        rows = []
        ncol = len(colnames)
        for ln in lines:
            if not ln or ln.startswith("#"):
                continue
            toks = ln.split("\t")
            if len(toks) != ncol:
                continue
            try:
                rows.append([float(t) for t in toks])
            except ValueError:
                continue
        if not rows:
            raise RuntimeError("No data rows parsed from GenericIOPrint output")
        return colnames, np.asarray(rows, dtype=np.float64)
    
    
    # ---------------------------------------------------------------------------
    # 1. Read halo catalog and select most massive SO halo
    # ---------------------------------------------------------------------------
    print("\n[halo] reading %s" % HALO)
    htxt = run_gioprint(HALO)
    hcols, hdata = parse_gio_table(htxt)
    cidx = {name: i for i, name in enumerate(hcols)}
    print("[halo] %d halos, %d columns" % (hdata.shape[0], len(hcols)))
    
    for req in ("sod_halo_mass", "sod_halo_count", "fof_halo_mass",
                "sod_halo_center_x", "sod_halo_center_y", "sod_halo_center_z",
                "fof_halo_center_x", "fof_halo_center_y", "fof_halo_center_z"):
        if req not in cidx:
            raise RuntimeError("Expected halo column '%s' not found" % req)
    
    sod_mass  = hdata[:, cidx["sod_halo_mass"]]
    sod_count = hdata[:, cidx["sod_halo_count"]]
    fof_mass  = hdata[:, cidx["fof_halo_mass"]]
    
    # Exclude invalid SO halos (sod_halo_count == -101 marks "no valid SO halo")
    valid = sod_count != -101
    n_valid = int(np.count_nonzero(valid))
    print("[halo] valid SO halos (sod_halo_count != -101): %d / %d" % (n_valid, hdata.shape[0]))
    
    if n_valid == 0:
        # Fall back to FOF mass if no valid SO halo exists in this mini run
        print("[halo] WARNING: no valid SO halos; falling back to most massive FOF halo")
        sel = int(np.argmax(fof_mass))
        sel_mass = fof_mass[sel]
        cx = hdata[sel, cidx["fof_halo_center_x"]]
        cy = hdata[sel, cidx["fof_halo_center_y"]]
        cz = hdata[sel, cidx["fof_halo_center_z"]]
        mass_kind = "FOF (fof_halo_mass, no valid SO halo)"
    else:
        masked = np.where(valid, sod_mass, -np.inf)
        sel = int(np.argmax(masked))
        sel_mass = sod_mass[sel]
        cx = hdata[sel, cidx["sod_halo_center_x"]]
        cy = hdata[sel, cidx["sod_halo_center_y"]]
        cz = hdata[sel, cidx["sod_halo_center_z"]]
        mass_kind = "SO (sod_halo_mass, M_200c)"
    
    sel_fofmass = fof_mass[sel]
    sel_fofcount = hdata[sel, cidx["fof_halo_count"]] if "fof_halo_count" in cidx else float("nan")
    print("[halo] selected halo idx=%d  mass=%.4e M_sun/h  center=(%.3f, %.3f, %.3f)"
          % (sel, sel_mass, cx, cy, cz))
    print("[halo] selected halo FOF mass=%.4e  FOF count=%.0f  kind=%s"
          % (sel_fofmass, sel_fofcount, mass_kind))
    
    
    # ---------------------------------------------------------------------------
    # 2. Read particle snapshot
    # ---------------------------------------------------------------------------
    print("\n[part] reading %s" % SNAP)
    ptxt = run_gioprint(SNAP)
    pcols, pdata = parse_gio_table(ptxt)
    pidx = {name: i for i, name in enumerate(pcols)}
    print("[part] %d particles, columns=%s" % (pdata.shape[0], pcols))
    
    for req in ("x", "y", "z"):
        if req not in pidx:
            raise RuntimeError("Expected particle column '%s' not found" % req)
    
    px = pdata[:, pidx["x"]]
    py = pdata[:, pidx["y"]]
    pz = pdata[:, pidx["z"]]
    n_part = px.size
    print("[part] loaded %d particles; total mass = %.4e M_sun/h"
          % (n_part, n_part * M_PARTICLE))
    
    
    # ---------------------------------------------------------------------------
    # 3. Build 4 Mpc/h-thick xy density slice centered on halo z
    # ---------------------------------------------------------------------------
    half = SLICE_THICKNESS / 2.0
    dz = np.abs(pz - cz)
    # periodic wrap in z
    dz = np.minimum(dz, RL - dz)
    in_slab = dz <= half
    n_slab = int(np.count_nonzero(in_slab))
    print("\n[slice] z-center=%.3f  thickness=%.1f Mpc/h  particles in slab=%d"
          % (cz, SLICE_THICKNESS, n_slab))
    
    nbins = 256
    edges = np.linspace(0.0, RL, nbins + 1)
    H, xe, ye = np.histogram2d(px[in_slab], py[in_slab], bins=[edges, edges])
    # convert counts to surface mass density [M_sun/h per (Mpc/h)^2]
    cell_area = (RL / nbins) ** 2
    sigma = (H * M_PARTICLE) / (cell_area * SLICE_THICKNESS)  # 3D-ish density in slab
    # For plotting use projected mass density (counts * m_p / cell_area)
    proj = (H.T * M_PARTICLE) / cell_area
    
    # ---------------------------------------------------------------------------
    # 4. Render with LogNorm
    # ---------------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(8, 7.2))
    pos = proj[proj > 0]
    vmin = pos.min() if pos.size else 1.0
    vmax = proj.max() if proj.max() > 0 else 10.0
    im = ax.imshow(proj, origin="lower", extent=[0, RL, 0, RL],
                   cmap="inferno", norm=LogNorm(vmin=max(vmin, vmax * 1e-4), vmax=vmax),
                   interpolation="nearest")
    # mark the selected halo center
    ax.plot(cx, cy, marker="+", color="cyan", markersize=16, markeredgewidth=2)
    ax.set_xlabel(r"x  [$h^{-1}$ Mpc]")
    ax.set_ylabel(r"y  [$h^{-1}$ Mpc]")
    ax.set_title("Last Journey (mini) -- DM density slice, z~0 (step %s)\n"
                 "%.1f $h^{-1}$Mpc slab @ z=%.2f; most massive halo M=%.3e $h^{-1}M_\\odot$"
                 % (STEP, SLICE_THICKNESS, cz, sel_mass), fontsize=10)
    cb = fig.colorbar(im, ax=ax)
    cb.set_label(r"projected $\Sigma$  [$h\,M_\odot\,(h^{-1}\mathrm{Mpc})^{-2}$]")
    fig.tight_layout()
    fig.savefig(PNG, dpi=130)
    plt.close(fig)
    print("[render] wrote %s" % PNG)
    
    
    # ---------------------------------------------------------------------------
    # 5. Summary
    # ---------------------------------------------------------------------------
    with open(SUMMARY, "w") as f:
        f.write("Last Journey (SampleRun_go mini) -- analysis summary\n")
        f.write("=" * 60 + "\n\n")
        f.write("Snapshot : %s\n" % SNAP)
        f.write("Halo cat : %s\n" % HALO)
        f.write("Step     : %s (z ~ 0)\n\n" % STEP)
        f.write("Cosmology / run config (from param files):\n")
        f.write("  Omega_cdm = %.5f\n" % OMEGA_CDM)
        f.write("  Omega_b   = %.5f (DEUT=%.5f, h=%.4f)\n" % (OMEGA_B, DEUT, HUBBLE))
        f.write("  Omega_m   = %.5f\n" % OMEGA_M)
        f.write("  h         = %.4f\n" % HUBBLE)
        f.write("  RL        = %.1f Mpc/h\n" % RL)
        f.write("  NG = %d, NP = %d  (NP^3 = %d particles)\n" % (NG, NP, NP**3))
        f.write("  FOF linking length b = %.3f\n" % FOF_B)
        f.write("  SOD overdensity Delta = %.0f x rho_crit\n" % SOD_DELTA)
        f.write("  per-particle mass m_p = %.6e M_sun/h\n\n" % M_PARTICLE)
        f.write("Particle snapshot:\n")
        f.write("  columns        : %s\n" % ", ".join(pcols))
        f.write("  N particles    : %d\n" % n_part)
        f.write("  total mass     : %.4e M_sun/h\n\n" % (n_part * M_PARTICLE))
        f.write("Halo catalog:\n")
        f.write("  N halos        : %d\n" % hdata.shape[0])
        f.write("  valid SO halos : %d (excluding sod_halo_count == -101)\n\n" % n_valid)
        f.write("Selected (most massive) halo:\n")
        f.write("  selection basis: %s\n" % mass_kind)
        f.write("  index          : %d\n" % sel)
        f.write("  mass           : %.6e M_sun/h\n" % sel_mass)
        f.write("  fof_halo_mass  : %.6e M_sun/h\n" % sel_fofmass)
        f.write("  fof_halo_count : %.0f particles\n" % sel_fofcount)
        f.write("  center (x,y,z) : (%.4f, %.4f, %.4f) Mpc/h\n\n" % (cx, cy, cz))
        f.write("Density slice:\n")
        f.write("  thickness      : %.1f Mpc/h\n" % SLICE_THICKNESS)
        f.write("  z-center       : %.4f Mpc/h (halo z)\n" % cz)
        f.write("  particles/slab : %d\n" % n_slab)
        f.write("  grid           : %d x %d bins over %.1f Mpc/h box\n" % (nbins, nbins, RL))
        f.write("  output image   : %s\n" % PNG)
    
    print("[summary] wrote %s" % SUMMARY)
    print("\n=== ANALYSIS COMPLETE ===")
    '''
    
    path = "/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/analyze_and_render.py"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(script)
    print("wrote", path, len(script), "bytes")
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

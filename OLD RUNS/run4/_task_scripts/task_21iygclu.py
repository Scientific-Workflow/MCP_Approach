import sys, os, traceback

os.makedirs("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0")

# ADIOS2 is available -- import it for use in task code
import adios2

try:
    # --- User task code (ADIOS2 mode) ---
    import os, csv
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    
    timesteps, cubic, hexc, total, nucleated_flags = [], [], [], [], []
    with open("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/results.csv") as f:
        for row in csv.DictReader(f):
            timesteps.append(int(float(row["timestep"])))
            cubic.append(int(row["cubic_diamond_count"]))
            hexc.append(int(row["hexagonal_diamond_count"]))
            total.append(int(row["total_crystallized"]))
            nucleated_flags.append(row.get("nucleated","no"))
    
    # total atoms = 4360 -> threshold
    total_atoms = 4360
    threshold = total_atoms / 8.0
    
    fig, ax = plt.subplots(figsize=(10,6))
    ax.plot(timesteps, cubic, color="#0000FF", marker="o", markersize=4, label="Cubic Diamond (Ice Ic)")
    ax.plot(timesteps, hexc, color="#FF2200", marker="s", markersize=4, label="Hexagonal Diamond (Ice Ih)")
    ax.plot(timesteps, total, "k--", linewidth=1.5, alpha=0.6, label="Total Ice")
    ax.axhline(threshold, color="green", linestyle=":", linewidth=1.5, label=f"Nucleation threshold (1/8 = {threshold:.0f})")
    
    # Mark first nucleation crossing
    first_nuc = None
    for t, fl in zip(timesteps, nucleated_flags):
        if fl == "yes":
            first_nuc = t
            break
    if first_nuc is not None:
        ax.axvline(first_nuc, color="purple", linestyle="-", linewidth=2, alpha=0.7,
                   label=f"First nucleation @ ts={first_nuc}")
    else:
        ax.text(0.5, 0.95, "No nucleation observed (threshold not crossed)\n— consistent with stochastic nucleation (paper: 1/60 events)",
                transform=ax.transAxes, ha="center", va="top", fontsize=9,
                bbox=dict(boxstyle="round", fc="#FFFFCC", ec="gray"))
    
    ax.set_xlabel("Timestep")
    ax.set_ylabel("Ice-like Atoms")
    ax.set_title("Water Freezing: Nucleation Progress (4360 atoms, 180K)")
    ax.legend(loc="center right", fontsize=8)
    ax.grid(True, alpha=0.3)
    
    out = "/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/renders/nucleation_timeseries.png"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("Timeseries plot saved:", out)
    print("First nucleation crossing:", first_nuc)
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

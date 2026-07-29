import sys, os, traceback

# Ensure working directory exists
os.makedirs("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0")
try:
    # --- User task code ---
    import os, csv
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    
    timesteps, cubic_counts, hex_counts = [], [], []
    with open("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/results.csv") as f:
        for row in csv.DictReader(f):
            timesteps.append(int(float(row["timestep"])))
            cubic_counts.append(int(row["cubic_diamond_count"]))
            hex_counts.append(int(row["hexagonal_diamond_count"]))
    
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(timesteps, cubic_counts, color="#0000FF", marker="o", markersize=4, label="Cubic Diamond (Ice Ic)")
    ax.plot(timesteps, hex_counts, color="#FF2200", marker="s", markersize=4, label="Hexagonal Diamond (Ice Ih)")
    total_ice = [c + h for c, h in zip(cubic_counts, hex_counts)]
    ax.plot(timesteps, total_ice, "k--", linewidth=1.5, alpha=0.6, label="Total Ice")
    ax.set_xlabel("Timestep"); ax.set_ylabel("Ice-like Atoms")
    ax.set_title("Water Freezing: Nucleation Progress"); ax.legend(); ax.grid(True, alpha=0.3)
    
    render_dir = "/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/renders"
    os.makedirs(render_dir, exist_ok=True)
    fig.savefig(os.path.join(render_dir, "nucleation_timeseries.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("Timeseries plot saved -> nucleation_timeseries.png")
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

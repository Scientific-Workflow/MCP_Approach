import sys, os, traceback

os.makedirs("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0")

from pycompss.api.api import compss_start, compss_stop, compss_wait_on
from pycompss.api.task import task
from pycompss.api.parameter import INOUT, IN

try:
    compss_start()

    @task(returns=str)
    def _user_task():
        import os, csv
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        
        timesteps, cubic_counts, hex_counts = [], [], []
        with open("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/results.csv") as f:
            for row in csv.DictReader(f):
                timesteps.append(int(float(row["timestep"])))
                cubic_counts.append(int(row["cubic_diamond_count"]))
                hex_counts.append(int(row["hexagonal_diamond_count"]))
        total_ice = [c + h for c, h in zip(cubic_counts, hex_counts)]
        
        # Parse nucleation onset (if any) from summary
        onset_ts = None
        verdict = "UNKNOWN"
        sp = "/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/nucleation_summary.txt"
        if os.path.exists(sp):
            with open(sp) as f:
                for line in f:
                    if "verdict" in line.lower():
                        verdict = line.split(":",1)[1].strip()
                    if "First frame crossing threshold" in line:
                        import re
                        m = re.search(r"timestep (\d+)", line)
                        if m: onset_ts = int(m.group(1))
        
        TOTAL_ATOMS = 4360
        threshold = TOTAL_ATOMS / 8.0
        
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(timesteps, cubic_counts, color="#0000FF", marker="o", markersize=4, label="Cubic Diamond (Ice Ic)")
        ax.plot(timesteps, hex_counts,   color="#FF2200", marker="s", markersize=4, label="Hexagonal Diamond (Ice Ih)")
        ax.plot(timesteps, total_ice, "k--", linewidth=1.5, alpha=0.6, label="Total Ice")
        ax.axhline(threshold, color="green", linestyle=":", linewidth=1.5, alpha=0.7,
                   label=f"Nucleation threshold (1/8 = {threshold:.0f})")
        
        if onset_ts is not None:
            ax.axvline(onset_ts, color="purple", linestyle="-", alpha=0.7)
            ax.annotate(f"Nucleation onset\nt={onset_ts}", xy=(onset_ts, threshold),
                        xytext=(onset_ts, threshold*1.2),
                        arrowprops=dict(arrowstyle="->", color="purple"), color="purple")
        else:
            ax.text(0.5, 0.92, f"Verdict: {verdict} (no frame crossed threshold)",
                    transform=ax.transAxes, ha="center", fontsize=10,
                    bbox=dict(boxstyle="round", fc="#FFFFCC", ec="gray"))
        
        ax.set_xlabel("Timestep"); ax.set_ylabel("Ice-like Atoms")
        ax.set_title("Water Freezing: Nucleation Progress (4360 atoms, 180 K)")
        ax.legend(loc="upper left"); ax.grid(True, alpha=0.3)
        
        render_dir = "/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/renders"
        os.makedirs(render_dir, exist_ok=True)
        out = os.path.join(render_dir, "nucleation_timeseries.png")
        fig.savefig(out, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"Timeseries plot saved: {out}")
        return "__TASK_SUCCESS__"

    result = _user_task()
    result = compss_wait_on(result)
    print(result)

    compss_stop()
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    try:
        compss_stop()
    except Exception:
        pass
    sys.exit(1)

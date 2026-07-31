import sys, os, traceback

# Ensure working directory exists
os.makedirs("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0")
try:
    # --- User task code ---
    import os
    os.environ["LIBGL_ALWAYS_SOFTWARE"]="1"
    os.environ["PYOPENGL_PLATFORM"]="osmesa"
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    
    d = np.load("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/psi_final.npz")
    psi, GX, GY = d["psi"], d["GX"], d["GY"]
    t = float(d["time"])
    
    fig, ax = plt.subplots(figsize=(7,6))
    cf = ax.contourf(GX, GY, psi, levels=40, cmap="RdBu_r")
    ax.contour(GX, GY, psi, levels=20, colors='k', linewidths=0.4, alpha=0.6)
    cb = fig.colorbar(cf, ax=ax)
    cb.set_label(r"stream function $\psi$")
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.set_aspect("equal")
    ax.set_title(f"Reconstructed stream function (eddy_uv, final frame, t={t:.3f})")
    fig.tight_layout()
    fig.savefig("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/streamfunction_final.png", dpi=130)
    print("saved streamfunction_final.png")
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

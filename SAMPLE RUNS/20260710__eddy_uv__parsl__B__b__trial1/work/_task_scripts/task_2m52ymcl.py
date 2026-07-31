import sys, os, traceback

# Ensure working directory exists
os.makedirs("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0")
try:
    # --- User task code ---
    import os
    os.environ["LIBGL_ALWAYS_SOFTWARE"]="1"; os.environ["PYOPENGL_PLATFORM"]="osmesa"
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    IDX=8; VMAX=0.63
    d=np.load(f"/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/psi_frame{IDX:02d}.npz")
    psi,GX,GY=d["psi"],d["GX"],d["GY"]; t=float(d["time"])
    lv=np.linspace(-VMAX,VMAX,41)
    fig,ax=plt.subplots(figsize=(6.5,5.5))
    cf=ax.contourf(GX,GY,psi,levels=lv,cmap="RdBu_r",vmin=-VMAX,vmax=VMAX,extend='both')
    ax.contour(GX,GY,psi,levels=lv[::2],colors='k',linewidths=0.35,alpha=0.6)
    cb=fig.colorbar(cf,ax=ax); cb.set_label(r"$\psi$")
    ax.set_xlabel("x"); ax.set_ylabel("y"); ax.set_aspect("equal")
    ax.set_title(f"eddy_uv stream function  frame {IDX:02d}  t={t:.3f}")
    fig.tight_layout(); fig.savefig(f"/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/frame{IDX:02d}.png",dpi=110)
    print("saved", IDX)
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

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
    
    idx=[]; times=[]; maxpsi=[]; energy=[]
    for i in range(1,12):
        d=np.load(f"/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/psi_frame{i:02d}.npz")
        psi=d["psi"]; t=float(d["time"])
        idx.append(i); times.append(t)
        maxpsi.append(float(np.max(np.abs(psi))))
        # kinetic energy from velocity if present, else from psi gradients
        if "u" in d.files and "v" in d.files:
            u=d["u"]; v=d["v"]
            energy.append(float(np.mean(u**2+v**2)))
        else:
            gy,gx=np.gradient(psi)
            energy.append(float(np.mean(gx**2+gy**2)))
    
    times=np.array(times); maxpsi=np.array(maxpsi); energy=np.array(energy)
    
    # Fit exponential decay to max|psi|: log(amp) = log(A0) + rate*t
    # use time axis if it varies, else frame index
    tax = times if (times.max()-times.min())>1e-9 else np.array(idx,dtype=float)
    coef=np.polyfit(tax, np.log(maxpsi), 1)
    rate=coef[0]
    fit=np.exp(np.polyval(coef, tax))
    
    fig,ax=plt.subplots(1,2,figsize=(12,5))
    ax[0].semilogy(tax, maxpsi, 'o-', label=r"$\max|\psi|$")
    ax[0].semilogy(tax, fit, 'r--', label=f"exp fit, rate={rate:.4f}")
    ax[0].set_xlabel("time"); ax[0].set_ylabel(r"$\max|\psi|$ (log)")
    ax[0].set_title("Stream function amplitude decay"); ax[0].legend(); ax[0].grid(True,which='both',alpha=0.3)
    
    ax[1].semilogy(tax, energy, 's-', color='green', label="kinetic energy")
    ax[1].set_xlabel("time"); ax[1].set_ylabel("mean KE (log)")
    ax[1].set_title("Kinetic energy decay"); ax[1].legend(); ax[1].grid(True,which='both',alpha=0.3)
    
    fig.suptitle("Walsh (1992) eddy_uv: exponential decay of self-similar flow")
    fig.tight_layout()
    out="/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/decay_curve.png"
    fig.savefig(out, dpi=120)
    print("saved:", out)
    print("max|psi|:", [f"{v:.4f}" for v in maxpsi])
    print("energy  :", [f"{v:.4f}" for v in energy])
    print("fitted decay rate (max|psi|):", rate)
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

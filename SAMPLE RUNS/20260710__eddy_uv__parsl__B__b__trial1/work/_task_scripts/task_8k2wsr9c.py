import sys, os, traceback

# Ensure working directory exists
os.makedirs("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0")
try:
    # --- User task code ---
    import numpy as np
    import pymech
    
    CASE = "/lcrc/project/PEDAL/jacoboh/Nek5000/NekExamples-master/eddy_uv"
    f = CASE + "/eddy_uv0.f00011"
    
    # Inspect available API
    print("pymech version:", pymech.__version__)
    
    from pymech.neksuite import readnek
    fld = readnek(f)
    print("type:", type(fld))
    print("nel:", fld.nel, "ndim:", fld.ndim, "lr1:", fld.lr1)
    print("time:", fld.time, "istep:", fld.istep)
    print("nvar/var:", getattr(fld, 'var', None))
    
    el = fld.elem[0]
    print("elem pos shape:", np.array(el.pos).shape)
    print("elem vel shape:", np.array(el.vel).shape)
    
    # Gather all element data
    nel = fld.nel
    lr1 = fld.lr1  # (lx, ly, lz)
    lz, ly, lx = lr1[2], lr1[1], lr1[0]
    print("lx,ly,lz:", lx, ly, lz)
    
    # pos: shape (ndim, lz, ly, lx) per element ; vel same
    X = np.array([e.pos[0] for e in fld.elem])  # (nel, lz, ly, lx)
    Y = np.array([e.pos[1] for e in fld.elem])
    U = np.array([e.vel[0] for e in fld.elem])
    V = np.array([e.vel[1] for e in fld.elem])
    print("X arr shape:", X.shape)
    print("X range:", X.min(), X.max())
    print("Y range:", Y.min(), Y.max())
    print("U range:", U.min(), U.max())
    print("V range:", V.min(), V.max())
    
    np.savez("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/field_final.npz",
             X=X, Y=Y, U=U, V=V, time=fld.time,
             lx=lx, ly=ly, lz=lz, nel=nel)
    print("saved field_final.npz")
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

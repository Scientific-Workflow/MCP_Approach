import sys, os, traceback

# Ensure working directory exists
os.makedirs("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0")
try:
    # --- User task code ---
    import os
    import numpy as np
    from PIL import Image
    
    frames=[]
    for i in range(1,12):
        p=f"/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/frame{i:02d}.png"
        frames.append(Image.open(p).convert("RGB"))
    
    out="/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/eddy_uv_evolution.gif"
    frames[0].save(out, save_all=True, append_images=frames[1:],
                   duration=500, loop=0)
    print("GIF saved:", out, "frames:", len(frames), "size:", frames[0].size)
    print("exists:", os.path.exists(out), "bytes:", os.path.getsize(out))
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

import sys, os, traceback

os.makedirs("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0")

# ADIOS2 is available -- import it for use in task code
import adios2

try:
    # --- User task code (ADIOS2 mode) ---
    import os
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ovito.io import import_file
    from ovito.modifiers import IdentifyDiamondModifier
    
    frames_dir = "/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/frames"
    render_dir = "/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/renders"
    os.makedirs(render_dir, exist_ok=True)
    
    pipeline = import_file(os.path.join(frames_dir, "step.*.lammpstrj"))
    pipeline.modifiers.append(IdentifyDiamondModifier())
    n = pipeline.source.num_frames
    
    # Order frames by timestep
    ts_list = []
    for i in range(n):
        d = pipeline.compute(i)
        ts_list.append((int(d.attributes.get("Timestep", i)), i))
    ts_list.sort()
    
    total_atoms = pipeline.compute(0).particles.count
    threshold = total_atoms / 8.0
    
    for out_idx, (ts, i) in enumerate(ts_list):
        data = pipeline.compute(i)
        pos = np.array(data.particles.positions)
        struct = np.array(data.particles["Structure Type"])
    
        mask0 = struct == 0
        mask_c = (struct == 1) | (struct == 2) | (struct == 3)
        mask_h = (struct == 4) | (struct == 5) | (struct == 6)
        crystallized = int(mask_c.sum() + mask_h.sum())
        nucleated = crystallized > threshold
    
        fig = plt.figure(figsize=(8, 8))
        ax = fig.add_subplot(111, projection="3d")
    
        if nucleated:
            # Following the paper: emphasize only crystallized atoms for nucleated frames
            if mask_c.any():
                ax.scatter(pos[mask_c,0], pos[mask_c,1], pos[mask_c,2], c="#0000FF", s=35, alpha=0.9, label="Cubic Ice")
            if mask_h.any():
                ax.scatter(pos[mask_h,0], pos[mask_h,1], pos[mask_h,2], c="#FF2200", s=35, alpha=0.9, label="Hex Ice")
        else:
            if mask0.any():
                ax.scatter(pos[mask0,0], pos[mask0,1], pos[mask0,2], c="#00BFFF", s=25, alpha=0.6, label="Liquid")
            if mask_c.any():
                ax.scatter(pos[mask_c,0], pos[mask_c,1], pos[mask_c,2], c="#0000FF", s=25, alpha=0.8, label="Cubic Ice")
            if mask_h.any():
                ax.scatter(pos[mask_h,0], pos[mask_h,1], pos[mask_h,2], c="#FF2200", s=25, alpha=0.8, label="Hex Ice")
    
        ax.set_title(f"Timestep {ts}  |  crystallized={crystallized}" + ("  [NUCLEATED]" if nucleated else ""))
        ax.legend(loc="upper right", fontsize=8)
        fig.savefig(os.path.join(render_dir, f"frame_{out_idx:04d}.png"), dpi=100, bbox_inches="tight")
        plt.close(fig)
    
    print(f"Rendered {len(ts_list)} frames to {render_dir}")
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

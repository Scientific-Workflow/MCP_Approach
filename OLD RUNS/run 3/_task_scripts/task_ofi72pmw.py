import sys, os, traceback

os.makedirs("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0")

# ADIOS2 is available -- import it for use in task code
import adios2

try:
    # --- User task code (ADIOS2 mode) ---
    import os
    os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
    os.environ["PYOPENGL_PLATFORM"] = "osmesa"
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d import Axes3D
    from ovito.io import import_file
    from ovito.modifiers import IdentifyDiamondModifier
    
    frames_dir = "/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/frames"
    render_dir = "/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/renders"
    os.makedirs(render_dir, exist_ok=True)
    
    pipeline = import_file(os.path.join(frames_dir, "step.*.lammpstrj"))
    pipeline.modifiers.append(IdentifyDiamondModifier())
    
    n = pipeline.source.num_frames
    for i in range(n):
        data = pipeline.compute(i)
        pos = np.array(data.particles.positions)
        struct = np.array(data.particles["Structure Type"])
        ts = data.attributes.get("Timestep", i)
    
        fig = plt.figure(figsize=(8, 8))
        ax = fig.add_subplot(111, projection="3d")
    
        mask0 = struct == 0
        if mask0.any():
            ax.scatter(pos[mask0,0], pos[mask0,1], pos[mask0,2],
                       c="#00BFFF", s=25, alpha=0.6, label="Liquid")
        mask_c = (struct == 1) | (struct == 2) | (struct == 3)
        if mask_c.any():
            ax.scatter(pos[mask_c,0], pos[mask_c,1], pos[mask_c,2],
                       c="#0000FF", s=25, alpha=0.9, label="Cubic Ice")
        mask_h = (struct == 4) | (struct == 5) | (struct == 6)
        if mask_h.any():
            ax.scatter(pos[mask_h,0], pos[mask_h,1], pos[mask_h,2],
                       c="#FF2200", s=25, alpha=0.9, label="Hex Ice")
    
        ax.set_title(f"Frame {i}  (timestep {ts})")
        ax.legend(loc="upper right", fontsize=8)
        fig.savefig(os.path.join(render_dir, f"frame_{i:04d}.png"), dpi=100, bbox_inches="tight")
        plt.close(fig)
    
    print(f"Rendered {n} frames to {render_dir}")
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

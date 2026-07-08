import sys, os, traceback

os.makedirs("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0")

# ADIOS2 is available -- import it for use in task code
import adios2

try:
    # --- User task code (ADIOS2 mode) ---
    import os, glob
    from PIL import Image
    
    render_dir = "/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/renders"
    frame_files = sorted(glob.glob(os.path.join(render_dir, "frame_*.png")))
    print(f"Found {len(frame_files)} frame PNGs")
    
    if frame_files:
        frames = [Image.open(f).convert("RGB") for f in frame_files]
        out = os.path.join(render_dir, "animation.gif")
        frames[0].save(out, save_all=True, append_images=frames[1:], loop=0, duration=100)
        print("Animation saved:", out, "with", len(frames), "frames")
    else:
        print("No frames found")
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

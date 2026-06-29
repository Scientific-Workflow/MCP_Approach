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
        import os, glob
        from PIL import Image
        
        render_dir = "/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/renders"
        frame_files = sorted(glob.glob(os.path.join(render_dir, "frame_*.png")))
        print(f"Found {len(frame_files)} frame PNGs")
        
        frames = [Image.open(f).convert("RGB") for f in frame_files]
        out = os.path.join(render_dir, "animation.gif")
        frames[0].save(out, save_all=True, append_images=frames[1:], loop=0, duration=100)
        print(f"Animation saved: {out} ({len(frames)} frames)")
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

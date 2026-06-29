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
        import os, csv, glob, re
        from ovito.io import import_file
        from ovito.modifiers import IdentifyDiamondModifier
        
        frames_dir = "/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/frames"
        # Build a naturally-sorted list of frame files so timesteps are in order
        files = glob.glob(os.path.join(frames_dir, "step.*.lammpstrj"))
        def step_num(p):
            m = re.search(r"step\.(\d+)\.lammpstrj", os.path.basename(p))
            return int(m.group(1)) if m else -1
        files = sorted(files, key=step_num)
        print(f"Found {len(files)} frame files")
        
        pipeline = import_file(files)
        pipeline.modifiers.append(IdentifyDiamondModifier())
        
        output_csv = "/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/results.csv"
        with open(output_csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["frame", "timestep", "cubic_diamond_count", "hexagonal_diamond_count"])
            for i in range(pipeline.source.num_frames):
                data = pipeline.compute(i)
                struct = data.particles["Structure Type"]
                cubic = int(((struct == 1) | (struct == 2) | (struct == 3)).sum())
                hexag = int(((struct == 4) | (struct == 5) | (struct == 6)).sum())
                ts = data.attributes.get("Timestep", step_num(files[i]))
                writer.writerow([i, ts, cubic, hexag])
        
        print(f"Analysis complete: {pipeline.source.num_frames} frames -> {output_csv}")
        # print a quick preview
        with open(output_csv) as f:
            for line in list(f)[:12]:
                print(line.rstrip())
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

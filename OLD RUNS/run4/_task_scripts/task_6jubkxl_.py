import sys, os, traceback

os.makedirs("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0")

# ADIOS2 is available -- import it for use in task code
import adios2

try:
    # --- User task code (ADIOS2 mode) ---
    import os, csv
    import numpy as np
    from ovito.io import import_file
    from ovito.modifiers import IdentifyDiamondModifier
    
    frames_dir = "/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/frames"
    pipeline = import_file(os.path.join(frames_dir, "step.*.lammpstrj"))
    pipeline.modifiers.append(IdentifyDiamondModifier())
    
    n = pipeline.source.num_frames
    print(f"Loaded {n} frames")
    
    # Determine total atom count from frame 0
    data0 = pipeline.compute(0)
    total_atoms = data0.particles.count
    threshold = total_atoms / 8.0
    print(f"Total atoms = {total_atoms}, nucleation threshold (1/8) = {threshold:.1f}")
    
    rows = []
    for i in range(n):
        data = pipeline.compute(i)
        struct = np.array(data.particles["Structure Type"])
        ts = int(data.attributes.get("Timestep", i))
        cubic = int(((struct == 1) | (struct == 2) | (struct == 3)).sum())
        hexag = int(((struct == 4) | (struct == 5) | (struct == 6)).sum())
        crystallized = cubic + hexag
        nucleated = "yes" if crystallized > threshold else "no"
        rows.append((i, ts, cubic, hexag, crystallized, nucleated))
    
    # sort by timestep for sensible time ordering
    rows.sort(key=lambda r: r[1])
    
    out_csv = "/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/results.csv"
    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame", "timestep", "cubic_diamond_count", "hexagonal_diamond_count", "total_crystallized", "nucleated"])
        for r in rows:
            w.writerow(r)
    
    print("Wrote", out_csv)
    print("Sample rows (timestep, cubic, hex, total, nucleated):")
    for r in rows[::10]:
        print(r[1], r[2], r[3], r[4], r[5])
    maxc = max(rows, key=lambda r: r[4])
    print("Max crystallized:", maxc)
    nuc_frames = [r for r in rows if r[5] == "yes"]
    print(f"Nucleated frames: {len(nuc_frames)}")
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

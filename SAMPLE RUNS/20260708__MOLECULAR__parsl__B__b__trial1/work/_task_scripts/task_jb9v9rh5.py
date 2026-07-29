import sys, os, traceback

# Ensure working directory exists
os.makedirs("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0")
try:
    # --- User task code ---
    import os, csv
    from ovito.io import import_file
    from ovito.modifiers import IdentifyDiamondModifier
    
    frames_dir = "/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/frames"
    pipeline = import_file(os.path.join(frames_dir, "step.*.lammpstrj"))
    pipeline.modifiers.append(IdentifyDiamondModifier())
    
    output_csv = "/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/results.csv"
    with open(output_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["frame", "timestep", "cubic_diamond_count", "hexagonal_diamond_count"])
        for i in range(pipeline.source.num_frames):
            data = pipeline.compute(i)
            struct = data.particles["Structure Type"]
            cubic = int(((struct == 1) | (struct == 2) | (struct == 3)).sum())
            hexag = int(((struct == 4) | (struct == 5) | (struct == 6)).sum())
            ts = data.attributes.get("Timestep", i)
            writer.writerow([i, ts, cubic, hexag])
    
    print(f"Analysis complete: {pipeline.source.num_frames} frames -> {output_csv}")
    
    # quick summary
    with open(output_csv) as f:
        rows = list(csv.reader(f))
    print("First few rows:")
    for r in rows[:3]:
        print(r)
    print("Last few rows:")
    for r in rows[-3:]:
        print(r)
    maxc = max(int(r[2]) for r in rows[1:])
    maxh = max(int(r[3]) for r in rows[1:])
    print(f"Max cubic: {maxc}, Max hexagonal: {maxh}")
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

import sys, os, traceback

os.makedirs("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0")

# ADIOS2 is available -- import it for use in task code
import adios2

try:
    # --- User task code (ADIOS2 mode) ---
    import os, csv
    from ovito.io import import_file
    from ovito.modifiers import IdentifyDiamondModifier
    
    pipeline = import_file("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/frames/step.*.lammpstrj")
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
            ts = data.attributes.get("Timestep", i)
            writer.writerow([i, ts, cubic, hexag])
    
    print(f"Analysis complete: {pipeline.source.num_frames} frames -> {output_csv}")
    
    # Print summary
    with open(output_csv) as f:
        rows = list(csv.DictReader(f))
    print("First frame:", rows[0])
    print("Last frame:", rows[-1])
    max_total = max(int(r["cubic_diamond_count"]) + int(r["hexagonal_diamond_count"]) for r in rows)
    print("Max total crystallized atoms:", max_total)
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

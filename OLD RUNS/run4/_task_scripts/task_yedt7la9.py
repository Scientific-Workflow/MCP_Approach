import sys, os, traceback

os.makedirs("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0")

# ADIOS2 is available -- import it for use in task code
import adios2

try:
    # --- User task code (ADIOS2 mode) ---
    import os, csv
    import numpy as np
    
    bp_path = "/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/diamond_analysis.bp"
    
    # Load reference from CSV
    csv_rows = []
    with open("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/results.csv") as f:
        for row in csv.DictReader(f):
            csv_rows.append((int(float(row["timestep"])),
                             int(row["cubic_diamond_count"]),
                             int(row["hexagonal_diamond_count"])))
    csv_rows.sort(key=lambda r: r[0])
    
    import adios2
    read_rows = []
    engine = "adios2-BP"
    with adios2.Stream(bp_path, "r") as fr:
        for _ in fr.steps():
            ts = int(fr.read("timestep"))
            cub = int(fr.read("cubic_count"))
            hexc = int(fr.read("hexagonal_count"))
            ncr = int(fr.read("n_crystallized"))
            read_rows.append((ts, cub, hexc, ncr))
    
    read_rows.sort(key=lambda r: r[0])
    print(f"Read back {len(read_rows)} steps from {bp_path} (engine={engine})")
    
    mismatches = 0
    for c, r in zip(csv_rows, read_rows):
        if c[0] != r[0] or c[1] != r[1] or c[2] != r[2]:
            mismatches += 1
            if mismatches <= 5:
                print("MISMATCH csv", c, "vs bp", r[:3])
        # verify n_crystallized == cubic+hex
        if r[3] != r[1] + r[2]:
            print("n_crystallized inconsistency at ts", r[0])
    
    print(f"Total steps compared: {min(len(csv_rows), len(read_rows))}")
    print(f"Mismatches: {mismatches}")
    print("Sample read-back (ts, cubic, hex, n_cryst):")
    for r in read_rows[::15]:
        print(r)
    print("VERIFICATION:", "PASS" if mismatches == 0 and len(csv_rows)==len(read_rows) else "FAIL")
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

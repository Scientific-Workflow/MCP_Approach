import sys, os, traceback

os.makedirs("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0")

# ADIOS2 is available -- import it for use in task code
import adios2

try:
    # --- User task code (ADIOS2 mode) ---
    import csv
    
    # Total atom count from LAMMPS log (4360 atoms)
    total_atoms = 4360
    threshold = total_atoms / 8.0  # 1/8 rule
    
    rows = []
    with open("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/results.csv") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    
    onset_frame = -1
    onset_timestep = -1
    for r in rows:
        total = int(r["cubic_diamond_count"]) + int(r["hexagonal_diamond_count"])
        if total >= threshold:
            onset_frame = int(r["frame"])
            onset_timestep = int(float(r["timestep"]))
            break
    
    with open("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/nucleation_onset.txt", "w") as f:
        f.write(f"total_atoms={total_atoms}\n")
        f.write(f"threshold_atoms={threshold}\n")
        f.write(f"nucleation_onset_frame={onset_frame}\n")
        f.write(f"nucleation_onset_timestep={onset_timestep}\n")
        if onset_frame == -1:
            f.write("note=No frame reached the 1/8 crystallization threshold; "
                    "no successful nucleation event detected in this short run "
                    "(consistent with paper: nucleation is stochastic and rare).\n")
    
    print(f"Total atoms: {total_atoms}, threshold (1/8): {threshold}")
    max_total = max(int(r["cubic_diamond_count"]) + int(r["hexagonal_diamond_count"]) for r in rows)
    print(f"Max crystallized atoms observed: {max_total}")
    if onset_frame == -1:
        print("No nucleation onset reached the 1/8 threshold.")
    else:
        print(f"Nucleation onset at frame {onset_frame}, timestep {onset_timestep}")
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

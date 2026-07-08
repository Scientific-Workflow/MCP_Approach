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
        import csv
        
        # Total atoms from the LAMMPS run
        TOTAL_ATOMS = 4360
        threshold = TOTAL_ATOMS / 8.0  # paper's crystallization threshold = 1/8 of total atoms
        
        rows = []
        with open("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/results.csv") as f:
            for row in csv.DictReader(f):
                frame = int(row["frame"])
                ts = int(float(row["timestep"]))
                cubic = int(row["cubic_diamond_count"])
                hexag = int(row["hexagonal_diamond_count"])
                rows.append((frame, ts, cubic, hexag, cubic + hexag))
        
        max_total = max(r[4] for r in rows)
        onset = None
        for r in rows:
            if r[4] > threshold:
                onset = r
                break
        
        nucleated = onset is not None
        
        lines = []
        lines.append("=== Nucleation Summary ===")
        lines.append(f"Total atoms: {TOTAL_ATOMS}")
        lines.append(f"Crystallization threshold (1/8 of atoms): {threshold:.1f}")
        lines.append(f"Max crystallized atoms observed in any frame: {max_total}")
        lines.append(f"Nucleation verdict: {'NUCLEATED' if nucleated else 'NOT NUCLEATED'}")
        if nucleated:
            lines.append(f"First frame crossing threshold: frame {onset[0]}, timestep {onset[1]}, "
                         f"crystallized={onset[4]} (cubic={onset[2]}, hex={onset[3]})")
        else:
            lines.append("No frame exceeded the 1/8 crystallization threshold. "
                         "This matches the paper's observation that nucleation is a rare event "
                         "at high undercooling (only 1 in 60 instances nucleated at 210 K).")
        report = "\n".join(lines)
        print(report)
        
        with open("/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/nucleation_summary.txt", "w") as f:
            f.write(report + "\n")
        print("\nWrote /gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/nucleation_summary.txt")
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

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
    
    # Build per-frame records sorted by timestep
    records = []
    for i in range(n):
        data = pipeline.compute(i)
        struct = np.array(data.particles["Structure Type"])
        pos = np.array(data.particles.positions)
        ts = int(data.attributes.get("Timestep", i))
        cubic_mask = (struct == 1) | (struct == 2) | (struct == 3)
        hex_mask = (struct == 4) | (struct == 5) | (struct == 6)
        cryst_mask = cubic_mask | hex_mask
        records.append({
            "timestep": ts,
            "cubic": int(cubic_mask.sum()),
            "hex": int(hex_mask.sum()),
            "cryst_pos": pos[cryst_mask].astype(np.float64),
        })
    records.sort(key=lambda r: r["timestep"])
    
    bp_path = "/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/diamond_analysis.bp"
    engine_used = None
    try:
        import adios2
        adios = adios2.Adios() if hasattr(adios2, "Adios") else None
        # Use the high-level Stream API (adios2 >= 2.10)
        with adios2.Stream(bp_path, "w") as fw:
            for rec in records:
                fw.begin_step()
                fw.write("timestep", np.array(rec["timestep"], dtype=np.int64))
                fw.write("cubic_count", np.array(rec["cubic"], dtype=np.int64))
                fw.write("hexagonal_count", np.array(rec["hex"], dtype=np.int64))
                cp = rec["cryst_pos"]
                ncr = cp.shape[0]
                fw.write("n_crystallized", np.array(ncr, dtype=np.int64))
                if ncr > 0:
                    fw.write("crystallized_positions", cp, shape=[ncr, 3], start=[0, 0], count=[ncr, 3])
                fw.end_step()
        engine_used = "adios2-BP"
        print(f"ADIOS2 stream written to {bp_path}, engine={engine_used}, steps={len(records)}")
    except Exception as e:
        print("ADIOS2 path failed, falling back to npz:", repr(e))
        npz_path = "/gpfs/fs1/home/jacob.oh/MCP_Approach/work/run0/diamond_analysis.npz"
        np.savez(npz_path,
                 timestep=np.array([r["timestep"] for r in records]),
                 cubic_count=np.array([r["cubic"] for r in records]),
                 hexagonal_count=np.array([r["hex"] for r in records]),
                 n_crystallized=np.array([r["cryst_pos"].shape[0] for r in records]))
        engine_used = "numpy-npz-fallback"
        print(f"Fallback written to {npz_path}, engine={engine_used}")
    
    print("ENGINE:", engine_used)
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

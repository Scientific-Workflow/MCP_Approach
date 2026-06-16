#!/usr/bin/env python3
"""
Parsl workflow for water crystallization nucleation simulation.

Producer: LAMMPS MD simulation of water molecules using AW Tersoff potential
Consumer: OVITO analysis (IdentifyDiamondModifier) + frame rendering

Usage:
    python workflow.py --data-dir /app/data --work-dir ./workdir
"""

import argparse
import os

import parsl
from parsl.config import Config
from parsl.executors import HighThroughputExecutor
from parsl.providers import LocalProvider
from parsl.app.app import python_app

# --- Parsl Configuration ---
config = Config(
    executors=[
        HighThroughputExecutor(
            label="local_htex",
            cores_per_worker=1,
            provider=LocalProvider(
                min_blocks=1,
                max_blocks=1,
                init_blocks=1,
            ),
        )
    ],
    strategy="none",
)
parsl.load(config)


# --- Task 1: Producer - LAMMPS simulation ---
@python_app
def run_lammps(input_script, data_dir, work_dir):
    """Run LAMMPS water crystallization simulation.

    Copies input files into work_dir, runs the simulation via the LAMMPS
    Python API, and returns the path to the trajectory dump directory.

    Args:
        input_script: Path to in.watbox input script.
        data_dir: Directory containing data.init and AW.tersoff.
        work_dir: Working directory for simulation output.

    Returns:
        str: Path to work_dir (which contains frames/ subdirectory with dumps).
    """
    import os
    import shutil
    import glob
    import ctypes

    # Create working directory
    os.makedirs(work_dir, exist_ok=True)
    frames_dir = os.path.join(work_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    # Copy supporting data files
    for fname in ["data.init", "AW.tersoff"]:
        src = os.path.join(data_dir, fname)
        dst = os.path.join(work_dir, fname)
        shutil.copy2(src, dst)

    # Always re-copy input script (user may have edited it)
    shutil.copy2(input_script, os.path.join(work_dir, "in.watbox"))

    # CRITICAL: chdir to work_dir BEFORE initializing LAMMPS
    # dump file paths in in.watbox are relative to CWD (e.g., frames/step.*.lammpstrj)
    os.chdir(work_dir)

    # Ensure MPI library can be found (needed on some systems)
    venv_lib = os.path.join(os.path.dirname(os.path.dirname(shutil.which("python") or "")), "lib")
    mpich_lib = os.path.join(venv_lib, "mpich")
    if os.path.isdir(venv_lib):
        os.environ["LD_LIBRARY_PATH"] = (
            f"{venv_lib}:{mpich_lib}:" + os.environ.get("LD_LIBRARY_PATH", "")
        )
        try:
            libmpi_path = os.path.join(venv_lib, "libmpi.so.12")
            if os.path.exists(libmpi_path):
                ctypes.CDLL(libmpi_path, ctypes.RTLD_GLOBAL)
        except OSError:
            pass  # May already be loaded or not needed

    # Initialize and run LAMMPS
    from lammps import lammps

    lmp = lammps(cmdargs=["-screen", "none"])
    lmp.file("in.watbox")
    lmp.close()

    # Verify dump files were produced
    dump_files = glob.glob(os.path.join(frames_dir, "step.*.lammpstrj"))
    if not dump_files:
        raise RuntimeError(f"No dump files found in {frames_dir}")

    return work_dir


# --- Task 2: Consumer - OVITO analysis + rendering ---
@python_app
def analyze_and_render(dump_path, output_dir):
    """Analyze trajectory with OVITO IdentifyDiamondModifier and render frames.

    Detects cubic and hexagonal diamond structures in each trajectory frame,
    writes a CSV of per-frame crystal counts, renders color-coded atom images,
    and produces a nucleation timeseries plot.

    IdentifyDiamondModifier structure type mapping:
        0 = Other (liquid/amorphous)
        1 = Cubic diamond
        2 = Cubic diamond (1st neighbor)
        3 = Cubic diamond (2nd neighbor)
        4 = Hexagonal diamond (wurtzite)
        5 = Hexagonal diamond (1st neighbor)
        6 = Hexagonal diamond (2nd neighbor)

    Args:
        dump_path: Path to work_dir containing frames/ subdirectory.
        output_dir: Directory where rendered PNGs, GIF, and plots will be saved.

    Returns:
        str: Path to output_dir.
    """
    import os
    import csv
    import glob

    import numpy as np
    from ovito.io import import_file
    from ovito.modifiers import IdentifyDiamondModifier

    os.makedirs(output_dir, exist_ok=True)

    # Load trajectory
    frames_pattern = os.path.join(dump_path, "frames", "step.*.lammpstrj")
    pipeline = import_file(frames_pattern)
    pipeline.modifiers.append(IdentifyDiamondModifier())

    num_frames = pipeline.source.num_frames

    # -- Phase 1: Analyze and write CSV --
    results_csv = os.path.join(dump_path, "results.csv")
    timesteps_list = []
    cubic_list = []
    hex_list = []

    with open(results_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["frame", "timestep", "cubic_diamond_count", "hexagonal_diamond_count"])
        for i in range(num_frames):
            data = pipeline.compute(i)
            struct = np.array(data.particles["Structure Type"])
            cubic = int(((struct == 1) | (struct == 2) | (struct == 3)).sum())
            hexag = int(((struct == 4) | (struct == 5) | (struct == 6)).sum())
            ts = int(data.attributes.get("Timestep", i))
            writer.writerow([i, ts, cubic, hexag])
            timesteps_list.append(ts)
            cubic_list.append(cubic)
            hex_list.append(hexag)

    # -- Phase 2: Render frames with matplotlib --
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Re-load pipeline for rendering (reuse modifier)
    pipeline2 = import_file(frames_pattern)
    pipeline2.modifiers.append(IdentifyDiamondModifier())

    for i in range(num_frames):
        data = pipeline2.compute(i)
        pos = np.array(data.particles.positions)
        struct = np.array(data.particles["Structure Type"])

        fig = plt.figure(figsize=(8, 8))
        ax = fig.add_subplot(111, projection="3d")

        # Liquid/Other (type 0): cyan
        mask0 = struct == 0
        if mask0.any():
            ax.scatter(
                pos[mask0, 0], pos[mask0, 1], pos[mask0, 2],
                c="#00BFFF", s=25, alpha=0.3, label="Liquid",
            )

        # Cubic diamond (types 1, 2, 3): blue
        mask_c = (struct == 1) | (struct == 2) | (struct == 3)
        if mask_c.any():
            ax.scatter(
                pos[mask_c, 0], pos[mask_c, 1], pos[mask_c, 2],
                c="#0000FF", s=25, alpha=0.8, label="Cubic Ice",
            )

        # Hexagonal diamond (types 4, 5, 6): red
        mask_h = (struct == 4) | (struct == 5) | (struct == 6)
        if mask_h.any():
            ax.scatter(
                pos[mask_h, 0], pos[mask_h, 1], pos[mask_h, 2],
                c="#FF2200", s=25, alpha=0.8, label="Hex Ice",
            )

        ax.set_title(f"Frame {i}")
        ax.legend(loc="upper right", fontsize=8)
        fig.savefig(
            os.path.join(output_dir, f"frame_{i:04d}.png"),
            dpi=100, bbox_inches="tight",
        )
        plt.close(fig)

    # -- Phase 3: Generate animation GIF --
    from PIL import Image

    frame_files = sorted(glob.glob(os.path.join(output_dir, "frame_*.png")))
    if frame_files:
        frames = [Image.open(f) for f in frame_files]
        frames[0].save(
            os.path.join(output_dir, "animation.gif"),
            save_all=True,
            append_images=frames[1:],
            loop=0,
            duration=100,
        )

    # -- Phase 4: Nucleation timeseries plot --
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(
        timesteps_list, cubic_list,
        color="#0000FF", marker="o", markersize=4, label="Cubic Diamond (Ice Ic)",
    )
    ax.plot(
        timesteps_list, hex_list,
        color="#FF2200", marker="s", markersize=4, label="Hexagonal Diamond (Ice Ih)",
    )
    total_ice = [c + h for c, h in zip(cubic_list, hex_list)]
    ax.plot(timesteps_list, total_ice, "k--", linewidth=1.5, alpha=0.6, label="Total Ice")
    ax.set_xlabel("Timestep")
    ax.set_ylabel("Ice-like Atoms")
    ax.set_title("Water Freezing: Nucleation Progress")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.savefig(
        os.path.join(output_dir, "nucleation_timeseries.png"),
        dpi=150, bbox_inches="tight",
    )
    plt.close(fig)

    return output_dir


# --- Main ---
def main():
    parser = argparse.ArgumentParser(
        description="Parsl workflow: Water crystallization nucleation (LAMMPS + OVITO)"
    )
    parser.add_argument(
        "--data-dir",
        default="/app/data",
        help="Directory containing in.watbox, data.init, and AW.tersoff",
    )
    parser.add_argument(
        "--work-dir",
        default="./workdir",
        help="Working directory for simulation and rendering output",
    )
    args = parser.parse_args()

    data_dir = os.path.abspath(args.data_dir)
    work_dir = os.path.abspath(args.work_dir)
    input_script = os.path.join(data_dir, "in.watbox")

    print(f"Data directory : {data_dir}")
    print(f"Work directory : {work_dir}")
    print(f"Input script   : {input_script}")

    # Producer: LAMMPS simulation
    print("\n[1/2] Submitting LAMMPS simulation...")
    sim_future = run_lammps(input_script, data_dir, work_dir)
    dump_path = sim_future.result()
    print(f"  LAMMPS complete. Output at: {dump_path}")

    # Consumer: OVITO analysis + rendering
    renders_dir = os.path.join(work_dir, "renders")
    print("\n[2/2] Submitting OVITO analysis and rendering...")
    render_future = analyze_and_render(dump_path, renders_dir)
    render_output = render_future.result()
    print(f"  Analysis & rendering complete. Output at: {render_output}")

    print("\n" + "=" * 60)
    print("Workflow finished successfully!")
    print(f"  Results CSV     : {os.path.join(work_dir, 'results.csv')}")
    print(f"  Rendered frames : {renders_dir}/frame_*.png")
    print(f"  Animation       : {os.path.join(renders_dir, 'animation.gif')}")
    print(f"  Timeseries plot : {os.path.join(renders_dir, 'nucleation_timeseries.png')}")
    print("=" * 60)

    parsl.clear()


if __name__ == "__main__":
    main()

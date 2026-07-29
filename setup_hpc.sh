#!/usr/bin/env bash
# Source this script before running the agent on LCRC (Swing/Improv).
# It sets LD_LIBRARY_PATH so the Intel MPI shared libraries (libmpi.so.12,
# libfabric.so.1) are visible to both the agent process and task subprocesses.
#
# Usage:
#   source setup_hpc.sh
#   python agent_mcp.py --env hpc --paper 1 --goal "..."
#
# Why this is needed:
#   LAMMPS is compiled with Intel MPI support. Its Python bindings load
#   libmpi.so.12 at import time. Without these paths, you get:
#     OSError: libmpi.so.12: cannot open shared object file: No such file or directory
#
# The same paths are also baked into TASK_ENV in servers/parsl_server.py so
# every submit_task subprocess inherits them automatically. This script covers
# the agent process itself.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# MPI shared libraries required by LAMMPS Python bindings
SWING_MPI="/gpfs/fs1/soft/swing/manual/intel/oneapi/2021.2.0.2883/mpi/2021.2.0/lib/release"
IMPROV_MPI="/gpfs/fs1/soft/improv/software/custom-built/intel-oneapi-toolkit/mpi/2021.15/lib"
IMPROV_FABRIC="/gpfs/fs1/soft/improv/software/custom-built/intel-oneapi-toolkit/mpi/2021.15/opt/mpi/libfabric/lib"

export LD_LIBRARY_PATH="${SWING_MPI}:${IMPROV_MPI}:${IMPROV_FABRIC}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

# points at the project venv with lammps, ovito, etc in it.
# the servers pick this up straight from the environment to launch with the right interpreter
export VENV_PYTHON="${SCRIPT_DIR}/venv3/bin/python3"

echo "LD_LIBRARY_PATH set for Intel MPI (Swing + Improv)"
echo "VENV_PYTHON=${VENV_PYTHON}"

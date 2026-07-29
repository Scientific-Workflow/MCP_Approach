import sys, os, traceback

os.makedirs("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0")

# ADIOS2 is available -- import it for use in task code
import adios2

try:
    # --- User task code (ADIOS2 mode) ---
    import os
    
    pbs = r'''#!/bin/bash
    #PBS -A PEDAL
    #PBS -l walltime=01:00:00
    #PBS -l select=1:mpiprocs=8
    #PBS -l place=scatter
    #PBS -N lastjourney_agent
    #PBS -j oe
    
    set -e
    echo "Working directory is $PBS_O_WORKDIR"
    cd $PBS_O_WORKDIR
    
    # ---- Paths (from reference subme.pbs) ----
    exe=/lcrc/project/PEDAL/jacoboh/HACC/HACC_go/improv.cpu/mpi/bin/hacc_tpm
    envfile=/lcrc/project/PEDAL/jacoboh/HACC/HACC_go/env/bashrc.improv.cpu
    paramfile=./params/indat.params
    
    # venv python + analysis script for stage 2
    VENV_PY=/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/venv3/bin/python3
    ANALYSIS=/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/analyze_and_render.py
    
    # ---- Load HACC build environment ----
    source $envfile
    
    NNODES=1
    NRANKS=8
    NTHREADS=1
    NTOTRANKS=$(( NNODES * NRANKS ))
    echo "NNODES=${NNODES} NTOTRANKS=${NTOTRANKS} NRANKS=${NRANKS} NTHREADS=${NTHREADS}"
    
    # =========================================================
    # STAGE 1: HACC producer (hacc_tpm) -- 8 MPI ranks
    # =========================================================
    echo "=== STAGE 1: hacc_tpm (8 ranks) ==="
    mpiexec -np ${NTOTRANKS} \
      --map-by ppr:${NRANKS}:node \
      --bind-to core \
      -x OMP_NUM_THREADS=${NTHREADS} \
      $exe $paramfile -n
    echo "=== STAGE 1 complete (rc=$?) ==="
    
    # =========================================================
    # STAGE 2: analysis + rendering (SAME job, immediately after)
    # =========================================================
    echo "=== STAGE 2: analyze_and_render.py ==="
    export MPLBACKEND=Agg
    $VENV_PY $ANALYSIS
    echo "=== STAGE 2 complete (rc=$?) ==="
    echo "=== JOB DONE ==="
    '''
    
    path = "/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/agent_subme.pbs"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(pbs)
    print("wrote", path, len(pbs), "bytes")
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

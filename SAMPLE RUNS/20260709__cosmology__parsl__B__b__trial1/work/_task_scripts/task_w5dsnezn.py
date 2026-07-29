import sys, os, traceback

# Ensure working directory exists
os.makedirs("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0", exist_ok=True)
os.chdir("/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0")
try:
    # --- User task code ---
    pbs = r'''#!/bin/bash
    #PBS -A PEDAL
    #PBS -l walltime=01:00:00
    #PBS -l select=1:mpiprocs=8
    #PBS -l place=scatter
    #PBS -N agent_hacc_run
    #PBS -j oe
    
    set -e
    echo "Working directory is $PBS_O_WORKDIR"
    cd $PBS_O_WORKDIR
    
    # Paths (referenced from subme.pbs; NOT modifying the original)
    exe=/lcrc/project/PEDAL/jacoboh/HACC/HACC_go/improv.cpu/mpi/bin/hacc_tpm
    envfile=/lcrc/project/PEDAL/jacoboh/HACC/HACC_go/env/bashrc.improv.cpu
    paramfile=./params/indat.params
    
    # Load the build environment
    source $envfile
    
    NNODES=1
    NRANKS=8
    NTHREADS=1
    NTOTRANKS=$(( NNODES * NRANKS ))
    echo "NNODES=${NNODES} NTOTRANKS=${NTOTRANKS} NRANKS=${NRANKS} NTHREADS=${NTHREADS}"
    
    # --- Stage 1: HACC producer ---
    mpiexec -np ${NTOTRANKS} \
      --map-by ppr:${NRANKS}:node \
      --bind-to core \
      -x OMP_NUM_THREADS=${NTHREADS} \
      $exe $paramfile -n
    
    echo "=== hacc_tpm finished; starting analysis+render ==="
    
    # --- Stage 2: analysis + visualization (same job) ---
    VENV_PY=/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/venv3/bin/python3
    ANALYZE=/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/analyze_and_render.py
    $VENV_PY $ANALYZE
    
    echo "=== analysis+render finished ==="
    '''
    
    path = "/gpfs/fs1/home/jacob.oh/SULI/MCP_Approach/work/run0/agent_subme.pbs"
    with open(path, "w") as f:
        f.write(pbs)
    print("Wrote", path, len(pbs), "bytes")
    print(pbs)
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {e}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

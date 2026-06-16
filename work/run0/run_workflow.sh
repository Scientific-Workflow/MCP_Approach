#!/usr/bin/env bash
# run_workflow.sh - Launcher for water crystallization nucleation workflow
#
# Usage:
#   ./run_workflow.sh
#
# Resolves paths relative to the script file itself, not the caller's CWD.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

# Data directory: contains in.watbox, data.init, AW.tersoff
DATA_DIR="${SCRIPT_DIR}/../../../data"

# Working directory: simulation output goes here
WORK_DIR="${SCRIPT_DIR}/workdir"

echo "=============================="
echo "Water Crystallization Workflow"
echo "=============================="
echo "Script dir : ${SCRIPT_DIR}"
echo "Data dir   : ${DATA_DIR}"
echo "Work dir   : ${WORK_DIR}"
echo ""

python "${SCRIPT_DIR}/workflow.py" --data-dir "${DATA_DIR}" --work-dir "${WORK_DIR}"

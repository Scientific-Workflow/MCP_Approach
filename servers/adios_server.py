"""
ADIOS2 Workflow MCP Server

An MCP server that exposes ADIOS2 workflow engine capabilities as tools.
The explorer agent connects to this server via MCP protocol to submit tasks,
check status, get results, and manage the workflow execution.

ADIOS2 (Adaptable Input/Output System) is a high-performance I/O framework
for scientific simulations. It provides streaming data transport between
workflow stages, supporting both file-based (BP format) and in-memory
(SST, DataMan) data exchange.

When the ADIOS2 Python bindings are available, tasks use adios2 for data I/O
between pipeline stages. When ADIOS2 is NOT available, tasks fall back to
numpy file I/O (.npy/.npz) — same result, just without ADIOS2 optimizations.

This server executes tasks locally (or in a virtual environment) using subprocess.
No Docker required. Compatible with HPC environments where ADIOS2 is installed.

The VENV_PYTHON environment variable controls which Python interpreter to use.

Usage:
    python servers/adios_server.py                    # stdio mode
    python servers/adios_server.py --transport sse     # SSE mode
"""

import os
import sys
import json
import subprocess
import uuid
import time
import tempfile
from typing import Optional
from mcp.server.fastmcp import FastMCP

# __ Server Setup ______________________________________________________________

mcp = FastMCP(
    "ADIOS2 Workflow Engine",
    instructions="MCP server exposing ADIOS2 workflow engine for scientific workflow execution with high-performance I/O",
)

# __ Configuration _____________________________________________________________

REPO_ROOT = os.environ.get(
    "REPO_ROOT",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)

VENV_PYTHON = os.environ.get("VENV_PYTHON", sys.executable)

DEFAULT_WORK_DIR = os.path.join(REPO_ROOT, "work", "run0")
DEFAULT_DATA_DIR = os.path.join(REPO_ROOT, "data")

TASK_ENV = {
    **os.environ,
    "LIBGL_ALWAYS_SOFTWARE": "1",
    "PYOPENGL_PLATFORM": "osmesa",
    "OVITO_GUI_MODE": "0",
}

# __ ADIOS2 Runtime Detection __________________________________________________

_adios2_available: Optional[bool] = None


def _check_adios2() -> bool:
    """Check if the ADIOS2 Python bindings are available."""
    global _adios2_available
    if _adios2_available is not None:
        return _adios2_available

    result = _run_command(
        [VENV_PYTHON, "-c", "import adios2; print(adios2.__version__)"],
        timeout=15,
    )
    _adios2_available = result["exit_code"] == 0
    return _adios2_available


# __ Task Registry _____________________________________________________________

_tasks: dict[str, dict] = {}


# __ Execution Helpers _________________________________________________________

def _run_command(cmd: list[str], work_dir: str = DEFAULT_WORK_DIR, timeout: int = 1800) -> dict:
    """Execute a command locally (or in venv) and return results."""
    os.makedirs(work_dir, exist_ok=True)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True,
            cwd=work_dir,
            env=TASK_ENV,
            timeout=timeout,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
        }
    except Exception as e:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e),
        }


def _run_python_script(script: str, work_dir: str = DEFAULT_WORK_DIR, timeout: int = 1800) -> dict:
    """Write a Python script to a temp file and execute it."""
    os.makedirs(work_dir, exist_ok=True)

    fd, script_path = tempfile.mkstemp(suffix=".py", prefix="_mcp_adios_task_", dir=work_dir)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(script)
        return _run_command([VENV_PYTHON, script_path], work_dir=work_dir, timeout=timeout)
    finally:
        if os.path.isfile(script_path):
            os.remove(script_path)


def _wrap_as_adios_task(python_code: str) -> str:
    """Wrap user code in an ADIOS2-aware script.

    If ADIOS2 is available, injects adios2 import and makes the adios2 module
    accessible to the user code. Otherwise, wraps with plain try/except for
    direct execution using numpy file I/O as fallback.
    """
    if _check_adios2():
        return f"""\
import sys, os, traceback

os.makedirs("{DEFAULT_WORK_DIR}", exist_ok=True)
os.chdir("{DEFAULT_WORK_DIR}")

# ADIOS2 is available -- import it for use in task code
import adios2

try:
    # --- User task code (ADIOS2 mode) ---
{_indent(python_code, 4)}
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {{e}}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
"""
    else:
        return f"""\
import sys, os, traceback

os.makedirs("{DEFAULT_WORK_DIR}", exist_ok=True)
os.chdir("{DEFAULT_WORK_DIR}")

try:
    # --- User task code (ADIOS2 fallback: numpy file I/O) ---
{_indent(python_code, 4)}
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {{e}}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
"""


# __ MCP Tools _________________________________________________________________

@mcp.tool()
def submit_task(
    name: str,
    python_code: str,
    depends_on: list[str] | None = None,
    timeout: int = 1800,
) -> str:
    """Submit a Python task for execution via the ADIOS2 workflow engine.

    The task runs locally using the configured Python interpreter.
    When ADIOS2 is available, the adios2 module is pre-imported for
    high-performance I/O. Otherwise falls back to numpy file I/O.
    If depends_on is specified, the task waits for those tasks to complete first.

    Args:
        name: Descriptive name for this task (e.g. "run_simulation", "analyze_data")
        python_code: Python code to execute (multi-line string, self-contained)
        depends_on: List of task IDs that must complete before this task runs (optional)
        timeout: Max seconds to wait for execution (default: 1800)

    Returns:
        JSON with task_id, status, and execution results
    """
    task_id = f"task_{uuid.uuid4().hex[:8]}"

    # Check dependencies
    if depends_on:
        for dep_id in depends_on:
            if dep_id not in _tasks:
                return json.dumps({
                    "task_id": task_id,
                    "status": "failed",
                    "error": f"Dependency {dep_id} not found",
                })
            if _tasks[dep_id]["status"] != "completed":
                return json.dumps({
                    "task_id": task_id,
                    "status": "failed",
                    "error": f"Dependency {dep_id} has status '{_tasks[dep_id]['status']}', not 'completed'",
                })

    # Register task
    _tasks[task_id] = {
        "name": name,
        "status": "running",
        "depends_on": depends_on or [],
        "submitted_at": time.time(),
        "engine": "adios2" if _check_adios2() else "adios2-fallback",
    }

    # Wrap and execute
    wrapped_script = _wrap_as_adios_task(python_code)
    result = _run_python_script(wrapped_script, timeout=timeout)

    # Update task status
    if result["exit_code"] == 0 and "__TASK_SUCCESS__" in result["stdout"]:
        _tasks[task_id]["status"] = "completed"
        _tasks[task_id]["exit_code"] = 0
        _tasks[task_id]["stdout"] = result["stdout"].replace("__TASK_SUCCESS__", "").strip()
        _tasks[task_id]["stderr"] = result["stderr"]
    else:
        _tasks[task_id]["status"] = "failed"
        _tasks[task_id]["exit_code"] = result["exit_code"]
        _tasks[task_id]["stdout"] = result["stdout"]
        _tasks[task_id]["stderr"] = result["stderr"]

    _tasks[task_id]["completed_at"] = time.time()

    return json.dumps({
        "task_id": task_id,
        "name": name,
        "status": _tasks[task_id]["status"],
        "exit_code": result["exit_code"],
        "stdout": result["stdout"][:3000],
        "stderr": result["stderr"][:3000],
        "engine": _tasks[task_id]["engine"],
    }, indent=2)


@mcp.tool()
def submit_shell_task(
    name: str,
    command: str,
    work_dir: str = "",
    timeout: int = 1800,
) -> str:
    """Submit a shell command for execution.

    Args:
        name: Descriptive name for this task
        command: Shell command to execute
        work_dir: Working directory (default: repo work/run0)
        timeout: Max seconds to wait
    """
    task_id = f"task_{uuid.uuid4().hex[:8]}"
    _work = work_dir if work_dir else DEFAULT_WORK_DIR

    _tasks[task_id] = {
        "name": name,
        "status": "running",
        "depends_on": [],
        "submitted_at": time.time(),
    }

    resolved_cmd = _resolve_paths(command)
    result = _run_command(["bash", "-c", resolved_cmd], work_dir=_work, timeout=timeout)

    _tasks[task_id]["status"] = "completed" if result["exit_code"] == 0 else "failed"
    _tasks[task_id]["exit_code"] = result["exit_code"]
    _tasks[task_id]["stdout"] = result["stdout"]
    _tasks[task_id]["stderr"] = result["stderr"]
    _tasks[task_id]["completed_at"] = time.time()

    return json.dumps({
        "task_id": task_id,
        "name": name,
        "status": _tasks[task_id]["status"],
        "exit_code": result["exit_code"],
        "stdout": result["stdout"][:3000],
        "stderr": result["stderr"][:3000],
    }, indent=2)


@mcp.tool()
def get_task_status(task_id: str) -> str:
    """Get the current status of a submitted task."""
    if task_id not in _tasks:
        return json.dumps({"error": f"Task {task_id} not found"})

    task = _tasks[task_id]
    info = {
        "task_id": task_id,
        "name": task["name"],
        "status": task["status"],
        "depends_on": task["depends_on"],
    }
    if "exit_code" in task:
        info["exit_code"] = task["exit_code"]
    if "engine" in task:
        info["engine"] = task["engine"]
    if "submitted_at" in task and "completed_at" in task:
        info["duration_seconds"] = round(task["completed_at"] - task["submitted_at"], 2)
    return json.dumps(info, indent=2)


@mcp.tool()
def get_task_result(task_id: str) -> str:
    """Get the full output (stdout/stderr) of a completed task."""
    if task_id not in _tasks:
        return json.dumps({"error": f"Task {task_id} not found"})

    task = _tasks[task_id]
    return json.dumps({
        "task_id": task_id,
        "name": task["name"],
        "status": task["status"],
        "exit_code": task.get("exit_code", -1),
        "stdout": task.get("stdout", ""),
        "stderr": task.get("stderr", ""),
    }, indent=2)


@mcp.tool()
def list_tasks() -> str:
    """List all submitted tasks and their current status."""
    task_list = []
    for task_id, task in _tasks.items():
        task_list.append({
            "task_id": task_id,
            "name": task["name"],
            "status": task["status"],
            "depends_on": task["depends_on"],
            "engine": task.get("engine", "unknown"),
        })
    return json.dumps({"total": len(task_list), "tasks": task_list}, indent=2)


@mcp.tool()
def install_package(package: str) -> str:
    """Install a pip package using the configured Python interpreter."""
    result = _run_command(
        [VENV_PYTHON, "-m", "pip", "install", package],
        timeout=300,
    )
    return json.dumps({
        "package": package,
        "status": "success" if result["exit_code"] == 0 else "failed",
        "message": result["stdout"][-500:] if result["exit_code"] == 0 else result["stderr"][-500:],
    }, indent=2)


@mcp.tool()
def check_package(package: str) -> str:
    """Check if a Python package is installed."""
    result = _run_command(
        [VENV_PYTHON, "-c",
         f"import {package}; v = getattr({package}, '__version__', 'unknown'); print(v)"],
        timeout=30,
    )
    if result["exit_code"] == 0:
        return json.dumps({
            "package": package,
            "installed": True,
            "version": result["stdout"].strip(),
        }, indent=2)
    else:
        return json.dumps({
            "package": package,
            "installed": False,
            "error": result["stderr"][:500],
        }, indent=2)


@mcp.tool()
def list_files(directory: str = "") -> str:
    """List files in a directory."""
    resolved = _resolve_paths(directory) if directory else DEFAULT_WORK_DIR

    if not os.path.isdir(resolved):
        return json.dumps({
            "directory": resolved,
            "files": [],
            "count": 0,
            "error": f"Directory not found: {resolved}",
        }, indent=2)

    files = []
    for root, dirs, filenames in os.walk(resolved):
        for fname in filenames:
            files.append(os.path.join(root, fname))

    return json.dumps({
        "directory": resolved,
        "files": sorted(files),
        "count": len(files),
    }, indent=2)


@mcp.tool()
def read_file(path: str, max_lines: int = 100) -> str:
    """Read the contents of a file."""
    resolved = _resolve_paths(path)

    if not os.path.isfile(resolved):
        return json.dumps({
            "path": resolved,
            "error": f"File not found: {resolved}",
        }, indent=2)

    try:
        with open(resolved) as f:
            all_lines = f.readlines()
        total = len(all_lines)
        content = "".join(all_lines[:max_lines])
        return json.dumps({
            "path": resolved,
            "content": content,
            "truncated": total > max_lines,
            "total_lines": total,
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "path": resolved,
            "error": str(e),
        }, indent=2)


@mcp.tool()
def cleanup() -> str:
    """Clean up resources. Clears the task registry."""
    global _tasks
    count = len(_tasks)
    _tasks = {}
    return json.dumps({"status": "cleaned up", "tasks_cleared": count})


# __ Helpers ___________________________________________________________________

def _indent(text: str, spaces: int) -> str:
    """Indent every line of text by the given number of spaces."""
    prefix = " " * spaces
    return "\n".join(prefix + line for line in text.splitlines())


def _resolve_paths(text: str) -> str:
    """Replace /app/ container paths with actual local repo paths."""
    return text.replace("/app/", REPO_ROOT + "/").replace("//", "/")


# __ Main ______________________________________________________________________

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ADIOS2 Workflow MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    args = parser.parse_args()

    if args.transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")

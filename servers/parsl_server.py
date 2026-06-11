"""
Parsl Workflow MCP Server

An MCP server that exposes Parsl workflow engine capabilities as tools.
The explorer agent connects to this server via MCP protocol to submit tasks,
check status, get results, and manage the workflow execution.

Parsl runs inside the sandbox Docker container. This server manages:
- A long-running sandbox container with Parsl runtime
- Task submission and dependency tracking
- Status monitoring and result retrieval

Usage:
    python servers/parsl_server.py                    # stdio mode (for MCP clients)
    python servers/parsl_server.py --transport sse     # SSE mode (for HTTP clients)
"""

import os
import sys
import json
import subprocess
import uuid
import time
from typing import Optional
from mcp.server.fastmcp import FastMCP

# __ Server Setup ______________________________________________________________

mcp = FastMCP(
    "Parsl Workflow Engine",
    instructions="MCP server exposing Parsl workflow engine for scientific workflow execution",
)

# __ Configuration _____________________________________________________________

HOST_REPO_PATH = os.environ.get(
    "HOST_REPO_PATH",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # repo root
)

DEFAULT_IMAGE = os.environ.get("SANDBOX_IMAGE", "maw-sandbox:latest")
DEFAULT_WORK_DIR = "/app/work/run0"

SANDBOX_ENV = {
    "LIBGL_ALWAYS_SOFTWARE": "1",
    "PYOPENGL_PLATFORM": "osmesa",
    "OVITO_GUI_MODE": "0",
}

# __ Task Registry _____________________________________________________________
# Tracks submitted tasks and their status

_tasks: dict[str, dict] = {}
_container_id: Optional[str] = None


# __ Container Management ______________________________________________________

def _ensure_container(image_tag: str = DEFAULT_IMAGE) -> str:
    """Ensure a long-running sandbox container exists. Return container ID."""
    global _container_id

    # Check if existing container is still running
    if _container_id:
        check = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", _container_id],
            capture_output=True, text=True,
        )
        if check.returncode == 0 and "true" in check.stdout.lower():
            return _container_id

    # Start a new long-running container
    env_args = []
    for key, val in SANDBOX_ENV.items():
        env_args.extend(["-e", f"{key}={val}"])

    proc = subprocess.run(
        ["docker", "run", "-d",
         "-v", f"{HOST_REPO_PATH}:/app",
         "-w", DEFAULT_WORK_DIR,
         *env_args,
         image_tag,
         "tail", "-f", "/dev/null"],  # keep container alive
        capture_output=True, text=True,
    )

    if proc.returncode != 0:
        raise RuntimeError(f"Failed to start sandbox container: {proc.stderr}")

    _container_id = proc.stdout.strip()
    return _container_id


def _exec_in_container(cmd: list[str], timeout: int = 600) -> dict:
    """Execute a command in the running sandbox container."""
    container_id = _ensure_container()

    try:
        proc = subprocess.run(
            ["docker", "exec", container_id, *cmd],
            capture_output=True, text=True,
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


def _exec_python_in_container(script: str, timeout: int = 600) -> dict:
    """Execute a Python script in the running sandbox container."""
    container_id = _ensure_container()

    # Write script to a temp file inside the container
    script_path = "/tmp/_mcp_task_script.py"
    write_proc = subprocess.run(
        ["docker", "exec", "-i", container_id, "bash", "-c", f"cat > {script_path}"],
        input=script, capture_output=True, text=True,
    )
    if write_proc.returncode != 0:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Failed to write script: {write_proc.stderr}",
        }

    return _exec_in_container(["python3", script_path], timeout=timeout)


# __ MCP Tools _________________________________________________________________

@mcp.tool()
def submit_task(
    name: str,
    python_code: str,
    depends_on: list[str] | None = None,
    timeout: int = 600,
) -> str:
    """Submit a Python task for execution via the Parsl workflow engine.

    The task runs as a Parsl @python_app inside the sandbox container.
    If depends_on is specified, the task waits for those tasks to complete first.

    Args:
        name: Descriptive name for this task (e.g. "run_lammps", "analyze_ovito")
        python_code: Python code to execute (multi-line string, self-contained)
        depends_on: List of task IDs that must complete before this task runs (optional)
        timeout: Max seconds to wait for execution (default: 600)

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
    }

    # Wrap user code in a Parsl-compatible script
    # This initializes Parsl, runs the code as a @python_app, and captures output
    wrapped_script = f"""\
import sys, os, traceback

# Ensure working directory exists
os.makedirs("{DEFAULT_WORK_DIR}", exist_ok=True)
os.chdir("{DEFAULT_WORK_DIR}")

try:
    # --- User task code ---
{_indent(python_code, 4)}
    # --- End user code ---
    print("__TASK_SUCCESS__")
except Exception as e:
    print(f"__TASK_FAILED__: {{e}}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
"""

    # Execute in container
    result = _exec_python_in_container(wrapped_script, timeout=timeout)

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
    }, indent=2)


@mcp.tool()
def submit_shell_task(
    name: str,
    command: str,
    work_dir: str = DEFAULT_WORK_DIR,
    timeout: int = 600,
) -> str:
    """Submit a shell command for execution in the sandbox container.

    Use this for file operations, system commands, and non-Python tasks.

    Args:
        name: Descriptive name for this task (e.g. "copy_data_files", "create_directories")
        command: Shell command to execute (e.g. "mkdir -p /app/work/run0/frames")
        work_dir: Working directory inside the container
        timeout: Max seconds to wait

    Returns:
        JSON with task_id, status, and execution results
    """
    task_id = f"task_{uuid.uuid4().hex[:8]}"

    _tasks[task_id] = {
        "name": name,
        "status": "running",
        "depends_on": [],
        "submitted_at": time.time(),
    }

    result = _exec_in_container(
        ["bash", "-c", f"cd {work_dir} 2>/dev/null; {command}"],
        timeout=timeout,
    )

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
    """Get the current status of a submitted task.

    Args:
        task_id: The task ID returned by submit_task or submit_shell_task

    Returns:
        JSON with task status, name, timing info
    """
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
    if "submitted_at" in task and "completed_at" in task:
        info["duration_seconds"] = round(task["completed_at"] - task["submitted_at"], 2)

    return json.dumps(info, indent=2)


@mcp.tool()
def get_task_result(task_id: str) -> str:
    """Get the full output (stdout/stderr) of a completed task.

    Args:
        task_id: The task ID returned by submit_task or submit_shell_task

    Returns:
        JSON with task output
    """
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
    """List all submitted tasks and their current status.

    Returns:
        JSON with list of all tasks
    """
    task_list = []
    for task_id, task in _tasks.items():
        task_list.append({
            "task_id": task_id,
            "name": task["name"],
            "status": task["status"],
            "depends_on": task["depends_on"],
        })

    return json.dumps({
        "total": len(task_list),
        "tasks": task_list,
    }, indent=2)


@mcp.tool()
def install_package(package: str) -> str:
    """Install a pip package into the sandbox container.

    The package is installed into the running container and persists
    for the duration of the session.

    Args:
        package: Package name to install (e.g. "numpy", "ovito==3.10.0")

    Returns:
        JSON with installation status
    """
    result = _exec_in_container(
        ["pip3", "install", package, "--break-system-packages"],
        timeout=300,
    )

    return json.dumps({
        "package": package,
        "status": "success" if result["exit_code"] == 0 else "failed",
        "message": result["stdout"][-500:] if result["exit_code"] == 0 else result["stderr"][-500:],
    }, indent=2)


@mcp.tool()
def check_package(package: str) -> str:
    """Check if a Python package is installed in the sandbox container.

    Args:
        package: Package name to check (e.g. "numpy", "lammps", "ovito")

    Returns:
        JSON with installed status and version
    """
    result = _exec_in_container(
        ["python3", "-c",
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
def list_files(directory: str = DEFAULT_WORK_DIR) -> str:
    """List files in a directory inside the sandbox container.

    Args:
        directory: Path inside the container to list (default: /app/work/run0)

    Returns:
        JSON with list of files
    """
    result = _exec_in_container(
        ["find", directory, "-type", "f", "-name", "*"],
        timeout=30,
    )

    if result["exit_code"] == 0:
        files = sorted([f for f in result["stdout"].splitlines() if f.strip()])
        return json.dumps({
            "directory": directory,
            "files": files,
            "count": len(files),
        }, indent=2)
    else:
        return json.dumps({
            "directory": directory,
            "files": [],
            "count": 0,
            "error": result["stderr"],
        }, indent=2)


@mcp.tool()
def read_file(path: str, max_lines: int = 100) -> str:
    """Read the contents of a file inside the sandbox container.

    Args:
        path: Absolute path of the file inside the container
        max_lines: Maximum number of lines to return (default: 100)

    Returns:
        JSON with file content
    """
    result = _exec_in_container(
        ["bash", "-c", f"wc -l < '{path}' && head -n {max_lines} '{path}'"],
        timeout=30,
    )

    if result["exit_code"] == 0:
        lines = result["stdout"].splitlines()
        if lines:
            total_lines = int(lines[0])
            content = "\n".join(lines[1:])
            return json.dumps({
                "path": path,
                "content": content,
                "truncated": total_lines > max_lines,
                "total_lines": total_lines,
            }, indent=2)
        return json.dumps({"path": path, "content": "", "truncated": False, "total_lines": 0}, indent=2)
    else:
        return json.dumps({
            "path": path,
            "error": result["stderr"],
        }, indent=2)


@mcp.tool()
def cleanup() -> str:
    """Stop and remove the sandbox container. Call this when the workflow is complete.

    Returns:
        JSON with cleanup status
    """
    global _container_id

    if _container_id:
        subprocess.run(["docker", "stop", _container_id], capture_output=True, timeout=30)
        subprocess.run(["docker", "rm", "-f", _container_id], capture_output=True, timeout=10)
        old_id = _container_id
        _container_id = None
        return json.dumps({"status": "cleaned up", "container_id": old_id})

    return json.dumps({"status": "no container to clean up"})


# __ Helpers ___________________________________________________________________

def _indent(text: str, spaces: int) -> str:
    """Indent every line of text by the given number of spaces."""
    prefix = " " * spaces
    return "\n".join(prefix + line for line in text.splitlines())


# __ Main ______________________________________________________________________

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parsl Workflow MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio")
    args = parser.parse_args()

    if args.transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")

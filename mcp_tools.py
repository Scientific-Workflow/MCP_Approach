"""
MCP Tools -- Client wrapper that connects to a Workflow Engine MCP Server.

STATUS: CURRENTLY UNUSED (retained for future use)
This module is not imported by any other file in the project as of June 17, 2026.
During the refactoring of mcp_explorer.py, the explorer was changed to connect
directly to the MCP server via mcp.client.stdio, bypassing this intermediate
client layer. This file is kept because:
  1. It defines the ENGINE_SERVERS registry and async connect/disconnect lifecycle
     that may be useful if the architecture is refactored again.
  2. It provides clean async convenience wrappers (submit_task, list_files, etc.)
     that could serve as a standalone MCP client library.
  3. It documents the original design intent of separating the MCP client logic
     from the explorer agent logic.

This module provides the bridge between the explorer agent (LangChain tools)
and the MCP server (Parsl, PyCOMPSs, etc.). It starts the MCP server as a
subprocess, connects via stdio, and exposes the server's tools as local
functions that the explorer can call.

The explorer doesn't know or care which engine is behind the MCP server.
It calls the same tool functions regardless of whether the backend is
Parsl, PyCOMPSs, or ADIOS.
"""

import os
import sys
import json
import asyncio
import subprocess
from typing import Optional
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# __ MCP Client State __________________________________________________________

_session: Optional[ClientSession] = None
_exit_stack: Optional[AsyncExitStack] = None
_server_process = None

# Path to the server script
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_SERVERS_DIR = os.path.join(_PROJECT_ROOT, "servers")

# Python interpreter used to launch the MCP server.
# Prefer VENV_PYTHON env var, then venv3 relative to this file, then sys.executable.
def _resolve_server_python() -> str:
    if os.environ.get("VENV_PYTHON"):
        return os.environ["VENV_PYTHON"]
    candidate = os.path.join(_PROJECT_ROOT, "venv3", "bin", "python3")
    if os.path.isfile(candidate):
        return candidate
    return sys.executable

_SERVER_PYTHON = _resolve_server_python()

# Available engine servers
ENGINE_SERVERS = {
    "parsl": os.path.join(_SERVERS_DIR, "parsl_server.py"),
    "pycompss": os.path.join(_SERVERS_DIR, "pycompss_server.py"),
    "adios": os.path.join(_SERVERS_DIR, "adios_server.py"),
}


# __ Connection Management _____________________________________________________

async def connect_to_server(engine: str = "parsl") -> ClientSession:
    """Start the MCP server subprocess and connect to it via stdio."""
    global _session, _exit_stack

    if _session is not None:
        return _session

    server_path = ENGINE_SERVERS.get(engine)
    if not server_path:
        raise ValueError(f"Unknown engine: {engine}. Available: {list(ENGINE_SERVERS.keys())}")

    if not os.path.isfile(server_path):
        raise FileNotFoundError(f"Server script not found: {server_path}")

    server_params = StdioServerParameters(
        command=_SERVER_PYTHON,
        args=[server_path],
        env={
            **os.environ,
            "HOST_REPO_PATH": os.environ.get(
                "HOST_REPO_PATH",
                os.path.dirname(os.path.abspath(__file__)),
            ),
        },
    )

    _exit_stack = AsyncExitStack()
    stdio_transport = await _exit_stack.enter_async_context(
        stdio_client(server_params)
    )
    read_stream, write_stream = stdio_transport
    _session = await _exit_stack.enter_async_context(
        ClientSession(read_stream, write_stream)
    )
    await _session.initialize()

    return _session


async def disconnect_from_server():
    """Disconnect from the MCP server and clean up."""
    global _session, _exit_stack

    if _session:
        # Call cleanup tool before disconnecting
        try:
            await _session.call_tool("cleanup", {})
        except Exception:
            pass

    if _exit_stack:
        await _exit_stack.aclose()

    _session = None
    _exit_stack = None


async def list_available_tools() -> list[str]:
    """List all tools available from the connected MCP server."""
    if _session is None:
        raise RuntimeError("Not connected to MCP server. Call connect_to_server() first.")

    result = await _session.list_tools()
    return [tool.name for tool in result.tools]


# __ Tool Call Wrapper _________________________________________________________

async def call_tool(tool_name: str, arguments: dict) -> str:
    """Call a tool on the MCP server and return the result as a JSON string."""
    if _session is None:
        raise RuntimeError("Not connected to MCP server. Call connect_to_server() first.")

    result = await _session.call_tool(tool_name, arguments)

    # Extract text content from MCP result
    if result.content:
        # MCP returns content as a list of content blocks
        texts = [block.text for block in result.content if hasattr(block, "text")]
        return "\n".join(texts) if texts else ""

    return "{}"


# __ Convenience Functions _____________________________________________________
# These wrap call_tool for cleaner usage from the explorer agent.
# Each function matches a tool exposed by the MCP server.

async def submit_task(
    name: str,
    python_code: str,
    depends_on: Optional[list[str]] = None,
    timeout: int = 600,
) -> str:
    """Submit a Python task for execution via the workflow engine."""
    args = {"name": name, "python_code": python_code, "timeout": timeout}
    if depends_on:
        args["depends_on"] = depends_on
    return await call_tool("submit_task", args)


async def submit_shell_task(
    name: str,
    command: str,
    work_dir: str = "/app/work/run0",
    timeout: int = 600,
) -> str:
    """Submit a shell command for execution via the workflow engine."""
    return await call_tool("submit_shell_task", {
        "name": name,
        "command": command,
        "work_dir": work_dir,
        "timeout": timeout,
    })


async def get_task_status(task_id: str) -> str:
    """Get the current status of a submitted task."""
    return await call_tool("get_task_status", {"task_id": task_id})


async def get_task_result(task_id: str) -> str:
    """Get the full output of a completed task."""
    return await call_tool("get_task_result", {"task_id": task_id})


async def list_tasks() -> str:
    """List all submitted tasks and their status."""
    return await call_tool("list_tasks", {})


async def install_package(package: str) -> str:
    """Install a pip package into the local venv."""
    return await call_tool("install_package", {"package": package})


async def check_package(package: str) -> str:
    """Check if a Python package is installed in the local venv."""
    return await call_tool("check_package", {"package": package})


async def list_files(directory: str = "/app/work/run0") -> str:
    """List files in a directory in the working tree."""
    return await call_tool("list_files", {"directory": directory})


async def read_file(path: str, max_lines: int = 100) -> str:
    """Read the contents of a file in the working tree."""
    return await call_tool("read_file", {"path": path, "max_lines": max_lines})


async def get_resources() -> str:
    """Return available compute resources (PBS vars or local fallback)."""
    return await call_tool("get_resources", {})


async def submit_mpi_task(
    name: str,
    command: str,
    num_ranks: int = 0,
    work_dir: str = "/app/work/run0",
    timeout: int = 1800,
) -> str:
    """Submit a command to run under MPI (mpirun). Prepends the launcher automatically."""
    return await call_tool("submit_mpi_task", {
        "name":      name,
        "command":   command,
        "num_ranks": num_ranks,
        "work_dir":  work_dir,
        "timeout":   timeout,
    })

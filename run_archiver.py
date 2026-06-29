"""
Run Archiver -- snapshots a completed run's output and trace into a permanent,
self-describing folder outside the repo, then clears work/run0 for the next run.

work/run0/ is a single fixed working directory shared by every run (see
DEFAULT_WORK_DIR in servers/parsl_server.py and servers/pycompss_server.py) --
it gets overwritten by whatever the next run does. archive_run() is the one
place that captures a permanent copy before that happens.

This is the single-agent (Condition C) sibling of the archiver in
MCP_Approach -- same logic, archiving under a separate single_approach/
namespace so the two repos' runs never collide in TEST_RUNS.

Usage (called from agent_mcp.py after tracer.save(trace_path), on both the
success and failure paths):

    from run_archiver import archive_run
    archive_path = archive_run(tracer.run_metadata, trace_path)
"""

import os
import re
import shutil
import sys

from trace_schema import RunMetadata

# Lives outside the repo: committing MCP_Approach_SINGLE should never drag run
# output along. single_approach/ is the sibling of MCP_Approach's mcp_approach/
# namespace so the two never collide.
ARCHIVE_ROOT = "/gpfs/fs1/home/jacob.oh/SULI/TEST_RUNS/single_approach"

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_WORK_DIR = os.path.join(_REPO_ROOT, "work", "run0")


def _slugify(value: str) -> str:
    """Filesystem-safe segment for the archive folder name. Mirrors the
    _slugify helper in agent_mcp.py -- duplicated rather than imported to
    avoid a circular import (agent_mcp.py imports archive_run from here)."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value or "").strip("_")
    return slug or "unknown"


def _folder_name(metadata: RunMetadata) -> str:
    date = metadata.run_id[:8] if len(metadata.run_id) >= 8 else metadata.run_id
    usecase = metadata.domain or metadata.paper_id
    return "__".join([
        _slugify(date),
        _slugify(usecase),
        _slugify(metadata.framework),
        _slugify(metadata.condition),
        _slugify(metadata.combination),
        f"trial{metadata.trial}",
    ])


def _unique_dest(root: str, name: str) -> str:
    """Windows-style collision handling: name, then 'name (2)', 'name (3)', ..."""
    dest = os.path.join(root, name)
    if not os.path.exists(dest):
        return dest
    n = 2
    while True:
        candidate = os.path.join(root, f"{name} ({n})")
        if not os.path.exists(candidate):
            return candidate
        n += 1


def archive_run(metadata: RunMetadata, trace_path: str) -> str:
    """Copy work/run0 + trace.json into ARCHIVE_ROOT/<slug>/, then wipe run0.

    Called on both success and failure so a failed run's diagnostics are
    never silently dropped. Never raises -- a broken archiver should not
    take down a real run's exit status. Returns the archive folder path,
    or "" if archiving failed.
    """
    try:
        os.makedirs(ARCHIVE_ROOT, exist_ok=True)
        dest = _unique_dest(ARCHIVE_ROOT, _folder_name(metadata))
        os.makedirs(dest)

        if os.path.isdir(_WORK_DIR):
            shutil.copytree(_WORK_DIR, os.path.join(dest, "work"))
        if os.path.isfile(trace_path):
            shutil.copy2(trace_path, os.path.join(dest, "trace.json"))

        # Only clear run0 once the copy above has actually landed, so a
        # mid-copy failure never leaves us with neither a backup nor the original.
        if os.path.isdir(_WORK_DIR):
            shutil.rmtree(_WORK_DIR)
            os.makedirs(_WORK_DIR)

        return dest
    except Exception as e:
        print(f"[run_archiver] WARNING: failed to archive run {metadata.run_id}: {e}",
              file=sys.stderr)
        return ""

"""
Run Archiver -- snapshots a completed run's output and trace into a permanent,
self-describing folder outside the repo, then clears work/run0 for the next run.

work/run0/ is a single fixed working directory shared by every run (see
DEFAULT_WORK_DIR in servers/parsl_server.py and servers/pycompss_server.py) --
it gets overwritten by whatever the next run does. archive_run() is the one
place that captures a permanent copy before that happens.

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

# Lives outside the repo: committing MCP_Approach should never drag run output
# along, and the eventual Artifact ("single") approach will archive alongside
# it under a sibling folder so the two never collide.
_HPC_ARCHIVE_ROOT = "/gpfs/fs1/home/jacob.oh/SULI/TEST_RUNS/mcp_approach"


def _default_archive_root() -> str:
    """Pick an archive root that actually exists on this machine.

    Priority:
      1. MCP_ARCHIVE_ROOT env var (explicit override, HPC or local).
      2. The LCRC/HPC path, if its parent exists (teammate's HPC runs).
      3. ~/MCP_runs as a local fallback -- so a laptop run always archives
         somewhere instead of silently dropping the output (which is what used
         to happen when the gpfs path wasn't creatable and no env var was set).
    """
    env = os.environ.get("MCP_ARCHIVE_ROOT")
    if env:
        return os.path.expanduser(env)
    if os.path.isdir(os.path.dirname(_HPC_ARCHIVE_ROOT)):
        return _HPC_ARCHIVE_ROOT
    return os.path.expanduser("~/MCP_runs")


ARCHIVE_ROOT = _default_archive_root()

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
_WORK_DIR = os.path.join(_REPO_ROOT, "work", "run0")


def _slugify(value: str) -> str:
    """Filesystem-safe segment for the archive folder name. Mirrors the
    _slugify helper in agent_mcp.py -- duplicated rather than imported to
    avoid a circular import (agent_mcp.py imports archive_run from here)."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value or "").strip("_")
    return slug or "unknown"


def _run_name(metadata: RunMetadata) -> str:
    """Human-readable label for the run: the paper's file name if a paper was
    used, otherwise the use-case/domain (combination "d" has no paper)."""
    if getattr(metadata, "paper_path", None):
        base = os.path.splitext(os.path.basename(metadata.paper_path))[0]
        if base:
            return base
    return metadata.domain or (metadata.paper_id if metadata.paper_id != "no_paper" else "") or "run"


def _folder_name(metadata: RunMetadata) -> str:
    """<name>_<MMDD>_<HHMMSS> -- e.g. molecular_0721_105840.

    name is the paper / use-case (see _run_name). The timestamp comes from
    run_id (YYYYMMDD_HHMMSS): MMDD = chars 4:8, HHMMSS = chars 9:15. Falls back
    to the slugified run_id if it isn't in the expected shape."""
    rid = metadata.run_id or ""
    if len(rid) >= 15 and rid[8] == "_":
        stamp = f"{rid[4:8]}_{rid[9:15]}"
    else:
        stamp = _slugify(rid)
    return f"{_slugify(_run_name(metadata))}_{stamp}"


def _run_start_epoch(metadata: RunMetadata):
    """Epoch seconds for when the run started -- from run_id (YYYYMMDD_HHMMSS) or
    start_time. Used to archive only this run's files (mtime >= start), not the
    stale output of previous runs that share the fixed work/run0 directory."""
    import datetime
    try:
        return datetime.datetime.strptime(metadata.run_id[:15], "%Y%m%d_%H%M%S").timestamp()
    except Exception:
        pass
    try:
        return datetime.datetime.fromisoformat(metadata.start_time).timestamp()
    except Exception:
        return None


def _copy_run_files(src_work: str, dest_work: str, since_epoch: float) -> None:
    """Copy only files written during this run (mtime >= since_epoch), preserving
    the directory structure. Skips stale outputs from earlier runs."""
    for dirpath, _, filenames in os.walk(src_work):
        for fn in filenames:
            src = os.path.join(dirpath, fn)
            try:
                if os.path.getmtime(src) < since_epoch:
                    continue
            except OSError:
                continue
            dst = os.path.join(dest_work, os.path.relpath(src, src_work))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)


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
    """Copy work/run0 + trace.json into ARCHIVE_ROOT/<slug>/.

    Called on both success and failure so a failed run's diagnostics are
    never silently dropped. Never raises -- a broken archiver should not
    take down a real run's exit status. Returns the archive folder path,
    or "" if archiving failed.

    Does NOT clear work/run0 afterward -- it used to (wipe + recreate, gated
    behind a successful copy), but since work/run0 is a single fixed directory
    shared by every run, the next run's own setup tasks (re-copying input
    files, run_lammps's own pre-run frame cleanup, etc.) are what's actually
    responsible for not stepping on stale output, not a blanket wipe here.
    Leaving the directory alone after archiving means a run is never one
    archive-step bug away from losing both the copy and the original.
    """
    try:
        os.makedirs(ARCHIVE_ROOT, exist_ok=True)
        dest = _unique_dest(ARCHIVE_ROOT, _folder_name(metadata))
        os.makedirs(dest)

        if os.path.isdir(_WORK_DIR):
            # Archive only THIS run's files (mtime >= run start) so the folder isn't
            # polluted by stale output left in the shared work/run0 by earlier runs.
            # Fall back to a full copy if the start time can't be determined.
            _since = _run_start_epoch(metadata)
            if _since is not None:
                _copy_run_files(_WORK_DIR, os.path.join(dest, "work"), _since)
            else:
                shutil.copytree(_WORK_DIR, os.path.join(dest, "work"))
        if os.path.isfile(trace_path):
            shutil.copy2(trace_path, os.path.join(dest, "trace.json"))

        return dest
    except Exception as e:
        print(f"[run_archiver] WARNING: failed to archive run {metadata.run_id}: {e}",
              file=sys.stderr)
        return ""

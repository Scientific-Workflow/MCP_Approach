"""
extract_code.py -- Unpack the agent-generated code from a trace into readable files.

The tracer already stores every generated snippet inside each tool_call event's
`args` (submit_task -> python_code, submit_shell_task/submit_mpi_task -> command).
This script pulls them out of a runs/*_trace.json and writes one file per call,
so you get human-readable, runnable .py / .sh files instead of digging through JSON.

Output layout:
    runs/<run_id>_code/
        index.md                              <- summary table of every snippet
        001_iter01_check_adios2_stream__ok.py
        002_iter02_create_dirs__ok.sh
        ...

File-name encoding:  <seq>_iter<NN>_<taskname>__<ok|FAIL>.<py|sh>

Usage:
    python extract_code.py                                  # newest trace in runs/
    python extract_code.py runs/20260626_215336_trace.json # a specific trace
    python extract_code.py --success-only                   # skip failed attempts
    python extract_code.py --final-only                     # keep only last attempt per task name
"""
import os
import re
import sys
import json
import argparse


def _slug(s: str, n: int = 40) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", (s or "unnamed")).strip("_").lower()
    return (s[:n] or "unnamed")


def _newest_trace() -> str:
    runs = "runs"
    cands = sorted(f for f in os.listdir(runs) if f.endswith("_trace.json")) if os.path.isdir(runs) else []
    if not cands:
        sys.exit("No runs/*_trace.json found. Pass a path explicitly.")
    return os.path.join(runs, cands[-1])


def extract(trace_path: str, success_only: bool = False, final_only: bool = False) -> str:
    with open(trace_path) as f:
        data = json.load(f)

    meta = data.get("run_metadata", {})
    run_id = meta.get("run_id") or os.path.basename(trace_path).replace("_trace.json", "")
    out_dir = os.path.join("runs", f"{run_id}_code")
    os.makedirs(out_dir, exist_ok=True)

    # Pull every code-bearing tool call, in execution order.
    snippets = []  # {iter, name, kind, ext, code, ok}
    for e in data.get("trace", []):
        if e.get("type") != "tool_call":
            continue
        tool = e.get("tool", "")
        args = e.get("args", {}) or {}
        if tool == "submit_task" and "python_code" in args:
            code, ext, kind = args["python_code"], "py", "python"
        elif tool in ("submit_shell_task", "submit_mpi_task") and "command" in args:
            code, ext, kind = args["command"], "sh", "shell"
        else:
            continue
        snippets.append({
            "iter": e.get("iteration") or 0,
            "name": args.get("name", tool),
            "kind": kind,
            "ext": ext,
            "code": code,
            "ok": bool(e.get("succeeded")),
        })

    if success_only:
        snippets = [s for s in snippets if s["ok"]]

    if final_only:
        # keep only the last snippet per task name (later attempts overwrite earlier)
        last = {}
        for s in snippets:
            last[s["name"]] = s
        snippets = list(last.values())

    # Write files + build index
    index_rows = []
    for i, s in enumerate(snippets, 1):
        status = "ok" if s["ok"] else "FAIL"
        fname = f"{i:03d}_iter{int(s['iter']):02d}_{_slug(s['name'])}__{status}.{s['ext']}"
        path = os.path.join(out_dir, fname)
        header = (f"# task: {s['name']}\n# iteration: {s['iter']}\n# succeeded: {s['ok']}\n"
                  f"# run: {run_id}\n\n") if s["ext"] == "py" else \
                 (f"#!/usr/bin/env bash\n# task: {s['name']} | iter {s['iter']} | ok={s['ok']}\n\n")
        with open(path, "w") as f:
            f.write(header + s["code"].lstrip("\n"))
        index_rows.append((i, s["iter"], s["name"], s["kind"], status, fname))

    # index.md
    with open(os.path.join(out_dir, "index.md"), "w") as f:
        f.write(f"# Generated code -- run {run_id}\n\n")
        f.write(f"- Paper: `{meta.get('paper_id','?')}`  ·  Engine: `{meta.get('framework','?')}`\n")
        f.write(f"- Snippets extracted: **{len(snippets)}** "
                f"({'success-only' if success_only else 'all attempts'}"
                f"{', final-only' if final_only else ''})\n\n")
        f.write("| # | iter | task | kind | status | file |\n|---|---|---|---|---|---|\n")
        for seq, it, name, kind, status, fname in index_rows:
            f.write(f"| {seq} | {it} | {name} | {kind} | {status} | `{fname}` |\n")

    print(f"Extracted {len(snippets)} snippet(s) -> {out_dir}/")
    print(f"  index: {out_dir}/index.md")
    return out_dir


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Extract agent-generated code from a trace.json")
    ap.add_argument("trace", nargs="?", help="Path to runs/*_trace.json (default: newest)")
    ap.add_argument("--success-only", action="store_true", help="Skip failed attempts")
    ap.add_argument("--final-only", action="store_true", help="Keep only the last attempt per task name")
    args = ap.parse_args()
    extract(args.trace or _newest_trace(),
            success_only=args.success_only, final_only=args.final_only)

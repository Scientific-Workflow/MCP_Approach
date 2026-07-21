# Changelog

## [master_feat/clarifier] — 2026-07-21

Two features on this branch — an optional **Clarifier** node and **per-run output
archiving** — plus one infra fix. See `README_clarifier_archive.md` for the
overview and run instructions. Detailed, file-by-file changes below.

### Added
- **`clarifier.py`** *(new module)* — turns an underspecified request into a filled
  6-slot task spec, **asking only the missing slots**.
  - `run_clarifier(seed_prompt, answer_fn, fill_fn, detect_fn)` — 3 steps:
    (1) `detect_fn` decides which slots the prompt already covers;
    (2) ask the user only the uncovered slots;
    (3) `fill_fn` (LLM) assumes any slot still left blank.
  - Per-slot provenance: `prompt` / `user` / `agent`.
  - Pluggable I/O: `cli_answer_fn` (real CLI), `make_simulated_user_answer_fn`
    (batch evaluation with a ground-truth spec).
  - `_default_detect_fn` / `_default_fill_fn` — LLM calls (lazy `langchain_openai`
    import, `streaming=True`). Returns `{}` on any parse failure (safe fallback).
  - `format_clarified_spec` — renders the filled slots into the planner-facing spec.

### Changed — `agent_mcp.py`
- `import clarifier`.
- `OrchestratorOutput.next`: `Literal[..., "clarifier", ...]` — added `"clarifier"`.
- `ORCHESTRATOR_SYSTEM_PROMPT` (both the full and the no-skills variant): added the
  rule to route to `clarifier` when the request is underspecified and not yet
  clarified, and to do so **at most once**.
- `AgentState`: added `combination: str`, `clarified_spec: str`, `clarified: bool`.
- Orchestrator node:
  - Adds `Request clarified so far: yes/no` and the clarified spec to the LLM context.
  - Hard-override **loop-guard**: if the LLM picks `clarifier` but `clarified` is
    already true, force `planner`.
- New `clarifier_node()` — runs `clarifier.run_clarifier(goal)` with the CLI
  answer_fn, prints the clarified spec, logs to the tracer, and returns
  `{clarified_spec, clarified: True, current_step: "clarifier_complete"}`.
- Graph wiring: `add_node("clarifier", clarifier_node)`; `"clarifier"` added to the
  orchestrator's conditional edges; `add_edge("clarifier", "orchestrator")`.
- Planner: consumes `clarified_spec` (new `Task specification (from clarifier)`
  section) and is PDF-optional (`if state.get("pdf_path")` guard).
- **Removed** the old pre-processing clarifier block in `__main__` (the
  `if args.combination == "d": clarifier.run_clarifier(...)` step and its trace
  logging) — the clarifier is now fully graph-driven.
- `initial_state`: `clarified_spec: ""`, `clarified: False` (kept `combination`).

### Changed — `run_archiver.py`
- **Per-run folder naming**: `_folder_name()` now returns
  `<name>_<MMDD>_<HHMMSS>` (e.g. `molecular_0721_105840`), where `name` comes from
  the new `_run_name()` — the paper's file basename if a paper was used, otherwise
  the `--domain`. (Was: `<date>__<usecase>__<framework>__<condition>__<combination>__trial<N>`.)
- **Smart `ARCHIVE_ROOT` resolution** via `_default_archive_root()`:
  1. `MCP_ARCHIVE_ROOT` env var if set;
  2. else the LCRC/HPC path if its parent exists (HPC runs);
  3. else `~/MCP_runs` (local fallback — a laptop run no longer silently drops
     output when the gpfs path isn't creatable).
- (Unchanged, from earlier) `_copy_run_files()` copies only files with
  `mtime >= run start`, so an archive contains only that run's output, not stale
  files left in the shared `work/run0`.

### Fixed — `mcp_explorer.py`
- `streaming=True` on the coder-model `ChatOpenAI` client — the Argo endpoint
  returns `500 - Streaming is required...` for requests that may exceed 10 minutes.

### Notes
- `work/run0` (the shared scratch directory) is intentionally left untouched, since
  it is hard-coded as `DEFAULT_WORK_DIR` in the MCP servers and referenced in skill
  text as `/app/work/run0`. Isolation is achieved at archive time, not by changing
  the working directory.
- `builds/requirements.txt` was **not** modified on this branch (an unrelated local
  edit that would have dropped `pymech`/`adios2` — needed for the eddy use case —
  was reverted before committing).

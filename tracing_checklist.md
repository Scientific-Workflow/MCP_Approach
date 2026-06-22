# Tracing Infrastructure — Implementation Checklist

Scope: build the tracing layer described in Section 6 of `maw_evaluation_plan.md`,
before forking the codebase into conditions A/B/C. Nothing here touches the
ablation conditions themselves.

**Status: implemented on top of master (2026-06-22).** Built fresh against the
new schema rather than merging `origin/fix/token-tracking` — that branch's
relevant piece (`log_token_usage`) is fully superseded by the new `LLMCall`
event, which also captures full prompt/response and latency, which the branch
never did. The branch's unrelated work (ADIOS server, real Parsl backend, new
papers) was left untouched, per "without messing with any of the other
features or structure." New/changed files: `trace_schema.py` (new),
`trace_logger.py` (rewritten), `agent_mcp.py`, `mcp_explorer.py`.

---

## 0. Branch reconciliation

- [x] **Resolved: build fresh, don't merge.** `origin/fix/token-tracking`'s
      `log_token_usage`/`extract_usage` only logged token counts, never
      prompt/response content — the new `LLMCall` event supersedes it
      entirely. The branch's unrelated work (ADIOS server, real Parsl
      backend, new papers, notebook waterfall) was left alone.
- [ ] The `runs/*_trace.json` / `*.jsonl` files already in the repo predate
      the new schema and won't validate against it — still sitting there,
      not cleaned up. Low priority; they're just stale artifacts.

## 1. Pydantic schema (foundation)

- [x] One Pydantic model per event type in `trace_schema.py`: `AgentStartEvent`,
      `AgentInputEvent`, `AgentOutputEvent`, `AgentEndEvent`, `RoutingEvent`,
      `ToolCallEvent`, `SkillLoadEvent`, `LLMCallEvent`, `ReplanEvent`,
      `RunErrorEvent`, `ArtifactManifestEvent`, `MessageEvent`.
- [x] **`LLMCallEvent` added** — agent, model, full `messages` list, full
      `response` text, `tool_calls`, input/output/total tokens, `latency_s`,
      `attempt`, absolute timestamp.
  - [x] `_invoke_structured()` in `agent_mcp.py` now takes an `agent_name`
        param and logs one `LLMCall` per retry attempt (not just the final
        success) — `attempt` field tracks which try it was.
  - [x] The two-pass skill-loading re-invoke logs its own separate `LLMCall`.
  - [x] The explorer's ReAct loop logs one `LLMCall` per iteration, including
        `tool_calls` requested that iteration.
- [x] Top-level `TraceFile` model: `{run_metadata, trace: list[Event], summary}`.
- [x] Discriminated union on `type` (Pydantic `Field(discriminator="type")`).
- [x] `trace_logger.py`'s `log_*` methods construct + validate the Pydantic
      model, then `.model_dump()` into `self.events`.
- [x] Schema lives in its own module, `trace_schema.py`, imported by
      `trace_logger.py`, `agent_mcp.py`, and `mcp_explorer.py`.

## 2. Remove truncation (full-fidelity capture)

- [x] `log_agent_input` / `log_agent_output`: no truncation — `data: dict`
      stored as-is.
- [x] `log_tool_call`: no arg/result truncation.
- [x] `log_routing`: no reasoning/feedback truncation.
- [x] `mcp_explorer.py` call site now passes the full `tool_result`, not a slice.
- [x] `exploration_log`'s internal `[:2000]` cap **kept as-is** — it's
      LLM-context bookkeeping for the explorer's own summary, not the trace;
      the full value already lives in the `tool_call` trace event regardless.
- [x] `_MAX_TOOL_RESULT_CHARS = 8000` (bounds what re-enters the LLM's own
      context window) — confirmed untouched, separate concern from trace
      fidelity.
- [ ] Sanity-check trace file size **on a real run** — only verified via a
      synthetic smoke test so far (large strings round-tripped intact, see
      Section 9). No real pipeline run has been executed yet to see actual
      file size with real PDF text + real multi-turn explorer prompts.

## 3. Skill-file load logging

- [x] `tracer.log_skill_load(agent, skill_path, found)` added to `trace_logger.py`.
- [x] `_read_skill()` in `agent_mcp.py` takes `agent_name` and logs every read,
      including misses.
- [x] `_read_skill()` in `mcp_explorer.py` logs every read (defaults to
      `agent_name="explorer"` since that module is explorer-only).
- [x] `_env_knowledge()` now takes `agent_name` and logs through `_read_skill`.
- [x] Use-case auto-detection loop in `mcp_explorer.py` refactored to call
      `_read_skill()` instead of a raw `open()` — now traced, and removes a
      small duplicate file-reading path in the process.
- [x] Two-pass `skill_requests` loading in orchestrator/planner now passes
      `agent_name` through to `_read_skill()`.
- [x] **Resolved: do not add a real `load_skill` tool.** Adding new explorer
      capability is out of scope for "tracing, don't touch other features."
      Instead the success-detection bug (below) ensures the hallucinated call
      is now correctly logged as a failure instead of a false success.
- [x] Success-detection bug fixed: `mcp_explorer.py`'s non-JSON fallback now
      checks for an `"unknown tool"` / `"error"` prefix and marks those failed,
      instead of defaulting every non-JSON response to `succeeded=True`.

## 4. Run-level metadata

All fields implemented in `trace_schema.RunMetadata`, populated in `agent_mcp.py`'s
`__main__` via `tracer.start_run(...)`:

- [x] `run_id` — generated once (`YYYYMMDD_HHMMSS` at run **start**, not end —
      see note below) and reused for both the `.jsonl` log and `_trace.json` filename.
- [x] `condition` — new `--condition {A,B,C}` CLI flag, default `"B"`.
- [x] `trial` — new `--trial` CLI flag, default `1`.
- [x] `paper_id` — auto-slugified from the PDF filename via new `_slugify()` helper.
- [x] `paper_path`, `framework` (`--engine`), `env` (`--env`), `goal` — wired
      from existing args/state.
- [x] `domain` — new `--domain` CLI flag (optional, no auto-detection source exists).
- [x] `model` — single string from `MODEL_NAME` env var (confirmed: one model
      across all agents).
- [x] `seed` — present in schema as `Optional[int] = None`; stays `null`,
      since no sampling seed exists anywhere in the code.
- [x] `start_time` / `end_time` — absolute ISO timestamps, set in
      `start_run()` / `finalize_run()`.
- [x] `final_status` — `"completed"` on normal return, `"failed"` if an
      exception propagates out of `app.invoke()`.
- [x] `config_spec_ref` — present in schema as `Optional[str] = None`; stays
      `null` until GT artifacts exist (Section 7 of the plan).
- [x] `code_commit` — auto-captured via `git rev-parse HEAD` in `trace_logger.py`.
- [x] **Resolved:** `run_id` is now generated *before* `app.invoke()` (it used
      to be generated after, from the end timestamp) — required so a crash
      mid-run still has a `trace_path` to save to. This shifts the trace
      filename's meaning from "when the run ended" to "when the run started,"
      a deliberate, minor behavior change needed for crash safety (Section 5).

## 5. Reliability / crash safety

- [x] `app.invoke(initial_state)` wrapped in try/except in `agent_mcp.py`'s
      `__main__`; `tracer.save()` now runs in both the success and exception paths.
- [x] On exception: `tracer.log_run_error(error_type, message, traceback)` is
      logged before saving.
- [x] `final_status="failed"` set automatically in the except branch.
- [x] Partial events are preserved — confirmed via the synthetic crash-path
      smoke test (Section 9): `log_run_error` + prior events all round-tripped.
- [ ] Pipeline-level wall-clock timeout — **still not implemented**, by
      design (deferred). `final_status` already has a `"timeout"` value
      reserved in the schema for whenever that gets built.

## 6. Event-level enrichments

- [x] `latency_s` on every `LLMCall` (measured around each `invoke()` call,
      separate from cumulative `elapsed_s`).
- [x] `iteration` on `tool_call` events, sourced from the explorer's existing
      loop counter.
- [x] Absolute ISO `timestamp` added to every event type (was previously only
      on `agent_start`).
- [x] End-of-run artifact manifest: `mcp_explorer.py` walks `work/` after the
      ReAct loop ends and logs `(path, size_bytes)` for every file via
      `log_artifact_manifest`.
- [x] `planner_revisions`/`installer_revisions`/`explorer_revisions` now
      surfaced via `tracer.log_replan(agent, revision)` whenever the
      orchestrator routes back to an agent that already ran.
- [x] `payload_size` on routing events — byte length of the JSON-serialized
      state update returned by the orchestrator node for that transition.

## 7. Cleanup / consolidation

- [x] **Resolved: left `_run_log_path` (the routing-only JSONL log) untouched.**
      It's redundant with the new trace now, but removing/folding it counts as
      "messing with other structure" — out of scope for this pass.
- [x] **Resolved:** wrote `LLMCall`/token capture fresh against the new
      schema rather than porting `origin/fix/token-tracking`'s helpers (see
      Section 0).

## 8. Explicitly deferred (unchanged — not attempted this pass)

- [ ] Real LangSmith wiring — still just the notebook's local matplotlib
      waterfall, no actual LangSmith integration.
- [ ] Condition A/B/C forking itself — out of scope by design.

## 9. Verification pass

- [x] `python -m py_compile` on all four changed/new files — clean.
- [x] `import agent_mcp` / `import mcp_explorer` — both import cleanly, graph
      compiles with all 4 nodes.
- [x] Synthetic round-trip test: built one of every event type with
      multi-KB strings, saved via `tracer.save()`, reloaded the JSON, and
      validated it against `TraceFile`. Confirmed no truncation anywhere
      (5000-char system prompt, 5000-char response, 9000-char tool result all
      came back intact), `iteration`, `payload_size`, `code_commit`, and
      `final_status="failed"` all round-tripped correctly.
- [ ] **Not done: an actual end-to-end pipeline run.** The synthetic test
      validates the logging/schema layer in isolation, but a real run (real
      LLM calls, real MCP tool calls, real PBS/LAMMPS execution) hasn't been
      exercised against this code yet. This costs real API calls and HPC
      allocation, so it wasn't run unilaterally — recommend running one real
      trial (e.g. the existing molecular-nucleation paper) to confirm the
      integration end-to-end before treating this as fully verified.
- [ ] Deliberately triggering a failure **inside a real CLI run** (vs. the
      synthetic test above) hasn't been done — same reasoning as above.

# Implementation Log (LOCAL — do not commit)

Detailed development record distilled from the git history + working notes, written
as raw material for the SULI report. Each entry has **What / Why / Problem / Fix /
→ report section**. Commit messages are shorthand; this file is the prose-ready version.

> **Scope note.** This repository starts at the MCP approach. The earlier
> **workflow-as-artifact (codegen + executor)** approach — built, evaluated, then
> deliberately abandoned — is **not** in this repo's history. The artifact-vs-tool
> comparison (report §4) must draw on that separate repo / personal notes.
>
> **Division of labor.** Ivy = framework implementation (this log). Teammate = HPC
> running + evaluation (separate paper). Shared interface = the `trace.json` format.

Project in one line: *given only a workflow paper, a multi-agent system (orchestrator →
planner → installer → explorer) autonomously plans, installs, generates, and executes
the workflow by treating the workflow engine as an interactive MCP tool.*

---

## Chronological development log

### Phase 1 — Foundation & first generalization (Jun 11)
- **What:** First working MCP approach — the workflow engine is exposed as an MCP server whose tools a ReAct "explorer" agent calls interactively. Added auto use-case matching and local/venv execution; encoded scientific-integrity rules in the prompts (no fabricated/benchmark data).
- **Why:** Establish the core bet — *workflow-as-tool* rather than generating a standalone script — and avoid hard-coding a single workflow.
- **Problem / Fix:** Early timeout and broken-pipe issues surfaced when tasks ran long; added timeout/pipe handling. A second paper was used to sanity-check generality.
- **→ report:** §3 (architecture), §4 (design decision), §5 (generalization), §8 (proof-of-function).

### Phase 2 — Conventions & reliability of generated tasks (Jun 12)
- **What:** Clarified `/app/` path resolution in the explorer prompt; enforced a single output convention (`/app/work/run0/...`); cleaned up Docker.
- **Why:** Generated task code kept writing to inconsistent/absolute paths, breaking downstream steps. A fixed path contract (`/app/` → resolved at runtime by the server) made tasks portable and outputs findable.
- **→ report:** §6 (robustness / engineering details).

### Phase 3 — Second backend + usability (Jun 15)
- **What:** Added the **PyCOMPSs** MCP server behind the same tool interface (fallback mode verified). Added paper-skip and data-file selection.
- **Why:** First real test of the engine-agnostic design — could a *different* scheduler sit behind the identical tool set with the agent layer unchanged? Yes.
- **Note:** PyCOMPSs runs in **fallback** locally (no COMPSs runtime installed); real mode requires `runcompss` on HPC.
- **→ report:** §5 (engine-agnostic design).

### Phase 4 — Environment adaptation, MPI, and traceability (Jun 16)
- **What:** Separated local vs HPC runtime; added the `get_resources` MCP tool (reads PBS env vars); enabled MPI task execution. Fixed LAMMPS install issues under MPI. **Added the trace logger + demo Jupyter notebook.**
- **Why:** The same agents must behave correctly in two environments; environment knowledge is injected via skills, not hard-coded. The trace logger (`trace.json`) became the backbone for observability and every figure — and later the interface to the teammate's evaluation.
- **Problem / Fix:** LAMMPS Python bindings failed to load Intel-MPI shared libs; fixed via `LD_LIBRARY_PATH` setup (`setup_hpc.sh` for the agent process; `TASK_ENV` for task subprocesses).
- **→ report:** §5 (environment adaptation), §6 (traceability), §8.

### Phase 5 — Robustness pass + observability (Jun 17)
- **What:** Fixed multi-rank runs (the `run_lammps` MPI path: `mpirun -n <ranks> lmp`). Fixed an installer infinite loop. Added token-usage reporting. Marked `mcp_tools.py` as currently-unused with a documented rationale.
- **Why:** Move from "works once" to "works reliably and is observable." Token reporting gives a cost signal; documenting dead code prevents confusion (explorer manages its own MCP session, so `mcp_tools.py` is unused).
- **→ report:** §6 (robustness, cost observability), §3 (architecture hygiene).

### Phase 6 — Third backend, different paradigm (Jun 18)
- **What:** Added the **ADIOS2** MCP server — a *third* backend behind the identical 10-tool interface, with the agent layer unchanged.
- **Why:** The strongest generalization evidence: ADIOS2 is **not a scheduler** but an I/O/streaming framework, so supporting it shows the abstraction holds across *paradigms*, not just across similar schedulers.
- **Note:** ADIOS2 also runs in fallback locally (numpy `.npy/.npz` I/O) when the `adios2` bindings are absent.
- **→ report:** §5 (core generalization claim).

### Phase 7 — Real Parsl integration (Jun 19, branch `feat/real-parsl`, merged)
- **What:** Routed task execution through a **real Parsl DataFlowKernel**: every command now runs as a Parsl `@python_app` (HighThroughputExecutor + LocalProvider) via a single `_run_command` chokepoint, with graceful subprocess fallback; `cleanup()` shuts the DFK down.
- **Why:** Investigation found the "parsl" server had **no `import parsl`** — it was nominal; parallelism came only from `mpirun`. This change makes the engine name accurate (tasks become AppFutures scheduled by the DFK).
- **Verification:** MCP smoke test + full agent run (`--engine parsl`) — DFK loaded, zero fallback, end-to-end success.
- **Caveat:** each MCP tool still blocks on `.result()` (synchronous contract); true cross-task DAG parallelism (async submit) is future work.
- **→ report:** §5 (real engine integration), §6, §9 (future work).

### Phase 8 — Documentation & visualization (Jun 20)
- **What:** Added code comments; added a self-contained **LangSmith-style waterfall** figure built from `trace.json` (agent spans + tool calls, success/failure colors, token annotations).
- **Why:** A trace-style waterfall communicates the run at a glance without depending on an external service (LangSmith would also miss the MCP-execution layer and isn't reproducible for reviewers).
- **→ report:** §6 (traceability), figures.

### Phase 9 — Teammate's HPC follow-on (built on the real-Parsl base)
- **What (teammate):** `fix(parsl): size executor to PBS allocation` — sizes the Parsl HighThroughputExecutor to the actual PBS allocation; multi-node uses `MpiRunLauncher` + `address_by_hostname()`; resolved the interchange-subprocess PATH issue. Plus a chore purging remaining Docker/containerization vestiges (venv-only flow).
- **Why it matters:** Confirms the division of labor — the real-Parsl base (Ivy) enabled the teammate to take it to genuine multi-node HPC scaling (eval paper).
- **→ report:** cite as the bridge to the companion evaluation paper.

### Phase 10 — Token tracking completed (branch `fix/token-tracking`, pushed)
- **What:** `_invoke_structured` now logs per-call token usage under the calling agent's name, so trace summaries / the waterfall reflect **orchestrator + planner + explorer**, not just explorer. (installer makes no LLM calls.)
- **Why:** A regression had left only the explorer instrumented, so per-agent cost was undercounted.
- **→ report:** §6 (cost observability). *Old traces predate this — re-run to get full per-agent token data.*
- **Superseded:** the team's `master` branch already had richer per-agent tracing ("bolstered eval tracing": schema-validated events, full LLM-call logging, skill-load logging). This `fix/token-tracking` branch is therefore redundant and was not merged.

### Phase 11 — Branch reality check (Jun 23–24)
- **What:** Discovered the team's integration branch is **`master`, not `main`** (main was stale by several commits). `master` carries the merged real-Parsl work, the `load_skill` tool, schema-validated tracing (`trace_schema.py`), image support, and the teammate's `fix(parsl): size executor to PBS allocation` (real multi-node sizing) and `pycompss confirmed working`. Re-based all new work onto `master`.
- **Why it matters:** confirms the division of labor in motion — the real-Parsl base (Ivy) enabled the teammate's HPC sizing + a confirmed PyCOMPSs run (eval paper). Going forward: always branch from and sync onto `master`.
- **→ report:** process/collaboration note; cite the companion eval paper.

### Phase 12 — Real ADIOS2 (branch `feat/real-adios`, PR #3)
- **What:** Made the ADIOS engine genuinely use ADIOS2 for inter-stage data transport. Two changes, **no server change**:
  1. `mcp_explorer.py` injects the `systems/<engine>` skill into the explorer prompt, scoped to I/O-library engines (`{"adios"}`); scheduler engines (parsl/pycompss) excluded.
  2. `skills/systems/adios.SKILL.md` rewritten from passive reference → MANDATORY directive: inter-stage data must move via adios2 BP files (producer writes, consumer reads), with a concrete template.
- **Why:** Root cause of "nominal ADIOS" was that the code-writing agent (explorer) never received the adios skill, so the server's `import adios2` was a dead import. Fixing it lives at the skill/agent layer — unlike Parsl (a scheduler fixed in the server), ADIOS2 is an I/O library the *task code* must call.
- **Status:** implementation + skill-injection verified locally; real-mode execution (emit `adios2.open` → produce `.bp`) needs adios2 installed → HPC verification (teammate, `module load adios2`).
- **How to confirm real (not fallback)** — check all three: (1) a `.bp` artifact exists in `work/run0/` — note it's a *directory* (`sim_output.bp/` containing `data.0`, `md.idx`, ...), not a flat file; (2) a `submit_task` `python_code` in the trace contains `adios2.open(...)`; (3) task results show `"engine": "adios2"`, not `"adios2-fallback"`. Only inter-stage data becomes `.bp`; final artifacts (`results.csv`, `renders/*.png`) stay normal files.
- **→ report:** §5 (engine-agnostic design — now ADIOS is a *real* third paradigm, not a stub), §4 (scheduler-vs-I/O-library design distinction), §9.

---

## Key design decisions (report §3–§4)
1. **Workflow-as-tool over workflow-as-artifact.** Interactive primitives (submit/monitor/fetch) instead of generating one big script: enables step-wise validation, failure isolation, and mid-run recovery. (Artifact approach built then abandoned — evidence in the other repo.)
2. **Agent/engine separation via MCP.** The agent layer has zero knowledge of the backend; engines (Parsl/PyCOMPSs/ADIOS2) sit behind one identical 10-tool interface. Switching is a `--engine` flag.
3. **Skill/prompt-driven behavior.** Per-engine and per-environment behavior comes from skill files injected into context, not hard-coded branches — demonstrated by adapting to HPC via skill edits alone.
4. **Single execution chokepoint (`_run_command`).** All tools funnel through one function — the reason real-Parsl could be added in one place, and the natural spot for instrumentation.
5. **Scheduler vs. I/O-library engines fix at different layers.** A *scheduler* (Parsl, PyCOMPSs) is made real in the **server** (route execution through the runtime), and the explorer must NOT see its API. An *I/O library* (ADIOS2) is made real at the **skill/agent layer** (the generated task code must call it), and the explorer MUST see its API. The `_IO_LIBRARY_ENGINES` gate encodes this distinction.

## Problems encountered & fixes (report §6 / §9 "lessons learned")
| Problem | Root cause | Fix |
|---|---|---|
| Tasks wrote to wrong/absolute paths | no path contract | `/app/` alias resolved at runtime + fixed `work/run0/` convention |
| LAMMPS bindings fail to load MPI libs | missing `LD_LIBRARY_PATH` | `setup_hpc.sh` + `TASK_ENV` inject Intel-MPI paths |
| Installer infinite loop | routing/approval logic | loop fix (Jun 17) |
| "parsl" engine didn't use Parsl | nominal naming, no `import parsl` | real DataFlowKernel integration |
| Parsl `parsl.load()` silently fell back | interchange resolved via PATH, not venv | prepend venv bin to PATH (teammate) |
| Generated script syntax error slipped through | wrapper is an f-string; `py_compile` can't see it | (recommended) `compile()` the wrapped script before running |
| Only explorer's tokens counted | instrumentation regression | per-agent token logging restored |
| OVITO/Qt render tasks fail | headless GUI/rendering | skip-after-N-retries; matplotlib fallback renders |

## Robustness & observability mechanisms (report §6)
- Per-task retry cap (≤3), per-tool timeout (1800s), MCP broken-pipe handling, explorer context-window trimming, engine fallback (Parsl→subprocess, COMPSs/ADIOS→plain/ numpy).
- `trace.json` event stream: agent start/end, routing decisions, tool calls (+success), token usage; powers timeline / routing / tool-success / waterfall figures.

## Open / future work (report §9)
- Async cross-task DAG for true task-level parallelism (currently blocks on `.result()`).
- Validate generated scripts (`compile()`) before execution.
- Reduce duplication across the three servers (shared base) — the same bug class can hide in all three.
- A test suite (unit + per-engine smoke) — would have caught the token regression and the f-string syntax bug.
- Per-run output dirs (avoid `work/run0/` clobbering).

## Narrative arc (drop-in paragraph for §9)
The system began (Jun 11) as a single design bet — expose the workflow engine as MCP tools
and let a ReAct explorer drive it — then generalized in stages: prompt/skill conventions for
reliable task generation (Jun 11–12), a second scheduler PyCOMPSs (Jun 15), local↔HPC
environment adaptation with MPI and a trace logger (Jun 16), a third, *different-paradigm*
backend ADIOS2 (Jun 18), and a real Parsl DataFlowKernel (Jun 19) — all behind an unchanged
agent layer, which let the teammate take it to multi-node HPC scaling. A parallel thread of
robustness fixes (timeouts, broken pipes, install loops, multi-rank LAMMPS, path contracts)
and an observability layer (trace logger, per-agent token reporting, waterfall) turned the
proof-of-concept into a usable, traceable framework.

## Report-section index
§3 Architecture: Phases 1,5(hygiene),7; decisions 2,4 ·
§4 Artifact-vs-tool: decision 1 (evidence in other repo) ·
§5 Engine-agnostic: Phases 3,4,6,7; decision 2 ·
§6 Robustness & traceability: Phases 2,4,5,8,10; problem table ·
§8 Proof-of-function: Phases 1,4 + existing `runs/*_trace.json` ·
§9 Lessons & future: problem table + open-work list + narrative arc.

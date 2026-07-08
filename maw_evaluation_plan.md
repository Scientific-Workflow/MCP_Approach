# MAW Evaluation Framework: Decisions and Rationale

This document is a handoff. Anyone (human or LLM) reading it should leave with full context on what we are building, what we decided, and why.

## 1. Vision

MAW is a multi-agent system that, given a scientific paper (PDF) and a one-sentence prompt, autonomously reproduces the simulation described in the paper end-to-end. It reads the paper, identifies and installs required software, generates workflow code targeting a specified framework (Parsl, PyCOMPSs, or ADIOS), executes the simulation, and produces a visualization.

The system is the research contribution. This evaluation does NOT propose a novel benchmarking framework. It produces a performance report showing that MAW's two major design choices, skill files (memory) and multi-agent decomposition (architecture), each contribute meaningfully to system performance.

The evaluation method is ablation. We compare three system variants on the same test papers and measure the cost of removing each design element.

## 2. The three conditions

### Condition A: MAW-no-skills

**Definition:** Full multi-agent architecture (orchestrator, planner, installer, explorer). All MCP tools available. System prompts contain role definitions, tool catalogs, task framing only. Skill files are removed; the skill-loading tool is either removed or returns empty.

**What it tests:** The contribution of the skill-file memory layer.

**Why:** If skill files do useful work, removing them should degrade performance. The agent retains the base LLM's training knowledge plus full tool access, so it is not starting from nothing. It is starting from "what an LLM with tools can do on its own." That is the right baseline against which to measure the skill files' contribution.

### Condition B: MAW-full (baseline being claimed)

**Definition:** The proposed system. Full architecture, all tools, skill files available via tool loading.

**Why:** This is the system we are claiming works. A and C are measured relative to it.

### Condition C: Single-agent

**Definition:** One agent doing the work of all four. All skill files available via tool loading. Union of MCP tools that the four agents previously had access to. System prompt written from scratch describing the consolidated role.

**What it tests:** The contribution of multi-agent decomposition, specifically via context-window isolation. With one agent, the context accumulates paper text + install logs + generated code + execution traces + skill file loads all in one window.

**Why:** The hypothesis is not "multi-agent is better in the abstract." The hypothesis is "context isolation prevents the degradation that occurs when one agent's context grows past some threshold." This is falsifiable; if C performs comparably to B, the multi-agent claim weakens, and we should know that before publishing.

### Shared controls across all three conditions

- Same LLM (model + specific version pinned)
- Same test papers
- Same per-agent iteration budgets where applicable
- Same execution environment (container, network access policy, filesystem starting state)
- Same input format (paper PDF + one-sentence prompt)

### Prompt parity rule

Conditions A and B share an identical system prompt scaffold. The only variable is whether the skill-loading tool returns content (B) or nothing (A). We do not subtly rewrite the prompt between conditions; that introduces noise unrelated to the ablation.

C has a different prompt because the architecture is different. Write it from scratch. Do not concatenate the four agent prompts. Do not include skill content in the prompt itself; skills come via tool loading in C just as in B.

**Why this matters:** The cleanest possible isolation of the variable. If the prompts differ in ways that do not follow necessarily from the ablation, the resulting performance differences are confounded.

## 3. Test cases

Three papers, one per domain, each in its native framework:

| Domain | Framework | Selection status |
|---|---|---|
| Molecular nucleation | Parsl | TBD |
| Cosmology | ADIOS | TBD |
| Protein folding | PyCOMPSs | TBD |

**Why this matrix:** Covers the diagonal of the 3-domain by 3-framework grid. With only three papers, going diagonal probes both axes weakly rather than fully populating one axis. The framework-domain pairings reflect what published code in each domain typically uses (cosmology has heavy ADIOS adoption due to I/O scale; molecular dynamics tends toward simpler Python orchestration like Parsl).

### Inclusion criteria for test papers

- Published 2023 or later (older code rots)
- Publicly available code (GitHub, Zenodo, or supplementary materials)
- Code passes a reproducibility gate: we can run it end-to-end ourselves and reproduce the paper's reported observables before the paper enters the test set
- Held out: never used during MAW development or skill-file iteration

**Why the reproducibility gate:** If we cannot reproduce the paper ourselves, we have no trustworthy ground truth, and evaluating MAW against it is meaningless. Expect roughly 50% rejection rate from this gate; plan to screen 2-3 times the number of candidates per slot.

## 4. Metrics

### Three-tier success

**Tier 1: Did it run end-to-end?**
Binary. Captures crashes, timeouts, hung loops, and any pipeline that failed to produce final outputs.

**Tier 2: Did it use the right configuration data? (Primary scientific-correctness signal)**
For each paper, we extract a configuration spec from the methods section: simulation parameters, force fields, box sizes, timesteps, ensembles, key numerical tolerances. MAW's generated workflow.py is diffed against this spec, parameter by parameter. Score is the match rate.

**Why tier 2 is primary:** It directly measures "did the system extract and apply the right knowledge from the paper" without the noise of statistical output variation or implementation correctness. For an ablation that aims to compare knowledge access across conditions, this is exactly what we want to measure. It is also cheap (a text diff) and deterministic (no LLM judge bias).

**Tier 3: Did it produce outputs within tolerance? (Supplemental)**
Only computed for runs that pass tier 1. Compares MAW's simulation observables to the author's reference outputs within published domain tolerances.

**Why tier 3 is supplemental:** Re-running reference code can be expensive (cosmology), require hardware we do not have, or be impractical at the eval scale of 27 runs. Tier 2 is the primary signal; tier 3 is bonus where feasible. For papers where tier 3 is not feasible, we skip it cleanly and report only tier 1 and 2.

### Supplementary metrics (logged every run)

**Iterations per agent.** Count of LLM re-invocations within each agent's sub-task. Captures whether agents are converging quickly or thrashing.

**Issue-to-resolution iterations.** For each error encountered during a run, count iterations from error to next successful step. Reveals recovery cost. An issue is any tool call failure or LLM output that triggered correction.

**Token usage per agent.** Input + output tokens. Source: LLM API metadata, native to every call.

**Wall-clock time per agent and end-to-end.** Source: trace timestamps.

**Failure stage breakdown.** For failed runs, categorical assignment: paper reading, install, code generation, execution, or outcome. Tells us which ablation introduces which kind of brittleness.

**Orchestrator replans.** Count of times the orchestrator revised its decomposition. Multi-agent specific; not applicable to condition C, reported as N/A there.

**Why we do not measure cost:** Runs happen on local infrastructure; dollar cost is not a meaningful metric here. Wall-clock time captures the relevant compute-time signal.

### What we are NOT measuring in phase 1

- Skill consultation precision/recall (deferred to phase 2)
- LLM-as-judge fidelity of skill application (phase 2)
- Code structural diff vs author's reference (phase 2)
- Visualization quality beyond "was a viz produced" (phase 2)

## 5. Run protocol

**End State Total: 27 runs.** 3 papers × 3 conditions × 3 trials.

**For Now to keep it simple Total: 3 runs.** 3 papers each with a different condition associated to a specific use case. = 3 trials.

**Three trials per (paper, condition):** LLMs are non-deterministic. One run is anecdotal; three lets us report mean and standard deviation per condition and reveals run-to-run variance.

**Scripted, no manual intervention.** All runs launched by a driver script that reads (paper, condition, trial) triples and dispatches. No mid-run human interaction.

**Failed runs are still recorded** with full diagnostic data, not silently dropped.

### Edge cases (decided before runs start)

**Timeout policy:** Per-pipeline wall-clock cap (TBD specific number, set during instrumentation). A run exceeding the cap is marked tier-1 fail with all collected data preserved.

**Iteration budget:**
- Explorer: 100 LLM calls (tentative; reflects the explorer's heavier workload of code generation, simulation execution, visualization, and output handling)
- Planner, Installer, Orchestrator: smaller per-agent caps to be set during instrumentation based on observed needs
- Per-pipeline total cap as a runaway-cost guard

**Partial output handling:**
- Generation completes but execution fails: tier-1 fail, diagnostic data preserved
- Execution completes but produces empty or garbage outputs: tier-1 pass, tier-2 and tier-3 failures recorded
- All-or-nothing scoring is too coarse; the breakdown reveals failure character

**Hung loops:** Detected via the iteration cap. No separate stuck-state detection in v1.

## 6. Tracing infrastructure

**Built first, before forking the codebase into three condition variants.** Debugging three codebases without tracing is unworkable. This is a strict ordering: tracing first, then variants.

**Approach:** LangSmith plus a structured per-run JSONL dump. LangSmith for ergonomic debugging during development. JSONL dump for offline analysis independence (we cannot be locked into LangSmith's API at report time).

### Captured per run

- Every LLM call: model + version, timestamp, input tokens, output tokens, latency, full prompt and response (the full content is needed for debugging failed runs later)
- Every tool call: tool name, input arguments, return value, success/failure flag
- Every skill file load: file name, requesting agent, timestamp
- Every state transition (LangGraph edges): from-node, to-node, payload size
- Run-level metadata: condition (A/B/C), paper ID, model version, random seed (if any), start/end timestamps, final status, the paper's configuration spec (tier-2 ground truth) for the run

### Implementation note

Bundle all logged fields into a Pydantic schema before writing logging code. Inconsistent schema across runs is the most painful retroactive fix. Define it once, then write loggers against the schema.

## 7. Ground truth construction

Ground truth is the author's reference, not a "perfect MAW run." A perfect MAW run as ground truth would be circular (we would be evaluating MAW against itself).

### Per test paper, the GT artifact contains

- Configuration spec extracted from the paper's methods section (for tier 2)
- Image of Author simulation/visualization run 


**Authored before MAW runs on these papers.** Held-out test methodology. No iteration on the GT based on observed MAW behavior. The discipline is strict because GT iteration would turn this into eval-on-training.

**Labor estimate per paper:**
- Configuration extraction: 30-60 minutes
- Reference code validation (reproducing the paper's outputs): variable, often several hours
- Plan accordingly when scheduling.

## 8. Predicted failure modes per condition

These predictions are stated up front so the analysis can confirm or refute them rather than rationalize whatever emerges.

**Condition A (no skills):**
- Domain-specific configuration errors (used wrong defaults, missed paper-specific overrides)
- Dependency resolution failures the skill files would have flagged
- Framework API misuse on edge cases not in LLM training data
- Higher tier-2 failure rate; tier-1 pass rate may stay reasonable since basic execution is well-known to base LLMs

**Condition B (full MAW):**
- Rare failures, ideally only on edge cases not yet covered by current skill files
- The bar against which A and C are measured

**Condition C (single-agent):**
- Context degradation in long-running tasks (more accumulated context per LLM call)
- Confusion between sub-tasks (state tracking failures)
- Skill loading still works, so failure mode is reasoning quality rather than knowledge access
- Predicted pattern: comparable to B on short tasks, worse on long tasks; this is the falsifiable prediction

If the predicted patterns hold, the ablation supports the design. If they do not hold, that is also a finding worth reporting. We report the data either way, not just the data that supports the design.

## 9. Scope and explicit non-claims

### We are claiming

- MAW works on at least three papers across three domains
- Skill files contribute measurably to performance (vs condition A)
- Multi-agent decomposition contributes measurably via context isolation (vs condition C)

### We are NOT claiming

- Generalization to arbitrary scientific computing
- Generalization beyond the three tested frameworks
- That MAW outperforms any external system (we ran no external comparisons; see below)
- That the skill files are optimal; only that they help
- That the multi-agent decomposition is optimal; only that decomposition helps
- Anything about cost-efficiency (cost not measured)

### No external baselines

The evaluation is ablations-only, intentionally. We do not compare MAW against external systems (SWE-agent, Agentless, etc.) because no directly comparable system exists for scientific workflow reproduction from papers. The ablation isolates MAW's design choices; external comparison would require building or adapting a baseline system, which is out of scope for this evaluation.

This is a stated choice, not an oversight. Reviewers asking "why no comparison to X" get the above answer: X does not solve the same problem.

## 10. Reporting structure

**Headline table:** condition by metric. Mean and standard deviation across the 9 runs per condition.

| Condition | Tier 1 pass rate | Tier 2 mean | Tier 3 pass rate | Mean iterations | Mean tokens | Mean wall-clock |
|---|---|---|---|---|---|---|
| MAW-no-skills | | | | | | |
| MAW-full | | | | | | |
| Single-agent | | | | | | |

**Per-paper breakdown:** Same metrics broken out by paper. Reveals whether ablation effects are uniform across domains or domain-specific.

**Failure mode breakdown:** Stacked bar chart, failure stages by condition. Reveals what kind of brittleness each ablation introduces.

**Iteration profile:** Mean iterations per agent per condition. Reveals where ablation effects concentrate (does no-skills thrash in the installer? does single-agent thrash everywhere?).

### Statistical reporting approach

Descriptive statistics: mean, standard deviation, min, max. With 9 runs per condition we do not have power for significance testing; descriptive numbers are the honest report. If patterns are strong they will be visible in mean and standard deviation. If patterns are marginal, we report that honestly rather than hunting for a significance threshold.

## 11. Phase 2 outlook

Phase 2 is behavioral analysis, conducted AFTER phase 1 produces its headline numbers. Same paper, later section, not a separate publication.

Phase 2 answers HOW skill files and multi-agent decomposition help, given that phase 1 shows THAT they help:

- Trajectory contracts per (paper, agent), with required/forbidden/neutral buckets
- LLM-as-judge for skill application fidelity (did the agent's actions actually reflect the skill content)
- Code structural diff (explorer's workflow.py vs author's reference)
- Visualization qualitative judge

Phase 2 reuses the same 27 traces produced in phase 1. No additional runs required for the bulk of it; just additional analysis layered on the same data. This is why tracing must capture everything in phase 1.

## 12. Reproducibility commitments

To strengthen the eval and pre-empt reviewer concerns, the following should be released publicly alongside the paper:

- List of test papers (DOIs)
- Per-paper GT artifacts (config specs, observables, tolerances)
- All system prompts for all three conditions
- The MAW codebase at the eval-time commit
- All 27 run traces
- The driver script that ran the 27 trials

Reproducibility commitments cost nothing extra when committed early. They are painful to retrofit.

## 13. Open items requiring decision

These items are not blocking the next steps (tracing, GT construction) but must be pinned before runs start.

- Specific test papers per domain (selection pending)
- Specific LLM identity and version (deferred for now, must be pinned before runs)
- Iteration budgets for orchestrator, planner, installer (set during instrumentation based on observed needs)
- Wall-clock timeout per pipeline run
- Exact tier-3 tolerance values per domain (look up published reproducibility studies for each)
- Single-agent system prompt (write from scratch before runs, do not derive from concatenation)

"""
Regenerate trace figures for the SLIDES_OUTLINE, pinned to the
quadratic-gravity ADIOS run (runs/20260626_215336_trace.json).

Reuses the plotting logic from demo_workflow.ipynb (timeline / routing /
tool-call summary / waterfall) and adds an iteration_breakdown chart.

Outputs go to slides_figs/ so the old root-level PNGs are not overwritten.
"""
import os, json
from collections import Counter
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

TRACE = "runs/20260626_215336_trace.json"
OUT = "slides_figs"
os.makedirs(OUT, exist_ok=True)

with open(TRACE) as f:
    trace_data = json.load(f)
events = trace_data["trace"]
summary = trace_data["summary"]

agent_colors = {
    "orchestrator": "#4A90D9",
    "planner": "#50C878",
    "installer": "#FFB347",
    "explorer": "#FF6B6B",
}

print(f"Loaded {TRACE}")
print(f"  routing: {' -> '.join(summary['routing_path'])}")
print(f"  tool calls: {summary['tool_calls']} ({summary['tool_successes']} ok)")
print(f"  duration: {summary['total_duration_s']}s")

# ---------- 1. Agent timeline ----------
timeline = []
for e in events:
    if e["type"] == "agent_start":
        timeline.append({"agent": e["agent"], "start": e["elapsed_s"], "end": None})
    elif e["type"] == "agent_end":
        for t in reversed(timeline):
            if t["agent"] == e["agent"] and t["end"] is None:
                t["end"] = e["elapsed_s"]; break
max_time = max(e["elapsed_s"] for e in events)
for t in timeline:
    if t["end"] is None: t["end"] = max_time

fig, ax = plt.subplots(figsize=(14, 4))
agents_list = list(agent_colors.keys())
for t in timeline:
    if t["agent"] in agents_list:
        y = agents_list.index(t["agent"])
        ax.barh(y, t["end"] - t["start"], left=t["start"],
                color=agent_colors[t["agent"]], alpha=0.85, height=0.6)
ax.set_yticks(range(len(agents_list))); ax.set_yticklabels(agents_list, fontsize=12)
ax.set_xlabel("Time (seconds)", fontsize=12)
ax.set_title("Agent Execution Timeline — Quadratic Gravity (ADIOS)", fontsize=14)
ax.grid(axis="x", alpha=0.3); plt.tight_layout()
plt.savefig(f"{OUT}/agent_timeline.png", dpi=150, bbox_inches="tight"); plt.close()
print("  saved agent_timeline.png")

# ---------- 2. Routing path ----------
routings = [e for e in events if e["type"] == "routing"]
fig, ax = plt.subplots(figsize=(12, 3))
ax.set_xlim(-0.5, len(routings) + 0.5); ax.set_ylim(-1, 1); ax.axis("off")
ax.set_title(f"Orchestrator Routing Path ({len(routings)} decisions)", fontsize=14, pad=20)
for i, r in enumerate(routings):
    color = agent_colors.get(r["to"], "#888888")
    ax.add_patch(plt.Circle((i, 0), 0.3, color=color, alpha=0.85))
    ax.text(i, 0, r["to"][:4], ha="center", va="center", fontsize=8, fontweight="bold", color="white")
    ax.text(i, -0.6, r["to"], ha="center", va="top", fontsize=9)
    ax.text(i, 0.5, f"{r['elapsed_s']:.0f}s", ha="center", fontsize=8, color="gray")
    if i < len(routings) - 1:
        ax.annotate("", xy=(i + 0.65, 0), xytext=(i + 0.35, 0),
                    arrowprops=dict(arrowstyle="->", color="#333", lw=1.5))
i = len(routings)
ax.add_patch(plt.Circle((i, 0), 0.3, color="#666", alpha=0.85))
ax.text(i, 0, "END", ha="center", va="center", fontsize=8, fontweight="bold", color="white")
if routings:
    ax.annotate("", xy=(i - 0.35, 0), xytext=(i - 0.65, 0),
                arrowprops=dict(arrowstyle="->", color="#333", lw=1.5))
plt.tight_layout(); plt.savefig(f"{OUT}/routing_path.png", dpi=150, bbox_inches="tight"); plt.close()
print("  saved routing_path.png")

# ---------- 3. Tool-call summary ----------
tool_calls = [e for e in events if e["type"] == "tool_call"]
tool_counts = Counter(tc["tool"] for tc in tool_calls)
tool_success = Counter(tc["tool"] for tc in tool_calls if tc.get("succeeded"))
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
tools = sorted(tool_counts.keys())
counts = [tool_counts[t] for t in tools]
successes = [tool_success.get(t, 0) for t in tools]
x = range(len(tools))
ax1.bar(x, counts, color="#4A90D9", alpha=0.7, label="Total")
ax1.bar(x, successes, color="#50C878", alpha=0.7, label="Succeeded")
ax1.set_xticks(x); ax1.set_xticklabels(tools, rotation=45, ha="right", fontsize=9)
ax1.set_ylabel("Count"); ax1.set_title("Tool Calls by Type"); ax1.legend()
total_success = sum(1 for tc in tool_calls if tc.get("succeeded"))
total_fail = len(tool_calls) - total_success
ax2.pie([total_success, total_fail], labels=["Succeeded", "Failed"],
        colors=["#50C878", "#FF6B6B"], autopct="%1.0f%%", startangle=90,
        textprops={"fontsize": 12})
ax2.set_title(f"Tool Call Success Rate ({total_success}/{len(tool_calls)})")
plt.tight_layout(); plt.savefig(f"{OUT}/tool_calls_summary.png", dpi=150, bbox_inches="tight"); plt.close()
print("  saved tool_calls_summary.png")

# ---------- 4. Workflow waterfall ----------
tokens_by_agent = summary.get("tokens_by_agent", {})
spans = []
open_starts = {}; explorer_start = None
for e in events:
    t = e.get("elapsed_s", 0)
    if e["type"] == "agent_start":
        open_starts.setdefault(e["agent"], []).append(t)
        if e["agent"] == "explorer" and explorer_start is None: explorer_start = t
    elif e["type"] == "agent_end":
        stack = open_starts.get(e["agent"], [])
        start = stack.pop(0) if stack else t
        tok = tokens_by_agent.get(e["agent"])
        label = e["agent"] + (f"  [{tok:,} tok]" if tok else "")
        spans.append({"label": label, "start": start, "end": t,
                      "color": agent_colors.get(e["agent"], "#888888"), "kind": "agent"})
prev_t = explorer_start
for e in events:
    if e["type"] != "tool_call": continue
    t = e.get("elapsed_s", 0); dur = e.get("duration_s", 0)
    start = (t - dur) if dur and dur > 0 else (prev_t if prev_t is not None else t)
    spans.append({"label": "  └ " + e["tool"], "start": start, "end": t,
                  "color": "#2E8B57" if e.get("succeeded") else "#C0392B", "kind": "tool"})
    prev_t = t
spans.sort(key=lambda s: (s["start"], s["kind"] != "agent"))
fig, ax = plt.subplots(figsize=(14, max(4, 0.42 * len(spans))))
total = max((s["end"] for s in spans), default=1)
for i, s in enumerate(spans):
    width = max(s["end"] - s["start"], total * 0.004)
    ax.barh(i, width, left=s["start"], color=s["color"], alpha=0.85, height=0.62,
            edgecolor="black" if s["kind"] == "agent" else "none",
            linewidth=0.8 if s["kind"] == "agent" else 0)
    ax.text(s["end"] + total * 0.005, i,
            f'{s["label"]} ({s["end"] - s["start"]:.1f}s)', va="center", fontsize=8)
ax.set_yticks([]); ax.invert_yaxis(); ax.set_xlim(0, total * 1.28)
ax.set_xlabel("Elapsed time (s)", fontsize=12)
ax.set_title("Workflow Waterfall — agents (outlined) + tool calls (indented)\n"
             "green = tool succeeded, red = tool failed", fontsize=13)
ax.grid(axis="x", alpha=0.3); plt.tight_layout()
plt.savefig(f"{OUT}/workflow_waterfall.png", dpi=150, bbox_inches="tight"); plt.close()
print("  saved workflow_waterfall.png")

# ---------- 5. Iteration breakdown (per explorer round) ----------
# Split tool calls into rounds: a new round starts whenever iteration resets to 1.
rounds = []
cur = []
last_iter = 0
for e in tool_calls:
    it = e.get("iteration", 0)
    if it == 1 and last_iter != 0 and last_iter >= 1 and cur and last_iter > 1:
        rounds.append(cur); cur = []
    cur.append(e); last_iter = it
if cur: rounds.append(cur)
# max iteration reached per round
round_iters = [max((e.get("iteration", 0) for e in r), default=0) for r in rounds]
round_calls = [len(r) for r in rounds]
round_ok = [sum(1 for e in r if e.get("succeeded")) for r in rounds]
labels = [f"Explorer\nround {i+1}" for i in range(len(rounds))]
fig, ax = plt.subplots(figsize=(8, 5))
x = range(len(rounds))
ax.bar(x, round_iters, width=0.5, color="#FF6B6B", alpha=0.85, label="iterations")
for i, (it, c, ok) in enumerate(zip(round_iters, round_calls, round_ok)):
    ax.text(i, it + 0.5, f"{it} iters\n{ok}/{c} tools ok", ha="center", fontsize=10)
ax.set_xticks(list(x)); ax.set_xticklabels(labels, fontsize=11)
ax.set_ylabel("ReAct iterations")
ax.set_title("Explorer Iteration Breakdown (ReAct rounds)")
ax.set_ylim(0, max(round_iters) * 1.25 if round_iters else 1)
plt.tight_layout(); plt.savefig(f"{OUT}/iteration_breakdown.png", dpi=150, bbox_inches="tight"); plt.close()
print(f"  saved iteration_breakdown.png  (rounds={round_iters}, calls={round_calls}, ok={round_ok})")

print("\nAll figures written to", OUT + "/")

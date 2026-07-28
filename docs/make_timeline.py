"""Render the development-timeline figure used in the README (docs/timeline.png).

The phases below were derived from the real commit history. To update the figure after
new development:
  1. Add/extend an entry in PHASES (label, start-date, end-date, color) and, optionally,
     a milestone in MILES.
  2. Run:  python docs/make_timeline.py
  3. Commit the regenerated docs/timeline.png.

To re-derive the raw commit dates:  git log --reverse --format='%ad  %s' --date=short

Requires: matplotlib.  Output is written next to this script, so it works from any cwd.
"""
import os
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# (label, start, end, color) -- single-day phases get a small min width for visibility.
PHASES = [
    ("P1  Foundation: MCP-as-Tool",      date(2026, 6, 11), date(2026, 6, 12), "#6C5CE7"),
    ("P2  2nd engine + infrastructure",  date(2026, 6, 12), date(2026, 6, 17), "#0984E3"),
    ("P3  3rd engine: ADIOS2",           date(2026, 6, 18), date(2026, 6, 19), "#00B894"),
    ("P4  Making the engines real",      date(2026, 6, 19), date(2026, 6, 22), "#E1A100"),
    ("P5  Confirmation + ablation",      date(2026, 6, 22), date(2026, 6, 25), "#E17055"),
    ("P6  HPC full 3x3 matrix testing",  date(2026, 6, 29), date(2026, 7, 13), "#8E44AD"),
    ("P7  Clarifier + clean archiving",  date(2026, 7, 20), date(2026, 7, 21), "#D63384"),
]
# (date, text) key milestones plotted along a baseline under the bars.
MILES = [
    (date(2026, 6, 11), "MCP-as-tool idea"),
    (date(2026, 6, 15), "PyCOMPSs (2nd engine)"),
    (date(2026, 6, 18), "ADIOS2 (3rd engine)"),
    (date(2026, 6, 19), "real Parsl DataFlowKernel"),
    (date(2026, 6, 25), "no-skills ablation"),
    (date(2026, 7, 13), "3x3 matrix complete on HPC"),
    (date(2026, 7, 21), "clarifier + archiving"),
]

# X-axis window (a little padding on each side of the phase range).
X_START, X_END = date(2026, 6, 8), date(2026, 7, 24)
TITLE = "MAW (MCP Approach) — development timeline, SULI 2026 (7 phases, 40 commits)"


def main():
    fig, ax = plt.subplots(figsize=(12, 5.6))
    for i, (label, s, e, c) in enumerate(PHASES):
        y = len(PHASES) - i
        ax.barh(y, mdates.date2num(e) - mdates.date2num(s), left=mdates.date2num(s),
                height=0.55, color=c, edgecolor="white", linewidth=1, zorder=3)
        ax.text(mdates.date2num(s) - 0.6, y, label, ha="right", va="center",
                fontsize=9.5, fontweight="bold", color="#222", zorder=4)

    base_y = 0.35
    for d, txt in MILES:
        x = mdates.date2num(d)
        ax.plot(x, base_y, "o", color="#444", markersize=5, zorder=5)
        ax.annotate(txt, (x, base_y), xytext=(0, -12), textcoords="offset points",
                    ha="center", va="top", fontsize=7.3, color="#555", rotation=25, zorder=5)

    ax.set_ylim(-1.6, len(PHASES) + 0.8)
    ax.set_yticks([])
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.set_xlim(mdates.date2num(X_START), mdates.date2num(X_END))
    ax.grid(axis="x", linestyle=":", alpha=0.5, zorder=0)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.set_title(TITLE, fontsize=12.5, fontweight="bold", pad=12)

    plt.tight_layout()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "timeline.png")
    plt.savefig(out, dpi=200, bbox_inches="tight", facecolor="white")
    print("written:", out)


if __name__ == "__main__":
    main()

"""Figures from the reconciled development rerun; no inference or score changes."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "studies/execution-contract-v2/results.json"
ASSETS = ROOT / "agent-lens-in-practice/assets"
LABELS = {"default-committee": "Luna/Sol\ncommittee", "luna-committee": "All-Luna\ncommittee", "single-luna": "Single Luna\nanalyst"}
COLORS = {"original": "#8c9799", "corrected": "#226d86"}
BG, INK = "#fcfaf6", "#172633"


def style(ax):
    ax.set_facecolor(BG)
    ax.tick_params(length=0, pad=8, labelcolor=INK)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_axisbelow(True)


def build():
    data = json.loads(SOURCE.read_text())
    rows = data["summaries"]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 12, "svg.fonttype": "none"})
    fig, ax = plt.subplots(figsize=(5.4, 6.0), dpi=180)
    fig.patch.set_facecolor(BG)
    fig.subplots_adjust(left=.29, right=.97, bottom=.30, top=.72)
    fig.text(.035, .96, "What changed after the fix?", va="top", fontsize=17, weight="bold", color=INK)
    fig.text(.035, .89, "Mean five-session trading P&L\nFresh $100,000 accounts · fees included", va="top", fontsize=12, color=INK)
    all_values = []
    for i, row in enumerate(rows):
        values = [row[v]["mean_trading_pnl"] for v in ("original", "corrected")]
        all_values += values
        ax.plot(values, [i, i], color="#c0c7c6", zorder=1)
        for version, offset, marker in (("original", -.18, "o"), ("corrected", .18, "D")):
            value = row[version]["mean_trading_pnl"]
            ax.scatter(value, i, marker=marker, s=50, color=COLORS[version], label=version if i == 0 else None, zorder=3)
            ax.annotate(f"${value:,.2f}", (value, i + offset), ha="center", va="center", fontsize=11, color=COLORS[version])
    pad = max(max(all_values) - min(all_values), 100) * .3
    ax.set_xlim(min(0, min(all_values)) - pad, max(0, max(all_values)) + pad)
    ax.set_ylim(2.5, -.5)
    ax.set_yticks(range(3), [LABELS[r["treatment"]] for r in rows])
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.locator_params(axis="x", nbins=4)
    ax.axvline(0, color="#a8b2b2", linewidth=.7)
    ax.grid(axis="x", color="#dce0de", linewidth=.6)
    style(ax)
    fig.legend(*ax.get_legend_handles_labels(), loc="center", bbox_to_anchor=(.58, .19), ncol=2, frameon=False, fontsize=11)
    fig.text(.035, .045, "8 dates · 2 trials/date · 10 bps/side\nExposure differs. Model expense excluded.\nSame inspected cases; a development rerun.", color="#46535d", fontsize=11, linespacing=1.4)
    save(fig, "corrected-portfolio-pnl")

    fig, ax = plt.subplots(figsize=(5.4, 6.0), dpi=180)
    fig.patch.set_facecolor(BG)
    fig.subplots_adjust(left=.29, right=.96, bottom=.31, top=.73)
    fig.text(.035, .96, "Did it authorize a trade?", va="top", fontsize=17, weight="bold", color=INK)
    fig.text(.035, .89, "Explicit orders in the corrected executions\n120 runs per treatment, including pending", va="top", fontsize=12, color=INK)
    styles = [("accepted", "Accepted", "#226d86", ""), ("abstained", "Chose cash", "#c0b598", "//"),
              ("blocked_condition", "Condition blocked", "#a9654b", "xx"), ("invalid_contract", "Invalid contract", "#805775", ".."),
              ("actor_failed", "Actor failed", "#4a4a4a", "++")]
    for i, row in enumerate(rows):
        start = 0
        for key, label, color, hatch in styles:
            count = row["contract_counts"].get(key, 0)
            if count:
                ax.barh(i, count, left=start, color=color, hatch=hatch, edgecolor=BG, height=.5,
                        label=label if i == next(j for j,r in enumerate(rows) if r["contract_counts"].get(key,0)) else None)
                ax.text(start + count/2, i, str(count), ha="center", va="center", fontsize=12,
                        color="white" if key != "abstained" else INK, weight="bold")
            start += count
        assert start == row["requested"]
    ax.set_yticks(range(3), [LABELS[r["treatment"]] for r in rows])
    ax.set_ylim(2.5, -.5)
    ax.set_xlim(0, max(r["requested"] for r in rows))
    ax.set_xticks([0, 30, 60, 90, 120])
    style(ax)
    fig.legend(*ax.get_legend_handles_labels(), loc="center", bbox_to_anchor=(.58, .19), frameon=False, ncol=2, fontsize=11)
    fig.text(.035, .045, "Accepted means the typed contract passed.\nIt does not validate the reasoning or forecast.\nCash decisions still incur model charges.", color="#46535d", fontsize=11, linespacing=1.4)
    save(fig, "corrected-execution-status")
    exports = [{"treatment": r["treatment"], "version": v,
                "mean_trading_pnl": r[v]["mean_trading_pnl"], "mean_exposure": r[v]["mean_exposure"],
                "matured_accounts": r[v]["matured_accounts"], "independent_dates": r[v]["independent_dates"]}
               for r in rows for v in ("original", "corrected")]
    with (ASSETS / "corrected-portfolio-pnl.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(exports[0]))
        writer.writeheader()
        writer.writerows(exports)
    (ROOT.parent / "studies/execution-contract-v2/figure-provenance.json").write_text(json.dumps({
        "source": "results.json", "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "figures": ["corrected-portfolio-pnl", "corrected-execution-status"],
        "interpretation_limit": "Development rerun, not an untouched test. Means are descriptive; trial and cohort uncertainty is in summaries.json. Typed acceptance is not semantic validation."
    }, indent=2) + "\n")


def save(fig, name):
    for suffix in ("png", "svg"):
        fig.savefig(ASSETS / f"{name}.{suffix}", facecolor=BG)
    plt.close(fig)


if __name__ == "__main__":
    build()

"""Draw the saved common-evidence comparison; no inference or rescoring."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "studies/common-evidence-v3-repaired"
ASSETS = ROOT / "articles/agent-lens-in-practice/assets"
BG, INK = "#fcfaf6", "#172633"
LABELS = {
    "default-committee": "Luna/Sol",
    "luna-committee": "All-Luna",
    "single-luna": "Single Luna",
}
ARMS = {"shared-evidence": "Shared brief", "cited-evidence": "Citations required"}


def style(ax):
    ax.set_facecolor(BG)
    ax.tick_params(length=0, pad=7, labelcolor=INK)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(axis="x", color="#dce0de", linewidth=0.6)
    ax.set_axisbelow(True)


def save(fig, name):
    for suffix in ("png", "svg"):
        fig.savefig(ASSETS / (name + "." + suffix), facecolor=BG)
    plt.close(fig)


def build():
    data = json.loads((PUBLIC / "results.json").read_text())
    rows = sorted(
        data["summaries"],
        key=lambda r: (list(LABELS).index(r["treatment"]), r["arm"] == "cited-evidence"),
    )
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "svg.fonttype": "none"})
    fig, ax = plt.subplots(figsize=(5.8, 7.1), dpi=180)
    fig.patch.set_facecolor(BG)
    fig.subplots_adjust(left=0.30, right=0.96, bottom=0.23, top=0.77)
    fig.text(
        0.035, 0.96, "Did stock selection help?", va="top", fontsize=18, weight="bold", color=INK
    )
    fig.text(
        0.035,
        0.90,
        "Same allocation, entry date and trading fees.\nOnly the purchased asset changes.",
        va="top",
        fontsize=12,
        color=INK,
    )
    values = []
    for i, row in enumerate(rows):
        stock, spy = row["mean_trading_pnl"], row["mean_matched_SPY_pnl"]
        values.extend((stock, spy))
        ax.plot([stock, spy], [i, i], color="#b7c2c4", zorder=1)
        for value, marker, color, label, offset in (
            (stock, "o", "#226d86", "Agent stock", -0.17),
            (spy, "D", "#aa7044", "Same-weight SPY", 0.17),
        ):
            ax.scatter(
                value,
                i,
                s=40,
                marker=marker,
                color=color,
                label=label if i == 0 else None,
                zorder=3,
            )
            ax.annotate(
                f"${value:,.0f}",
                (value, i + offset),
                ha="center",
                va="center",
                fontsize=10,
                color=color,
            )
    low, high = min(values + [0]), max(values + [0])
    span = max(high - low, 100)
    ax.set_xlim(low - 0.22 * span, high + 0.22 * span)
    ax.set_ylim(len(rows) - 0.5, -0.6)
    ax.set_yticks(range(len(rows)), [LABELS[r["treatment"]] + "\n" + ARMS[r["arm"]] for r in rows])
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.locator_params(axis="x", nbins=4)
    ax.axvline(0, color="#a8b2b2", linewidth=0.7)
    style(ax)
    fig.legend(
        *ax.get_legend_handles_labels(),
        loc="center",
        bbox_to_anchor=(0.55, 0.16),
        frameon=False,
        ncol=2,
        fontsize=10,
    )
    fig.text(
        0.035,
        0.035,
        "Mean P&L per fresh $100,000 account · 8 dates\n10 bps/side · model expense separate\nMatching capital does not match beta or volatility.",
        fontsize=10.5,
        color="#46535d",
        linespacing=1.4,
    )
    save(fig, "evidence-stock-selection")

    fig, ax = plt.subplots(figsize=(5.8, 6.5), dpi=180)
    fig.patch.set_facecolor(BG)
    fig.subplots_adjust(left=0.30, right=0.96, bottom=0.25, top=0.75)
    fig.text(
        0.035,
        0.96,
        "What passed the decision gate?",
        va="top",
        fontsize=17,
        weight="bold",
        color=INK,
    )
    fig.text(
        0.035,
        0.89,
        "Every requested execution, including pending\nmarket outcomes. Actor failures stay separate.",
        va="top",
        fontsize=11.5,
        color=INK,
    )
    styles = [
        ("accepted", "Accepted", "#226d86", ""),
        ("abstained", "Explicit abstentions", "#c0b598", "//"),
        ("invalid_citations", "Citation rejected", "#a9654b", "xx"),
        ("invalid_contract", "Contract rejected", "#805775", ".."),
        ("blocked_condition", "Condition blocked", "#8d6791", "\\"),
        ("actor_failed", "Actor failed", "#434c53", "++"),
    ]
    seen = set()
    for i, row in enumerate(rows):
        start = 0
        for key, label, color, hatch in styles:
            count = row["contract_counts"].get(key, 0)
            if count:
                ax.barh(
                    i,
                    count,
                    left=start,
                    height=0.60,
                    color=color,
                    hatch=hatch,
                    edgecolor=BG,
                    label=label if key not in seen else None,
                )
                seen.add(key)
                ax.text(
                    start + count / 2,
                    i,
                    str(count),
                    ha="center",
                    va="center",
                    fontsize=10,
                    color=INK if key == "abstained" else "white",
                    weight="bold",
                )
            start += count
        assert start == row["requested"]
    ax.set_xlim(0, max(r["requested"] for r in rows))
    ax.set_ylim(len(rows) - 0.5, -0.6)
    ax.set_yticks(range(len(rows)), [LABELS[r["treatment"]] + "\n" + ARMS[r["arm"]] for r in rows])
    style(ax)
    fig.legend(
        *ax.get_legend_handles_labels(),
        loc="center",
        bbox_to_anchor=(0.56, 0.15),
        frameon=False,
        ncol=2,
        fontsize=10,
    )
    fig.text(
        0.035,
        0.035,
        "60 decisions per arm/system · 1 trial each\nExact citations validate copied observations.\nThey do not certify the investment explanation.",
        fontsize=10.5,
        color="#46535d",
        linespacing=1.4,
    )
    save(fig, "evidence-contract-status")

    fig, ax = plt.subplots(figsize=(5.8, 5.6), dpi=180)
    fig.patch.set_facecolor(BG)
    fig.subplots_adjust(left=0.26, right=0.96, bottom=0.28, top=0.73)
    fig.text(
        0.035,
        0.96,
        "Did the citation requirement\nchange selection P&L?",
        va="top",
        fontsize=17,
        weight="bold",
        color=INK,
    )
    fig.text(0.035, 0.84, "Required citations minus shared brief", va="top", fontsize=12, color=INK)
    for i, t in enumerate(LABELS):
        p = data["paired_comparisons"][t]["selection_pnl"]
        lo, hi = p["interval"]
        ax.plot([lo, hi], [i, i], color="#226d86", linewidth=2)
        ax.scatter(p["mean"], i, color="#226d86", s=45, zorder=3)
        ax.annotate(
            f"${p['mean']:,.0f}  [{lo:,.0f}, {hi:,.0f}]",
            (p["mean"], i + 0.22),
            ha="center",
            va="center",
            fontsize=10,
            color=INK,
        )
    ax.set_yticks(range(3), LABELS.values())
    ax.set_ylim(2.55, -0.5)
    ax.axvline(0, color="#a8b2b2", linewidth=0.8)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.locator_params(axis="x", nbins=4)
    style(ax)
    fig.text(
        0.035,
        0.045,
        "8 paired dates in 4 cohort blocks\nExploratory 95% cohort-block intervals.\nSame previously inspected development cases.",
        fontsize=11,
        color="#46535d",
        linespacing=1.4,
    )
    save(fig, "evidence-paired-uncertainty")
    exports = [
        {
            k: r[k]
            for k in (
                "arm",
                "treatment",
                "requested",
                "mean_trading_pnl",
                "mean_matched_SPY_pnl",
                "mean_selection_pnl",
                "mean_exposure",
                "total_model_cost_usd",
            )
        }
        for r in rows
    ]
    with (ASSETS / "evidence-comparison.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(exports[0]))
        writer.writeheader()
        writer.writerows(exports)
    (PUBLIC / "figure-provenance.json").write_text(
        json.dumps(
            {
                "source": "results.json",
                "source_sha256": hashlib.sha256((PUBLIC / "results.json").read_bytes()).hexdigest(),
                "figures": [
                    "evidence-stock-selection",
                    "evidence-contract-status",
                    "evidence-paired-uncertainty",
                ],
                "limits": "Paired development arms, one repetition, four matured cohort blocks. Equal capital is not equal risk. Citation slots are not complete prose validation.",
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    build()

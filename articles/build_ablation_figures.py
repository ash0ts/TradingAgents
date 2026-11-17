"""Two figures from the frozen repeated-study export; no model calls or fitting."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "studies/debate-ablation-v5"
ASSETS = ROOT / "articles/agent-lens-in-practice/assets"
LABELS = {"luna-committee": "Full committee", "luna-no-research": "No research debate",
          "luna-no-risk": "No risk debate", "single-luna": "Single analyst"}
BG, INK, ACCENT = "#fcfaf6", "#172633", "#226d86"


def style(ax):
    ax.set_facecolor(BG)
    ax.tick_params(length=0, pad=7, labelcolor=INK)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(axis="x", color="#dce0de", linewidth=0.6)
    ax.set_axisbelow(True)


def save(fig, name):
    for extension in ("png", "svg"):
        fig.savefig(ASSETS / (name + "." + extension), facecolor=BG)
    plt.close(fig)


def build():
    data = json.loads((PUBLIC / "results.json").read_text())
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "svg.fonttype": "none"})
    comparisons = data["paired_contrasts"]
    fig, ax = plt.subplots(figsize=(6.2, 6.7), dpi=180)
    fig.subplots_adjust(left=0.35, right=0.95, top=0.72, bottom=0.29)
    fig.text(0.04, 0.96, "Did removing a debate help?", fontsize=18, weight="bold", color=INK, va="top")
    fig.text(0.04, 0.89, "Change in stock-selection P&L versus the full committee.\nDots are historical cohorts; diamonds are their means.", fontsize=11, color=INK, va="top")
    colors = ["#7b5a7e", "#aa7044", "#3a8172", "#597693"]
    shapes = ["o", "s", "^", "v"]
    for i, row in enumerate(comparisons):
        low, high = row["exploratory_bootstrap_95"]
        ax.plot([low, high], [i, i], color="#b1bcbd", linewidth=4, zorder=1)
        for j, (cohort, val) in enumerate(row["block_differences"].items()):
            ax.scatter(val, i + (j - 1.5) * 0.09, color=colors[j], marker=shapes[j], s=32,
                       label=cohort.replace("control-", "Control ").replace("midterms-", "Midterms ").replace("presidential-", "Election ") if i == 0 else None, zorder=3)
        ax.scatter(row["mean_difference"], i, color=INK, marker="D", s=56, zorder=4)
        ax.annotate(f"${row['mean_difference']:+,.0f}", (row["mean_difference"], i), xytext=(0, -25), textcoords="offset points", ha="center", weight="bold", color=INK)
    ax.axvline(0, color="#67777d", linewidth=1)
    ax.set_ylim(2.6, -0.6)
    ax.set_yticks(range(3), [LABELS[r["treatment"]] for r in comparisons])
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))
    ax.locator_params(axis="x", nbins=4)
    style(ax)
    fig.legend(*ax.get_legend_handles_labels(), loc="lower center", bbox_to_anchor=(0.52, 0.15), frameon=False, ncol=2, fontsize=9)
    fig.text(0.04, 0.035, "Per $100,000 scenario · 8 dates in 4 cohort blocks\nThree trials averaged within date · 10 bps/side\nIntervals are exploratory; more trials add no market dates.", fontsize=10, color="#46535d", linespacing=1.35)
    save(fig, "debate-paired-cohorts")

    rows = data["summaries"]
    fig, ax = plt.subplots(figsize=(6.2, 6.2), dpi=180)
    fig.subplots_adjust(left=0.35, right=0.95, top=0.73, bottom=0.27)
    fig.text(0.04, 0.96, "Would it make the same allocation again?", fontsize=16, weight="bold", color=INK, va="top")
    fig.text(0.04, 0.88, "Same frozen case, three fresh executions.\nAgreement is a reliability measure, not proof of skill.", fontsize=11, color=INK, va="top")
    for i, row in enumerate(rows):
        same, total = row["same_weight_cases"], row["repeatability_cases"]
        ax.barh(i, same, color=ACCENT, height=0.55, label="Same allocation" if i == 0 else None)
        ax.barh(i, total - same, left=same, color="#c9bc9f", hatch="//", height=0.55, label="Allocation changed" if i == 0 else None)
        ax.text(total + 1, i, f"{same}/{total}\nsame", va="center", fontsize=10, color=INK)
    total = max(r["repeatability_cases"] for r in rows)
    ax.set_xlim(0, total * 1.25)
    ax.set_xticks([0, total / 2, total])
    ax.set_ylim(3.7, -0.5)
    ax.set_yticks(range(4), [LABELS[r["treatment"]] for r in rows])
    style(ax)
    fig.legend(*ax.get_legend_handles_labels(), loc="lower center", bbox_to_anchor=(0.52, 0.15), frameon=False, ncol=2, fontsize=10)
    fig.text(0.04, 0.035, "All scheduled cases, including pending outcomes.\nCash and failed decisions remain in the denominator.\nThe export also separates contract status and actor failures.", fontsize=10, color="#46535d", linespacing=1.35)
    save(fig, "debate-repeatability")
    for name in ("summaries", "contrasts"):
        shutil.copyfile(PUBLIC / (name + ".csv"), ASSETS / ("debate-" + name + ".csv"))
    (PUBLIC / "figure-provenance.json").write_text(json.dumps({
        "source_sha256": hashlib.sha256((PUBLIC / "results.json").read_bytes()).hexdigest(),
        "figures": {"debate-paired-cohorts": "All three planned contrasts and all four cohort means; no significance or future-skill implication.",
                    "debate-repeatability": "Same-weight cases / all requested cases per treatment; agreement is not accuracy."},
        "renderer": "Matplotlib", "no_generated_product_images": True,
    }, indent=2) + "\n")


if __name__ == "__main__":
    build()

"""Build public article evidence from saved results. Makes no network/model calls."""

import csv
import hashlib
import json
import statistics
import zipfile
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
P = json.loads((REPO / "notebooks/data/showcase.json").read_text())
BODY = {k: v for k, v in P.items() if k != "public_data_sha256"}
assert (
    hashlib.sha256(
        json.dumps(BODY, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    == P["public_data_sha256"]
)
OUT = ROOT / "evidence"
OUT.mkdir(exist_ok=True)
A = ROOT / "meet-the-investment-committee/assets"
B = ROOT / "confident-expensive-and-wrong/assets"
C = ROOT / "did-it-beat-doing-nothing/assets"
AGENTS = ["default-committee", "luna-committee", "single-luna"]
METHODS = AGENTS + [
    "momentum-20",
    "mean-reversion-5",
    "AR-5",
    "ridge",
    "XGBoost",
    "DLinear",
    "chronos-bolt-small",
]
LABELS = dict(
    zip(
        METHODS,
        [
            "Luna/Sol committee",
            "All-Luna committee",
            "Single Luna analyst",
            "Momentum (20)",
            "Mean reversion (5)",
            "AR(5)",
            "Ridge",
            "XGBoost",
            "DLinear",
            "Chronos Bolt Small",
        ],
        strict=True,
    )
)
BG, INK, BLUE, GRAY, GOLD = "#fcfaf6", "#172633", "#226d86", "#9aa6a7", "#b68730"
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 11,
        "svg.fonttype": "none",
        "text.color": INK,
        "axes.labelcolor": INK,
        "xtick.color": INK,
        "ytick.color": INK,
    }
)
FIGURES = []


def write_csv(name, rows):
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with (OUT / name).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(
            {
                k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v
                for k, v in r.items()
            }
            for r in rows
        )


def save(fig, path, question, limits):
    fig.patch.set_facecolor(BG)
    for ax in fig.axes:
        ax.set_facecolor(BG)
    for ext in ["png", "svg"]:
        fig.savefig(
            path.with_suffix("." + ext), dpi=180, facecolor=BG, bbox_inches="tight", pad_inches=0.18
        )
    FIGURES.append(
        {
            "path": str(path.relative_to(ROOT)),
            "question": question,
            "limits": limits,
            "source": "notebooks/data/showcase.json",
            "public_data_sha256": P["public_data_sha256"],
        }
    )
    plt.close(fig)


def plain(ax):
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)


# Public exports use explicit field allowlists; raw reports, trace IDs and source
# text are deliberately absent. The authenticated crosswalk stays local.
fields = [
    "case_id",
    "treatment",
    "trial",
    "ticker",
    "cohort",
    "decision_date",
    "status",
    "rating",
    "forecast",
    "information_access",
    "cost_known_usd",
    "cost_upper_usd",
    "latency_s",
    "model_calls",
    "tool_calls",
    "unknown_calls",
    "behavior_tags",
    "missing_data_acknowledged",
    "evidence_sha256",
    "dataset_version",
    "code_revision",
]
predictions = [{k: r[k] for k in fields} for r in P["rows"]]
write_csv("predictions.csv", predictions)
scores = []
for r in P["rows"]:
    for h, s in r["scores_by_horizon"].items():
        scores.append(
            {
                "case_id": r["case_id"],
                "treatment": r["treatment"],
                "trial": r["trial"],
                "horizon_sessions": int(h),
                **s,
            }
        )
write_csv("scores-all-horizons.csv", scores)
write_csv(
    "portfolio-scenarios.csv",
    [{k: v for k, v in r.items() if k != "conversation_urls"} for r in P["portfolios"]],
)
write_csv("source-coverage.csv", P["coverage"])
reviews = []
by_key = {r["run_key"]: r for r in P["rows"]}
for r in P["reviews"]:
    row = by_key[r["run_key"]]
    reviews.append(
        {
            k: r[k]
            for k in ["case_id", "label", "rationale", "reviewer", "reviewed_at", "evidence_sha256"]
        }
        | {"treatment": row["treatment"], "trial": row["trial"]}
    )
write_csv("assistant-reviews.csv", reviews)
pairs = [
    {
        "treatment": k,
        "reference": "momentum-20",
        "mean_difference": v["mean"],
        "ci95_low": v["interval"][0],
        "ci95_high": v["interval"][1],
        "pairs": v["pairs"],
        "cohort_blocks": v["blocks"],
        "method": v["method"],
    }
    for k, v in P["paired_comparisons"].items()
]
write_csv("paired-comparisons.csv", pairs)
write_csv(
    "selected-examples.csv",
    [
        {"selection": selection, **{k: by_key[key][k] for k in fields}}
        for selection, key in P["examples"].items()
    ],
)
write_csv("method-summaries.csv", [{"treatment": k, **v} for k, v in P["summaries"].items()])
audit_path = REPO / "lab-runs/election-v1/hosted-audit.json"
if audit_path.exists():
    audit = json.loads((REPO / "lab-runs/election-v1/hosted-audit.json").read_text())
    verification = {
        "hosted_readback": {
            k: audit[k]
            for k in [
                "conversations",
                "spans",
                "model_calls",
                "all_evaluation_links_verified",
                "all_usage_reconciled",
            ]
        },
        "offline_reconciliation": json.loads(
            (REPO / "lab-runs/election-v1/e2e-reconciliation.json").read_text()
        ),
        "notebook_versions": [
            {
                k: row[k]
                for k in [
                    "name",
                    "version",
                    "source_sha256",
                    "static_sha256",
                    "static_bytes",
                    "has_static_output",
                    "url",
                    "runtime_versions",
                ]
            }
            for row in json.loads((REPO / "notebooks/publication.json").read_text())["notebooks"]
        ],
        "scope": "Readback verifies recorded execution and source/output versions, not semantic correctness. Hosted paid-run button was not exercised.",
    }
else:
    # A public checkout can rebuild tables/figures from the frozen payload.
    # Retain the published receipt; this is not a new hosted verification.
    verification = json.loads((OUT / "verification-receipts.json").read_text())
    assert verification["offline_reconciliation"]["public_data_sha256"] == P["public_data_sha256"]
(OUT / "verification-receipts.json").write_text(json.dumps(verification, indent=2) + "\n")
(OUT / "study-design-and-budget.json").write_text(
    json.dumps(
        {
            "qualification_design": P["design"],
            "budget": P["budget"],
            "limits": P["limits"],
            "budget_note": "Infrastructure reservation is not recorded spend; local hardware is unmetered. No new inference was launched for article publication.",
        },
        indent=2,
    )
    + "\n"
)
(ROOT / "private-evidence").mkdir(exist_ok=True)
(ROOT / "private-evidence/authenticated-case-index.json").write_text(
    json.dumps(
        [
            {
                k: r[k]
                for k in [
                    "case_id",
                    "treatment",
                    "trial",
                    "run_key",
                    "conversation_url",
                    "evidence_sha256",
                ]
            }
            for r in P["rows"]
            if r["conversation_url"]
        ],
        indent=2,
    )
    + "\n"
)

# Explain the evidence chain rather than implying that tracing improves returns.
fig, ax = plt.subplots(figsize=(6.8, 7.7))
ax.set(xlim=(0, 10), ylim=(0, 11))
ax.axis("off")
ax.text(0, 10.7, "Follow one decision all the way back", fontsize=19, weight="bold")
steps = [
    (
        "1  Freeze the case",
        "60 stock/date cases · cutoff 23:59:59 New York\nPrices + SEC + macro; missing sources recorded",
    ),
    (
        "2  Execute TradingAgents",
        "Three treatments × two trials = 360 runs\nLocal execution; isolated memory and checkpoints",
    ),
    (
        "3  Inspect in Agent Lens",
        "360 conversations · 15,058 spans\nActual tool/model activity and visible recommendations",
    ),
    (
        "4  Join decisions to outcomes",
        "Weave evaluation Call IDs link native spans\nFive-session primary outcomes; 2026 remains pending",
    ),
    (
        "5  Explore in Forge Notebooks",
        "Saved results, reviews and independent portfolio scenarios\nAuthenticated drilldowns to evidence and behavior",
    ),
]
for i, (title, detail) in enumerate(steps):
    y = 8.7 - i * 1.95
    ax.add_patch(
        FancyBboxPatch(
            (0.1, y),
            9.7,
            1.5,
            boxstyle="round,pad=.12",
            linewidth=1,
            edgecolor="#c5d3d5",
            facecolor="#edf3f1",
        )
    )
    ax.text(0.35, y + 1.12, title, fontsize=13.5, weight="bold", color=BLUE)
    ax.text(0.35, y + 0.85, detail, fontsize=10.7, va="top", linespacing=1.4)
    if i < 4:
        ax.annotate(
            "",
            xy=(5, y - 0.40),
            xytext=(5, y - 0.1),
            arrowprops={"arrowstyle": "->", "color": BLUE},
        )
save(
    fig,
    A / "evidence-chain",
    "How does a result resolve to its evidence?",
    "Diagram of this implementation; not a claim that observability improves financial performance.",
)

fig, axes = plt.subplots(
    2, 1, figsize=(6.7, 6.8), gridspec_kw={"height_ratios": [1.35, 1]}, layout="constrained"
)
sources = [
    ("prices", "Prices + corporate actions"),
    ("sec", "SEC company facts"),
    ("fred", "ALFRED macro vintages"),
    ("news", "Archived news"),
    ("reddit", "Reddit / social archive"),
    ("identity", "Identity lookup archive"),
    ("insiders", "Insider transactions"),
    ("prediction_markets", "Prediction markets"),
]
for i, (k, _label) in enumerate(sources):
    n = sum(k in r["available"] for r in P["coverage"])
    axes[0].barh(i, 60, color="#e7e7df", height=0.58)
    axes[0].barh(i, n, color=BLUE, height=0.58)
    axes[0].text(62, i, f"{n}/60", va="center", weight="bold")
axes[0].set_yticks(range(len(sources)), [v for _, v in sources])
axes[0].invert_yaxis()
axes[0].set_xlim(0, 72)
axes[0].set_xticks([])
axes[0].set_title("The evidence we actually had", loc="left", fontsize=18, weight="bold", pad=18)
plain(axes[0])
cohorts = ["midterms-2022", "control-2023", "presidential-2024", "control-2025", "midterms-2026"]
for i, c in enumerate(cohorts):
    rows = [
        r
        for r in P["rows"]
        if r["treatment"] == "single-luna" and r["trial"] == 0 and r["cohort"] == c
    ]
    m = sum(r["scores"]["outcome_status"] == "matured" for r in rows)
    axes[1].barh(i, 12, color="#eadcc0", height=0.58)
    axes[1].barh(i, m, color=BLUE, height=0.58)
    axes[1].text(12.3, i, f"{m} matured / {12 - m} pending", va="center")
axes[1].set_yticks(
    range(5),
    ["2022 midterms", "2023 control", "2024 presidential", "2025 control", "2026 midterms"],
)
axes[1].invert_yaxis()
axes[1].set_xlim(0, 24)
axes[1].set_xticks([])
plain(axes[1])
axes[1].set_title(
    "Five-session outcomes at the November 5 freeze", loc="left", fontsize=12, weight="bold", pad=15
)
save(
    fig,
    A / "coverage-and-maturity",
    "Which inputs and outcomes were available?",
    "Availability does not guarantee correctness. Global news and Stocktwits are also missing; the CSV lists every source.",
)

fig, axes = plt.subplots(1, 2, figsize=(6.8, 3.5), layout="constrained")
for ax, key, title, scale, fmt in [
    (axes[0], "latency_s", "Elapsed seconds / run", 1, "{:.0f}s"),
    (axes[1], "cost_known_usd", "Recorded model $ / run", 1, "${:.3f}"),
]:
    vals = [
        statistics.mean(r[key] for r in P["rows"] if r["treatment"] == t) * scale for t in AGENTS
    ]
    ax.barh(range(3), vals, color=[BLUE, "#6196a3", GRAY])
    ax.set_yticks(range(3), ["Luna/Sol", "All-Luna", "Single Luna"] if ax == axes[0] else [])
    ax.invert_yaxis()
    ax.set_xlim(0, max(vals) * 1.4)
    for i, v in enumerate(vals):
        ax.text(v + max(vals) * 0.035, i, fmt.format(v), va="center")
    ax.set_title(title, loc="left", fontsize=12, weight="bold")
    plain(ax)
fig.suptitle("More committee, more time", fontsize=18, weight="bold", x=0.02, ha="left")
save(
    fig,
    B / "latency-and-model-cost",
    "How much elapsed time and API cost did each agent use?",
    "Means over 120 runs per treatment; excludes local hardware and infrastructure. Does not isolate a causal effect of debate.",
)

fig, ax = plt.subplots(figsize=(6.8, 4.7))
ax.axis("off")
ax.set(xlim=(0, 10), ylim=(0, 7))
ax.text(0, 6.6, "Inspect a flag before calling it a failure", fontsize=18, weight="bold")
ax.text(0, 5.9, "Six selected Codex assistant reviews · no human reference labels", fontsize=11)
for i, r in enumerate(reviews):
    y = 5.1 - i * 0.78
    label = "Coverage gap" if r["label"] == "confirmed-failure" else "False positive"
    ax.text(
        0,
        y,
        f"{r['case_id']}\n{LABELS[r['treatment']]} · trial {r['trial']}",
        fontsize=10.3,
        va="center",
        linespacing=1.3,
    )
    ax.text(
        7.2,
        y,
        label,
        color=GOLD if label == "Coverage gap" else BLUE,
        weight="bold",
        fontsize=11,
        va="center",
    )
ax.text(
    0, 0.05, "Selected cases cannot estimate a campaign-wide false-positive rate.", fontsize=10.5
)
save(
    fig,
    B / "reviewed-candidates",
    "What did inspection change about the candidate labels?",
    "Selected assistant reviews; not expert adjudication or a representative accuracy estimate.",
)

fig, ax = plt.subplots(figsize=(7.1, 6.4))
fig.subplots_adjust(left=0.29, right=0.96, top=0.84, bottom=0.17)
counts = []
for i, t in enumerate(METHODS):
    rows = [r for r in P["rows"] if r["treatment"] == t]
    count = Counter(
        "pending"
        if r["scores"]["outcome_status"] != "matured"
        else "scored"
        if r["scores"]["directional_correct"] is not None
        else "hold"
        for r in rows
    )
    assert sum(count.values()) == len(rows)
    left = 0
    for k, color in [("scored", BLUE), ("hold", GRAY), ("pending", GOLD)]:
        v = count[k]
        ax.barh(i, v, left=left, color=color, height=0.65, label=k if i == 0 else None)
        if v:
            ax.text(
                left + v / 2,
                i,
                str(v),
                ha="center",
                va="center",
                fontsize=10,
                color="white" if k == "scored" else INK,
            )
        left += v
    counts.append({"treatment": t, "requested": len(rows), **count})
ax.set_yticks(range(10), [LABELS[t] for t in METHODS])
ax.invert_yaxis()
ax.set_xlim(0, 123)
plain(ax)
ax.set_xlabel("Prediction records (agent trials share market cases)")
ax.legend(loc="upper left", bbox_to_anchor=(0, -0.13), ncol=3, frameon=False)
fig.text(0.02, 0.97, "Which predictions enter the score?", fontsize=18, weight="bold", va="top")
fig.text(0.02, 0.91, "Five-session horizon · Hold abstains · zero execution failures", fontsize=11)
write_csv("directional-denominators.csv", counts)
save(
    fig,
    C / "directional-denominators",
    "What is the denominator of directional accuracy?",
    "Pending takes precedence over Hold, so the three groups partition requested records. Passives make no directional forecasts and are omitted.",
)

order = [t for t in METHODS if t != "momentum-20"]
fig, ax = plt.subplots(figsize=(7, 6.4))
fig.subplots_adjust(left=0.29, right=0.94, top=0.82, bottom=0.17)
for i, t in enumerate(order):
    r = P["paired_comparisons"][t]
    m = r["mean"] * 100
    lo, hi = [x * 100 for x in r["interval"]]
    ax.plot([lo, hi], [i, i], color=BLUE if t in AGENTS else GRAY, lw=3)
    ax.plot(m, i, "o", color=BLUE if t in AGENTS else "#52676b")
    ax.text(4.75, i, str(r["pairs"]), va="center", fontsize=10)
ax.axvline(0, color=GOLD, ls="--", lw=1)
ax.set_yticks(range(9), [LABELS[t] for t in order])
ax.invert_yaxis()
ax.set_xlim(-1.9, 5.3)
ax.set_xlabel("Signed excess return difference (percentage points)")
plain(ax)
fig.text(0.02, 0.97, "Compared on shared market cases", fontsize=18, weight="bold", va="top")
fig.text(
    0.02, 0.91, "Method minus momentum · point estimate and exploratory 95% interval", fontsize=10.7
)
fig.text(0.88, 0.85, "Pairs", fontsize=10, weight="bold")
fig.text(
    0.02,
    0.04,
    "Four cohort blocks · 2,000 resamples · trials averaged within case\nUnequal paired subsets; these intervals do not establish a general winner.",
    fontsize=10.5,
    linespacing=1.5,
)
save(
    fig,
    C / "paired-uncertainty",
    "How uncertain are matched differences from momentum?",
    "Four matured blocks; exploratory bootstrap, no multiple-comparison correction. Different methods have different paired subsets.",
)

fees = []
for t in ["equal-weight", "SPY", "cash"] + METHODS:
    for bps in [0, 5, 10, 25]:
        selected = [
            r
            for r in P["portfolios"]
            if r["treatment"] == t and r["bps_per_side"] == bps and r["status"] == "matured"
        ]
        fees.append(
            {
                "treatment": t,
                "bps_per_side": bps,
                "mean_trading_pnl_usd": statistics.mean(r["trading_pnl"] for r in selected),
                "scenarios": len(selected),
            }
        )
write_csv("fee-sensitivity.csv", fees)
fig, axes = plt.subplots(1, 2, figsize=(7.1, 4.7), layout="constrained")
for ax, group, title in [
    (axes[0], AGENTS, "Agent treatments"),
    (
        axes[1],
        ["equal-weight", "SPY", "ridge", "mean-reversion-5"],
        "Invested controls and two baselines",
    ),
]:
    for t in group:
        rows = [r for r in fees if r["treatment"] == t]
        ax.plot(
            [r["bps_per_side"] for r in rows],
            [r["mean_trading_pnl_usd"] for r in rows],
            marker="o",
            label=LABELS.get(t, t),
        )
    ax.axhline(0, color=GRAY, lw=0.7)
    ax.set_xticks([0, 5, 10, 25])
    ax.set_xlabel("Basis points per side")
    ax.set_ylabel("Mean trading P&L ($ / $100k)")
    ax.set_title(title, fontsize=10.5)
    plain(ax)
    ax.legend(fontsize=8.5, frameon=False, loc="upper right")
fig.suptitle("A few basis points matter at this scale", fontsize=17, weight="bold")
save(
    fig,
    C / "fee-sensitivity",
    "How much does the fee assumption change P&L?",
    "Selected methods for readability; all 13 in CSV. Separate y-axis scales; independent scenarios, model expense excluded.",
)

manifest = {
    "schema": "article-evidence-v1",
    "source": "notebooks/data/showcase.json",
    "public_data_sha256": P["public_data_sha256"],
    "source_file_sha256": hashlib.sha256(
        (REPO / "notebooks/data/showcase.json").read_bytes()
    ).hexdigest(),
    "evidence_manifest_sha256": "92623c2d0bf66b9c698f158e1374359303469a214dbcc110583e907abec4f6ef",
    "paid_execution_revision": "edaa0e68895b8f671c05d3ca382751148c784801",
    "freeze_through": P["freeze_through"],
    "counts": {
        "predictions": len(predictions),
        "scores_all_horizons": len(scores),
        "portfolios": len(P["portfolios"]),
        "coverage_cases": len(P["coverage"]),
        "assistant_reviews": len(reviews),
    },
    "figures": FIGURES,
    "files": {
        f.name: hashlib.sha256(f.read_bytes()).hexdigest()
        for f in sorted(OUT.iterdir())
        if f.suffix == ".csv"
        or f.name in {"verification-receipts.json", "study-design-and-budget.json"}
    },
}
(OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
(OUT / "README.md").write_text("""# TradingAgents election lab: evidence release

This is the complete public tabular result export for the November 5, 2026 freeze: 960 predictions, 2,880 horizon scores, 640 portfolio scenarios, 60 source-coverage cases and six selected assistant reviews. It contains no new experiment or paid model execution.

Join predictions to scores on `case_id`, `treatment`, `trial`; add `horizon_sessions` for score uniqueness. Join portfolio scenarios on `treatment`, `trial`, `decision_date`; distinguish `bps_per_side`. Each decision-date scenario starts with $100,000. Fees apply on both sides. Returns are decimals, dollars are USD. Empty numeric CSV fields are unavailable, never zero. Pending outcomes remain pending. Portfolio means are independent-scenario averages, never a concatenated equity curve.

Agent Lens links and raw source bodies are intentionally absent from this public package. The authenticated Forge notebooks provide the result-to-conversation drilldown for authorized team members. A local private crosswalk retains the exact 360 conversation mappings. Evidence SHA-256 values identify the frozen case bundle without redistributing its source content. This public package supports result reconciliation; a full agent rerun additionally requires the private source artifact and model access.

## Reproduce and check

In the TradingAgents fork, use the pinned project environment, then run:

```sh
.venv/bin/python articles/build_assets.py
.venv/bin/python articles/build_evidence.py
.venv/bin/python scripts/reconcile_campaign.py
```

`manifest.json` gives the canonical payload digest, evidence manifest, execution revision, row counts, file hashes, figure questions and limits. `method-summaries.csv` preserves denominators. `directional-denominators.csv` partitions pending first, then scored or matured Hold. Assistant review labels are selected, not representative, and are not human labels. `paired-comparisons.csv` compares with momentum after averaging trials within case: four cohort blocks and 2,000 bootstrap resamples, seed 2026. The roster does not isolate the effect of debate because prompt objectives and evidence delivery differ. Historical model knowledge remains possible.

Public Forge notebooks:
- https://forge.coreweave.com/notebooks/Tm90ZWJvb2s6MTUyNjA%3D
- https://forge.coreweave.com/notebooks/Tm90ZWJvb2s6MTUyNzE%3D
- https://forge.coreweave.com/notebooks/Tm90ZWJvb2s6MTUyNzI%3D
""")
with zipfile.ZipFile(OUT / "tradingagents-public-evidence.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(OUT.iterdir()):
        if f.suffix in {".csv", ".json", ".md"}:
            z.write(f, f.name)
print(json.dumps(manifest["counts"]))
print(f"Generated {len(FIGURES)} additional reproducible figures")

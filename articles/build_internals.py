"""Inspect frozen committee handoffs without rerunning or rescoring the actors."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "internals"
ASSETS = ROOT / "agent-lens-in-practice/assets"
RATING = re.compile(
    r"(?:Recommendation|Rating)\*{0,2}\s*:\s*\*{0,2}(Buy|Overweight|Hold|Underweight|Sell)\b",
    re.I,
)
CONDITION = re.compile(
    r"only (?:after|if|on|above|upon)|wait for|conditional (?:on|increase)|subject to", re.I
)
MISSING_HORIZON = re.compile(r"\*\*Time Horizon\*\*:\s*not provided", re.I)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def observe(row, source_sha256, sleeve):
    """Labels describe recorded text; phrase matches are not failure judgments."""
    state, report = row.get("state", {}), row["report"]
    match = RATING.search(state.get("investment_plan", ""))
    prior = match.group(1).title() if match else None
    events = row.get("events", [])
    return {
        "case_id": row["case_id"],
        "treatment": row["treatment"],
        "trial": row["trial"],
        "cohort": row["cohort"],
        "ticker": row["ticker"],
        "research_rating": prior,
        "final_rating": row["rating"],
        "rating_changed": prior != row["rating"] if prior else None,
        "condition_phrase_candidate": bool(CONDITION.search(report)),
        "condition_phrases": sorted({m.group().lower() for m in CONDITION.finditer(report)}),
        "horizon_explicitly_not_provided": bool(MISSING_HORIZON.search(report)),
        "missing_tool_evidence": any(
            e["kind"] == "tool_end" and "DATA_UNAVAILABLE" in str(e.get("result", ""))
            for e in events
        ),
        "outcome_status": row["scores"]["outcome_status"],
        "signed_excess_return": row["scores"]["signed_excess_return"],
        "sleeve_pnl_usd": float(sleeve["trading_pnl"]) if sleeve["trading_pnl"] else None,
        "target_weight": float(sleeve["target_weight"]),
        "source_prediction_sha256": source_sha256,
        "evidence_sha256": row["evidence_sha256"],
        "report_sha256": sha(report.encode()),
        "research_plan_sha256": sha(state.get("investment_plan", "").encode()),
        "code_revision": row["code_revision"],
    }


def collect(campaign):
    sleeves = {
        (r["case_id"], r["treatment"], int(r["trial"])): r
        for r in csv.DictReader((ROOT / "trading-scenarios/stock-contributions.csv").open())
    }
    rows = []
    for path in sorted(campaign.rglob("prediction.json")):
        row = json.loads(path.read_text())
        key = (row["case_id"], row["treatment"], row["trial"])
        sleeve = sleeves[key]
        assert row["evidence_sha256"] == sleeve["evidence_sha256"]
        assert row["rating"] == sleeve["rating"]
        rows.append(observe(row, sha(path.read_bytes()), sleeve))
    assert len(rows) == len({(r["case_id"], r["treatment"], r["trial"]) for r in rows}) == 360
    write_json(OUT / "observations.json", rows)


def summarize(rows):
    summaries = []
    for treatment in sorted({r["treatment"] for r in rows}):
        selected = [r for r in rows if r["treatment"] == treatment]
        comparable = [r for r in selected if r["research_rating"] is not None]
        summaries.append(
            {
                "treatment": treatment,
                "runs": len(selected),
                "comparable_research_final_ratings": len(comparable),
                "rating_changed": sum(r["rating_changed"] for r in comparable),
                "rating_unchanged": sum(not r["rating_changed"] for r in comparable),
                "condition_phrase_candidates": sum(
                    r["condition_phrase_candidate"] for r in selected
                ),
                "horizon_explicitly_not_provided": sum(
                    r["horizon_explicitly_not_provided"] for r in selected
                ),
                "missing_tool_evidence": sum(r["missing_tool_evidence"] for r in selected),
                "matured_runs": sum(r["outcome_status"] == "matured" for r in selected),
            }
        )
    return summaries


def render(summaries):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {"font.family": "DejaVu Sans", "svg.fonttype": "none", "svg.hashsalt": "internals-v1"}
    )
    labels = {
        "default-committee": "Luna/Sol committee",
        "luna-committee": "All-Luna committee",
        "single-luna": "Single Luna",
    }
    fig, axes = plt.subplots(2, 1, figsize=(6.3, 6.5), dpi=170)
    fig.patch.set_facecolor("#fcfaf6")
    fig.subplots_adjust(left=0.35, right=0.92, top=0.80, bottom=0.15, hspace=0.65)
    fig.text(
        0.04,
        0.96,
        "Read the conditions, not just the rating",
        fontsize=17,
        weight="bold",
        color="#172633",
    )
    fig.text(
        0.04,
        0.90,
        "120 executions per treatment · same 60 cases, two trials\nText checks on saved outputs; no new predictions",
        fontsize=11,
        color="#46535d",
    )
    for ax, key, title in zip(
        axes,
        ["condition_phrase_candidates", "horizon_explicitly_not_provided"],
        ["Conditional wording: review candidates", "Final horizon field: “not provided”"],
        strict=True,
    ):
        ax.set_facecolor("#fcfaf6")
        values = [s[key] for s in summaries]
        ax.barh(range(3), values, color="#226d86", height=0.55)
        for i, value in enumerate(values):
            ax.text(value + 3, i, f"{value}/120", va="center", fontsize=11)
        ax.set_yticks(range(3), [labels[s["treatment"]] for s in summaries], fontsize=11)
        ax.invert_yaxis()
        ax.set_xlim(0, 125)
        ax.set_xticks([0, 40, 80, 120])
        ax.tick_params(length=0)
        ax.set_title(title, loc="left", fontsize=12, pad=12)
        for spine in ax.spines.values():
            spine.set_visible(False)
    fig.text(
        0.04,
        0.045,
        "Phrase matches can describe exits or position limits.\nDifferent prompts and output schemas prevent a fair quality ranking.",
        fontsize=10.5,
        color="#46535d",
    )
    for suffix in ["png", "svg"]:
        fig.savefig(
            ASSETS / f"internals-contract-checks.{suffix}",
            metadata={"Date": None} if suffix == "svg" else {},
        )
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--campaign", type=Path, help="Optional private source; otherwise rebuild public summaries"
    )
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    if args.campaign:
        collect(args.campaign)
    rows = json.loads((OUT / "observations.json").read_text())
    summaries = summarize(rows)
    write_json(OUT / "summaries.json", summaries)
    for name, data in [("observations", rows), ("summaries", summaries)]:
        with (OUT / f"{name}.csv").open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(
                {k: json.dumps(v) if isinstance(v, list) else v for k, v in row.items()}
                for row in data
            )
    render(summaries)
    write_json(
        OUT / "manifest.json",
        {
            "schema": 1,
            "analysis": "post-hoc descriptive handoff audit",
            "review_date": "2026-11-09",
            "rows": len(rows),
            "independent_cases": len({r["case_id"] for r in rows}),
            "paid_model_calls": 0,
            "original_predictions_and_scores_changed": False,
            "files": {
                p.name: sha(p.read_bytes())
                for p in sorted(OUT.glob("*"))
                if p.name != "manifest.json" and p.is_file()
            },
            "figures": {
                p.name: sha(p.read_bytes())
                for p in sorted(ASSETS.glob("internals-contract-checks.*"))
            },
        },
    )
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()

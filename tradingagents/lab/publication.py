"""An allowlist public export; raw reports, prompts, evidence and credentials stay private."""
from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from tradingagents.lab.diagnostics import analyze, showcase_examples
from tradingagents.lab.evidence import canonical, digest
from tradingagents.lab.portfolio import run_portfolios
from tradingagents.lab.scoring import paired_blocks, summary

ROW_FIELDS = ["case_id", "cohort", "ticker", "decision_date", "treatment", "trial", "status", "rating", "forecast",
              "conversation_url", "evidence_sha256", "dataset_version", "code_revision", "run_key", "information_access",
              "latency_s", "cost_upper_usd", "cost_known_usd", "unknown_calls", "scores", "scores_by_horizon"]
PORTFOLIO_FIELDS = ["decision_date", "entry_date", "exit_date", "treatment", "trial", "cohort", "bps_per_side",
                    "status", "return", "trading_pnl", "transaction_costs", "dividends", "model_expense_upper_usd",
                    "economic_pnl", "exposure_at_entry", "turnover", "max_drawdown", "failed_or_unrated_sleeves_held_cash", "conversation_urls"]


def public_budget(ledger):
    """Infrastructure holds are budget reservations, never measured model charges."""
    result = ledger.totals()
    with ledger.connect() as db:
        rows = db.execute("SELECT model,reserve,charged FROM calls").fetchall()
    infrastructure = [r for r in rows if r[0] == "forge-infrastructure-pending-reconciliation"]
    result.update(
        infrastructure_reserved_usd=sum(r[1] for r in infrastructure if r[2] is None) / 1e6,
        model_unknown_calls=sum(r[2] is None for r in rows if r not in infrastructure),
        infrastructure_status="Conservative holds; invoice reconciliation pending. Not recorded spend.",
        campaign_cap_usd=250,
    )
    return result


def public_export(root, output, destination="notebooks/data/showcase.json"):
    root, output = Path(root), Path(output)
    manifest = json.loads((root / "manifest.json").read_text())
    design = json.loads((output / "design.json").read_text())
    rows = [json.loads(p.read_text()) for directory in ["campaign", "baselines"]
            for p in (output / directory).rglob("*.json") if directory == "baselines" or p.name == "prediction.json"]
    agents = [r for r in rows if r.get("conversation_url")]
    diagnostics = analyze(root, output)
    public_rows = []
    for row in rows:
        clean = {k: row.get(k) for k in ROW_FIELDS}
        behavior = diagnostics["results"].get(row.get("run_key"), {})
        clean["behavior_tags"] = sorted({f["tag"] for f in behavior.get("findings", [])})
        clean["missing_data_acknowledged"] = behavior.get("missing_data_acknowledged")
        clean["model_calls"] = len([e for e in row.get("events", []) if e["kind"] == "llm"])
        clean["tool_calls"] = len([e for e in row.get("events", []) if e["kind"] == "tool_start"])
        public_rows.append(clean)
    portfolios = [{k: p.get(k) for k in PORTFOLIO_FIELDS} for p in run_portfolios(root, output)]
    summaries = {t: summary([r for r in rows if r["treatment"] == t]) for t in sorted({r["treatment"] for r in rows})}
    from tradingagents.lab.budget import Ledger
    report = {"schema": 1, "campaign_id": "election-replay-v1", "generated_at": datetime.now(UTC).isoformat(),
              "freeze_through": manifest["freeze_through"], "evidence_version": manifest["version"], "design": design,
              "planned_agent_runs": 10 * design["stocks"] * design["trials"] * 3,
              "completed_agent_runs": len(agents), "agent_failures": sum(r["status"] != "success" for r in agents),
              "rows": public_rows, "portfolios": portfolios, "summaries": summaries,
              "coverage": manifest["coverage"], "examples": showcase_examples(agents),
              "behavior_counts": dict(Counter(tag for r in public_rows for tag in r["behavior_tags"])),
              "paired_comparisons": {t: paired_blocks(rows, t, "momentum-20") for t in summaries if t not in {"cash", "SPY", "equal-weight", "momentum-20"}},
              "budget": public_budget(Ledger(output / "budget.sqlite")),
              "lens_views": [{k: v[k] for k in ("id", "name", "url")} for v in json.loads((output / "lens-views.json").read_text())] if (output / "lens-views.json").exists() else [],
              "reviews": json.loads((output / "public-reviews.json").read_text()) if (output / "public-reviews.json").exists() else [],
              "regressions": json.loads((output / "regressions-v1.json").read_text()) if (output / "regressions-v1.json").exists() else {"schema": 1, "records": []},
              "limits": ["Retrospective replay cannot remove pretrained knowledge.",
                         "No archived news/social evidence: this is a prices, SEC, and macro evidence comparison.",
                         "Five-session 2026 outcomes are pending at the November 5 freeze.",
                         "Only four cohorts have matured five-session outcomes. Block intervals are exploratory, not an election-causality claim.",
                         "API dollars use recorded token usage; local hardware and hosted infrastructure are reported separately."]}
    report["public_data_sha256"] = digest(report)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(report))
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="lab-data/election-v1")
    parser.add_argument("--output", default="lab-runs/election-v1")
    args = parser.parse_args()
    data = public_export(args.root, args.output)
    print(json.dumps({"agent_runs": data["completed_agent_runs"], "public_data_sha256": data["public_data_sha256"]}))

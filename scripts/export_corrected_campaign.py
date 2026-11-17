"""Reconcile and export only derived v2 results; preserve all original outcomes."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from tradingagents.lab.budget import Ledger
from tradingagents.lab.evidence import canonical
from tradingagents.lab.execution import execution_check, score_execution
from tradingagents.lab.portfolio import run_portfolios, simulate
from tradingagents.lab.protocol import STOCKS, calendar_sessions, cases
from tradingagents.lab.publication import PORTFOLIO_FIELDS, ROW_FIELDS, public_budget
from tradingagents.lab.scoring import paired_blocks, summary

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "lab-runs/election-contract-v2"
PUBLIC = REPO / "studies/execution-contract-v2"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export():
    design = json.loads((OUT / "design.json").read_text())
    protocol = json.loads((PUBLIC / "protocol.json").read_text())
    manifest = json.loads((REPO / "lab-data/election-v1/manifest.json").read_text())
    outcomes = json.loads((REPO / "lab-data/election-v1/outcomes.json").read_text())
    original = json.loads((REPO / "notebooks/data/showcase.json").read_text())
    stocks = STOCKS if design["stocks"] == 6 else ["MSFT", "JPM", "XOM"]
    expected = {(c["case_id"], t, i) for c in cases(stocks) for t in protocol["treatments"] for i in range(design["trials"])}
    paths = sorted((OUT / "campaign").rglob("prediction.json"))
    rows = [json.loads(p.read_text()) for p in paths]
    key = lambda r: (r["case_id"], r["treatment"], r["trial"])  # noqa: E731
    assert len(rows) == len(expected) and {key(r) for r in rows} == expected, "Incomplete campaign"
    original_index = {key(r): r for r in original["rows"]}
    public, paired = [], []
    for row, path in zip(rows, paths, strict=True):
        assert row["evidence_sha256"] == manifest["cases"][row["case_id"]]
        assert row["execution_check"] == execution_check(row)
        for h, observed in row["scores_by_horizon"].items():
            assert observed == score_execution(row, outcomes["cases"][row["case_id"]][h], h)
        prior = original_index[key(row)]
        old_path = REPO / "lab-runs/election-v1/campaign" / row["case_id"] / row["treatment"] / str(row["trial"]) / "prediction.json"
        old = json.loads(old_path.read_text())
        assert old["scores"] == prior["scores"] and old["rating"] == prior["rating"]
        decision = row.get("execution_decision") or {}
        order = decision.get("order") or {}
        clean = {k: row.get(k) for k in ROW_FIELDS}
        clean.update(contract_status=row["execution_check"]["status"],
                     target_weight=row["execution_check"]["target_weight"],
                     order_kind=order.get("kind"), condition_count=len(order.get("conditions", [])),
                     execution_mandate=row["execution_mandate"],
                     source_prediction_sha256=digest(path), original_prediction_sha256=digest(old_path),
                     original_conversation_url=prior["conversation_url"])
        public.append(clean)
        paired.append({"case_id": row["case_id"], "treatment": row["treatment"], "trial": row["trial"],
                       "original_rating": prior["rating"], "corrected_rating": row.get("rating"),
                       "contract_status": clean["contract_status"], "target_weight": clean["target_weight"],
                       "original_signed_excess": prior["scores"]["signed_excess_return"],
                       "corrected_signed_excess": row["scores"]["signed_excess_return"],
                       "outcome_status": row["scores"]["outcome_status"],
                       "original_conversation_url": prior["conversation_url"],
                       "corrected_conversation_url": row["conversation_url"]})
    portfolios = run_portfolios(REPO / "lab-data/election-v1", OUT)
    portfolio_public = [{k: p.get(k) for k in PORTFOLIO_FIELDS} for p in portfolios]
    summaries = []
    sessions = calendar_sessions()
    for treatment in protocol["treatments"]:
        selected = [r for r in public if r["treatment"] == treatment]
        old_rows = [original_index[key(r)] for r in selected]
        old_groups = defaultdict(list)
        for r in old_rows:
            old_groups[(r["decision_date"], r["trial"], r["cohort"])].append(r)
        old_p = [{"cohort": cohort, "trial": trial, **simulate(date, group, outcomes["prices"], sessions,
                   freeze=outcomes["freeze_through"])}
                 for (date, trial, cohort), group in sorted(old_groups.items())]
        old_p = [p for p in old_p if p["status"] == "matured"]
        new_p = [p for p in portfolios if p["treatment"] == treatment and p["bps_per_side"] == 10 and p["status"] == "matured"]
        if design["stocks"] == 6:
            published_old = {(p["decision_date"], p["trial"]): p for p in original["portfolios"]
                             if p["treatment"] == treatment and p["bps_per_side"] == 10 and p["status"] == "matured"}
            for p in old_p:
                assert abs(p["trading_pnl"] - published_old[p["decision_date"], p["trial"]]["trading_pnl"]) < 1e-7
        portfolio_pairs = [{"case_id": p["decision_date"], "cohort": p["cohort"], "treatment": version,
                            "scores": {"trading_pnl": p["trading_pnl"]}}
                           for version, group in [("original", old_p), ("corrected", new_p)] for p in group]
        record = {"treatment": treatment, "requested": len(selected),
                  "contract_counts": dict(Counter(r["contract_status"] for r in selected)),
                  "original": summary(old_rows), "corrected": summary(selected),
                  "paired_financial": paired_blocks(portfolio_pairs, "corrected", "original", metric="trading_pnl")}
        for version, group, executions in [("original", old_p, old_rows), ("corrected", new_p, selected)]:
            record[version].update(
                mean_trading_pnl=float(np.mean([p["trading_pnl"] for p in group])),
                matured_accounts=len(group), independent_dates=len({p["decision_date"] for p in group}),
                mean_exposure=float(np.mean([p["exposure_at_entry"] for p in group])),
                total_model_cost_usd=sum(r["cost_upper_usd"] for r in executions),
                mean_latency_s=float(np.mean([r["latency_s"] for r in executions])),
            )
        summaries.append(record)
    ledger = Ledger(REPO / "lab-runs/election-v1/budget.sqlite")
    with ledger.connect() as db:
        campaign_cost = db.execute("SELECT sum(coalesce(charged,reserve))/1000000.0 FROM calls WHERE run_key LIKE 'election-contract-v2/%'").fetchone()[0]
    result = {"campaign_id": protocol["campaign_id"], "protocol_sha256": digest(PUBLIC / "protocol.json"),
              "design": design, "rows": public, "portfolios": portfolio_public,
              "summaries": summaries, "paired_rows": paired,
              "baseline_controls": {"unchanged_payload_sha256": digest(REPO / "notebooks/data/showcase.json"),
                                    "methods": list(original["summaries"])},
              "budget": public_budget(ledger), "new_campaign_cost_upper_usd": campaign_cost,
              "limitations": protocol["limitations"],
              "observed_comparison_limits": [
                  "The committee stock-price tool injects the case ticker; it does not expose SPY prices. The single analyst's direct bundle includes SPY. This inherited evidence-access difference remains in both versions.",
                  "The frozen contract checker validates structured orders, not every factual or semantic claim in the report.",
              ], "raw_reports_public": False}
    (PUBLIC / "results.json").write_bytes(canonical(result))
    for name, values in [("paired-decisions", paired), ("portfolio-results", portfolio_public)]:
        with (PUBLIC / f"{name}.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(values[0]))
            writer.writeheader()
            writer.writerows({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in r.items()} for r in values)
    (PUBLIC / "summaries.json").write_bytes(canonical(summaries))
    print(json.dumps({"executions": len(public), "portfolios": len(portfolios), "new_campaign_cost_upper_usd": campaign_cost, "summaries": summaries}, indent=2))
    return result


if __name__ == "__main__":
    export()

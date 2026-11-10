"""Derived dashboard metrics. The frozen campaign remains the source of truth."""
from __future__ import annotations

from collections import Counter
from statistics import mean

from tradingagents.lab.evidence import digest
from tradingagents.lab.scoring import paired_blocks, summary


def validate_payload(data):
    """Reject altered payloads or aggregates before publishing a dashboard."""
    body = {k: v for k, v in data.items() if k != "public_data_sha256"}
    if digest(body) != data["public_data_sha256"]:
        raise ValueError("Public payload fingerprint does not match")
    rows = data["rows"]
    identities = [(r["case_id"], r["treatment"], r["trial"]) for r in rows]
    if len(set(identities)) != len(rows):
        raise ValueError("Duplicate case/treatment/trial")
    for treatment, expected in data["summaries"].items():
        actual = summary([r for r in rows if r["treatment"] == treatment])
        if actual != expected:
            raise ValueError(f"Summary does not reconcile: {treatment}")
    for treatment, expected in data["paired_comparisons"].items():
        if paired_blocks(rows, treatment, "momentum-20") != expected:
            raise ValueError(f"Paired comparison does not reconcile: {treatment}")
    agents = [r for r in rows if r["conversation_url"]]
    if len(agents) != data["completed_agent_runs"]:
        raise ValueError("Agent completion count does not reconcile")
    if dict(Counter(t for r in rows for t in r["behavior_tags"])) != data["behavior_counts"]:
        raise ValueError("Behavior counts do not reconcile")
    return {"rows": len(rows), "agent_runs": len(agents),
            "baseline_predictions": len(rows) - len(agents),
            "market_cases": len({r["case_id"] for r in rows}),
            "public_data_sha256": data["public_data_sha256"]}


def treatment_metrics(data, treatment):
    rows = [r for r in data["rows"] if r["treatment"] == treatment]
    totals = data["summaries"][treatment]
    metrics = {"coverage/actionable_pct": totals["coverage"] * 100,
               "coverage/requested_trials": totals["requested"],
               "coverage/market_cases": len({r["case_id"] for r in rows}),
               "coverage/scored_trials": totals["signed_excess_return"]["n"],
               "coverage/pending_trials": totals["pending"],
               "coverage/abstained_trials": totals["abstained"],
               "execution/failed_trials": totals["failed"]}
    for source, target in [("signed_excess_return", "outcomes/signed_excess_pct"),
                           ("directional_correct", "outcomes/directional_accuracy_pct"),
                           ("absolute_forecast_error", "outcomes/forecast_mae_pp")]:
        value = totals[source]["mean"]
        # Passive portfolios have no directional forecast: absent, never zero.
        if value is not None:
            metrics[target] = value * 100
    portfolios = [p for p in data["portfolios"] if p["treatment"] == treatment
                  and p["bps_per_side"] == 10 and p["status"] == "matured"]
    if portfolios:
        metrics.update({"portfolio/mean_pnl_usd": mean(p["trading_pnl"] for p in portfolios),
                        "portfolio/scenarios": len(portfolios),
                        "portfolio/decision_dates": len({p["decision_date"] for p in portfolios}),
                        "portfolio/mean_exposure_pct": mean(p["exposure_at_entry"] for p in portfolios) * 100,
                        "portfolio/mean_fees_usd": mean(p["transaction_costs"] for p in portfolios)})
    if rows and rows[0]["conversation_url"]:
        metrics.update({"execution/mean_latency_s": mean(r["latency_s"] for r in rows),
                        "execution/mean_model_calls": mean(r["model_calls"] for r in rows),
                        "execution/mean_tool_calls": mean(r["tool_calls"] for r in rows),
                        "cost/recorded_model_usd": sum(r["cost_known_usd"] for r in rows),
                        "cost/mean_model_usd": mean(r["cost_known_usd"] for r in rows)})
        for tag in data["behavior_counts"]:
            metrics["behavior/" + tag] = sum(tag in r["behavior_tags"] for r in rows)
    return metrics

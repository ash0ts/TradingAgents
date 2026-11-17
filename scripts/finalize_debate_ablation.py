"""Apply disclosed audit/accounting corrections around the frozen analysis.

No outcomes, weights, financial estimands, failed attempts or actor inputs change.
The execution-tag exporter remains byte-for-byte frozen. The amendment records
this wrapper and the failure-audit/accounting helpers before final analysis.
"""
from __future__ import annotations

import csv
import json
import shutil
from collections import defaultdict
from statistics import mean

import audit_debate_failures
import export_debate_ablation as frozen
from reconcile_cache_write_costs import reconcile
from run_debate_ablation import OUT, PUBLIC, REPO, sha

from tradingagents.lab.evidence import canonical


def finalize():
    amendment = json.loads((PUBLIC / "analysis-amendment.json").read_text())
    assert all(sha(REPO / p) == v for p, v in amendment["source_sha256"].items())
    costs = reconcile()
    frozen.native.main = audit_debate_failures.main
    frozen.export()
    source = PUBLIC / "results.json"
    shutil.copyfile(source, OUT / "frozen-export-before-cost-adjustment.json")
    result = json.loads(source.read_text())
    groups = defaultdict(list)
    adjustments = costs["run_adjustments_usd"]
    for row in result["rows"]:
        extra = adjustments.get(row["run_key"], 0)
        row["original_cost_upper_usd"] = row["cost_upper_usd"]
        row["cache_write_correction_usd"] = extra
        row["cost_upper_usd"] = round(row["cost_upper_usd"] + extra, 6)
        row["cost_known_usd"] = round(row["cost_known_usd"] + extra, 6)
        groups[row["decision_date"], row["treatment"], row["trial"]].append(row)
    accounts = {}
    for account in result["portfolios"]:
        group = groups[account["decision_date"], account["treatment"], account["trial"]]
        account["model_expense_upper_usd"] = sum(r["cost_upper_usd"] for r in group)
        if account["status"] == "matured":
            account["economic_pnl"] = account["trading_pnl"] - account["model_expense_upper_usd"]
        accounts[account["decision_date"], account["treatment"], account["trial"], account["bps_per_side"]] = account
    for selected in result["examples"]:
        account = accounts[selected["decision_date"], selected["treatment"], selected["trial"], selected["bps_per_side"]]
        selected.update(account)
    for summary in result["summaries"]:
        rows = [r for r in result["rows"] if r["treatment"] == summary["treatment"]]
        ps = [p for p in result["portfolios"] if p["treatment"] == summary["treatment"] and p["status"] == "matured" and p["bps_per_side"] == 10]
        summary["total_model_cost_usd"] = sum(r["cost_upper_usd"] for r in rows)
        summary["total_model_cost_known_usd"] = sum(r["cost_known_usd"] for r in rows)
        summary["unknown_api_calls"] = sum(r["unknown_calls"] for r in rows)
        summary["mean_economic_pnl"] = mean(p["economic_pnl"] for p in ps)
    result["cost_accounting"] = {"pricing_reconciliation_sha256": sha(PUBLIC / "pricing-reconciliation.json"),
                                 "basis": costs["cost_basis"], "original_predictions_unchanged": True,
                                 "main_cache_write_correction_usd": sum(r["cache_write_correction_usd"] for r in result["rows"]),
                                 "earlier_cost_figures": "Preserved historical exports use their original estimates; this study and current ledger include the correction."}
    result["analysis_amendment_sha256"] = sha(PUBLIC / "analysis-amendment.json")
    # Primary contrasts are bit-for-bit identical to the frozen export.
    original = json.loads((OUT / "frozen-export-before-cost-adjustment.json").read_text())
    assert result["paired_contrasts"] == original["paired_contrasts"]
    assert result["repeatability"] == original["repeatability"]
    source.write_bytes(canonical(result))
    for name, values in (("decisions", result["rows"]), ("accounts", result["portfolios"]), ("summaries", result["summaries"]), ("repeatability", result["repeatability"]), ("contrasts", result["paired_contrasts"])):
        with (PUBLIC / (name + ".csv")).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(values[0]))
            writer.writeheader()
            writer.writerows({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in row.items()} for row in values)
    print(json.dumps({"executions": result["executions"], "summaries": result["summaries"],
                      "contrasts": result["paired_contrasts"], "budget": result["budget"],
                      "accounting": result["cost_accounting"]}, indent=2))


if __name__ == "__main__":
    finalize()

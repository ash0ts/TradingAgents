"""Public verification receipt, generated only after the full hosted readback."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from tradingagents.lab.evidence import canonical

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "studies/execution-contract-v2"
OUT = ROOT / "lab-runs/election-contract-v2"


def verify():
    result = json.loads((PUBLIC / "results.json").read_text())
    protocol = json.loads((PUBLIC / "protocol.json").read_text())
    audit = json.loads((OUT / "hosted-audit.json").read_text())
    rows = result["rows"]
    paths = sorted((OUT / "campaign").rglob("prediction.json"))
    private = [json.loads(p.read_text()) for p in paths]
    reviews = json.loads((PUBLIC / "reviews.json").read_text())["records"]
    assert len(reviews) == 30
    assert len({(r["case_id"], r["treatment"], r["trial"]) for r in reviews}) == 30
    assert {r["source_prediction_sha256"] for r in reviews} <= {hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    assert len(rows) == len(private) == audit["conversations"] == 360
    assert audit["all_evaluation_links_verified"] and audit["all_usage_reconciled"] and audit["all_model_requests_have_mandate"]
    assert len({r["conversation_id"] for r in private}) == 360
    assert {r["conversation_id"] for r in private} == {r["conversation_id"] for r in audit["rows"]}
    assert {r["source_prediction_sha256"] for r in rows} == {hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    for name, digest in protocol["source_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    for name, field in (("manifest.json", "evidence_manifest_sha256"), ("outcomes.json", "outcomes_sha256")):
        assert hashlib.sha256((ROOT / "lab-data/election-v1" / name).read_bytes()).hexdigest() == protocol[field]
    for r in rows:
        for horizon, score in r["scores_by_horizon"].items():
            if horizon != "5":
                assert score["directional_correct"] is None and score["signed_excess_return"] is None
        if r["cohort"] == "midterms-2026":
            assert r["scores"]["outcome_status"] == "pending"
            assert r["scores"]["directional_correct"] is None
    assert len(result["portfolios"]) == 240
    for account in result["portfolios"]:
        if account["status"] == "pending":
            assert account["trading_pnl"] is None and account["return"] is None
    assert result["budget"]["cost_upper_usd"] <= 250 and result["new_campaign_cost_upper_usd"] <= 30
    report = {"campaign_id": result["campaign_id"], "executions": len(rows),
              "qualification_executions": len(list((OUT / "qualification").rglob("prediction.json"))),
              "protocol_sha256": result["protocol_sha256"],
              "result_sha256": hashlib.sha256((PUBLIC / "results.json").read_bytes()).hexdigest(),
              "actor_code_revisions": sorted({r["code_revision"] for r in rows}),
              "source_hashes_match_frozen_protocol": True,
              "evidence_and_outcome_hashes_match_frozen_protocol": True,
              "selected_assistant_reviews": len(reviews),
              "status_counts": dict(Counter(r["status"] for r in rows)),
              "contract_counts": dict(Counter(r["contract_status"] for r in rows)),
              "hosted": {k: v for k, v in audit.items() if k != "rows"},
              "unique_conversations": 360, "all_prediction_hashes_match": True,
              "scores_and_original_portfolios_recomputed_by_exporter": True,
              "nonmandate_horizons_unscored": True, "2026_five_session_outcomes_pending": True,
              "portfolio_counts": dict(Counter(p["status"] for p in result["portfolios"])),
              "budget": result["budget"], "new_model_cost_upper_usd_including_qualification": result["new_campaign_cost_upper_usd"],
              "original_controls_unchanged_sha256": result["baseline_controls"]["unchanged_payload_sha256"],
              "semantic_boundary": "Typed validation and numeric reconciliation do not certify factual or investment quality. See 30 selected Codex assistant reviews."}
    (PUBLIC / "verification.json").write_bytes(canonical(report))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    verify()

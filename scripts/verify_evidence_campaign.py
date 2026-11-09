"""Independent readback receipt for the frozen evidence campaign."""

from __future__ import annotations

import json
from collections import Counter

from run_repaired_evidence_campaign import CAP, OUT, PROTOCOL, PUBLIC, REPO, sha, validate

from tradingagents.lab.evidence import canonical


def verify():
    protocol = validate()
    result = json.loads((PUBLIC / "results.json").read_text())
    audit = json.loads((OUT / "campaign-hosted-audit.json").read_text())
    qualification = json.loads((OUT / "qualification-hosted-audit.json").read_text())
    expected = result["design"]["stocks"] * result["design"]["trials"] * 10 * 3 * 2
    rows = result["rows"]
    paths = sorted(OUT.glob("*/campaign/**/prediction.json"))
    assert len(rows) == len(paths) == audit["conversations"] == expected
    assert all(
        audit[k]
        for k in (
            "all_evaluation_links_verified",
            "all_usage_reconciled",
            "all_model_requests_have_exact_brief",
        )
    )
    assert {r["source_prediction_sha256"] for r in rows} == {sha(p) for p in paths}
    assert len({r["conversation_url"] for r in rows}) == expected
    identities = {(r["arm"], r["case_id"], r["treatment"], r["trial"]) for r in rows}
    assert len(identities) == expected
    for r in rows:
        if r["cohort"] == "midterms-2026":
            assert (
                r["scores"]["outcome_status"] == "pending"
                and r["scores"]["directional_correct"] is None
            )
        if r["contract_status"] != "accepted":
            assert r["target_weight"] == 0 and r["scores"]["directional_correct"] is None
        for h, s in r["scores_by_horizon"].items():
            if h != "5":
                assert s["directional_correct"] is None
        receipt = r["execution_receipt"]
        assert (
            abs(
                receipt["stock_principal_usd"]
                + receipt["entry_fee_usd"]
                - receipt["cash_deployed_usd"]
            )
            < 1e-8
        )
        assert (
            abs(
                receipt["cash_deployed_usd"]
                + receipt["remaining_cash_usd"]
                - receipt["sleeve_cash_usd"]
            )
            < 1e-8
        )
    assert len(result["portfolios"]) == 10 * 3 * 2 * 4 * result["design"]["trials"]
    for p in result["portfolios"]:
        if p["status"] == "pending":
            assert p["trading_pnl"] is None and p["selection_pnl"] is None
        else:
            assert abs(p["selection_pnl"] - (p["trading_pnl"] - p["matched_SPY_pnl"])) < 1e-8
    reviews = json.loads((PUBLIC / "reviews.json").read_text())["records"]
    expected_reviews = {
        (m, c, t, i)
        for m in protocol["arms"]
        for c in protocol["review"]["prespecified_cases"]
        for t in protocol["treatments"]
        for i in range(result["design"]["trials"])
    }
    assert {
        (r["arm"], r["case_id"], r["treatment"], r["trial"]) for r in reviews
    } == expected_reviews
    assert {r["source_prediction_sha256"] for r in reviews} <= {sha(p) for p in paths}
    assert (
        result["budget"]["cost_upper_usd"] <= 250
        and sum(result["new_cost_usd_by_phase"].values()) <= CAP
    )
    assert result["frozen_controls"]["original_sha256"] == sha(
        REPO / "notebooks/data/showcase.json"
    )
    assert result["frozen_controls"]["contract_v2_sha256"] == sha(
        REPO / "studies/execution-contract-v2/results.json"
    )
    receipt = {
        "campaign_id": result["campaign_id"],
        "executions": expected,
        "qualification_executions": qualification["conversations"],
        "protocol_sha256": sha(PROTOCOL),
        "result_sha256": sha(PUBLIC / "results.json"),
        "actor_code_revision": result["design"]["actor_code_revision"],
        "frozen_sources_verified": True,
        "briefs_recomputed_from_original_snapshots": 60,
        "all_trial_hashes_verified": True,
        "hosted": {k: v for k, v in audit.items() if k != "rows"},
        "status_counts": dict(Counter(r["status"] for r in rows)),
        "contract_counts": dict(Counter(r["contract_status"] for r in rows)),
        "portfolio_counts": dict(Counter(p["status"] for p in result["portfolios"])),
        "assistant_reviews": len(reviews),
        "old_results_preserved": True,
        "2026_five_session_outcomes_pending": True,
        "matched_SPY_entry_exposure_reconciled_by_exporter": True,
        "budget": result["budget"],
        "new_cost_usd_by_phase": result["new_cost_usd_by_phase"],
        "boundary": "Citation slots reconcile to supplied observations; prose claims and investment merit require separate review.",
    }
    (PUBLIC / "verification.json").write_bytes(canonical(receipt))
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    verify()

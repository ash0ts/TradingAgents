import json
from pathlib import Path

from articles.build_internals import observe, summarize


def test_conditional_qualifier_remains_candidate_and_pending_is_not_zero():
    private = "SOURCE_MUST_NOT_BE_EXPORTED"
    row = {
        "case_id": "case",
        "treatment": "default-committee",
        "trial": 0,
        "cohort": "2026",
        "ticker": "UNH",
        "rating": "Overweight",
        "state": {"investment_plan": "**Recommendation**: Overweight", "private": private},
        "report": "Only if a breakout holds, add gradually.\n**Time Horizon**: not provided",
        "events": [{"kind": "tool_end", "result": "DATA_UNAVAILABLE " + private}],
        "scores": {"outcome_status": "pending", "signed_excess_return": None},
        "evidence_sha256": "digest",
        "code_revision": "revision",
    }
    record = observe(row, "original-file-hash", {"trading_pnl": "", "target_weight": "0.75"})
    assert record["condition_phrase_candidate"]
    assert record["rating_changed"] is False
    assert record["sleeve_pnl_usd"] is None
    assert record["signed_excess_return"] is None
    assert record["horizon_explicitly_not_provided"]
    assert "failure" not in record
    assert private not in json.dumps(record)


def test_handoff_denominator_excludes_single_analyst_without_fabricating_a_stage():
    root = Path(__file__).resolve().parents[2]
    rows = json.loads((root / "articles/internals/observations.json").read_text())
    scores = json.loads((root / "notebooks/data/showcase.json").read_text())["rows"]
    by_key = {(r["case_id"], r["treatment"], r["trial"]): r for r in scores}
    for row in rows:
        original = by_key[(row["case_id"], row["treatment"], row["trial"])]
        assert row["final_rating"] == original["rating"]
        assert row["evidence_sha256"] == original["evidence_sha256"]
        assert row["signed_excess_return"] == original["scores"]["signed_excess_return"]
    result = {r["treatment"]: r for r in summarize(rows)}
    assert result["single-luna"]["comparable_research_final_ratings"] == 0
    assert sum(r["comparable_research_final_ratings"] for r in result.values()) == 240
    assert sum(r["runs"] for r in result.values()) == 360
    assert sum(r["matured_runs"] for r in result.values()) == 288

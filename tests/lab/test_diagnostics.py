import pytest

from tradingagents.lab.diagnostics import export_regressions, inspect_behavior, showcase_examples


def test_candidates_separate_behavior_from_outcomes():
    bundle = {"case": {"ticker": "MSFT", "missing_sources": ["reddit"]}, "prices": {"MSFT": [{"date": "2024-11-04", "close": 100}]}}
    row = {"report": "Reddit is bullish. The current close is $120.\n**Rating**: Buy\n**Rating**: Sell", "rating": "Sell", "events": []}
    result = inspect_behavior(row, bundle)
    tags = {f["tag"] for f in result["findings"]}
    assert {"unavailable-evidence-as-fact", "unsupported-current-price", "contradictory-recommendations"} <= tags
    assert not result["financial_outcome_used_for_behavior"]
    assert all(f["status"] == "review-candidate" for f in result["findings"])
    row["report"] = "Reddit is unavailable; I cannot call it bullish."
    assert "unavailable-evidence-as-fact" not in {f["tag"] for f in inspect_behavior(row, bundle)["findings"]}


def test_regressions_require_review_and_preserve_test_boundary(tmp_path):
    row = {"run_key": "r", "case_id": "case", "treatment": "agent", "evidence_sha256": "hash", "conversation_url": "url", "code_revision": "rev"}
    with pytest.raises(ValueError, match="Review must"):
        export_regressions([row], [{"run_key": "r"}], tmp_path / "bad.json")
    review = {"run_key": "r", "reviewer": "reviewer", "reviewed_at": "2026-11-06", "label": "confirmed-failure", "rationale": "Unavailable evidence asserted", "evidence_locator": "report"}
    result = export_regressions([row], [review], tmp_path / "regression.json")
    assert result["records"][0]["split"] == "study-discovered-regression-not-untouched-test"


def test_seeded_selection_includes_extremes():
    rows = [{"run_key": str(i), "scores": {"signed_excess_return": i}} for i in range(5)]
    assert showcase_examples(rows) == showcase_examples(list(reversed(rows)))
    assert showcase_examples(rows)["strongest"] == "4"
    assert showcase_examples(rows)["weakest"] == "0"

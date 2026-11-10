from concurrent.futures import ThreadPoolExecutor

import pytest

from tradingagents.lab.budget import BudgetExceeded, Ledger, choose_design
from tradingagents.lab.scoring import paired_blocks, score


def test_reservations_atomic_and_unknown_charges_not_released(tmp_path):
    ledger = Ledger(tmp_path / "ledger.sqlite")
    def attempt(i):
        try:
            ledger.reserve(str(i), "run", "qualification", "gpt-6-luna", 15_000_000)
            return True
        except BudgetExceeded:
            return False
    with ThreadPoolExecutor(2) as pool:
        assert sum(pool.map(attempt, [0, 1])) == 1
    assert ledger.totals()["cost_upper_usd"] == 15
    assert ledger.totals()["unknown_calls"] == 1


def test_settle_once_and_design():
    costs = dict.fromkeys(["default-committee", "luna-committee", "single-luna"], 0.1)
    assert choose_design(costs)["trials"] == 2
    with pytest.raises(BudgetExceeded):
        choose_design(dict.fromkeys(costs, 100))


def test_pending_and_abstentions_not_counted_as_losses():
    pending = {k: {"status": "pending", "return": None} for k in ["stock", "benchmark"]}
    assert score({"status": "success", "rating": "Buy"}, pending)["signed_excess_return"] is None
    matured = {"stock": {"status": "matured", "return": .1}, "benchmark": {"status": "matured", "return": .03}}
    result = score({"status": "success", "rating": "Sell"}, matured)
    assert result["signed_excess_return"] == pytest.approx(-.07)
    assert not result["directional_correct"]
    assert score({"status": "success", "rating": "Hold"}, matured)["abstained"]


def test_trials_are_not_independent_observations():
    rows = [{"case_id": "case", "cohort": "cohort", "treatment": t, "scores": {"signed_excess_return": v}}
            for t, v in [("a", .1), ("a", .3), ("b", .1), ("b", .1)]]
    result = paired_blocks(rows, "a", "b")
    assert result["pairs"] == 1
    assert result["mean"] == pytest.approx(.1)


def test_cache_write_pricing_and_settlement_are_exactly_once(tmp_path):
    from tradingagents.lab.budget import cost_micros
    # 300 regular + 200 cache-read + 500 cache-write input tokens, 100 output.
    assert cost_micros("gpt-6-luna", 1000, 100, 200, 500) == 145
    assert cost_micros("gpt-6-sol", 1000, 100, 200, 500) == 2890
    # Above 272K input tokens, input prices double and output prices rise 50%.
    assert cost_micros("gpt-6-luna", 300000, 500, 50000, 200000) == 61375
    with pytest.raises(ValueError, match="token categories"):
        cost_micros("gpt-6-luna", 100, 1, 60, 50)
    ledger = Ledger(tmp_path / "ledger.sqlite")
    ledger.reserve("call", "case", "campaign", "gpt-6-luna", 1000)
    usage = {"input_tokens": 1000, "output_tokens": 100,
             "input_token_details": {"cache_read": 200, "cache_creation": 500}}
    ledger.settle("call", usage)
    ledger.settle("call", usage)
    assert ledger.totals()["cost_known_usd"] == 0.000145
    assert ledger.totals()["calls"] == 1


def test_failed_actor_persists_partial_callback_events(tmp_path, monkeypatch):
    import json

    from tradingagents.lab import runner
    from tradingagents.lab.evidence import EvidenceStore

    case = {"case_id": "fixture", "ticker": "AAPL", "decision_date": "2024-11-04", "cohort": "fixture"}
    root = tmp_path / "evidence"
    key = EvidenceStore(root).bundle(case, [], {})
    (root / "manifest.json").write_text(json.dumps({"version": "fixture", "cases": {"fixture": key}}))
    pending = {k: {"status": "pending", "return": None} for k in ["stock", "benchmark"]}
    (root / "outcomes.json").write_text(json.dumps({"cases": {"fixture": {"5": pending}}}))
    monkeypatch.delenv("TRADINGAGENTS_MODELS_ENV", raising=False)
    monkeypatch.setenv("TRADINGAGENTS_LAB_CODE_REVISION", "fixture")
    event = {"kind": "error", "run_id": "fixture-call", "error": "provider unavailable"}

    def fail(config, data, budget):
        config["forge_event_sink"].append(event)
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(runner, "single_analyst", fail)
    result = runner.run_one(root, tmp_path / "runs", "fixture", "single-luna", publish=False)
    persisted = json.loads((tmp_path / "runs/campaign/fixture/single-luna/0/prediction.json").read_text())
    assert result["status"] == persisted["status"] == "failed"
    assert result["events"] == persisted["events"] == [event]
    assert persisted["calls"] == 0  # Synthetic failure; no paid dispatch.

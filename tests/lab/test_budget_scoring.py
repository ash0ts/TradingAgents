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

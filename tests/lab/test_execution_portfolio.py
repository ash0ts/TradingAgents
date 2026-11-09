from copy import deepcopy

import pytest

from tradingagents.lab.execution import make_mandate
from tradingagents.lab.portfolio import simulate


@pytest.fixture
def inputs():
    sessions = [f"2024-01-{i:02d}" for i in range(1, 10)]
    prices = {"UNH": [{"date": d, "close": 100, "split": 1, "dividend": 0} for d in sessions]}
    mandate = make_mandate("UNH", sessions[0], sleeves=1, sessions=sessions).model_dump()
    decision = {"rating": "Overweight", "executive_summary": "Allocate 75%.",
                "investment_thesis": "Synthetic regression fixture.", "time_horizon": "5 trading sessions",
                "mandate": mandate, "order": {"kind": "next_close", "target_weight": .75,
                "conditions": [], "reason": "Fixed-horizon instruction"}}
    predictions = [{"ticker": "UNH", "treatment": "test", "status": "success", "rating": "Overweight",
                    "execution_mandate": deepcopy(mandate), "execution_decision": decision}]
    return sessions, prices, predictions


def test_conditional_order_cannot_lose_cash_or_pay_fees(inputs):
    sessions, prices, predictions = inputs
    for p in prices["UNH"][2:]:
        p["close"] = 50
    predictions[0]["execution_decision"]["order"]["conditions"] = ["Only after confirmation above the zone"]
    predictions[0]["execution_check"] = {"eligible": True, "target_weight": .75}
    result = simulate(sessions[0], predictions, prices, sessions)
    assert result["execution_checks"]["UNH"]["status"] == "blocked_condition"
    assert result["final_cash"] == 100000
    assert result["transaction_costs"] == 0
    assert result["transactions"] == []
    assert result["exposure_at_entry"] == 0


def test_accepted_order_has_exact_dates_size_fees_and_corporate_actions(inputs):
    sessions, prices, predictions = inputs
    for p in prices["UNH"][2:]:
        p["close"] = 50
    prices["UNH"][2].update(split=2, dividend=1)
    result = simulate(sessions[0], predictions, prices, sessions)
    shares = 75000 / 1.001 / 100
    dividends = shares * 2
    fees = shares * 100 * .001 * 2
    assert result["final_cash"] == pytest.approx(100000 + dividends - fees)
    assert result["transactions"][0]["date"] == sessions[1]
    assert result["transactions"][-1]["date"] == sessions[6]
    assert result["positions"][0]["target_weight"] == .75
    assert result["positions"][0]["shares"] == 0


def test_missing_typed_order_does_not_fall_back_to_rating(inputs):
    sessions, prices, predictions = inputs
    del predictions[0]["execution_decision"]
    result = simulate(sessions[0], predictions, prices, sessions)
    assert result["final_cash"] == 100000
    assert result["execution_checks"]["UNH"]["status"] == "invalid_contract"


@pytest.mark.parametrize("override", [{"entry_delay": 2}, {"horizon": 20}, {"target_weights": {"UNH": 1}}])
def test_scenario_override_cannot_bypass_contract(inputs, override):
    sessions, prices, predictions = inputs
    with pytest.raises(ValueError, match="Cannot override"):
        simulate(sessions[0], predictions, prices, sessions, **override)


def test_pending_contract_is_not_given_a_zero_return(inputs):
    sessions, prices, predictions = inputs
    result = simulate(sessions[0], predictions, prices, sessions, freeze=sessions[3])
    assert result["status"] == "pending"
    assert result["return"] is None
    assert result["execution_checks"]["UNH"]["eligible"]

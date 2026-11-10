from copy import deepcopy
from unittest.mock import Mock, patch

import pytest

from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.dataflows.config import run_config
from tradingagents.graph.propagation import Propagator
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.lab.budget import BudgetExceeded, Ledger
from tradingagents.lab.execution import (
    ExecutionDecision,
    assess_execution,
    make_mandate,
    score_execution,
)


@pytest.fixture
def decision():
    mandate = make_mandate("UNH", "2022-11-07", sessions=[
        "2022-11-07", "2022-11-08", "2022-11-09", "2022-11-10",
        "2022-11-11", "2022-11-14", "2022-11-15",
    ]).model_dump()
    return {
        "rating": "Overweight", "executive_summary": "Allocate 75% at the stated close.",
        "investment_thesis": "Illustrative regression fixture, not a new model response.",
        "price_target": None, "time_horizon": "5 trading sessions", "mandate": mandate,
        "order": {"kind": "next_close", "target_weight": .75, "conditions": [], "reason": "Fixed horizon."},
    }


def test_buy_if_never_turns_into_buy_now(decision):
    # Reproduces the discovered handoff, without inferring an executable trigger.
    decision["order"]["conditions"] = ["Add only after confirmation above the zone"]
    result = assess_execution(decision, decision["mandate"], "Overweight")
    assert result["status"] == "blocked_condition"
    assert result["target_weight"] == 0
    assert not result["eligible"]
    decision["order"].update(kind="conditional", conditions=[])
    assert assess_execution(decision, decision["mandate"])["target_weight"] == 0


@pytest.mark.parametrize(("field", "bad"), [
    ("decision_date", "2026-11-09"), ("horizon_sessions", 20),
    ("entry_date", "2022-11-07"), ("exit_date", "2022-11-09"),
    ("account_basis", "existing_position"), ("benchmark", "QQQ"),
    ("ticker", "AAPL"), ("sleeve_cash_usd", 100000),
])
def test_changed_date_horizon_or_book_is_rejected(decision, field, bad):
    expected = deepcopy(decision["mandate"])
    decision["mandate"][field] = bad
    result = assess_execution(decision, expected)
    assert result["status"] == "invalid_contract"
    assert result["reasons"] == [field]
    assert result["target_weight"] == 0


def test_missing_contract_and_inconsistent_weights_are_not_salvaged(decision):
    assert assess_execution(None, decision["mandate"])["status"] == "invalid_contract"
    decision["order"]["target_weight"] = 1
    assert assess_execution(decision, decision["mandate"])["status"] == "invalid_contract"
    decision["order"].update(kind="abstain", target_weight=0, reason="News unavailable")
    assert assess_execution(decision, decision["mandate"])["status"] == "abstained"


def test_wrong_contract_cannot_earn_a_directional_score(decision):
    row = {"status": "success", "rating": "Overweight", "execution_decision": decision,
           "execution_mandate": deepcopy(decision["mandate"])}
    outcome = {"stock": {"status": "matured", "return": .1},
               "benchmark": {"status": "matured", "return": .02}}
    assert score_execution(row, outcome, 5)["signed_excess_return"] == pytest.approx(.08)
    assert score_execution(row, outcome, 20)["signed_excess_return"] is None
    decision["mandate"]["decision_date"] = "2026-11-09"
    result = score_execution(row, outcome, 5)
    assert result["signed_excess_return"] is None
    assert result["contract_rejected"]
    assert not result["explicit_abstention"]


def test_shared_context_reaches_graph_and_typed_decision_survives_pm(decision):
    model = Mock()
    model.with_structured_output.return_value.invoke.return_value = ExecutionDecision.model_validate(decision)
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.config = {"evaluation_mandate": decision["mandate"]}
    with patch("tradingagents.graph.trading_graph.resolve_instrument_identity", return_value={}):
        context = graph.resolve_instrument_context("UNH", trade_date="2022-11-07")
    assert '"decision_date":"2022-11-07"' in context
    assert "zero existing stock holdings" in context
    state = Propagator().create_initial_state("UNH", "2022-11-07", instrument_context=context)
    state.update(investment_plan="Consider a modest conditional position", trader_investment_plan="Wait for confirmation")
    with run_config(graph.config):
        result = create_portfolio_manager(model)(state)
    assert result["execution_decision"]["order"]["target_weight"] == .75
    assert '"horizon_sessions": 5' in result["final_trade_decision"]
    assert context in model.with_structured_output.return_value.invoke.call_args.args[0]
    model.invoke.assert_not_called()


def test_contract_errors_do_not_fall_back_to_an_untyped_paid_call(decision):
    model = Mock()
    model.with_structured_output.return_value.invoke.side_effect = ValueError("bad schema")
    state = Propagator().create_initial_state("UNH", "2022-11-07")
    state.update(investment_plan="x", trader_investment_plan="y")
    with run_config({"evaluation_mandate": decision["mandate"]}), pytest.raises(ValueError, match="bad schema"):
        create_portfolio_manager(model)(state)
    model.invoke.assert_not_called()


def test_new_campaign_reservations_share_old_budget_and_keep_unknowns(tmp_path):
    path = tmp_path / "budget.sqlite"
    old = Ledger(path)
    old.reserve("infrastructure", "old", "campaign", "infra", 150_000_000)
    new = Ledger(path, campaign_prefix="v2/", campaign_cap_usd=2)
    new.reserve("one", "v2/case", "campaign", "gpt-6-luna", 1_500_000)
    new.settle("one", None)
    with pytest.raises(BudgetExceeded, match="Campaign-specific"):
        new.reserve("two", "v2/other", "campaign", "gpt-6-luna", 600_000)
    assert old.totals()["cost_upper_usd"] == 151.5

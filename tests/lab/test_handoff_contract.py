from copy import deepcopy
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.schemas import TraderProposal
from tradingagents.agents.trader.trader import create_trader
from tradingagents.dataflows.config import run_config
from tradingagents.graph.propagation import Propagator
from tradingagents.lab.execution import ExecutionDecision, make_mandate
from tradingagents.lab.handoff import ContractTraderProposal, render_contract_proposal


@pytest.fixture
def mandate():
    return make_mandate(
        "UNH",
        "2023-09-13",
        sessions=[
            "2023-09-13",
            "2023-09-14",
            "2023-09-15",
            "2023-09-18",
            "2023-09-19",
            "2023-09-20",
            "2023-09-21",
        ],
    ).model_dump()


@pytest.fixture
def proposal(mandate):
    return {
        "action": "Underweight",
        "reasoning": "Fixture: mixed evidence.",
        "mandate": mandate,
        "order": {
            "kind": "next_close",
            "target_weight": 0.25,
            "conditions": [],
            "reason": "Fixture.",
        },
    }


def test_five_rating_proposal_rejects_legacy_sell_quarter_allocation(proposal):
    valid = ContractTraderProposal.model_validate(proposal)
    assert valid.action.value == "Underweight" and valid.order.target_weight == 0.25
    wrong = deepcopy(proposal)
    wrong["action"] = "Sell"
    with pytest.raises(ValidationError, match="action and new allocation disagree"):
        ContractTraderProposal.model_validate(wrong)
    assert "**Action**: Underweight" in render_contract_proposal(valid)


def test_proposed_conditions_survive_the_handoff(proposal):
    proposal["order"].update(kind="conditional", conditions=["Only after verified confirmation"])
    rendered = render_contract_proposal(ContractTraderProposal.model_validate(proposal))
    assert "Only after verified confirmation" in rendered
    assert "subject to final review" in rendered


def test_actual_trader_uses_five_buckets_and_no_paid_freetext_fallback(proposal, mandate):
    state = Propagator().create_initial_state(
        "UNH", "2023-09-13", instrument_context="FROZEN BRIEF"
    )
    state.update(investment_plan="Underweight, 25% new allocation", market_report="Fixture report")
    llm = Mock()
    llm.with_structured_output.return_value.invoke.return_value = (
        ContractTraderProposal.model_validate(proposal)
    )
    with run_config({"evaluation_mandate": mandate}):
        output = create_trader(llm)(state)
    assert llm.with_structured_output.call_args.args[0] is ContractTraderProposal
    messages = llm.with_structured_output.return_value.invoke.call_args.args[0]
    text = "\n".join(m["content"] for m in messages)
    assert "Underweight=25%" in text and "Sell=0%" in text and "FROZEN BRIEF" in text
    assert "Underweight is a Sell" not in text
    assert "**Action**: Underweight" in output["trader_investment_plan"]
    llm.invoke.assert_not_called()
    llm.with_structured_output.return_value.invoke.return_value = None
    with (
        run_config({"evaluation_mandate": mandate}),
        pytest.raises(ValueError, match="contracted proposal"),
    ):
        create_trader(llm)(state)
    llm.invoke.assert_not_called()


def test_ordinary_trader_keeps_original_schema_and_mapping():
    llm = Mock()
    with run_config({}):
        create_trader(llm)
    assert llm.with_structured_output.call_args.args[0] is TraderProposal


def test_final_manager_has_no_conflicting_existing_holding_scale(mandate):
    state = Propagator().create_initial_state(
        "UNH", "2023-09-13", instrument_context="FROZEN BRIEF"
    )
    state.update(
        investment_plan="Fixture", trader_investment_plan="Underweight: 25% new allocation"
    )
    decision = ExecutionDecision.model_validate(
        {
            "rating": "Underweight",
            "executive_summary": "Allocate 25%.",
            "investment_thesis": "Fixture.",
            "price_target": None,
            "time_horizon": "5 trading sessions",
            "mandate": mandate,
            "order": {
                "kind": "next_close",
                "target_weight": 0.25,
                "conditions": [],
                "reason": "Fixture.",
            },
        }
    )
    llm = Mock()
    llm.with_structured_output.return_value.invoke.return_value = decision
    with run_config({"evaluation_mandate": mandate}):
        create_portfolio_manager(llm)(state)
    prompt = llm.with_structured_output.return_value.invoke.call_args.args[0]
    assert "Underweight=25%" in prompt
    assert "Maintain current position, no action needed" not in prompt
    assert "Reduce exposure, take partial profits" not in prompt

"""Explicit retrospective decision contracts; unsupported orders never become buys."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tradingagents.agents.schemas import PortfolioDecision, render_pm_decision
from tradingagents.lab.protocol import calendar_sessions

VERSION = "next-close-v2"
WEIGHTS = {"Buy": 1.0, "Overweight": .75, "Hold": .5, "Underweight": .25, "Sell": 0.0}


class Mandate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    ticker: str
    decision_date: str
    entry_date: str
    exit_date: str
    horizon_sessions: int
    benchmark: str
    account_basis: str
    sleeve_cash_usd: float


class OrderIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    kind: Literal["next_close", "abstain", "conditional"] = Field(
        description="next_close executes unconditionally at the specified entry close; abstain holds cash. Conditional orders are unsupported and held in cash, never converted into next_close."
    )
    target_weight: float = Field(ge=0, le=1, description="Fraction of this fresh cash sleeve, including entry fees. Must match the rating bucket for next_close; use zero for abstain.")
    conditions: list[str] = Field(description="Every prerequisite for acting, including price confirmation, new evidence, staged entry or a required stop. Empty only for an unconditional next_close instruction. Do not hide conditions in prose.")
    reason: str = Field(min_length=1, description="Why this order is appropriate or why you abstain. State missing evidence explicitly.")


class ExecutionDecision(PortfolioDecision):
    """Filled in the final actor call, without a later extraction model."""

    time_horizon: Literal["5 trading sessions"]
    mandate: Mandate = Field(description="The exact decision mandate you answered, copied from the supplied evaluation mandate. Never substitute the current date or assume existing holdings.")
    order: OrderIntent


def make_mandate(ticker, decision_date, *, sleeves=6, sessions=None):
    sessions = sessions if sessions is not None else calendar_sessions()
    i = sessions.index(decision_date)
    if sleeves <= 0:
        raise ValueError("Sleeve count must be positive")
    return Mandate(ticker=ticker, decision_date=decision_date, entry_date=sessions[i + 1],
                   exit_date=sessions[i + 6], horizon_sessions=5, benchmark="SPY",
                   account_basis="fresh_cash_sleeve", sleeve_cash_usd=100_000 / sleeves)


def mandate_prompt(mandate):
    mandate = Mandate.model_validate(mandate)
    return (
        "\n\nEVALUATION MANDATE (applies to every role and takes precedence over generic investment guidance):\n"
        + mandate.model_dump_json() + "\n"
        f"You are deciding as of {mandate.decision_date} at 23:59:59 America/New_York, not advising someone trading on the actual execution date. "
        "Use only frozen evidence available by that cutoff. Missing historical news remains missing; do not retrieve or infer later information. "
        "This is a fresh, all-cash sleeve with zero existing stock holdings. No position is available to trim. "
        "Recommend this stock relative to SPY for exactly five trading sessions from the stated entry close to the stated exit close. "
        "The rating denotes a NEW allocation of this sleeve: Buy=100%, Overweight=75%, Hold=50%, Underweight=25%, Sell=0%. "
        "Here Hold is a 50% allocation, not an instruction to retain an unknown existing position. "
        "The only supported execution is one unconditional next-session-close allocation, then liquidation at the specified close. "
        "Costs are 10 basis points on each side; the allocation includes entry fees. No leverage, shorting, interest, staged entries, price-contingent orders or stop-loss orders. "
        "If your recommendation requires confirmation, new information, a stop, or another unsupported condition, explicitly abstain and leave this sleeve in cash. "
        "The final actor must preserve any such conditions in order.conditions, never discard them to make an order executable. "
        "Analysis may discuss uncertainty and alternatives, but the final order and action plan must agree."
    )


def render_execution_decision(decision):
    return (render_pm_decision(decision)
            + "\n\n**Decision mandate**\n```json\n" + decision.mandate.model_dump_json(indent=2)
            + "\n```\n\n**Execution instruction**\n```json\n" + decision.order.model_dump_json(indent=2) + "\n```")


def assess_execution(payload, expected, rating=None):
    """Schema/contract checks, not a semantic truth or investment-quality judge."""
    base = {"version": VERSION, "eligible": False, "target_weight": 0.0}
    try:
        decision = ExecutionDecision.model_validate(payload)
        expected = Mandate.model_validate(expected)
    except (ValidationError, TypeError):
        return {**base, "status": "invalid_contract", "reasons": ["missing_or_invalid_structured_decision"]}
    mismatch = [k for k, v in expected.model_dump().items() if decision.mandate.model_dump()[k] != v]
    if rating is not None and rating != decision.rating.value:
        mismatch.append("rating")
    if mismatch:
        return {**base, "status": "invalid_contract", "reasons": mismatch}
    order = decision.order
    if order.kind == "abstain":
        if order.target_weight != 0:
            return {**base, "status": "invalid_contract", "reasons": ["nonzero_abstention"]}
        return {**base, "status": "abstained", "reasons": [order.reason]}
    if order.kind == "conditional" or order.conditions:
        return {**base, "status": "blocked_condition", "reasons": order.conditions or [order.reason]}
    if order.target_weight != WEIGHTS[decision.rating.value]:
        return {**base, "status": "invalid_contract", "reasons": ["rating_weight_mismatch"]}
    return {**base, "status": "accepted", "eligible": True,
            "target_weight": order.target_weight, "reasons": []}


def execution_check(row):
    if row.get("status") != "success":
        return {"version": VERSION, "eligible": False, "target_weight": 0.0,
                "status": "actor_failed", "reasons": ["actor_did_not_complete"]}
    return assess_execution(row.get("execution_decision"), row.get("execution_mandate"), row.get("rating"))


def score_execution(row, outcome, horizon):
    from tradingagents.lab.scoring import score

    check = execution_check(row)
    applicable = int(horizon) == 5
    adapted = dict(row)
    if not check["eligible"] or not applicable:
        adapted["rating"] = None
        adapted["forecast"] = None
    result = score(adapted, outcome)
    # Rejected contracts are distinct from an actor's explicit abstention.
    result.update(contract_status=check["status"], mandate_horizon=applicable,
                  contract_rejected=check["status"] in {"blocked_condition", "invalid_contract"},
                  explicit_abstention=check["status"] == "abstained")
    return result

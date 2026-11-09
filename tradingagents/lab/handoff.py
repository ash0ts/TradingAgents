"""A trader proposal uses the same allocation vocabulary as its final decision."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tradingagents.agents.schemas import PortfolioRating
from tradingagents.lab.execution import WEIGHTS, Mandate, OrderIntent


class ContractTraderProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    action: PortfolioRating = Field(
        description="New allocation rating: Buy=100%, Overweight=75%, Hold=50%, Underweight=25%, Sell=0%. Never collapse five ratings into three actions."
    )
    reasoning: str = Field(
        min_length=1,
        description="The observed evidence for this proposed allocation, its limitations and missing sources. Preserve actual evidence references.",
    )
    mandate: Mandate = Field(description="Copy the supplied historical decision mandate exactly.")
    order: OrderIntent

    @model_validator(mode="after")
    def consistent_allocation(self):
        if (
            self.order.kind == "next_close"
            and self.order.target_weight != WEIGHTS[self.action.value]
        ):
            raise ValueError("Trader action and new allocation disagree")
        if self.order.kind == "abstain" and self.order.target_weight != 0:
            raise ValueError("Trader abstention must hold cash")
        return self


def render_contract_proposal(proposal):
    return (
        f"**Action**: {proposal.action.value}\n\n**Reasoning**: {proposal.reasoning}"
        "\n\n**Proposed mandate**\n```json\n" + proposal.mandate.model_dump_json(indent=2) + "\n```"
        "\n\n**Proposed execution instruction (subject to final review)**\n```json\n"
        + proposal.order.model_dump_json(indent=2)
        + "\n```"
        f"\n\nFINAL TRANSACTION PROPOSAL: **{proposal.action.value.upper()}**"
    )

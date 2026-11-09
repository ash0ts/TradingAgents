"""Trader: turns the Research Manager's investment plan into a concrete transaction proposal."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from tradingagents.agents.context import (
    get_instrument_context_from_state,
    get_language_instruction,
    get_portfolio_context_from_state,
)
from tradingagents.agents.schemas import TraderProposal, render_trader_proposal
from tradingagents.agents.structured import (
    NO_EXTERNAL_TOOLS,
    bind_structured,
    invoke_structured_or_freetext,
)


def create_trader(llm):
    from tradingagents.dataflows.config import get_config
    from tradingagents.lab.handoff import ContractTraderProposal, render_contract_proposal

    contracted = bool(get_config().get("evaluation_mandate"))
    schema = ContractTraderProposal if contracted else TraderProposal
    structured_llm = bind_structured(llm, schema, "Trader")

    def trader_node(state):
        company_name = state["company_of_interest"]
        instrument_context = get_instrument_context_from_state(state)
        investment_plan = state["investment_plan"]
        # The research plan digests the debate but loses exact price structure;
        # give the Trader the technical market report so entry/stop levels are
        # grounded in real ATR / support-resistance / current price (#1167). The
        # report is empty when the user did not select the market analyst, so
        # only offer it (and the grounding instruction) when it has content.
        market_report = (state["market_report"] or "").strip()
        portfolio_context = get_portfolio_context_from_state(state)

        if market_report:
            grounding = (
                "Ground concrete price levels (entry, stop-loss, position sizing) in the technical "
                "market report's price structure -- current price, support/resistance, ATR, and "
                "volatility -- and use the research plan for direction and strategy. "
            )
            report_section = f"Technical Market Report:\n{market_report}\n\n"
        else:
            grounding = ""
            report_section = ""

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a trading agent analyzing market data to make investment decisions. "
                    "Based on your analysis, provide a specific recommendation to buy, sell, or hold. "
                    + grounding
                    # Entry/stop are numeric price fields. Asking for concrete
                    # levels invites a percentage ("15%"), which is not a price
                    # and fails the structured parse (#1288).
                    + "State entry price and stop-loss as absolute price levels in the "
                    "instrument's quote currency (for example 189.5), never a percentage "
                    "or a range; convert a percentage distance to the price level it "
                    "implies, or omit the field if you cannot state a number. "
                    + NO_EXTERNAL_TOOLS
                    + get_language_instruction()
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Here is the research team's investment plan for {company_name}. "
                    f"{instrument_context}\n\n"
                    f"{report_section}"
                    f"{portfolio_context}\n\n"
                    f"Proposed Investment Plan:\n{investment_plan}\n\n"
                    "Make an informed, strategic trading decision.\n\n"
                    "## Output\n\n"
                    "Write these sections, in this order, starting with the action "
                    "on its own line:\n\n"
                    "- **Action**: exactly one of Buy / Hold / Sell. A research "
                    "recommendation of Overweight is a Buy and Underweight is a Sell, "
                    "sized by how strong the case is; conflict alone is not a Hold.\n"
                    "- **Reasoning**: why, against the plan and the price structure\n"
                    "- **Entry Price**, **Stop Loss**, **Position Sizing**: when you can state them"
                ),
            },
        ]

        if contracted:
            # The legacy trader intentionally maps Underweight -> Sell. That is
            # incompatible with the fresh-cash mandate's Sell=0% allocation.
            # Replace its instructions and schema rather than asking the final
            # manager to reconcile mutually inconsistent action definitions.
            messages = [
                {"role": "system", "content": (
                    "Turn the supplied research into a proposal for the exact fresh-cash mandate. "
                    "Use all five allocation ratings: Buy=100%, Overweight=75%, Hold=50%, "
                    "Underweight=25%, Sell=0%. Do not translate Underweight into Sell or "
                    "Overweight into Buy. These are new allocations, not trims of existing positions. "
                    "Copy the mandate exactly. State any required confirmation, stop or staging "
                    "in order.conditions; unsupported conditions must remain visible for the final "
                    "manager, never be silently removed. No unprovided entry price is known. "
                    "The allocation includes entry fees; deterministic accounting is supplied by "
                    "the harness. Preserve evidence references and missing sources. "
                    + NO_EXTERNAL_TOOLS + get_language_instruction()
                )},
                {"role": "user", "content": (
                    f"{instrument_context}\n\n{portfolio_context}\n\n"
                    f"{report_section}Research plan:\n{investment_plan}\n\n"
                    "Return the typed proposal with action, reasoning, mandate and order. "
                    "Your proposal is reviewed by the risk participants and final manager; "
                    "it is not itself an executed trade."
                )},
            ]
            if structured_llm is None:
                raise RuntimeError("The evaluation trader contract requires structured output")
            proposal = structured_llm.invoke(messages)
            if not isinstance(proposal, ContractTraderProposal):
                raise ValueError("The trader did not return a contracted proposal")
            trader_plan = render_contract_proposal(proposal)
        else:
            trader_plan = invoke_structured_or_freetext(
                structured_llm, llm, messages, render_trader_proposal, "Trader",
            )

        return {
            "messages": [AIMessage(content=trader_plan)],
            "trader_investment_plan": trader_plan,
        }

    return trader_node

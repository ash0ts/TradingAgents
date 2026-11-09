"""Post-hoc execution sensitivities of frozen predictions, never new forecasts.

Public unit-account factors permit deterministic replay without redistributing
vendor quotes. No model calls, training, case selection, or network access.
"""

from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean

from tradingagents.lab.portfolio import WEIGHTS

AGENTS = {"default-committee", "luna-committee", "single-luna"}
PROFILES = {
    "original": "Next close, 10 bp per side",
    "one-session-late": "Second close, 10 bp per side; same five-session hold",
    "higher-friction": "Next close, 25 bp per side",
    "half-exposure-cap": "Scale target weights to at most 50% invested",
    "matched-SPY": "SPY at each method's invested fraction; remaining cash",
    "matched-basket": "Equal stock basket at each method's invested fraction",
    "require-archived-news": "Do not open agent positions when frozen news is missing",
}


def aggregate_sleeves(units, weights, initial_cash=100_000.0):
    """Combine independent unit-dollar accounts; fees/dividends scale linearly."""
    if len(units) != len(weights) or not units or initial_cash <= 0:
        raise ValueError("Need nonempty, equally sized sleeves and positive capital")
    if any(not math.isfinite(w) or not 0 <= w <= 1 for w in weights):
        raise ValueError("Weights must be finite fractions in [0, 1]")
    if len({(r["entry_date"], r["exit_date"]) for r in units}) != 1:
        raise ValueError("Sleeve dates differ")
    identity = {
        k: units[0][k] for k in ["decision_date", "entry_date", "exit_date", "bps_per_side"]
    }
    statuses = {r["status"] for r in units}
    if statuses != {"matured"}:
        return {
            **identity,
            "status": "pending" if "pending" in statuses else "missing-prices",
            "trading_pnl": None,
            "return": None,
        }
    dates = [[p["date"] for p in r["equity_curve"]] for r in units]
    if any(d != dates[0] for d in dates):
        raise ValueError("Sleeve curves must share a calendar")
    capital = initial_cash / len(units)
    curve = []
    for i, day in enumerate(dates[0]):
        equity = sum(
            capital * (1 - w + w * r["equity_curve"][i]["equity"])
            for r, w in zip(units, weights, strict=True)
        )
        cash = sum(
            capital * (1 - w + w * r["equity_curve"][i]["cash"])
            for r, w in zip(units, weights, strict=True)
        )
        curve.append(
            {"date": day, "equity": equity, "cash": cash, "exposure": (equity - cash) / equity}
        )
    totals = {
        k: sum(capital * w * r[k] for r, w in zip(units, weights, strict=True))
        for k in ["price_pnl", "dividends", "transaction_costs", "trading_pnl"]
    }
    peak, drawdown = initial_cash, 0.0
    for point in curve:
        peak = max(peak, point["equity"])
        drawdown = min(drawdown, point["equity"] / peak - 1)
    assert (
        abs(
            totals["trading_pnl"]
            - (totals["price_pnl"] + totals["dividends"] - totals["transaction_costs"])
        )
        < 1e-7
    )
    assert abs(curve[-1]["cash"] - initial_cash - totals["trading_pnl"]) < 1e-7
    return {
        **identity,
        "status": "matured",
        **totals,
        "final_cash": curve[-1]["cash"],
        "return": totals["trading_pnl"] / initial_cash,
        "max_drawdown": drawdown,
        "exposure_at_entry": mean(
            w * r["exposure_at_entry"] for r, w in zip(units, weights, strict=True)
        ),
        "turnover": mean(w * r["turnover"] for r, w in zip(units, weights, strict=True)),
        "equity_curve": curve,
    }


def replay(predictions, coverage, factors):
    by_case = {r["case_id"]: r for r in coverage}
    groups = defaultdict(list)
    for r in predictions:
        groups[(r["decision_date"], r["treatment"], r["trial"])].append(r)
    units = {
        (r["decision_date"], r["asset"], r["entry_delay"], r["bps_per_side"]): r for r in factors
    }
    stocks = set(factors[0]["universe"])
    results = []
    for (date, treatment, trial), group in sorted(groups.items()):
        if len(group) != len(stocks) or {r["ticker"] for r in group} != stocks:
            raise ValueError("Incomplete portfolio; cannot silently reduce denominator")
        group.sort(key=lambda r: r["ticker"])
        original = [WEIGHTS.get(r["rating"], 0) if r["status"] == "success" else 0 for r in group]
        for profile in PROFILES:
            weights = original.copy()
            assets = ["SPY" if treatment == "SPY" else r["ticker"] for r in group]
            delay, bps = (
                (2 if profile == "one-session-late" else 1),
                (25 if profile == "higher-friction" else 10),
            )
            if profile == "half-exposure-cap":
                scale = min(1, 0.5 / mean(weights)) if mean(weights) else 1
                weights = [w * scale for w in weights]
            elif profile in {"matched-SPY", "matched-basket"}:
                weights = [mean(original)] * len(group)
                assets = (
                    ["SPY"] * len(group)
                    if profile == "matched-SPY"
                    else [r["ticker"] for r in group]
                )
            elif profile == "require-archived-news" and treatment in AGENTS:
                weights = [
                    0 if "news" in by_case[r["case_id"]]["missing"] else w
                    for r, w in zip(group, weights, strict=True)
                ]
            result = aggregate_sleeves([units[(date, a, delay, bps)] for a in assets], weights)
            expense = sum(r["cost_upper_usd"] for r in group)
            results.append(
                {
                    "profile": profile,
                    "treatment": treatment,
                    "trial": trial,
                    "cohort": group[0]["cohort"],
                    "case_ids": [r["case_id"] for r in group],
                    "weights": dict(zip([r["ticker"] for r in group], weights, strict=True)),
                    "model_expense_upper_usd": expense,
                    "economic_pnl": result["trading_pnl"] - expense
                    if result["status"] == "matured"
                    else None,
                    **result,
                }
            )
    return results


def summarize(rows):
    groups = defaultdict(list)
    for r in rows:
        groups[(r["profile"], r["treatment"])].append(r)
    summaries = []
    for (profile, treatment), group in sorted(groups.items()):
        mature = [r for r in group if r["status"] == "matured"]
        # Average repeated agent trials within each date first.
        by_date = defaultdict(list)
        for r in mature:
            by_date[r["decision_date"]].append(r)
        metrics = {
            k: mean(mean(r[k] for r in rs) for rs in by_date.values()) if by_date else None
            for k in [
                "trading_pnl",
                "exposure_at_entry",
                "max_drawdown",
                "turnover",
                "transaction_costs",
                "economic_pnl",
            ]
        }
        summaries.append(
            {
                "profile": profile,
                "treatment": treatment,
                "matured_dates": len(by_date),
                "matured_executions": len(mature),
                "pending_executions": sum(r["status"] == "pending" for r in group),
                **metrics,
            }
        )
    return summaries

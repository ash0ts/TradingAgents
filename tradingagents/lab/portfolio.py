"""Deterministic, independent sleeve scenarios. No broker or order execution."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from tradingagents.lab.evidence import canonical
from tradingagents.lab.protocol import FREEZE, STOCKS, calendar_sessions

WEIGHTS = {"Buy": 1.0, "Overweight": .75, "Hold": .5, "Underweight": .25, "Sell": 0.0}


def simulate(decision_date, predictions, prices, sessions, *, initial_cash=100_000.0,
             bps=10, horizon=5, freeze=FREEZE):
    if initial_cash <= 0 or bps < 0 or not predictions:
        raise ValueError("Invalid portfolio inputs")
    i = sessions.index(decision_date)
    entry, exit_day = sessions[i + 1], sessions[i + horizon + 1]
    identity = {"decision_date": decision_date, "entry_date": entry, "exit_date": exit_day,
                "horizon": horizon, "bps_per_side": bps, "initial_cash": initial_cash}
    if exit_day > freeze:
        return {**identity, "status": "pending", "return": None, "trading_pnl": None}
    window = sessions[i+1:i+horizon+2]
    tables = {ticker: {r["date"]: r for r in rows} for ticker, rows in prices.items()}
    assets = {"SPY" if p["treatment"] == "SPY" else p["ticker"] for p in predictions}
    if any(any(day not in tables.get(asset, {}) for day in window) for asset in assets):
        return {**identity, "status": "missing-prices", "return": None, "trading_pnl": None}
    fee = bps / 10000
    sleeve = initial_cash / len(predictions)
    cash, positions, transactions = initial_cash, [], []
    total_fees, dividends, buy_notional, sell_notional = 0.0, 0.0, 0.0, 0.0
    failures = 0
    for p in predictions:
        asset = "SPY" if p["treatment"] == "SPY" else p["ticker"]
        weight = WEIGHTS.get(p.get("rating"), 0.0) if p["status"] == "success" else 0.0
        failures += p["status"] != "success" or p.get("rating") not in WEIGHTS
        # Target allocation is total cash deployed including entry fee, so
        # a 100% sleeve never borrows cash to pay transaction costs.
        notional = sleeve * weight / (1 + fee)
        shares = notional / tables[asset][entry]["close"]
        charge = notional * fee
        cash -= notional + charge
        buy_notional += notional
        total_fees += charge
        positions.append({"sleeve": p["ticker"], "asset": asset, "shares": shares, "target_weight": weight})
        transactions.append({"date": entry, "sleeve": p["ticker"], "asset": asset, "side": "buy",
                             "shares": shares, "price": tables[asset][entry]["close"], "notional": notional, "fee": charge})
    curve = [{"date": decision_date, "equity": initial_cash, "cash": initial_cash, "exposure": 0.0}]
    for day in window:
        if day != entry:
            for pos in positions:
                bar = tables[pos["asset"]][day]
                pos["shares"] *= bar.get("split", 1) or 1
                income = pos["shares"] * bar.get("dividend", 0)
                cash += income
                dividends += income
                if income or (bar.get("split", 1) or 1) != 1:
                    transactions.append({"date": day, "sleeve": pos["sleeve"], "asset": pos["asset"],
                                         "side": "corporate-action", "dividend_cash": income,
                                         "split": bar.get("split", 1) or 1, "shares_after": pos["shares"]})
        marked = sum(pos["shares"] * tables[pos["asset"]][day]["close"] for pos in positions)
        if day == exit_day:
            for pos in positions:
                notional = pos["shares"] * tables[pos["asset"]][day]["close"]
                charge = notional * fee
                cash += notional - charge
                sell_notional += notional
                total_fees += charge
                transactions.append({"date": day, "sleeve": pos["sleeve"], "asset": pos["asset"], "side": "sell",
                                     "shares": pos["shares"], "price": tables[pos["asset"]][day]["close"], "notional": notional, "fee": charge})
                pos["shares"] = 0.0
            marked = 0.0
        equity = cash + marked
        curve.append({"date": day, "equity": equity, "cash": cash, "exposure": marked / equity})
    peak, drawdown = initial_cash, 0.0
    for point in curve:
        peak = max(peak, point["equity"])
        drawdown = min(drawdown, point["equity"] / peak - 1)
    trading_pnl = cash - initial_cash
    assert abs(trading_pnl - (sell_notional - buy_notional + dividends - total_fees)) < 1e-7
    expense = sum(p.get("cost_upper_usd", 0) for p in predictions)
    return {**identity, "status": "matured", "final_cash": cash, "positions": positions,
            "price_pnl": sell_notional - buy_notional, "dividends": dividends, "transaction_costs": total_fees,
            "trading_pnl": trading_pnl, "model_expense_upper_usd": expense, "economic_pnl": trading_pnl - expense,
            "return": trading_pnl / initial_cash, "exposure_at_entry": buy_notional / initial_cash,
            "turnover": (buy_notional + sell_notional) / initial_cash, "max_drawdown": drawdown,
            "failed_or_unrated_sleeves_held_cash": failures, "transactions": transactions, "equity_curve": curve}


def run_portfolios(root, output):
    root, output = Path(root), Path(output)
    outcomes = json.loads((root / "outcomes.json").read_text())
    design = json.loads((output / "design.json").read_text())
    stocks = set(STOCKS if design["stocks"] == 6 else ["MSFT", "JPM", "XOM"])
    rows = [json.loads(p.read_text()) for directory in ["campaign", "baselines"]
            for p in (output / directory).rglob("*.json") if p.name == "prediction.json" or directory == "baselines"]
    groups = defaultdict(list)
    for row in rows:
        if row["ticker"] in stocks:
            groups[(row["decision_date"], row["treatment"], row["trial"])].append(row)
    sessions = calendar_sessions()
    results = []
    for (date, treatment, trial), group in sorted(groups.items()):
        if {r["ticker"] for r in group} != stocks or len(group) != len(stocks):
            continue  # unfinished scenarios cannot silently reduce their denominator
        for bps in [0, 5, 10, 25]:
            result = simulate(date, group, outcomes["prices"], sessions, bps=bps, freeze=outcomes["freeze_through"])
            results.append({"treatment": treatment, "trial": trial, "cohort": group[0]["cohort"],
                            "case_ids": [r["case_id"] for r in group],
                            "conversation_urls": [r["conversation_url"] for r in group if r.get("conversation_url")], **result})
    (output / "portfolios.json").write_bytes(canonical({"scenario_independence": "overlapping scenarios are not compounded", "results": results}))
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="lab-data/election-v1")
    parser.add_argument("--output", default="lab-runs/election-v1")
    args = parser.parse_args()
    print(json.dumps({"scenario_sensitivity_rows": len(run_portfolios(args.root, args.output))}))

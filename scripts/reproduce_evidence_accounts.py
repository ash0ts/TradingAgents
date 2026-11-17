"""Reproduce every new account from public per-dollar factors; standard library only."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

PUBLIC = Path(__file__).resolve().parents[1] / "studies/common-evidence-v3-repaired"


def reproduce(public=PUBLIC):
    public = Path(public)
    result = json.loads((public / "results.json").read_text())
    units = json.loads((public / "unit-account-factors.json").read_text())
    index = {(r["decision_date"], r["asset"], r["bps_per_side"]): r for r in units}
    groups = defaultdict(list)
    for row in result["rows"]:
        groups[row["arm"], row["treatment"], row["decision_date"], row["trial"]].append(row)
    errors = []
    checked, pending = 0, 0
    for account in result["portfolios"]:
        date, bps = account["decision_date"], account["bps_per_side"]
        group = groups[account["arm"], account["treatment"], date, account["trial"]]
        assert len(group) == result["design"]["stocks"]
        factors = [index[date, r["ticker"], bps] for r in group]
        spy = index[date, "SPY", bps]
        assert all(f["status"] == account["status"] for f in [*factors, spy])
        if account["status"] == "pending":
            assert account["trading_pnl"] is None and account["selection_pnl"] is None
            pending += 1
            continue
        assert account["status"] == "matured"
        sleeve = account["initial_cash"] / len(group)
        deployed = [sleeve * r["target_weight"] for r in group]
        derived = {
            k: sum(d * f[k] for d, f in zip(deployed, factors, strict=True))
            for k in ("trading_pnl", "price_pnl", "dividends", "transaction_costs")
        }
        derived["final_cash"] = account["initial_cash"] + derived["trading_pnl"]
        derived["matched_SPY_pnl"] = sum(deployed) * spy["trading_pnl"]
        derived["selection_pnl"] = derived["trading_pnl"] - derived["matched_SPY_pnl"]
        derived["exposure_at_entry"] = sum(deployed) / (1 + bps / 10000) / account["initial_cash"]
        derived["turnover"] = (
            sum(d * f["turnover"] for d, f in zip(deployed, factors, strict=True))
            / account["initial_cash"]
        )
        derived["model_expense_upper_usd"] = sum(r["cost_upper_usd"] for r in group)
        derived["economic_pnl"] = derived["trading_pnl"] - derived["model_expense_upper_usd"]
        peak, drawdown = account["initial_cash"], 0.0
        for i, point in enumerate(factors[0]["equity_curve"]):
            assert all(f["equity_curve"][i]["date"] == point["date"] for f in factors)
            equity = (
                account["initial_cash"]
                - sum(deployed)
                + sum(
                    d * f["equity_curve"][i]["equity"]
                    for d, f in zip(deployed, factors, strict=True)
                )
            )
            peak = max(peak, equity)
            drawdown = min(drawdown, equity / peak - 1)
        derived["max_drawdown"] = drawdown
        for field, value in derived.items():
            error = abs(value - account[field])
            errors.append(error)
            assert error < 1e-7, (date, account["arm"], account["treatment"], bps, field, error)
        checked += 1
    receipt = {
        "method": "Independent linear account reconstruction from public per-dollar factors and accepted target weights.",
        "matured_accounts_reconciled": checked,
        "pending_accounts_preserved": pending,
        "maximum_absolute_error": max(errors),
        "tolerance": 1e-7,
        "result_sha256": hashlib.sha256((public / "results.json").read_bytes()).hexdigest(),
        "unit_factors_sha256": hashlib.sha256(
            (public / "unit-account-factors.json").read_bytes()
        ).hexdigest(),
        "requires_raw_prices_or_credentials": False,
        "boundary": "Reconciles portfolio arithmetic, not original data collection, model outputs or investment merit.",
    }
    (public / "public-reproduction.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=PUBLIC, type=Path)
    reproduce(parser.parse_args().data)

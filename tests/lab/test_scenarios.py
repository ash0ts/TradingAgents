import pytest

from tradingagents.lab.portfolio import simulate
from tradingagents.lab.scenarios import aggregate_sleeves


def fixture():
    sessions = [f"2024-01-{i:02d}" for i in range(1, 12)]
    prices = {
        "AAPL": [
            {"date": d, "close": 100 + i * 2, "split": 1, "dividend": 0}
            for i, d in enumerate(sessions)
        ]
    }
    predictions = [{"ticker": "AAPL", "treatment": "test", "status": "success", "rating": "Buy"}]
    return sessions, prices, predictions


def test_delayed_entry_skips_price_and_dividend_and_shifts_exit():
    sessions, prices, rows = fixture()
    prices["AAPL"][1]["dividend"] = 20
    r = simulate(sessions[0], rows, prices, sessions, entry_delay=2, bps=0)
    assert r["entry_date"] == sessions[2] and r["exit_date"] == sessions[7]
    assert r["dividends"] == 0
    assert r["trading_pnl"] == pytest.approx(100000 * (114 / 104 - 1))


def test_public_unit_factors_reconcile_dollars_actions_and_cash():
    sessions, prices, rows = fixture()
    prices["AAPL"][3]["split"] = 2
    prices["AAPL"][3]["dividend"] = 1
    for r in prices["AAPL"][3:]:
        r["close"] /= 2
    unit = simulate(sessions[0], rows, prices, sessions, initial_cash=1)
    combined = aggregate_sleeves([unit], [0.37])
    direct = simulate(sessions[0], rows, prices, sessions, target_weights={"AAPL": 0.37})
    for key in [
        "trading_pnl",
        "dividends",
        "transaction_costs",
        "max_drawdown",
        "exposure_at_entry",
        "turnover",
    ]:
        assert combined[key] == pytest.approx(direct[key])
    assert min(p["cash"] for p in combined["equity_curve"]) >= 0
    assert combined["equity_curve"][-1]["exposure"] == pytest.approx(0)


def test_zero_weights_pending_and_invalid_allocations():
    sessions, prices, rows = fixture()
    unit = simulate(sessions[0], rows, prices, sessions, initial_cash=1)
    zero = aggregate_sleeves([unit], [0])
    assert zero["trading_pnl"] == zero["transaction_costs"] == zero["max_drawdown"] == 0
    pending = simulate(sessions[0], rows, prices, sessions, freeze=sessions[3])
    assert aggregate_sleeves([pending], [0])["status"] == "pending"
    for weights in [{"AAPL": 1.1}, {"AAPL": float("nan")}, {}]:
        with pytest.raises(ValueError):
            simulate(sessions[0], rows, prices, sessions, target_weights=weights)
    with pytest.raises(ValueError):
        simulate(sessions[0], rows, prices, sessions, entry_delay=0)


def test_all_profiles_keep_dates_and_gate_missing_news_without_new_decisions():
    from tradingagents.lab.scenarios import replay

    sessions, prices, predictions = fixture()
    prices["SPY"] = prices["AAPL"]
    row = {
        **predictions[0],
        "decision_date": sessions[0],
        "case_id": "frozen-AAPL",
        "treatment": "default-committee",
        "trial": 0,
        "cohort": "fixed",
        "cost_upper_usd": 0.1,
    }
    factors = []
    for asset in ["AAPL", "SPY"]:
        for delay, bps in [(1, 10), (1, 25), (2, 10)]:
            result = simulate(
                sessions[0],
                [{**row, "ticker": asset}],
                prices,
                sessions,
                initial_cash=1,
                entry_delay=delay,
                bps=bps,
            )
            factors.append({**result, "asset": asset, "entry_delay": delay, "universe": ["AAPL"]})
    results = {
        r["profile"]: r
        for r in replay([row], [{"case_id": "frozen-AAPL", "missing": ["news"]}], factors)
    }
    assert len(results) == 7
    assert results["original"]["trading_pnl"] == pytest.approx(
        results["matched-SPY"]["trading_pnl"]
    )
    assert results["half-exposure-cap"]["trading_pnl"] == pytest.approx(
        results["original"]["trading_pnl"] / 2
    )
    assert results["require-archived-news"]["trading_pnl"] == 0
    assert results["require-archived-news"]["economic_pnl"] == -0.1
    assert results["one-session-late"]["entry_date"] == sessions[2]
    assert results["one-session-late"]["exit_date"] == sessions[7]
    assert row["rating"] == "Buy"  # external allocation gate never rewrites decisions
    with pytest.raises(ValueError, match="Incomplete portfolio"):
        replay([row, row], [{"case_id": "frozen-AAPL", "missing": []}], factors)

import pytest

from tradingagents.lab.portfolio import simulate


def fixture():
    sessions = [f'2024-01-{i:02d}' for i in range(1, 10)]
    prices = {'AAPL': [{'date': d, 'close': 100, 'split': 1, 'dividend': 0} for d in sessions]}
    predictions = [{'ticker': 'AAPL', 'treatment': 'test', 'status': 'success', 'rating': 'Buy', 'cost_upper_usd': 3}]
    return sessions, prices, predictions


def test_entry_fee_cash_and_liquidation_reconcile():
    sessions, prices, predictions = fixture()
    prices['AAPL'][0]['close'] = 1  # decision close must never become entry
    result = simulate(sessions[0], predictions, prices, sessions, bps=10)
    assert result['final_cash'] == pytest.approx(100000 * .999 / 1.001)
    assert result['transaction_costs'] == pytest.approx(2 * 100000 * .001 / 1.001)
    assert result['economic_pnl'] == pytest.approx(result['trading_pnl'] - 3)
    assert all(p['shares'] == 0 for p in result['positions'])
    assert min(p['cash'] for p in result['equity_curve']) >= -1e-8


def test_split_and_dividend_in_dollars_not_double_adjusted():
    sessions, prices, predictions = fixture()
    for row in prices['AAPL'][2:]:
        row['close'] = 50
    prices['AAPL'][2].update(split=2, dividend=1)
    result = simulate(sessions[0], predictions, prices, sessions, bps=0)
    assert result['dividends'] == pytest.approx(2000)
    assert result['price_pnl'] == pytest.approx(0)
    assert result['final_cash'] == pytest.approx(102000)


def test_half_sleeve_cash_failures_and_pending():
    sessions, prices, predictions = fixture()
    predictions[0]['rating'] = 'Hold'
    result = simulate(sessions[0], predictions, prices, sessions, bps=0)
    assert result['exposure_at_entry'] == .5
    assert result['final_cash'] == 100000
    predictions[0]['status'] = 'failed'
    result = simulate(sessions[0], predictions, prices, sessions)
    assert result['failed_or_unrated_sleeves_held_cash'] == 1
    assert result['transaction_costs'] == 0
    result = simulate(sessions[0], predictions, prices, sessions, freeze=sessions[3])
    assert result['status'] == 'pending' and result['return'] is None

import numpy as np
import pytest

from tradingagents.lab.baselines import NumericPredictor, rating_for, supervised


def fixture():
    import pandas as pd
    dates = pd.bdate_range('2020-01-01', periods=400).strftime('%Y-%m-%d').tolist()
    rng = np.random.default_rng(9)
    prices = {}
    for ticker in ['AAPL', 'SPY']:
        values = 100 * np.exp(np.cumsum(rng.normal(0, .01, len(dates))))
        prices[ticker] = [{'date': d, 'close': float(v), 'split': 1, 'dividend': 0} for d, v in zip(dates, values, strict=True)]
    return {'case': {'ticker':'AAPL', 'cohort':'test'}, 'prices': prices}, dates


def test_training_labels_mature_and_validation_is_chronological():
    data, dates = fixture()
    xt, yt, xv, yv, _, meta = supervised(data, dates[350])
    assert meta['last_training_exit'] < meta['last_validation_exit'] < dates[350]
    assert xt.shape[1] == xv.shape[1] == 20
    assert len(yt) > len(yv) > 0


def test_future_prices_do_not_change_training_fit(tmp_path):
    data, dates = fixture()
    before = supervised(data, dates[350])
    for row in data['prices']['AAPL'][351:]:
        row['close'] *= 10
    after = supervised(data, dates[350])
    np.testing.assert_equal(before[0], after[0])
    np.testing.assert_equal(before[1], after[1])
    assert before[-1]['data_sha256'] == after[-1]['data_sha256']
    for name in ['momentum-20', 'mean-reversion-5', 'AR-5']:
        result = NumericPredictor(name, tmp_path).predict(data, dates[350])
        assert np.isfinite(result.forecast)


def test_optional_ridge_predictor(tmp_path):
    pytest.importorskip("sklearn")
    data, dates = fixture()
    assert np.isfinite(NumericPredictor("ridge", tmp_path).predict(data, dates[350]).forecast)


@pytest.mark.parametrize(('value','rating'), [(-.02,'Sell'),(-.005,'Underweight'),(0,'Hold'),(.005,'Overweight'),(.02,'Buy')])
def test_forecast_buckets(value, rating):
    assert rating_for(value) == rating

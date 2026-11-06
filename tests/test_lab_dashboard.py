"""Dashboard counts preserve missingness and the experiment's actual units."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tradingagents.lab.dashboard import treatment_metrics, validate_payload
from tradingagents.lab.evidence import digest


@pytest.fixture(scope="module")
def payload():
    return json.loads((Path(__file__).parents[1] / "notebooks/data/showcase.json").read_text())


def test_frozen_aggregates_reconcile(payload):
    audit = validate_payload(payload)
    assert audit["agent_runs"] == 360
    assert audit["baseline_predictions"] == 600
    assert audit["market_cases"] == 60


def test_passive_forecast_is_absent_not_zero(payload):
    metrics = treatment_metrics(payload, "SPY")
    assert "outcomes/signed_excess_pct" not in metrics
    assert "outcomes/directional_accuracy_pct" not in metrics
    assert "cost/mean_model_usd" not in metrics
    assert metrics["portfolio/decision_dates"] == 8
    assert metrics["portfolio/mean_pnl_usd"] == pytest.approx(458.44, abs=.01)


def test_trial_and_market_denominators_stay_distinct(payload):
    metrics = treatment_metrics(payload, "default-committee")
    assert metrics["coverage/requested_trials"] == 120
    assert metrics["coverage/market_cases"] == 60
    assert metrics["coverage/pending_trials"] == 24
    assert metrics["portfolio/scenarios"] == 16
    assert metrics["portfolio/decision_dates"] == 8
    assert metrics["coverage/scored_trials"] == 77
    assert metrics["outcomes/signed_excess_pct"] < 0


def test_rejects_tampered_aggregate_even_with_new_fingerprint(payload):
    changed = copy.deepcopy(payload)
    changed["summaries"]["default-committee"]["signed_excess_return"]["mean"] = .5
    changed["public_data_sha256"] = digest({k: v for k, v in changed.items() if k != "public_data_sha256"})
    with pytest.raises(ValueError, match="Summary does not reconcile"):
        validate_payload(changed)

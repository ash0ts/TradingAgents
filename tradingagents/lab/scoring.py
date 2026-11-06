"""Behavior and financial returns are separate axes. Missing is never zero."""
from __future__ import annotations

from collections import defaultdict

import numpy as np

RATING_DIRECTION = {"Buy": 1, "Overweight": 1, "Hold": 0, "Underweight": -1, "Sell": -1}


def score(prediction, outcome):
    rating = prediction.get("rating")
    direction = RATING_DIRECTION.get(rating)
    failed = prediction.get("status") != "success"
    result = {"failed": failed, "abstained": not failed and direction in (None, 0),
              "actionable": not failed and direction not in (None, 0),
              "directional_correct": None, "signed_excess_return": None,
              "absolute_forecast_error": None, "outcome_status": outcome["stock"]["status"]}
    if failed or any(outcome[asset]["status"] != "matured" for asset in ("stock", "benchmark")):
        return result
    excess = outcome["stock"]["return"] - outcome["benchmark"]["return"]
    result["excess_return"] = excess
    if direction not in (None, 0):
        result.update(directional_correct=(direction * excess > 0), signed_excess_return=direction * excess)
    if prediction.get("forecast") is not None and outcome["stock"].get("horizon", 5) == 5:
        result["absolute_forecast_error"] = abs(prediction["forecast"] - excess)
    return result


def summary(rows):
    output = {"requested": len(rows)}
    for key in ["failed", "abstained", "actionable"]:
        output[key] = sum(bool(r["scores"][key]) for r in rows)
    output["coverage"] = output["actionable"] / len(rows) if rows else None
    for key in ["directional_correct", "signed_excess_return", "absolute_forecast_error"]:
        values = [float(r["scores"][key]) for r in rows if r["scores"].get(key) is not None]
        output[key] = {"mean": float(np.mean(values)) if values else None, "n": len(values)}
    output["pending"] = sum(r["scores"]["outcome_status"] == "pending" for r in rows)
    return output


def paired_blocks(rows, a, b, metric="signed_excess_return", seed=2026):
    # Repeated trials collapse before matching; stocks/dates stay in cohorts.
    groups = defaultdict(list)
    for row in rows:
        value = row["scores"].get(metric)
        if value is not None:
            groups[(row["case_id"], row["cohort"], row["treatment"])].append(value)
    blocks = defaultdict(list)
    for case, cohort, treatment in groups:
        if treatment == a and (case, cohort, b) in groups:
            blocks[cohort].append(float(np.mean(groups[case, cohort, a]) - np.mean(groups[case, cohort, b])))
    if not blocks:
        return {"pairs": 0, "blocks": 0, "mean": None, "interval": None}
    arrays = list(blocks.values())
    rng = np.random.default_rng(seed)
    draws = [np.mean([v for i in rng.integers(0, len(arrays), len(arrays)) for v in arrays[i]]) for _ in range(2000)]
    return {"pairs": sum(map(len, arrays)), "blocks": len(arrays),
            "mean": float(np.mean([v for values in arrays for v in values])),
            "interval": np.quantile(draws, [.025, .975]).tolist(), "method": "paired cohort-block bootstrap; exploratory with five blocks"}

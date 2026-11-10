"""Prespecified paired analysis: trials are repetitions, not new market dates."""
from __future__ import annotations

import itertools
import random
from collections import defaultdict
from statistics import mean


def paired_contrasts(accounts, control="luna-committee", *, seed=20261110):
    """Equal-weight date means, four cohort blocks; no independence claim for trials.

    Exact sign-flip values assume independent, sign-symmetric cohort differences.
    They are sensitivity diagnostics, not randomization-test guarantees. With four
    nonzero blocks the smallest two-sided value is 2/16, regardless of trial count.
    """
    groups = defaultdict(list)
    for row in accounts:
        if row["status"] == "matured" and row["bps_per_side"] == 10:
            groups[row["treatment"], row["cohort"], row["decision_date"]].append(row["selection_pnl"])
    dates = {key: mean(values) for key, values in groups.items()}
    result = []
    for treatment in ("luna-no-research", "luna-no-risk", "single-luna"):
        paired = [{"cohort": cohort, "decision_date": date,
                   "difference": value - dates[control, cohort, date]}
                  for (arm, cohort, date), value in dates.items() if arm == treatment]
        blocks = defaultdict(list)
        for row in paired:
            blocks[row["cohort"]].append(row["difference"])
        block_means = {c: mean(v) for c, v in sorted(blocks.items())}
        assert len({len(v) for v in blocks.values()}) == 1, "Equal-sized cohort blocks required"
        values = list(block_means.values())
        estimate = mean(values)
        flips = [mean(s * v for s, v in zip(signs, values, strict=True))
                 for signs in itertools.product((-1, 1), repeat=len(values))]
        p = sum(abs(x) >= abs(estimate) - 1e-12 for x in flips) / len(flips)
        rng = random.Random(seed)
        draws = sorted(mean(rng.choices(values, k=len(values))) for _ in range(10000))
        result.append({"treatment": treatment, "control": control, "mean_difference": estimate,
                       "independent_dates": len(paired), "cohort_blocks": len(values),
                       "date_differences": sorted(paired, key=lambda r: r["decision_date"]),
                       "block_differences": block_means,
                       "exploratory_bootstrap_95": [draws[249], draws[9749]],
                       "sign_flip_p": p,
                       "leave_one_cohort_out": {c: mean(v for k, v in block_means.items() if k != c)
                                                for c in block_means}})
    running = 0.0
    for rank, row in enumerate(sorted(result, key=lambda r: r["sign_flip_p"])):
        running = max(running, min(1.0, (len(result) - rank) * row["sign_flip_p"]))
        row["holm_adjusted_p"] = running
    return result


def repeatability(rows, trials):
    """Report all requested cases, including invalid contracts and failed attempts."""
    groups = defaultdict(list)
    for row in rows:
        groups[row["treatment"], row["case_id"]].append(row)
    result = []
    for (treatment, case), values in sorted(groups.items()):
        assert len(values) == trials and len({r["trial"] for r in values}) == trials
        weights = [r["target_weight"] for r in values]
        statuses = [r["contract_status"] for r in values]
        result.append({"treatment": treatment, "case_id": case, "trials": trials,
                       "weight_range": max(weights) - min(weights),
                       "same_weight_all_trials": len(set(weights)) == 1,
                       "same_rating_all_trials": len({r["rating"] for r in values}) == 1,
                       "same_contract_status_all_trials": len(set(statuses)) == 1,
                       "all_actor_success": all(r["status"] == "success" for r in values),
                       "conversation_urls": [r["conversation_url"] for r in sorted(values, key=lambda x: x["trial"])]})
    return result

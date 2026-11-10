from tradingagents.lab.repeated_analysis import paired_contrasts


def fixture(repeats):
    return [{"treatment": arm, "cohort": str(cohort), "decision_date": f"{cohort}-{day}",
             "status": "matured", "bps_per_side": 10, "selection_pnl": float(value), "trial": trial}
            for arm, value in [("luna-committee", 0), ("luna-no-research", 1),
                               ("luna-no-risk", -1), ("single-luna", 0)]
            for cohort in range(4) for day in range(2) for trial in range(repeats)]


def test_repetitions_do_not_manufacture_market_sample_size_or_significance():
    one = paired_contrasts(fixture(1))
    assert one == paired_contrasts(fixture(3))
    assert one[0]["independent_dates"] == 8 and one[0]["cohort_blocks"] == 4
    assert one[0]["mean_difference"] == 1
    assert one[0]["sign_flip_p"] == 0.125 and one[0]["holm_adjusted_p"] == 0.375
    assert one[1]["mean_difference"] == -1
    assert one[2]["sign_flip_p"] == 1


def test_pending_outcomes_and_fee_sensitivities_do_not_enter_primary_contrast():
    rows = fixture(3)
    extra = [{**r, "status": "pending", "selection_pnl": None} for r in rows]
    extra += [{**r, "bps_per_side": 25, "selection_pnl": 10000} for r in rows]
    assert paired_contrasts(rows) == paired_contrasts(rows + extra)

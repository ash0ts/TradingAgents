"""Audit cache-write premiums without mutating any frozen prediction or actor.

The original ledger charged cache creation at the uncached rate. Reserve an
additional accounting hold while execution continues; reconcile settled calls
only after all scheduled actors have finished. Unknown call charges retain their
original conservative reservation. This is list-price accounting, not an invoice.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal

from run_debate_ablation import LEDGER, OUT, PUBLIC

from tradingagents.lab.budget import CAPS, Ledger

HOLD = "debate-v5-cache-write-accounting-hold"
HOLD_KEY = "election-evidence-v3/pricing-reconciliation-hold"
RATES = {"gpt-6-luna": ("0.10", "0.01", "0.125", "0.50"),
         "gpt-6-sol": ("2.00", "0.20", "2.50", "10.00")}


def charge(model, usage):
    inp, read, write, out = map(Decimal, RATES[model])
    tokens = usage["input_tokens"]
    detail = usage.get("input_token_details") or {}
    cached, created = detail.get("cache_read", 0), detail.get("cache_creation", 0)
    assert 0 <= cached + created <= tokens
    input_multiplier = 2 if tokens > 272000 else 1
    output_multiplier = Decimal("1.5") if tokens > 272000 else Decimal(1)
    cost = ((tokens - cached - created) * inp + cached * read + created * write) * input_multiplier
    cost += usage["output_tokens"] * out * output_multiplier
    return int(cost.to_integral_value(rounding=ROUND_CEILING))


def reserve():
    ledger = Ledger(LEDGER, campaign_prefix="election-evidence-v3/", campaign_cap_usd=30)
    with ledger.connect() as db:
        exists = db.execute("SELECT 1 FROM calls WHERE id=?", (HOLD,)).fetchone()
    if not exists:
        ledger.reserve(HOLD, HOLD_KEY, "campaign", "accounting-reservation", 6_000_000)
    value = {"recorded_at": datetime.now(UTC).isoformat(), "reserve_usd": 6,
             "reason": "Original settled estimates omitted the 25% cache-write premium. Hold covers prior and current calls while preserving all actor sources and predictions.",
             "sources": ["https://developers.openai.com/api/docs/models/gpt-6-luna", "https://developers.openai.com/api/docs/models/gpt-6-sol"],
             "rates_usd_per_million": RATES,
             "scope": "Accounting correction only; no actor retry, prompt change or financial-outcome selection."}
    path = PUBLIC / "pricing-reservation.json"
    if not path.exists():
        path.write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps({"pricing_hold_usd": 6, "budget": ledger.totals()}))


def reconcile():
    receipt = PUBLIC / "pricing-reconciliation.json"
    if receipt.exists():
        # Refuse a stale receipt after a restored or manually edited ledger.
        plan = json.loads((OUT / "pricing-reconciliation-call-records.json").read_text())
        with Ledger(LEDGER).connect() as db:
            assert all(db.execute("SELECT charged FROM calls WHERE id=?", (r["call_id"],)).fetchone()[0] == r["corrected_micros"] for r in plan)
        return json.loads(receipt.read_text())
    paths = list(OUT.glob("*/campaign/**/prediction.json"))
    assert len(paths) == len(json.loads((OUT / "jobs.json").read_text()))
    ledger = Ledger(LEDGER)
    corrections = []
    by_run = defaultdict(int)
    with ledger.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute("SELECT id,run_key,phase,model,reserve,charged,usage,status FROM calls").fetchall()
        assert not [r for r in rows if r[3] in RATES and r[7] == "reserved"], "Actors still have active reservations"
        plan_path = OUT / "pricing-reconciliation-call-records.json"
        prior_plan = json.loads(plan_path.read_text()) if plan_path.exists() else None
        for cid, key, phase, model, reserve_value, old, raw, status in rows:
            if model not in RATES or status != "settled" or not raw:
                continue
            usage = json.loads(raw)
            created = (usage.get("input_token_details") or {}).get("cache_creation", 0)
            if not created:
                continue
            new = max(old, charge(model, usage))
            assert new <= reserve_value
            corrections.append({"call_id": cid, "run_key": key, "phase": phase, "model": model,
                                "old_micros": old, "corrected_micros": new,
                                "cache_creation_tokens": created})
        if prior_plan is not None:
            # Recovery after a committed transaction but before receipt save.
            corrections = prior_plan
        for row in corrections:
            by_run[row["run_key"]] += row["corrected_micros"] - row["old_micros"]
        assert sum(by_run.values()) <= 6_000_000, "Pricing correction exceeds its separate hold"
        # A durable before/after plan exists before any mutation.
        if prior_plan is None:
            plan_path.write_text(json.dumps(corrections, indent=2) + "\n")
        for row in corrections:
            current = db.execute("SELECT charged FROM calls WHERE id=?", (row["call_id"],)).fetchone()[0]
            assert current in (row["old_micros"], row["corrected_micros"])
            db.execute("UPDATE calls SET charged=? WHERE id=? AND charged=?", (row["corrected_micros"], row["call_id"], row["old_micros"]))
        db.execute("UPDATE calls SET charged=0,status='settled' WHERE id=?", (HOLD,))
        phase_totals = dict(db.execute("SELECT phase,sum(coalesce(charged,reserve)) FROM calls GROUP BY phase"))
        assert all(v <= CAPS[k] for k, v in phase_totals.items())
        combined = db.execute("SELECT sum(coalesce(charged,reserve)) FROM calls WHERE run_key LIKE 'election-evidence-v3/%'").fetchone()[0]
        assert combined <= 30_000_000
        totals = dict(db.execute("SELECT model,sum(charged) FROM calls WHERE model IN ('gpt-6-luna','gpt-6-sol') GROUP BY model"))
        value = {"recorded_at": datetime.now(UTC).isoformat(), "correction_usd": sum(by_run.values()) / 1e6,
                 "corrected_calls": len(corrections), "model_totals_usd": {k: v / 1e6 for k, v in totals.items()},
                 "run_adjustments_usd": {k: v / 1e6 for k, v in sorted(by_run.items())},
                 "original_predictions_unchanged": True, "unknown_calls_retain_reserve": True,
                 "accounting_hold_released": True, "cost_basis": "Standard US list prices including cache-write premiums; invoice reconciliation still pending.",
                 "rates_usd_per_million": RATES,
                 "sources": ["https://developers.openai.com/api/docs/models/gpt-6-luna", "https://developers.openai.com/api/docs/models/gpt-6-sol"]}
    receipt.write_text(json.dumps(value, indent=2) + "\n")
    return value


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("reserve", "reconcile"))
    reserve() if parser.parse_args().command == "reserve" else print(json.dumps(reconcile()))

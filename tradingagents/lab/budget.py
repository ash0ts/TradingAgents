"""Durable, concurrent reservations. Unknown charges keep their full reserve."""
from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler

# USD / million tokens, standard US endpoint; verified 2026-11-06.
# https://developers.openai.com/api/docs/models/gpt-6-luna
# https://developers.openai.com/api/docs/models/gpt-6-sol
PRICES = {"gpt-6-luna": (.10, .01, .50), "gpt-6-sol": (2.0, .20, 10.0)}
CAPS = {"qualification": 25_000_000, "campaign": 200_000_000, "publication": 25_000_000}


class BudgetExceeded(RuntimeError):
    pass


def cost_micros(model, input_tokens, output_tokens, cached=0):
    inp, cache, out = PRICES[model]  # Unknown model is an error, never free.
    long = input_tokens > 272_000
    return math.ceil((input_tokens - cached) * inp * (2 if long else 1)
                     + cached * cache * (2 if long else 1) + output_tokens * out * (1.5 if long else 1))


class Ledger:
    def __init__(self, path, *, campaign_prefix=None, campaign_cap_usd=None):
        if (campaign_prefix is None) != (campaign_cap_usd is None):
            raise ValueError("Campaign prefix and cap must be supplied together")
        if campaign_cap_usd is not None and (not campaign_prefix or not math.isfinite(campaign_cap_usd) or campaign_cap_usd <= 0):
            raise ValueError("Invalid campaign budget")
        self.campaign_prefix = campaign_prefix
        self.campaign_cap = round(campaign_cap_usd * 1e6) if campaign_cap_usd else None
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS calls (id TEXT PRIMARY KEY, run_key TEXT, phase TEXT, model TEXT, reserve INTEGER, charged INTEGER, usage TEXT, status TEXT)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=60, isolation_level="IMMEDIATE")

    def reserve(self, call_id, run_key, phase, model, micros):
        if phase not in CAPS or micros <= 0:
            raise ValueError("Invalid budget reservation")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            total, subtotal = db.execute("SELECT COALESCE(SUM(COALESCE(charged,reserve)),0), COALESCE(SUM(CASE WHEN phase=? THEN COALESCE(charged,reserve) ELSE 0 END),0) FROM calls", (phase,)).fetchone()
            if total + micros > sum(CAPS.values()) or subtotal + micros > CAPS[phase]:
                raise BudgetExceeded(f"Budget exhausted before dispatch: {phase}")
            if self.campaign_prefix is not None:
                if not run_key.startswith(self.campaign_prefix):
                    raise ValueError("Run does not belong to the capped campaign")
                spent = db.execute("SELECT COALESCE(SUM(COALESCE(charged,reserve)),0) FROM calls WHERE substr(run_key,1,length(?))=?",
                                   (self.campaign_prefix, self.campaign_prefix)).fetchone()[0]
                if spent + micros > self.campaign_cap:
                    raise BudgetExceeded("Campaign-specific cap exhausted before dispatch")
            db.execute("INSERT INTO calls VALUES (?,?,?,?,?,NULL,NULL,'reserved')", (str(call_id), run_key, phase, model, micros))

    def settle(self, call_id, usage):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT model,reserve,status FROM calls WHERE id=?", (str(call_id),)).fetchone()
            if row is None or row[2] == "settled":
                return
            if usage is None:
                db.execute("UPDATE calls SET status='unknown' WHERE id=?", (str(call_id),))
                return
            charge = cost_micros(row[0], usage["input_tokens"], usage["output_tokens"], (usage.get("input_token_details") or {}).get("cache_read", 0))
            if charge > row[1]:
                raise RuntimeError("Cost exceeded conservative reserve; stop campaign and reconcile")
            db.execute("UPDATE calls SET charged=?,usage=?,status='settled' WHERE id=?", (charge, json.dumps(usage), str(call_id)))

    def totals(self, run_key=None):
        with self.connect() as db:
            rows = db.execute("SELECT phase,model,reserve,charged,status FROM calls" + (" WHERE run_key=?" if run_key else ""), (run_key,) if run_key else ()).fetchall()
        return {"cost_upper_usd": sum(r[3] if r[3] is not None else r[2] for r in rows) / 1e6,
                "cost_known_usd": sum(r[3] or 0 for r in rows) / 1e6,
                "unknown_calls": sum(r[3] is None for r in rows), "calls": len(rows)}


class BudgetCallback(BaseCallbackHandler):
    raise_error = True
    run_inline = True

    def __init__(self, ledger, run_key, phase, max_output=4096):
        self.ledger, self.run_key, self.phase, self.max_output = ledger, run_key, phase, max_output

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        params = kwargs.get("invocation_params") or {}
        model = (kwargs.get("metadata") or {}).get("ls_model_name") or params.get("model") or params.get("model_name")
        # One token cannot encode fewer than one UTF-8 byte; include serialized
        # tools/parameters and 4096 bytes of protocol overhead. No image inputs.
        text = json.dumps([[m.model_dump() for m in batch] for batch in messages], ensure_ascii=False, default=str)
        input_bound = len(text.encode()) + len(json.dumps(params, default=str).encode()) + 4096
        if input_bound > 1_000_000:
            raise BudgetExceeded("Pilot request exceeds frozen 1M input bound")
        # Reserve cache-write price and regional/fast multipliers as headroom.
        reserve = math.ceil(cost_micros(model, input_bound, self.max_output) * 2.5)
        self.ledger.reserve(run_id, self.run_key, self.phase, model, reserve)

    def on_llm_end(self, response, *, run_id, **kwargs):
        usages = [getattr(g.message, "usage_metadata", None) for batch in response.generations for g in batch if hasattr(g, "message")]
        usages = [u for u in usages if u]
        if len(usages) != 1:
            self.ledger.settle(run_id, None)
        else:
            self.ledger.settle(run_id, usages[0])

    def on_llm_error(self, error, *, run_id, **kwargs):
        self.ledger.settle(run_id, None)


def choose_design(qualification_costs, allowance=200):
    if set(qualification_costs) != {"default-committee", "luna-committee", "single-luna"}:
        raise ValueError("Qualification must cover all treatments")
    # A 2x qualification margin absorbs case-length variation and failures.
    per_case = sum(qualification_costs.values()) * 2
    for stocks, trials in [(6, 2), (6, 1), (3, 2), (3, 1)]:
        expected = 10 * stocks * trials * per_case
        if expected <= allowance:
            return {"stocks": stocks, "trials": trials, "estimated_upper_usd": expected,
                    "qualification_costs": qualification_costs, "margin": 2}
    raise BudgetExceeded("Even the minimum balanced configuration is unaffordable")

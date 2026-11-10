"""A small, identical, point-in-time evidence set for every evaluated role.

No price outcomes, event dates from memory, or re-collected facts enter the brief.
Each derived number points back into the existing content-addressed snapshot.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tradingagents.lab.evidence import cutoff, digest, timestamp
from tradingagents.lab.execution import ExecutionDecision

MODES = ("shared-evidence", "cited-evidence")
MISSING = ("news", "social", "event_calendar", "insiders", "prediction_markets")


def total_return(rows, sessions):
    window = rows[-sessions - 1:]
    if len(window) != sessions + 1:
        return None
    shares, dividends = 1.0, 0.0
    for row in window[1:]:
        shares *= row.get("split", 1) or 1
        dividends += shares * row.get("dividend", 0)
    return (shares * window[-1]["close"] + dividends) / window[0]["close"] - 1


def build_brief(data, source_hash):
    if digest(data) != source_hash:
        raise ValueError("Brief source hash mismatch")
    day = data["case"]["decision_date"]
    if any(timestamp(r["available_at"]) > cutoff(day) for r in data["records"]):
        raise ValueError("Future evidence in brief")
    facts = []

    def add(identity, value, unit, as_of, available, kind, locator, **details):
        if as_of > day or timestamp(available) > cutoff(day) or not math.isfinite(value):
            raise ValueError("Invalid or future brief fact")
        facts.append(dict(id=identity, value=round(float(value), 6), unit=unit, as_of=as_of,
                          available_at=available, kind=kind, source_locator=locator, **details))

    ticker = data["case"]["ticker"]
    returns = {}
    for symbol in (ticker, "SPY"):
        rows = sorted(data["prices"].get(symbol, []), key=lambda r: r["date"])
        if not rows or len({r["date"] for r in rows}) != len(rows) or rows[-1]["date"] > day:
            raise ValueError("Missing, duplicated or future prices in brief")
        latest = rows[-1]["date"]
        available = cutoff(latest).isoformat()
        add(f"{symbol}.close", rows[-1]["close"], "USD/share", latest, available, "prices", f"prices/{symbol}/{latest}/close")
        for n in (5, 20, 60):
            value = total_return(rows, n)
            if value is not None:
                returns[symbol, n] = value
                add(f"{symbol}.return{n}", value, "fraction_total_return", latest, available,
                    "prices", f"prices/{symbol}/{rows[-n-1]['date']}..{latest}", sessions=n,
                    calculation="Buy at first close, apply subsequent splits and cash dividends, mark at last close; no dividend reinvestment or trading costs.")
        if len(rows) >= 21:
            daily = [total_return(rows[i-1:i+1], 1) for i in range(len(rows)-20, len(rows))]
            mean = sum(daily) / len(daily)
            vol = math.sqrt(sum((x-mean)**2 for x in daily) / (len(daily)-1))
            add(f"{symbol}.daily_vol20", vol, "fraction_daily_sample_std", latest, available,
                "prices", f"prices/{symbol}/{rows[-21]['date']}..{latest}")
    for n in (5, 20, 60):
        if (ticker, n) in returns and ("SPY", n) in returns:
            # Same dates are essential when subtracting horizon returns.
            stock_dates = [r['date'] for r in data['prices'][ticker]][-n-1:]
            spy_dates = [r['date'] for r in data['prices']['SPY']][-n-1:]
            if stock_dates != spy_dates:
                raise ValueError("Stock and benchmark sessions differ")
            add(f"{ticker}.excess{n}", returns[ticker, n]-returns['SPY', n], "fraction_vs_SPY",
                stock_dates[-1], cutoff(stock_dates[-1]).isoformat(), "prices",
                f"derived/{ticker}.return{n}-SPY.return{n}")
    for index, record in enumerate(data['records']):
        if record['kind'] == 'sec':
            groups = defaultdict(list)
            for fact_index, fact in enumerate(record['content']):
                if fact['filed'] > day or fact['end'] > day:
                    raise ValueError('Future SEC fact in brief')
                groups[fact['tag'], fact['unit']].append((fact_index, fact))
            for (tag, unit), values in sorted(groups.items()):
                # Latest reporting period, then latest eligible filing; never assume
                # that a legacy XBRL tag was still current at the decision date.
                fact_index, fact = max(values, key=lambda v: (v[1]['end'], v[1]['filed'], v[1].get('start', ''), v[0]))
                age = (date.fromisoformat(day)-date.fromisoformat(fact['end'])).days
                add(f"SEC.{tag}.{unit}", fact['val'], unit, fact['end'], cutoff(fact['filed']).isoformat(),
                    'sec', f"records/{index}/content/{fact_index}", filed=fact['filed'],
                    period_start=fact.get('start'), form=fact['form'], age_days=age,
                    stale_over_180_days=age > 180, accession=fact['accn'])
        elif record['kind'] == 'fred':
            content = record['content']
            available = record['available_at']
            observations = content['observations']
            if not observations:
                continue
            obs = max(observations, key=lambda x: x['observation_date'])
            columns = [k for k in obs if k != 'observation_date']
            if len(columns) != 1:
                raise ValueError('Ambiguous FRED vintage value')
            unit = {'CPIAUCSL': 'index_1982_84_100', 'DFF': 'percent_per_year'}.get(content['series'], 'source_units_unspecified')
            add(f"FRED.{content['series']}", obs[columns[0]], unit, obs['observation_date'], available,
                'fred', f"records/{index}/content/observations/{observations.index(obs)}", vintage=content['vintage'])
    if len({f['id'] for f in facts}) != len(facts):
        raise ValueError('Duplicate brief fact identifiers')
    view = {"schema": 1, "case_id": data['case']['case_id'], "source_evidence_sha256": source_hash,
                "decision_date": day, "facts": facts, "missing_sources": list(MISSING),
                "scope": 'Prescribed numeric features only; excludes raw histories. Not a news-driven event study.',
                "limitations": ['Historical vendor corrections remain possible.',
                             'SEC tags may be obsolete; inspect reporting period and age.',
                             'Past returns are observations, not five-session forecasts.']}
    return {**view, 'view_sha256': digest(view)}


def brief_prompt(view, mode):
    if mode not in MODES:
        raise ValueError('Unknown evidence mode')
    prompt = ('\n\nCOMMON FROZEN DECISION BRIEF\n' + json.dumps(view, separators=(',', ':')) + '\n'
              'Every role and treatment receives this exact information set. Tools can only repeat its facts or report missing data. '
              'Analyze this limited-data scenario. Missing news is an explicit limitation, not a request for live retrieval. '
              'Do not supply remembered earnings, product, CPI-release, FOMC or election-result details: no event calendar or news is supplied. '
              'A historical return is not a forecast. Treat old reporting periods as stale, even when the filing is available. '
              'Use percentages for allocations; an authoritative receipt will compute dollar amounts and entry fees after your decision. '
              'Your explanation must not promise stop-loss, conditional or intraday execution.\n')
    if mode == 'cited-evidence':
        prompt += ('CITATION CONTRACT: In citations, copy the fact_id, value, unit and as_of date of the observations your decision relies on, exactly as supplied. '
                   'Cite fact IDs beside factual assertions in your prose. Label forecasts and opinions explicitly as judgments. '
                   'An executable decision must cite at least one stock-price fact and one SPY-price fact. '
                   'In evidence_gaps, list exactly the five missing_sources identifiers. '
                   'The harness records the brief hash as provenance; do not copy hashes into any output field. '
                   'An abstention may have an empty citation list. Invalid citations will block execution; never invent supporting facts.\n')
    return prompt


class Citation(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    fact_id: str
    value: float
    unit: str
    as_of: str


class CitedDecision(ExecutionDecision):
    citations: list[Citation] = Field(description='Observed facts relied on, copied exactly from the brief; not forecasts or calculations invented by the model.')
    evidence_gaps: list[Literal['news', 'social', 'event_calendar', 'insiders', 'prediction_markets']] = Field(
        description='Exactly the five missing_sources identifiers from the brief. Provenance hashes are recorded by the harness, not generated by the model.')


def assess_citations(payload, view):
    from pydantic import ValidationError
    try:
        decision = CitedDecision.model_validate(payload)
    except (ValidationError, TypeError):
        return {'valid': False, 'reasons': ['invalid_citation_schema'], 'checked_citations': 0}
    reasons = []
    if sorted(decision.evidence_gaps) != sorted(view['missing_sources']):
        reasons.append('missing_or_invented_gap')
    facts = {f['id']: f for f in view['facts']}
    identifiers = [c.fact_id for c in decision.citations]
    if len(set(identifiers)) != len(identifiers):
        reasons.append('duplicate_citation')
    for c in decision.citations:
        fact = facts.get(c.fact_id)
        if fact is None or any(getattr(c, k) != fact[k] for k in ('value', 'unit', 'as_of')):
            reasons.append('unresolved_or_mismatched_citation:' + c.fact_id)
    if decision.order.kind == 'next_close':
        for symbol in (decision.mandate.ticker, 'SPY'):
            if not any(facts.get(k, {}).get('kind') == 'prices' and k.startswith(symbol + '.') for k in identifiers):
                reasons.append('missing_price_citation:' + symbol)
    return {'valid': not reasons, 'reasons': reasons, 'checked_citations': len(identifiers),
            'scope': 'Exact cited observations only; not exhaustive prose truth or causal support.'}

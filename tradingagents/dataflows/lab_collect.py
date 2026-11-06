"""Network-enabled collection phase. Replay never imports this module."""
from __future__ import annotations

import argparse
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

from tradingagents.lab.evidence import EvidenceStore, canonical, cutoff, digest, outcome
from tradingagents.lab.protocol import FREEZE, STOCKS, calendar_sessions, cases

CIKS = {"AAPL": "0000320193", "MSFT": "0000789019", "NVDA": "0001045810",
        "JPM": "0000019617", "XOM": "0000034088", "UNH": "0000731766"}
TAGS = {"Assets", "Liabilities", "CashAndCashEquivalentsAtCarryingValue", "NetIncomeLoss",
        "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "EarningsPerShareDiluted",
        "NetCashProvidedByUsedInOperatingActivities", "StockholdersEquity"}


def raw_prices(ticker, end=FREEZE):
    frame = yf.Ticker(ticker).history(start="2018-01-01", end=(datetime.fromisoformat(end) + timedelta(days=1)).date().isoformat(),
                                      auto_adjust=False, actions=True, raise_errors=True)
    if frame.empty:
        raise RuntimeError(f"No prices for {ticker}")
    # Yahoo's unadjusted close still adjusts old shares for later splits.
    # Reconstruct then-current units from the separately frozen split history.
    splits = frame["Stock Splits"].replace(0, 1)
    future = splits.iloc[::-1].cumprod().iloc[::-1] / splits
    rows = []
    for (date, row), factor in zip(frame.iterrows(), future, strict=True):
        rows.append({"date": date.strftime("%Y-%m-%d"),
                     **{key.lower(): float(row[key] * factor) for key in ["Open", "High", "Low", "Close"]},
                     "volume": float(row["Volume"] / factor), "split": float(row["Stock Splits"] or 1),
                     "dividend": float(row["Dividends"] * factor)})
    return rows


def sec_facts(ticker):
    from tradingagents.dataflows.vendors.sec_edgar import _fetch_json
    return _fetch_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIKS[ticker]}.json")


def as_filed(facts, day):
    result = []
    for tag, fact in facts.get("facts", {}).get("us-gaap", {}).items():
        if tag not in TAGS:
            continue
        for unit, items in fact.get("units", {}).items():
            eligible = [f for f in items if f["filed"] <= day and f["end"] <= day]
            # Retain actual accession and filing date for every displayed number.
            latest = {}
            for item in sorted(eligible, key=lambda f: f["filed"]):
                latest[(item.get("start"), item["end"])] = item
            for item in sorted(latest.values(), key=lambda f: f["end"])[-6:]:
                result.append({"tag": tag, "unit": unit, **item})
    return result


def fred_vintage(series, day):
    url = "https://alfred.stlouisfed.org/graph/alfredgraph.csv"
    response = requests.get(url, params={"id": series, "cosd": str(int(day[:4]) - 2) + day[4:],
                                         "coed": day, "vintage_date": day}, timeout=40)
    response.raise_for_status()
    frame = pd.read_csv(io.StringIO(response.text))
    expected = series + "_" + day.replace("-", "")
    if expected not in frame.columns:
        raise ValueError("ALFRED did not confirm requested vintage in CSV header")
    frame = frame.dropna().tail(24)
    return {"series": series, "vintage": day, "observations": json.loads(frame.to_json(orient="records"))}


def collect(root):
    root = Path(root)
    store = EvidenceStore(root)
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for key in manifest["cases"].values():
            store.get(key)
        return manifest
    now = datetime.now(UTC).isoformat()
    sources, errors, collection_times = {}, {}, {}

    def cached(name, fetch):
        path = root / "collection" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            saved = json.loads(path.read_text())
            sources[name] = store.put(saved)
            collection_times[name] = saved["collected_at"]
            return saved["data"]
        try:
            data = fetch()
        except Exception as exc:
            errors[name] = f"{type(exc).__name__}: {exc}"
            return None
        path.write_bytes(canonical({"collected_at": now, "data": data}))
        sources[name] = store.put({"collected_at": now, "data": data})
        collection_times[name] = now
        return data

    prices = {t: cached(f"prices-{t}", lambda t=t: raw_prices(t)) for t in [*STOCKS, "SPY"]}
    if any(not rows for rows in prices.values()):
        raise RuntimeError(f"Price collection incomplete: {errors}")
    facts = {t: cached(f"sec-{t}", lambda t=t: sec_facts(t)) for t in STOCKS}
    sessions = calendar_sessions()
    index, outcomes, coverage = {}, {}, []
    for case in cases():
        day, ticker = case["decision_date"], case["ticker"]
        records = []
        if facts[ticker]:
            items = as_filed(facts[ticker], day)
            if items:
                records.append({"kind": "sec", "source": f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIKS[ticker]}.json",
                                "available_at": cutoff(max(f["filed"] for f in items)).isoformat(),
                                "collected_at": collection_times[f"sec-{ticker}"], "redistributable": True, "content": items})
        for series in ["CPIAUCSL", "DFF"]:
            value = cached(f"fred-{series}-{day}", lambda s=series, d=day: fred_vintage(s, d))
            if value:
                records.append({"kind": "fred", "source": "https://alfred.stlouisfed.org",
                                "available_at": cutoff(day).isoformat(), "collected_at": collection_times[f"fred-{series}-{day}"],
                                "redistributable": False, "content": value})
        records.append({"kind": "prices", "source": "Yahoo Finance via yfinance; prices and actions as collected",
                        "available_at": cutoff(day).isoformat(), "collected_at": collection_times[f"prices-{ticker}"],
                        "redistributable": False, "content": "Historical prices can contain vendor corrections. Raw units restored from split history."})
        present = {r["kind"] for r in records}
        missing = [s for s in ["sec", "fred", "news", "global_news", "reddit", "stocktwits", "identity", "insiders", "prediction_markets"] if s not in present]
        case = {**case, "missing_sources": missing}
        # Actors receive only own ticker + SPY and never post-cutoff rows.
        actor_prices = {t: [r for r in prices[t] if r["date"] <= day] for t in [ticker, "SPY"]}
        index[case["case_id"]] = store.bundle(case, records, actor_prices)
        outcomes[case["case_id"]] = {
            str(h): {"stock": outcome(prices[ticker], day, h, sessions, FREEZE),
                     "benchmark": outcome(prices["SPY"], day, h, sessions, FREEZE)} for h in [1, 5, 20]}
        coverage.append({"case_id": case["case_id"], "available": sorted(present), "missing": missing})
    outcome_path = root / "outcomes.json"
    outcome_path.write_bytes(canonical({"freeze_through": FREEZE, "cases": outcomes, "prices": prices}))
    manifest = {"schema": 1, "freeze_through": FREEZE, "collected_at": now, "cases": index,
                "sources": sources, "coverage": coverage, "collection_errors": errors,
                "outcomes_sha256": digest(json.loads(outcome_path.read_text()))}
    manifest["version"] = digest(manifest)
    manifest_path.write_bytes(canonical(manifest))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="lab-data/election-v1")
    args = parser.parse_args()
    result = collect(args.root)
    print(json.dumps({"version": result["version"], "cases": len(result["cases"]), "errors": result["collection_errors"]}, indent=2))

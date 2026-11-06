"""Snapshot-only data access and a model/export-only network allowlist."""
from __future__ import annotations

import json
import socket
from contextlib import ExitStack, contextmanager
from functools import lru_cache
from unittest.mock import patch
from urllib.parse import urlparse

from tradingagents.dataflows.config import get_config
from tradingagents.lab.evidence import EvidenceStore, cutoff, timestamp
from tradingagents.observability.agent_lens import trace_data


@lru_cache(maxsize=32)
def _load(root, key):
    return EvidenceStore(root).get(key)


def bundle():
    cfg = get_config()
    if not cfg.get("replay_evidence"):
        return None
    data = _load(cfg["replay_root"], cfg["replay_evidence"])
    end = cutoff(data["case"]["decision_date"])
    if any(timestamp(r["available_at"]) > end for r in data["records"]):
        raise ValueError("Future evidence in replay")
    return data


def unavailable(source):
    return f"DATA_UNAVAILABLE: {source} is absent from this frozen evidence bundle. Do not infer or invent it."


@trace_data
def read(method, *args, **kwargs):
    data = bundle()
    if data is None:
        raise RuntimeError("Replay requires a frozen evidence bundle")
    day, ticker = data["case"]["decision_date"], data["case"]["ticker"]
    # Reject future requests; do not silently clamp a benchmark's leakage.
    values = list(args) + list(kwargs.values())
    for value in values:
        if isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-" and value > day:
            raise ValueError("Future request rejected by replay cutoff")
    symbol = args[0] if args and args[0] in data["prices"] else ticker
    rows = data["prices"].get(symbol, [])
    if any(r["date"] > day for r in rows):
        raise ValueError("Future prices in replay")
    if method == "identity":
        matches = [r for r in data["records"] if r["kind"] == "identity"]
        return matches[-1]["content"] if matches else {}
    if view := get_config().get("replay_view"):
        # A frozen experiment may expose a smaller common information set.
        # Every data path must respect it; never fall through to the full bundle.
        if (view["source_evidence_sha256"] != get_config()["replay_evidence"]
                or view["case_id"] != data["case"]["case_id"]):
            raise ValueError("Replay view belongs to different evidence")
        if any(timestamp(f["available_at"]) > cutoff(day) or f["as_of"] > day
               for f in view["facts"]):
            raise ValueError("Future evidence in replay view")
        kinds = {"get_stock_data": "prices", "get_indicators": "prices",
                 "get_verified_market_snapshot": "prices", "get_fundamentals": "sec",
                 "get_balance_sheet": "sec", "get_cashflow": "sec",
                 "get_income_statement": "sec", "get_macro_indicators": "fred"}
        selected = [f for f in view["facts"] if f["kind"] == kinds.get(method)]
        return json.dumps({"requested_tool": method, "view_sha256": view["view_sha256"],
                           "status": "prescribed_features_only" if selected else "DATA_UNAVAILABLE",
                           "facts": selected, "missing_sources": view["missing_sources"],
                           "notice": "Only this common decision brief is available. No hidden raw history, news or event calendar may be inferred."})
    if method == "get_stock_data":
        start, end = args[1:3]
        selected = [r for r in rows if start <= r["date"] <= end]
        return json.dumps(selected) if selected else unavailable(method)
    if method in {"get_indicators", "get_verified_market_snapshot"}:
        import pandas as pd
        from stockstats import StockDataFrame
        if not rows:
            return unavailable(method)
        requested = args[2] if method == "get_indicators" else args[1]
        frame = pd.DataFrame([r for r in rows if r["date"] <= requested]).set_index("date")
        if frame.empty:
            return unavailable(method)
        # Indicators use a split-adjusted series through the cutoff.
        # The raw last row is separately shown for exact current-price claims.
        raw = frame.iloc[-1].to_dict()
        closes = frame["close"]
        splits = frame["split"].replace(0, 1)
        future_factors = splits.iloc[::-1].cumprod().iloc[::-1] / splits
        for col in ["open", "high", "low", "close"]:
            frame[col] = frame[col] / future_factors
        ss = StockDataFrame.retype(frame)
        names = [args[1]] if method == "get_indicators" else ["close_20_sma", "close_50_sma", "rsi", "macd", "boll_ub", "boll_lb"]
        aliases = {"close_50_sma": "close_50_sma", "close_200_sma": "close_200_sma", "close_10_ema": "close_10_ema"}
        values = {}
        for name in names:
            try:
                values[name] = float(ss[aliases.get(name, name)].iloc[-1])
            except (KeyError, ValueError, AttributeError):
                values[name] = unavailable(name)
        return json.dumps({"as_of": str(frame.index[-1]), "raw_last_row": raw,
                           "indicators": values, "recent_closes": closes.tail(30).to_dict()}, default=str)
    kinds = {
        "get_fundamentals": "sec", "get_balance_sheet": "sec", "get_cashflow": "sec",
        "get_income_statement": "sec", "get_news": "news", "get_global_news": "global_news",
        "get_insider_transactions": "insiders", "get_macro_indicators": "fred",
        "get_prediction_markets": "prediction_markets", "reddit": "reddit", "stocktwits": "stocktwits",
    }
    records = [r for r in data["records"] if r["kind"] == kinds.get(method, method)]
    if method == "get_macro_indicators":
        aliases = {"cpi": "CPIAUCSL", "fed_funds_rate": "DFF"}
        requested = aliases.get(args[0], args[0])
        records = [r for r in records if r["content"]["series"] == requested]
    return json.dumps(records, ensure_ascii=False) if records else unavailable(method)


@contextmanager
def network_guard(allowed_hosts=()):
    """Process-wide guard for a serial replay worker and its parallel analysts.

    Actors can call their model endpoint. Persistence/export runs outside this
    context; no wildcard hosts, redirects, arbitrary sockets, or proxy bypass.
    """
    hosts = set(allowed_hosts)
    ips = set()
    resolve, connect = socket.getaddrinfo, socket.socket.connect

    def check_url(url):
        host = urlparse(str(url)).hostname
        if host not in hosts:
            raise RuntimeError(f"Replay blocked network access to {host}")

    def guarded_dns(host, *args, **kwargs):
        if host not in hosts:
            raise RuntimeError(f"Replay blocked DNS access to {host}")
        result = resolve(host, *args, **kwargs)
        ips.update(item[4][0] for item in result)
        return result

    def guarded_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ips and address[0] not in hosts:
            raise RuntimeError("Replay blocked socket access")
        return connect(sock, address)

    import httpx
    import requests
    from curl_cffi.requests import Session
    http_send, request, curl_request = httpx.Client.send, requests.Session.request, Session.request

    def send(client, req, *args, **kwargs):
        check_url(req.url)
        return http_send(client, req, *args, **kwargs)

    def req(client, method, url, *args, **kwargs):
        check_url(url)
        return request(client, method, url, *args, **kwargs)

    def curl(client, method, url, *args, **kwargs):
        check_url(url)
        return curl_request(client, method, url, *args, **kwargs)

    with ExitStack() as stack:
        for obj, name, value in [(socket, "getaddrinfo", guarded_dns), (socket.socket, "connect", guarded_connect),
                                 (httpx.Client, "send", send), (requests.Session, "request", req), (Session, "request", curl)]:
            stack.enter_context(patch.object(obj, name, value))
        yield

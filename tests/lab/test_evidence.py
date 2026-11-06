import json
import socket

import pytest
import requests

from tradingagents.lab.evidence import EvidenceStore, cutoff, outcome
from tradingagents.lab.protocol import cases
from tradingagents.lab.replay import network_guard


def test_membership_and_calendar():
    pytest.importorskip("exchange_calendars")
    sample = cases()
    assert len(sample) == len({c["case_id"] for c in sample}) == 60
    assert {c["decision_date"] for c in sample if c["cohort"] == "midterms-2026"} == {"2026-11-02", "2026-11-04"}


def test_integrity_and_availability(tmp_path):
    store = EvidenceStore(tmp_path)
    case = {"decision_date": "2022-11-07"}
    future = {"available_at": cutoff("2022-11-08").isoformat(), "collected_at": cutoff("2026-11-06").isoformat()}
    with pytest.raises(ValueError, match="Future"):
        store.bundle(case, [future], {})
    with pytest.raises(ValueError, match="Future prices"):
        store.bundle(case, [], {"AAPL": [{"date": "2022-11-08"}]})
    key = store.bundle(case, [], {})
    path = tmp_path / "objects" / f"{key}.json"
    path.write_text(json.dumps({"edited": True}))
    with pytest.raises(ValueError, match="integrity"):
        store.get(key)


def test_network_blocked_without_model_allowlist():
    with network_guard():
        with pytest.raises(RuntimeError, match="blocked"):
            requests.get("https://query1.finance.yahoo.com")
        with pytest.raises(RuntimeError, match="blocked"):
            socket.getaddrinfo("example.com", 443)


def test_entry_delay_dividend_split_and_pending():
    sessions = [f"2024-01-{i:02d}" for i in range(1, 12)]
    rows = [{"date": d, "close": 100, "split": 1, "dividend": 0} for d in sessions]
    rows[0]["close"] = 20  # decision date is not execution price
    rows[2].update(close=50, split=2, dividend=1)
    result = outcome(rows, sessions[0], 1, sessions, sessions[-1])
    assert result["return"] == pytest.approx(.02)
    assert outcome(rows, sessions[0], 5, sessions, sessions[2])["status"] == "pending"

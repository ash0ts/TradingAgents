"""Content-addressed evidence, with availability separate from collection time."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def cutoff(day):
    return datetime.fromisoformat(day + "T23:59:59").replace(tzinfo=NY)


def timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Evidence timestamps must carry a timezone")
    return parsed


class EvidenceStore:
    def __init__(self, root):
        self.root = Path(root)

    def put(self, value):
        key = digest(value)
        path = self.root / "objects" / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self.get(key)
        else:
            # Exclusive creation prevents overwriting an existing version.
            try:
                with path.open("xb") as stream:
                    stream.write(canonical(value))
            except FileExistsError:
                self.get(key)
        return key

    def get(self, key):
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("Invalid evidence hash")
        value = json.loads((self.root / "objects" / f"{key}.json").read_bytes())
        if digest(value) != key:
            raise ValueError(f"Evidence integrity failure: {key}")
        return value

    def bundle(self, case, records, prices):
        end = cutoff(case["decision_date"])
        for record in records:
            if timestamp(record["available_at"]) > end:
                raise ValueError("Future evidence rejected")
            timestamp(record["collected_at"])
        for symbol, rows in prices.items():
            if any(row["date"] > case["decision_date"] for row in rows):
                raise ValueError(f"Future prices rejected: {symbol}")
        return self.put({"schema": 1, "case": case, "records": records, "prices": prices,
                         "study_type": "retrospective replay"})


def outcome(rows, decision_date, horizon, sessions, freeze_date):
    """Entry next close; horizon counts close-to-close holding intervals."""
    index = sessions.index(decision_date)
    entry, exit_day = sessions[index + 1], sessions[index + 1 + horizon]
    result = {"horizon": horizon, "entry_date": entry, "exit_date": exit_day}
    if exit_day > freeze_date:
        return {**result, "status": "pending", "return": None}
    prices = {row["date"]: row for row in rows}
    if any(day not in prices for day in sessions[index + 1:index + horizon + 2]):
        return {**result, "status": "missing", "return": None}
    shares, dividends = 1.0, 0.0
    for day in sessions[index + 2:index + horizon + 2]:
        row = prices[day]
        shares *= row.get("split", 1.0) or 1.0
        dividends += shares * row.get("dividend", 0.0)
    total = (shares * prices[exit_day]["close"] + dividends) / prices[entry]["close"] - 1
    return {**result, "status": "matured", "return": total}

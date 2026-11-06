"""Deterministic investigation candidates; reviewed truth is a separate record."""
from __future__ import annotations

import json
import random
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from tradingagents.agents.rating import parse_rating
from tradingagents.lab.evidence import canonical, digest


def inspect_behavior(row, bundle):
    events = row.get("events", [])
    report = row.get("report", "")
    findings = []

    def add(tag, reason, locator, status="observed"):
        findings.append({"tag": tag, "reason": reason, "locator": locator, "status": status,
                         "observer": "deterministic-v1"})

    for i, event in enumerate(events):
        if event["kind"] == "error":
            add("tool-or-model-error", event["error"], f"events/{i}")
        if event["kind"] == "tool_end" and any(s in (event.get("result") or "") for s in ["DATA_UNAVAILABLE", "NO_DATA_AVAILABLE"]):
            add("missing-tool-evidence", event.get("name", "tool"), f"events/{i}")
    counts = Counter((e.get("name"), e.get("arguments")) for e in events if e["kind"] == "tool_start")
    for (name, args), count in counts.items():
        if count > 1:
            add("repeated-tool-call", f"{name}: identical arguments {count} times: {args}", "events", "review-candidate")
    sentences = re.split(r"(?<=[.!?])\s+|\n", report)
    missing = set(bundle["case"].get("missing_sources", []))
    for source in missing & {"reddit", "stocktwits", "news"}:
        for sentence in sentences:
            if (re.search(rf"\b{source}\b", sentence, re.I)
                    and re.search(r"bullish|bearish|positive|negative|rose|fell|confirms?", sentence, re.I)
                    and not re.search(r"missing|unavailable|no\b|not\b|cannot|without|absent", sentence, re.I)):
                add("unavailable-evidence-as-fact", sentence, "report", "review-candidate")
    latest = bundle["prices"][bundle["case"]["ticker"]][-1]
    for match in re.finditer(r"(?:latest|last|current)\s+(?:closing\s+)?(?:price|close)[^$\n]{0,30}\$([\d,]+(?:\.\d+)?)", report, re.I):
        claimed = float(match.group(1).replace(",", ""))
        if abs(claimed - latest["close"]) > max(.02, latest["close"] * .001):
            add("unsupported-current-price", f"Claim {claimed}; frozen last close {latest['close']} on {latest['date']}", "report", "review-candidate")
    for sentence in sentences:
        if re.search(r"(?:win rate|historically validated|backtest.{0,20}accuracy).{0,30}\d", sentence, re.I):
            add("unsupported-performance-statistic", sentence, "report", "review-candidate")
    labels = re.findall(r"(?:\*\*)?Rating(?:\*\*)?\s*:\s*(?:\*\*)?(Buy|Overweight|Hold|Underweight|Sell)\b", report, re.I)
    if len({s.lower() for s in labels}) > 1:
        add("contradictory-recommendations", ", ".join(labels), "report", "review-candidate")
    trader = row.get("state", {}).get("trader_investment_plan", "")
    prior, final = parse_rating(trader), row.get("rating")
    valid = {"Buy", "Overweight", "Hold", "Underweight", "Sell"}
    if prior in valid and final in valid and prior != final:
        add("recommendation-changed", f"Trader {prior} → portfolio manager {final}; inspect debate for explanation", "state/trader_investment_plan")
    acknowledged = bool(re.search(r"unavailable|missing|no (?:news|social)|cannot verify|not (?:available|provided)", report, re.I))
    if missing and not acknowledged:
        add("missing-data-not-acknowledged", "Final report does not explicitly acknowledge missing sources", "report", "review-candidate")
    tool_seconds = sum(e.get("latency_s", 0) for e in events if e["kind"] == "tool_end")
    return {"findings": findings, "missing_data_acknowledged": acknowledged,
            "tool_seconds_sum": tool_seconds, "tool_runtime_note": "sum may exceed wall time under parallel execution",
            "financial_outcome_used_for_behavior": False}


def showcase_examples(rows, seed=2026):
    eligible = [r for r in rows if r.get("scores", {}).get("signed_excess_return") is not None]
    if not eligible:
        return {"strongest": None, "weakest": None, "seeded_random": None}
    ordered = sorted(eligible, key=lambda r: (r["scores"]["signed_excess_return"], r["run_key"]))
    rng = random.Random(seed)
    return {"strongest": ordered[-1]["run_key"], "weakest": ordered[0]["run_key"],
            "seeded_random": rng.choice(sorted(eligible, key=lambda r: r["run_key"]))["run_key"]}


def export_regressions(rows, reviews, destination):
    by_key = {r["run_key"]: r for r in rows}
    records = []
    for review in reviews:
        required = {"run_key", "reviewer", "reviewed_at", "label", "rationale", "evidence_locator"}
        if not required <= review.keys():
            raise ValueError("Review must identify reviewer, time, label, rationale, and evidence locator")
        row = by_key[review["run_key"]]
        if review["label"] != "confirmed-failure":
            continue
        records.append({"review": review, "case_id": row["case_id"], "treatment": row["treatment"],
                        "evidence_sha256": row["evidence_sha256"], "conversation_url": row["conversation_url"],
                        "code_revision": row["code_revision"], "split": "study-discovered-regression-not-untouched-test"})
    dataset = {"schema": 1, "records": records}
    dataset["version"] = digest(dataset)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(dataset))
    return dataset


def analyze(root, output):
    from tradingagents.lab.evidence import EvidenceStore
    store = EvidenceStore(root)
    rows = [json.loads(p.read_text()) for p in (Path(output) / "campaign").rglob("prediction.json")]
    results = {r["run_key"]: inspect_behavior(r, store.get(r["evidence_sha256"])) for r in rows}
    artifact = {"created_at": datetime.now(UTC).isoformat(), "rules_version": 1,
                "results": results, "examples": showcase_examples(rows), "llm_judge": "disabled; no reviewed calibration set yet"}
    (Path(output) / "diagnostics.json").write_bytes(canonical(artifact))
    return artifact

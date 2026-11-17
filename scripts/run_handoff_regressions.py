"""A separate, prespecified engineering regression after the frozen main campaign.

These selected cases cannot establish trading performance. No financial result is
exported or compared; all costs share the original ledger and combined $30 subcap.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from tradingagents.lab.budget import Ledger
from tradingagents.lab.evidence import canonical
from tradingagents.lab.publication import public_budget
from tradingagents.lab.runner import run_one

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "lab-data/election-v1"
OUT = REPO / "lab-runs/trader-handoff-v4"
PUBLIC = REPO / "studies/trader-handoff-v4"
PROTOCOL = PUBLIC / "protocol.json"
LEDGER = REPO / "lab-runs/election-v1/budget.sqlite"
JOBS = [
    (c, m, t)
    for c in ("control-2023-after-UNH", "control-2025-after-UNH")
    for m in ("shared-evidence", "cited-evidence")
    for t in ("default-committee", "luna-committee")
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze():
    assert not PROTOCOL.exists(), "Preserve the frozen protocol"
    previous = json.loads(
        (REPO / "studies/common-evidence-v3-repaired/verification.json").read_text()
    )
    assert previous["executions"] == 360
    sources = sorted((REPO / "tradingagents").rglob("*.py")) + [Path(__file__).resolve()]
    data = {
        "study_kind": "Selected development engineering regression, not a financial comparison or untouched test.",
        "frozen_at": datetime.now(UTC).isoformat(),
        "problem": "The legacy trader explicitly maps Underweight to Sell and Overweight to Buy; those three actions conflict with the five allocation buckets in the fresh-cash evaluation mandate.",
        "change": "Use a five-rating typed trader proposal only in execution-contract mode, preserve its exact mandate and order conditions, reject action/weight disagreement, and remove the final manager’s incompatible existing-holding definitions.",
        "jobs": JOBS,
        "selection_sha256": sha(PUBLIC / "selection.json"),
        "trials_per_job": 1,
        "retries": 0,
        "models": {"quick": "gpt-6-luna", "default_deep": "gpt-6-sol", "other_deep": "gpt-6-luna"},
        "evidence": "Exactly the main campaign’s frozen common brief; no new news, prices, outcomes or model parameters.",
        "main_results_sha256": sha(REPO / "studies/common-evidence-v3-repaired/results.json"),
        "checks": [
            "actual trader request/schema uses five ratings",
            "no legacy Underweight-to-Sell instruction",
            "proposed mandate matches",
            "proposed action and next-close weight match",
            "explicit conditions preserved",
            "final order gate",
            "native parentage/evaluation links/usage/exact brief",
            "exact private OTLP journal IDs equal hosted span IDs",
        ],
        "observability_change": "Opt-in local journal of actual ended native spans, retaining original IDs, parentage and timestamps. It cannot recover the earlier unjournaled export gap.",
        "financial_results_exported": False,
        "budget": {
            "global_cap_usd": 250,
            "combined_evidence_model_cap_usd": 30,
            "ledger_prefix": "election-evidence-v3/",
        },
        "source_sha256": {str(p.relative_to(REPO)): sha(p) for p in sources},
        "evidence_manifest_sha256": sha(ROOT / "manifest.json"),
        "outcomes_sha256": sha(ROOT / "outcomes.json"),
    }
    PUBLIC.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    PROTOCOL.write_bytes(canonical(data))
    print(json.dumps({"jobs": len(JOBS), "protocol_sha256": sha(PROTOCOL)}))


def validate():
    p = json.loads(PROTOCOL.read_text())
    assert all(sha(REPO / f) == s for f, s in p["source_sha256"].items()), "Frozen source drift"
    assert sha(ROOT / "manifest.json") == p["evidence_manifest_sha256"]
    assert sha(ROOT / "outcomes.json") == p["outcomes_sha256"]
    assert (
        sha(REPO / "studies/common-evidence-v3-repaired/results.json") == p["main_results_sha256"]
    )
    return p


def job(args):
    validate()
    os.environ["TRADINGAGENTS_TRACE_JOURNAL"] = str(OUT / "trace-journal")
    case, mode, treatment = args
    return run_one(
        ROOT,
        OUT / mode,
        case,
        treatment,
        0,
        "campaign",
        campaign_id="election-evidence-v3/handoff-regression/" + mode,
        execution_contract=True,
        evidence_mode=mode,
        budget_path=LEDGER,
        budget_prefix="election-evidence-v3/",
        campaign_cap_usd=30,
        sleeves=6,
    )


def run():
    validate()
    launch = OUT / "launch.json"
    if not launch.exists():
        launch.write_bytes(
            canonical(
                {
                    "actor_code_revision": subprocess.check_output(
                        ["git", "rev-parse", "HEAD"], text=True
                    ).strip(),
                    "protocol_sha256": sha(PROTOCOL),
                    "started_at": datetime.now(UTC).isoformat(),
                    "workers": 4,
                }
            )
        )
    with ProcessPoolExecutor(
        max_workers=4, mp_context=multiprocessing.get_context("spawn"), max_tasks_per_child=1
    ) as pool:
        futures = [pool.submit(job, args) for args in JOBS]
        for future in as_completed(futures):
            row = future.result()
            print(
                json.dumps(
                    {
                        k: row.get(k)
                        for k in (
                            "case_id",
                            "evidence_mode",
                            "treatment",
                            "status",
                            "cost_upper_usd",
                            "error",
                        )
                    }
                ),
                flush=True,
            )
    print(json.dumps(public_budget(Ledger(LEDGER))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["freeze", "run"])
    args = parser.parse_args()
    freeze() if args.command == "freeze" else run()

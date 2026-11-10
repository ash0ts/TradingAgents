"""Freeze and run the contract-v2 development study against original evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path

from tradingagents.lab.budget import Ledger, choose_design
from tradingagents.lab.evidence import canonical
from tradingagents.lab.protocol import STOCKS, cases
from tradingagents.lab.runner import TREATMENTS, run_one

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "lab-data/election-v1"
OUT = REPO / "lab-runs/election-contract-v2"
LEDGER = REPO / "lab-runs/election-v1/budget.sqlite"
PROTOCOL = REPO / "studies/execution-contract-v2/protocol.json"
CAMPAIGN = "election-contract-v2"
CAP = 30
QUALIFICATION_CASE = "midterms-2022-before-UNH"
SOURCES = [
    "tradingagents/lab/execution.py", "tradingagents/lab/runner.py",
    "tradingagents/lab/budget.py", "tradingagents/lab/portfolio.py",
    "tradingagents/agents/managers/portfolio_manager.py",
    "tradingagents/agents/state.py", "tradingagents/graph/trading_graph.py",
    "scripts/run_corrected_campaign.py", "notebooks/requirements.lock",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze():
    PROTOCOL.parent.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    if PROTOCOL.exists():
        raise RuntimeError("Protocol already frozen; preserve it and validate before resuming")
    manifest = json.loads((ROOT / "manifest.json").read_text())
    protocol = {
        "campaign_id": CAMPAIGN, "frozen_at": datetime.now(UTC).isoformat(),
        "question": "Does a common historical mandate plus an explicit executable decision prevent the observed contract failures, and how do allocations and exploratory returns change?",
        "decision": "Verify the interface fix before planning a registered forward study.",
        "study_kind": "Development rerun of previously inspected retrospective cases; not untouched or forward test evidence.",
        "changes": ["Shared date, horizon, benchmark and fresh-cash mandate at every role",
                    "Same typed final-decision schema for committee and single analyst",
                    "Conditional, malformed or mismatched orders fail closed into cash",
                    "No directional grade for rejected contracts or other horizons"],
        "controls": "Original v1 executions and all original numerical/passive baselines are retained without rescoring or retraining.",
        "membership": cases(), "treatments": TREATMENTS, "target_trials": 2,
        "qualification": {"case_id": QUALIFICATION_CASE, "treatments": TREATMENTS, "trials": 1},
        "design_selection": "Use qualification cost only with a 2x margin; choose 6 stocks/2 trials, 6/1, 3/2, or 3/1. Three-stock fallback is MSFT/JPM/XOM. All cohorts and treatments retained.",
        "budget": {"additional_cap_usd": CAP, "global_cap_usd": 250,
                   "shared_ledger": "../../lab-runs/election-v1/budget.sqlite",
                   "initial_totals": Ledger(LEDGER).totals(),
                   "unknown_usage": "Keep full reservations; never reset the original infrastructure holds"},
        "actor_settings": {"quick": "gpt-6-luna", "default_deep": "gpt-6-sol",
                           "other_deep": "gpt-6-luna", "max_output_tokens": 4096,
                           "sdk_retries": 0, "trials_are_independent_market_observations": False,
                           "llm_judge": None},
        "prices_verified_on": "2026-11-09",
        "price_sources": ["https://developers.openai.com/api/docs/models/gpt-6-luna",
                          "https://developers.openai.com/api/docs/models/gpt-6-sol"],
        "evidence_version": manifest["version"], "freeze_through": manifest["freeze_through"],
        "evidence_manifest_sha256": sha(ROOT / "manifest.json"),
        "outcomes_sha256": sha(ROOT / "outcomes.json"),
        "source_sha256": {p: sha(REPO / p) for p in SOURCES},
        "metrics": {
            "contract_acceptance": "Accepted typed decisions / all requested executions; report explicit abstention, blocked conditions, invalid contract and actor failures separately.",
            "financial": "Independent $100,000 scenarios, equal stock sleeves, next close entry, five sessions, 10 bps per side; additional 0/5/25 bps sensitivities. Never compound overlapping scenarios.",
            "directional": "Accepted Buy/Overweight/Underweight/Sell decisions with matured outcomes only; report denominator and coverage. Hold has no directional forecast.",
            "paired": "Pair the same case/date/treatment/trial with v1. Collapse trials before cohort-block uncertainty; only four matured cohorts.",
            "missing": "Pending horizons remain null. Rejected/abstaining sleeves hold cash, not invented conditional fills. Failures are not successful abstentions.",
        },
        "review": "Inspect all five discovered development cases in both trials, across treatments; raw reports are private. Typed agreement alone does not establish semantic agreement or investment quality.",
        "stop": "Stop new launches at a budget failure or source drift. Do not retry uncertain starts or tune prompts after campaign outcomes.",
        "privacy": "Source snapshots and complete model reports remain in the existing private evidence project. Public outputs use derived metrics and selected short excerpts.",
        "limitations": ["Retrospective pretrained knowledge", "Same previously inspected market cases",
                        "Missing archived news remains missing", "Committee/tool and single/bundle evidence delivery differs",
                        "Bundled prompt/schema/gate change does not identify each component's causal effect",
                        "No conditional-order execution is implemented; unsupported instructions hold cash"],
        "reproduce": "python scripts/run_corrected_campaign.py qualify; python scripts/run_corrected_campaign.py select; python scripts/run_corrected_campaign.py run",
    }
    PROTOCOL.write_bytes(canonical(protocol))
    print(json.dumps({"protocol": str(PROTOCOL.relative_to(REPO)), "sha256": sha(PROTOCOL)}))


def validate():
    protocol = json.loads(PROTOCOL.read_text())
    for p, digest in protocol["source_sha256"].items():
        if sha(REPO / p) != digest:
            raise RuntimeError(f"Frozen source changed: {p}")
    assert sha(ROOT / "manifest.json") == protocol["evidence_manifest_sha256"]
    assert sha(ROOT / "outcomes.json") == protocol["outcomes_sha256"]
    return protocol


def job(case_id, treatment, trial, phase, sleeves):
    validate()
    return run_one(ROOT, OUT, case_id, treatment, trial, phase,
                   campaign_id=CAMPAIGN, execution_contract=True, budget_path=LEDGER,
                   campaign_cap_usd=CAP, sleeves=sleeves)


def run(jobs, workers):
    context = multiprocessing.get_context("spawn")
    jobs = iter(jobs)
    complete, stopped = 0, False
    with ProcessPoolExecutor(max_workers=workers, mp_context=context, max_tasks_per_child=1) as pool:
        pending = {}

        def launch():
            args = next(jobs, None)
            if args is not None:
                pending[pool.submit(job, *args)] = args

        for _ in range(workers):
            launch()
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                args = pending.pop(future)
                try:
                    row = future.result()
                    complete += 1
                    print(json.dumps({"complete": complete, "case_id": row["case_id"],
                                      "treatment": row["treatment"], "trial": row["trial"],
                                      "status": row["status"], "contract": row["execution_check"]["status"],
                                      "cost_usd": row["cost_upper_usd"], "error": row.get("error")}), flush=True)
                    if "Budget" in row.get("error", ""):
                        stopped = True
                except Exception as exc:
                    print(json.dumps({"job": args, "dispatch_error": str(exc)}), flush=True)
                    stopped = True
                if not stopped:
                    launch()
    if stopped:
        raise RuntimeError("Campaign stopped; inspect preserved attempts before any continuation")


def select():
    rows = [json.loads(p.read_text()) for p in (OUT / "qualification").rglob("prediction.json")]
    assert len(rows) == len(TREATMENTS)
    if any(r["status"] != "success" or r["execution_check"]["status"] == "invalid_contract" for r in rows):
        raise RuntimeError("Qualification did not establish the contract; inspect saved outputs")
    costs = {r["treatment"]: r["cost_upper_usd"] for r in rows}
    design = choose_design(costs, allowance=CAP - sum(costs.values()))
    design.update(campaign_id=CAMPAIGN, execution_contract=True, protocol_sha256=sha(PROTOCOL))
    (OUT / "design.json").write_bytes(canonical(design))
    print(json.dumps(design, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["freeze", "qualify", "select", "run"])
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze()
    else:
        validate()
        if args.command == "select":
            select()
        elif args.command == "qualify":
            run([(QUALIFICATION_CASE, t, 0, "qualification", 6) for t in TREATMENTS], min(args.workers, 3))
        else:
            design = json.loads((OUT / "design.json").read_text())
            assert design["protocol_sha256"] == sha(PROTOCOL)
            stocks = STOCKS if design["stocks"] == 6 else ["MSFT", "JPM", "XOM"]
            run([(c["case_id"], t, trial, "campaign", len(stocks))
                 for trial in range(design["trials"]) for c in cases(stocks) for t in TREATMENTS], args.workers)

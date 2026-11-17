"""Frozen, repeated, all-Luna stage ablations; original ledger and no actor retries."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import multiprocessing
import os
import random
import subprocess
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.lab.brief import build_brief
from tradingagents.lab.budget import Ledger
from tradingagents.lab.evidence import EvidenceStore, canonical
from tradingagents.lab.protocol import STOCKS, cases
from tradingagents.lab.runner import run_one

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "lab-data/election-v1"
OUT = REPO / "lab-runs/debate-ablation-v5"
PUBLIC = REPO / "studies/debate-ablation-v5"
PROTOCOL = PUBLIC / "protocol.json"
LEDGER = REPO / "lab-runs/election-v1/budget.sqlite"
PREFIX = "election-evidence-v3/"
CAMPAIGN = PREFIX + "debate-ablation-v5"
ARMS = {"luna-committee": None, "luna-no-research": "no-research",
        "luna-no-risk": "no-risk", "single-luna": None}
SEED = 20261110
QUAL_CASES = ("midterms-2022-before-UNH", "control-2025-after-AAPL")
SETTINGS = ("max_debate_rounds", "max_risk_discuss_rounds", "max_tool_rounds",
            "max_recur_limit", "openai_reasoning_effort", "temperature", "llm_timeout")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze():
    assert not PROTOCOL.exists(), "Never replace a frozen protocol"
    OUT.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / "manifest.json").read_text())
    sources = sorted((REPO / "tradingagents").rglob("*.py")) + [Path(__file__).resolve()]
    protocol = {
        "frozen_at": datetime.now(UTC).isoformat(), "campaign_id": CAMPAIGN,
        "study_kind": "Prespecified retrospective development ablation; previously inspected market cases, not an untouched or prospective test.",
        "question": "Does removing either debate change selection P&L, allocation consistency, executable coverage and cost after the handoff repair?",
        "arms": ARMS, "membership": cases(), "target_trials": 3,
        "interventions": {
            "luna-no-research": "Remove bull/bear calls; pass original four analyst reports to the same Research Manager with an explicit omission notice. Preserve trader, risk and final manager.",
            "luna-no-risk": "Remove aggressive/conservative/neutral calls; final manager receives the same upstream plans and an explicit omission notice.",
            "single-luna": "One structured analyst call; same raw brief and mandate, without committee-generated reports.",
            "control": "Repaired five-rating all-Luna committee; same model, evidence, fee rules and source cutoff in all arms.",
        },
        "hypotheses": [
            "Research debate adds positive mean selection P&L relative to its removal.",
            "Risk debate adds positive mean selection P&L relative to its removal.",
            "Full committee adds positive mean selection P&L relative to one analyst.",
        ],
        "primary_estimand": "Alternative minus full committee in five-session account P&L less same-capital SPY P&L, 10 bps per side. Average trials within date, pair eight matured dates, then group the before/after dates in four cohorts. Equal date weights.",
        "secondary": ["same allocation across every trial / all 60 cases per arm", "allocation range per case", "accepted, explicit abstention, rejected and failed / all requested executions", "model calls, cost, latency", "trading P&L, exposure, model-expense-adjusted P&L", "0/5/25 bps sensitivity", "one- and twenty-session directional scores where matured"],
        "inference": "Three fixed two-sided contrasts against full committee; descriptive paired cohort bootstrap (10,000 draws, seed 20261110), leave-one-cohort-out values and all date differences. Exact cohort sign-flip sensitivity assumes independent sign-symmetric cohort effects; Holm adjusts its three values. Four blocks imply minimum two-sided p=0.125, so no 5% significance claim is possible. Trials never become market observations.",
        "missingness": "Preserve every started attempt. Failed, invalid or explicit-abstention sleeves hold cash under the frozen execution policy; report these statuses separately. Unknown charges retain reserves. Pending horizons stay null. Incomplete schedules cannot be advertised as the complete design.",
        "qualifications": {"cases": QUAL_CASES, "arms": list(ARMS), "excluded_from_main": True},
        "design_selection": "Qualification maximum cost per arm times 2, summed over arms. Choose first affordable: 6 stocks/3 trials, 6/2, 3/3, 3/2. Three-stock fallback is MSFT/JPM/XOM. Cost alone determines selection; preserve five cohorts and all four arms. Do not inspect qualification financial outcomes to choose.",
        "schedule": "Shuffle case/trial blocks with seed 20261110, then shuffle four arms within each block. Four worker processes. Fresh memory and state for every execution; no service seed assumed.",
        "actor": {"all_roles": "gpt-6-luna", "provider": "OpenAI", "max_output_tokens": 4096,
                  "sdk_retries": 0, "llm_judge": None,
                  "effective_defaults": {k: DEFAULT_CONFIG.get(k) for k in SETTINGS}},
        "budget": {"global_cap_usd": 250, "combined_followup_model_cap_usd": 30,
                   "ledger_prefix": PREFIX, "initial_totals": Ledger(LEDGER).totals(),
                   "policy": "Original ledger, phases and infrastructure reservations retained; no new notebook runtime reservation."},
        "stop": "Stop launching on source drift, unknown interrupted attempt or budget gate. Score ordinary actor failures without retries or prompt changes. No performance-driven early stopping.",
        "review": "Prespecified first alphabetic ticker in each cohort/side, trial 0, all arms; inspect actual requests for omitted stages and final contract. Additional strongest/weakest/seeded-random examples labeled post-result selection. Codex review is not independent domain-expert grading.",
        "privacy": "Public allowlist: metrics, allocation, derived account factors, hashes and authenticated conversation links. Raw inputs, reports and OTLP journal stay private.",
        "limitations": ["Previously examined development dates; sequential research and backtest selection remain.", "Pretrained knowledge cannot be removed.", "Archived news/social and event calendar are missing.", "Removal changes context and computation; this is not a compute-matched test of multi-agent reasoning.", "Only four matured cohorts; no powered investment-performance claim.", "The November 5, 2026 outcome freeze remains unchanged."],
        "sources_checked": {"date": "2026-11-10", "research": ["https://arxiv.org/abs/2412.20138v7", "https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents", "https://doi.org/10.21314/jcf.2016.322"], "pricing": "https://developers.openai.com/api/docs/models/gpt-6-luna"},
        "source_sha256": {str(p.relative_to(REPO)): sha(p) for p in sources},
        "evidence_manifest_sha256": sha(ROOT / "manifest.json"),
        "outcomes_sha256": sha(ROOT / "outcomes.json"),
        "brief_sha256": {c: build_brief(EvidenceStore(ROOT).get(key), key)["view_sha256"] for c, key in manifest["cases"].items()},
        "dependencies": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
        "reproduce": "python scripts/run_debate_ablation.py qualify; python scripts/run_debate_ablation.py select; python scripts/run_debate_ablation.py run; python scripts/export_debate_ablation.py",
    }
    PROTOCOL.write_bytes(canonical(protocol))
    print(json.dumps({"protocol_sha256": sha(PROTOCOL), "maximum_executions": 720}))


def validate():
    protocol = json.loads(PROTOCOL.read_text())
    assert all(sha(REPO / name) == digest for name, digest in protocol["source_sha256"].items()), "Frozen actor or analysis source drift"
    assert sha(ROOT / "manifest.json") == protocol["evidence_manifest_sha256"]
    assert sha(ROOT / "outcomes.json") == protocol["outcomes_sha256"]
    assert {k: DEFAULT_CONFIG.get(k) for k in SETTINGS} == protocol["actor"]["effective_defaults"]
    return protocol


def job(case, arm, trial, phase, sleeves):
    validate()
    os.environ["TRADINGAGENTS_TRACE_JOURNAL"] = str(OUT / "trace-journal")
    return run_one(ROOT, OUT / "shared-evidence", case, arm, trial, phase,
                   campaign_id=CAMPAIGN, execution_contract=True, evidence_mode="shared-evidence",
                   debate_ablation=ARMS[arm], budget_path=LEDGER, budget_prefix=PREFIX,
                   campaign_cap_usd=30, sleeves=sleeves)


def run(jobs):
    validate()
    jobs = iter(jobs)
    count, stopped = 0, False
    with ProcessPoolExecutor(max_workers=4, mp_context=multiprocessing.get_context("spawn"), max_tasks_per_child=1) as pool:
        pending = {}
        def launch():
            args = next(jobs, None)
            if args is not None:
                pending[pool.submit(job, *args)] = args
        for _ in range(4):
            launch()
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                args = pending.pop(future)
                try:
                    row = future.result()
                    count += 1
                    print(json.dumps({"completed": count, "case": row["case_id"], "arm": row["treatment"], "trial": row["trial"], "status": row["status"], "contract": row["execution_check"]["status"], "cost": row["cost_upper_usd"], "error": row.get("error")}), flush=True)
                    if "Budget" in row.get("error", ""):
                        stopped = True
                except Exception as exc:
                    print(json.dumps({"job": args, "dispatch_error": str(exc)}), flush=True)
                    stopped = True
                if not stopped:
                    launch()
    if stopped:
        raise RuntimeError("Launches stopped; inspect persisted attempts before any resume")


def select():
    validate()
    path = OUT / "design.json"
    assert not path.exists(), "Preserve the selected design"
    rows = [json.loads(p.read_text()) for p in OUT.glob("*/qualification/**/prediction.json")]
    assert len(rows) == 8 and all(r["status"] == "success" and not r["unknown_calls"] for r in rows)
    costs = {arm: max(r["cost_upper_usd"] for r in rows if r["treatment"] == arm) for arm in ARMS}
    with Ledger(LEDGER).connect() as db:
        spent = db.execute("SELECT sum(coalesce(charged,reserve))/1000000.0 FROM calls WHERE run_key LIKE 'election-evidence-v3/%'").fetchone()[0]
    choice = next(((s, t) for s, t in ((6, 3), (6, 2), (3, 3), (3, 2)) if 10 * s * t * sum(costs.values()) * 2 <= 30 - spent - 0.5), None)
    assert choice, "No balanced repeated design fits the remaining allowance"
    stocks, trials = choice
    design = {"stocks": stocks, "trials": trials, "arms": list(ARMS), "protocol_sha256": sha(PROTOCOL),
              "actor_code_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "qualification_cost_by_arm": costs, "estimated_2x_cost": 10 * stocks * trials * sum(costs.values()) * 2,
              "combined_cost_before_main": spent, "selected_at": datetime.now(UTC).isoformat()}
    path.write_bytes(canonical(design))
    (OUT / "shared-evidence/design.json").write_bytes(canonical(design))
    (PUBLIC / "design.json").write_bytes(canonical(design))
    blocks = [(c["case_id"], trial) for c in cases(STOCKS if stocks == 6 else ["MSFT", "JPM", "XOM"]) for trial in range(trials)]
    rng = random.Random(SEED)
    rng.shuffle(blocks)
    jobs = []
    for case, trial in blocks:
        arms = list(ARMS)
        rng.shuffle(arms)
        jobs.extend((case, arm, trial, "campaign", stocks) for arm in arms)
    (OUT / "jobs.json").write_bytes(canonical(jobs))
    (PUBLIC / "schedule.json").write_bytes(canonical(jobs))
    print(json.dumps(design, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("freeze", "qualify", "select", "run"))
    command = parser.parse_args().command
    if command == "freeze":
        freeze()
    elif command == "qualify":
        run([(case, arm, 0, "qualification", 6) for case in QUAL_CASES for arm in ARMS])
    elif command == "select":
        select()
    else:
        run(json.loads((OUT / "jobs.json").read_text()))

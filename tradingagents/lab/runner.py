"""Budgeted actors. Predictions are durable before any evaluation upload."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import traceback
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from tradingagents.lab.budget import BudgetCallback, Ledger, choose_design
from tradingagents.lab.evaluation import EvaluationBridge
from tradingagents.lab.evidence import EvidenceStore, canonical
from tradingagents.lab.replay import network_guard
from tradingagents.lab.scoring import score, summary

TREATMENTS = ["default-committee", "luna-committee", "single-luna"]


def compact_evidence(data):
    # Lossless columns relevant to prices/actions, rather than repeated JSON keys.
    lines = ["Retrospective replay. Only the following frozen evidence is available.",
             json.dumps({"case": data["case"], "records": data["records"]})]
    for ticker, rows in data["prices"].items():
        lines.append(ticker + "\ndate,open,high,low,close,volume,split,dividend")
        lines.extend(",".join(str(r[k]) for k in ["date", "open", "high", "low", "close", "volume", "split", "dividend"]) for r in rows)
    return "\n".join(lines)


def single_analyst(config, data, budget):
    from langchain_core.messages import HumanMessage, SystemMessage

    from tradingagents.agents.rating import parse_rating
    from tradingagents.llm_clients import create_tier_client
    from tradingagents.observability.agent_lens import decision_scope
    with decision_scope(config, data["case"]["ticker"], data["case"]["decision_date"]) as handler:
        model = create_tier_client(config, "quick", callbacks=[budget, handler]).get_llm()
        response = model.invoke([
            SystemMessage(content="You are a single investment analyst. Use only supplied evidence. Identify missing sources and uncertainty. Recommend the stock relative to SPY over five sessions after entry at the next session close. Explain your recommendation and finish with '**Rating**: Buy', Overweight, Hold, Underweight, or Sell. Do not fabricate numerical evidence or invoke tools."),
            HumanMessage(content=compact_evidence(data)),
        ])
        text = str(response.content)
        handler.turn.output_messages = [handler.sdk.Message(role="assistant", content=text)]
        return {"rating": parse_rating(text), "report": text, "state": {"final_trade_decision": text},
                "conversation_id": handler.conversation_id, "conversation_url": handler.url,
                "events": handler.events}


def run_one(root, output, case_id, treatment, trial=0, phase="campaign", publish=True):
    from dotenv import load_dotenv
    if credentials := os.getenv("TRADINGAGENTS_MODELS_ENV"):
        load_dotenv(credentials, override=False)
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.observability.agent_lens import conversation_url

    root, output = Path(root), Path(output)
    manifest = json.loads((root / "manifest.json").read_text())
    evidence_hash = manifest["cases"][case_id]
    data = EvidenceStore(root).get(evidence_hash)
    case = data["case"]
    key = f"election-replay-v1/{phase}/{case_id}/{treatment}/{trial}/attempt-0"
    run_dir = output / phase / case_id / treatment / str(trial)
    run_dir.mkdir(parents=True, exist_ok=True)
    result_path = run_dir / "prediction.json"
    if result_path.exists():
        return json.loads(result_path.read_text())
    ledger = Ledger(output / "budget.sqlite")
    started_path = run_dir / "started.json"
    if started_path.exists():
        raise RuntimeError(f"Uncertain interrupted attempt; inspect before retry: {key}")
    started_path.write_bytes(canonical({"run_key": key, "started_at": datetime.now(UTC).isoformat()}))
    project = "wandb/tradingagents-election-lab"
    trace_project = "wandb/tradingagents-election-lab-evidence"
    cid = str(uuid5(NAMESPACE_URL, key))
    revision = os.getenv("TRADINGAGENTS_LAB_CODE_REVISION") or subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    meta = {"campaign_id": "election-replay-v1", "case_id": case_id, "treatment": treatment,
            "trial": trial, "attempt": 0, "cohort": case["cohort"], "dataset_version": evidence_hash,
            "code_revision": revision, "outcome_status": "not_scored"}
    config = deepcopy(DEFAULT_CONFIG)
    config.update({"forge_project": trace_project, "forge_conversation_id": cid,
                   "forge_metadata": meta, "replay_root": str(root.resolve()), "replay_evidence": evidence_hash,
                   "results_dir": str(run_dir / "reports"), "data_cache_dir": str(run_dir / "cache"),
                   "memory_log_path": str(run_dir / "memory.md"), "checkpoint_enabled": False,
                   "llm_max_retries": 0, "max_tokens": 4096,
                   "backend_url": "https://api.openai.com/v1", "llm_provider": "openai",
                   "quick_think_llm": "gpt-6-luna", "deep_think_llm": "gpt-6-sol" if treatment == "default-committee" else "gpt-6-luna"})
    budget = BudgetCallback(ledger, key, phase)
    bridge = EvaluationBridge(project, "election-replay-v1/" + phase, treatment, manifest["version"]) if publish else None
    from contextlib import nullcontext
    context = bridge.prediction(case, trial, evidence_hash) if bridge else nullcontext((None, {}))
    start = time.monotonic()
    row = {**case, "run_key": key, "phase": phase, "trial": trial, "treatment": treatment,
           "evidence_sha256": evidence_hash, "dataset_version": manifest["version"], "code_revision": revision,
           "conversation_id": cid, "conversation_url": conversation_url(trace_project, cid),
           "forecast": None, "information_access": "frozen prices, SEC facts, ALFRED vintages; missing news/social explicit",
           "started_at": datetime.now(UTC).isoformat()}
    with context as (prediction, attrs):
        config["forge_metadata"].update(attrs)
        row["evaluation_ids"] = attrs
        try:
            from tradingagents.dataflows.config import run_config
            with run_config(config), network_guard(["api.openai.com", "forge.coreweave.com", "api.wandb.ai", "trace.wandb.ai"]):
                if treatment == "single-luna":
                    row.update(single_analyst(config, data, budget))
                else:
                    graph = TradingAgentsGraph(config=config, callbacks=[budget])
                    state, rating = graph.propagate(case["ticker"], case["decision_date"])
                    row.update(rating=rating, report=state.get("final_trade_decision", ""),
                               state={k: v for k, v in state.items() if k != "messages"},
                               events=graph.forge_result["events"])
            row["status"] = "success"
        except Exception as exc:
            row.update(status="failed", rating=None, error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        row.update(latency_s=time.monotonic() - start, completed_at=datetime.now(UTC).isoformat(), **ledger.totals(key))
        # Paid outputs persist before reading outcomes or touching evaluation upload.
        result_path.write_bytes(canonical(row))
        outcomes = json.loads((root / "outcomes.json").read_text())["cases"][case_id]
        row["scores_by_horizon"] = {h: score(row, value) for h, value in outcomes.items()}
        row["scores"] = row["scores_by_horizon"]["5"]
        result_path.write_bytes(canonical(row))
        if prediction:
            # Public evaluations contain derived metrics and authenticated links.
            prediction.output = {k: row[k] for k in ["rating", "status", "conversation_url", "cost_upper_usd", "latency_s"]}
            for name, value in row["scores"].items():
                prediction.log_score(name, value)
    if bridge:
        bridge.finish(summary([row]))
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["qualify", "run", "select"])
    parser.add_argument("--root", default="lab-data/election-v1")
    parser.add_argument("--output", default="lab-runs/election-v1")
    parser.add_argument("--case-id", default="presidential-2024-before-MSFT")
    parser.add_argument("--treatment", choices=TREATMENTS)
    parser.add_argument("--trial", type=int, default=0)
    args = parser.parse_args()
    if args.command == "select":
        files = list((Path(args.output) / "qualification").rglob("prediction.json"))
        values = [json.loads(f.read_text()) for f in files]
        if any(v["status"] != "success" for v in values):
            raise RuntimeError("Qualification failed; diagnose plumbing before campaign")
        costs = {t: max(v["cost_upper_usd"] for v in values if v["treatment"] == t) for t in TREATMENTS}
        design = choose_design(costs)
        (Path(args.output) / "design.json").write_bytes(canonical(design))
        print(json.dumps(design))
        return
    treatments = [args.treatment] if args.treatment else TREATMENTS
    for treatment in treatments:
        row = run_one(args.root, args.output, args.case_id, treatment, args.trial,
                      "qualification" if args.command == "qualify" else "campaign")
        print(json.dumps({k: row.get(k) for k in ["run_key", "status", "rating", "cost_upper_usd", "unknown_calls", "conversation_url", "error"]}), flush=True)


if __name__ == "__main__":
    main()

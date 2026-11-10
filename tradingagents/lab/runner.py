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
        if mandate := config.get("evaluation_mandate"):
            from tradingagents.lab.execution import (
                ExecutionDecision,
                mandate_prompt,
                render_evaluated_decision,
            )
            decision_schema = ExecutionDecision
            evidence_text = compact_evidence(data)
            if mode := config.get("evidence_mode"):
                from tradingagents.lab.brief import CitedDecision, brief_prompt
                evidence_text = brief_prompt(config["replay_view"], mode)
                if mode == "cited-evidence":
                    decision_schema = CitedDecision
            decision = model.with_structured_output(decision_schema).invoke([
                SystemMessage(content="You are a single investment analyst. Use only supplied evidence; identify missing sources and uncertainty. Do not fabricate numerical evidence or invoke external tools." + mandate_prompt(mandate)),
                HumanMessage(content=evidence_text),
            ])
            if not isinstance(decision, ExecutionDecision):
                raise ValueError("Single analyst did not return an execution decision")
            text = render_evaluated_decision(decision, config)
            handler.turn.output_messages = [handler.sdk.Message(role="assistant", content=text)]
            return {"rating": decision.rating.value, "report": text,
                    "execution_decision": decision.model_dump(mode="json"),
                    "state": {"final_trade_decision": text},
                    "conversation_id": handler.conversation_id, "conversation_url": handler.url,
                    "events": handler.events}
        response = model.invoke([
            SystemMessage(content="You are a single investment analyst. Use only supplied evidence. Identify missing sources and uncertainty. Recommend the stock relative to SPY over five sessions after entry at the next session close. Explain your recommendation and finish with '**Rating**: Buy', Overweight, Hold, Underweight, or Sell. Do not fabricate numerical evidence or invoke tools."),
            HumanMessage(content=compact_evidence(data)),
        ])
        text = str(response.content)
        handler.turn.output_messages = [handler.sdk.Message(role="assistant", content=text)]
        return {"rating": parse_rating(text), "report": text, "state": {"final_trade_decision": text},
                "conversation_id": handler.conversation_id, "conversation_url": handler.url,
                "events": handler.events}


def run_one(root, output, case_id, treatment, trial=0, phase="campaign", publish=True, *,
            campaign_id="election-replay-v1", execution_contract=False, budget_path=None,
            campaign_cap_usd=None, sleeves=6, evidence_mode=None, budget_prefix=None,
            debate_ablation=None):
    from dotenv import load_dotenv
    if credentials := os.getenv("TRADINGAGENTS_MODELS_ENV"):
        load_dotenv(credentials, override=False)
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.observability.agent_lens import conversation_url

    root, output = Path(root), Path(output)
    if debate_ablation not in (None, "no-research", "no-risk"):
        raise ValueError("Unknown debate ablation")
    if debate_ablation and (not execution_contract or evidence_mode != "shared-evidence"
                            or treatment != "luna-" + debate_ablation):
        raise ValueError("Ablations require an identified Luna treatment and shared execution evidence")
    manifest = json.loads((root / "manifest.json").read_text())
    evidence_hash = manifest["cases"][case_id]
    data = EvidenceStore(root).get(evidence_hash)
    case = data["case"]
    if evidence_mode:
        from tradingagents.lab.brief import MODES
        if evidence_mode not in MODES or not execution_contract:
            raise ValueError("A common evidence mode requires a supported execution contract")
    if execution_contract and campaign_id == "election-replay-v1":
        raise ValueError("A corrected contract needs a new campaign identity")
    key = f"{campaign_id}/{phase}/{case_id}/{treatment}/{trial}/attempt-0"
    run_dir = output / phase / case_id / treatment / str(trial)
    run_dir.mkdir(parents=True, exist_ok=True)
    result_path = run_dir / "prediction.json"
    if result_path.exists():
        saved = json.loads(result_path.read_text())
        if (saved["run_key"] != key or bool(saved.get("execution_mandate")) != execution_contract
                or saved.get("evidence_mode") != evidence_mode
                or saved.get("debate_ablation") != debate_ablation):
            raise ValueError("Output belongs to a different campaign or contract")
        return saved
    ledger = Ledger(budget_path or output / "budget.sqlite",
                    campaign_prefix=(budget_prefix or campaign_id + "/") if campaign_cap_usd is not None else None,
                    campaign_cap_usd=campaign_cap_usd)
    started_path = run_dir / "started.json"
    if started_path.exists():
        raise RuntimeError(f"Uncertain interrupted attempt; inspect before retry: {key}")
    started_path.write_bytes(canonical({"run_key": key, "started_at": datetime.now(UTC).isoformat()}))
    project = "wandb/tradingagents-election-lab"
    trace_project = "wandb/tradingagents-election-lab-evidence"
    cid = str(uuid5(NAMESPACE_URL, key))
    revision = os.getenv("TRADINGAGENTS_LAB_CODE_REVISION") or subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    meta = {"campaign_id": campaign_id, "case_id": case_id,
            "treatment": treatment + "/" + (evidence_mode or "contract-v2") if execution_contract else treatment,
            "trial": trial, "attempt": 0, "cohort": case["cohort"], "dataset_version": evidence_hash,
            "code_revision": revision, "outcome_status": "not_scored"}
    config = deepcopy(DEFAULT_CONFIG)
    events = []
    config.update({"forge_project": trace_project, "forge_conversation_id": cid,
                   "forge_event_sink": events,
                   "forge_metadata": meta, "replay_root": str(root.resolve()), "replay_evidence": evidence_hash,
                   "results_dir": str(run_dir / "reports"), "data_cache_dir": str(run_dir / "cache"),
                   "memory_log_path": str(run_dir / "memory.md"), "checkpoint_enabled": False,
                   "llm_max_retries": 0, "max_tokens": 4096,
                   "backend_url": "https://api.openai.com/v1", "llm_provider": "openai",
                   "quick_think_llm": "gpt-6-luna", "deep_think_llm": "gpt-6-sol" if treatment == "default-committee" else "gpt-6-luna"})
    budget = BudgetCallback(ledger, key, phase)
    if debate_ablation:
        config["lab_debate_ablation"] = debate_ablation
        config["forge_metadata"]["debate_ablation"] = debate_ablation
    portfolio = None
    if execution_contract:
        from tradingagents.lab.execution import make_mandate
        from tradingagents.portfolio import PortfolioContext
        mandate = make_mandate(case["ticker"], case["decision_date"], sleeves=sleeves)
        config["evaluation_mandate"] = mandate.model_dump()
        portfolio = PortfolioContext(cash=mandate.sleeve_cash_usd, currency="USD", positions=[])
    if evidence_mode:
        from tradingagents.lab.brief import build_brief
        config["evidence_mode"] = evidence_mode
        config["replay_view"] = build_brief(data, evidence_hash)
        config["forge_metadata"].update(evidence_mode=evidence_mode,
                                        evidence_view_sha256=config["replay_view"]["view_sha256"])
    bridge = EvaluationBridge(project, campaign_id + "/" + phase, treatment, manifest["version"]) if publish else None
    from contextlib import nullcontext
    context = bridge.prediction(case, trial, evidence_hash) if bridge else nullcontext((None, {}))
    start = time.monotonic()
    row = {**case, "run_key": key, "phase": phase, "trial": trial, "treatment": treatment,
           "evidence_sha256": evidence_hash, "dataset_version": manifest["version"], "code_revision": revision,
           "conversation_id": cid, "conversation_url": conversation_url(trace_project, cid),
           "forecast": None, "information_access": "frozen prices, SEC facts, ALFRED vintages; missing news/social explicit",
           "started_at": datetime.now(UTC).isoformat()}
    if execution_contract:
        row["execution_mandate"] = config["evaluation_mandate"]
    if debate_ablation:
        row["debate_ablation"] = debate_ablation
    if evidence_mode:
        row.update(evidence_mode=evidence_mode, evidence_view=config["replay_view"],
                   information_access="Identical frozen numeric decision brief; tools restricted to its facts. Archived news and event calendars unavailable.")
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
                    state, rating = graph.propagate(case["ticker"], case["decision_date"], portfolio=portfolio)
                    row.update(rating=rating, report=state.get("final_trade_decision", ""),
                               state={k: v for k, v in state.items() if k != "messages"},
                               events=graph.forge_result["events"])
                    if execution_contract:
                        row["execution_decision"] = state.get("execution_decision")
            row["status"] = "success"
        except Exception as exc:
            row.update(status="failed", rating=None, events=events,
                       error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        row.update(latency_s=time.monotonic() - start, completed_at=datetime.now(UTC).isoformat(), **ledger.totals(key))
        # Paid outputs persist before reading outcomes or touching evaluation upload.
        result_path.write_bytes(canonical(row))
        outcomes = json.loads((root / "outcomes.json").read_text())["cases"][case_id]
        if execution_contract:
            from tradingagents.lab.execution import execution_check, score_execution
            row["execution_check"] = execution_check(row)
            row["scores_by_horizon"] = {h: score_execution(row, value, h) for h, value in outcomes.items()}
            if evidence_mode:
                from tradingagents.lab.execution import execution_receipt
                row["execution_receipt"] = execution_receipt(row)
                if evidence_mode == "cited-evidence" and row["status"] == "success":
                    from tradingagents.lab.brief import assess_citations
                    row["citation_check"] = assess_citations(row["execution_decision"], row["evidence_view"])
        else:
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

"""Small synthetic support demonstration; inference requires explicit --execute."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from tradingagents.lab.budget import BudgetCallback, BudgetExceeded, Ledger
from tradingagents.lab.evidence import canonical

ROOT = Path(__file__).resolve().parent
OUTPUT = Path("lab-runs/support-v1")
PROJECT = "wandb/tradingagents-election-lab-evidence"
MODEL = "gpt-6-luna"


def fixture():
    return json.loads((ROOT / "fixtures.json").read_text())


class Store:
    """Tools bind the session order and enforce policy outside the model."""

    def __init__(self, case):
        self.case = deepcopy(case)
        self.looked_up = False
        self.new_refund_cents = 0
        self.tickets = []
        self.events = []

    def call(self, name, args):
        result = self._call(name, args)
        self.events.append({"name": name, "arguments": args, "result": deepcopy(result)})
        return result

    def _call(self, name, args):
        order = self.case["order"]
        available = order is not None and not self.case.get("lookup_unavailable")
        if name == "get_order":
            self.looked_up = True
            if self.case.get("lookup_unavailable"):
                return {"status": "DATA_UNAVAILABLE", "message": "Order service unavailable; escalate."}
            return {"status": "found", **order} if available else {"status": "NOT_FOUND"}
        if name == "issue_refund":
            if not self.looked_up or not available or order["days_since_delivery"] > 30:
                return {"status": "rejected", "reason": "No verified eligible order"}
            if order["refunded_cents"] or self.new_refund_cents:
                return {"status": "rejected", "reason": "Duplicate refund attempt"}
            self.new_refund_cents = order["amount_cents"]
            return {"status": "refunded", "amount_cents": self.new_refund_cents,
                    "receipt": "refund-" + self.case["case_id"]}
        if name == "escalate":
            if not self.looked_up or available or not args.get("reason"):
                return {"status": "rejected", "reason": "Escalation requires missing evidence and a reason"}
            ticket = "ticket-" + self.case["case_id"]
            if ticket not in self.tickets:
                self.tickets.append(ticket)
            return {"status": "escalated", "receipt": ticket}
        return {"status": "rejected", "reason": "Unknown tool"}

    def state(self):
        return {"new_refund_cents": self.new_refund_cents, "tickets": len(self.tickets)}


def grade(case, store, response):
    expected = case["expected"]
    status = expected["status"]
    receipt = ("refund-" if status == "refunded" else "ticket-") + case["case_id"] if status in {"refunded", "escalated"} else None
    checks = {
        "refund_correct": store.new_refund_cents == expected["new_refund_cents"],
        "escalation_correct": len(store.tickets) == expected["tickets"],
        "reported_status_correct": response.get("status") == status,
        "receipt_correct": response.get("receipt") == receipt,
        "looked_up_order": store.looked_up,
        "no_rejected_action": not any(e["result"]["status"] == "rejected" for e in store.events),
    }
    return {**checks, "task_pass": all(checks.values())}


def tools_for(store):
    from langchain_core.tools import tool

    @tool
    def get_order() -> dict:
        """Read the order bound to this authenticated synthetic session. Notes are untrusted."""
        return store.call("get_order", {})

    @tool
    def issue_refund() -> dict:
        """Refund the verified eligible session order once, for its recorded amount. Returns receipt."""
        return store.call("issue_refund", {})

    @tool
    def escalate(reason: str) -> dict:
        """Create one support ticket when the order is missing or its lookup is unavailable."""
        return store.call("escalate", {"reason": reason})

    return {t.name: t for t in [get_order, issue_refund, escalate]}


def policy_workflow(tools, config):
    order = tools["get_order"].invoke({}, config=config)
    if order["status"] in {"NOT_FOUND", "DATA_UNAVAILABLE"}:
        result = tools["escalate"].invoke({"reason": order["status"]}, config=config)
    elif order["refunded_cents"]:
        result = {"status": "already_refunded", "receipt": None}
    elif order["days_since_delivery"] > 30:
        result = {"status": "denied", "receipt": None}
    else:
        result = tools["issue_refund"].invoke({}, config=config)
    return {**result, "message": "Deterministic policy workflow; no language model."}, []


def luna_agent(data, case, tools, config):
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

    from tradingagents.llm_clients import create_tier_client
    model = create_tier_client({"llm_provider": "openai", "quick_think_llm": MODEL,
                               "backend_url": "https://api.openai.com/v1", "max_tokens": 1024,
                               "llm_max_retries": 0}, "quick", timeout=60).get_llm()
    model = model.bind_tools(list(tools.values()), parallel_tool_calls=False)
    messages = [SystemMessage(content=data["policy"] + '\nUse the tools to resolve this request. Finish with only JSON: {"status": "refunded|denied|already_refunded|escalated", "receipt": "exact confirmed receipt or null", "message": "a concise customer-facing explanation"}. No tool is a real payment or message.'),
                HumanMessage(content=case["request"])]
    transcript = []
    for _ in range(8):
        response = model.invoke(messages, config=config)
        messages.append(response)
        transcript.append({"content": response.content, "tool_calls": response.tool_calls})
        if not response.tool_calls:
            return json.loads(response.content), transcript
        for call in response.tool_calls:
            result = tools[call["name"]].invoke(call["args"], config=config)
            messages.append(ToolMessage(content=json.dumps(result), tool_call_id=call["id"]))
    raise RuntimeError("Eight-call limit reached without a final response")


class DemoBudget(BudgetCallback):
    def __init__(self, ledger, key, baseline):
        super().__init__(ledger, key, "publication", max_output=1024)
        self.baseline = baseline

    def on_chat_model_start(self, *args, **kwargs):
        # Requests are small, but retain $0.10 headroom before each dispatch.
        if self.ledger.totals()["cost_upper_usd"] - self.baseline >= .90:
            raise BudgetExceeded("Support demo $1 incremental cap reached")
        super().on_chat_model_start(*args, **kwargs)
        if self.ledger.totals()["cost_upper_usd"] - self.baseline > 1:
            raise BudgetExceeded("Support demo reservation would exceed $1")


def execute_one(data, case, treatment, trial, ledger, frozen, sdk):
    from tradingagents.lab.evaluation import EvaluationBridge
    from tradingagents.observability.agent_lens import AgentLensCallback, conversation_url

    key = f"support-refunds-v1/{case['case_id']}/{treatment}/{trial}/attempt-1"
    path = OUTPUT / case["case_id"] / treatment / str(trial)
    path.mkdir(parents=True, exist_ok=True)
    result_path = path / "prediction.json"
    if result_path.exists():
        return json.loads(result_path.read_text())
    started = path / "started.json"
    if started.exists():
        raise RuntimeError(f"Inspect interrupted attempt before retry: {key}")
    started.write_bytes(canonical({"key": key, "started_at": datetime.now(UTC).isoformat()}))
    cid = str(uuid5(NAMESPACE_URL, key))
    row = {"case_id": case["case_id"], "treatment": treatment, "trial": trial,
           "conversation_id": cid, "conversation_url": conversation_url(PROJECT, cid),
           "started_at": datetime.now(UTC).isoformat(), "fixture_sha256": frozen["fixture_sha256"],
           "runner_sha256": frozen["runner_sha256"], "code_revision": frozen["code_revision"]}
    bridge = EvaluationBridge("wandb/tradingagents-election-lab", "support-refunds-v1", treatment, data["version"])
    store = Store(case)
    tools = tools_for(store)
    start = time.monotonic()
    with bridge.prediction({"case_id": case["case_id"], "request": case["request"]}, trial, frozen["fixture_sha256"]) as (prediction, evaluation):
        attrs = {**evaluation, "demo.campaign_id": "support-refunds-v1", "demo.case_id": case["case_id"],
                 "demo.synthetic": True, "demo.fixture_sha256": frozen["fixture_sha256"],
                 "demo.runner_sha256": frozen["runner_sha256"], "demo.trial": trial}
        row["evaluation_ids"] = evaluation
        handler = None
        try:
            with sdk.start_conversation(agent_name=treatment, conversation_id=cid,  # noqa: SIM117
                                        conversation_name=f"Synthetic support · {case['case_id']} · trial {trial}", attributes=attrs) as conversation:
                with conversation.start_turn(user_message=case["request"]) as turn:
                    turn.set_attributes(attrs)
                    with turn.start_subagent(name="Support specialist" if treatment == "support-luna" else "Policy workflow") as agent:
                        agent.set_attributes(attrs)
                        handler = AgentLensCallback(sdk, agent, attrs)
                        config = {"callbacks": [DemoBudget(ledger, key, frozen["budget_before_upper_usd"]), handler]}
                        try:
                            response, transcript = luna_agent(data, case, tools, config) if treatment == "support-luna" else policy_workflow(tools, config)
                            row.update(response=response, transcript=transcript, status="success")
                            turn.output_messages = [sdk.Message(role="assistant", content=json.dumps(response))]
                            agent.output_messages = turn.output_messages
                        finally:
                            handler.close()
        except Exception as exc:
            row.update(status="failed", error=f"{type(exc).__name__}: {exc}", response={})
        finally:
            row["flushed"] = sdk.force_flush()
        row.update(events=handler.events if handler else [], tools=store.events, state=store.state(),
                   latency_s=time.monotonic() - start, completed_at=datetime.now(UTC).isoformat(),
                   **ledger.totals(key))
        result_path.write_bytes(canonical(row))
        row["scores"] = grade(case, store, row["response"])
        if row["status"] != "success":
            row["scores"]["task_pass"] = False
        result_path.write_bytes(canonical(row))
        prediction.output = {k: row[k] for k in ["response", "state", "conversation_url", "status", "cost_known_usd", "latency_s"]}
        for name, value in row["scores"].items():
            prediction.log_score(name, value)
    bridge.finish({"task_pass": row["scores"]["task_pass"]})
    return row


def execute():
    from dotenv import load_dotenv

    from tradingagents.observability.agent_lens import _sdk
    if credentials := os.getenv("TRADINGAGENTS_MODELS_ENV"):
        load_dotenv(credentials, override=False)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    ledger = Ledger("lab-runs/election-v1/budget.sqlite")
    data = fixture()
    frozen = {"fixture_sha256": hashlib.sha256((ROOT / "fixtures.json").read_bytes()).hexdigest(),
              "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "code_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()}
    manifest = OUTPUT / "manifest.json"
    if manifest.exists():
        previous = json.loads(manifest.read_text())
        assert all(previous[k] == v for k, v in frozen.items()), "Frozen protocol drift"
        frozen = previous
    else:
        frozen.update(budget_before_upper_usd=ledger.totals()["cost_upper_usd"], frozen_at=datetime.now(UTC).isoformat())
        manifest.write_bytes(canonical(frozen))
    # One initialization per process, matching the original campaign workers.
    sdk = _sdk(PROJECT)
    for case in data["cases"]:
        for treatment, trials in [("support-policy", 1), ("support-luna", 2)]:
            for trial in range(trials):
                row = execute_one(data, case, treatment, trial, ledger, frozen, sdk)
                print(json.dumps({k: row[k] for k in ["case_id", "treatment", "trial", "status", "scores", "cost_known_usd"]}), flush=True)


def audit():
    from tradingagents.lab.lens import LensClient, audit_spans
    rows = [json.loads(p.read_text()) for p in sorted(OUTPUT.glob("*/*/*/prediction.json"))]
    audits = [audit_spans(r, LensClient().spans(r["conversation_id"])) for r in rows]
    result = {"conversations": len(rows), "spans": sum(r["span_count"] for r in audits),
              "model_calls": sum(r["model_calls"] for r in audits),
              "tool_calls": sum(r["tool_calls"] for r in audits),
              "all_evaluation_links_verified": all(r["all_spans_linked"] for r in audits),
              "all_usage_reconciled": all(r["usage_reconciled"] for r in audits),
              "rows": audits}
    (OUTPUT / "hosted-audit.json").write_bytes(canonical(result))
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--execute", action="store_true")
    group.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    execute() if args.execute else audit()

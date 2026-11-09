"""Read every regression trace and export engineering checks, not trading scores."""

from __future__ import annotations

import json
import re
from collections import Counter

import audit_evidence_campaign as common_audit
from recover_journaled_traces import reconcile
from run_handoff_regressions import JOBS, LEDGER, OUT, PROTOCOL, PUBLIC, REPO, sha, validate

from tradingagents.lab.budget import Ledger
from tradingagents.lab.evidence import canonical
from tradingagents.lab.handoff import ContractTraderProposal
from tradingagents.lab.lens import LensClient
from tradingagents.lab.publication import public_budget


def export():
    protocol = validate()
    paths = sorted(OUT.glob("*/campaign/**/prediction.json"))
    assert len(paths) == len(JOBS)
    common_audit.OUT = OUT
    common_audit.main("campaign")
    audit = json.loads((OUT / "campaign-hosted-audit.json").read_text())
    journal = reconcile(OUT / "trace-journal/wandb/tradingagents-election-lab-evidence", "wandb/tradingagents-election-lab-evidence")
    assert len(journal["conversations"]) == len(JOBS)
    assert all(not r["missing_after_readback"] for r in journal["conversations"])
    assert sum(r["journal_spans"] for r in journal["conversations"]) == audit["spans"]
    (OUT / "journal-verification.json").write_bytes(canonical(journal))
    launch = json.loads((OUT / "launch.json").read_text())
    rows = []
    raw = OUT / "native-spans"
    raw.mkdir(exist_ok=True)
    for path in paths:
        row = json.loads(path.read_text())
        assert row["code_revision"] == launch["actor_code_revision"]
        cid = row["conversation_id"]
        spans = LensClient().spans(cid)
        (raw / (cid + ".json")).write_bytes(canonical(spans))
        parents = {s["span_id"]: s for s in spans}
        trader_calls = [
            s
            for s in spans
            if s["operation_name"] == "chat"
            and parents.get(s["parent_span_id"], {}).get("agent_name") == "Trader"
        ]
        manager_calls = [
            s
            for s in spans
            if s["operation_name"] == "chat"
            and parents.get(s["parent_span_id"], {}).get("agent_name") == "Portfolio Manager"
        ]
        assert len(trader_calls) == len(manager_calls) == 1
        request = "\n".join(common_audit.strings(trader_calls[0]["input_messages"]))
        response = "\n".join(common_audit.strings(trader_calls[0]["output_messages"]))
        assert "Underweight=25%" in request and "Sell=0%" in request
        assert "Underweight is a Sell" not in request and "ContractTraderProposal" in response
        manager_request = "\n".join(common_audit.strings(manager_calls[0]["input_messages"]))
        assert "Maintain current position, no action needed" not in manager_request
        assert "Reduce exposure, take partial profits" not in manager_request
        text = row["state"]["trader_investment_plan"]
        action = re.search(r"^\*\*Action\*\*: (.+)$", text, re.M).group(1)
        blocks = re.findall(r"```json\n(.*?)\n```", text, re.S)
        reason = text.split("**Reasoning**: ", 1)[1].split("\n\n**Proposed mandate**", 1)[0]
        proposal = ContractTraderProposal.model_validate(
            {
                "action": action,
                "reasoning": reason,
                "mandate": json.loads(blocks[0]),
                "order": json.loads(blocks[1]),
            }
        )
        assert proposal.mandate.model_dump() == row["execution_mandate"]
        previous_path = (
            REPO
            / "lab-runs/election-evidence-v3-repaired"
            / row["evidence_mode"]
            / "campaign"
            / row["case_id"]
            / row["treatment"]
            / "0/prediction.json"
        )
        previous = json.loads(previous_path.read_text())
        assert previous["evidence_view"] == row["evidence_view"]
        old_plan = previous["state"]["trader_investment_plan"]
        old_action = re.search(r"^\*\*Action\*\*: (.+)$", old_plan, re.M).group(1)
        rows.append(
            {
                "case_id": row["case_id"],
                "arm": row["evidence_mode"],
                "treatment": row["treatment"],
                "trial": 0,
                "status": row["status"],
                "trader_action": action,
                "proposed_weight": proposal.order.target_weight,
                "proposed_kind": proposal.order.kind,
                "proposed_conditions": proposal.order.conditions,
                "final_rating": row["rating"],
                "final_target_weight": row["execution_check"]["target_weight"],
                "final_contract_status": row["execution_check"]["status"],
                "mandate_matched": True,
                "action_weight_matched": True,
                "five_rating_request_verified": True,
                "legacy_instruction_absent": True,
                "manager_existing_holding_scale_absent": True,
                "conversation_url": row["conversation_url"],
                "source_prediction_sha256": sha(path),
                "brief_sha256": row["evidence_view"]["view_sha256"],
                "evidence_sha256": row["evidence_sha256"],
                "cost_known_usd": row["cost_known_usd"],
                "cost_upper_usd": row["cost_upper_usd"],
                "latency_s": row["latency_s"],
                "unknown_calls": row["unknown_calls"],
                "previous_trader_action": old_action,
                "previous_final_rating": previous["rating"],
                "previous_final_target_weight": previous["execution_check"]["target_weight"],
                "previous_conversation_url": previous["conversation_url"],
                "previous_source_sha256": sha(previous_path),
            }
        )
    ledger = Ledger(LEDGER)
    with ledger.connect() as db:
        combined = db.execute(
            "SELECT sum(coalesce(charged,reserve))/1000000.0 FROM calls WHERE run_key LIKE 'election-evidence-v3/%'"
        ).fetchone()[0]
    assert combined <= 30
    result = {
        "protocol_sha256": sha(PROTOCOL),
        "actor_code_revision": launch["actor_code_revision"],
        "main_results_sha256": protocol["main_results_sha256"],
        "rows": rows,
        "executions": len(rows),
        "status_counts": dict(Counter(r["status"] for r in rows)),
        "contract_counts": dict(Counter(r["final_contract_status"] for r in rows)),
        "cost_upper_usd": sum(r["cost_upper_usd"] for r in rows),
        "combined_evidence_model_cost_upper_usd": combined,
        "budget": public_budget(ledger),
        "hosted": {k: v for k, v in audit.items() if k != "rows"},
        "private_journal_spans_verified": sum(r["journal_spans"] for r in journal["conversations"]),
        "journal_verification_sha256": sha(OUT / "journal-verification.json"),
        "financial_results_exported": False,
        "scope": "Eight selected engineering regressions, one execution each. Checks establish the repaired handoff contract, not narrative correctness or financial improvement.",
    }
    (PUBLIC / "results.json").write_bytes(canonical(result))
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    export()

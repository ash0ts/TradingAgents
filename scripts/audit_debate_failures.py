"""Audit failed actors without inventing the callback events they did not save.

Successful actors retain the original callback reconciliation. Failed actors
instead reconcile dispatched model counts and reported usage with the durable
ledger, plus exact original span IDs in the OTLP journal. Unknown API charges
remain unknown, even when their error spans are present.
"""
from __future__ import annotations

import gzip
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import audit_evidence_campaign as original
from recover_journaled_traces import records
from run_debate_ablation import LEDGER, OUT, sha

from tradingagents.lab.budget import Ledger
from tradingagents.lab.evidence import canonical
from tradingagents.lab.lens import LensClient


def audit_failed(path, journal):
    row = json.loads(path.read_text())
    assert row["status"] == "failed" and "events" not in row
    raw = OUT / "native-spans" / (row["conversation_id"] + ".json.gz")
    saved = OUT / "hosted-readback" / (row["conversation_id"] + ".json")
    prior = json.loads(saved.read_text()) if saved.exists() else {}
    spans = (json.loads(gzip.decompress(raw.read_bytes()))
             if raw.exists() and prior.get("native_span_export_sha256") == sha(raw)
             else LensClient().spans(row["conversation_id"]))
    ids = {s["span_id"] for s in spans}
    assert spans and len(ids) == len(spans)
    assert ids == {r["span_id"] for r in journal[row["conversation_id"]]}
    for span in spans:
        assert span["eval_run_id"] == row["evaluation_ids"]["weave.eval.run_id"]
        assert span["eval_predict_and_score_call_id"] == row["evaluation_ids"]["weave.eval.predict_and_score_call_id"]
        assert not span["parent_span_id"] or span["parent_span_id"] in ids
        assert span["started_at"][:10] >= row["started_at"][:10] and span["ended_at"]
    models = [s for s in spans if s["operation_name"] == "chat"]
    with Ledger(LEDGER).connect() as db:
        calls = db.execute("SELECT status,usage FROM calls WHERE run_key=?", (row["run_key"],)).fetchall()
    assert len(models) == len(calls) == row["calls"]
    known = [json.loads(usage) for status, usage in calls if status == "settled" and usage]
    errors = [m for m in models if m["status_code"] == "ERROR"]
    unknown = sum(usage is None for _, usage in calls)
    assert unknown == row["unknown_calls"] == len(errors)
    assert all(m["input_tokens"] == m["output_tokens"] == 0 for m in errors)
    expected = Counter((u["input_tokens"], u["output_tokens"], (u.get("input_token_details") or {}).get("cache_read", 0)) for u in known)
    observed = Counter((m["input_tokens"], m["output_tokens"], m["cache_read_input_tokens"]) for m in models if m not in errors)
    assert expected == observed
    for model in models:
        request = "\n".join(original.strings([model["input_messages"], model["system_instructions"]]))
        assert "EVALUATION MANDATE" in request
        marker = "COMMON FROZEN DECISION BRIEF\n"
        assert marker in request
        assert json.loads(request.split(marker, 1)[1].split("\n", 1)[0]) == row["evidence_view"]
        assert all(row["execution_mandate"][k] in request for k in ("ticker", "decision_date", "entry_date", "exit_date", "benchmark"))
    assert any(s["status_code"] == "ERROR" for s in spans if s["operation_name"] == "invoke_agent")
    result = {"audit_schema": 3, "conversation_id": row["conversation_id"],
              "span_count": len(spans), "model_calls": len(models),
              "tool_calls": sum(s["operation_name"] == "execute_tool" for s in spans),
              "agents": sorted({s["agent_name"] for s in spans if s["operation_name"] == "invoke_agent"}),
              "all_spans_linked": True, "usage_reconciled": True,
              "usage_scope": "Recorded successful-call usage matches ledger multiset; failed requests have unknown usage and retain reserves.",
              "unknown_api_calls": unknown, "actor_status": "failed",
              "trace_complete": True, "journal_matches_native": True,
              "missing_native_activity": {}, "missing_native_subagents": {},
              "incident": row["error"], "trace_ids": sorted({s["trace_id"] for s in spans}),
              "arm": row["evidence_mode"], "case_id": row["case_id"], "treatment": row["treatment"], "trial": row["trial"],
              "prediction_sha256": sha(path), "all_model_requests_have_mandate": True,
              "all_observed_model_requests_have_mandate": True, "all_model_requests_have_exact_brief": True,
              "all_observed_model_requests_have_exact_brief": True, "brief_sha256": row["evidence_view"]["view_sha256"],
              "callback_events_unavailable": True}
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(gzip.compress(canonical(spans), mtime=0))
    result["native_span_export_sha256"] = sha(raw)
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main(phase):
    original.OUT = OUT
    journal = records(OUT / "trace-journal/wandb/tradingagents-election-lab-evidence")
    paths = sorted(OUT.glob(f"*/{phase}/**/prediction.json"))
    def audit(path):
        row = json.loads(path.read_text())
        value = original.audit(path) if row["status"] == "success" else audit_failed(path, journal)
        raw = OUT / "native-spans" / (row["conversation_id"] + ".json.gz")
        spans = json.loads(gzip.decompress(raw.read_bytes()))
        assert {s["span_id"] for s in spans} == {r["span_id"] for r in journal[row["conversation_id"]]}
        return value
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(audit, paths))
    result = {"conversations": len(rows), "spans": sum(r["span_count"] for r in rows),
              "model_calls": sum(r["model_calls"] for r in rows),
              "all_evaluation_links_verified": all(r["all_spans_linked"] for r in rows),
              "all_usage_reconciled": all(r["usage_reconciled"] for r in rows),
              "usage_scope": "All reported successful-call usage; unreported failed-call usage remains unknown.",
              "unknown_api_calls": sum(r.get("unknown_api_calls", 0) for r in rows),
              "complete_conversations": sum(r["trace_complete"] for r in rows),
              "incomplete_conversations": [r for r in rows if not r["trace_complete"]],
              "journal_matches_native": True,
              **{k: all(r[k] for r in rows) for k in ("all_model_requests_have_mandate", "all_model_requests_have_exact_brief", "all_observed_model_requests_have_exact_brief", "all_observed_model_requests_have_mandate")},
              "rows": rows}
    (OUT / f"{phase}-hosted-audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("campaign", "qualification"), default="campaign")
    main(parser.parse_args().phase)

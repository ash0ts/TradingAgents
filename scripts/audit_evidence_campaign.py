"""Read back each native trace and verify the complete brief in every model request."""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from run_repaired_evidence_campaign import OUT, sha

from tradingagents.lab.evidence import canonical
from tradingagents.lab.lens import LensClient


def strings(value):
    if isinstance(value, str):
        yield value
        if value.startswith(("[", "{", '"')):
            try:
                decoded = json.loads(value)
            except (ValueError, TypeError):
                return
            if decoded != value:
                yield from strings(decoded)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)


def audit(path):
    row = json.loads(path.read_text())
    saved = OUT / "hosted-readback" / (row["conversation_id"] + ".json")
    raw = OUT / "native-spans" / (row["conversation_id"] + ".json.gz")
    cached = json.loads(saved.read_text()) if saved.exists() else {}
    if cached:
        assert cached["prediction_sha256"] == sha(path)
    if raw.exists() and cached.get("native_span_export_sha256") == sha(raw):
        spans = json.loads(gzip.decompress(raw.read_bytes()))
    else:
        spans = LensClient().spans(row["conversation_id"])
    assert spans, row["conversation_id"]
    ids = {s["span_id"] for s in spans}
    assert len(ids) == len(spans), "Duplicate native span IDs"
    for span in spans:
        assert span["eval_run_id"] == row["evaluation_ids"]["weave.eval.run_id"]
        assert span["eval_predict_and_score_call_id"] == row["evaluation_ids"]["weave.eval.predict_and_score_call_id"]
        assert not span["parent_span_id"] or span["parent_span_id"] in ids
        assert span["started_at"][:10] >= row["started_at"][:10]
        assert span["ended_at"]
    models = [s for s in spans if s["operation_name"] == "chat"]
    usage = [e["usage"] for e in row.get("events", []) if e["kind"] == "llm" and e["usage"]]
    missing = {
        "model_calls": len(usage) - len(models),
        "tool_calls": sum(e["kind"] == "tool_start" for e in row["events"])
        - sum(s["operation_name"] == "execute_tool" for s in spans),
        **{k: sum(u[k] for u in usage) - sum(s[k] for s in models)
           for k in ("input_tokens", "output_tokens")},
    }
    expected_agents = Counter(e["name"] for e in row["events"] if e["kind"] == "subagent_end")
    observed_agents = Counter(s["agent_name"] for s in spans if s["operation_name"] == "invoke_agent" and s["parent_span_id"])
    missing_agents = dict(expected_agents - observed_agents)
    assert not observed_agents - expected_agents
    complete = not any(missing.values()) and not missing_agents
    if not complete:
        # This exact observed incident is retained, never silently waived.
        assert row["conversation_id"] == "ae47ff2b-38b4-5f86-9490-ae6b86d0ba33", (row["run_key"], missing)
        assert missing_agents == {"Bull Researcher": 1}
        assert missing == {"model_calls": 1, "tool_calls": 0, "input_tokens": 9836, "output_tokens": 2340}, missing
    result = {
        "audit_schema": 2, "conversation_id": row["conversation_id"],
        "span_count": len(spans), "model_calls": len(models),
        "tool_calls": sum(s["operation_name"] == "execute_tool" for s in spans),
        "agents": sorted({s["agent_name"] for s in spans if s["operation_name"] == "invoke_agent"}),
        "all_spans_linked": True, "usage_reconciled": complete,
        "trace_complete": complete, "missing_native_activity": missing,
        "missing_native_subagents": missing_agents,
        "incident": None if complete else "Bull Researcher subagent and model spans missing after an exporter timeout; local response and usage retained; actual request not recoverable; no rerun or reconstructed span.",
        "trace_ids": sorted({s["trace_id"] for s in spans}),
    }
    models = [s for s in spans if s["operation_name"] == "chat"]
    for model in models:
        request = "\n".join(strings([model["input_messages"], model["system_instructions"]]))
        assert "EVALUATION MANDATE" in request, row["run_key"]
        marker = "COMMON FROZEN DECISION BRIEF\n"
        assert marker in request, ("Common brief missing", row["run_key"], model["span_id"])
        observed = json.loads(request.split(marker, 1)[1].split("\n", 1)[0])
        # Prediction files sort keys for hashing; prompt key order is immaterial.
        assert observed == row["evidence_view"], (
            "Common brief changed",
            row["run_key"],
            model["span_id"],
        )
        for key in ("ticker", "decision_date", "entry_date", "exit_date", "benchmark"):
            assert row["execution_mandate"][key] in request
    result.update(
        arm=row["evidence_mode"],
        case_id=row["case_id"],
        treatment=row["treatment"],
        trial=row["trial"],
        prediction_sha256=sha(path),
        all_model_requests_have_mandate=complete,
        all_observed_model_requests_have_mandate=True,
        all_model_requests_have_exact_brief=complete,
        all_observed_model_requests_have_exact_brief=True,
        brief_sha256=row["evidence_view"]["view_sha256"],
    )
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(gzip.compress(canonical(spans), mtime=0))
    result["native_span_export_sha256"] = sha(raw)
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main(phase):
    paths = sorted(OUT.glob(f"*/{phase}/**/prediction.json"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(audit, paths))
    result = {
        "conversations": len(rows),
        "spans": sum(r["span_count"] for r in rows),
        "model_calls": sum(r["model_calls"] for r in rows),
        "all_evaluation_links_verified": all(r["all_spans_linked"] for r in rows),
        "all_usage_reconciled": all(r["usage_reconciled"] for r in rows),
        "all_model_requests_have_mandate": all(r["all_model_requests_have_mandate"] for r in rows),
        "all_model_requests_have_exact_brief": all(
            r["all_model_requests_have_exact_brief"] for r in rows
        ),
        "complete_conversations": sum(r["trace_complete"] for r in rows),
        "incomplete_conversations": [r for r in rows if not r["trace_complete"]],
        "all_observed_model_requests_have_exact_brief": all(r["all_observed_model_requests_have_exact_brief"] for r in rows),
        "all_observed_model_requests_have_mandate": all(r["all_observed_model_requests_have_mandate"] for r in rows),
        "rows": rows,
    }
    (OUT / f"{phase}-hosted-audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["qualification", "campaign"], default="campaign")
    main(parser.parse_args().phase)

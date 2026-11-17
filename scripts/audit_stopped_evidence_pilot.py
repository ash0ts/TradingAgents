"""Read back each native trace and verify the complete brief in every model request."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor

from run_evidence_campaign import OUT, sha

from tradingagents.lab.lens import LensClient, audit_spans


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
    if saved.exists():
        result = json.loads(saved.read_text())
        assert result["prediction_sha256"] == sha(path)
        return result
    spans = LensClient().spans(row["conversation_id"])
    result = audit_spans(row, spans)
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
        all_model_requests_have_mandate=True,
        all_model_requests_have_exact_brief=True,
        brief_sha256=row["evidence_view"]["view_sha256"],
    )
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
        "rows": rows,
    }
    (OUT / f"{phase}-hosted-audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["qualification", "campaign"], default="campaign")
    main(parser.parse_args().phase)

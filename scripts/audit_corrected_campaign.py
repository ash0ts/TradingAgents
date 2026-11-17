"""Read back native corrected traces; cache verified immutable executions."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tradingagents.lab.lens import LensClient, audit_spans

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "lab-runs/election-contract-v2"


def audit(path):
    row = json.loads(path.read_text())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    saved = OUT / "hosted-readback" / (row["conversation_id"] + ".json")
    if saved.exists():
        result = json.loads(saved.read_text())
        assert result["prediction_sha256"] == digest
        return result
    spans = LensClient().spans(row["conversation_id"])
    result = audit_spans(row, spans)
    models = [s for s in spans if s["operation_name"] == "chat"]
    for span in models:
        # Check actual logged request content, not metadata alone.
        request = json.dumps([span["input_messages"], span["system_instructions"]])
        assert "EVALUATION MANDATE" in request, span.keys()
        for key in ("ticker", "decision_date", "entry_date", "exit_date", "benchmark"):
            assert row["execution_mandate"][key] in request
    result.update(case_id=row["case_id"], treatment=row["treatment"], trial=row["trial"],
                  prediction_sha256=digest, all_model_requests_have_mandate=True)
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    paths = sorted((OUT / "campaign").rglob("prediction.json"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(audit, paths))
    result = {"conversations": len(rows), "spans": sum(r["span_count"] for r in rows),
              "model_calls": sum(r["model_calls"] for r in rows),
              "all_evaluation_links_verified": all(r["all_spans_linked"] for r in rows),
              "all_usage_reconciled": all(r["usage_reconciled"] for r in rows),
              "all_model_requests_have_mandate": all(r["all_model_requests_have_mandate"] for r in rows),
              "rows": rows}
    (OUT / "hosted-audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}))


if __name__ == "__main__":
    main()

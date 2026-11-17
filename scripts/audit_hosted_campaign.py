"""Reconcile persisted predictions with native hosted spans without exporting content."""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tradingagents.lab.lens import LensClient, audit_spans


def audit_one(path):
    row = json.loads(path.read_text())
    spans = LensClient().spans(row["conversation_id"])
    result = audit_spans(row, spans)
    result["case_id"] = row["case_id"]
    result["treatment"] = row["treatment"]
    result["readback_json_bytes"] = len(json.dumps(spans).encode())
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="lab-runs/election-v1")
    args = parser.parse_args()
    output = Path(args.output)
    paths = sorted((output / "campaign").rglob("prediction.json"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(audit_one, paths))
    result = {"conversations": len(rows), "spans": sum(r["span_count"] for r in rows),
              "model_calls": sum(r["model_calls"] for r in rows),
              "all_evaluation_links_verified": all(r["all_spans_linked"] for r in rows),
              "all_usage_reconciled": all(r["usage_reconciled"] for r in rows),
              "readback_json_bytes": sum(r["readback_json_bytes"] for r in rows),
              "rows": rows}
    (output / "hosted-audit.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}))

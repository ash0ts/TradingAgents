"""Inspect a private native OTLP journal and optionally retry only missing spans.

No model is called. Original payloads, IDs, parentage and timestamps are reused.
A successful HTTP response is followed by native readback, never assumed complete.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import requests
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)

from tradingagents.lab.lens import LensClient


def records(directory):
    result = defaultdict(list)
    for path in sorted(Path(directory).glob("*.otlp")):
        payload = path.read_bytes()
        request = ExportTraceServiceRequest.FromString(payload)
        assert len(request.resource_spans) == 1
        resource = request.resource_spans[0]
        attributes = {a.key: a.value.string_value for a in resource.resource.attributes}
        project = attributes["wandb.entity"] + "/" + attributes["wandb.project"]
        assert len(resource.scope_spans) == 1 and len(resource.scope_spans[0].spans) == 1
        span = resource.scope_spans[0].spans[0]
        attrs = {a.key: a.value.string_value for a in span.attributes}
        cid = attrs["gen_ai.conversation.id"]
        result[cid].append({
            "span_id": span.span_id.hex(), "trace_id": span.trace_id.hex(),
            "project": project, "path": path, "payload": payload,
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    return result


def reconcile(directory, project, apply=False):
    client = LensClient(project)
    receipts = []
    for cid, saved in records(directory).items():
        assert all(r["project"] == project for r in saved), "Journal destination differs from requested project"
        hosted = {s["span_id"] for s in client.spans(cid)}
        missing = [r for r in saved if r["span_id"] not in hosted]
        if apply:
            for record in missing:
                response = requests.post(
                    "https://trace.wandb.ai/agents/otel/v1/traces",
                    headers={"wandb-api-key": client.session.headers["Authorization"].removeprefix("Bearer "),
                             "project_id": project, "Content-Type": "application/x-protobuf"},
                    data=record["payload"], timeout=60,
                )
                response.raise_for_status()
                if response.content:
                    body = ExportTraceServiceResponse.FromString(response.content)
                    assert not body.partial_success.rejected_spans, "OTLP rejected spans; journal retained"
            hosted = {s["span_id"] for s in client.spans(cid)}
        receipts.append({"conversation_id": cid, "journal_spans": len(saved),
                         "missing_before": [r["span_id"] for r in missing],
                         "missing_after_readback": [r["span_id"] for r in saved if r["span_id"] not in hosted],
                         "submitted": len(missing) if apply else 0,
                         "journal_sha256": {r["span_id"]: r["sha256"] for r in saved}})
    return {"project": project, "apply": apply, "model_calls": 0, "conversations": receipts}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--project", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = reconcile(args.directory, args.project, args.apply)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"conversations": len(result["conversations"]), "missing": sum(len(r["missing_after_readback"]) for r in result["conversations"])}))

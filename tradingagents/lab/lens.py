"""Supported hosted Agent Lens views, tags, and span readback; no product changes."""
from __future__ import annotations

import json
import netrc
import os
from urllib.parse import urlencode

import requests


class LensClient:
    def __init__(self, project="wandb/tradingagents-election-lab-evidence"):
        self.project = project
        entity, name = project.split("/")
        key = os.getenv("WANDB_API_KEY")
        if not key:
            key = netrc.netrc().authenticators("api.wandb.ai")[2]
        self.session = requests.Session()
        self.session.headers.update({"Authorization": "Bearer " + key,
                                     "x-wandb-entity": entity, "x-wandb-project": name})
        self.base = "https://forge.coreweave.com/api/pulse"

    def request(self, method, path, body=None):
        response = self.session.request(method, self.base + path, json=body, timeout=60)
        response.raise_for_status()
        return response.json() if response.content else None

    def spans(self, conversation_id):
        return self.request("POST", "/weave/agents/spans/query", {
            "project_id": self.project, "limit": 10000, "include_details": True,
            "query": {"$expr": {"$eq": [{"$getField": "conversation_id"}, {"$literal": conversation_id}]}}
        })["spans"]

    def tag(self, conversation_id, trace_id, name):
        # Explicit tag names disclose provenance; deterministic candidates are
        # never passed off as a reviewed human judgment.
        return self.request("POST", "/conversation-tags", {
            "conversation_id": conversation_id, "trace_id": trace_id, "tag_name": name})

    def save_views(self):
        base = f"/agent-lens/{self.project}/conversations"
        views = [("Election lab · all conversations", []),
                 ("Election lab · tool failures", [{"id": "errors", "value": {"operator": "gt", "value": 0}}]),
                 ("Election lab · reviewed cases", [{"id": "tags", "value": {"operator": "contains", "value": "reviewed:"}}])]
        for name in ["default-committee", "luna-committee", "single-luna"]:
            views.append(("Election lab · " + name, [{"id": "agent", "value": {"operator": "eq", "value": [name]}}]))
        existing = {v["name"]: v for v in self.request("GET", "/views")["data"]}
        saved = []
        for name, filters in views:
            url = base + ("?" + urlencode({"filter": json.dumps(filters, separators=(",", ":"))}) if filters else "")
            body = {"name": name, "description": "Frozen retrospective campaign; inspect behavior separately from returns.", "url": url}
            if name in existing:
                result = self.request("PATCH", "/views/" + existing[name]["id"], body)
            else:
                result = self.request("POST", "/views", body)
            saved.append(result["data"])
        return saved


def audit_spans(row, spans):
    if not spans:
        raise ValueError("No hosted spans found")
    expected = row["evaluation_ids"]
    ids = {s["span_id"] for s in spans}
    for span in spans:
        assert span["eval_run_id"] == expected["weave.eval.run_id"]
        assert span["eval_predict_and_score_call_id"] == expected["weave.eval.predict_and_score_call_id"]
        assert not span["parent_span_id"] or span["parent_span_id"] in ids
        assert span["started_at"][:10] >= row["started_at"][:10]
        assert span["ended_at"]
    model_spans = [s for s in spans if s["operation_name"] == "chat"]
    local_usage = [e["usage"] for e in row.get("events", []) if e["kind"] == "llm" and e["usage"]]
    for field in ["input_tokens", "output_tokens"]:
        assert sum(s[field] for s in model_spans) == sum(u[field] for u in local_usage)
    return {"conversation_id": row["conversation_id"], "span_count": len(spans), "model_calls": len(model_spans),
            "tool_calls": sum(s["operation_name"] == "execute_tool" for s in spans),
            "agents": sorted({s["agent_name"] for s in spans if s["operation_name"] == "invoke_agent"}),
            "all_spans_linked": True, "usage_reconciled": True,
            "trace_ids": sorted({s["trace_id"] for s in spans})}

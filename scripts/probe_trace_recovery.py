"""Real HTTP-export failure and exact-payload hosted recovery, with no model call."""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

from coreweave.forge.agentlens import tracing
from recover_journaled_traces import reconcile, records
from run_debate_ablation import OUT, PUBLIC, sha

from tradingagents.lab.evidence import canonical
from tradingagents.lab.lens import LensClient
from tradingagents.observability.agent_lens import conversation_url
from tradingagents.observability.trace_journal import TraceJournal


def run():
    directory = OUT / "fault-injection"
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / "started.json"
    assert not marker.exists(), "Inspect the existing probe; never silently replace it"
    cid = str(uuid4())
    marker.write_bytes(canonical({"conversation_id": cid, "started_at": datetime.now(UTC).isoformat()}))
    requests_seen = []

    class RejectingServer(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = self.rfile.read(int(self.headers["Content-Length"]))
            requests_seen.append({"path": self.path, "payload_bytes": len(payload), "status": 503})
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b"Intentional journal recovery integration fixture")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), RejectingServer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    os.environ["OTEL_EXPORTER_OTLP_TRACES_TIMEOUT"] = "1"
    project = "wandb/tradingagents-election-lab-evidence"
    session = tracing.init(project, api_key="local-fixture-not-a-credential",
                           base_url=f"http://127.0.0.1:{server.server_port}", autopatch_integrations=False)
    session.provider.add_span_processor(TraceJournal(directory / "journal", project))
    try:
        with tracing.start_conversation(agent_name="Journal recovery engineering fixture", conversation_id=cid,  # noqa: SIM117
                                        conversation_name="Intentional export failure — no investment decision",
                                        attributes={"tradingagents.study_kind": "synthetic engineering fixture; no model inference"}) as conversation:
            with conversation.start_turn(user_message="Run a local arithmetic fixture, reject its OTLP export, then recover the exact saved spans.") as turn:
                with tracing.start_tool(name="local_arithmetic_fixture", arguments={"a": 2, "b": 3}) as tool:
                    tool.result = {"sum": 2 + 3}
                turn.output_messages = [tracing.Message(role="assistant", content="Local fixture returned 5. This is an export-recovery integration test, not a model response or trading result.")]
        flush = tracing.force_flush()
    finally:
        tracing.shutdown()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert requests_seen and all(r["status"] == 503 for r in requests_seen)
    journal_dir = directory / "journal" / project
    saved = records(journal_dir)[cid]
    client = LensClient(project)
    assert client.spans(cid) == [], "Probe unexpectedly reached hosted storage before recovery"
    recovery = reconcile(journal_dir, project, apply=True)
    (directory / "recovery.json").write_bytes(canonical(recovery))
    for _ in range(15):
        spans = client.spans(cid)
        if {s["span_id"] for s in spans} == {r["span_id"] for r in saved}:
            break
        time.sleep(2)
    assert {s["span_id"] for s in spans} == {r["span_id"] for r in saved}
    assert not any(s["operation_name"] == "chat" for s in spans)
    tool = next(s for s in spans if s["operation_name"] == "execute_tool")
    assert json.loads(tool["tool_call_arguments"]) == {"a": 2, "b": 3}
    assert json.loads(tool["tool_call_result"]) == {"sum": 5}
    assert all(r["sha256"] == sha(r["path"]) for r in saved)
    client.tag(cid, spans[0]["trace_id"], "synthetic-engineering-export-recovery")
    (directory / "native-spans.json").write_bytes(canonical(spans))
    receipt = {"kind": "Synthetic engineering integration fixture, not an agent decision",
               "verified_at": datetime.now(UTC).isoformat(), "http_export_attempts": requests_seen,
               "force_flush_returned": flush, "hosted_spans_before_recovery": 0,
               "original_journal_spans": len(saved), "hosted_spans_after_recovery": len(spans),
               "original_ids_preserved": True, "actual_tool_arguments_and_result_verified": True,
               "journal_payloads_unchanged": True, "model_calls": 0,
               "conversation_url": conversation_url(project, cid),
               "boundary": "Demonstrates recovery of already-journaled spans after an intentional HTTP 503. Does not recover the older unjournaled gap or guarantee recovery when disk persistence fails."}
    (PUBLIC / "trace-recovery-probe.json").write_bytes(canonical(receipt))
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    run()

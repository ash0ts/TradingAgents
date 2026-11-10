"""Private journal preserves actual native spans across failed exports."""
import os

import pytest

pytest.importorskip("coreweave.forge.agentlens.tracing")
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from tradingagents.observability.trace_journal import TraceJournal


class FailedExporter(SpanExporter):
    def export(self, spans):
        return SpanExportResult.FAILURE


def test_exact_span_survives_failed_network_export(tmp_path):
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(FailedExporter()))
    journal = TraceJournal(tmp_path, "wandb/test")
    provider.add_span_processor(journal)
    tracer = provider.get_tracer("test")
    with (
        tracer.start_as_current_span("committee") as parent,
        tracer.start_as_current_span("chat", attributes={"request": "actual input", "response": "actual output", "weave.eval.run_id": "eval-1"}) as child,
    ):
        child_id = child.context.span_id
        parent_id = parent.context.span_id
    assert provider.force_flush()
    files = list(journal.directory.glob("*.otlp"))
    assert len(files) == 2
    records = [ExportTraceServiceRequest.FromString(p.read_bytes()).resource_spans[0].scope_spans[0].spans[0] for p in files]
    model = next(x for x in records if x.name == "chat")
    assert int.from_bytes(model.span_id, "big") == child_id
    assert int.from_bytes(model.parent_span_id, "big") == parent_id
    assert model.start_time_unix_nano < model.end_time_unix_nano
    assert {a.key: a.value.string_value for a in model.attributes} == {"request": "actual input", "response": "actual output", "weave.eval.run_id": "eval-1"}
    assert all(os.stat(p).st_mode & 0o077 == 0 for p in files)
    provider.shutdown()


def test_disk_failure_is_reported_without_changing_the_decision(tmp_path, monkeypatch):
    provider = TracerProvider()
    journal = TraceJournal(tmp_path, "wandb/test")
    provider.add_span_processor(journal)
    monkeypatch.setattr("tradingagents.observability.trace_journal.encode_spans", lambda _: (_ for _ in ()).throw(OSError("disk failure")))
    with provider.get_tracer("test").start_as_current_span("chat"):
        decision = "Hold"
    assert decision == "Hold"
    assert not provider.force_flush()
    assert not list(journal.directory.iterdir())
    provider.shutdown()


def test_optional_journal_uses_native_provider_without_autopatching(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from coreweave.forge.agentlens import tracing
    from coreweave.forge.agentlens.tracing import tracing as implementation

    from tradingagents.observability import agent_lens

    provider = TracerProvider()
    calls = []

    def initialize(project, **kwargs):
        calls.append((project, kwargs))
        return SimpleNamespace(provider=provider)

    monkeypatch.setattr(tracing, "init", initialize)
    monkeypatch.setattr(implementation, "is_enabled", lambda: bool(calls))
    monkeypatch.setattr(agent_lens, "_project", None)
    monkeypatch.setenv("TRADINGAGENTS_TRACE_JOURNAL", str(tmp_path))
    assert agent_lens._sdk("wandb/test") is tracing
    assert agent_lens._sdk("wandb/test") is tracing
    with provider.get_tracer("test").start_as_current_span("native"):
        pass
    assert calls == [("wandb/test", {"autopatch_integrations": False})]
    assert len(list((tmp_path / "wandb/test").glob("*.otlp"))) == 1
    provider.shutdown()

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from tradingagents.observability import agent_lens as lens


@pytest.fixture
def spans(monkeypatch):
    tracing = pytest.importorskip("coreweave.forge.agentlens.tracing")
    from coreweave.forge.agentlens.tracing import tracing as implementation
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    session = implementation.TracingSession(provider=provider, endpoint="unused", project_id="wandb/test")
    monkeypatch.setattr(implementation, "_session", session)
    monkeypatch.setattr(lens, "_sdk", lambda project: tracing)
    yield exporter
    provider.shutdown()


def test_parallel_analysts_have_correct_parents_and_one_usage_record(spans):
    config = {"forge_project": "wandb/test", "forge_metadata": {"case_id": "c1", "weave.eval.run_id": "eval-call"}}
    with lens.decision_scope(config, "AAPL", "2024-11-04") as handler:
        def run(name):
            actor, model, tool = uuid4(), uuid4(), uuid4()
            handler.on_chain_start({}, {}, run_id=actor, name=name)
            handler.on_chat_model_start({}, [[HumanMessage("Check prices")]], run_id=model,
                                        parent_run_id=actor, metadata={"ls_model_name": "test-model", "ls_provider": "test"})
            response = LLMResult(generations=[[ChatGeneration(message=AIMessage("Buy", usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}))]])
            handler.on_llm_end(response, run_id=model)
            handler.on_llm_end(response, run_id=model)
            handler.on_tool_start({"name": "get_price"}, '{"ticker":"AAPL"}', run_id=tool, parent_run_id=actor)
            handler.on_tool_end("100", run_id=tool)
            handler.on_chain_end({"market_report": "price 100"}, run_id=actor)
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(run, ["Market Analyst", "News Analyst"]))
        assert len([e for e in handler.events if e["kind"] == "llm"]) == 2
    all_spans = spans.get_finished_spans()
    assert len(all_spans) == 7
    by_id = {s.context.span_id: s for s in all_spans}
    for span in all_spans:
        assert span.attributes["weave.eval.run_id"] == "eval-call"
        if span.name.startswith(("chat", "execute_tool")):
            assert by_id[span.parent.span_id].name in {"invoke_agent Market Analyst", "invoke_agent News Analyst"}


def test_error_closes_spans_and_checkpoint_conversation_resumes(spans, tmp_path):
    config = {"forge_project": "wandb/test", "checkpoint_enabled": True, "data_cache_dir": str(tmp_path)}
    with pytest.raises(ValueError), lens.decision_scope(config, "MSFT", "2024-11-04", "same") as handler:
        cid = handler.conversation_id
        handler.on_tool_start({"name": "bad_tool"}, "", run_id=uuid4())
        raise ValueError("run failed")
    with lens.decision_scope(config, "MSFT", "2024-11-04", "same") as handler:
        assert handler.conversation_id == cid
    with lens.decision_scope(config, "MSFT", "2024-11-04", "same") as handler:
        assert handler.conversation_id != cid
    assert any(s.status.is_ok is False for s in spans.get_finished_spans())


def test_disabled_never_imports_or_initializes_sdk(monkeypatch):
    monkeypatch.setattr(lens, "_sdk", lambda _: pytest.fail("SDK initialized"))
    with lens.decision_scope({}, "AAPL", "2024-11-04") as handler:
        assert handler is None
        assert lens.graph_args({"config": {"recursion_limit": 10}}) == {"config": {"recursion_limit": 10}}


def test_redaction_and_url(monkeypatch):
    monkeypatch.setenv("EXAMPLE_API_KEY", "private-example-key")
    assert lens.redact({"api_key": "x", "report": "private-example-key"}) == {"report": "[REDACTED]"}
    assert lens.conversation_url("wandb/project", "a/b").endswith("/a%2Fb")


def test_cache_write_usage_and_error_events_survive_scope_exit(spans):
    events = []
    config = {"forge_project": "wandb/test", "forge_event_sink": events}
    with pytest.raises(RuntimeError, match="provider unavailable"), lens.decision_scope(config, "AAPL", "2024-11-04") as handler:
        model = uuid4()
        handler.on_chat_model_start({}, [[HumanMessage("Fixture request")]], run_id=model,
                                    metadata={"ls_model_name": "test-model"})
        response = LLMResult(generations=[[ChatGeneration(message=AIMessage(
            "Fixture response", usage_metadata={"input_tokens": 1000, "output_tokens": 100,
                "total_tokens": 1100, "input_token_details": {"cache_read": 200, "cache_creation": 500}}
        ))]])
        handler.on_llm_end(response, run_id=model)
        handler.on_llm_end(response, run_id=model)
        failed = uuid4()
        handler.on_chat_model_start({}, [[HumanMessage("Failing request")]], run_id=failed)
        error = RuntimeError("provider unavailable")
        handler.on_llm_error(error, run_id=failed)
        raise error
    model_spans = [s for s in spans.get_finished_spans() if s.name.startswith("chat")]
    assert len(model_spans) == 2
    assert sum(s.attributes.get("gen_ai.usage.cache_creation.input_tokens", 0) for s in model_spans) == 500
    assert sum(s.attributes.get("gen_ai.usage.cache_read.input_tokens", 0) for s in model_spans) == 200
    assert len([e for e in events if e["kind"] == "llm"]) == 1
    assert any(e["kind"] == "error" and e["run_id"] == str(failed) for e in events)
    assert all(s.end_time is not None for s in spans.get_finished_spans())

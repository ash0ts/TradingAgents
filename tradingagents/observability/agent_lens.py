"""Native Forge spans adapted from LangChain callbacks, without provider patching."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from functools import wraps
from pathlib import Path
from threading import RLock
from urllib.parse import quote
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)
_active = ContextVar("tradingagents_agent_lens", default=None)
_session_lock = RLock()
_project = None
ACTORS = frozenset({
    "Market Analyst", "Sentiment Analyst", "News Analyst", "Fundamentals Analyst",
    "Bull Researcher", "Bear Researcher", "Research Manager", "Trader",
    "Aggressive Analyst", "Conservative Analyst", "Neutral Analyst", "Portfolio Manager",
    "Memory Log",
})
_METADATA = ("campaign_id", "case_id", "treatment", "trial", "attempt", "cohort",
             "dataset_version", "code_revision", "outcome_status")


def redact(value):
    if isinstance(value, dict):
        return {str(k): redact(v) for k, v in value.items()
                if not re.search(r"api.?key|authorization|password|secret|access.token", str(k), re.I)}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    text = str(value)
    for key, secret in os.environ.items():
        if re.search(r"(?:KEY|TOKEN|SECRET|PASSWORD)$", key) and len(secret) >= 8:
            text = text.replace(secret, "[REDACTED]")
    return re.sub(r"\bsk-[A-Za-z0-9_-]{12,}", "[REDACTED]", text)


def _text(value):
    if isinstance(value, str):
        return redact(value)
    if hasattr(value, "content"):
        content = value.content
        if isinstance(content, list):
            content = "\n".join(part if isinstance(part, str) else part.get("text", "")
                                for part in content if isinstance(part, str) or part.get("type") in {"text", "output_text"})
        calls = getattr(value, "tool_calls", None)
        if calls:
            content += "\nTool calls: " + json.dumps(redact(calls), ensure_ascii=False)
        return _text(content)
    return json.dumps(redact(value), ensure_ascii=False, default=str)


def conversation_url(project, conversation_id):
    return "https://forge.coreweave.com/agent-lens/" + "/".join(
        quote(part, safe="") for part in (*project.split("/"), "conversations", conversation_id))


def _sdk(project):
    global _project
    try:
        from coreweave.forge.agentlens import tracing
        from coreweave.forge.agentlens.tracing.tracing import is_enabled
    except ImportError as exc:
        raise RuntimeError('Agent Lens requires pip install "tradingagents[forge]"') from exc
    with _session_lock:
        if _project != project or not is_enabled():
            session = tracing.init(project, autopatch_integrations=False)
            if directory := os.environ.get("TRADINGAGENTS_TRACE_JOURNAL"):
                from tradingagents.observability.trace_journal import TraceJournal

                session.provider.add_span_processor(TraceJournal(directory, project))
            _project = project
    return tracing


class AgentLensCallback(BaseCallbackHandler):
    """Pin parent spans explicitly: concurrent callback contexts need not match."""

    run_inline = True

    def __init__(self, sdk, turn, attributes):
        self.sdk, self.turn, self.attributes = sdk, turn, attributes
        self._root_context = copy_context()
        self._owners, self._spans = {}, {}
        self._lock = RLock()
        self.events = []

    def _start(self, run_id, parent_run_id, kind, **kwargs):
        with self._lock:
            if run_id in self._spans:
                return
            parent = self._owners.get(parent_run_id, self.turn)
            # LLM/tool callbacks may be delivered in different worker threads.
            context = self._root_context.copy()
            span = context.run(getattr(parent, f"start_{kind}"), **kwargs)
            span.set_attributes(self.attributes)
            self._spans[run_id] = (span, context, kind, time.monotonic())
            self._owners[run_id] = span if kind == "subagent" else parent
            return span

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        name = kwargs.get("name") or (serialized or {}).get("name", "")
        if name in ACTORS:
            self._start(run_id, parent_run_id, "subagent", name=name, set_current=False)
        else:
            with self._lock:
                self._owners[run_id] = self._owners.get(parent_run_id, self.turn)

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        meta = kwargs.get("metadata") or {}
        params = kwargs.get("invocation_params") or {}
        span = self._start(run_id, parent_run_id, "llm",
                           model=meta.get("ls_model_name") or params.get("model_name") or params.get("model", ""),
                           provider_name=meta.get("ls_provider", ""))
        if span:
            roles = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}
            span.input_messages = [self.sdk.Message(role=roles.get(getattr(m, "type", "human"), "user"),
                                                   content=_text(m)) for batch in messages for m in batch]

    def on_llm_end(self, response, *, run_id, **kwargs):
        item = self._spans.get(run_id)
        if item:
            span = item[0]
            messages = [g.message for batch in response.generations for g in batch if hasattr(g, "message")]
            span.output_messages = [self.sdk.Message(role="assistant", content=_text(m)) for m in messages]
            usage = [getattr(m, "usage_metadata", None) for m in messages]
            usage = [u for u in usage if u]
            if usage:
                span.usage = self.sdk.Usage(
                    input_tokens=sum(u.get("input_tokens", 0) for u in usage),
                    output_tokens=sum(u.get("output_tokens", 0) for u in usage),
                    cache_read_input_tokens=sum((u.get("input_token_details") or {}).get("cache_read", 0) for u in usage),
                    reasoning_tokens=sum((u.get("output_token_details") or {}).get("reasoning", 0) for u in usage),
                )
            span.set_attributes({"tradingagents.usage_known": bool(usage)})
            self.events.append({"kind": "llm", "model": span.model,
                                "run_id": str(run_id), "response": _text(messages[-1]) if messages else "",
                                "usage": dict(span.usage) if usage else None})
        self._finish(run_id)

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kwargs):
        name = (serialized or {}).get("name", "tool")
        self._start(run_id, parent_run_id, "tool", name=name, arguments=_text(input_str))
        self.events.append({"kind": "tool_start", "run_id": str(run_id), "name": name,
                            "arguments": _text(input_str)})

    def on_tool_end(self, output, *, run_id, **kwargs):
        if item := self._spans.get(run_id):
            item[0].result = _text(output)
        self._finish(run_id)

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        if item := self._spans.get(run_id):
            visible = {k: v for k, v in (outputs or {}).items() if k != "messages"} if isinstance(outputs, dict) else outputs
            if visible:
                item[0].output_messages = [self.sdk.Message(role="assistant", content=_text(visible))]
        self._finish(run_id)

    def _error(self, error, *, run_id, **kwargs):
        self.events.append({"kind": "error", "run_id": str(run_id), "error": _text(error)})
        self._finish(run_id, RuntimeError(_text(error)))

    on_llm_error = _error
    on_tool_error = _error
    on_chain_error = _error

    def _finish(self, run_id, error=None):
        with self._lock:
            item = self._spans.pop(run_id, None)
            self._owners.pop(run_id, None)
        if item:
            span, context, kind, started = item
            self.events.append({"kind": kind + "_end", "run_id": str(run_id),
                                "latency_s": time.monotonic() - started,
                                "name": getattr(span, "name", ""),
                                "result": _text(getattr(span, "result", "")) if kind == "tool" else None})
            if error:
                span.record_error(error)
            context.run(span.end)

    def close(self):
        for run_id in reversed(list(self._spans)):
            self._finish(run_id, RuntimeError("Run ended before callback completion"))


def graph_args(args):
    handler = _active.get()
    if handler is None:
        return args
    config = dict(args.get("config") or {})
    callbacks = list(config.get("callbacks") or [])
    if handler not in callbacks:
        callbacks.append(handler)
    return {**args, "config": {**config, "callbacks": callbacks}}


@contextmanager
def decision_scope(config, ticker, date, signature=""):
    project = config.get("forge_project")
    if not project or _active.get() is not None:
        yield _active.get()
        return
    if len(project.split("/")) != 2 or not all(project.split("/")):
        raise ValueError("forge_project must be entity/project")
    sdk = _sdk(project)
    meta = config.get("forge_metadata") or {}
    attrs = {f"tradingagents.{k}": v for k, v in meta.items() if k in _METADATA}
    attrs.update({"tradingagents.ticker": ticker, "tradingagents.market_as_of": date})
    attrs.update({k: v for k, v in meta.items() if k.startswith("weave.eval.")})
    checkpoint = None
    cid = config.get("forge_conversation_id")
    if not cid and config.get("checkpoint_enabled"):
        key = hashlib.sha256(f"{ticker}|{date}|{signature}".encode()).hexdigest()
        checkpoint = Path(config["data_cache_dir"]) / "agent_lens" / f"{key}.json"
        if checkpoint.exists():
            cid = json.loads(checkpoint.read_text())["conversation_id"]
    cid = cid or str(uuid4())
    if checkpoint:
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text(json.dumps({"conversation_id": cid}))
    name = meta.get("treatment", "TradingAgents")
    try:
        with sdk.start_conversation(agent_name=name, conversation_id=cid,  # noqa: SIM117
                                    conversation_name=f"{ticker} · {date} · {name}", attributes=attrs) as conversation:
            with conversation.start_turn(user_message=f"Evaluate {ticker} using information available through {date}.") as turn:
                turn.set_attributes(attrs)
                handler = AgentLensCallback(sdk, turn, attrs)
                handler.conversation_id = cid
                handler.url = conversation_url(project, cid)
                token = _active.set(handler)
                try:
                    yield handler
                    if checkpoint:
                        checkpoint.unlink(missing_ok=True)
                finally:
                    handler.close()
                    _active.reset(token)
    finally:
        if not sdk.force_flush():
            logger.warning("Agent Lens export did not flush; local decisions remain available")


def trace_decision(func):
    @wraps(func)
    def wrapped(self, company_name, trade_date, *args, **kwargs):
        asset_type = kwargs.get("asset_type", args[0] if args else "stock")
        portfolio = kwargs.get("portfolio", args[2] if len(args) > 2 else None)
        signature = self._run_signature(asset_type, portfolio) if self.config.get("forge_project") else ""
        with decision_scope(self.config, company_name, trade_date, signature) as handler:
            result = func(self, company_name, trade_date, *args, **kwargs)
            if handler:
                handler.turn.output_messages = [handler.sdk.Message(role="assistant", content=_text(result[0].get("final_trade_decision", result[1])))]
                self.forge_result = {"conversation_id": handler.conversation_id, "url": handler.url,
                                     "events": handler.events}
            return result
    return wrapped


def trace_stream(func):
    @wraps(func)
    def wrapped(self, graph_input, **args):
        identity = graph_input or getattr(self, "_forge_input", {})

        def generate():
            with decision_scope(self.config, identity.get("company_of_interest", ""),
                                identity.get("trade_date", ""),
                                getattr(self, "_forge_signature", "")) as handler:
                final = {}
                for messages, state in func(self, graph_input, **graph_args(args)):
                    if state:
                        final.update(state)
                    yield messages, state
                if handler:
                    handler.turn.output_messages = [handler.sdk.Message(role="assistant", content=_text(final.get("final_trade_decision", "")))]
                    self.forge_result = {"conversation_id": handler.conversation_id, "url": handler.url,
                                         "events": handler.events}

        context = copy_context()
        stream = generate()
        try:
            while (step := context.run(next, stream, None)) is not None:
                yield step
        finally:
            context.run(stream.close)
    return wrapped


def trace_data(func):
    """Capture direct data reads that bypass LangChain's ToolNode callbacks."""
    @wraps(func)
    def wrapped(*args, **kwargs):
        handler = _active.get()
        if handler is None:
            return func(*args, **kwargs)
        from langchain_core.runnables.config import var_child_runnable_config
        config = var_child_runnable_config.get() or {}
        parent = getattr(config.get("callbacks"), "parent_run_id", None)
        # ToolNode already owns a complete tool span for ordinary tools.
        item = handler._spans.get(parent)
        if item and item[2] == "tool":
            return func(*args, **kwargs)
        run_id = uuid4()
        handler.on_tool_start({"name": func.__name__}, _text({"args": args, "kwargs": kwargs}),
                              run_id=run_id, parent_run_id=parent)
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            handler.on_tool_error(exc, run_id=run_id)
            raise
        handler.on_tool_end(result, run_id=run_id)
        return result
    return wrapped

# TradingAgents in Agent Lens

Install `pip install 'tradingagents[forge]'`, then set
`TRADINGAGENTS_FORGE_PROJECT=wandb/tradingagents-election-lab` and authenticate
with `WANDB_API_KEY` or your existing W&B netrc login. Python callers can set
`config['forge_project']` instead. Credentials are never stored in run metadata.

The native `coreweave.forge.agentlens.tracing` SDK records one conversation per
decision and nested analyst, model, and tool spans. Provider autopatching is
disabled: LangChain callbacks own model usage, preventing duplicate billing.
Parallel callbacks use explicit parent spans and isolated contexts. CLI streams
and Python `propagate()` share the same adapter; without `forge_project`, no
exporter is imported or initialized. Set `forge_conversation_id` for an external
attempt identity. Checkpointed runs otherwise retain their ID until success.

`graph.forge_result` contains the conversation ID, its Forge URL, and a local
event ledger after success. `forge_metadata` accepts campaign_id, case_id,
treatment, trial, attempt, cohort, dataset_version, code_revision, outcome_status,
and evaluation-link attributes beginning with `weave.eval.`. Historical market
cutoffs are metadata, never substituted for actual span timestamps.

For callers that must retain partial events after an exception, pass a fresh list
as `config['forge_event_sink']` for each attempt. The callback appends to that
caller-owned list even when no successful `forge_result` is returned. Model spans
record cache-read and cache-creation input tokens separately when the provider
reports them; repeated completion callbacks contribute usage only once.

Inspect the run at https://forge.coreweave.com/agent-lens. Read Thread for the
request and recommendation, Spans for agent/tool evidence, and Timeline for
parallel activity and latency. Missing token usage is marked unknown locally;
the product's cost chart alone is not an accounting ledger.

SDK contract: https://docs.coreweave.com/products/agent-lens/tracing/instrument

### Preserve exact spans for recovery

For private evaluation runs, set `TRADINGAGENTS_TRACE_JOURNAL` to a writable local
directory before the first traced call. The integration adds a standard
OpenTelemetry span processor to the native Forge session. It writes each ended
span as an OTLP payload under `<directory>/<entity>/<project>/`, with original
span/trace IDs, parentage, timestamps and already-redacted visible content.
Files use owner-only permissions and atomic replacement after flushing to disk.
This adds local disk work; it does not instrument a second model call or export a
second copy to the service. Keep these files private with the original evidence.

The native exporter still handles transmission. A successful `force_flush()`
means its queue was processed, not that every span reached the service. Compare
hosted span IDs and usage with local records. A journal permits retrying the exact
missing payload without a paid model rerun; it cannot reconstruct spans lost
before journaling was enabled. Disk failures are logged and make journal flush
report failure, while the existing decision path continues. With the environment
variable unset, the optional journal is not imported or created.

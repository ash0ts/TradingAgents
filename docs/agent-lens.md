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

Inspect the run at https://forge.coreweave.com/agent-lens. Read Thread for the
request and recommendation, Spans for agent/tool evidence, and Timeline for
parallel activity and latency. Missing token usage is marked unknown locally;
the product's cost chart alone is not an accounting ledger.

SDK contract: https://docs.coreweave.com/products/agent-lens/tracing/instrument

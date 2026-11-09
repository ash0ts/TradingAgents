# Support actions through Agent Lens

A small companion demonstration for the TradingAgents article. Six original synthetic refund requests, two Luna trials per request, and one deterministic policy workflow per request. No real customers, payment systems or emails. This is not a tau-bench run, a benchmark score, or evidence of deployment reliability.

The frozen fixtures include normal eligibility, the inclusive day-30 boundary, an out-of-window request with an instruction embedded in an untrusted note, an existing refund, a missing order, and an unavailable lookup. Each execution has isolated in-memory state. Session identity is bound outside model arguments. Both treatments use the same policy and tool enforcement. The deterministic workflow receives the structured request's bound order; it does not solve language understanding.

Freeze the fixture and runner hashes before dispatch. The Luna actor gets policy, the user request and tool results, never `expected`. Tool errors are retained; no automatic retries, replacements, or prompt tuning. Maximum eight model calls per execution, 1,024 output tokens each; reserve every request against the existing election ledger's publication allocation before dispatch. Stop at $1 additional known-or-reserved spend or the original $250/phase caps. An interrupted started execution must be inspected before retry. All runs and failures are reported.

The deterministic grader checks exact new refund amount, ticket count, reported status, reported receipt, prior lookup, and zero rejected refund attempts. A blocked unauthorized attempt fails even if final state is safe. It does not judge tone, every natural-language claim, customer satisfaction, or real payment settlement. Inspect the visible responses separately. Two trials are two runs on the same six fixtures, not 12 independent customer problems.

Run from the repository root in the pinned Forge/lab environment:

```sh
TRADINGAGENTS_MODELS_ENV=/path/to/models.env .venv/bin/python -m examples.support_lens.run --execute
.venv/bin/python -m examples.support_lens.run --audit
```

`--execute` is explicitly paid; importing the module, running tests, or rebuilding the article does not call a model. Predictions are persisted under ignored `lab-runs/support-v1/` before evaluation upload. Native Agent Lens owns model instrumentation; the existing Weave adapter supplies evaluation Call IDs to every span. The model uses the existing repository's Luna client and budget pricing. Local execution time and model usage are recorded separately from publication infrastructure.

The public export contains only these original synthetic fixtures, visible requests/responses, tool events, deterministic scores and derived audit counts. Private project identifiers and evaluation IDs remain in the local audit. Hosted Agent Lens drilldowns require team access.

# Investigating the committee

Open Agent Lens Overview for operational volume, then Conversations to compare
agents. Thread shows the research and final recommendation. Spans identifies the
analyst, evidence calls, and actual responses; Timeline shows parallel work and
where wall time went. Cost charts may omit unrecognized models: the campaign's
independent usage ledger remains the accounting source.

`tradingagents.lab.lens.LensClient.save_views()` creates six native saved views:
all campaign conversations, each of the three treatments, errors, and reviewed
cases. This uses the existing Forge saved-view API, authenticated with the current
W&B key; it changes no Forge or Agent Lens product code. Links and view definitions
are saved with the publication receipt. Raw prompts remain in the private evidence
project; a public notebook reader needs team access for those drilldowns.

Run `diagnostics.analyze(root, output)` on durable outputs. Tool errors and missing
source sentinels are observed events. Repeated calls, unsupported price claims,
claims about missing social data, contradictory labelled recommendations, and
failure to acknowledge gaps are **review candidates**, not automatic truth labels.
A changed trader/manager recommendation is evidence of deliberation, not inherently
an error. The rule output never uses the realized investment outcome.

Review the exact report and its evidence locator before confirming a failure.
Record reviewer identity, time, rationale, and label; tag a reviewed conversation
with `reviewed:<label>` and candidates with `candidate:<rule>`. Codex-assisted
reviews identify Codex as reviewer and are not described as human labels. Export
confirmed cases with `export_regressions`; their versioned dataset is explicitly
study-discovered and cannot later be reported as an untouched test set after tuning.

The notebooks choose the strongest and weakest matured signed-excess outcomes and
one seeded-random case. These are exploration examples, not a selected performance
estimate. All cases remain in denominators. LLM judging is disabled in this initial
release; enabling it later requires a reviewed calibration set, measured agreement,
a frozen judge configuration, and reservations from the same campaign ledger.
Automated Insights are optional: all investigation steps work without clusters.

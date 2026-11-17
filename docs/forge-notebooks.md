# Forge notebooks and publication

- [Meet the investment committee.](https://forge.coreweave.com/notebooks/Tm90ZWJvb2s6MTUyNjA%3D)
- [Confident, expensive, and wrong?](https://forge.coreweave.com/notebooks/Tm90ZWJvb2s6MTUyNzE%3D)
- [Did it beat doing nothing?](https://forge.coreweave.com/notebooks/Tm90ZWJvb2s6MTUyNzI%3D)

See [the initial findings](election-results.md) for denominators and limitations.
The published result artifact is
`wandb/tradingagents-election-lab/election-lab-public-results:v1`; the private
source artifact is
`wandb/tradingagents-election-lab-evidence/election-lab-frozen-evidence:v0`.
Exact saved notebook versions, source/static hashes, anonymous-access checks,
and trace reconciliation counts are in `notebooks/publication.json`.

The three native Marimo sources in `notebooks/` embed an allowlisted result
snapshot. Opening or exporting them makes no model calls. The first notebook's
run button requires an explicit click, local credentials, a frozen evidence
directory, and the same persistent campaign ledger. Authenticated Agent Lens
drilldowns belong to `wandb/tradingagents-election-lab-evidence`; the sanitized
notebooks belong to `wandb/tradingagents-election-lab`.

## Reproduce the saved results

Use Python 3.12 for the paid campaign environment in
`campaigns/environment.lock` (captured on macOS arm64). The notebook-only lock,
`notebooks/requirements.lock`, was also tested in a fresh Python 3.13 environment.
The native Forge editor currently runs Marimo 0.25.1; the portable notebook lock
uses 0.25.2. Both execute the saved-data cells successfully. The runtime checkpoint
receipt records the actual hosted package versions.

```sh
uv venv --python 3.13 /tmp/election-notebooks
uv pip sync --python /tmp/election-notebooks/bin/python notebooks/requirements.lock
/tmp/election-notebooks/bin/python -m marimo export html notebooks/01_meet_the_committee.py -o /tmp/committee.html
```

Regenerate from private local campaign artifacts only after all predictions are
durably saved. The exporter excludes prompts, reports, tool results, agent state,
and unrecognized prediction fields. It preserves evidence hashes, conversation
links, denominators, pending outcomes, and reviewed-label provenance.

```sh
python -m tradingagents.lab.publication
python scripts/build_forge_notebooks.py
python scripts/audit_hosted_campaign.py
python scripts/publish_forge_notebooks.py --import-source
```

## Native publication verification

The publisher creates actual Forge Notebook records and imports source into each
record's native artifact collection. API-key authentication can publish source
but cannot launch the current notebook runtime: launch it through the authenticated
Forge browser. Open the record, use **Config → Command palette → Re-run all cells**,
then save in the editor and inspect Preview. A Markdown title alone is not proof
that the Python cells executed.

For runtime images that save source without a static preview, run
`scripts/forge_runtime_checkpoint.py` in the native **Scratchpad** after executing
and saving. This exports actual outputs through the running Marimo server and
saves the source and HTML to the notebook's existing checkpoint collection. It
uses injected runtime credentials without copying them into notebook source.
The scratchpad is temporary. This requires no Forge or Agent Lens product change.

```sh
python scripts/publish_forge_notebooks.py --verify
python scripts/upload_campaign_artifacts.py
python scripts/upload_campaign_artifacts.py --public
```

Verification reads the exact `currentVersion`, downloads its source and static
HTML, and records both SHA-256 hashes. Reopen each saved record and verify that
its static output renders. The current API may return a null `lastStaticOutputAt`
even when the saved version contains HTML and `staticOutputUrl` resolves; receipts
retain that null instead of inventing a timestamp. Stop hosted runtimes afterward.

Publish the main project only after auditing its evaluation calls and artifacts.
The evidence project remains private. Public readers get sanitized saved examples;
Agent Lens links explicitly require W&B team access. Never publish raw evidence
to make an authenticated drilldown look public.

## Cost accounting

The SQLite ledger reserves model calls before dispatch and counts actual token
usage once. The initial run also holds $5 qualification ingestion, $150 campaign
ingestion, and $20 publication runtime headroom. These $175 holds are **not spent
amounts**. Model charges plus holds must stay below $250 and each phase cap. Keep
unreconciled infrastructure holds until billing is known. Runtime termination
and source/trace readback receipts document the hosted work; local training
hardware is unmetered. LLM judging is disabled in this initial release.

## Native Forge dashboards

The published [campaign report](https://forge.coreweave.com/wandb/wandb/tradingagents-election-lab/reports/Would-you-give-this-investment-committee-money--VmlldzoxODI2MzIwNQ==)
connects the [financial dashboard](https://forge.coreweave.com/wandb/wandb/tradingagents-election-lab?nw=0q277wzs5up)
and [behavior/cost dashboard](https://forge.coreweave.com/wandb/wandb/tradingagents-election-lab?nw=oc6zwblxo0y)
to the three notebooks and authenticated Agent Lens examples. These are native
W&B workspace/report records inside Forge, published to the `wandb` team.

Thirteen derived runs contain metrics and sanitized case-link tables. Each run
uses the immutable public-results artifact. No agent is rerun by this publisher.
All methods stay visible, including passive portfolios and unsuccessful financial
outcomes. Passive methods have no directional forecast; absent values are never
filled with zero. Charts show scored and pending trial counts, while notebooks
provide paired case comparisons and cohort-block uncertainty. Candidate behavior
flags remain separate from reviewed findings and financial performance.

```sh
pip install -e '.[dashboards]'
python scripts/reconcile_campaign.py
python scripts/publish_forge_dashboards.py
```

The first command in the workflow checks fingerprints, persisted predictions,
all outcome horizons, and all 640 portfolio sensitivity scenarios. The publisher
reconciles aggregate values, saves stable workspace/report identities in
`notebooks/dashboards.json`, and reads back all 13 run summaries and panel specs.
Subsequent invocations update those same records. It uses `summary_metrics` for
hosted readback; the SDK's separate summary-file wrapper can lag the API.

The original paid campaign executed locally with hosted traces/evaluations.
Saved notebook cells executed in native Forge runtimes. The optional paid-run
button has not been exercised inside a hosted notebook; do not describe the
campaign itself as having run on Forge compute. Publishing dashboards incurs no
additional model calls, and publication storage remains covered by the existing
infrastructure reservation.

The financial notebook now also embeds the post-hoc trading-scenario extension:
seven profiles across all original cases and methods, with cohort filtering,
exact account tables and a download. It makes no new model calls. Case IDs join
to the notebook's authenticated Agent Lens links and evidence hashes. The
separate scenario dashboard preserves the original financial and behavior
workspace filters. Public replay inputs and provenance live under
`articles/trading-scenarios`; raw vendor prices remain private.

## Matched evidence and handoff follow-up

The November 9 revision adds 360 matched-evidence executions, every individual
trial across the original/contract/shared/cited versions, 36 scoped assistant
reviews, and the complete 40-run stopped pilot. The investigation notebook also
shows eight separately frozen trader-handoff regressions with before/after
conversation links. These development checks are excluded from financial means.

The new comparison has 302 accepted execution contracts and 58 explicit
abstentions; four accepted contracts also allocate zero. Its native trace audit
is 359/360 complete, with the one unjournaled export gap retained in all financial
denominators. The eight later engineering executions reconcile 378 hosted spans
against their private OTLP journal. Citation matching, contract validation,
reviewed explanation quality and trading outcomes remain separate measurements.

The [matched-evidence workspace](https://forge.coreweave.com/wandb/wandb/tradingagents-election-lab?nw=94cw9owsbt4)
has seven native metrics panels and the separate handoff result table. Public
artifact `common-evidence-v3-repaired-results:v1` and the `trader-handoff-v4-results:v0`
artifact live in the same public project. Their raw execution companions remain
private. `studies/common-evidence-v3-repaired/artifact-readback.json` records
manifest verification and exact published result-byte comparisons.

All three notebooks were executed again in native Forge, checkpointed, and read
back at versions **20, 10 and 27**. Anonymous static outputs were downloaded and
matched byte-for-byte. Source ASTs match after normalizing only the generated
Marimo version and leading/trailing Markdown whitespace. The portable 0.25.2
lock also exported all three in a clean environment; the hosted runtime remains
0.25.1. No model calls were made by those notebook executions. The optional paid
button still requires explicit configuration and was not exercised.

The latest ledger records $26.178592 in model charges and $179.99 in conservative
infrastructure holds: $206.168592 known or reserved against $250. The added $4.99
publication hold covers this follow-up's notebook work; invoices remain pending.
Exact sources, static output hashes, package versions, and runtime termination
receipts are in `notebooks/publication.json`.

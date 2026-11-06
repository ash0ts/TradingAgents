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

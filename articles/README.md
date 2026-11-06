# TradingAgents × Agent Lens: articles and evidence

Read in order:

1. [Would you give this investment committee money?](meet-the-investment-committee/article.md) — premise, evidence contract, and the saved Forge workflow.
2. [Confident, expensive, and wrong?](confident-expensive-and-wrong/article.md) — a missing-news case, checker false positives, and native trace/evaluation linking.
3. [Did it beat doing nothing?](did-it-beat-doing-nothing/article.md) — all 13 methods, portfolio mechanics, uncertainty, and the next controlled test.

The three articles are published in the [existing Forge report](https://forge.coreweave.com/wandb/wandb/tradingagents-election-lab/reports/Would-you-give-this-investment-committee-money--VmlldzoxODI2MzIwNQ==), with eight figures, five real product screenshots, chapter navigation and ten preserved native dashboard panels. `article.md` remains canonical. Private source ledgers, working notes, raw capture originals and authenticated trace mappings stay outside this public release. No new paid evaluations were run for the articles.

The [public evidence package](evidence/tradingagents-public-evidence.zip) includes 960 predictions, 2,880 horizon scores, 640 portfolio scenarios, all 60 coverage cases, paired comparisons, six selected assistant reviews, budget qualification and verification receipts. [The evidence guide](evidence/README.md) defines joins, units, missing outcomes and the boundary between public reconciliation and an authenticated rerun. [The manifest](evidence/manifest.json) identifies the immutable payload and execution revision. These tables do not redistribute licensed raw inputs.

Regenerate the figures with the project's Python environment (publication package versions are pinned in `requirements.txt`):

```sh
MPLCONFIGDIR=/tmp/tradingagents-article-mpl .venv/bin/python articles/build_assets.py
MPLCONFIGDIR=/tmp/tradingagents-article-mpl .venv/bin/python articles/build_evidence.py
.venv/bin/python scripts/reconcile_campaign.py
```

The last command requires the frozen private evidence and local prediction artifacts. Figure CSVs preserve unrounded values; prose rounds only for display. SVG source is included beside each PNG. Screenshot crops and original capture hashes are recorded in `screenshot-provenance.json`. Screenshots are actual UI captures, without synthetic or edited pixels.

`build_preview.py` renders local responsive previews. `publish_report.py` uploads an explicit public allowlist, verifies anonymous downloads, updates the same report, and checks that the native panels survive unchanged. It requires the original private report backup and explicit publication authorization; it does not run models. `report-publication.json` and `anonymous-report-verification.json` record the published revision and readback.

Primary research and product documentation are linked beside the claims in each article. Editorial notes and claim ledgers remain local production material.

# TradingAgents × Agent Lens

Read [Would you give this investment committee money?](agent-lens-in-practice/article.md): one cohesive investigation of recommendations, evidence, behavior, financial outcomes, and realistic trading constraints.

The [existing Forge report](https://forge.coreweave.com/wandb/wandb/tradingagents-election-lab/reports/Would-you-give-this-investment-committee-money--VmlldzoxODI2MzIwNQ==) is the publication destination. The original three article drafts remain as archival source material. The three native Forge Notebooks remain separate executable workspaces.

`build_assets.py` and `build_evidence.py` rebuild figures and public exports from saved trading results. `build_preview.py` renders the active article. `publish_report.py` uploads the explicit public allowlist and updates the same report while preserving the original ten dashboard panels. Publication runs no models. Private source text and raw originals remain excluded.

The trading-only scenario extension is reproducible with
`python articles/build_trading_scenarios.py` using public saved inputs. It covers
seven allocation/execution profiles across every original case and method,
with 1,120 independent accounts. `publish_trading_scenarios.py` publishes five
native dashboard panels and case/evidence/Agent Lens crosswalk tables. The
financial Marimo notebook embeds the same results with an interactive selector.
These are explicitly post-hoc stress tests, not new earnings or crash forecasts.

The [internals audit](internals/README.md) follows five selected recommendations
through the Research Manager, Trader, risk discussion and Portfolio Manager.
It distinguishes conditional advice from the fixed allocation rule used in the
original backtest. `build_internals.py` rebuilds the 360-row audit and figure;
`publish_internals.py` publishes its dashboard and tables. Add `--tags` to apply
the candidate and assistant-review tags and update the three native Lens views.
The publisher never triggers inference. Original predictions and scores remain
unchanged; discovered cases belong to a development regression split.

The [internals dashboard](https://forge.coreweave.com/wandb/wandb/tradingagents-election-lab?nw=dufjini1rvb)
contains three panels and authenticated conversation links. The article report
adds two of those panels alongside the original ten and two scenario panels.
Native Insights was below its displayed 1,000-new-turn threshold when inspected;
the audit does not claim native clustering generated these findings.

The completed [repeated debate study](../studies/debate-ablation-v5/README.md)
adds 720 attempts across four workflows and three executions per case. The article
now includes 31 images and 20 native panels. Its new six-panel dashboard exposes
20 public tables and seven Agent Lens views. All 720 conversations reconcile;
four provider failures remain in the outcomes without retries. The public
reproduction reconciles 384 matured accounts and preserves 96 pending accounts.
The new study is in the article, dashboard and versioned artifacts; the three
notebooks retain their previously verified studies and saved versions.

`studies/debate-ablation-v5/publication-validation.json` records anonymous report,
asset and repository-link readback, desktop/mobile inspection, and the native
mobile label-truncation limitation. Full-size figures and adjacent tables provide
complete labels. Raw source material and Agent Lens drilldowns require access.
The article discloses the cache-write accounting correction, qualification-design
deviation, small number of market blocks and unavailable current GitHub Actions.

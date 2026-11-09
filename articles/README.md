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

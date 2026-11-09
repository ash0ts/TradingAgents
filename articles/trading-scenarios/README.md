# Trading scenario evidence

This is a post-hoc analysis of all original TradingAgents decisions, not a new agent trial or a prespecified test. Market data remains frozen through November 5, 2026.

Run `.venv/bin/python articles/build_trading_scenarios.py` from the repository to reconstruct all results and figures offline from public unit-account factors and `notebooks/data/showcase.json`. The optional `--refresh-factors` requires private licensed price snapshots; it is not needed for public reproduction. Factors contain derived per-dollar account values, not raw quotes or source text.

`protocol.json` defines every profile. `scenario-results.json` retains each equity curve and joins to original predictions by case IDs, treatment, and trial. `stock-contributions.csv` preserves per-stock joins and evidence hashes; native dashboard case tables and the original notebooks provide authenticated Agent Lens links. `summaries.csv` averages trials within decision date. `cohort-breakdown.csv` has two dates per cohort; current outcomes stay pending.

Every original 10-bp account reconciles within 1e-7 dollars. Unit-factor replay scales fractional long-only accounts with unchanged corporate actions and fees. Starting holdings, taxes, market impact, leverage, cash yield and intraday order fills are outside this simulator. A zero-news policy closes no positions because all scenarios start in cash; it is an external gate and does not show agents spontaneously abstaining. The single-analyst/committee prompt confound remains.

Event labels annotate the study after the fact. The November 10, 2022 CPI release and November 7, 2024 Fed statement overlap selected holding windows; price moves are not attributed to elections or those releases. No archived textual evidence was added to model inputs.

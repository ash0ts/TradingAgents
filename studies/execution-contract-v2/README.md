# TradingAgents: corrected execution-contract study

This is a **development rerun of previously inspected retrospective cases**. It
tests the interface problems found in the original campaign: conditional advice
reduced to an unconditional rating, inconsistent historical horizons, and advice
about existing positions in a simulator that starts in cash.

The frozen `protocol.json` records the source, evidence and outcome hashes before
qualification and campaign execution. The original executions, their scores and
all numerical/passive baselines are preserved. This study does not retrain those
baselines or move the November 5, 2026 evidence/outcome freeze.

## What changed

Every role receives the same cutoff, exact entry/exit dates, five-session horizon,
SPY benchmark, and fresh-cash sleeve. The final actor produces a typed order in
its existing model call. An unconditional next-close order must match the rating's
target weight. Explicit abstentions, unsupported conditions and invalid contracts
leave cash; failures remain separately labeled. A rejected contract cannot receive
a directional grade. The simulator revalidates the order against its own dates
and account before opening a position.

This is a bundled prompt/schema/execution change. It does not isolate the causal
effect of any one component. Structured agreement is not proof that the explanation
is true or that the investment decision is good.

## Design and units

Qualification cost selected six stocks and two trials: 60 stock/date cases × three
treatments × two trials = 360 new campaign executions. Three qualification runs
are separate. All five cohorts and every treatment are retained. Calls have no
automatic SDK retries; predictions persist before grading and upload.

Each decision-date scenario starts with $100,000 across six equal sleeves. Entry
is the following session's close, exit five sessions later, with 10 basis points
per side and 0/5/25-basis-point sensitivities. Accounts overlap and are independent;
their returns must not be compounded. There are eight matured dates in four
historical cohorts. The two 2026 dates remain pending. Trials are repeated model
executions, not new market observations.

`accepted` means a typed, matching unconditional order. `abstained` means the actor
explicitly chose cash. `blocked_condition` and `invalid_contract` are execution
rejections. `actor_failed` is a runtime failure. An accepted Hold invests 50% but
abstains from directional scoring. An accepted Sell allocates zero yet expresses
a negative relative forecast; an explicit cash abstention expresses no graded
direction. Pending horizons remain null.

## Evidence files and joins

- `results.json`: allowlisted execution records, account results, paired decisions,
  summaries, budget and limitations. No raw model reports or licensed quotes.
- `paired-decisions.csv`: join on `(case_id, treatment, trial)` to both versions;
  both Agent Lens links require team access. Trial indices are zero-based here.
- `portfolio-results.csv`: join on `(decision_date, treatment, trial, bps_per_side)`.
  P&L excludes model expense; `economic_pnl` subtracts it. Pending money values are null.
- `summaries.json`: original/corrected denominators, mean account results and paired
  differences. Trials collapse within date before the 2,000-resample, seed-2026
  cohort-block bootstrap. Four matured blocks support only exploratory uncertainty.
- `reviews.json`: 30 prespecified final-output reviews by Codex, **not human or
  domain-expert labels**. These inspect the execution mandate and order/prose
  agreement; they do not certify every factual claim.
- `verification.json`: hosted readback counts, source hashes, prediction identities,
  score/account reconciliation and budget receipt.
- `dashboard.json`: saved native Forge dashboard and public derived-table receipt.
  Conversation links require access to the private companion project.

The original public controls and scenario factors remain in
[`notebooks/data/showcase.json`](../../notebooks/data/showcase.json) and
[`articles/trading-scenarios`](../../articles/trading-scenarios/README.md).
Raw evidence and full new reports stay in the existing private evidence project;
artifact versions are recorded separately. Public artifact files and native tables
are checked independently of the authenticated Agent Lens drilldowns.

## Observed result

All 360 executions succeeded: 215 accepted orders and 145 explicit cash choices.
Hosted readback reconciled 14,829 spans and 4,194 model calls. The 30 selected
assistant reviews found 29 mandate/order-consistent outputs and one fee-description
mismatch: a report said an allocation was before fees, while the typed target
and simulator correctly include entry fees. This is not a general factual audit.
The qualification and campaign added $7.783134 in model charges; total known or
reserved spend is $190.468169 against the original $250 cap.

## Reproduction

The exact actor revision is preserved by the `tradingagents-contract-v2-execution`
tag (commit `4eb79a67a1e64b3945c5d219b7ea92ad49313c8b`).

Use the repository's pinned notebook environment and optional lab dependencies.
The original private evidence snapshot is needed to rerun agents and raw-price
portfolio accounting. Never fetch live replacements during replay.

```sh
# New paid inference: review protocol and budget; use a fresh campaign identity.
# These existing commands resume saved completed rows and refuse uncertain starts.
python scripts/run_corrected_campaign.py qualify
python scripts/run_corrected_campaign.py select
python scripts/run_corrected_campaign.py run --workers 16

# Analysis/publication only; these make no model or judge calls.
python scripts/export_corrected_campaign.py
python scripts/audit_corrected_campaign.py
python articles/build_corrected_figures.py
python scripts/build_forge_notebooks.py
python -m marimo export html notebooks/03_beat_doing_nothing.py -o /tmp/comparisons.html
```

The dispatcher verifies every frozen source and evidence hash before each job.
The $30 additional cap shares the original $250 ledger, including its outstanding
infrastructure reservations. Do not delete that ledger to obtain a new allowance.
Qualification is excluded from financial comparisons but included in new spend.

## Limits that remain

Archived news/social evidence remains unavailable. Frozen inputs cannot remove
pretrained knowledge. The committee's stock-price tool injects the case ticker;
it does not expose SPY prices. The single analyst receives SPY in its direct
bundle. Both versions retain this inherited access difference, so a comparison
between treatments cannot isolate deliberation or agent count. Review the actual
requests and tool outputs before interpreting the committee's missing-benchmark
statements as an agent error.

No conditional-order fills are simulated. These are new executions on familiar
cases, not new market evidence. A forward study with matched information access
must be registered separately before examining its outcomes.

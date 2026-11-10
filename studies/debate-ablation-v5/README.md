# Does either debate earn its place?

This is a prespecified **retrospective development ablation**, following the
five-rating handoff repair. It is not an untouched test, a prospective trading
study, or a replication of the original TradingAgents paper. The protocol was
committed and pushed before qualification. The dispatch amendment was recorded
after qualification and before any main execution.

## Question and interventions

Every role uses `gpt-6-luna`. All four treatments receive the same frozen numerical
brief and fresh-cash execution mandate. The committee variants keep the same four
analysts, Research Manager, Trader and Portfolio Manager. No new evidence, labels,
model parameters or trading rules are introduced between treatments.

| Treatment | Research debate | Risk debate | Decision procedure |
|---|---|---|---|
| Full all-Luna committee | Bull and bear | Aggressive, conservative and neutral | Complete repaired workflow |
| No research debate | Omitted | Retained | Original analyst reports go directly to Research Manager |
| No risk debate | Retained | Omitted | Research and trader plans go directly to Portfolio Manager |
| Single Luna | None | None | One structured prediction from the common brief |

The affected managers receive an explicit omission notice. We check the actual
native spans to establish which roles ran. The no-research intervention includes
substituting original analyst reports for debate summaries. Removing a stage
changes both context and computation; these are total pipeline interventions,
not equal-compute tests of collaboration. There is no double-ablation arm, so
the design does not identify a research-by-risk interaction.

## Membership and repeated execution

The original six stocks and five anchor cohorts remain. Each anchor has the
trading date immediately before and after it: 60 stock/date cases, including 12
whose primary outcomes remain pending. The qualification-driven rule selects
three repetitions if affordable, with a fixed balanced fallback. `design.json`
records the selected configuration; `schedule.json` records every planned job.

Qualification uses two fixed previously examined cases in every arm. These eight
executions do not enter the main financial or repeatability analysis. Selection
uses their costs, not returns. Main case/trial blocks and arm order are shuffled
with a fixed seed. Model sampling has no claimed reproducibility seed. Each run
has isolated memory, files and conversation identity. No actor retries are allowed.

Repetitions estimate within-case variability. They do not add market observations.
There are still eight matured dates in four historical cohort blocks. All cases
have been available during previous development. We preserve their status as
development data even though this particular comparison was specified in advance.

## Primary estimand

For each date, treatment and repetition, create a fresh $100,000 account with equal
stock sleeves. Accepted five-rating decisions allocate 0%, 25%, 50%, 75% or 100%
of each sleeve, including entry fees. Explicit abstentions, invalid contracts and
actor failures hold cash, with their statuses reported separately. Entry is the
next session's close, exit is five sessions later, and fees are 10 basis points
per side. Corporate actions and dividends use the frozen outcome snapshot.

For each account, calculate a SPY control with exactly the same sleeve allocations,
dates and fee rules. Define selection P&L as stock-account trading P&L minus that
SPY control's P&L. This controls invested capital and timing, not market beta,
sector risk or volatility. It is a counterfactual accounting control, not another
prediction model. Overlapping account scenarios remain independent scenarios;
their equity curves are never concatenated.

Average repetitions within each decision date. Pair each alternative with the
full committee on the same date, then average the date differences. The three
planned contrasts are no-research minus full, no-risk minus full, and single
minus full. All three are reported, regardless of sign. Positive values favor
the alternative in this sample.

## Uncertainty, robustness and denominators

We publish all eight date differences and their four cohort means. The bootstrap
resamples whole before/after cohort blocks, using 10,000 draws and a fixed seed.
Its percentile intervals are exploratory: four blocks cannot establish calibrated
95% coverage. Leave-one-cohort-out estimates expose dependence on any one anchor.

A two-sided exact sign-flip sensitivity enumerates all 16 signs of four block
differences. It assumes independent, sign-symmetric block effects. It is not a
design-based randomization test: only execution order was randomized. Its minimum
attainable nonzero two-sided p-value is 0.125. Holm adjusts the three planned
values as a family. Neither adjustment nor extra model repetitions overcomes
the small number of market blocks. We make no 5% significance or power claim.

Secondary outputs include allocation agreement across repetitions, allocation
range, executable-contract coverage, explicit abstentions, actor failures, model
calls, latency and expense. Agreement uses every scheduled case, including cash
and failure outcomes; successful-only agreement cannot hide failures. Financial
tables show exposure and economic P&L after model expense. Every fee scenario at
0, 5, 10 and 25 basis points remains available. One- and twenty-session directional
scores are secondary and retain their own matured denominators. Hold, explicit
abstention and rejected decisions receive no directional grade.

The November 5, 2026 data freeze is unchanged. Pending outcomes stay null. A cash
allocation has known zero deployment but does not turn a pending market outcome
into a matured observation. We do not condition the main analysis on acceptance
or on whichever repetition earned most.

## Evidence and measurement boundary

The evidence package includes stock/SPY return summaries, dated SEC facts and
FRED vintages. Archived news, social posts and event calendars are unavailable.
Frozen inputs cannot erase pretrained historical knowledge. These results do not
measure election-news reasoning, real-time adaptation, or execution in a broker.

Native readback checks model identity, intended role presence/absence, the exact
brief in actual requests, evaluation Call IDs, parentage, timing and token usage.
The private OTLP journal is compared by original span IDs. Any export recovery
reuses the actual payload; it never calls the model again or reconstructs a prompt.
Schema acceptance and trace reconciliation do not certify narrative factuality.
Codex's selected inspection is disclosed as assistant review, not independent
financial-domain adjudication.

The original 13-method comparison and earlier campaigns remain separate. Their
different prompts, evidence access and execution contracts prevent attributing
cross-campaign differences to one repaired component. No negative run is replaced.

## Reproduction and budget

Use the execution tag and dependency versions in `protocol.json`. Raw snapshots
and requests require access to the private companion project. Public results
allowlist derived metrics, allocations, source hashes and authenticated trace
links. Public per-dollar account factors allow arithmetic reproduction without
raw quotes, credentials or further model charges:

```sh
python scripts/reproduce_evidence_accounts.py --data studies/debate-ablation-v5
```

The `$250` global cap, original phase limits, infrastructure holds, and `$30`
combined follow-up model subcap stay in the same durable SQLite ledger. Reserve
each call before dispatch; preserve unknown charges at their reserved amount.
Publication uses saved results and launches no notebook compute or model judge.

## Relationship to prior work

[TradingAgents (Xiao et al., v7)](https://arxiv.org/abs/2412.20138v7) motivates the
role architecture. Our restricted evidence, independent short-horizon accounts,
models and development sample differ from its experiments; our findings neither
replicate nor refute its reported performance.
[Anthropic's evaluation guidance](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
informs the separation of transcript, outcome, grader and repeated execution.
[Bailey et al., The Probability of Backtest Overfitting](https://doi.org/10.21314/jcf.2016.322)
motivates preserving the sequential search history and resisting performance-driven
selection. We do not estimate PBO from this small collection of cohorts.

A forward study with richer timestamped evidence, decisions sealed before outcomes,
many independent dates and independent domain review remains necessary for stronger
claims about investment skill. It has not been completed by rerunning these dates.

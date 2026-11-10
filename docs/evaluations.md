# Reproducing evaluations

Install `pip install -e '.[forge,lab,dev]'`. Keep credentials in a local file and
set `TRADINGAGENTS_MODELS_ENV` to its path; do not commit it. Collect evidence
using the command in `election-study.md`, then:

```sh
python -m tradingagents.lab.runner qualify
python -m tradingagents.lab.runner select
python -m tradingagents.lab.campaign --workers 8
python -m tradingagents.lab.baselines --chronos-path /absolute/path/to/pinned/chronos-bolt-small
```

`select` uses qualification costs alone, doubles the estimate, and chooses six
stocks/two trials, six/one, three/two, or three/one, preserving every cohort and
treatment. The independent SQLite ledger reserves conservative per-call costs
before dispatch across all workers. SDK retries are disabled; a structured-output
fallback is a new reserved call. Unknown usage retains the entire reservation.
A restart returns durable completed outputs and refuses an interrupted attempt
until its execution state is investigated. Never erase a reservation to retry.

The standard US API rates are frozen from the official Luna/Sol model pages on
2026-11-06. Counts include reasoning in output usage once. Displayed dollars are
usage-based estimates, not invoice reconciliation. Local baseline API cost is
zero; hardware expense is unmetered and explicitly separate.

Native Agent Lens owns model spans; Weave initializes with
`settings={"implicitly_patch_integrations": False}`. Its older
`autopatch_settings` argument is deprecated and does not disable the current
implicit patcher. `EvaluationLogger.log_prediction` begins before agent execution;
its actual evaluation and prediction Call IDs attach to every native span. Native
span content belongs in the private evidence project. Public evaluation rows
contain ratings, derived metrics, costs, and authenticated conversation links.

The single analyst receives the same frozen records and all OHLCV/action rows
as the committee can retrieve, serialized as CSV to fit context. It makes one
Luna call. Committee defaults retain one debate/risk round and the repository's
20-tool-round limit. All actors have a 4096-token output ceiling and zero SDK
retries as explicit budget controls. Fresh memory and graph state isolate cases.

Numerical methods receive price/action history only. Momentum extrapolates the
20-session relative log return to five sessions; mean reversion negates the last
five. AR(5) fits preceding daily relative log returns and forecasts six steps,
excluding the first for entry delay. Ridge and XGBoost predict delayed five-session
excess returns from 20 daily relative-return lags. DLinear uses two linear maps
on a five-point moving average and its residual, trained locally for 100 epochs.
Its architecture follows [LTSF-Linear](https://arxiv.org/abs/2205.13504), with our
short-horizon regression task explicitly different from the paper's benchmark.
Chronos uses a pinned local [amazon/chronos-bolt-small](https://huggingface.co/amazon/chronos-bolt-small),
512 observations, and forecasts stock and SPY through entry/exit; pretrained
contamination is unknown. This is an adaptation, not a paper replication.

All local supervised training labels mature before the cohort's first decision.
The final 20% of preceding examples is chronological validation, separated by a
six-session purge. Scaling is fitted on training rows only. Fixed hyperparameters
are recorded with validation MAE, training hash, and model weights. Validation
results are reported without selecting new hyperparameters. The same frozen
cohort fit serves both decision dates. Forecast MAE is reported only at its
five-session forecast horizon. Passive cash/SPY/basket comparisons belong in the
portfolio view, not the directional forecasting leaderboard.

## Corrected execution contract

`run_one(..., campaign_id="election-contract-v2", execution_contract=True,
budget_path="lab-runs/election-v1/budget.sqlite", campaign_cap_usd=30)` is a
separate development rerun. Use a new output directory. It preserves the old
campaign and shares its durable ledger, including outstanding infrastructure
reservations. The additional campaign cap applies across qualification and
campaign calls, including uncertain usage.

Every role receives the historical cutoff, exact entry/exit dates, SPY
benchmark, five-session horizon and a fresh cash sleeve with zero holdings.
The final committee actor and single analyst use the same typed decision
schema in their original model call. A next-close order must match that mandate
and the rating's explicit allocation bucket. Missing/mismatched contracts and
unsupported conditional orders are rejected and held in cash. An explicit
abstention remains distinguishable from rejection and provider failure. No
free-text fallback can authorize a trade. A rejected contract receives no
directional score; one- and twenty-session outcomes do not grade a five-session
forecast. The original v1 behavior remains the default.

This fixes the executable interface, not every possible contradiction in prose.
Schema compliance is not a semantic or financial-quality judgment. Historical
cases already inspected are development evidence; any before/after return
comparison is exploratory and does not establish forward performance.

## Common-evidence development arms

The opt-in `shared-evidence` and `cited-evidence` modes give every role the same
hashed brief: stock and SPY closes, trailing 5/20/60-session total returns,
20-session daily volatility, excess historical returns, latest eligible SEC
facts with reporting-period age, and latest frozen FRED observations. These are
observations, not forecasts. Raw histories are intentionally excluded from these
arms, and replay tools cannot recover them. This changes information delivery
relative to the older campaigns; it is not a clean causal estimate of the SPY
access fix alone.

Both arms preserve the five-session execution contract and display a computed
cash/fee receipt, explicitly separate from model prose and actual fills. The cited
arm additionally requires exact fact references, values, units and dates, and
explicit missing-source identifiers. The harness records the brief hash; asking
the actor to copy it caused an ambiguous-instruction failure in a stopped pilot.
Missing-source fields now use an enum, excluding arbitrary hash strings.
Executable decisions must include
stock and SPY price citations. Failed citation checks hold cash and are reported
as rejected contracts, not successful abstentions. The checker validates only the
cited observations; it does not establish that every sentence is true or that the
observations support the forecast. Original modes and saved predictions remain
unchanged.

### Keep the trader's proposed allocation in the same vocabulary

Execution-contract mode uses `ContractTraderProposal`: Buy/Overweight/Hold/
Underweight/Sell mean 100%/75%/50%/25%/0% of a fresh-cash sleeve, including entry
fees. The exact historical mandate and explicit order conditions survive the
handoff to risk review. A next-close weight that disagrees with its action is
rejected; an abstention has zero weight. Structured-output failure does not fall
back to an untyped paid call. The final manager also receives these definitions,
without the generic Hold/trim-existing-holdings scale.

The legacy trader explicitly translated Underweight to Sell and Overweight to
Buy. Those translations are retained in ordinary repository execution but are
incompatible with this evaluation's five allocation buckets. The repair changes
the contract at the trader boundary; it does not infer an executable order from
free text or silently remove a proposed confirmation or stop requirement. Its
selected eight-run development regression is separate from the already-frozen
matched-evidence campaign and makes no new financial-performance claim.

### Accounting and partial failures

The ledger prices regular input, cache reads, cache writes (a 25% input-price
premium), and output separately using decimal arithmetic, then rounds up to a
whole microdollar. Long-context multipliers apply before rounding. Invalid token
category totals fail closed; missing usage keeps the original reservation, and
repeated settlement does not charge twice. The native model spans also retain
cache-write counts, although product cost charts may not recognize every model.

Each attempt owns a fresh callback-event list. If an actor raises, its partial
model/tool events are saved with the failed prediction before scoring or upload.
These fixes apply to future executions. Frozen study tags and original outputs
remain unchanged; retrospective accounting corrections are separate artifacts.

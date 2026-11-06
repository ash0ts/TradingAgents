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

# Portfolio replay rules

`python -m tradingagents.lab.portfolio` builds separate $100,000 scenarios for each
decision date, treatment, and trial. Every scenario must contain all selected stock
sleeves before it is reported. Scenarios overlap and are never concatenated into a
fictional compounded equity curve. TradingAgents' original decision backtest is
unchanged.

The mapping is Buy 100%, Overweight 75%, Hold 50%, Underweight 25%, Sell 0%.
Numeric forecasts use the same ratings with boundaries −1%, −0.25%, +0.25%, +1%
(equal-to-boundary goes into the higher bucket). Cash earns zero. Fractional shares
avoid arbitrary round-lot effects. Target allocation includes the entry fee, so a
100% sleeve pays for shares and transaction costs without borrowing. Uninvested
cash stays in its sleeve; failed or unrated decisions hold cash and are counted.

Entry is the next XNYS session close. Exit is five close-to-close intervals later,
with corporate actions during the holding period applied before that day's close.
Splits change shares; cash dividends are credited on the ex-date and are not
reinvested. This ex-date cash convention differs from actual broker payment dates.
The simulator consumes raw then-current units, never adjusted close plus dividends.

Every output includes orders, share balances, cash, dividends, price P&L, fees,
exposure, turnover, and within-scenario drawdown. Both entry and exit cost 10 bps;
0/5/25 bps are sensitivity views. API expense is shown separately from trading
returns and deducted only for economic P&L. Missing or unmatured exits remain
missing/pending, never zero. Fixtures reconcile all cash movements, split shares,
dividends, entry delay, and transaction costs.

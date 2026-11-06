"""Prespecified membership; calendar sessions, never weekday approximations."""
from __future__ import annotations

ANCHORS = {
    "midterms-2026": "2026-11-03", "presidential-2024": "2024-11-05",
    "midterms-2022": "2022-11-08", "control-2023": "2023-09-12",
    "control-2025": "2025-09-09",
}
STOCKS = ["AAPL", "MSFT", "NVDA", "JPM", "XOM", "UNH"]
FREEZE = "2026-11-05"


def calendar_sessions(start="2018-01-01", end="2027-02-01"):
    import exchange_calendars as xcals
    return [d.strftime("%Y-%m-%d") for d in xcals.get_calendar("XNYS", start=start, end=end).sessions]


def cases(stocks=None):
    sessions = calendar_sessions()
    result = []
    for cohort, anchor in ANCHORS.items():
        index = sessions.index(anchor)
        for side, date in (("before", sessions[index - 1]), ("after", sessions[index + 1])):
            for ticker in stocks or STOCKS:
                result.append({"case_id": f"{cohort}-{side}-{ticker}", "cohort": cohort,
                               "anchor": anchor, "side": side, "ticker": ticker,
                               "decision_date": date, "context_start": sessions[index - 10],
                               "context_end": sessions[index + 10]})
    return result

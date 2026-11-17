"""Rebuild the post-hoc trading scenario study. Public replay is offline.

--refresh-factors reads private frozen prices once. The default reads derived
unit-account factors, so every published dollar can be reproduced publicly.
"""

import argparse
import csv
import hashlib
import json
import statistics
import zipfile
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from tradingagents.lab.evidence import canonical
from tradingagents.lab.portfolio import simulate
from tradingagents.lab.protocol import STOCKS, calendar_sessions
from tradingagents.lab.scenarios import AGENTS, PROFILES, replay, summarize

matplotlib.rcParams["text.parse_math"] = False

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "trading-scenarios"
ASSETS = ROOT / "agent-lens-in-practice/assets"
P = json.loads((ROOT.parent / "notebooks/data/showcase.json").read_text())
LABELS = {
    "default-committee": "Luna/Sol committee",
    "luna-committee": "All-Luna committee",
    "single-luna": "Single Luna analyst",
    "mean-reversion-5": "Mean reversion (5)",
    "momentum-20": "Momentum (20)",
    "chronos-bolt-small": "Chronos Bolt Small",
    "equal-weight": "Equal stock basket",
}
COLORS = ["#226d86", "#b68730", "#7b547a"]


def write_json(name, data):
    (OUT / name).write_bytes(canonical(data))


def write_csv(name, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with (OUT / name).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(
            {
                k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v
                for k, v in r.items()
            }
            for r in rows
        )


def save(fig, name):
    fig.patch.set_facecolor("#fcfaf6")
    for ax in fig.axes:
        ax.set_facecolor("#fcfaf6")
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(length=0)
    for ext in ["png", "svg"]:
        fig.savefig(
            ASSETS / f"{name}.{ext}",
            dpi=180,
            bbox_inches="tight",
            pad_inches=0.2,
            facecolor=fig.get_facecolor(),
        )
    plt.close(fig)


def build(refresh=False):
    OUT.mkdir(exist_ok=True)
    path = OUT / "unit-account-factors.json"
    if refresh:
        prices = json.loads((ROOT.parent / "lab-data/election-v1/outcomes.json").read_text())[
            "prices"
        ]
        factors = []
        sessions = calendar_sessions()
        for date in sorted({r["decision_date"] for r in P["rows"]}):
            for asset in [*STOCKS, "SPY"]:
                for delay, bps in [(1, 10), (1, 25), (2, 10)]:
                    r = simulate(
                        date,
                        [
                            {
                                "ticker": asset,
                                "treatment": "unit",
                                "rating": "Buy",
                                "status": "success",
                            }
                        ],
                        prices,
                        sessions,
                        initial_cash=1,
                        entry_delay=delay,
                        bps=bps,
                        freeze=P["freeze_through"],
                    )
                    factors.append(
                        {
                            "asset": asset,
                            "universe": STOCKS,
                            "entry_delay": delay,
                            **{
                                k: v for k, v in r.items() if k not in ["positions", "transactions"]
                            },
                        }
                    )
        write_json(path.name, factors)
    factors = json.loads(path.read_text())
    results = replay(P["rows"], P["coverage"], factors)
    summaries = summarize(results)
    originals = {
        (r["decision_date"], r["treatment"], r["trial"]): r
        for r in P["portfolios"]
        if r["bps_per_side"] == 10
    }
    max_error = 0
    for r in results:
        if r["profile"] == "original":
            saved = originals[(r["decision_date"], r["treatment"], r["trial"])]
            assert saved["status"] == r["status"]
            if r["status"] == "matured":
                max_error = max(max_error, abs(saved["trading_pnl"] - r["trading_pnl"]))
                assert abs(saved["trading_pnl"] - r["trading_pnl"]) < 1e-7
    write_json("scenario-results.json", results)
    write_csv(
        "scenario-results.csv",
        [{k: v for k, v in r.items() if k != "equity_curve"} for r in results],
    )
    write_json("summaries.json", summaries)
    write_csv("summaries.csv", summaries)
    cohort_rows = []
    grouped = defaultdict(list)
    for r in results:
        if r["profile"] == "original":
            grouped[(r["cohort"], r["treatment"])].append(r)
    for (cohort, method), group in sorted(grouped.items()):
        matured = [r for r in group if r["status"] == "matured"]
        cohort_rows.append(
            {
                "cohort": cohort,
                "treatment": method,
                "matured_dates": len({r["decision_date"] for r in matured}),
                "executions": len(group),
                "mean_trading_pnl": statistics.mean(r["trading_pnl"] for r in matured)
                if matured
                else None,
                "status": "matured" if matured else "pending",
            }
        )
    write_csv("cohort-breakdown.csv", cohort_rows)
    # Stock contributions are fixed $16,666.67 sleeves, never sector-index returns.
    unit_index = {
        (r["decision_date"], r["asset"]): r
        for r in factors
        if r["entry_delay"] == 1 and r["bps_per_side"] == 10
    }
    from tradingagents.lab.portfolio import WEIGHTS

    stock_rows = []
    for r in P["rows"]:
        if r["treatment"] not in AGENTS:
            continue
        u = unit_index[(r["decision_date"], r["ticker"])]
        w = WEIGHTS.get(r["rating"], 0) if r["status"] == "success" else 0
        stock_rows.append(
            {
                k: r[k]
                for k in [
                    "case_id",
                    "cohort",
                    "ticker",
                    "decision_date",
                    "treatment",
                    "trial",
                    "rating",
                    "evidence_sha256",
                ]
            }
            | {
                "status": u["status"],
                "sleeve_capital": 100000 / 6,
                "target_weight": w,
                "trading_pnl": u["trading_pnl"] * w * 100000 / 6
                if u["status"] == "matured"
                else None,
            }
        )
    write_csv("stock-contributions.csv", stock_rows)
    lookup = {(r["profile"], r["treatment"]): r for r in summaries}
    methods = ["default-committee", "luna-committee", "single-luna"]
    profiles = [
        "original",
        "matched-SPY",
        "matched-basket",
        "one-session-late",
        "higher-friction",
        "half-exposure-cap",
        "require-archived-news",
    ]
    labels = [
        "Original allocation",
        "SPY, same invested fraction",
        "Stock basket, same invested fraction",
        "Enter one session later",
        "25 bp per side",
        "Cap total exposure at 50%",
        "Require archived news",
    ]
    fig, ax = plt.subplots(figsize=(11, 7.2))
    y = np.arange(len(profiles))
    for i, t in enumerate(methods):
        values = [lookup[(p, t)]["trading_pnl"] for p in profiles]
        ax.scatter(
            values,
            y + (i - 1) * 0.17,
            label=LABELS[t],
            s=48,
            color=COLORS[i],
            marker=["o", "s", "^"][i],
            zorder=3,
        )
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.axvline(0, color="#9aa6a7", lw=1)
    ax.grid(axis="x", color="#e6e3dc")
    ax.set_axisbelow(True)
    ax.set_xlabel("Mean five-session trading P&L ($ per independent $100,000 account)")
    ax.set_title("What changes when the trading rules change?", loc="left", fontsize=17, pad=25)
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    fig.text(
        0.02,
        0.015,
        "Eight matured decision dates; trials averaged within date. Post-hoc, fixed predictions.\nExposure matching is not beta or volatility matching. Model expense excluded; all outcomes remain retrospective.",
        fontsize=10,
        color="#46535d",
    )
    fig.subplots_adjust(left=0.36, bottom=0.16, top=0.9)
    save(fig, "trading-scenario-sensitivity")
    cohorts = [
        "midterms-2022",
        "control-2023",
        "presidential-2024",
        "control-2025",
        "midterms-2026",
    ]
    cohort_labels = [
        "2022 election\nCPI overlap",
        "2023 calendar\ncontrol",
        "2024 election\nFed overlap",
        "2025 calendar\ncontrol",
        "2026 election\npending",
    ]
    shown = [*methods, "SPY", "equal-weight", "mean-reversion-5", "ridge"]
    table = {(r["cohort"], r["treatment"]): r["mean_trading_pnl"] for r in cohort_rows}
    mat = np.array(
        [[table[(c, t)] if table[(c, t)] is not None else np.nan for c in cohorts] for t in shown]
    )
    bound = np.nanmax(abs(mat))
    fig, ax = plt.subplots(figsize=(12, 6.7))
    cmap = plt.get_cmap("RdBu").copy()
    cmap.set_bad("#e8e7e2")
    im = ax.imshow(mat, cmap=cmap, vmin=-bound, vmax=bound, aspect="auto")
    for i in range(len(shown)):
        for j in range(len(cohorts)):
            v = mat[i, j]
            ax.text(
                j,
                i,
                "Pending" if np.isnan(v) else f"${v:,.0f}",
                ha="center",
                va="center",
                fontsize=10,
                color="white" if abs(v) > 0.62 * bound else "#172633",
            )
    ax.set_xticks(range(len(cohorts)), cohort_labels)
    ax.set_yticks(range(len(shown)), [LABELS.get(t, t) for t in shown])
    ax.tick_params(axis="x", labelsize=10)
    ax.set_title("The calendar window changes the answer", loc="left", fontsize=17, pad=20)
    fig.colorbar(im, ax=ax, shrink=0.7, label="Mean trading P&L ($)")
    fig.text(
        0.02,
        0.02,
        "Two decision dates per cohort; agent means include two trials per date. Selected methods shown; all 13 exported.\n$100,000 independent scenarios, next-close entry, 10 bp per side. Event labels are context, not causal attribution.",
        fontsize=10,
        color="#46535d",
    )
    fig.subplots_adjust(left=0.23, bottom=0.20, right=0.96, top=0.9)
    save(fig, "trading-cohort-results")
    protocol = {
        "version": "trading-scenarios-v1",
        "analysis_class": "post-hoc robustness analysis of frozen predictions",
        "defined_at": "2026-11-09",
        "model_reruns": 0,
        "input_public_data_sha256": P["public_data_sha256"],
        "freeze_through": P["freeze_through"],
        "profiles": PROFILES,
        "selection": "All 60 original cases, all 13 methods; no outcome-based exclusion",
        "cash_interest": 0,
        "initial_capital": 100000,
        "horizon_sessions": 5,
        "same_capital_not_compounded": True,
        "event_context_only": {
            "midterms-2022": "CPI release November 10, 2022 at 08:30 ET overlaps some holding windows",
            "presidential-2024": "FOMC statement November 7, 2024 at 14:00 ET overlaps some holding windows",
        },
        "limits": [
            "No new earnings, crash or forward sample was run.",
            "Original agent prompts and evidence-delivery confounds remain.",
            "News gate is an external policy, not an observed agent abstention; charges already incurred remain.",
            "Exposure controls match invested fraction, not factor risk or volatility.",
            "No existing holdings, tax lots, intraday fills, spreads or market impact estimates.",
            "Second-close stress shifts entry and exit together and does not measure millisecond latency.",
            "Fixed long-only targets are allocation rules, not executable orders from the agents.",
        ],
    }
    write_json("protocol.json", protocol)
    verification = {
        "original_rows_reconciled": len(originals),
        "max_original_pnl_error_usd": max_error,
        "scenario_rows": len(results),
        "matured_rows": sum(r["status"] == "matured" for r in results),
        "pending_rows": sum(r["status"] == "pending" for r in results),
        "summary_rows": len(summaries),
        "unit_factors": len(factors),
        "new_model_calls": 0,
        "network_calls": 0,
    }
    write_json("verification.json", verification)
    (OUT / "README.md").write_text(
        """# Trading scenario evidence\n\nThis is a post-hoc analysis of all original TradingAgents decisions, not a new agent trial or a prespecified test. Market data remains frozen through November 5, 2026.\n\nRun `.venv/bin/python articles/build_trading_scenarios.py` from the repository to reconstruct all results and figures offline from public unit-account factors and `notebooks/data/showcase.json`. The optional `--refresh-factors` requires private licensed price snapshots; it is not needed for public reproduction. Factors contain derived per-dollar account values, not raw quotes or source text.\n\n`protocol.json` defines every profile. `scenario-results.json` retains each equity curve and joins to original predictions by case IDs, treatment, and trial. `stock-contributions.csv` preserves per-stock joins and evidence hashes; native dashboard case tables and the original notebooks provide authenticated Agent Lens links. `summaries.csv` averages trials within decision date. `cohort-breakdown.csv` has two dates per cohort; current outcomes stay pending.\n\nEvery original 10-bp account reconciles within 1e-7 dollars. Unit-factor replay scales fractional long-only accounts with unchanged corporate actions and fees. Starting holdings, taxes, market impact, leverage, cash yield and intraday order fills are outside this simulator. A zero-news policy closes no positions because all scenarios start in cash; it is an external gate and does not show agents spontaneously abstaining. The single-analyst/committee prompt confound remains.\n\nEvent labels annotate the study after the fact. The November 10, 2022 CPI release and November 7, 2024 Fed statement overlap selected holding windows; price moves are not attributed to elections or those releases. No archived textual evidence was added to model inputs.\n"""
    )
    manifest = {
        "version": "trading-scenarios-v1",
        "files": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(OUT.iterdir())
            if p.suffix in {".json", ".csv", ".md"} and p.name != "manifest.json"
        },
        "figures": {
            n: hashlib.sha256((ASSETS / n).read_bytes()).hexdigest()
            for n in ["trading-scenario-sensitivity.png", "trading-cohort-results.png"]
        },
    }
    write_json("manifest.json", manifest)
    with zipfile.ZipFile(
        OUT / "trading-scenarios-evidence.zip", "w", compression=zipfile.ZIP_DEFLATED
    ) as z:
        for p in sorted(OUT.iterdir()):
            if p.suffix != ".zip":
                info = zipfile.ZipInfo(p.name, date_time=(2026, 11, 9, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, p.read_bytes())
    print(json.dumps(verification, indent=2))
    print(json.dumps([r for r in summaries if r["treatment"] == "default-committee"], indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-factors", action="store_true")
    args = parser.parse_args()
    build(args.refresh_factors)

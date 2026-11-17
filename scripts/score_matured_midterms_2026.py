#!/usr/bin/env python3
"""Score the sealed Nov 3, 2026 midterm forward cohort after 5-session close maturity.

All predictions in `articles/evidence/predictions.csv`, `studies/execution-contract-v2/`,
`studies/common-evidence-v3-repaired/`, and `studies/debate-ablation-v5/` were sealed
and SHA-256 hashed on or before Nov 10, 2026—before the Nov 10 (`before` window) and
Nov 12 (`after` window) market closes existed.

This script leaves `lab-data/election-v1/outcomes.json` untouched so historical hashes
stay reproducible, fetches actual market bars through `2026-11-13`, scores the forward
5-session outcomes with the lab's exact rules, writes
`articles/evidence/midterms-2026-matured-20261116.json`, and optionally logs side-by-side
`wandb.EvalTable` runs to `wandb/tradingagents-election-lab`.
"""
from __future__ import annotations

import argparse
import csv
import json
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import yfinance as yf

from tradingagents.lab.evidence import outcome
from tradingagents.lab.portfolio import WEIGHTS, simulate
from tradingagents.lab.protocol import STOCKS, calendar_sessions
from tradingagents.lab.scoring import RATING_DIRECTION

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTCOMES_PATH = REPO_ROOT / "lab-data" / "election-v1" / "outcomes.json"
DEFAULT_OUT = REPO_ROOT / "articles" / "evidence" / "midterms-2026-matured-20261116.json"
MATURED_FREEZE = "2026-11-13"


def fetch_merged_prices(base_prices: dict[str, list[dict[str, Any]]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, dict[str, float]]]]:
    symbols = sorted([*STOCKS, "SPY"])
    merged: dict[str, list[dict[str, Any]]] = {}
    fetched_window: dict[str, dict[str, dict[str, float]]] = {}
    df = yf.download(
        symbols,
        start="2026-10-30",
        end="2026-11-15",
        auto_adjust=False,
        actions=True,
        progress=False,
        group_by="ticker",
    )
    for sym in symbols:
        by_date = {row["date"]: dict(row) for row in base_prices.get(sym, [])}
        sym_df = df[sym].dropna(subset=["Close"])
        fetched_window[sym] = {}
        for idx, r in sym_df.iterrows():
            day = idx.strftime("%Y-%m-%d")
            bar = {
                "date": day,
                "open": float(r["Open"]),
                "high": float(r["High"]),
                "low": float(r["Low"]),
                "close": float(r["Close"]),
                "volume": int(r["Volume"]),
                "dividend": float(r.get("Dividends", 0.0) or 0.0),
                "split": float(r.get("Stock Splits", 0.0) or 1.0) or 1.0,
            }
            by_date[day] = bar
            if "2026-11-02" <= day <= MATURED_FREEZE:
                fetched_window[sym][day] = {
                    "close": round(bar["close"], 4),
                    "dividend": bar["dividend"],
                    "split": bar["split"],
                }
        merged[sym] = [by_date[d] for d in sorted(by_date)]
    return merged, fetched_window


def compute_midterm_case_outcomes(merged_prices: dict[str, list[dict[str, Any]]], sessions: list[str]) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    for label, decision_date in [("before", "2026-11-02"), ("after", "2026-11-04")]:
        spy_5 = outcome(merged_prices["SPY"], decision_date, 5, sessions, MATURED_FREEZE)
        spy_1 = outcome(merged_prices["SPY"], decision_date, 1, sessions, MATURED_FREEZE)
        for ticker in STOCKS:
            cid = f"midterms-2026-{label}-{ticker}"
            stk_5 = outcome(merged_prices[ticker], decision_date, 5, sessions, MATURED_FREEZE)
            stk_1 = outcome(merged_prices[ticker], decision_date, 1, sessions, MATURED_FREEZE)
            excess_5 = stk_5["return"] - spy_5["return"]
            excess_1 = stk_1["return"] - spy_1["return"]
            cases[cid] = {
                "decision_date": decision_date,
                "ticker": ticker,
                "entry_date": stk_5["entry_date"],
                "exit_date_5d": stk_5["exit_date"],
                "stock_return_5d": stk_5["return"],
                "spy_return_5d": spy_5["return"],
                "excess_return_5d": excess_5,
                "stock_return_1d": stk_1["return"],
                "spy_return_1d": spy_1["return"],
                "excess_return_1d": excess_1,
            }
    return cases


def score_decision_row(rating: str | None, contract_status: str, excess_5d: float) -> dict[str, Any]:
    eligible = contract_status == "accepted"
    direction = RATING_DIRECTION.get(rating or "") if eligible else None
    actionable = direction not in (None, 0)
    return {
        "eligible": eligible,
        "actionable": actionable,
        "abstained": not actionable,
        "directional_correct": bool(direction * excess_5d > 0) if actionable else None,
        "signed_excess_return": float(direction * excess_5d) if actionable else None,
    }


def matched_spy_pnl(decision_date: str, preds: list[dict[str, Any]], merged_prices: dict[str, list[dict[str, Any]]], sessions: list[str], bps: int = 10) -> float:
    target_weights = {p["ticker"]: float(p["target_weight"]) for p in preds}
    spy_preds = [{"ticker": p["ticker"], "treatment": "SPY", "rating": "Buy", "status": "success", "cost_upper_usd": 0.0} for p in preds]
    sim_spy = simulate(
        decision_date,
        spy_preds,
        merged_prices,
        sessions,
        bps=bps,
        freeze=MATURED_FREEZE,
        target_weights=target_weights,
    )
    return float(sim_spy["trading_pnl"])


def summarize_treatment_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    act = [r for r in rows if r["actionable"]]
    corr = [1.0 if r["directional_correct"] else 0.0 for r in act]
    sig = [r["signed_excess_return"] for r in act]
    return {
        "decisions": n,
        "actionable": len(act),
        "coverage": round(len(act) / n, 4) if n else None,
        "abstained_or_rejected": n - len(act),
        "directional_accuracy": round(float(np.mean(corr)), 4) if corr else None,
        "mean_signed_excess_return": round(float(np.mean(sig)), 6) if sig else None,
        "mean_target_weight": round(float(np.mean([r["target_weight"] for r in rows])), 4) if rows else None,
        "total_model_cost_usd": round(float(sum(r.get("cost_upper_usd", 0.0) for r in rows)), 4),
    }


def score_campaign_csv(
    csv_path: Path,
    case_outcomes: dict[str, dict[str, Any]],
    merged_prices: dict[str, list[dict[str, Any]]],
    sessions: list[str],
    *,
    contracted: bool,
) -> dict[str, Any]:
    with csv_path.open() as f:
        all_rows = list(csv.DictReader(f))
    mid_rows = [r for r in all_rows if r["case_id"].startswith("midterms-2026-")]
    scored_rows: list[dict[str, Any]] = []
    by_treatment: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_arm_treatment: dict[str, list[dict[str, Any]]] = defaultdict(list)
    scenario_groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)

    for r in mid_rows:
        cid = r["case_id"]
        co = case_outcomes[cid]
        c_status = r.get("contract_status", "accepted") if contracted else ("accepted" if r.get("status") == "success" else "failed")
        rating = r.get("rating") or ""
        t_weight = float(r["target_weight"]) if contracted and r.get("target_weight") not in (None, "") else (
            WEIGHTS.get(rating, 0.0) if r.get("status") == "success" else 0.0
        )
        sc = score_decision_row(rating, c_status, co["excess_return_5d"])
        cost = float(r.get("cost_upper_usd") or 0.0)
        arm = r.get("arm") or "default"
        item = {
            "case_id": cid,
            "decision_date": co["decision_date"],
            "ticker": co["ticker"],
            "arm": arm,
            "treatment": r["treatment"],
            "trial": int(r["trial"]),
            "rating": rating,
            "contract_status": c_status,
            "target_weight": t_weight,
            "cost_upper_usd": cost,
            "excess_return_5d": co["excess_return_5d"],
            "conversation_url": r.get("conversation_url", ""),
            **sc,
        }
        scored_rows.append(item)
        by_treatment[r["treatment"]].append(item)
        by_arm_treatment[f"{arm}:{r['treatment']}"].append(item)
        scenario_groups[(arm, co["decision_date"], r["treatment"], str(r["trial"]))].append(item)

    scenarios: list[dict[str, Any]] = []
    scen_by_treatment: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (arm, decision_date, treatment, trial), grp in sorted(scenario_groups.items()):
        if {g["ticker"] for g in grp} != set(STOCKS) or len(grp) != len(STOCKS):
            continue
        target_weights = {g["ticker"]: g["target_weight"] for g in grp}
        sim_preds = [
            {
                "ticker": g["ticker"],
                "treatment": treatment,
                "rating": "Buy" if g["target_weight"] > 0 else "Sell",
                "status": "success",
                "cost_upper_usd": g["cost_upper_usd"],
                "target_weight": g["target_weight"],
            }
            for g in grp
        ]
        sim = simulate(
            decision_date,
            sim_preds,
            merged_prices,
            sessions,
            bps=10,
            freeze=MATURED_FREEZE,
            target_weights=target_weights,
        )
        m_spy = matched_spy_pnl(decision_date, sim_preds, merged_prices, sessions, bps=10)
        sel_pnl = float(sim["trading_pnl"]) - m_spy
        scen = {
            "arm": arm,
            "decision_date": decision_date,
            "entry_date": sim["entry_date"],
            "exit_date": sim["exit_date"],
            "treatment": treatment,
            "trial": int(trial),
            "exposure_at_entry": round(float(sim["exposure_at_entry"]), 4),
            "trading_pnl_usd": round(float(sim["trading_pnl"]), 2),
            "economic_pnl_usd": round(float(sim["economic_pnl"]), 2),
            "matched_spy_pnl_usd": round(m_spy, 2),
            "selection_pnl_usd": round(sel_pnl, 2),
            "return_pct": round(float(sim["return"]) * 100.0, 4),
            "max_drawdown_pct": round(float(sim["max_drawdown"]) * 100.0, 4),
            "model_expense_usd": round(float(sim["model_expense_upper_usd"]), 4),
        }
        scenarios.append(scen)
        scen_by_treatment[treatment].append(scen)

    portfolio_summary = {}
    for treatment, s_list in sorted(scen_by_treatment.items()):
        portfolio_summary[treatment] = {
            "scenarios": len(s_list),
            "mean_exposure": round(float(np.mean([s["exposure_at_entry"] for s in s_list])), 4),
            "mean_trading_pnl_usd": round(float(np.mean([s["trading_pnl_usd"] for s in s_list])), 2),
            "mean_economic_pnl_usd": round(float(np.mean([s["economic_pnl_usd"] for s in s_list])), 2),
            "mean_matched_spy_pnl_usd": round(float(np.mean([s["matched_spy_pnl_usd"] for s in s_list])), 2),
            "mean_selection_pnl_usd": round(float(np.mean([s["selection_pnl_usd"] for s in s_list])), 2),
        }

    # Full-buy SPY reference on both midterm dates ($100k at 10 bps)
    spy_full = {}
    for label, decision_date in [("before_2026-11-02", "2026-11-02"), ("after_2026-11-04", "2026-11-04")]:
        spy_preds = [{"ticker": t, "treatment": "SPY", "rating": "Buy", "status": "success", "cost_upper_usd": 0.0} for t in STOCKS]
        s_full = simulate(decision_date, spy_preds, merged_prices, sessions, bps=10, freeze=MATURED_FREEZE)
        spy_full[label] = {
            "entry_date": s_full["entry_date"],
            "exit_date": s_full["exit_date"],
            "trading_pnl_usd": round(float(s_full["trading_pnl"]), 2),
            "return_pct": round(float(s_full["return"]) * 100.0, 4),
        }

    return {
        "source_csv": str(csv_path.relative_to(REPO_ROOT)),
        "midterm_decisions_scored": len(scored_rows),
        "by_treatment": {k: summarize_treatment_rows(v) for k, v in sorted(by_treatment.items())},
        "by_arm_and_treatment": {k: summarize_treatment_rows(v) for k, v in sorted(by_arm_treatment.items())},
        "portfolio_10bps_summary": portfolio_summary,
        "spy_100pct_benchmark_10bps": spy_full,
        "scenarios_10bps": scenarios,
        "scored_rows": scored_rows,
    }


def log_debate_ablation_eval_tables(
    project_path: str,
    case_outcomes: dict[str, dict[str, Any]],
) -> dict[str, str]:
    import wandb

    ent, proj = project_path.split("/", 1)
    csv_path = REPO_ROOT / "studies" / "debate-ablation-v5" / "decisions.csv"
    with csv_path.open() as f:
        rows = list(csv.DictReader(f))

    by_treatment: dict[str, list[list[Any]]] = defaultdict(list)
    columns = [
        "case_id",
        "cohort",
        "arm",
        "trial",
        "excess_return_5d",
        "rating",
        "contract_status",
        "target_weight",
        "actionable",
        "directional_correct",
        "signed_excess_return",
        "cost_upper_usd",
        "conversation_url",
    ]
    for r in rows:
        cid = r["case_id"]
        sc_json = json.loads(r["scores"])
        if cid in case_outcomes:
            ex5 = round(float(case_outcomes[cid]["excess_return_5d"]), 6)
            re_sc = score_decision_row(r["rating"], r["contract_status"], case_outcomes[cid]["excess_return_5d"])
            act = re_sc["actionable"]
            d_corr = re_sc["directional_correct"]
            sig_ex = round(re_sc["signed_excess_return"], 6) if re_sc["signed_excess_return"] is not None else None
        else:
            ex5 = round(float(sc_json["excess_return"]), 6) if sc_json.get("excess_return") is not None else None
            act = bool(sc_json.get("actionable"))
            d_corr = sc_json.get("directional_correct")
            sig_ex = round(float(sc_json["signed_excess_return"]), 6) if sc_json.get("signed_excess_return") is not None else None
        by_treatment[r["treatment"]].append(
            [
                cid,
                r["cohort"],
                r["arm"],
                int(r["trial"]),
                ex5,
                r["rating"],
                r["contract_status"],
                float(r["target_weight"]),
                act,
                d_corr,
                sig_ex,
                round(float(r["cost_upper_usd"]), 6),
                r["conversation_url"],
            ]
        )

    urls: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        for treatment, t_rows in sorted(by_treatment.items()):
            with wandb.init(
                entity=ent,
                project=proj,
                name=f"debate-ablation-v5-{treatment}-matured-2026",
                job_type="forward-evaluation",
                dir=tmpdir,
                config={
                    "study": "debate-ablation-v5",
                    "treatment": treatment,
                    "matured_through": MATURED_FREEZE,
                    "cohorts_matured": 6,
                    "decisions": len(t_rows),
                },
            ) as run:
                et = wandb.EvalTable(
                    columns=columns,
                    input_columns=["case_id", "cohort", "arm", "trial", "excess_return_5d"],
                    score_columns=[
                        "actionable",
                        "directional_correct",
                        "signed_excess_return",
                        "target_weight",
                        "cost_upper_usd",
                    ],
                    data=t_rows,
                )
                run.log({"election_lab_6cohort_eval": et})
                urls[treatment] = run.url
    return urls


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--log-eval-table", action="store_true")
    parser.add_argument("--project", default="wandb/tradingagents-election-lab")
    args = parser.parse_args()

    base_outcomes = json.loads(OUTCOMES_PATH.read_text())
    sessions = calendar_sessions()
    merged_prices, fetched_window = fetch_merged_prices(base_outcomes["prices"])
    case_outcomes = compute_midterm_case_outcomes(merged_prices, sessions)

    v1 = score_campaign_csv(
        REPO_ROOT / "articles" / "evidence" / "predictions.csv",
        case_outcomes,
        merged_prices,
        sessions,
        contracted=False,
    )
    v3 = score_campaign_csv(
        REPO_ROOT / "studies" / "common-evidence-v3-repaired" / "decisions.csv",
        case_outcomes,
        merged_prices,
        sessions,
        contracted=True,
    )
    v5 = score_campaign_csv(
        REPO_ROOT / "studies" / "debate-ablation-v5" / "decisions.csv",
        case_outcomes,
        merged_prices,
        sessions,
        contracted=True,
    )

    eval_table_urls: dict[str, str] = {}
    if args.log_eval_table:
        eval_table_urls = log_debate_ablation_eval_tables(args.project, case_outcomes)

    payload = {
        "schema": "tradingagents.midterms-2026-forward-maturity/v1",
        "evaluated_at_utc": datetime.now(UTC).isoformat(),
        "original_outcomes_freeze": base_outcomes["freeze_through"],
        "forward_maturity_freeze": MATURED_FREEZE,
        "zero_leakage_guarantee": (
            "All predictions were sealed, SHA-256 hashed, and exported to Agent Lens on or before "
            "2026-11-10, prior to the 2026-11-10 ('before' window) and 2026-11-12 ('after' window) "
            "market closes. `lab-data/election-v1/outcomes.json` remains unmodified."
        ),
        "market_bars_nov_2026": fetched_window,
        "case_outcomes_5d": {
            k: {
                ck: (round(cv, 6) if isinstance(cv, float) else cv)
                for ck, cv in v.items()
            }
            for k, v in sorted(case_outcomes.items())
        },
        "campaigns": {
            "election_v1_initial": {k: v for k, v in v1.items() if k != "scored_rows"},
            "common_evidence_v3_repaired": {k: v for k, v in v3.items() if k != "scored_rows"},
            "debate_ablation_v5": {k: v for k, v in v5.items() if k != "scored_rows"},
        },
        "eval_table_run_urls": eval_table_urls,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        json.dumps(
            {
                "wrote": str(args.out),
                "case_outcomes_5d": {
                    k: f"stock={v['stock_return_5d']*100:+.2f}% vs SPY={v['spy_return_5d']*100:+.2f}% (excess={v['excess_return_5d']*100:+.2f}%)"
                    for k, v in sorted(case_outcomes.items())
                },
                "election_v1_portfolios": v1["portfolio_10bps_summary"],
                "common_evidence_v3_portfolios": v3["portfolio_10bps_summary"],
                "debate_ablation_v5_by_treatment": v5["by_treatment"],
                "debate_ablation_v5_portfolios": v5["portfolio_10bps_summary"],
                "spy_100pct_benchmark_10bps": v5["spy_100pct_benchmark_10bps"],
                "eval_table_run_urls": eval_table_urls,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

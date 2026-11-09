"""Reconcile every new trial and its matched-exposure SPY control; allowlist exports."""

from __future__ import annotations

import csv
import json
import random
from collections import Counter, defaultdict
from statistics import mean

from run_repaired_evidence_campaign import (
    CAP,
    LEDGER,
    MODES,
    OUT,
    PROTOCOL,
    PUBLIC,
    REPO,
    ROOT,
    SEED,
    sha,
    validate,
)

from tradingagents.lab.brief import assess_citations, build_brief
from tradingagents.lab.budget import Ledger
from tradingagents.lab.evidence import EvidenceStore, canonical
from tradingagents.lab.execution import execution_check, execution_receipt, score_execution
from tradingagents.lab.portfolio import run_portfolios, simulate
from tradingagents.lab.protocol import STOCKS, calendar_sessions, cases
from tradingagents.lab.publication import PORTFOLIO_FIELDS, ROW_FIELDS, public_budget
from tradingagents.lab.scoring import paired_blocks, summary


def csv_file(name, rows):
    with (PUBLIC / (name + ".csv")).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(
            {k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in row.items()}
            for row in rows
        )


def export():
    protocol = validate()
    design = json.loads((OUT / "design.json").read_text())
    manifest = json.loads((ROOT / "manifest.json").read_text())
    outcomes = json.loads((ROOT / "outcomes.json").read_text())
    stocks = STOCKS if design["stocks"] == 6 else ["MSFT", "JPM", "XOM"]
    expected = {
        (m, c["case_id"], t, i)
        for m in MODES
        for c in cases(stocks)
        for t in protocol["treatments"]
        for i in range(design["trials"])
    }
    paths = sorted(OUT.glob("*/campaign/**/prediction.json"))
    rows = [json.loads(p.read_text()) for p in paths]
    key = lambda r: (r["evidence_mode"], r["case_id"], r["treatment"], r["trial"])  # noqa: E731
    assert len(rows) == len(expected) and {key(r) for r in rows} == expected, "Incomplete campaign"
    assert {r["code_revision"] for r in rows} == {design["actor_code_revision"]}
    views = {c: build_brief(EvidenceStore(ROOT).get(k), k) for c, k in manifest["cases"].items()}
    coverage = [
        {
            "case_id": case,
            "source_evidence_sha256": view["source_evidence_sha256"],
            "brief_sha256": view["view_sha256"],
            "fact_id": fact["id"],
            "reporting_period_end": fact["as_of"],
            "filed": fact["filed"],
            "age_days": fact["age_days"],
            "stale_over_180_days": fact["stale_over_180_days"],
        }
        for case, view in views.items()
        for fact in view["facts"]
        if fact["kind"] == "sec"
    ]
    public = []
    for row, path in zip(rows, paths, strict=True):
        view = views[row["case_id"]]
        assert row["evidence_view"] == view
        assert view["view_sha256"] == protocol["brief_sha256"][row["case_id"]]
        assert row["execution_check"] == execution_check(row)
        assert row["execution_receipt"] == execution_receipt(row)
        for h, s in row["scores_by_horizon"].items():
            assert s == score_execution(row, outcomes["cases"][row["case_id"]][h], h)
        check = None
        if row["evidence_mode"] == "cited-evidence" and row["status"] == "success":
            check = assess_citations(row["execution_decision"], view)
            assert row["citation_check"] == check
        clean = {k: row.get(k) for k in ROW_FIELDS}
        clean.update(
            arm=row["evidence_mode"],
            brief_sha256=view["view_sha256"],
            contract_status=row["execution_check"]["status"],
            contract_reasons=row["execution_check"]["reasons"],
            target_weight=row["execution_check"]["target_weight"],
            source_prediction_sha256=sha(path),
            citation_check=check,
            execution_receipt=row["execution_receipt"],
            cited_fact_ids=[
                c["fact_id"] for c in row.get("execution_decision", {}).get("citations", [])
            ],
            stale_facts_available=sum(bool(f.get("stale_over_180_days")) for f in view["facts"]),
            model_calls=len([e for e in row.get("events", []) if e["kind"] == "llm"]),
        )
        public.append(clean)
    accounts, private_accounts = [], []
    sessions = calendar_sessions()
    groups = defaultdict(list)
    for r in rows:
        groups[r["evidence_mode"], r["decision_date"], r["treatment"], r["trial"]].append(r)
    for mode in MODES:
        ps = run_portfolios(ROOT, OUT / mode)
        for p in ps:
            group = groups[mode, p["decision_date"], p["treatment"], p["trial"]]
            control = simulate(
                p["decision_date"],
                [{**r, "treatment": "SPY", "cost_upper_usd": 0} for r in group],
                outcomes["prices"],
                sessions,
                bps=p["bps_per_side"],
                freeze=outcomes["freeze_through"],
            )
            assert p["status"] == control["status"]
            if p["status"] == "matured":
                assert abs(p["exposure_at_entry"] - control["exposure_at_entry"]) < 1e-10
                delta = p["trading_pnl"] - control["trading_pnl"]
                # Constant-weight same-timing control isolates observed selection P&L,
                # not beta, risk, causal skill or the value of the information.
            else:
                delta = None
            clean = {k: p.get(k) for k in PORTFOLIO_FIELDS}
            clean.update(arm=mode, matched_SPY_pnl=control.get("trading_pnl"), selection_pnl=delta)
            accounts.append(clean)
            private_accounts.append({"arm": mode, "actor": p, "matched_SPY": control})
    (OUT / "account-audit.json").write_bytes(canonical(private_accounts))
    summaries = []
    for mode in MODES:
        for treatment in protocol["treatments"]:
            selected = [r for r in public if r["arm"] == mode and r["treatment"] == treatment]
            ps = [
                p
                for p in accounts
                if p["arm"] == mode
                and p["treatment"] == treatment
                and p["bps_per_side"] == 10
                and p["status"] == "matured"
            ]
            checked = [r["citation_check"] for r in selected if r["citation_check"] is not None]
            summaries.append(
                {
                    "arm": mode,
                    "treatment": treatment,
                    **summary(selected),
                    "contract_counts": dict(Counter(r["contract_status"] for r in selected)),
                    "mean_trading_pnl": mean(p["trading_pnl"] for p in ps),
                    "mean_matched_SPY_pnl": mean(p["matched_SPY_pnl"] for p in ps),
                    "mean_selection_pnl": mean(p["selection_pnl"] for p in ps),
                    "mean_exposure": mean(p["exposure_at_entry"] for p in ps),
                    "mean_economic_pnl": mean(p["economic_pnl"] for p in ps),
                    "matured_accounts": len(ps),
                    "independent_dates": len({p["decision_date"] for p in ps}),
                    "total_model_cost_usd": sum(r["cost_upper_usd"] for r in selected),
                    "mean_latency_s": mean(r["latency_s"] for r in selected),
                    "citation_decisions_checked": len(checked),
                    "citation_decisions_valid": sum(c["valid"] for c in checked),
                    "citations_checked": sum(c["checked_citations"] for c in checked),
                    "model_calls": sum(r["model_calls"] for r in selected),
                }
            )
    paired = {}
    for t in protocol["treatments"]:
        paired[t] = {}
        for metric in ("trading_pnl", "selection_pnl", "exposure_at_entry"):
            values = [
                {
                    "case_id": p["decision_date"],
                    "cohort": p["cohort"],
                    "treatment": p["arm"],
                    "scores": {metric: p.get(metric)},
                }
                for p in accounts
                if p["treatment"] == t and p["bps_per_side"] == 10
            ]
            paired[t][metric] = paired_blocks(
                values, "cited-evidence", "shared-evidence", metric=metric
            )
    # Keep all four historical decision versions visible at the individual-trial level.
    original = json.loads((REPO / "notebooks/data/showcase.json").read_text())
    corrected = json.loads((REPO / "studies/execution-contract-v2/results.json").read_text())
    identity = lambda r: (r["case_id"], r["treatment"], r["trial"])  # noqa: E731
    old = {identity(r): r for r in original["rows"] if r.get("conversation_url")}
    v2 = {identity(r): r for r in corrected["rows"]}
    new = {(r["arm"], *identity(r)): r for r in public}
    timeline = []
    for case, t, trial in sorted(old):
        if old[case, t, trial]["ticker"] not in stocks:
            continue
        result = {"case_id": case, "treatment": t, "trial": trial}
        for version, r in [("original", old[case, t, trial]), ("contract", v2[case, t, trial])] + [
            (m, new.get((m, case, t, trial))) for m in MODES
        ]:
            for field in (
                "rating",
                "contract_status",
                "target_weight",
                "cost_upper_usd",
                "conversation_url",
            ):
                result[version + "_" + field] = r.get(field) if r else None
            result[version + "_signed_excess_return"] = (
                r["scores"]["signed_excess_return"] if r else None
            )
            result[version + "_scheduled"] = r is not None
        timeline.append(result)
    ledger = Ledger(LEDGER)
    with ledger.connect() as db:
        costs = dict(
            db.execute(
                "SELECT phase,sum(coalesce(charged,reserve))/1000000.0 FROM calls WHERE run_key LIKE 'election-evidence-v3/repaired/%' GROUP BY phase"
            ).fetchall()
        )
    assert sum(costs.values()) <= CAP
    examples = []
    for mode in MODES:
        for t in protocol["treatments"]:
            ps = sorted(
                [
                    p
                    for p in accounts
                    if p["arm"] == mode
                    and p["treatment"] == t
                    and p["bps_per_side"] == 10
                    and p["status"] == "matured"
                ],
                key=lambda p: (p["trading_pnl"], p["decision_date"], p["trial"]),
            )
            for selection, p in [
                ("weakest", ps[0]),
                ("strongest", ps[-1]),
                ("seeded-random", random.Random(SEED).choice(ps)),
            ]:
                examples.append({"selection": selection, **p})
    report = {
        "campaign_id": protocol["campaign_id"],
        "protocol_sha256": sha(PROTOCOL),
        "design": design,
        "rows": public,
        "portfolios": accounts,
        "summaries": summaries,
        "paired_comparisons": paired,
        "trial_history": timeline,
        "examples": examples,
        "brief_coverage": coverage,
        "new_cost_usd_by_phase": costs,
        "budget": public_budget(ledger),
        "frozen_controls": {
            "original_sha256": sha(REPO / "notebooks/data/showcase.json"),
            "contract_v2_sha256": sha(REPO / "studies/execution-contract-v2/results.json"),
        },
        "limitations": protocol["limitations"],
        "raw_reports_public": False,
    }
    (PUBLIC / "results.json").write_bytes(canonical(report))
    (PUBLIC / "summaries.json").write_bytes(canonical(summaries))
    for name, values in [
        ("decisions", public),
        ("portfolio-results", accounts),
        ("trial-history", timeline),
        ("filing-age", coverage),
    ]:
        csv_file(name, values)
    print(
        json.dumps(
            {
                "executions": len(public),
                "accounts": len(accounts),
                "summaries": summaries,
                "paired": paired,
                "new_cost_usd_by_phase": costs,
            },
            indent=2,
        )
    )
    return report


if __name__ == "__main__":
    export()

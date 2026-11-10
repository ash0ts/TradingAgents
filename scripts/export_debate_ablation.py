"""Reconcile frozen decisions, native traces, journals and prespecified contrasts."""
from __future__ import annotations

import csv
import gzip
import json
import random
import shutil
from collections import Counter, defaultdict
from statistics import mean

import audit_evidence_campaign as native
from recover_journaled_traces import records
from run_debate_ablation import ARMS, LEDGER, OUT, PROTOCOL, PUBLIC, REPO, ROOT, SEED, sha, validate

from tradingagents.lab.budget import Ledger
from tradingagents.lab.evidence import canonical
from tradingagents.lab.execution import execution_check, execution_receipt, score_execution
from tradingagents.lab.portfolio import run_portfolios, simulate
from tradingagents.lab.protocol import calendar_sessions
from tradingagents.lab.publication import PORTFOLIO_FIELDS, ROW_FIELDS, public_budget
from tradingagents.lab.repeated_analysis import paired_contrasts, repeatability
from tradingagents.lab.scoring import summary


def export():
    protocol = validate()
    design = json.loads((OUT / "design.json").read_text())
    jobs = json.loads((OUT / "jobs.json").read_text())
    expected = {(c, a, t) for c, a, t, _, _ in jobs}
    paths = sorted(OUT.glob("*/campaign/**/prediction.json"))
    rows = [json.loads(p.read_text()) for p in paths]
    assert len(rows) == len(expected) and {(r["case_id"], r["treatment"], r["trial"]) for r in rows} == expected
    assert {r["code_revision"] for r in rows} == {design["actor_code_revision"]}
    native.OUT = OUT
    native.main("campaign")
    hosted = json.loads((OUT / "campaign-hosted-audit.json").read_text())
    by_cid = {r["conversation_id"]: r for r in hosted["rows"]}
    journal = records(OUT / "trace-journal/wandb/tradingagents-election-lab-evidence")
    outcomes = json.loads((ROOT / "outcomes.json").read_text())
    public, engineering = [], []
    for row, path in zip(rows, paths, strict=True):
        cid, arm = row["conversation_id"], row["treatment"]
        assert row["evidence_view"]["view_sha256"] == protocol["brief_sha256"][row["case_id"]]
        assert row["execution_check"] == execution_check(row)
        assert row["execution_receipt"] == execution_receipt(row)
        assert row["scores_by_horizon"] == {h: score_execution(row, val, h) for h, val in outcomes["cases"][row["case_id"]].items()}
        spans = json.loads(gzip.decompress((OUT / "native-spans" / (cid + ".json.gz")).read_bytes()))
        assert {s["span_id"] for s in spans} == {s["span_id"] for s in journal[cid]}
        roles = Counter(s["agent_name"] for s in spans if s["operation_name"] == "invoke_agent" and s["parent_span_id"])
        model_names = sorted({s["request_model"] for s in spans if s["operation_name"] == "chat"})
        assert model_names == ["gpt-6-luna"], model_names
        expected_research = arm in ("luna-committee", "luna-no-risk")
        expected_risk = arm in ("luna-committee", "luna-no-research")
        if row["status"] == "success":
            for role in ("Bull Researcher", "Bear Researcher"):
                assert roles[role] == int(expected_research), (row["run_key"], role, roles)
            for role in ("Aggressive Analyst", "Conservative Analyst", "Neutral Analyst"):
                assert roles[role] == int(expected_risk), (row["run_key"], role, roles)
            for role in ("Research Manager", "Trader", "Portfolio Manager"):
                assert roles[role] == int(arm != "single-luna")
        clean = {k: row.get(k) for k in ROW_FIELDS}
        clean.update(arm="shared-evidence", contract_status=row["execution_check"]["status"],
                     contract_reasons=row["execution_check"]["reasons"],
                     target_weight=row["execution_check"]["target_weight"],
                     source_prediction_sha256=sha(path), brief_sha256=row["evidence_view"]["view_sha256"],
                     trace_complete=by_cid[cid]["trace_complete"],
                     native_span_export_sha256=by_cid[cid]["native_span_export_sha256"],
                     model_calls=by_cid[cid]["model_calls"], tool_calls=by_cid[cid]["tool_calls"])
        public.append(clean)
        engineering.append({"case_id": row["case_id"], "treatment": arm, "trial": row["trial"],
                            "status": row["status"], "roles": dict(roles), "models": model_names,
                            "role_presence_checked": row["status"] == "success",
                            "journal_matches_native": True, "span_count": len(spans),
                            "conversation_url": row["conversation_url"]})
    groups = defaultdict(list)
    for row in rows:
        groups[row["decision_date"], row["treatment"], row["trial"]].append(row)
    accounts = []
    for p in run_portfolios(ROOT, OUT / "shared-evidence"):
        group = groups[p["decision_date"], p["treatment"], p["trial"]]
        control = simulate(p["decision_date"], [{**r, "treatment": "SPY", "cost_upper_usd": 0} for r in group], outcomes["prices"], calendar_sessions(), bps=p["bps_per_side"], freeze=outcomes["freeze_through"])
        assert p["status"] == control["status"]
        delta = p["trading_pnl"] - control["trading_pnl"] if p["status"] == "matured" else None
        if p["status"] == "matured":
            assert abs(p["exposure_at_entry"] - control["exposure_at_entry"]) < 1e-10
        accounts.append({**{k: p.get(k) for k in [*PORTFOLIO_FIELDS, "initial_cash", "final_cash", "price_pnl"]},
                         "arm": "shared-evidence", "matched_SPY_pnl": control.get("trading_pnl"), "selection_pnl": delta})
    assert len(accounts) == 10 * len(ARMS) * design["trials"] * 4
    repeated = repeatability(public, design["trials"])
    summaries = []
    for arm in ARMS:
        selected = [r for r in public if r["treatment"] == arm]
        ps = [p for p in accounts if p["treatment"] == arm and p["status"] == "matured" and p["bps_per_side"] == 10]
        stability = [r for r in repeated if r["treatment"] == arm]
        summaries.append({"treatment": arm, **summary(selected),
                          "contract_counts": dict(Counter(r["contract_status"] for r in selected)),
                          **{"mean_" + k: mean(p[k] for p in ps) for k in ("trading_pnl", "selection_pnl", "matched_SPY_pnl", "economic_pnl", "exposure_at_entry")},
                          "matured_accounts": len(ps), "independent_dates": len({p["decision_date"] for p in ps}),
                          "same_weight_cases": sum(r["same_weight_all_trials"] for r in stability), "repeatability_cases": len(stability),
                          "mean_weight_range": mean(r["weight_range"] for r in stability),
                          "total_model_cost_usd": sum(r["cost_upper_usd"] for r in selected),
                          "mean_latency_s": mean(r["latency_s"] for r in selected),
                          "model_calls": sum(r["model_calls"] for r in selected),
                          "complete_conversations": sum(r["trace_complete"] for r in selected)})
    examples = []
    rng = random.Random(SEED)
    for arm in ARMS:
        ps = sorted([p for p in accounts if p["treatment"] == arm and p["status"] == "matured" and p["bps_per_side"] == 10], key=lambda p: (p["decision_date"], p["trial"]))
        for kind, p in (("strongest", max(ps, key=lambda p: p["selection_pnl"])), ("weakest", min(ps, key=lambda p: p["selection_pnl"])), ("seeded-random", rng.choice(ps))):
            examples.append({"selection": kind, **p})
    with Ledger(LEDGER).connect() as db:
        combined = db.execute("SELECT sum(coalesce(charged,reserve))/1000000.0 FROM calls WHERE run_key LIKE 'election-evidence-v3/%'").fetchone()[0]
    assert combined <= 30
    result = {"protocol_sha256": sha(PROTOCOL), "actor_code_revision": design["actor_code_revision"],
              "design": design, "executions": len(rows), "rows": public, "portfolios": accounts,
              "summaries": summaries, "repeatability": repeated, "paired_contrasts": paired_contrasts(accounts),
              "examples": examples, "engineering": engineering,
              "hosted": {k: v for k, v in hosted.items() if k != "rows"},
              "combined_followup_model_cost_upper_usd": combined, "budget": public_budget(Ledger(LEDGER)),
              "limits": protocol["limitations"], "inference": protocol["inference"]}
    (PUBLIC / "results.json").write_bytes(canonical(result))
    shutil.copyfile(REPO / "studies/common-evidence-v3-repaired/unit-account-factors.json", PUBLIC / "unit-account-factors.json")
    for name, values in (("decisions", public), ("accounts", accounts), ("summaries", summaries), ("repeatability", repeated), ("contrasts", result["paired_contrasts"])):
        with (PUBLIC / (name + ".csv")).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(values[0]))
            writer.writeheader()
            writer.writerows({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in row.items()} for row in values)
    print(json.dumps({"executions": len(rows), "summaries": summaries, "contrasts": result["paired_contrasts"], "budget": result["budget"]}, indent=2))


if __name__ == "__main__":
    export()

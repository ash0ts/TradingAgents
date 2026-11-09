"""Publish saved TradingAgents robustness results to a separate Forge workspace."""

import csv
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlsplit

import requests
import wandb
import wandb_workspaces.reports.v2 as wr
import wandb_workspaces.workspaces as ws

ROOT = Path(__file__).resolve().parent
RECEIPT = ROOT / "trading-scenarios-dashboard.json"
ENTITY, PROJECT = "wandb", "tradingagents-election-lab"


def panels():
    definitions = [
        (
            "scenario/original_minus_matched_SPY",
            "Does stock selection beat SPY at the same exposure?",
            "Mean P&L difference (USD; eight dates)",
        ),
        (
            "scenario/one_session_late_pnl",
            "What if entry slips to the second close?",
            "Mean five-session P&L (USD; exit also shifts)",
        ),
        (
            "scenario/higher_friction_pnl",
            "What survives 25 basis points per side?",
            "Mean five-session P&L (USD)",
        ),
        (
            "scenario/half_exposure_cap_pnl",
            "Limit deployed capital to 50%",
            "Mean five-session P&L (USD)",
        ),
        (
            "scenario/original_minus_matched_basket",
            "Does allocation beat an equal basket at the same exposure?",
            "Mean P&L difference (USD; eight dates)",
        ),
    ]
    return [
        wr.BarPlot(
            metrics=[metric],
            title=title,
            title_x=units,
            max_runs_to_show=13,
            max_bars_to_show=13,
            legend_template="${run:displayName}",
            layout=wr.Layout(x=0, y=i * 11, w=24, h=11),
        )
        for i, (metric, title, units) in enumerate(definitions)
    ]


def publish():
    rows = json.loads((ROOT / "trading-scenarios/scenario-results.json").read_text())
    summaries = json.loads((ROOT / "trading-scenarios/summaries.json").read_text())
    original = json.loads((ROOT.parent / "notebooks/data/showcase.json").read_text())
    with (ROOT / "trading-scenarios/cohort-breakdown.csv").open() as f:
        cohorts = list(csv.DictReader(f))
    lookup = {(r["profile"], r["treatment"]): r for r in summaries}
    digest = hashlib.sha256((ROOT / "trading-scenarios/manifest.json").read_bytes()).hexdigest()
    methods = sorted({r["treatment"] for r in rows})
    api = wandb.Api()
    ids = []
    for method in methods:
        run_id = "scenario-" + hashlib.sha256((digest + method).encode()).hexdigest()[:16]
        ids.append(run_id)
        metrics = {
            f"scenario/{profile.replace('-', '_')}_pnl": lookup[(profile, method)]["trading_pnl"]
            for profile in {r["profile"] for r in rows}
        }
        metrics.update(
            {
                f"scenario/original_minus_matched_{name}": lookup[("original", method)][
                    "trading_pnl"
                ]
                - lookup[(f"matched-{name}", method)]["trading_pnl"]
                for name in ["SPY", "basket"]
            }
        )
        metrics.update({"scenario/matured_dates": 8, "scenario/pending_dates": 2})
        try:
            saved = api.run(f"{ENTITY}/{PROJECT}/{run_id}")
        except wandb.errors.CommError as exc:
            if "Could not find run" not in str(exc):
                raise
            saved = None
        if saved is None:
            cases = [r for r in original["rows"] if r["treatment"] == method]
            case_table = wandb.Table(
                columns=[
                    "case",
                    "cohort",
                    "ticker",
                    "trial",
                    "rating",
                    "evidence_sha256",
                    "authenticated_agent_lens",
                ],
                data=[
                    [
                        r["case_id"],
                        r["cohort"],
                        r["ticker"],
                        r["trial"],
                        r["rating"],
                        r["evidence_sha256"],
                        r.get("conversation_url") or "numerical/passive control",
                    ]
                    for r in cases
                ],
            )
            scenarios = [r for r in rows if r["treatment"] == method]
            scenario_table = wandb.Table(
                columns=[
                    "profile",
                    "cohort",
                    "decision_date",
                    "trial",
                    "entry_date",
                    "exit_date",
                    "status",
                    "pnl_usd",
                    "case_ids",
                ],
                data=[
                    [
                        r[k]
                        for k in [
                            "profile",
                            "cohort",
                            "decision_date",
                            "trial",
                            "entry_date",
                            "exit_date",
                            "status",
                            "trading_pnl",
                        ]
                    ]
                    + [", ".join(r["case_ids"])]
                    for r in scenarios
                ],
            )
            cohort_table = wandb.Table(
                columns=["cohort", "dates", "mean_pnl_usd", "status"],
                data=[
                    [
                        r["cohort"],
                        int(r["matured_dates"]),
                        float(r["mean_trading_pnl"]) if r["mean_trading_pnl"] else None,
                        r["status"],
                    ]
                    for r in cohorts
                    if r["treatment"] == method
                ],
            )
            with wandb.init(
                entity=ENTITY,
                project=PROJECT,
                id=run_id,
                name=method,
                group="trading-scenarios-v1",
                job_type="scenario-summary",
                settings=wandb.Settings(
                    console="off", x_disable_meta=True, disable_git=True, disable_code=True
                ),
                config={
                    "analysis": "post-hoc frozen-prediction sensitivity",
                    "treatment": method,
                    "evidence_manifest_sha256": digest,
                    "model_reruns": 0,
                    "freeze_through": "2026-11-05",
                },
            ) as run:
                run.summary.update(metrics)
                run.log(
                    {
                        "case_links": case_table,
                        "scenario_accounts": scenario_table,
                        "cohort_breakdown": cohort_table,
                    }
                )
        saved = api.run(f"{ENTITY}/{PROJECT}/{run_id}")
        anonymous = requests.Session()
        anonymous.trust_env = False
        response = anonymous.get(saved.file("wandb-summary.json").url, timeout=60)
        response.raise_for_status()
        stored = response.json()
        assert all(
            math.isclose(stored.get(k, float("nan")), v, abs_tol=1e-8) for k, v in metrics.items()
        )
        if not all(
            math.isclose(dict(saved.summary).get(k, float("nan")), v, abs_tol=1e-8)
            for k, v in metrics.items()
        ):
            # Preserve tables and metadata when materializing the API summary.
            saved.summary.update(stored)
        assert all(
            math.isclose(dict(saved.summary).get(k, float("nan")), v, abs_tol=1e-8)
            for k, v in metrics.items()
        )
    filters = "name in " + repr(ids)
    old = json.loads(RECEIPT.read_text()) if RECEIPT.exists() else None
    workspace = (
        ws.Workspace.from_url(old["wandb_url"])
        if old
        else ws.Workspace(
            entity=ENTITY, project=PROJECT, name="TradingAgents — realistic execution scenarios"
        )
    )
    workspace.settings.max_runs = len(methods)
    workspace.runset_settings = ws.RunsetSettings(
        filters=filters, pinned_columns=["Name", "config.treatment"]
    )
    workspace.sections = [
        ws.Section(
            name="What this tests",
            panels=[
                wr.MarkdownPanel(
                    markdown="## TradingAgents: execution, exposure, and missing evidence\nAll 60 original cases, 13 methods, seven profiles. 1,120 independent portfolio accounts: 896 matured, 224 pending. Eight matured decision dates, with agent trials averaged within date. Post-hoc robustness analysis, zero new model calls. Same invested fraction does not mean same beta or volatility. Original prompt/evidence confounds remain. Open a run’s case_links, scenario_accounts, and cohort_breakdown tables to connect dollars to decisions, evidence hashes, and authenticated Agent Lens traces.",
                    layout=wr.Layout(w=24, h=6),
                )
            ],
            is_open=True,
            layout_settings=ws.SectionLayoutSettings(columns=1, rows=1),
        ),
        ws.Section(
            name="Execution and allocation sensitivity",
            panels=panels(),
            is_open=True,
            layout_settings=ws.SectionLayoutSettings(columns=1, rows=5),
        ),
    ]
    workspace.save()
    parsed = urlsplit(workspace.url)
    forge = (
        "https://forge.coreweave.com/wandb"
        + parsed.path
        + ("?" + parsed.query if parsed.query else "")
    )
    report_panels = panels()[:2]
    grid = wr.PanelGrid(
        runsets=[
            wr.Runset(
                entity=ENTITY,
                project=PROJECT,
                filters=filters,
                name="All 13 methods · eight matured dates · fixed original decisions",
                visible_columns=["Name", "summary:scenario/matured_dates"],
            )
        ],
        panels=report_panels,
        hide_run_sets=False,
    )
    (ROOT / "trading-scenarios-panel-grid.json").write_text(
        grid._to_model().model_dump_json(indent=2) + "\n"
    )
    saved = ws.Workspace.from_url(workspace.url)
    assert len(saved.sections[1].panels) == 5
    receipt = {
        "wandb_url": workspace.url,
        "forge_url": forge,
        "run_ids": ids,
        "evidence_manifest_sha256": digest,
        "metrics_verified": True,
        "native_panels": 5,
        "report_panels": 2,
        "model_calls": 0,
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    publish()

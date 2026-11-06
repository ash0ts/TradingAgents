"""Publish native W&B workspaces and a report, accessible within the Forge shell.

No model execution or re-scoring. Only the allowlisted, fingerprinted public
payload is uploaded. Persisted receipt makes subsequent updates idempotent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

import wandb
import wandb_workspaces.reports.v2 as wr
import wandb_workspaces.workspaces as ws
from wandb_workspaces.workspaces import internal as workspace_models

from tradingagents.lab.dashboard import treatment_metrics, validate_payload

ENTITY = "wandb"
PROJECT = "tradingagents-election-lab"
LENS = "https://forge.coreweave.com/agent-lens/wandb/tradingagents-election-lab-evidence"


def forge_url(url):
    # The Reports SDK leaves a title's trailing '?' unescaped in its URL.
    url = url.replace("?--", "--")
    parsed = urlsplit(url)
    if parsed.netloc == "forge.coreweave.com" and parsed.path.startswith("/wandb/" + ENTITY + "/"):
        return url
    return "https://forge.coreweave.com/wandb" + parsed.path + ("?" + parsed.query if parsed.query else "")


def bar(metric, title, x_label):
    return wr.BarPlot(metrics=[metric], title=title, title_x=x_label,
                      max_runs_to_show=20, max_bars_to_show=20,
                      legend_template="${run:displayName}", layout=wr.Layout(w=12, h=8))


def publish(payload, receipt_path):
    data = json.loads(Path(payload).read_text())
    audit = validate_payload(data)
    publication = json.loads(Path("notebooks/publication.json").read_text())
    receipt_path = Path(receipt_path)
    old = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    api = wandb.Api()
    run_ids = []
    settings = wandb.Settings(console="off", disable_code=True, disable_git=True)
    for treatment in sorted(data["summaries"]):
        run_id = "dash-" + hashlib.sha256((data["public_data_sha256"] + treatment).encode()).hexdigest()[:16]
        run_ids.append(run_id)
        metrics = treatment_metrics(data, treatment)
        try:
            saved = api.run(f"{ENTITY}/{PROJECT}/{run_id}")
        except wandb.errors.CommError as exc:
            if "Could not find run" not in str(exc):
                raise
            saved = None
        if saved is not None:
            if any(saved.summary_metrics.get(k) != v for k, v in metrics.items()):
                raise ValueError(f"Existing derived run differs: {treatment}")
            continue
        rows = [r for r in data["rows"] if r["treatment"] == treatment]
        columns = ["case_id", "cohort", "ticker", "decision_date", "trial", "status", "rating",
                   "conversation_url", "evidence_sha256", "code_revision"]
        table_rows = [[r.get(k) for k in columns] + [r["scores"]["outcome_status"],
                      r["scores"].get("signed_excess_return"), ", ".join(r["behavior_tags"])] for r in rows]
        with wandb.init(entity=ENTITY, project=PROJECT, id=run_id, name=treatment,
                        job_type="frozen-campaign-dashboard", group="election-replay-v1",
                        config={"treatment": treatment, "campaign": data["campaign_id"],
                                "public_data_sha256": data["public_data_sha256"],
                                "evidence_version": data["evidence_version"],
                                "freeze_through": data["freeze_through"],
                                "aggregation": "descriptive trial means; paired notebook collapses trials",
                                "execution_location": "local campaign; hosted tracing and notebooks",
                                "agent": bool(rows[0]["conversation_url"])}, settings=settings) as run:
            run.use_artifact(f"{ENTITY}/{PROJECT}/election-lab-public-results:v1")
            run.summary.update(metrics)
            run.log({"case_links": wandb.Table(columns=columns + ["outcome_status", "signed_excess_return", "candidate_tags"],
                                               data=table_rows)})
    filters = "name in " + repr(run_ids)
    outcome_panels = [
        bar("portfolio/mean_pnl_usd", "Mean five-session P&L ($ per $100k)", "Mean five-session P&L ($), $100k, 10 bps/side"),
        bar("outcomes/signed_excess_pct", "Signed excess return (%) - unequal coverage", "Mean signed stock-minus-SPY return (%)"),
        bar("coverage/scored_trials", "How much was actually scored?", "Matured, actionable trials (not independent cases)"),
        bar("coverage/pending_trials", "2026 outcomes remain pending", "Pending trials at the November 5 freeze"),
        bar("portfolio/mean_exposure_pct", "Mean capital invested (%)", "Mean fraction of capital invested (%)"),
        bar("outcomes/forecast_mae_pp", "Forecast MAE (percentage points)", "Five-session excess-return MAE (percentage points)"),
    ]
    operation_panels = [
        bar("cost/mean_model_usd", "Recorded model cost ($ per agent run)", "Recorded model cost per run ($)"),
        bar("execution/mean_latency_s", "Mean decision latency (seconds)", "Mean wall-clock seconds"),
        bar("execution/mean_model_calls", "Mean model calls per run", "Mean model calls per run"),
        bar("behavior/missing-tool-evidence", "Unavailable evidence", "Runs with missing-tool-evidence flag"),
        bar("behavior/missing-data-not-acknowledged", "Acknowledgment candidates", "Flagged runs; labels require review"),
        bar("behavior/unavailable-evidence-as-fact", "Unsupported-source candidates", "Flagged runs; not confirmed hallucinations"),
    ]
    for panels in (outcome_panels, operation_panels):
        for index, panel in enumerate(panels):
            panel.layout = wr.Layout(x=12 * (index % 2), y=8 * (index // 2), w=12, h=8)
    notice = (
        "## Would you give this investment committee money?\n"
        "360 agent runs · 600 baseline predictions · 60 stock/date cases · frozen November 5, 2026. "
        "These are descriptive comparisons with unequal coverage. Trials are not independent market observations. "
        "Portfolio scenarios use $100k, five sessions and 10 bps per side; model expense is separate. "
        "Five-session 2026 outcomes are pending; archived news/social are unavailable. "
        "Committee and single-analyst prompt objectives differ, so this does not isolate the effect of debate.\n\n"
        f"[Investigate in Agent Lens]({LENS}) · "
        f"[Paired comparisons, costs and portfolio sensitivities]({publication['notebooks'][2]['url']})"
    )
    dashboards = {}
    for key, title, panels in [
        ("outcomes", "Election lab - financial outcomes and coverage", outcome_panels),
        ("behavior", "Election lab - agent behavior and cost", operation_panels),
    ]:
        workspace = ws.Workspace.from_url(old[key]["wandb_url"]) if key in old else ws.Workspace(entity=ENTITY, project=PROJECT, name=title)
        workspace.runset_settings = ws.RunsetSettings(filters=filters, pinned_columns=["Name", "config.treatment"])
        workspace.sections = [ws.Section(name="Read this first", is_open=True,
                                        panels=[wr.MarkdownPanel(markdown=notice, layout=wr.Layout(w=24, h=5))],
                                        layout_settings=ws.SectionLayoutSettings(columns=1, rows=1)),
                              ws.Section(name=title, panels=panels, is_open=True,
                                         layout_settings=ws.SectionLayoutSettings(columns=2, rows=3))]
        workspace.save()
        # The SDK exposes native box height in its validated view model, while
        # SectionLayoutSettings exposes only pagination. Give 13 labels room.
        model = workspace._to_model()
        model.spec.section.panel_bank_config.sections[0].flow_config.box_height = 230
        model.spec.section.panel_bank_config.sections[1].flow_config.box_height = 460
        workspace_models.upsert_view2(model)
        dashboards[key] = {"wandb_url": workspace.url, "forge_url": forge_url(workspace.url)}
        # Save identities before creating the next remote resource.
        receipt_path.write_text(json.dumps({**old, **dashboards}, indent=2))
    runset = wr.Runset(entity=ENTITY, project=PROJECT, filters=filters,
                       visible_columns=["Name", "summary:coverage/scored_trials", "summary:coverage/pending_trials"],
                       name="All 13 methods; frozen results")
    report = wr.Report.from_url(old["report"]["wandb_url"].replace("?--", "--")) if "report" in old else wr.Report(entity=ENTITY, project=PROJECT)
    report.title = "Would you give this investment committee money?"
    report.description = "TradingAgents × Agent Lens: audited execution, honest outcomes, and reproducible Forge notebooks."
    report.width = "fluid"
    blocks = [wr.P("The committee has not earned a victory lap. All 360 agent runs and 600 baseline predictions completed, "
                   "but the agents did not beat SPY's mean portfolio P&L in this small retrospective sample."),
              wr.P("Start with the financial result, open its saved notebook row, then inspect its Agent Lens conversation, "
                   "tool activity and immutable evidence fingerprint. Agent Lens drilldowns require team access; the derived results are public."),
              wr.P([wr.Link("Financial dashboard", dashboards["outcomes"]["forge_url"]), " · ",
                    wr.Link("Behavior and cost dashboard", dashboards["behavior"]["forge_url"]), " · ",
                    wr.Link("Agent Lens overview", LENS)]),
              wr.H1("Did it beat doing nothing?"),
              wr.P("Each scenario starts with $100,000 and exits five sessions after next-session-close entry. "
                   "10 basis points per side, dividends and corporate actions are included. "
                   "Overlapping scenarios are independent; the equity curves are never concatenated. "
                   "Agent averages cover 16 scenarios across eight matured dates; passive methods cover eight dates. "
                   "Model expense is separate. The 2026 five-session outcomes remain pending."),
              wr.PanelGrid(runsets=[runset], panels=outcome_panels[:4], hide_run_sets=False),
              wr.P("Default committee minus momentum: -0.33 percentage points over 41 matched market cases, "
                   "after averaging trials within case. Exploratory 95% cohort-block interval: [-1.25, +0.74] percentage points. "
                   "Only four matured cohorts. Unequal coverage prevents reading the descriptive chart as a significance ranking."),
              wr.H1("What did the agents actually do?"),
              wr.P("All 360 conversations, 15,058 spans and 4,149 model calls were reconciled to persisted predictions. "
                   "Native spans carry evaluation Call IDs and complete parentage; usage reconciles once per model call. "
                   "No duplicated legacy model instrumentation. Candidate flags are not a hallucination leaderboard: "
                   "six assistant-reviewed findings yielded five false positives and one confirmed missing-news coverage gap."),
              wr.PanelGrid(runsets=[runset], panels=operation_panels, hide_run_sets=False)]
    for name, run_key in data["examples"].items():
        row = next(r for r in data["rows"] if r["run_key"] == run_key)
        blocks.append(wr.P([wr.Link(name.replace("_", " ").title() + ": " + row["case_id"], row["conversation_url"]),
                            f" · {row['treatment']}, trial {row['trial']} · authenticated Agent Lens drilldown"]))
    blocks += [wr.H1("Reopen the experiment")]
    for notebook in publication["notebooks"]:
        blocks.append(wr.P([wr.Link(notebook["name"], notebook["url"]),
                            f" · saved source v{notebook['version']['versionIndex']}, executed static output verified"]))
    blocks += [wr.P("The paid campaign ran locally with hosted Agent Lens tracing and evaluation persistence. "
                    "The three saved notebooks executed in native Forge runtimes; their default views use the saved campaign. "
                    "The paid-run button has not been exercised inside a hosted notebook."),
               wr.P("Recorded model charges: $7.683182. Infrastructure reservation: $175, pending invoice reconciliation, "
                    "not recorded spend. Charges plus reservations: $182.683182 / $250. No behavioral LLM judge was used."),
               wr.P("This is retrospective replay with prices, SEC facts and ALFRED vintages; archived news/social were unavailable. "
                    "Frozen inputs cannot remove pretrained knowledge. Committees retain upstream recommendation prompts while "
                    "the single analyst explicitly targets five-session excess return versus SPY. Text access and prompt objectives differ. "
                    "These results establish neither a causal benefit of debate nor an election effect."),
               wr.P([wr.Link("Implementation and six dependent draft PRs", "https://github.com/ash0ts/TradingAgents/pull/6")]),
               wr.P("Immutable public result SHA-256: " + data["public_data_sha256"])]
    report.blocks = blocks
    report.save()
    dashboards.update(report={"wandb_url": report.url.replace("?--", "--"), "forge_url": forge_url(report.url)},
                      audit=audit, run_ids=run_ids, sdk="wandb-workspaces==0.4.13")
    receipt_path.write_text(json.dumps(dashboards, indent=2))
    # Independent hosted readback, including numbers and saved panel specs.
    for treatment, run_id in zip(sorted(data["summaries"]), run_ids, strict=True):
        saved = api.run(f"{ENTITY}/{PROJECT}/{run_id}")
        assert all(saved.summary_metrics.get(k) == v for k, v in treatment_metrics(data, treatment).items())
    for key in ("outcomes", "behavior"):
        saved = ws.Workspace.from_url(dashboards[key]["wandb_url"])
        assert len(saved.sections[1].panels) == 6
    assert wr.Report.from_url(dashboards["report"]["wandb_url"]).title == report.title
    dashboards["remote_readback_verified"] = True
    receipt_path.write_text(json.dumps(dashboards, indent=2))
    return dashboards


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", default="notebooks/data/showcase.json")
    parser.add_argument("--receipt", default="notebooks/dashboards.json")
    args = parser.parse_args()
    print(json.dumps(publish(args.payload, args.receipt), indent=2))

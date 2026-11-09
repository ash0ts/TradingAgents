"""Publish derived handoff checks and reviewed tags; never trigger inference."""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import requests
import wandb
import wandb_workspaces.reports.v2 as wr
import wandb_workspaces.workspaces as ws

from tradingagents.lab.lens import LensClient, audit_spans

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "internals"
PRIVATE = ROOT / "private-evidence/internals"
ENTITY, PROJECT = "wandb", "tradingagents-election-lab"


def native_tags():
    observations = json.loads((OUT / "observations.json").read_text())
    reviews = json.loads((OUT / "reviews.json").read_text())
    review_index = {(r["case_id"], r["treatment"], r["trial"]): r for r in reviews}
    audit_index = {
        r["conversation_id"]: r
        for r in json.loads((ROOT.parent / "lab-runs/election-v1/hosted-audit.json").read_text())[
            "rows"
        ]
    }

    def tag_one(row):
        key = (row["case_id"], row["treatment"], row["trial"])
        tags = []
        if row["condition_phrase_candidate"]:
            tags.append("internals-condition-phrase-candidate")
        if row["horizon_explicitly_not_provided"]:
            tags.append("internals-horizon-unspecified")
        if key in review_index:
            tags.append(
                review_index[key]["finding"].replace(
                    "reviewed-assistant-", "reviewed-assistant-internals-"
                )
            )
        if not tags:
            return []
        path = (
            ROOT.parent
            / "lab-runs/election-v1/campaign"
            / row["case_id"]
            / row["treatment"]
            / str(row["trial"])
            / "prediction.json"
        )
        saved = json.loads(path.read_text())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["source_prediction_sha256"]
        client = LensClient()
        audit = audit_index[saved["conversation_id"]]
        if key in review_index:
            spans = client.spans(saved["conversation_id"])
            audit = audit_spans(saved, spans)
            (PRIVATE / (row["case_id"] + "-" + str(row["trial"]) + ".json")).write_text(
                json.dumps(spans)
            )
        assert len(audit["trace_ids"]) == 1
        return [client.tag(saved["conversation_id"], audit["trace_ids"][0], tag) for tag in tags]

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(tag_one, observations))
    (PRIVATE / "tag-receipts.json").write_text(json.dumps(results, indent=2))
    client = LensClient()
    existing = {v["name"]: v for v in client.request("GET", "/views")["data"]}
    saved_views = []
    for name, tag in [
        ("Internals · conditional wording candidates", "internals-condition-phrase-candidate"),
        ("Internals · explicit missing horizon", "internals-horizon-unspecified"),
        ("Internals · assistant-reviewed handoffs", "reviewed-assistant-internals-"),
    ]:
        filters = [{"id": "tags", "value": {"operator": "contains", "value": tag}}]
        url = "/agent-lens/wandb/tradingagents-election-lab-evidence/conversations?" + urlencode(
            {"filter": json.dumps(filters, separators=(",", ":"))}
        )
        body = {
            "name": name,
            "description": "Post-hoc checks of original frozen runs. Phrase candidates are not validated failures; reviews are by Codex, not a domain expert.",
            "url": url,
        }
        result = (
            client.request("PATCH", "/views/" + existing[name]["id"], body)
            if name in existing
            else client.request("POST", "/views", body)
        )
        saved_views.append(result["data"])
    (PRIVATE / "views.json").write_text(json.dumps(saved_views, indent=2))
    return saved_views, sum(map(len, results))


def panels():
    return [
        wr.BarPlot(
            metrics=["internals/" + key],
            title=title,
            title_x="Executions out of 120 per treatment",
            max_runs_to_show=3,
            max_bars_to_show=3,
            legend_template="${run:displayName}",
            layout=wr.Layout(x=0, y=i * 8, w=24, h=8),
        )
        for i, (key, title) in enumerate(
            [
                ("condition_phrase_candidates", "Conditional wording: candidates requiring review"),
                ("horizon_explicitly_not_provided", "Final horizon field explicitly not provided"),
                (
                    "rating_changed",
                    "Research-to-final rating changes; single analyst not applicable",
                ),
            ]
        )
    ]


def publish(with_tags):
    views, tagged = (
        native_tags() if with_tags else (json.loads((PRIVATE / "views.json").read_text()), None)
    )
    observations = json.loads((OUT / "observations.json").read_text())
    summaries = json.loads((OUT / "summaries.json").read_text())
    reviews = json.loads((OUT / "reviews.json").read_text())
    showcase = json.loads((ROOT.parent / "notebooks/data/showcase.json").read_text())
    links = {
        (r["case_id"], r["treatment"], r["trial"]): r.get("conversation_url")
        for r in showcase["rows"]
    }
    digest = hashlib.sha256((OUT / "manifest.json").read_bytes()).hexdigest()
    api, run_ids = wandb.Api(), []
    for summary in summaries:
        method = summary["treatment"]
        run_id = "internals-" + hashlib.sha256((digest + method).encode()).hexdigest()[:16]
        run_ids.append(run_id)
        rows = [
            dict(r, authenticated_agent_lens=links[(r["case_id"], method, r["trial"])])
            for r in observations
            if r["treatment"] == method
        ]
        case_columns = [
            "case_id",
            "trial",
            "research_rating",
            "final_rating",
            "rating_changed",
            "condition_phrase_candidate",
            "horizon_explicitly_not_provided",
            "outcome_status",
            "sleeve_pnl_usd",
            "signed_excess_return",
            "evidence_sha256",
            "authenticated_agent_lens",
        ]
        metrics = {"internals/" + k: v for k, v in summary.items() if k != "treatment"}
        if not summary["comparable_research_final_ratings"]:
            metrics.pop("internals/rating_changed")
            metrics.pop("internals/rating_unchanged")
        try:
            run = api.run(f"{ENTITY}/{PROJECT}/{run_id}")
        except wandb.errors.CommError as exc:
            if "Could not find run" not in str(exc):
                raise
            with wandb.init(
                entity=ENTITY,
                project=PROJECT,
                id=run_id,
                name=method,
                group="trading-internals-v1",
                job_type="internals-analysis",
                config={
                    "analysis": "post-hoc saved-output audit",
                    "treatment": method,
                    "manifest_sha256": digest,
                    "model_calls": 0,
                },
                settings=wandb.Settings(
                    console="off", x_disable_meta=True, disable_git=True, disable_code=True
                ),
            ) as logged:
                logged.summary.update(metrics)
                selected_reviews = [r for r in reviews if r["treatment"] == method]
                data = {
                    "internals_cases": wandb.Table(
                        columns=case_columns, data=[[r[k] for k in case_columns] for r in rows]
                    )
                }
                if selected_reviews:
                    data["reviewed_handoffs"] = wandb.Table(
                        columns=[
                            "case",
                            "trial",
                            "finding",
                            "recorded_excerpt",
                            "observed",
                            "limitation",
                            "regression_expectation",
                            "authenticated_agent_lens",
                        ],
                        data=[
                            [
                                r["case_id"],
                                r["trial"],
                                r["finding"],
                                "\n".join(e["locator"] + ": " + e["text"] for e in r["excerpts"]),
                                r["observed"],
                                r["limitation"],
                                r["regression_expectation"],
                                links[(r["case_id"], method, r["trial"])],
                            ]
                            for r in selected_reviews
                        ],
                    )
                logged.log(data)
            run = api.run(f"{ENTITY}/{PROJECT}/{run_id}")
        session = requests.Session()
        session.trust_env = False
        response = session.get(run.file("wandb-summary.json").url, timeout=60)
        response.raise_for_status()
        stored = response.json()
        assert all(stored[k] == v for k, v in metrics.items())
        run.summary.update(stored)
        for field in ["internals_cases", "reviewed_handoffs"]:
            if field not in stored:
                continue
            table_response = session.get(run.file(stored[field]["path"]).url, timeout=60)
            table_response.raise_for_status()
            table = table_response.json()
            assert len(table["data"]) == (120 if field == "internals_cases" else 5)
    receipt_path = ROOT / "internals-dashboard.json"
    old = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    workspace = (
        ws.Workspace.from_url(old["wandb_url"])
        if old
        else ws.Workspace(
            entity=ENTITY, project=PROJECT, name="TradingAgents — inside the committee"
        )
    )
    filters = "name in " + repr(run_ids)
    view_links = "\n".join(f"- [{v['name']}](https://forge.coreweave.com{v['url']})" for v in views)
    case_links = "\n".join(
        f"- [{r['case_id']} · trial {r['trial'] + 1}]({links[(r['case_id'], r['treatment'], r['trial'])]})"
        for r in reviews
    )
    workspace.runset_settings = ws.RunsetSettings(
        filters=filters, pinned_columns=["Name", "config.treatment"]
    )
    workspace.settings.max_runs = 3
    workspace.sections = [
        ws.Section(
            name="Read the actual handoff",
            is_open=True,
            panels=[
                wr.MarkdownPanel(
                    markdown="## From a losing position to the recommendation behind it\n360 saved executions, 60 cases, two trials. No new predictions or score changes. Open each run's internals_cases table; the default-committee run also has five reviewed_handoffs. Reviews are by Codex, not a human expert.\n\n**Authenticated native Agent Lens views:**\n"
                    + view_links
                    + "\n\n**Reviewed cases:**\n"
                    + case_links
                    + "\n\nInsights had no completed clustering run on November 9; the UI requires 1,000 new turns. These are deterministic checks and assistant reviews, not native cluster discoveries.",
                    layout=wr.Layout(w=24, h=13),
                )
            ],
        ),
        ws.Section(
            name="Checks, with their denominators",
            is_open=True,
            panels=panels(),
            layout_settings=ws.SectionLayoutSettings(columns=1, rows=3),
        ),
    ]
    workspace.save()
    saved = ws.Workspace.from_url(workspace.url)
    assert len(saved.sections[1].panels) == 3
    parsed = urlsplit(workspace.url)
    grid = wr.PanelGrid(
        runsets=[
            wr.Runset(
                entity=ENTITY,
                project=PROJECT,
                filters=filters,
                name="Saved original runs · post-hoc text checks",
            )
        ],
        panels=panels()[:2],
    )
    (ROOT / "internals-panel-grid.json").write_text(
        grid._to_model().model_dump_json(indent=2) + "\n"
    )
    receipt = {
        "wandb_url": workspace.url,
        "forge_url": "https://forge.coreweave.com/wandb"
        + parsed.path
        + ("?" + parsed.query if parsed.query else ""),
        "run_ids": run_ids,
        "anonymous_tables_verified": 4,
        "rows": 360,
        "reviews": 5,
        "native_panels": 3,
        "report_panels": 2,
        "tag_writes": tagged if tagged is not None else (old or {}).get("tag_writes", 0),
        "native_saved_views": len(views),
        "new_model_calls": 0,
        "manifest_sha256": digest,
    }
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tags", action="store_true")
    publish(parser.parse_args().tags)

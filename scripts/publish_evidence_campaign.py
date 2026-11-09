"""Publish saved common-evidence comparisons; never launch an actor or judge."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode, urlsplit

import requests
import wandb
import wandb_workspaces.reports.v2 as wr
import wandb_workspaces.workspaces as ws
from run_evidence_campaign import MODES, OUT, PUBLIC, REPO, sha

from tradingagents.lab.lens import LensClient

ENTITY, PROJECT = "wandb", "tradingagents-election-lab"
LABELS = {
    "default-committee": "Luna/Sol committee",
    "luna-committee": "All-Luna committee",
    "single-luna": "Single Luna",
}
ARMS = {"shared-evidence": "Shared brief", "cited-evidence": "Required citations"}


def panels():
    return [
        wr.BarPlot(
            metrics=["evidence/" + field],
            title=title,
            title_x=unit,
            max_runs_to_show=6,
            max_bars_to_show=6,
            legend_template="${run:displayName}",
            layout=wr.Layout(x=0, y=i * 10, w=24, h=10),
        )
        for i, (field, title, unit) in enumerate(
            [
                (
                    "accepted",
                    "Did it issue an executable decision?",
                    "Accepted contracts / 60 requested executions per arm and treatment",
                ),
                (
                    "mean_selection_pnl",
                    "Did stock selection beat the same allocation to SPY?",
                    "Mean USD per $100,000 scenario · 8 matured dates · 10 bps/side",
                ),
                (
                    "mean_trading_pnl",
                    "What did the accounts earn after trading fees?",
                    "Mean USD per independent $100,000 account · 8 matured dates",
                ),
                (
                    "mean_exposure",
                    "How much capital did it put to work?",
                    "Mean invested fraction at entry · 8 matured dates",
                ),
                (
                    "total_model_cost_usd",
                    "What did the decisions cost?",
                    "USD · all campaign executions; qualification and infrastructure separate",
                ),
                (
                    "citation_decisions_valid",
                    "Did required citations resolve exactly?",
                    "Valid final citation records / 60 in cited arm; shared arm has no citation test",
                ),
            ]
        )
    ]


def save_views(result, audit):
    client = LensClient()
    traces = {r["conversation_id"]: r["trace_ids"] for r in audit["rows"]}

    def tag(row):
        cid = row["conversation_url"].rsplit("/", 1)[-1]
        path = OUT / "tag-receipts" / (cid + ".json")
        if path.exists():
            return
        assert len(traces[cid]) == 1
        receipts = [
            LensClient().tag(cid, traces[cid][0], name)
            for name in ["common-evidence-v3", row["arm"], "v3-" + row["contract_status"]]
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipts) + "\n")

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(tag, result["rows"]))
    existing = {v["name"]: v for v in client.request("GET", "/views")["data"]}
    views = []
    for mode in MODES:
        for t, label in LABELS.items():
            name = ARMS[mode] + " · " + label
            filters = [
                {"id": "agent", "value": {"operator": "eq", "value": [t + "/" + mode]}},
                {"id": "tags", "value": {"operator": "contains", "value": "common-evidence-v3"}},
            ]
            body = {
                "name": name,
                "description": "Same frozen numeric brief, with or without exact final citations. Development study.",
                "url": "/agent-lens/wandb/tradingagents-election-lab-evidence/conversations?"
                + urlencode({"filter": json.dumps(filters, separators=(",", ":"))}),
            }
            saved = (
                client.request("PATCH", "/views/" + existing[name]["id"], body)
                if name in existing
                else client.request("POST", "/views", body)
            )
            views.append(saved["data"])
    (OUT / "lens-views.json").write_text(json.dumps(views, indent=2) + "\n")
    return views


def publish():
    result = json.loads((PUBLIC / "results.json").read_text())
    audit = json.loads((OUT / "campaign-hosted-audit.json").read_text())
    assert (
        audit["conversations"] == len(result["rows"])
        and audit["all_model_requests_have_exact_brief"]
    )
    views = save_views(result, audit)
    digest = sha(PUBLIC / "results.json")
    api = wandb.Api()
    anonymous = requests.Session()
    anonymous.trust_env = False
    ids, tables = [], 0
    for row in result["summaries"]:
        mode, t = row["arm"], row["treatment"]
        import hashlib

        run_id = "evidence-v3-" + hashlib.sha256((digest + mode + t).encode()).hexdigest()[:16]
        ids.append(run_id)
        metrics = {
            "evidence/" + k: row[k]
            for k in [
                "requested",
                "failed",
                "pending",
                "mean_trading_pnl",
                "mean_selection_pnl",
                "mean_matched_SPY_pnl",
                "mean_exposure",
                "total_model_cost_usd",
                "mean_latency_s",
                "citation_decisions_checked",
                "citations_checked",
            ]
        }
        metrics["evidence/accepted"] = row["contract_counts"].get("accepted", 0)
        metrics["evidence/abstained"] = row["contract_counts"].get("abstained", 0)
        if mode == "cited-evidence":
            metrics["evidence/citation_decisions_valid"] = row["citation_decisions_valid"]
        decisions = [r for r in result["rows"] if r["arm"] == mode and r["treatment"] == t]
        accounts = [r for r in result["portfolios"] if r["arm"] == mode and r["treatment"] == t]
        history = [r for r in result["trial_history"] if r["treatment"] == t]
        payloads = {
            "decision_evidence": decisions,
            "accounts_and_matched_SPY": accounts,
            "all_trial_versions": history,
        }
        try:
            run = api.run(f"{ENTITY}/{PROJECT}/{run_id}")
        except wandb.errors.CommError as exc:
            if "Could not find run" not in str(exc):
                raise
            with wandb.init(
                entity=ENTITY,
                project=PROJECT,
                id=run_id,
                name=LABELS[t] + " · " + ARMS[mode],
                group="common-evidence-v3",
                job_type="common-evidence-publication",
                config={
                    "arm": mode,
                    "treatment": t,
                    "result_sha256": digest,
                    "protocol_sha256": result["protocol_sha256"],
                    "study": "previously inspected development cases",
                    "model_calls_in_publication": 0,
                },
                settings=wandb.Settings(
                    console="off", x_disable_meta=True, disable_git=True, disable_code=True
                ),
            ) as logged:
                logged.summary.update(metrics)
                logged.log(
                    {
                        k: wandb.Table(columns=list(v[0]), data=[list(r.values()) for r in v])
                        for k, v in payloads.items()
                    }
                )
            run = api.run(f"{ENTITY}/{PROJECT}/{run_id}")
        response = anonymous.get(run.file("wandb-summary.json").url, timeout=60)
        response.raise_for_status()
        saved = response.json()
        assert all(saved[k] == v for k, v in metrics.items())
        for field, values in payloads.items():
            response = anonymous.get(run.file(saved[field]["path"]).url, timeout=60)
            response.raise_for_status()
            assert len(response.json()["data"]) == len(values)
            tables += 1
    filters = "name in " + repr(ids)
    receipt_path = PUBLIC / "dashboard.json"
    prior = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    workspace = (
        ws.Workspace.from_url(prior["wandb_url"])
        if prior
        else ws.Workspace(
            entity=ENTITY, project=PROJECT, name="TradingAgents — same facts, checkable decisions"
        )
    )
    workspace.runset_settings = ws.RunsetSettings(
        filters=filters, pinned_columns=["Name", "config.arm", "config.treatment"]
    )
    workspace.settings.max_runs = 6
    view_links = "\n".join(f"- [{v['name']}](https://forge.coreweave.com{v['url']})" for v in views)
    workspace.sections = [
        ws.Section(
            name="The matched development trial",
            is_open=True,
            panels=[
                wr.MarkdownPanel(
                    markdown="## Same facts, with or without required citations\n360 new executions: 60 stock/date cases × 3 systems × 2 arms, one trial per arm. Eight dates have matured outcomes; 2026 remains pending at the November 5 freeze.\n\nBoth arms receive the same numeric brief, including SPY and dated filing facts. Required citations add an exact-reference check and execution gate. Resolving citations does not certify the narrative.\n\nOpen a run’s **decision_evidence**, **accounts_and_matched_SPY**, or **all_trial_versions** tables. Every agent row links to its authenticated Agent Lens conversation. Original and contract-only trials remain visible; unscheduled new repeats are null, not failed or zero.\n\n### Native Agent Lens views\n"
                    + view_links,
                    layout=wr.Layout(w=24, h=14),
                )
            ],
            layout_settings=ws.SectionLayoutSettings(columns=1, rows=1),
        ),
        ws.Section(
            name="Observed behavior and financial outcomes",
            is_open=True,
            panels=panels(),
            layout_settings=ws.SectionLayoutSettings(columns=1, rows=6),
        ),
    ]
    workspace.save()
    readback = ws.Workspace.from_url(workspace.url)
    assert len(readback.sections[1].panels) == 6
    grid = wr.PanelGrid(
        runsets=[
            wr.Runset(
                entity=ENTITY,
                project=PROJECT,
                filters=filters,
                name="Shared brief versus required citations",
            )
        ],
        panels=panels()[:2],
    )
    (REPO / "articles/evidence-panel-grid.json").write_text(
        grid._to_model().model_dump_json(indent=2) + "\n"
    )
    url = urlsplit(workspace.url)
    receipt = {
        "wandb_url": workspace.url,
        "forge_url": "https://forge.coreweave.com/wandb"
        + url.path
        + ("?" + url.query if url.query else ""),
        "run_ids": ids,
        "native_panels": 6,
        "report_panels": 2,
        "anonymous_tables_verified": tables,
        "result_sha256": digest,
        "protocol_sha256": result["protocol_sha256"],
        "executions": len(result["rows"]),
    }
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    publish()

"""Publish allowlisted rerun data and native panels without launching inference."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import requests
import wandb
import wandb_workspaces.reports.v2 as wr
import wandb_workspaces.workspaces as ws

from tradingagents.lab.lens import LensClient

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "studies/execution-contract-v2"
OUT = ROOT / "lab-runs/election-contract-v2"
ENTITY, PROJECT = "wandb", "tradingagents-election-lab"
LABELS = {"default-committee": "Luna/Sol committee", "luna-committee": "All-Luna committee", "single-luna": "Single Luna"}


def panels():
    return [wr.BarPlot(
        metrics=["rerun/" + field], title=title, title_x=unit,
        max_runs_to_show=6, max_bars_to_show=6, legend_template="${run:displayName}",
        layout=wr.Layout(x=0, y=i * 10, w=24, h=10),
    ) for i, (field, title, unit) in enumerate([
        ("mean_trading_pnl", "Did the new contract change trading profit?", "Mean USD per fresh $100,000 scenario · 8 matured dates"),
        ("mean_exposure", "How much of the account was invested?", "Mean fraction at entry · 8 matured dates"),
        ("scored_predictions", "How many directional calls were graded?", "Matured, actionable predictions / 120 executions per version"),
        ("total_model_cost_usd", "Model expense for every requested execution", "USD · campaign only; qualification and infrastructure separate"),
    ])]


def save_views(rows, audit):
    client = LensClient()
    traces = {r["conversation_id"]: r["trace_ids"] for r in audit["rows"]}

    def tag_one(row):
        conversation = row["conversation_url"].rsplit("/", 1)[-1]
        assert len(traces[conversation]) == 1
        tagged = OUT / "tag-receipts" / (conversation + ".json")
        if tagged.exists():
            return
        local = LensClient()
        receipts = [local.tag(conversation, traces[conversation][0], name) for name in
                    ("corrected-campaign-v2", "contract-v2-" + row["contract_status"])]
        tagged.parent.mkdir(parents=True, exist_ok=True)
        tagged.write_text(json.dumps(receipts) + "\n")

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(tag_one, rows))
    existing = {v["name"]: v for v in client.request("GET", "/views")["data"]}
    views = []
    for treatment, label in LABELS.items():
        name = "Corrected mandate · " + label
        filters = [{"id": "agent", "value": {"operator": "eq", "value": [treatment + "/contract-v2"]}},
                   {"id": "tags", "value": {"operator": "contains", "value": "corrected-campaign-v2"}}]
        body = {"name": name, "description": "New executions on previously inspected frozen cases; development evidence, not a forward test.",
                "url": "/agent-lens/wandb/tradingagents-election-lab-evidence/conversations?" + urlencode({"filter": json.dumps(filters, separators=(",", ":"))})}
        result = client.request("PATCH", "/views/" + existing[name]["id"], body) if name in existing else client.request("POST", "/views", body)
        views.append(result["data"])
    (OUT / "lens-views.json").write_text(json.dumps(views, indent=2) + "\n")
    return views


def publish():
    result = json.loads((PUBLIC / "results.json").read_text())
    audit = json.loads((OUT / "hosted-audit.json").read_text())
    assert audit["conversations"] == len(result["rows"]) == result["design"]["stocks"] * result["design"]["trials"] * 30
    assert audit["all_evaluation_links_verified"] and audit["all_usage_reconciled"] and audit["all_model_requests_have_mandate"]
    digest = hashlib.sha256((PUBLIC / "results.json").read_bytes()).hexdigest()
    views = save_views(result["rows"], audit)
    api, ids = wandb.Api(), []
    anonymous = requests.Session()
    anonymous.trust_env = False
    table_count = 0
    for summary in result["summaries"]:
        treatment = summary["treatment"]
        paired = [r for r in result["paired_rows"] if r["treatment"] == treatment]
        accounts = [r for r in result["portfolios"] if r["treatment"] == treatment]
        for version in ("original", "corrected"):
            metrics = {"rerun/" + k: summary[version][k] for k in ("mean_trading_pnl", "mean_exposure", "total_model_cost_usd", "mean_latency_s", "requested", "pending", "failed")}
            metrics["rerun/scored_predictions"] = summary[version]["directional_correct"]["n"]
            metrics["rerun/directional_accuracy"] = summary[version]["directional_correct"]["mean"]
            if version == "corrected":
                metrics.update({"contract/" + k: v for k, v in summary["contract_counts"].items()})
            run_id = "contract-v2-" + hashlib.sha256((digest + treatment + version).encode()).hexdigest()[:16]
            ids.append(run_id)
            try:
                run = api.run(f"{ENTITY}/{PROJECT}/{run_id}")
            except wandb.errors.CommError as exc:
                if "Could not find run" not in str(exc):
                    raise
                with wandb.init(entity=ENTITY, project=PROJECT, id=run_id,
                                name=LABELS[treatment] + " · " + version,
                                group="execution-contract-v2", job_type="corrected-evaluation-publication",
                                config={"version": version, "treatment": treatment, "result_sha256": digest,
                                        "protocol_sha256": result["protocol_sha256"], "study": "development rerun", "new_model_calls_in_publication": 0},
                                settings=wandb.Settings(console="off", x_disable_meta=True, disable_git=True, disable_code=True)) as logged:
                    logged.summary.update(metrics)
                    if version == "corrected":
                        logged.log({"paired_decisions": wandb.Table(columns=list(paired[0]), data=[list(r.values()) for r in paired]),
                                    "corrected_accounts": wandb.Table(columns=list(accounts[0]), data=[list(r.values()) for r in accounts])})
                run = api.run(f"{ENTITY}/{PROJECT}/{run_id}")
            response = anonymous.get(run.file("wandb-summary.json").url, timeout=60)
            response.raise_for_status()
            saved = response.json()
            assert all(saved[k] == value for k, value in metrics.items())
            run.summary.update(saved)
            for field, expected in (("paired_decisions", len(paired)), ("corrected_accounts", len(accounts))):
                if field in saved:
                    response = anonymous.get(run.file(saved[field]["path"]).url, timeout=60)
                    response.raise_for_status()
                    assert len(response.json()["data"]) == expected
                    table_count += 1
    filters = "name in " + repr(ids)
    receipt_path = PUBLIC / "dashboard.json"
    prior = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    workspace = ws.Workspace.from_url(prior["wandb_url"]) if prior else ws.Workspace(entity=ENTITY, project=PROJECT, name="TradingAgents — corrected execution contract")
    workspace.runset_settings = ws.RunsetSettings(filters=filters, pinned_columns=["Name", "config.version", "config.treatment"])
    workspace.settings.max_runs = 6
    view_links = "\n".join(f"- [{v['name']}](https://forge.coreweave.com{v['url']})" for v in views)
    workspace.sections = [ws.Section(name="Original and corrected executions", is_open=True, panels=[wr.MarkdownPanel(
        markdown="## Same market cases, new instructions and execution gate\n360 new executions; 60 stock/date cases; two trials per treatment. Previously inspected development cases, not an untouched test. Eight dates have matured five-session outcomes; 2026 stays pending at the November 5 freeze. Costs and exposure differ.\n\nOpen each **corrected** run's **paired_decisions** table for old/new ratings, contract status and both authenticated Agent Lens links. **corrected_accounts** includes all four fee assumptions. The original baselines remain in the financial dashboard.\n\n### Native Agent Lens views (team access)\n" + view_links,
        layout=wr.Layout(w=24, h=12))], layout_settings=ws.SectionLayoutSettings(columns=1, rows=1)),
        ws.Section(name="Paired development comparison", is_open=True, panels=panels(), layout_settings=ws.SectionLayoutSettings(columns=1, rows=4))]
    workspace.save()
    readback = ws.Workspace.from_url(workspace.url)
    assert len(readback.sections[1].panels) == 4
    grid = wr.PanelGrid(runsets=[wr.Runset(entity=ENTITY, project=PROJECT, filters=filters, name="Original and corrected · same development cases")], panels=panels()[:2])
    (ROOT / "articles/corrected-panel-grid.json").write_text(grid._to_model().model_dump_json(indent=2) + "\n")
    parsed = urlsplit(workspace.url)
    receipt = {"wandb_url": workspace.url, "forge_url": "https://forge.coreweave.com/wandb" + parsed.path + ("?" + parsed.query if parsed.query else ""),
               "run_ids": ids, "native_panels": 4, "report_panels": 2, "anonymous_tables_verified": table_count,
               "new_executions": len(result["rows"]), "result_sha256": digest, "protocol_sha256": result["protocol_sha256"]}
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    publish()

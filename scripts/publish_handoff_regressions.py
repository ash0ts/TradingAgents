"""Publish the eight engineering checks alongside the matched development study."""
from __future__ import annotations

import json
from urllib.parse import urlencode

import requests
import wandb
import wandb_workspaces.reports.v2 as wr
import wandb_workspaces.workspaces as ws
from run_handoff_regressions import OUT, PUBLIC, REPO, sha

from tradingagents.lab.lens import LensClient


def publish():
    result = json.loads((PUBLIC / "results.json").read_text())
    rows = result["rows"]
    assert len(rows) == result["hosted"]["complete_conversations"] == 8
    assert all(r["action_weight_matched"] and r["legacy_instruction_absent"] for r in rows)
    digest = sha(PUBLIC / "results.json")
    run_id = "handoff-v4-" + digest[:16]
    api = wandb.Api()
    try:
        run = api.run("wandb/tradingagents-election-lab/" + run_id)
    except wandb.errors.CommError as exc:
        if "Could not find run" not in str(exc):
            raise
        with wandb.init(entity="wandb", project="tradingagents-election-lab", id=run_id,
                        name="Eight trader handoff regressions", group="trader-handoff-v4",
                        job_type="engineering-regression-publication",
                        config={"financial_comparison": False, "source_sha256": digest},
                        settings=wandb.Settings(console="off", x_disable_meta=True, disable_git=True, disable_code=True)) as logged:
            logged.summary.update({"handoff/executions": 8, "handoff/valid_proposals": 8,
                                   "handoff/complete_conversations": 8,
                                   "handoff/model_cost_usd": result["cost_upper_usd"]})
            logged.log({"paired_handoff_checks": wandb.Table(columns=list(rows[0]), data=[list(r.values()) for r in rows], allow_mixed_types=True)})
        run = api.run("wandb/tradingagents-election-lab/" + run_id)
    anonymous = requests.Session()
    anonymous.trust_env = False
    response = anonymous.get(run.file("wandb-summary.json").url, timeout=60)
    response.raise_for_status()
    summary = response.json()
    response = anonymous.get(run.file(summary["paired_handoff_checks"]["path"]).url, timeout=60)
    response.raise_for_status()
    assert len(response.json()["data"]) == 8
    client = LensClient()
    audits = json.loads((OUT / "campaign-hosted-audit.json").read_text())["rows"]
    for row in audits:
        client.tag(row["conversation_id"], row["trace_ids"][0], "trader-handoff-v4-engineering-regression")
    tags = client.request("POST", "/conversation-tags/query", {"conversation_ids": [r["conversation_id"] for r in audits]})["data"]
    assert len({t["conversation_id"] for t in tags if t["tag"] == "trader-handoff-v4-engineering-regression"}) == 8
    body = {"name": "Trader handoff · eight engineering regressions",
            "description": "Selected development cases; five-rating proposal checks and exact span journaling. No financial-performance claim.",
            "url": "/agent-lens/wandb/tradingagents-election-lab-evidence/conversations?" + urlencode({"filter": json.dumps([{"id": "tags", "value": {"operator": "contains", "value": "trader-handoff-v4-engineering-regression"}}])})}
    existing = {v["name"]: v for v in client.request("GET", "/views")["data"]}
    view = (client.request("PATCH", "/views/" + existing[body["name"]]["id"], body) if body["name"] in existing else client.request("POST", "/views", body))["data"]
    assert next(v for v in client.request("GET", "/views")["data"] if v["id"] == view["id"])["url"] == body["url"]
    url = "https://forge.coreweave.com/wandb/wandb/tradingagents-election-lab/runs/" + run_id
    dashboard = json.loads((REPO / "studies/common-evidence-v3-repaired/dashboard.json").read_text())
    workspace = ws.Workspace.from_url(dashboard["wandb_url"])
    name = "Follow-up: the trader and manager now share an allocation vocabulary"
    workspace.sections = [s for s in workspace.sections if s.name != name]
    workspace.sections.append(ws.Section(name=name, is_open=True, panels=[wr.MarkdownPanel(markdown=(
        "## Eight selected engineering regressions\n\nThe legacy trader translated Underweight into Sell while the evaluation mapped Sell to zero exposure. We replaced that conflict with a typed five-rating proposal. All eight selected executions returned consistent proposals and preserved every native span in a private OTLP journal.\n\nThese runs test the handoff, not investment performance. They remain separate from the frozen 360-run comparison.\n\n[Open all eight paired handoff checks](" + url + ") · [Inspect the native conversations](https://forge.coreweave.com" + view["url"] + ")"), layout=wr.Layout(w=24, h=8))]))
    workspace.save()
    assert ws.Workspace.from_url(workspace.url).sections[-1].name == name
    receipts = []
    for private in (False, True):
        project = "tradingagents-election-lab" + ("-evidence" if private else "")
        artifact = wandb.Artifact("trader-handoff-v4-" + ("executions" if private else "results"), type="engineering-regression", metadata={"result_sha256": digest, "financial_results_exported": False})
        for filename in ("protocol.json", "selection.json", "results.json", "README.md"):
            artifact.add_file(str(PUBLIC / filename), name=filename)
        if private:
            for directory in ("shared-evidence", "cited-evidence", "native-spans", "hosted-readback", "trace-journal"):
                artifact.add_dir(str(OUT / directory), name=directory)
            for filename in ("launch.json", "campaign-hosted-audit.json", "journal-verification.json"):
                artifact.add_file(str(OUT / filename), name=filename)
        with wandb.init(entity="wandb", project=project, job_type="handoff-regression-archive", settings=wandb.Settings(console="off", x_disable_meta=True, disable_git=True, disable_code=True)) as logged:
            saved = logged.log_artifact(artifact)
            saved.wait(timeout=300)
            receipts.append({"artifact": saved.qualified_name, "digest": saved.digest, "private": private})
    receipt = {"run_url": url, "run_id": run_id, "result_sha256": digest, "anonymous_table_rows_verified": 8,
               "native_tags_verified": 8, "view": view, "workspace_url": dashboard["forge_url"], "artifacts": receipts}
    (PUBLIC / "publication.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    publish()

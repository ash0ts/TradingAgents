"""Publish saved common-evidence comparisons; never launch an actor or judge."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode, urlsplit

import requests
import wandb
import wandb_workspaces.reports.v2 as wr
import wandb_workspaces.workspaces as ws
from run_repaired_evidence_campaign import MODES, OUT, PUBLIC, REPO, sha

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
                ("complete_native_conversations", "Did the native trace preserve every model, tool and subagent?", "Complete conversations / 60; one documented export gap remains"),
            ]
        )
    ]


def save_views(result, audit):
    client = LensClient()
    traces = {r["conversation_id"]: r["trace_ids"] for r in audit["rows"]}
    reviewed = json.loads((PUBLIC / "reviews.json").read_text())["records"]
    review_by_url = {r["conversation_url"]: r for r in reviewed}

    def tag(row):
        cid = row["conversation_url"].rsplit("/", 1)[-1]
        path = OUT / "tag-receipts" / (cid + ".json")
        if path.exists():
            return
        assert len(traces[cid]) == 1
        names = ["common-evidence-v3-repaired", row["arm"], "v3-" + row["contract_status"]]
        if not row["trace_complete"]:
            names.append("observed-native-export-gap")
        if review := review_by_url.get(row["conversation_url"]):
            names.extend(["reviewed-v3-codex-assistant", "reviewed-v3-" + review["finding"]])
        receipts = [LensClient().tag(cid, traces[cid][0], name) for name in names]
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
                {
                    "id": "tags",
                    "value": {"operator": "contains", "value": "common-evidence-v3-repaired"},
                },
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
    name = "Common evidence · assistant-reviewed explanations"
    body = {
        "name": name,
        "description": "36 prespecified final-output reviews by Codex; not domain-expert labels or exhaustive narrative verification.",
        "url": "/agent-lens/wandb/tradingagents-election-lab-evidence/conversations?"
        + urlencode(
            {
                "filter": json.dumps(
                    [
                        {
                            "id": "tags",
                            "value": {
                                "operator": "contains",
                                "value": "reviewed-v3-codex-assistant",
                            },
                        }
                    ],
                    separators=(",", ":"),
                )
            }
        ),
    }
    saved = (
        client.request("PATCH", "/views/" + existing[name]["id"], body)
        if name in existing
        else client.request("POST", "/views", body)
    )
    views.append(saved["data"])
    pilot_row = next(
        r for r in result["stopped_pilot"]["rows"] if r["contract_status"] == "invalid_citations"
    )
    pilot_id = pilot_row["conversation_url"].rsplit("/", 1)[-1]
    pilot_audit = json.loads(
        (REPO / "lab-runs/election-evidence-v3/campaign-hosted-audit.json").read_text()
    )
    pilot_trace = next(
        r["trace_ids"][0] for r in pilot_audit["rows"] if r["conversation_id"] == pilot_id
    )
    tag_name = "reviewed-harness-ambiguous-citation-instruction"
    client.tag(pilot_id, pilot_trace, tag_name)
    name = "Stopped pilot · reviewed harness instruction error"
    filters = [{"id": "tags", "value": {"operator": "contains", "value": tag_name}}]
    body = {
        "name": name,
        "description": "Codex assistant reviewed a harness-induced rejection; not an agent hallucination label.",
        "url": "/agent-lens/wandb/tradingagents-election-lab-evidence/conversations?"
        + urlencode({"filter": json.dumps(filters, separators=(",", ":"))}),
    }
    saved = (
        client.request("PATCH", "/views/" + existing[name]["id"], body)
        if name in existing
        else client.request("POST", "/views", body)
    )
    views.append(saved["data"])
    expected_tags = {pilot_id: {tag_name}}
    for row in result["rows"]:
        cid = row["conversation_url"].rsplit("/", 1)[-1]
        names = {"common-evidence-v3-repaired", row["arm"], "v3-" + row["contract_status"]}
        if not row["trace_complete"]:
            names.add("observed-native-export-gap")
        if review := review_by_url.get(row["conversation_url"]):
            names.update({"reviewed-v3-codex-assistant", "reviewed-v3-" + review["finding"]})
        expected_tags[cid] = {re.sub(r"[^a-z0-9]+", "-", n).strip("-") for n in names}
    ids = list(expected_tags)
    actual_tags = {}
    for start in range(0, len(ids), 100):
        response = client.request(
            "POST", "/conversation-tags/query", {"conversation_ids": ids[start : start + 100]}
        )
        for tag in response["data"]:
            actual_tags.setdefault(tag["conversation_id"], set()).add(tag["tag"])
    assert all(tags <= actual_tags.get(cid, set()) for cid, tags in expected_tags.items())
    saved_views = {v["id"]: v for v in client.request("GET", "/views")["data"]}
    assert all(
        saved_views[v["id"]]["url"] == v["url"] and saved_views[v["id"]]["name"] == v["name"]
        for v in views
    )
    (OUT / "native-view-verification.json").write_text(
        json.dumps(
            {
                "conversations": len(expected_tags),
                "expected_tags_verified": sum(map(len, expected_tags.values())),
                "saved_views_verified": len(views),
                "assistant_reviewed_conversations": len(reviewed),
                "review_label_provenance": "Codex assistant; API tag names explicitly distinguish these from expert or automated-judge labels.",
            },
            indent=2,
        )
        + "\n"
    )
    (OUT / "lens-views.json").write_text(json.dumps(views, indent=2) + "\n")
    return views


def publish():
    result = json.loads((PUBLIC / "results.json").read_text())
    reviews = json.loads((PUBLIC / "reviews.json").read_text())["records"]
    assert len(reviews) == 36
    audit = json.loads((OUT / "campaign-hosted-audit.json").read_text())
    assert (
        audit["conversations"] == len(result["rows"])
        and audit["all_observed_model_requests_have_exact_brief"]
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

        run_id = (
            "evidence-v3-repaired-" + hashlib.sha256((digest + mode + t).encode()).hexdigest()[:16]
        )
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
                "complete_native_conversations",
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
            "reviewed_explanations": [
                r for r in reviews if r["arm"] == mode and r["treatment"] == t
            ],
        }
        try:
            run = api.run(f"{ENTITY}/{PROJECT}/{run_id}")
        except wandb.errors.CommError as exc:
            if "Could not find run" not in str(exc):
                raise
            run = None
        if run is None or not all(field in run.summary for field in payloads):
            with wandb.init(
                resume="allow",
                entity=ENTITY,
                project=PROJECT,
                id=run_id,
                name=LABELS[t] + " · " + ARMS[mode],
                group="common-evidence-v3-repaired",
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
                        k: wandb.Table(columns=list(v[0]), data=[list(r.values()) for r in v], allow_mixed_types=True)
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
    pilot = result["stopped_pilot"]
    pilot_run_id = "evidence-v3-stopped-" + result["stopped_pilot_sha256"][:12]
    try:
        pilot_run = api.run(f"{ENTITY}/{PROJECT}/{pilot_run_id}")
    except wandb.errors.CommError as exc:
        if "Could not find run" not in str(exc):
            raise
        with wandb.init(
            entity=ENTITY,
            project=PROJECT,
            id=pilot_run_id,
            name="Stopped pilot · harness instruction error",
            group="common-evidence-v3-stopped",
            job_type="stopped-pilot-evidence",
            config={
                "status": "stopped partial schedule",
                "excluded_from_financial_comparison": True,
                "source_sha256": result["stopped_pilot_sha256"],
                "model_calls_in_publication": 0,
            },
            settings=wandb.Settings(
                console="off", x_disable_meta=True, disable_git=True, disable_code=True
            ),
        ) as logged:
            logged.summary.update(
                {
                    "pilot/completed": len(pilot["rows"]),
                    "pilot/cost_including_qualification": pilot["campaign_cost_usd"]
                    + pilot["qualification_cost_usd"],
                }
            )
            logged.log(
                {
                    "preserved_pilot_decisions": wandb.Table(
                        allow_mixed_types=True,
                        columns=list(pilot["rows"][0]),
                        data=[list(r.values()) for r in pilot["rows"]],
                    )
                }
            )
        pilot_run = api.run(f"{ENTITY}/{PROJECT}/{pilot_run_id}")
    response = anonymous.get(pilot_run.file("wandb-summary.json").url, timeout=60)
    response.raise_for_status()
    pilot_saved = response.json()
    response = anonymous.get(
        pilot_run.file(pilot_saved["preserved_pilot_decisions"]["path"]).url, timeout=60
    )
    response.raise_for_status()
    assert len(response.json()["data"]) == 40
    tables += 1
    pilot_url = f"https://forge.coreweave.com/wandb/{ENTITY}/{PROJECT}/runs/{pilot_run_id}"
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
                    + view_links
                    + "\n\n[Preserved stopped pilot: 40 executions]("
                    + pilot_url
                    + "). An ambiguous hash-copying instruction caused one reviewed rejection. Its costs count; the partial schedule is excluded from these financial panels. One Bull Researcher subagent and its model span are missing after an export timeout; its local response and charge remain in the results. The trace_complete field identifies that conversation.",
                    layout=wr.Layout(w=24, h=14),
                )
            ],
            layout_settings=ws.SectionLayoutSettings(columns=1, rows=1),
        ),
        ws.Section(
            name="Observed behavior and financial outcomes",
            is_open=True,
            panels=panels(),
            layout_settings=ws.SectionLayoutSettings(columns=1, rows=7),
        ),
    ]
    workspace.save()
    readback = ws.Workspace.from_url(workspace.url)
    assert len(readback.sections[1].panels) == 7
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
        "stopped_pilot_run_id": pilot_run_id,
        "stopped_pilot_url": pilot_url,
        "native_panels": 7,
        "report_panels": 2,
        "anonymous_tables_verified": tables,
        "native_views_and_tags": json.loads((OUT / "native-view-verification.json").read_text()),
        "result_sha256": digest,
        "protocol_sha256": result["protocol_sha256"],
        "executions": len(result["rows"]),
    }
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    publish()

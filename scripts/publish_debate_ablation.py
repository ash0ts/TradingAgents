"""Publish immutable derived results, native views/panels and private evidence."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode, urlsplit

import requests
import wandb
import wandb_workspaces.reports.v2 as wr
import wandb_workspaces.workspaces as ws
from run_debate_ablation import LEDGER, OUT, PUBLIC, REPO, sha

from tradingagents.lab.lens import LensClient

LABELS = {"luna-committee": "Full all-Luna committee", "luna-no-research": "No research debate",
          "luna-no-risk": "No risk debate", "single-luna": "Single Luna analyst"}
ENTITY, PROJECT = "wandb", "tradingagents-election-lab"


def panels():
    return [wr.BarPlot(metrics=["ablation/" + metric], title=title, title_x=unit,
                       max_runs_to_show=4, max_bars_to_show=4, legend_template="${run:displayName}",
                       layout=wr.Layout(x=0, y=i * 10, w=24, h=10))
            for i, (metric, title, unit) in enumerate([
                ("mean_selection_pnl", "Did selection beat the same allocation to SPY?", "Mean USD / independent $100,000 account; trials averaged, 8 dates"),
                ("same_weight_cases", "How often did all three runs choose the same allocation?", "Cases / 60; agreement is not accuracy"),
                ("total_model_cost_usd", "What did each workflow cost?", "USD upper estimate / 180 executions; includes cache writes and unknown-call reserves"),
                ("mean_exposure_at_entry", "How much was invested?", "Mean stock exposure at entry; 8 matured dates"),
                ("accepted", "Did the final execution contract pass?", "Accepted contracts / 180 requested; can include zero allocation"),
                ("complete_conversations", "Did every native span arrive?", "Complete conversations / 180, verified against journal and usage"),
            ])]


def native_views(result):
    audit = json.loads((OUT / "campaign-hosted-audit.json").read_text())
    traces = {r["conversation_id"]: r["trace_ids"][0] for r in audit["rows"]}
    reviewed = json.loads((PUBLIC / "reviews.json").read_text())
    assert reviewed["status"] == "complete" and len(reviewed["reviews"]) == 40
    reviewed_urls = {r["conversation_url"] for r in reviewed["reviews"]}
    numerical_issue_urls = {r["conversation_url"] for r in reviewed["reviews"]
                            if r.get("additional_observed_issue", {}).get("type") == "incorrect_unit_comparison"}
    expected_tags = {}
    for row in result["rows"]:
        cid = row["conversation_url"].rsplit("/", 1)[-1]
        expected_tags[cid] = {"debate-ablation-v5"}
        if row["conversation_url"] in reviewed_urls:
            expected_tags[cid].add("reviewed-v5-codex-assistant")
        if row["status"] == "failed":
            expected_tags[cid].add("observed-v5-actor-failure")
        if row["conversation_url"] in numerical_issue_urls:
            expected_tags[cid].add("reviewed-v5-numerical-comparison")
    def tag(row):
        cid = row["conversation_url"].rsplit("/", 1)[-1]
        receipt = OUT / "tag-receipts" / (cid + ".json")
        done = set(json.loads(receipt.read_text()).get("tags", [])) if receipt.exists() else set()
        for name in sorted(expected_tags[cid] - done):
            LensClient().tag(cid, traces[cid], name)
            done.add(name)
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text(json.dumps({"tags": sorted(done)}) + "\n")
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(tag, result["rows"]))
    client = LensClient()
    ids = list(traces)
    tagged = {cid: set() for cid in ids}
    for _ in range(10):
        for start in range(0, len(ids), 100):
            value = client.request("POST", "/conversation-tags/query", {"conversation_ids": ids[start:start + 100]})
            for row in value["data"]:
                tagged[row["conversation_id"]].add(row["tag"])
        if all(names <= tagged[cid] for cid, names in expected_tags.items()):
            break
        time.sleep(2)
    assert all(names <= tagged[cid] for cid, names in expected_tags.items())
    existing = {v["name"]: v for v in client.request("GET", "/views")["data"]}
    views = []
    definitions = [(label, {"id": "agent", "value": {"operator": "eq", "value": [arm + "/shared-evidence"]}}) for arm, label in LABELS.items()]
    definitions += [("Failed attempts", {"id": "errors", "value": {"operator": "gt", "value": 0}}),
                    ("Prespecified assistant reviews", {"id": "tags", "value": {"operator": "contains", "value": "reviewed-v5-codex-assistant"}}),
                    ("Reviewed numerical comparison", {"id": "tags", "value": {"operator": "contains", "value": "reviewed-v5-numerical-comparison"}})]
    for label, selected_filter in definitions:
        filters = [{"id": "tags", "value": {"operator": "contains", "value": "debate-ablation-v5"}}, selected_filter]
        if selected_filter["id"] == "tags":
            filters = [selected_filter]  # This review tag is unique to the study.
        body = {"name": "Repeated ablation · " + label,
                "description": "Three fresh executions per frozen case. Prespecified development study; trials are not independent market dates.",
                "url": "/agent-lens/wandb/tradingagents-election-lab-evidence/conversations?" + urlencode({"filter": json.dumps(filters, separators=(",", ":"))})}
        view = (client.request("PATCH", "/views/" + existing[body["name"]]["id"], body) if body["name"] in existing else client.request("POST", "/views", body))["data"]
        views.append(view)
    readback = {v["id"]: v for v in client.request("GET", "/views")["data"]}
    assert all(readback[v["id"]]["url"] == v["url"] for v in views)
    (OUT / "lens-views.json").write_text(json.dumps(views, indent=2) + "\n")
    return views


def publish():
    result = json.loads((PUBLIC / "results.json").read_text())
    digest = sha(PUBLIC / "results.json")
    assert result["executions"] == 720 and result["design"]["trials"] == 3
    assert result["hosted"]["complete_conversations"] == result["executions"]
    views = native_views(result)
    api = wandb.Api()
    anonymous = requests.Session()
    anonymous.trust_env = False
    ids, tables = [], 0
    for summary in result["summaries"]:
        arm = summary["treatment"]
        run_id = "debate-v5-" + hashlib.sha256((digest + arm).encode()).hexdigest()[:16]
        ids.append(run_id)
        fields = ("requested", "failed", "pending", "mean_selection_pnl", "mean_trading_pnl", "mean_exposure_at_entry", "same_weight_cases", "total_model_cost_usd", "total_model_cost_known_usd", "unknown_api_calls", "mean_latency_s", "complete_conversations")
        metrics = {"ablation/" + k: summary[k] for k in fields}
        metrics["ablation/accepted"] = summary["contract_counts"].get("accepted", 0)
        metrics["ablation/abstained"] = summary["contract_counts"].get("abstained", 0)
        payloads = {"every_decision": [r for r in result["rows"] if r["treatment"] == arm],
                    "accounts_and_matched_SPY": [r for r in result["portfolios"] if r["treatment"] == arm],
                    "three_run_repeatability": [r for r in result["repeatability"] if r["treatment"] == arm],
                    "all_planned_contrasts": result["paired_contrasts"],
                    "verified_role_presence": [r for r in result["engineering"] if r["treatment"] == arm]}
        try:
            run = api.run(f"{ENTITY}/{PROJECT}/{run_id}")
        except wandb.errors.CommError as exc:
            if "Could not find run" not in str(exc):
                raise
            run = None
        if run is None or not all(k in run.summary for k in payloads):
            with wandb.init(entity=ENTITY, project=PROJECT, id=run_id, resume="allow", name=LABELS[arm],
                            group="debate-ablation-v5", job_type="repeated-ablation-publication",
                            config={"treatment": arm, "result_sha256": digest, "protocol_sha256": result["protocol_sha256"], "independent_matured_dates": 8, "cohort_blocks": 4, "trials_per_case": 3, "study_kind": "retrospective development", "model_calls_in_publication": 0},
                            settings=wandb.Settings(console="off", x_disable_meta=True, disable_git=True, disable_code=True)) as logged:
                logged.summary.update(metrics)
                logged.log({k: wandb.Table(columns=list(v[0]), data=[list(r.values()) for r in v], allow_mixed_types=True) for k, v in payloads.items()})
            run = api.run(f"{ENTITY}/{PROJECT}/{run_id}")
        response = anonymous.get(run.file("wandb-summary.json").url, timeout=60)
        response.raise_for_status()
        saved = response.json()
        assert all(saved[k] == v for k, v in metrics.items())
        for key, values in payloads.items():
            response = anonymous.get(run.file(saved[key]["path"]).url, timeout=60)
            response.raise_for_status()
            assert len(response.json()["data"]) == len(values)
            tables += 1
    filters = "name in " + repr(ids)
    receipt_path = PUBLIC / "dashboard.json"
    prior = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    workspace = ws.Workspace.from_url(prior["wandb_url"]) if prior else ws.Workspace(entity=ENTITY, project=PROJECT, name="TradingAgents — does either debate earn its place?")
    workspace.runset_settings = ws.RunsetSettings(filters=filters, pinned_columns=["Name", "config.treatment"])
    workspace.settings.max_runs = 4
    links = "\n".join(f"- [{v['name']}](https://forge.coreweave.com{v['url']})" for v in views)
    workspace.sections = [ws.Section(name="Frozen study and evidence", is_open=True, panels=[wr.MarkdownPanel(
        markdown="## Does either debate earn its place?\n\n720 executions: 60 stock/date cases × four all-Luna workflows × three repetitions. Same evidence and repaired execution contract. Eight historical dates have matured outcomes; 2026 remains pending. Repetitions measure decision variability, not additional market observations.\n\nThe three planned comparisons use the full committee as control. We average repeats within date before pairing, retain four cohort blocks, and publish every date difference, leave-one-cohort-out estimate and Holm-adjusted sign-flip sensitivity. Four blocks cannot establish a 5% significance result here.\n\nEach run contains **every_decision**, **accounts_and_matched_SPY**, **three_run_repeatability**, **all_planned_contrasts** and **verified_role_presence** tables. Private trace links require team access. Costs include cache-write premiums and reserved unknown charges. The disclosed accounting amendment records a qualification-margin deviation; the global and follow-up hard caps were unchanged.\n\n[Protocol and methods](https://github.com/ash0ts/TradingAgents/tree/codex/tradingagents-forge-notebooks/studies/debate-ablation-v5)\n\n" + links,
        layout=wr.Layout(w=24, h=14))], layout_settings=ws.SectionLayoutSettings(columns=1, rows=1)),
        ws.Section(name="Financial outcomes, repeatability and cost", is_open=True, panels=panels(), layout_settings=ws.SectionLayoutSettings(columns=1, rows=6))]
    workspace.save()
    assert len(ws.Workspace.from_url(workspace.url).sections[1].panels) == 6
    grid = wr.PanelGrid(runsets=[wr.Runset(entity=ENTITY, project=PROJECT, filters=filters, name="Repeated debate ablation")], panels=panels()[:2])
    (REPO / "articles/ablation-panel-grid.json").write_text(grid._to_model().model_dump_json(indent=2) + "\n")
    parsed = urlsplit(workspace.url)
    forge_url = "https://forge.coreweave.com/wandb" + parsed.path + "?" + parsed.query
    receipt = {"result_sha256": digest, "wandb_url": workspace.url, "forge_url": forge_url,
               "run_ids": ids, "native_views": [{k: v[k] for k in ("id", "name", "description", "url")} for v in views], "anonymous_tables_verified": tables,
               "native_panels": 6, "report_panels": 2, "tagged_conversations": len(result["rows"])}
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


def archive():
    digest = sha(PUBLIC / "results.json")
    public_names = ["protocol.json", "dispatch-amendment.json", "design.json", "schedule.json", "qualification.json", "README.md", "results.json", "unit-account-factors.json", "public-reproduction.json", "decisions.csv", "accounts.csv", "summaries.csv", "repeatability.csv", "contrasts.csv", "figure-provenance.json", "trace-recovery-probe.json", "insights-status.json", "dashboard.json", "analysis-amendment.json", "analysis-amendment-publication.json", "pricing-reservation.json", "pricing-reconciliation.json", "reviews.json", "regressions.json", "screenshot-provenance.json"]
    package = OUT / "private-executions.tar.gz"
    manifest = {}
    if not package.exists():
        with sqlite3.connect(LEDGER) as source, sqlite3.connect(OUT / "budget.sqlite") as snapshot:
            source.backup(snapshot)
        with tarfile.open(package, "w:gz") as tar:
            for folder in ("shared-evidence", "native-spans", "hosted-readback", "trace-journal", "fault-injection"):
                for path in sorted((OUT / folder).rglob("*")):
                    if path.is_file():
                        name = str(path.relative_to(OUT))
                        manifest[name] = sha(path)
                        tar.add(path, arcname=name, recursive=False)
            for name in ("launch.json", "campaign-hosted-audit.json", "qualification-hosted-audit.json", "pricing-reconciliation-call-records.json", "frozen-export-before-cost-adjustment.json", "prespecified-review-material.json", "budget.sqlite"):
                manifest[name] = sha(OUT / name)
                tar.add(OUT / name, arcname=name)
        (OUT / "private-archive-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    receipts = []
    for private in (False, True):
        project = PROJECT + ("-evidence" if private else "")
        artifact = wandb.Artifact("debate-ablation-v5-" + ("executions" if private else "results"), type="repeated-ablation", metadata={"result_sha256": digest, "retrospective_development": True})
        for name in public_names:
            artifact.add_file(str(PUBLIC / name), name=name)
        if private:
            artifact.add_file(str(package), name=package.name)
            artifact.add_file(str(OUT / "private-archive-manifest.json"), name="private-archive-manifest.json")
        with wandb.init(entity=ENTITY, project=project, job_type="repeated-ablation-archive", settings=wandb.Settings(console="off", x_disable_meta=True, disable_git=True, disable_code=True)) as logged:
            saved = logged.log_artifact(artifact)
            saved.wait(timeout=300)
            remote = wandb.Api().artifact(saved.qualified_name)
            expected = {name: PUBLIC / name for name in public_names}
            if private:
                expected.update({package.name: package,
                                 "private-archive-manifest.json": OUT / "private-archive-manifest.json"})
            assert set(remote.manifest.entries) == set(expected)
            assert remote.digest == saved.digest
            destination = OUT / "artifact-readback" / ("private" if private else "public")
            for name, original in expected.items():
                downloaded = remote.get_entry(name).download(root=str(destination), skip_cache=True)
                assert sha(downloaded) == sha(original), name
            receipts.append({"artifact": saved.qualified_name, "digest": saved.digest, "private": private,
                             "manifest_files": len(saved.manifest.entries), "downloaded_files_sha256_verified": len(expected)})
    (PUBLIC / "artifact-publication.json").write_text(json.dumps(receipts, indent=2) + "\n")
    print(json.dumps(receipts, indent=2))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", action="store_true")
    archive() if parser.parse_args().archive else publish()

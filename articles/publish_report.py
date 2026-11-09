"""Publish reviewed article assets and update the existing report, preserving panels."""

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import requests
import wandb
import wandb_workspaces.reports.v2 as wr

ROOT = Path(__file__).resolve().parent
SLUGS = ["agent-lens-in-practice"]
RECEIPT = ROOT / "publication-assets.json"
REPORT_URL = json.loads((ROOT.parent / "notebooks/dashboards.json").read_text())["report"][
    "wandb_url"
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def files():
    # Explicitly excludes working notes, raw originals and private crosswalks.
    paths = []
    for slug in SLUGS:
        paths += sorted((ROOT / slug / "assets").glob("*"))
    paths += [
        ROOT / "evidence" / name
        for name in [
            "README.md",
            "manifest.json",
            "predictions.csv",
            "scores-all-horizons.csv",
            "portfolio-scenarios.csv",
            "source-coverage.csv",
            "assistant-reviews.csv",
            "paired-comparisons.csv",
            "selected-examples.csv",
            "method-summaries.csv",
            "directional-denominators.csv",
            "fee-sensitivity.csv",
            "tradingagents-public-evidence.zip",
            "verification-receipts.json",
            "study-design-and-budget.json",
        ]
    ]
    paths += [
        ROOT / "trading-scenarios" / name
        for name in [
            "README.md",
            "manifest.json",
            "protocol.json",
            "unit-account-factors.json",
            "scenario-results.json",
            "scenario-results.csv",
            "summaries.json",
            "summaries.csv",
            "cohort-breakdown.csv",
            "stock-contributions.csv",
            "verification.json",
            "trading-scenarios-evidence.zip",
        ]
    ]
    for p in paths:
        assert p.suffix in {".png", ".svg", ".csv", ".json", ".md", ".zip"}
        if p.suffix in {".svg", ".csv", ".json", ".md"}:
            body = p.read_text()
            assert not re.search(
                r"/Users/|/conversations/[0-9a-f-]{36}|WANDB_API_KEY|OPENAI_API_KEY", body
            ), p
    return paths


def upload():
    receipt = json.loads(RECEIPT.read_text()) if RECEIPT.exists() else {"files": {}}
    if "run_id" not in receipt:
        run = wandb.init(
            entity="wandb",
            project="tradingagents-election-lab",
            settings=wandb.Settings(x_disable_meta=True, disable_git=True, disable_code=True),
            job_type="article-publication",
            name="Agent Lens article evidence",
            config={
                "kind": "article-publication-assets",
                "new_model_runs": 0,
                "public_data_sha256": "f565efe5b288eaf93540484801b2f79e5f5bf8b2242ed9a3223428b797c10096",
            },
        )
        receipt["run_id"] = run.id
        run.finish()
        RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n")
    api = wandb.Api()
    run = api.run(f"wandb/tradingagents-election-lab/{receipt['run_id']}")
    session = requests.Session()
    session.trust_env = False  # anonymous readback: do not use netrc credentials
    for p in files():
        key = str(p.relative_to(ROOT))
        digest = sha(p.read_bytes())
        old = receipt["files"].get(key)
        if old and old["sha256"] == digest and old.get("anonymous_verified"):
            continue
        remote = run.upload_file(str(p), root=str(ROOT))
        url = remote.url
        assert not urlparse(url).query, "Refuse to publish expiring signed URL"
        response = session.get(url, timeout=60)
        response.raise_for_status()
        assert sha(response.content) == digest, key
        receipt["files"][key] = {
            "url": url,
            "sha256": digest,
            "bytes": len(response.content),
            "anonymous_verified": True,
        }
        RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n")
        print(f"Verified public asset: {key}", flush=True)
    return receipt


def article_blocks(slug, receipt, panels):
    text = (ROOT / slug / "article.md").read_text()
    heading, text = text.split("\n", 1)

    def link(match):
        label, target = match.groups()
        if target.startswith("http"):
            return match.group(0)
        path = (ROOT / slug / target).resolve()
        if path.name == "article.md":
            return f"[{label}]({REPORT_URL})"
        key = str(path.relative_to(ROOT))
        return f"[{label}]({receipt['files'][key]['url']})"

    text = re.sub(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)", link, text)
    blocks, buffer = [], []

    def flush():
        if body := "\n".join(buffer).strip():
            blocks.append(wr.MarkdownBlock(text=body))
        buffer.clear()

    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            blocks.append(wr.H1(line[3:]))
        elif marker := re.fullmatch(r"<!-- native-panel:(\w+) -->", line):
            flush()
            blocks.append(panels[marker[1]])
        elif match := re.fullmatch(r"!\[([^\]]+)\]\(([^)]+)\)", line):
            flush()
            alt, target = match.groups()
            key = str((ROOT / slug / target).resolve().relative_to(ROOT))
            blocks.append(wr.Image(url=receipt["files"][key]["url"], caption=alt))
        else:
            buffer.append(line)
    flush()
    return heading.removeprefix("# "), blocks


def publish(receipt):
    report = wr.Report.from_url(REPORT_URL)
    backup = ROOT / "private-evidence/forge-report-before-unification.json"
    current_obj = report._to_model().model_dump(mode="json")
    expected = json.loads((ROOT / "private-evidence/forge-report-after.json").read_text())
    assert current_obj.get("spec") == expected.get("spec"), (
        "Report changed since capture; inspect before update"
    )
    original = json.loads(backup.read_text())
    original_report = wr.Report._from_model(type(report._to_model()).model_validate(original))
    original_panels = [b for b in original_report.blocks if isinstance(b, wr.PanelGrid)]
    assert len(original_panels) == 2
    # The November 6 article report orders behavior before financial panels.
    panels = {"behavior": original_panels[0], "financial": original_panels[1]}
    panels["scenarios"] = wr.PanelGrid._from_model(
        type(original_panels[0]._to_model()).model_validate(
            json.loads((ROOT / "trading-scenarios-panel-grid.json").read_text())
        )
    )
    panel_models = [
        panels[k]._to_model().model_dump(mode="json")
        for k in ["financial", "behavior", "scenarios"]
    ]
    title, body = article_blocks(SLUGS[0], receipt, panels)
    blocks = [wr.TableOfContents(), *body]
    report.title = title
    report.blocks = blocks
    report.width = "fluid"
    report.description = "A TradingAgents investigation: native Agent Lens traces, saved Forge notebooks, financial and behavioral dashboards, and reproducible trading evidence. Market data frozen November 5, 2026."
    prior_publication = ROOT / "report-publication.json"
    proposed = report._to_model().model_dump_json()
    (ROOT / "private-evidence/forge-report-proposed.json").write_text(proposed)
    report.save()
    readback = wr.Report.from_url(REPORT_URL)
    raw_readback = wr.Report.from_url(REPORT_URL, as_model=True)
    assert raw_readback.spec.width == "fluid"
    actual_panels = [
        p._to_model().model_dump(mode="json")
        for p in readback.blocks
        if isinstance(p, wr.PanelGrid)
    ]
    assert actual_panels == panel_models, "Native panels changed"
    expected_images = [b.url for b in blocks if isinstance(b, wr.Image)]
    actual_images = [b.url for b in readback.blocks if isinstance(b, wr.Image)]
    assert expected_images == actual_images
    actual = readback._to_model().model_dump_json()
    (ROOT / "private-evidence/forge-report-after.json").write_text(actual)
    result = {
        "report_url": json.loads((ROOT.parent / "notebooks/dashboards.json").read_text())["report"][
            "forge_url"
        ],
        "same_report_identity": True,
        "images": len(actual_images),
        "native_panel_grids_preserved": 2,
        "native_panels_preserved": sum(len(p.panels) for p in original_panels),
        "article_count": 1,
        "trading_scenario_panels_added": 2,
        "trading_scenario_rows": 1120,
        "panel_layout": "Fluid width; financial panels h=11 so all 13 method labels fit. Data, filters and IDs preserved.",
        "source_sha256": {s: sha((ROOT / s / "article.md").read_bytes()) for s in SLUGS},
        "before_sha256": sha(backup.read_bytes()),
        "after_sha256": sha(actual.encode()),
        "new_model_runs_during_publication": 0,
    }
    prior_publication.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload-only", action="store_true")
    parser.add_argument("--publish-only", action="store_true")
    args = parser.parse_args()
    receipt = json.loads(RECEIPT.read_text()) if args.publish_only else upload()
    if not args.upload_only:
        publish(receipt)

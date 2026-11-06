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
SLUGS = [
    "meet-the-investment-committee",
    "confident-expensive-and-wrong",
    "did-it-beat-doing-nothing",
]
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
            name="Three-part article evidence",
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


def article_blocks(slug, receipt):
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
    blocks = [wr.H1(heading.removeprefix("# "))]
    for chunk in re.split(r"\n\n(?=!\[)|(?<=\))\n\n(?=\*)", text):
        m = re.fullmatch(r"!\[([^\]]+)\]\(([^)]+)\)", chunk.strip())
        if m:
            alt, target = m.groups()
            key = str((ROOT / slug / target).resolve().relative_to(ROOT))
            blocks.append(wr.Image(url=receipt["files"][key]["url"], caption=alt))
        else:
            # Markdown paragraphs/tables and primary-source links remain intact.
            blocks.append(wr.MarkdownBlock(text=chunk))
    return blocks


def publish(receipt):
    report = wr.Report.from_url(REPORT_URL)
    backup = ROOT / "private-evidence/forge-report-before.json"
    current = report._to_model().model_dump_json()
    original = json.loads(backup.read_text())
    # The supported roundtrip normalizes timestamps/defaults. Check content spec,
    # not JSON formatting, before replacing any prose.
    current_obj = json.loads(current)
    prior_publication = ROOT / "report-publication.json"
    expected = (
        json.loads((ROOT / "private-evidence/forge-report-after.json").read_text())
        if prior_publication.exists()
        else original
    )
    assert current_obj.get("spec") == expected.get("spec"), (
        "Report changed since capture; inspect before update"
    )
    original_report = wr.Report._from_model(type(report._to_model()).model_validate(original))
    panels = [b for b in original_report.blocks if isinstance(b, wr.PanelGrid)]
    assert len(panels) == 2
    # Thirteen labels need more height than the three-agent operational charts.
    # Keep panel IDs, data, filters, colors and runsets; only give labels room.
    for index, panel in enumerate(panels[0].panels):
        panel.layout = wr.Layout(x=12 * (index % 2), y=11 * (index // 2), w=12, h=11)
    panel_models = [p._to_model().model_dump(mode="json") for p in panels]
    preserved_intro = original_report.blocks[:3]
    blocks = preserved_intro + [
        wr.H1("Three articles, one inspectable experiment"),
        wr.P(
            "Read the study below, or open the native dashboards and Forge Notebooks. Every figure uses the frozen campaign. Screenshots are actual product captures. Public downloads contain sanitized results; raw sources and Agent Lens drilldowns require team access."
        ),
        wr.TableOfContents(),
    ]
    for i, slug in enumerate(SLUGS):
        blocks.append(wr.HorizontalRule())
        blocks.extend(article_blocks(slug, receipt))
        if i == 1:
            blocks += [wr.H2("Explore agent behavior and cost"), panels[1]]
        if i == 2:
            blocks += [wr.H2("Explore the financial outcomes"), panels[0]]
    report.blocks = blocks
    # SDK 0.4.13's from_url object omits width during deserialization.
    # Explicitly retain the original publisher's intended fluid panel width.
    report.width = "fluid"
    report.description = "Three-part TradingAgents investigation: actual Agent Lens captures, native dashboards, 960 predictions, 640 portfolio scenarios, and a downloadable evidence package. Frozen November 5, 2026; current five-session outcomes pending."
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
    assert actual_panels == [panel_models[1], panel_models[0]], "Native panels changed"
    expected_images = [b.url for b in blocks if isinstance(b, wr.Image)]
    actual_images = [b.url for b in readback.blocks if isinstance(b, wr.Image)]
    assert expected_images == actual_images
    actual = readback._to_model().model_dump_json()
    (ROOT / "private-evidence/forge-report-after.json").write_text(actual)
    result = {
        "report_url": REPORT_URL,
        "same_report_identity": True,
        "images": len(actual_images),
        "native_panel_grids_preserved": 2,
        "native_panels_preserved": sum(len(p.panels) for p in panels),
        "panel_layout": "Fluid width; financial panels h=11 so all 13 method labels fit. Data, filters and IDs preserved.",
        "source_sha256": {s: sha((ROOT / s / "article.md").read_bytes()) for s in SLUGS},
        "before_sha256": sha(backup.read_bytes()),
        "after_sha256": sha(actual.encode()),
        "new_model_runs": 0,
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

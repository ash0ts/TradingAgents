"""Separate public derived rerun evidence from private full model reports."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import wandb

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "studies/execution-contract-v2"
OUT = ROOT / "lab-runs/election-contract-v2"


def archive(public):
    result = json.loads((PUBLIC / "results.json").read_text())
    audit = json.loads((OUT / "hosted-audit.json").read_text())
    assert len(result["rows"]) == audit["conversations"] == 360
    name = "execution-contract-v2-results" if public else "execution-contract-v2-executions"
    project = "tradingagents-election-lab" + ("" if public else "-evidence")
    artifact = wandb.Artifact(name, type="evaluation-results", metadata={
        "protocol_sha256": result["protocol_sha256"], "result_sha256": hashlib.sha256((PUBLIC / "results.json").read_bytes()).hexdigest(),
        "development_rerun": True, "evidence_freeze_through": "2026-11-05",
        "original_private_evidence": json.loads((ROOT / "lab-runs/election-v1/private-artifact.json").read_text())["artifact"]})
    if public:
        # Allowlist only. Never include raw prediction files or model transcripts.
        for filename in ("protocol.json", "results.json", "paired-decisions.csv", "portfolio-results.csv", "summaries.json",
                         "verification.json", "reviews.json", "README.md", "figure-provenance.json", "dashboard.json"):
            artifact.add_file(str(PUBLIC / filename), name=filename)
    else:
        for directory in ("campaign", "qualification", "hosted-readback"):
            artifact.add_dir(str(OUT / directory), name=directory)
        for filename in ("design.json", "launch.json", "hosted-audit.json", "qualification-hosted-audit.json"):
            artifact.add_file(str(OUT / filename), name=filename)
        with sqlite3.connect(ROOT / "lab-runs/election-v1/budget.sqlite") as source, sqlite3.connect(OUT / "budget-backup.sqlite") as target:
            source.backup(target)
        artifact.add_file(str(OUT / "budget-backup.sqlite"), name="shared-budget.sqlite")
        artifact.add_file(str(PUBLIC / "protocol.json"), name="protocol.json")
    with wandb.init(entity="wandb", project=project, job_type="corrected-campaign-archive", name=name,
                    settings=wandb.Settings(console="off", x_disable_meta=True, disable_git=True, disable_code=True)) as run:
        saved = run.log_artifact(artifact, aliases=["execution-contract-v2"])
        saved.wait(timeout=300)
        receipt = {"artifact": saved.qualified_name, "digest": saved.digest, "project": "wandb/" + project,
                   "protocol_sha256": result["protocol_sha256"], "public": public}
    (OUT / ("public-artifact.json" if public else "private-artifact.json")).write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--public", action="store_true")
    archive(parser.parse_args().public)

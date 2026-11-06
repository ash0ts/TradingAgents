"""Publish source-restricted evidence privately and allowlisted results separately."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import wandb


def upload(root, output, public=False):
    root, output = Path(root), Path(output)
    project = "tradingagents-election-lab" + ("" if public else "-evidence")
    manifest = json.loads((root / "manifest.json").read_text())
    name = "election-lab-public-results" if public else "election-lab-frozen-evidence"
    artifact = wandb.Artifact(name, type="evaluation-results" if public else "dataset",
                             metadata={"evidence_version": manifest["version"],
                                       "freeze_through": manifest["freeze_through"],
                                       "retrospective_replay": True})
    if public:
        # Native editor caches and local export state are never public inputs.
        for path in [*Path("notebooks").glob("0*.py"), Path("notebooks/requirements.lock"),
                     Path("notebooks/publication.json"), Path("notebooks/data/showcase.json")]:
            artifact.add_file(str(path), name=str(path))
        for filename in ["regressions-v1.json", "public-reviews.json", "design.json"]:
            artifact.add_file(str(output / filename), name=filename)
    else:
        artifact.add_dir(str(root), name="evidence")
        for directory in ["campaign", "baselines", "models", "qualification"]:
            if (output / directory).exists():
                artifact.add_dir(str(output / directory), name=directory)
        with sqlite3.connect(output / "budget.sqlite") as source, sqlite3.connect(output / "budget-backup.sqlite") as target:
            source.backup(target)
        artifact.add_file(str(output / "budget-backup.sqlite"), name="budget.sqlite")
        for filename in ["design.json", "diagnostics.json", "regressions-v1.json", "hosted-audit.json", "public-call-audit.json"]:
            artifact.add_file(str(output / filename), name=filename)
    with wandb.init(entity="wandb", project=project, job_type="campaign-publication",
                    name=name, settings=wandb.Settings(console="off", disable_code=True)) as run:
        saved = run.log_artifact(artifact, aliases=["election-v1"])
        saved.wait(timeout=300)
        receipt = {"artifact": saved.qualified_name, "digest": saved.digest,
                   "project": "wandb/" + project, "evidence_version": manifest["version"]}
        (output / ("public-artifact.json" if public else "private-artifact.json")).write_text(json.dumps(receipt, indent=2))
        return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="lab-data/election-v1")
    parser.add_argument("--output", default="lab-runs/election-v1")
    parser.add_argument("--public", action="store_true")
    args = parser.parse_args()
    print(json.dumps(upload(args.root, args.output, args.public)))

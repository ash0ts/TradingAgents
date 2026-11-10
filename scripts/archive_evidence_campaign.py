"""Archive complete private executions and an explicit public result allowlist."""

from __future__ import annotations

import argparse
import json
import sqlite3

import wandb
from run_repaired_evidence_campaign import LEDGER, OUT, PUBLIC, REPO, sha


def archive(public):
    result = json.loads((PUBLIC / "results.json").read_text())
    audit = json.loads((OUT / "campaign-hosted-audit.json").read_text())
    assert len(result["rows"]) == audit["conversations"]
    name = (
        "common-evidence-v3-repaired-results"
        if public
        else "common-evidence-v3-repaired-executions"
    )
    project = "tradingagents-election-lab" + ("" if public else "-evidence")
    artifact = wandb.Artifact(
        name,
        type="evaluation-results",
        metadata={
            "protocol_sha256": result["protocol_sha256"],
            "result_sha256": sha(PUBLIC / "results.json"),
            "development_study": True,
            "evidence_freeze_through": "2026-11-05",
            "original_private_evidence": json.loads(
                (REPO / "lab-runs/election-v1/private-artifact.json").read_text()
            )["artifact"],
        },
    )
    if public:
        for name in (
            "protocol.json",
            "results.json",
            "summaries.json",
            "decisions.csv",
            "portfolio-results.csv",
            "trial-history.csv",
            "filing-age.csv",
            "reviews.json",
            "verification.json",
            "dashboard.json",
            "figure-provenance.json",
            "insights-status.json",
            "unit-account-factors.json",
            "public-reproduction.json",
            "publication-budget.json",
            "README.md",
        ):
            artifact.add_file(str(PUBLIC / name), name=name)
        artifact.add_file(
            str(REPO / "scripts/reproduce_evidence_accounts.py"),
            name="reproduce_evidence_accounts.py",
        )
        for name in ("protocol.json", "pilot-results.json", "README.md"):
            artifact.add_file(
                str(REPO / "studies/common-evidence-v3" / name), name="stopped-pilot/" + name
            )
    else:
        for mode in result["design"]["arms"]:
            for directory in ("campaign", "qualification"):
                artifact.add_dir(str(OUT / mode / directory), name=mode + "/" + directory)
        for directory in ("briefs", "hosted-readback", "native-spans"):
            artifact.add_dir(str(OUT / directory), name=directory)
        for name in (
            "design.json",
            "jobs.json",
            "launch.json",
            "campaign-hosted-audit.json",
            "qualification-hosted-audit.json",
            "account-audit.json",
            "native-view-verification.json",
            "lens-views.json",
        ):
            artifact.add_file(str(OUT / name), name=name)
        with (
            sqlite3.connect(LEDGER) as source,
            sqlite3.connect(OUT / "budget-backup.sqlite") as target,
        ):
            source.backup(target)
        artifact.add_file(str(OUT / "budget-backup.sqlite"), name="shared-budget.sqlite")
        artifact.add_file(str(PUBLIC / "protocol.json"), name="protocol.json")
        pilot = REPO / "lab-runs/election-evidence-v3"
        for mode in result["design"]["arms"]:
            for directory in ("campaign", "qualification"):
                artifact.add_dir(
                    str(pilot / mode / directory), name="stopped-pilot/" + mode + "/" + directory
                )
        artifact.add_dir(str(pilot / "hosted-readback"), name="stopped-pilot/hosted-readback")
        artifact.add_dir(str(pilot / "native-spans"), name="stopped-pilot/native-spans")
        for name in (
            "pilot-stop.json",
            "design.json",
            "campaign-hosted-audit.json",
            "qualification-hosted-audit.json",
        ):
            artifact.add_file(str(pilot / name), name="stopped-pilot/" + name)
    with wandb.init(
        entity="wandb",
        project=project,
        job_type="common-evidence-archive",
        name=artifact.name,
        settings=wandb.Settings(
            console="off", x_disable_meta=True, disable_git=True, disable_code=True
        ),
    ) as run:
        saved = run.log_artifact(artifact, aliases=["common-evidence-v3-repaired"])
        saved.wait(timeout=300)
        receipt = {
            "artifact": saved.qualified_name,
            "digest": saved.digest,
            "project": "wandb/" + project,
            "protocol_sha256": result["protocol_sha256"],
            "public": public,
        }
    (OUT / ("public-artifact.json" if public else "private-artifact.json")).write_text(
        json.dumps(receipt, indent=2) + "\n"
    )
    print(json.dumps(receipt))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--public", action="store_true")
    archive(parser.parse_args().public)

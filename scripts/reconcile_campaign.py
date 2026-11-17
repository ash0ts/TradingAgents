"""Reconcile the frozen evidence -> prediction -> scores -> portfolio -> public data path.

Offline verification: no model dispatch and no new market retrieval. Hosted
span and notebook readback use audit_hosted_campaign.py and
publish_forge_notebooks.py --verify separately.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingagents.lab.dashboard import validate_payload
from tradingagents.lab.evidence import EvidenceStore
from tradingagents.lab.portfolio import run_portfolios
from tradingagents.lab.publication import PORTFOLIO_FIELDS
from tradingagents.lab.scoring import score


def reconcile(root, output, payload):
    root, output = Path(root), Path(output)
    public = json.loads(Path(payload).read_text())
    result = validate_payload(public)
    manifest = json.loads((root / "manifest.json").read_text())
    outcomes = json.loads((root / "outcomes.json").read_text())["cases"]
    for case, sha in manifest["cases"].items():
        assert EvidenceStore(root).get(sha)["case"]["case_id"] == case
    rows = {r["run_key"]: r for r in public["rows"] if r["conversation_url"]}
    count = 0
    for path in (output / "campaign").rglob("prediction.json"):
        row = json.loads(path.read_text())
        clean = rows[row["run_key"]]
        assert row["evidence_sha256"] == manifest["cases"][row["case_id"]]
        for horizon, scores in row["scores_by_horizon"].items():
            assert scores == score(row, outcomes[row["case_id"]][horizon])
        for key in ["rating", "scores", "scores_by_horizon", "conversation_url", "evidence_sha256",
                    "dataset_version", "code_revision", "cost_known_usd"]:
            assert row[key] == clean[key], (row["run_key"], key)
        count += 1
    assert count == len(rows)
    portfolios = [{k: p.get(k) for k in PORTFOLIO_FIELDS} for p in run_portfolios(root, output)]
    assert portfolios == public["portfolios"]
    result.update(immutable_evidence_bundles=len(manifest["cases"]),
                  predictions_and_all_horizons_reconciled=count,
                  portfolio_scenarios_recomputed=len(portfolios))
    (output / "e2e-reconciliation.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="lab-data/election-v1")
    parser.add_argument("--output", default="lab-runs/election-v1")
    parser.add_argument("--payload", default="notebooks/data/showcase.json")
    args = parser.parse_args()
    print(json.dumps(reconcile(args.root, args.output, args.payload)))

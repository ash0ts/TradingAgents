import json

from tradingagents.lab.budget import Ledger
from tradingagents.lab.evidence import digest
from tradingagents.lab.publication import public_budget, public_export


def test_budget_distinguishes_infrastructure_holds_from_model_usage(tmp_path):
    ledger = Ledger(tmp_path / "budget.sqlite")
    ledger.reserve("model", "run", "campaign", "gpt-6-luna", 1_000_000)
    ledger.settle("model", {"input_tokens": 100, "output_tokens": 20})
    ledger.reserve("infra", "infra", "publication", "forge-infrastructure-pending-reconciliation", 20_000_000)
    result = public_budget(ledger)
    assert result["cost_known_usd"] == 0.000020
    assert result["infrastructure_reserved_usd"] == 20
    assert result["model_unknown_calls"] == 0
    assert result["cost_upper_usd"] == 20.000020


def test_public_export_omits_source_bearing_fields_and_keeps_lineage(tmp_path, monkeypatch):
    import tradingagents.lab.publication as publication

    root, output = tmp_path / "evidence", tmp_path / "runs"
    root.mkdir()
    directory = output / "campaign/case"
    directory.mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({"freeze_through": "2026-11-05", "version": "evidence-hash", "coverage": {}}))
    (output / "design.json").write_text(json.dumps({"stocks": 6, "trials": 2}))
    score = {"outcome_status": "pending", "failed": False, "abstained": True, "actionable": False, "signed_excess_return": None}
    private = "PRIVATE_SOURCE_CANARY"
    row = {"case_id": "case", "cohort": "2026", "treatment": "single-luna", "status": "success",
           "run_key": "run", "conversation_url": "https://forge.coreweave.com/conversation/example",
           "evidence_sha256": "case-hash", "scores": score, "scores_by_horizon": {"5": score},
           "report": private, "state": {"secret": private}, "events": [{"kind": "llm", "response": private}],
           "new_upstream_field": private}
    (directory / "prediction.json").write_text(json.dumps(row))
    monkeypatch.setattr(publication, "analyze", lambda *_: {"results": {}})
    monkeypatch.setattr(publication, "run_portfolios", lambda *_: [])
    result = public_export(root, output, tmp_path / "public.json")
    assert private not in json.dumps(result)
    assert result["rows"][0]["evidence_sha256"] == "case-hash"
    assert result["rows"][0]["model_calls"] == 1
    assert result["rows"][0]["scores"]["outcome_status"] == "pending"
    checksum = result.pop("public_data_sha256")
    assert checksum == digest(result)

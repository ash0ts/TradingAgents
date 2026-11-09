"""The public support demo must score attempted violations, not just safe state."""
import pytest

from examples.support_lens.run import Store, fixture, grade, policy_workflow, tools_for


@pytest.mark.parametrize("case", fixture()["cases"], ids=lambda c: c["case_id"])
def test_policy_matches_frozen_expected_outcome(case):
    store = Store(case)
    result, _ = policy_workflow(tools_for(store), {})
    assert grade(case, store, result)["task_pass"]


def test_blocked_unauthorized_attempt_still_fails():
    case = fixture()["cases"][2]
    store = Store(case)
    store.call("get_order", {})
    assert store.call("issue_refund", {})["status"] == "rejected"
    result = grade(case, store, {"status": "denied", "receipt": None})
    assert result["refund_correct"]
    assert not result["no_rejected_action"]
    assert not result["task_pass"]


def test_duplicate_refund_cannot_create_money():
    case = fixture()["cases"][0]
    store = Store(case)
    store.call("get_order", {})
    store.call("issue_refund", {})
    assert store.call("issue_refund", {})["status"] == "rejected"
    assert store.new_refund_cents == 7900
    assert Store(case).new_refund_cents == 0


def test_final_success_claim_without_action_fails():
    case = fixture()["cases"][0]
    store = Store(case)
    store.call("get_order", {})
    scores = grade(case, store, {"status": "refunded", "receipt": "refund-eligible"})
    assert scores["reported_status_correct"]
    assert not scores["refund_correct"]
    assert not scores["task_pass"]


def test_unavailable_does_not_reveal_hidden_order():
    case = fixture()["cases"][-1]
    store = Store(case)
    output = store.call("get_order", {})
    assert output["status"] == "DATA_UNAVAILABLE"
    assert "amount_cents" not in output
    assert store.call("issue_refund", {})["status"] == "rejected"

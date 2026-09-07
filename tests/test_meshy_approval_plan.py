"""Phase 46.5 tests: `factory.meshy_approval.build_meshy_approval_plan()`
and `factory meshy approval-plan`. This is a human-decision-package report
only - every test confirms it writes nothing, records nothing, selects no
decision on the human's behalf, and never contacts a network or reads a
credential. Every test isolates `MESHY_POLICY_PATH` to a `tmp_path` copy -
never the real committed `config/meshy_policy.json`. See
docs/meshy-policy.md "Phase 46.5".
"""

from __future__ import annotations

import copy
import json
import socket

import pytest
from typer.testing import CliRunner

from factory import meshy_approval as m
from factory.cli import app

runner = CliRunner()

_DEFAULT_POLICY = {
    "policy_version": 1,
    "cost_policy": {
        "currency": None, "per_request_cap": None, "per_project_cap": None, "daily_cap": None, "monthly_cap": None,
        "require_cost_estimate_before_request": True, "require_confirmation_above_threshold": True,
        "unknown_price_behavior": "block", "spend_tracking_required": True, "hard_stop_on_unknown_cost": True,
        "credit_policy": {"max_credits_per_request": None, "max_credits_per_project": None, "max_credits_per_day": None, "max_credits_per_month": None},
    },
    "license_policy": {
        "commercial_use_required": None, "commercial_use_verified": False, "terms_reviewed": False,
        "terms_review_date": None, "output_ownership_verified": False, "input_rights_required": True,
        "reference_license_required": True, "third_party_asset_restrictions": "unknown",
        "unknown_license_behavior": "block_commercial_use",
    },
    "approval": {
        "approved_at": None, "approved_by": None, "approval_scope": None,
        "cost_policy_acknowledged": False, "license_policy_acknowledged": False,
        "privacy_policy_acknowledged": False, "provenance_policy_acknowledged": False,
        "cloud_data_policy_acknowledged": False, "execution_enabled": False,
        "notes": [], "revoked_at": None, "revocation_history": [],
    },
}


@pytest.fixture
def policy_path(tmp_path, monkeypatch):
    path = tmp_path / "meshy_policy.json"
    path.write_text(json.dumps(copy.deepcopy(_DEFAULT_POLICY)))
    monkeypatch.setattr(m, "MESHY_POLICY_PATH", path)
    return path


# ---------------------------------------------------------------------------
# Core plan-building tests
# ---------------------------------------------------------------------------


def test_plan_is_read_only(policy_path):
    before = policy_path.read_text()
    m.build_meshy_approval_plan()
    assert policy_path.read_text() == before


def test_plan_has_ten_decisions(policy_path):
    plan = m.build_meshy_approval_plan()
    assert [d["id"] for d in plan["decisions"]] == list(range(1, 11))


def test_no_decision_is_pre_selected(policy_path):
    """Every decision's `current` must be `None`/empty (or the raw unset
    policy state echoed back) - never a value that looks like a human
    already chose it."""
    plan = m.build_meshy_approval_plan()
    for decision in plan["decisions"]:
        if decision["id"] in (7, 8):
            # Cost/credit decisions echo the (all-null) policy state itself.
            assert all(value is None for value in decision["current"].values())
        else:
            assert decision["current"] is None


def test_proposed_defaults_never_marked_approved(policy_path):
    plan = m.build_meshy_approval_plan()
    for decision in plan["decisions"]:
        if "proposed_default" in decision:
            assert decision["current"] is None
    assert plan["proposed_safe_defaults"]["label"] == "PROPOSED - NOT APPROVED"


def test_cost_nulls_remain_null(policy_path):
    plan = m.build_meshy_approval_plan()
    fields = plan["cost_fields_requiring_human_input"]
    for key in ("max_cost_per_request", "max_cost_per_project", "max_cost_per_day", "max_cost_per_month"):
        assert fields[key] is None
    for key in ("max_credits_per_request", "max_credits_per_project", "max_credits_per_day", "max_credits_per_month"):
        assert fields[key] is None
    assert fields["unknown_price_behavior"] == "block"


def test_cost_fields_reflect_explicit_caps(policy_path):
    policy = json.loads(policy_path.read_text())
    policy["cost_policy"]["per_request_cap"] = 5
    policy_path.write_text(json.dumps(policy))
    plan = m.build_meshy_approval_plan()
    assert plan["cost_fields_requiring_human_input"]["max_cost_per_request"] == 5
    assert plan["decisions"][6]["current"]["per_request_cap"] == 5


def test_implementation_approval_distinct_from_live_call_approval(policy_path):
    plan = m.build_meshy_approval_plan()
    assert plan["phase47_implementation_approval"]["status"] == "not_recorded"
    assert plan["phase47_live_call_approval"]["status"] == "not_recorded"
    assert plan["phase47_implementation_approval"] != plan["phase47_live_call_approval"]
    assert plan["phase47_live_call_approval"]["requires"]


def test_execution_remains_disabled_in_plan(policy_path):
    plan = m.build_meshy_approval_plan()
    assert plan["kill_switch"]["execution_enabled"] is False
    assert plan["current_state"]["execution"] == "disabled"


def test_student_and_private_data_stay_forbidden_in_plan(policy_path):
    plan = m.build_meshy_approval_plan()
    assert plan["proposed_safe_defaults"]["privacy"]["student_photos"] == "forbidden"
    assert plan["proposed_safe_defaults"]["privacy"]["student_identities"] == "forbidden"
    assert plan["proposed_safe_defaults"]["privacy"]["private_or_classroom_records"] == "forbidden"
    rows = {row["label"]: row for row in plan["input_classification_matrix"]}
    assert rows["Student photo"]["cloud_upload_allowed_by_default"] is False
    assert rows["Student identifying data"]["cloud_upload_allowed_by_default"] is False


def test_unknown_license_reference_blocked_in_matrix(policy_path):
    plan = m.build_meshy_approval_plan()
    rows = {row["label"]: row for row in plan["input_classification_matrix"]}
    assert rows["Unknown-license image"]["cloud_upload_allowed"] is False
    assert rows["Public-domain image"]["cloud_upload_allowed"] is True


def test_user_created_and_public_domain_treated_conditionally(policy_path):
    plan = m.build_meshy_approval_plan()
    rows = {row["label"]: row for row in plan["input_classification_matrix"]}
    # A user-created reference is allowed *by policy default* but decision 3
    # still proposes gating it behind explicit per-reference approval - the
    # plan must not claim it needs no further review.
    assert rows["User-created image"]["cloud_upload_allowed_by_default"] is True
    assert plan["decisions"][2]["proposed_default"] == "allow_after_per_reference_approval"


def test_reference_board_field_proposal_is_a_proposal_only(policy_path):
    plan = m.build_meshy_approval_plan()
    proposal = plan["reference_board_future_field_proposal"]
    assert proposal["status"] == "proposal_only_not_added"
    assert proposal["proposed_field"] == "cloud_upload_status"


def test_reference_board_json_never_touched(policy_path, tmp_path):
    board_path = tmp_path / "reference_board.json"
    board_path.write_text('{"references": []}')
    before = board_path.read_text()
    m.build_meshy_approval_plan()
    assert board_path.read_text() == before


def test_exact_commands_never_include_approve_without_review(policy_path):
    plan = m.build_meshy_approval_plan()
    commands = " ".join(plan["exact_commands_after_decisions"])
    assert "approve-policy" in commands
    assert "--ack-cost" in commands and "--ack-license" in commands


def test_phase47_scope_proposal_prefers_concept_generation_first(policy_path):
    plan = m.build_meshy_approval_plan()
    scope = plan["phase47_scope_proposal"]
    assert "47A" in scope and "47B" in scope and "47C" in scope
    assert "concept-generation" in scope["recommended_initial_scope"]
    assert "any real Meshy API call" in " ".join(scope["47A"]["excludes"])


def test_plan_json_serializable(policy_path):
    plan = m.build_meshy_approval_plan()
    json.dumps(plan)  # must not raise


def test_plan_safety_fields(policy_path):
    plan = m.build_meshy_approval_plan()
    assert plan["network_used"] is False
    assert plan["credentials_read"] is False
    assert plan["money_spent"] == 0
    assert plan["automatic_print_allowed"] is False
    assert plan["no_automatic_print"] is True


def test_plan_never_touches_network(policy_path, monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("build_meshy_approval_plan must never open a socket")

    monkeypatch.setattr(socket, "socket", _boom)
    m.build_meshy_approval_plan()


def test_plan_never_reads_meshy_credential_env_var(policy_path, monkeypatch):
    monkeypatch.setenv("MESHY_API_KEY", "fake-secret-should-never-appear")
    plan = m.build_meshy_approval_plan()
    assert "fake-secret-should-never-appear" not in json.dumps(plan)


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


def test_cli_approval_plan_human_output(policy_path):
    result = runner.invoke(app, ["meshy", "approval-plan"])
    assert result.exit_code == 0
    assert "MESHY HUMAN APPROVAL PLAN" in result.stdout
    assert "DECISION 1" in result.stdout
    assert "DECISION 10" in result.stdout
    assert "Proposed (NOT APPROVED)" in result.stdout


def test_cli_approval_plan_json_clean(policy_path):
    result = runner.invoke(app, ["meshy", "approval-plan", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["tool"] == "meshy"
    assert len(payload["decisions"]) == 10


def test_cli_approval_plan_never_writes_policy_file(policy_path):
    before = policy_path.read_text()
    runner.invoke(app, ["meshy", "approval-plan"])
    runner.invoke(app, ["meshy", "approval-plan", "--json"])
    assert policy_path.read_text() == before


def test_cli_approval_plan_safety_trailer(policy_path):
    result = runner.invoke(app, ["meshy", "approval-plan"])
    assert "No Meshy API call was made" in result.stdout
    assert "No credentials were read" in result.stdout


def test_cli_approval_plan_registered_under_meshy_help():
    result = runner.invoke(app, ["meshy", "--help"])
    assert "approval-plan" in result.stdout


def test_cli_does_not_run_approve_policy_automatically(policy_path):
    """`approval-plan` must never itself flip approval state, even though
    it *describes* the approve-policy command in its output."""
    runner.invoke(app, ["meshy", "approval-plan"])
    gate = m.evaluate_meshy_gate()
    assert gate["approval_recorded"] is False
    assert gate["kill_switch"]["execution_enabled"] is False

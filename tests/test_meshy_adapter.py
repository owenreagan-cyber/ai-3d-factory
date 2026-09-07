"""Phase 47A tests: `factory.meshy_adapter` - request planning, policy/
budget gating, the mocked task lifecycle, provenance, and the receipt.
Every test isolates `factory.meshy_approval.MESHY_POLICY_PATH` to a
`tmp_path` copy - never the real committed `config/meshy_policy.json`.
"""

from __future__ import annotations

import copy
import json

import pytest

from factory import meshy_adapter as adapter
from factory import meshy_approval as approval

_APPROVED_POLICY = {
    "policy_version": 1,
    "cost_policy": {
        "currency": "USD", "per_request_cap": None, "per_project_cap": None, "daily_cap": None, "monthly_cap": None,
        "require_cost_estimate_before_request": True, "require_confirmation_above_threshold": True,
        "unknown_price_behavior": "block", "spend_tracking_required": True, "hard_stop_on_unknown_cost": True,
        "credit_policy": {"max_credits_per_request": 25, "max_credits_per_project": 100, "max_credits_per_day": 150, "max_credits_per_month": 500},
    },
    "license_policy": {
        "commercial_use_required": True, "commercial_use_verified": False, "terms_reviewed": True,
        "terms_review_date": "2026-09-06", "output_ownership_verified": True, "input_rights_required": True,
        "reference_license_required": True, "third_party_asset_restrictions": "uploader_must_already_hold_rights_meshy_grants_none",
        "unknown_license_behavior": "block_commercial_use",
    },
    "approval": {
        "approved_at": "2026-09-07T00:00:00+00:00", "approved_by": "owen", "approval_scope": "policy_only",
        "cost_policy_acknowledged": True, "license_policy_acknowledged": True, "privacy_policy_acknowledged": True,
        "provenance_policy_acknowledged": True, "cloud_data_policy_acknowledged": True, "execution_enabled": False,
        "notes": [], "revoked_at": None, "revocation_history": [],
    },
}

_UNAPPROVED_POLICY = {
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
        "reference_license_required": True, "third_party_asset_restrictions": "unknown", "unknown_license_behavior": "block_commercial_use",
    },
    "approval": {
        "approved_at": None, "approved_by": None, "approval_scope": None, "cost_policy_acknowledged": False,
        "license_policy_acknowledged": False, "privacy_policy_acknowledged": False, "provenance_policy_acknowledged": False,
        "cloud_data_policy_acknowledged": False, "execution_enabled": False, "notes": [], "revoked_at": None, "revocation_history": [],
    },
}


@pytest.fixture
def approved_policy_path(tmp_path, monkeypatch):
    path = tmp_path / "meshy_policy.json"
    path.write_text(json.dumps(copy.deepcopy(_APPROVED_POLICY)))
    monkeypatch.setattr(approval, "MESHY_POLICY_PATH", path)
    return path


@pytest.fixture
def unapproved_policy_path(tmp_path, monkeypatch):
    path = tmp_path / "meshy_policy.json"
    path.write_text(json.dumps(copy.deepcopy(_UNAPPROVED_POLICY)))
    monkeypatch.setattr(approval, "MESHY_POLICY_PATH", path)
    return path


def _set_cost_policy(policy_path, **overrides):
    policy = json.loads(policy_path.read_text())
    policy["cost_policy"]["credit_policy"].update(overrides)
    policy_path.write_text(json.dumps(policy))


# ---------------------------------------------------------------------------
# Policy gate
# ---------------------------------------------------------------------------


def test_policy_gate_approved(approved_policy_path):
    check = adapter.check_policy_gate()
    assert check["policy_approved"] is True
    assert check["mock_execution_allowed"] is True
    assert check["live_execution_allowed"] is False


def test_policy_gate_not_approved_blocks_mock(unapproved_policy_path):
    check = adapter.check_policy_gate()
    assert check["policy_approved"] is False
    assert check["mock_execution_allowed"] is False
    assert check["live_execution_allowed"] is False
    assert check["blockers"]


def test_live_execution_never_allowed_regardless_of_policy(approved_policy_path):
    assert adapter.check_policy_gate()["live_execution_allowed"] is False


def test_policy_gate_reports_kill_switch_state(approved_policy_path):
    check = adapter.check_policy_gate()
    assert check["kill_switch_enabled"] is False  # config/future_cloud_tools.json, untouched by this phase


# ---------------------------------------------------------------------------
# Budget checks
# ---------------------------------------------------------------------------

_COST_POLICY = _APPROVED_POLICY["cost_policy"]


def test_budget_below_cap_allowed():
    result = adapter.check_budget(20, cost_policy=_COST_POLICY)
    assert result["allowed"] is True


def test_budget_equal_to_cap_allowed():
    result = adapter.check_budget(25, cost_policy=_COST_POLICY)
    assert result["allowed"] is True


def test_budget_above_cap_blocked():
    result = adapter.check_budget(26, cost_policy=_COST_POLICY)
    assert result["allowed"] is False
    assert result["error_code"] == "budget_exceeded"


def test_budget_unknown_cost_blocked():
    result = adapter.check_budget(None, cost_policy=_COST_POLICY)
    assert result["allowed"] is False
    assert result["error_code"] == "unknown_cost"


def test_budget_negative_estimate_rejected():
    result = adapter.check_budget(-5, cost_policy=_COST_POLICY)
    assert result["allowed"] is False
    assert result["error_code"] == "invalid_request"


def test_budget_zero_estimate_allowed():
    result = adapter.check_budget(0, cost_policy=_COST_POLICY)
    assert result["allowed"] is True


def test_budget_no_cap_configured_allows_anything_but_unknown():
    """A missing cap ('unset', not 'zero') never blocks by itself - only
    `unknown_price_behavior` (an explicit None estimate) blocks."""
    cost_policy = copy.deepcopy(_COST_POLICY)
    cost_policy["credit_policy"]["max_credits_per_request"] = None
    result = adapter.check_budget(1000000, cost_policy=cost_policy)
    assert result["allowed"] is True


def test_budget_project_cap_exceeded():
    ledger = adapter.InMemoryCreditLedger()
    ledger.record(request_id="r1", task_id="t1", estimated_credits=90, actual_credits=90, project_id="p1", status="SUCCEEDED")
    result = adapter.check_budget(20, cost_policy=_COST_POLICY, ledger=ledger, project_id="p1")
    assert result["allowed"] is False
    assert result["error_code"] == "budget_exceeded"


def test_budget_project_cap_not_shared_across_projects():
    ledger = adapter.InMemoryCreditLedger()
    ledger.record(request_id="r1", task_id="t1", estimated_credits=90, actual_credits=90, project_id="project-a", status="SUCCEEDED")
    result = adapter.check_budget(20, cost_policy=_COST_POLICY, ledger=ledger, project_id="project-b")
    assert result["allowed"] is True


def test_budget_daily_cap_exceeded():
    ledger = adapter.InMemoryCreditLedger()
    ledger.record(request_id="r1", task_id="t1", estimated_credits=140, actual_credits=140, project_id="p1", status="SUCCEEDED")
    result = adapter.check_budget(20, cost_policy=_COST_POLICY, ledger=ledger, project_id="p1")
    assert result["allowed"] is False


def test_budget_monthly_cap_exceeded():
    cost_policy = copy.deepcopy(_COST_POLICY)
    cost_policy["credit_policy"]["max_credits_per_day"] = None  # isolate the monthly check
    ledger = adapter.InMemoryCreditLedger()
    ledger.record(request_id="r1", task_id="t1", estimated_credits=490, actual_credits=490, project_id="p1", status="SUCCEEDED")
    result = adapter.check_budget(20, cost_policy=cost_policy, ledger=ledger, project_id="p1")
    assert result["allowed"] is False


def test_no_automatic_retry_field_on_budget_block():
    result = adapter.check_budget(1000, cost_policy=_COST_POLICY)
    assert result["allowed"] is False
    # budget checks never themselves retry with a smaller estimate


# ---------------------------------------------------------------------------
# Request planning
# ---------------------------------------------------------------------------


def test_plan_is_dry_run_and_writes_nothing(approved_policy_path, tmp_path):
    before = set(tmp_path.iterdir())
    plan = adapter.plan_text_to_3d_request(prompt="a rounded concept")
    assert plan["dry_run"] is True
    assert set(tmp_path.iterdir()) == before


def test_plan_prompt_hash_stable(approved_policy_path):
    plan = adapter.plan_text_to_3d_request(prompt="a rounded concept")
    assert plan["prompt_hash"] == plan["provenance"]["prompt_hash"]


def test_plan_mock_execution_allowed_when_policy_approved_and_budget_ok(approved_policy_path):
    plan = adapter.plan_text_to_3d_request(prompt="x")
    assert plan["mock_execution_allowed"] is True
    assert plan["blockers"] == []


def test_plan_blocked_when_policy_not_approved(unapproved_policy_path):
    plan = adapter.plan_text_to_3d_request(prompt="x")
    assert plan["mock_execution_allowed"] is False
    assert plan["blockers"]


def test_plan_json_serializable(approved_policy_path):
    plan = adapter.plan_text_to_3d_request(prompt="x")
    json.dumps(plan)


def test_plan_never_marks_live_execution_allowed(approved_policy_path):
    plan = adapter.plan_text_to_3d_request(prompt="x")
    assert plan["live_execution_allowed"] is False


def test_plan_surfaces_privacy_warning(approved_policy_path):
    plan = adapter.plan_text_to_3d_request(prompt="a keepsake for my student's birthday")
    assert plan["privacy_warnings"]
    assert any("student" in w for w in plan["warnings"])


# ---------------------------------------------------------------------------
# Mocked execution lifecycle
# ---------------------------------------------------------------------------


def test_execution_blocked_when_plan_not_allowed(unapproved_policy_path):
    plan = adapter.plan_text_to_3d_request(prompt="x")
    result = adapter.run_mock_text_to_3d_request(plan)
    assert result["task_id"] is None
    assert result["errors"]
    assert result["errors"][0]["error_code"] in ("policy_blocked", "unknown_cost", "budget_exceeded")


def test_execution_success_lifecycle(approved_policy_path):
    plan = adapter.plan_text_to_3d_request(prompt="x")
    result = adapter.run_mock_text_to_3d_request(plan, scenario="success")
    assert result["task_id"].startswith("mock-meshy-")
    assert result["lifecycle"] == ["PENDING", "IN_PROGRESS", "SUCCEEDED"]
    assert result["final_status"] == "SUCCEEDED"
    assert result["validation_state"] in ("PASS", "WARN")
    assert result["preview_state"] in ("PASS", "WARN")
    assert result["errors"] == []
    assert result["receipt"] is not None
    assert result["receipt"]["mock_execution"] is True
    assert result["receipt"]["live_api_used"] is False
    assert result["receipt"]["credits_spent"] == 0


def test_execution_failure_lifecycle(approved_policy_path):
    plan = adapter.plan_text_to_3d_request(prompt="x")
    result = adapter.run_mock_text_to_3d_request(plan, scenario="failure")
    assert result["final_status"] == "FAILED"
    assert any(e["error_code"] == "task_failed" for e in result["errors"])
    assert result["artifact_path"] is None


def test_execution_rate_limited(approved_policy_path):
    plan = adapter.plan_text_to_3d_request(prompt="x")
    result = adapter.run_mock_text_to_3d_request(plan, scenario="rate_limited")
    assert any(e["error_code"] == "rate_limited" for e in result["errors"])
    assert result["retry_allowed"] is False
    assert result["automatic_retry_performed"] is False


def test_execution_server_error(approved_policy_path):
    plan = adapter.plan_text_to_3d_request(prompt="x")
    result = adapter.run_mock_text_to_3d_request(plan, scenario="server_error")
    assert any(e["error_code"] == "server_error" for e in result["errors"])


def test_execution_expired_artifact(approved_policy_path):
    plan = adapter.plan_text_to_3d_request(prompt="x")
    result = adapter.run_mock_text_to_3d_request(plan, scenario="expired_artifact")
    assert any(e["error_code"] == "artifact_expired" for e in result["errors"])
    assert result["artifact_path"] is None


def test_execution_never_spends_real_credits(approved_policy_path):
    plan = adapter.plan_text_to_3d_request(prompt="x")
    result = adapter.run_mock_text_to_3d_request(plan, scenario="success")
    assert result["credits_spent"] == 0
    assert result["mock"] is True
    assert result["live_api_used"] is False


def test_execution_no_automatic_retry_loop(approved_policy_path):
    """A rate-limited submit must fail exactly once - no internal retry
    loop of any kind."""
    plan = adapter.plan_text_to_3d_request(prompt="x")
    result = adapter.run_mock_text_to_3d_request(plan, scenario="rate_limited")
    assert len(result["errors"]) == 1


def test_execution_bounded_polling_never_infinite(approved_policy_path, monkeypatch):
    """Force a task that never reaches a terminal state within the bound
    - must report task_timeout, never loop forever."""
    from factory.meshy_mock_transport import MockMeshyTransport

    class _NeverTerminalTransport(MockMeshyTransport):
        def get_task(self, task_id):
            response = super().get_task(task_id)
            response["status"] = "IN_PROGRESS"
            return response

    monkeypatch.setattr("factory.meshy_adapter.MockMeshyTransport", _NeverTerminalTransport)
    plan = adapter.plan_text_to_3d_request(prompt="x")
    result = adapter.run_mock_text_to_3d_request(plan, scenario="success")
    assert any(e["error_code"] == "task_timeout" for e in result["errors"])


# ---------------------------------------------------------------------------
# Validation/preview handoff - provider claims never bypass Factory checks
# ---------------------------------------------------------------------------


def test_mock_printable_claim_does_not_bypass_factory_validation(approved_policy_path, monkeypatch):
    """The mocked success fixture carries `meshy_printability_claim:
    {"printable": true}` - this must never be read as a substitute for a
    real `validate_mesh()` call. Force validate_mesh to report FAIL and
    confirm the receipt honestly reflects FAIL, proving the provider's
    own "printable" claim was never trusted."""

    def _fake_validate_mesh(path, printer=None):
        return {"overall_status": "FAIL", "checks": [], "mesh_stats": {}}

    monkeypatch.setattr("factory.meshy_adapter.validate_mesh", _fake_validate_mesh)
    plan = adapter.plan_text_to_3d_request(prompt="x")
    result = adapter.run_mock_text_to_3d_request(plan, scenario="success")
    assert result["validation_state"] == "FAIL"
    assert any(e["error_code"] == "validation_failed" for e in result["errors"])


def test_validate_mesh_is_actually_called(approved_policy_path, monkeypatch):
    calls = []

    def _spy_validate_mesh(path, printer=None):
        calls.append(path)
        return {"overall_status": "PASS", "checks": [], "mesh_stats": {}}

    monkeypatch.setattr("factory.meshy_adapter.validate_mesh", _spy_validate_mesh)
    plan = adapter.plan_text_to_3d_request(prompt="x")
    adapter.run_mock_text_to_3d_request(plan, scenario="success")
    assert len(calls) == 1


def test_validator_exception_does_not_abort_run(approved_policy_path, monkeypatch):
    def _boom(path, printer=None):
        raise RuntimeError("simulated validator crash")

    monkeypatch.setattr("factory.meshy_adapter.validate_mesh", _boom)
    plan = adapter.plan_text_to_3d_request(prompt="x")
    result = adapter.run_mock_text_to_3d_request(plan, scenario="success")
    assert result["validation_state"] == "FAIL"
    assert result["preview_state"] is not None  # preview still attempted


def test_preview_exception_does_not_abort_run(approved_policy_path, monkeypatch):
    def _boom(mesh_path, output_path):
        raise RuntimeError("simulated preview crash")

    monkeypatch.setattr("factory.meshy_adapter.render_preview", _boom)
    plan = adapter.plan_text_to_3d_request(prompt="x")
    result = adapter.run_mock_text_to_3d_request(plan, scenario="success")
    assert result["preview_state"] == "FAIL"
    assert result["validation_state"] is not None


# ---------------------------------------------------------------------------
# Artifact containment / temp cleanup
# ---------------------------------------------------------------------------


def test_temp_artifacts_cleaned_after_success(approved_policy_path):
    plan = adapter.plan_text_to_3d_request(prompt="x")
    result = adapter.run_mock_text_to_3d_request(plan, scenario="success")
    assert result["temporary_artifacts_cleaned"] is True
    from pathlib import Path

    assert not Path(result["artifact_path"]).exists()  # cleaned after the run returns


def test_no_unexpected_files_created(approved_policy_path):
    plan = adapter.plan_text_to_3d_request(prompt="x")
    result = adapter.run_mock_text_to_3d_request(plan, scenario="success")
    assert result["unexpected_files"] == []


def test_temp_run_never_touches_examples_or_projects_dir(approved_policy_path):
    from factory import project_store

    before_examples = set(project_store.REPO_ROOT.joinpath("examples").rglob("*")) if (project_store.REPO_ROOT / "examples").exists() else set()
    plan = adapter.plan_text_to_3d_request(prompt="x")
    adapter.run_mock_text_to_3d_request(plan, scenario="success")
    after_examples = set(project_store.REPO_ROOT.joinpath("examples").rglob("*")) if (project_store.REPO_ROOT / "examples").exists() else set()
    assert before_examples == after_examples


# ---------------------------------------------------------------------------
# Receipt write path - only with explicit project_dir
# ---------------------------------------------------------------------------


def test_no_project_no_receipt_written_to_disk(approved_policy_path, tmp_path):
    before = set(tmp_path.iterdir())
    plan = adapter.plan_text_to_3d_request(prompt="x")
    result = adapter.run_mock_text_to_3d_request(plan, scenario="success")
    assert result["receipt_path"] is None
    assert set(tmp_path.iterdir()) == before  # nothing new landed in the test's own tmp_path


def test_project_dir_writes_receipt_and_artifact(approved_policy_path, tmp_path):
    project_dir = tmp_path / "disposable-project"
    project_dir.mkdir()
    plan = adapter.plan_text_to_3d_request(prompt="x", project_id=str(project_dir))
    result = adapter.run_mock_text_to_3d_request(plan, scenario="success", project_dir=project_dir)

    receipt_path = project_dir / "generated" / "meshy_receipt.json"
    artifact_path = project_dir / "generated" / "meshy" / "mock_concept.stl"
    assert receipt_path.is_file()
    assert artifact_path.is_file()
    assert result["receipt_path"] == str(receipt_path)

    saved = json.loads(receipt_path.read_text())
    assert saved["mock_execution"] is True
    assert saved["live_api_used"] is False
    assert saved["credits_spent"] == 0
    assert saved["money_spent"] == 0
    assert saved["meshy_task_id"].startswith("mock-meshy-")


def test_project_dir_receipt_never_written_on_failure(approved_policy_path, tmp_path):
    project_dir = tmp_path / "disposable-project"
    project_dir.mkdir()
    plan = adapter.plan_text_to_3d_request(prompt="x")
    adapter.run_mock_text_to_3d_request(plan, scenario="failure", project_dir=project_dir)
    assert not (project_dir / "generated" / "meshy_receipt.json").exists()


# ---------------------------------------------------------------------------
# Commercial policy preservation
# ---------------------------------------------------------------------------


def test_commercial_use_verified_stays_false_in_provenance(approved_policy_path):
    plan = adapter.plan_text_to_3d_request(prompt="x")
    assert plan["provenance"]["commercial_policy_status"] is False  # commercial_use_verified is False in the fixture policy


def test_receipt_never_marks_commercial_ready(approved_policy_path):
    plan = adapter.plan_text_to_3d_request(prompt="x")
    result = adapter.run_mock_text_to_3d_request(plan, scenario="success")
    assert result["receipt"]["commercial_policy_status"] is False


# ---------------------------------------------------------------------------
# Adapter/registry runtime-state visibility
# ---------------------------------------------------------------------------


def test_summarize_mock_adapter_state():
    state = adapter.summarize_mock_adapter_state()
    assert state["mock_adapter_implemented"] is True
    assert state["live_transport_implemented"] is False
    assert state["live_execution_enabled"] is False


def test_safety_block_all_false():
    block = adapter.build_safety_block()
    assert block["network_used"] is False
    assert block["credentials_read"] is False
    assert block["credits_spent"] == 0
    assert block["money_spent"] == 0
    assert block["live_execution_allowed"] is False
    assert block["automatic_print_allowed"] is False

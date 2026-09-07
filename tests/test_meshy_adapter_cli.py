"""Phase 47A CLI tests: `factory meshy plan`/`factory meshy mock-run`.
Every test isolates `factory.meshy_approval.MESHY_POLICY_PATH` to a
`tmp_path` copy - never the real committed `config/meshy_policy.json`.
"""

from __future__ import annotations

import copy
import json

import pytest
from typer.testing import CliRunner

from factory import meshy_approval as approval
from factory.cli import app

runner = CliRunner()

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


# ---------------------------------------------------------------------------
# factory meshy plan
# ---------------------------------------------------------------------------


def test_plan_human_output(approved_policy_path):
    result = runner.invoke(app, ["meshy", "plan", "--prompt", "a rounded concept"])
    assert result.exit_code == 0
    assert "MESHY REQUEST PLAN" in result.stdout
    assert "Mocked Only" in result.stdout


def test_plan_json_clean(approved_policy_path):
    result = runner.invoke(app, ["meshy", "plan", "--prompt", "a rounded concept", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["request_type"] == "text_to_3d"
    assert payload["mock_execution_allowed"] is True
    assert payload["safety"]["network_used"] is False


def test_plan_help_text():
    result = runner.invoke(app, ["meshy", "plan", "--help"])
    assert result.exit_code == 0
    assert "--prompt" in result.stdout


def test_plan_writes_nothing(approved_policy_path, tmp_path):
    before = set(tmp_path.iterdir())
    runner.invoke(app, ["meshy", "plan", "--prompt", "a rounded concept"])
    assert set(tmp_path.iterdir()) == before


def test_plan_reports_blocked_when_policy_unapproved(unapproved_policy_path):
    result = runner.invoke(app, ["meshy", "plan", "--prompt", "x", "--json"])
    payload = json.loads(result.stdout)
    assert payload["mock_execution_allowed"] is False
    assert payload["blockers"]


# ---------------------------------------------------------------------------
# factory meshy mock-run
# ---------------------------------------------------------------------------


def test_mock_run_without_confirm_does_not_execute(approved_policy_path):
    result = runner.invoke(app, ["meshy", "mock-run", "--prompt", "x"])
    assert result.exit_code == 0
    assert "Pass --confirm-mock" in result.stdout
    assert "MESHY MOCK EXECUTION" not in result.stdout


def test_mock_run_without_confirm_json(approved_policy_path):
    result = runner.invoke(app, ["meshy", "mock-run", "--prompt", "x", "--json"])
    payload = json.loads(result.stdout)
    assert payload["note"].startswith("Dry-run only")
    assert "task_id" not in payload  # this is a plan dict, not an execution result


def test_mock_run_confirm_executes(approved_policy_path):
    result = runner.invoke(app, ["meshy", "mock-run", "--prompt", "x", "--confirm-mock"])
    assert result.exit_code == 0
    assert "MESHY MOCK EXECUTION" in result.stdout
    assert "mock-meshy-" in result.stdout
    assert "This is a MOCK artifact." in result.stdout


def test_mock_run_confirm_json(approved_policy_path):
    result = runner.invoke(app, ["meshy", "mock-run", "--prompt", "x", "--confirm-mock", "--json"])
    payload = json.loads(result.stdout)
    assert payload["task_id"].startswith("mock-meshy-")
    assert payload["mock"] is True
    assert payload["safety"]["network_used"] is False


def test_mock_run_scenario_option(approved_policy_path):
    result = runner.invoke(app, ["meshy", "mock-run", "--prompt", "x", "--confirm-mock", "--scenario", "failure", "--json"])
    payload = json.loads(result.stdout)
    assert payload["final_status"] == "FAILED"


def test_mock_run_no_project_writes_nothing_permanent(approved_policy_path, tmp_path):
    before = set(tmp_path.iterdir())
    runner.invoke(app, ["meshy", "mock-run", "--prompt", "x", "--confirm-mock"])
    assert set(tmp_path.iterdir()) == before


def test_mock_run_with_project_writes_receipt_and_artifact(approved_policy_path, tmp_path):
    project_dir = tmp_path / "disposable-project"
    project_dir.mkdir()
    result = runner.invoke(app, ["meshy", "mock-run", "--prompt", "x", "--confirm-mock", "--project", str(project_dir), "--json"])
    payload = json.loads(result.stdout)
    assert (project_dir / "generated" / "meshy_receipt.json").is_file()
    assert (project_dir / "generated" / "meshy" / "mock_concept.stl").is_file()
    assert payload["receipt_path"]


def test_mock_run_blocked_when_policy_unapproved(unapproved_policy_path):
    result = runner.invoke(app, ["meshy", "mock-run", "--prompt", "x", "--confirm-mock", "--json"])
    payload = json.loads(result.stdout)
    assert payload["task_id"] is None
    assert payload["errors"]


def test_mock_run_help_text():
    result = runner.invoke(app, ["meshy", "mock-run", "--help"])
    assert result.exit_code == 0
    assert "--confirm-mock" in result.stdout


# ---------------------------------------------------------------------------
# meshy status/policy - adapter visibility line
# ---------------------------------------------------------------------------


def test_meshy_status_shows_mock_adapter_implemented(approved_policy_path):
    result = runner.invoke(app, ["meshy", "status"])
    assert "Mock adapter" in result.stdout
    assert "Implemented" in result.stdout
    assert "Live transport" in result.stdout


def test_meshy_status_json_includes_adapter_state(approved_policy_path):
    result = runner.invoke(app, ["meshy", "status", "--json"])
    payload = json.loads(result.stdout)
    assert payload["adapter"]["mock_adapter_implemented"] is True
    assert payload["adapter"]["live_transport_implemented"] is True
    assert payload["adapter"]["live_execution_enabled"] is False


# ---------------------------------------------------------------------------
# Registered commands - no generate/live/upload/connect/login
# ---------------------------------------------------------------------------


def test_meshy_help_registers_plan_and_mock_run():
    from factory.cli import meshy_app

    registered = {c.name for c in meshy_app.registered_commands}
    assert "plan" in registered
    assert "mock-run" in registered
    for forbidden in ("generate", "live", "upload", "connect", "login"):
        assert forbidden not in registered


def test_available_commands_lists_meshy_plan_and_mock_run():
    from factory.cli import AVAILABLE_COMMANDS

    joined = " ".join(AVAILABLE_COMMANDS)
    assert "meshy plan" in joined
    assert "meshy mock-run" in joined

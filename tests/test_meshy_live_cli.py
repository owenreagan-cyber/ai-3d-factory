"""Phase 47B CLI tests: `factory meshy live-plan`/`approve-live-once`/
`revoke-live-approval`/`live-run`. Every test isolates policy/kill-switch/
ledger/approval state to `tmp_path` - never the real committed
`config/meshy_policy.json`/`config/future_cloud_tools.json` or the real
`state/` directory.
"""

from __future__ import annotations

import copy
import json

import pytest
from typer.testing import CliRunner

from factory import future_cloud_tools as fct
from factory import meshy_approval as approval
from factory import meshy_ledger as L
from factory import meshy_live_approval as A
from factory.cli import app

runner = CliRunner()

PROMPT = "A simple rounded piggy bank concept with no copyrighted characters, logos, text, or third-party references."

_APPROVED_POLICY = {
    "policy_version": 1,
    "cost_policy": {
        "currency": None, "per_request_cap": 25, "per_project_cap": 100, "daily_cap": 150, "monthly_cap": 500,
        "require_cost_estimate_before_request": True, "require_confirmation_above_threshold": True,
        "unknown_price_behavior": "block", "spend_tracking_required": True, "hard_stop_on_unknown_cost": True,
        "credit_policy": {"max_credits_per_request": 25, "max_credits_per_project": 100, "max_credits_per_day": 150, "max_credits_per_month": 500},
    },
    "license_policy": {
        "commercial_use_required": True, "commercial_use_verified": False, "terms_reviewed": True,
        "terms_review_date": "2026-09-06", "output_ownership_verified": True, "input_rights_required": True,
        "reference_license_required": True, "third_party_asset_restrictions": "x", "unknown_license_behavior": "block_commercial_use",
    },
    "approval": {
        "approved_at": "2026-09-07T00:00:00+00:00", "approved_by": "owen", "approval_scope": "policy_only",
        "cost_policy_acknowledged": True, "license_policy_acknowledged": True, "privacy_policy_acknowledged": True,
        "provenance_policy_acknowledged": True, "cloud_data_policy_acknowledged": True, "execution_enabled": False,
        "notes": [], "revoked_at": None, "revocation_history": [],
    },
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    policy_path = tmp_path / "meshy_policy.json"
    policy_path.write_text(json.dumps(copy.deepcopy(_APPROVED_POLICY)))
    monkeypatch.setattr(approval, "MESHY_POLICY_PATH", policy_path)

    fct_path = tmp_path / "future_cloud_tools.json"
    fct_path.write_text(json.dumps({"version": 1, "tools": {"meshy": {"enabled": False, "status": "future_gate_required"}}}))
    monkeypatch.setattr(fct, "FUTURE_CLOUD_TOOLS_PATH", fct_path)

    monkeypatch.setattr(L, "LEDGER_PATH", tmp_path / "ledger.json")
    monkeypatch.setattr(L, "_LOCK_PATH", tmp_path / "ledger.lock")
    monkeypatch.setattr(A, "APPROVAL_PATH", tmp_path / "approvals.json")

    return {"policy_path": policy_path, "fct_path": fct_path}


# ---------------------------------------------------------------------------
# live-plan
# ---------------------------------------------------------------------------


def test_live_plan_human_output(env):
    result = runner.invoke(app, ["meshy", "live-plan", "--prompt", PROMPT])
    assert result.exit_code == 0
    assert "MESHY LIVE PLAN" in result.stdout
    assert "Credential:" in result.stdout
    assert "Not checked" in result.stdout


def test_live_plan_json_clean(env):
    result = runner.invoke(app, ["meshy", "live-plan", "--prompt", PROMPT, "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["credential_checked"] is False
    assert payload["network_used"] is False


def test_live_plan_shows_correct_blocker_order(env):
    result = runner.invoke(app, ["meshy", "live-plan", "--prompt", PROMPT, "--json"])
    payload = json.loads(result.stdout)
    assert "Kill switch disabled" in " ".join(payload["blockers"])
    assert any("one-shot" in b.lower() for b in payload["blockers"])


# ---------------------------------------------------------------------------
# approve-live-once / revoke-live-approval
# ---------------------------------------------------------------------------


def test_approve_live_once_creates_record(env):
    result = runner.invoke(app, ["meshy", "approve-live-once", "--prompt", PROMPT, "--max-credits", "20"])
    assert result.exit_code == 0
    assert "recorded" in result.stdout.lower()

    approvals = A.load_approvals()
    assert len(approvals) == 1
    assert approvals[0]["status"] == "armed"


def test_approve_live_once_json(env):
    result = runner.invoke(app, ["meshy", "approve-live-once", "--prompt", PROMPT, "--max-credits", "20", "--json"])
    payload = json.loads(result.stdout)
    assert payload["approval_id"].startswith("meshy-approval-")


def test_approve_live_once_rejects_invalid_credits(env):
    result = runner.invoke(app, ["meshy", "approve-live-once", "--prompt", PROMPT, "--max-credits", "0"])
    assert result.exit_code == 1


def test_revoke_live_approval(env):
    create_result = runner.invoke(app, ["meshy", "approve-live-once", "--prompt", PROMPT, "--max-credits", "20", "--json"])
    approval_id = json.loads(create_result.stdout)["approval_id"]
    revoke_result = runner.invoke(app, ["meshy", "revoke-live-approval", approval_id])
    assert revoke_result.exit_code == 0
    assert A.load_approvals()[0]["status"] == "revoked"


def test_revoke_nonexistent_approval_errors(env):
    result = runner.invoke(app, ["meshy", "revoke-live-approval", "does-not-exist"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# live-run
# ---------------------------------------------------------------------------


def test_live_run_without_confirm_live_blocked(env):
    """Kill switch is disabled by default in this fixture, so the locked
    gate order surfaces kill_switch_disabled here (it's checked before
    confirm-live) - see test_confirm_live_missing_blocks_credential_never_called
    in test_meshy_live_adapter.py for the isolated confirm-live-specific case."""
    result = runner.invoke(app, ["meshy", "live-run", "--prompt", PROMPT, "--json"])
    payload = json.loads(result.stdout)
    assert payload["errors"][0]["error_code"] == "kill_switch_disabled"
    assert payload["live_api_used"] is False


def test_live_run_without_approval_blocked(env):
    result = runner.invoke(app, ["meshy", "live-run", "--prompt", PROMPT, "--confirm-live", "--json"])
    payload = json.loads(result.stdout)
    assert payload["errors"][0]["error_code"] == "kill_switch_disabled"


def test_live_run_human_output_safety_trailer(env):
    result = runner.invoke(app, ["meshy", "live-run", "--prompt", PROMPT, "--json"])
    result_human = runner.invoke(app, ["meshy", "live-run", "--prompt", PROMPT])
    assert "Automatic printing remains impossible" in result_human.stdout


def test_live_run_never_writes_policy_or_kill_switch_files(env):
    before_policy = env["policy_path"].read_text()
    before_fct = env["fct_path"].read_text()
    runner.invoke(app, ["meshy", "live-run", "--prompt", PROMPT, "--confirm-live"])
    assert env["policy_path"].read_text() == before_policy
    assert env["fct_path"].read_text() == before_fct


def test_help_lists_new_commands():
    result = runner.invoke(app, ["meshy", "--help"])
    for name in ("live-plan", "approve-live-once", "revoke-live-approval", "live-run"):
        assert name in result.stdout


def test_no_generate_upload_connect_login_commands_added():
    from factory.cli import meshy_app

    registered = {c.name for c in meshy_app.registered_commands}
    for forbidden in ("generate", "upload", "connect", "login", "live"):
        assert forbidden not in registered


# ---------------------------------------------------------------------------
# Phase 47B.7: reconcile-ledger-entry
# ---------------------------------------------------------------------------


def test_reconcile_ledger_entry_success(env):
    ledger = L.SpendLedger()
    entry = ledger.reserve(request_id="r1", project=None, request_type="text_to_3d", model="meshy-7", estimated_credits=20, policy_version=1, approval_reference="a1")
    ledger.mark_unknown(entry["reservation_id"], reason="submission failed: Meshy rejected the API key (HTTP 401)")

    result = runner.invoke(app, ["meshy", "reconcile-ledger-entry", entry["reservation_id"], "--reason", "401 before any task existed", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "confirmed_zero_rejected_before_submission"
    assert payload["actual_credits"] == 0


def test_reconcile_ledger_entry_refuses_entry_with_task_id(env):
    ledger = L.SpendLedger()
    entry = ledger.reserve(request_id="r1", project=None, request_type="text_to_3d", model="meshy-7", estimated_credits=20, policy_version=1, approval_reference="a1")
    ledger.mark_submitted(entry["reservation_id"], task_id="real-task-1")
    ledger.mark_unknown(entry["reservation_id"], reason="network error mid-poll")

    result = runner.invoke(app, ["meshy", "reconcile-ledger-entry", entry["reservation_id"], "--reason", "should be refused"])
    assert result.exit_code == 1


def test_reconcile_ledger_entry_never_touches_network_or_subprocess(env, monkeypatch):
    import socket
    import subprocess

    def _boom(*a, **k):
        raise AssertionError("reconcile-ledger-entry must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    ledger = L.SpendLedger()
    entry = ledger.reserve(request_id="r1", project=None, request_type="text_to_3d", model="meshy-7", estimated_credits=20, policy_version=1, approval_reference="a1")
    ledger.mark_unknown(entry["reservation_id"], reason="submission failed: Meshy rejected the API key (HTTP 401)")
    result = runner.invoke(app, ["meshy", "reconcile-ledger-entry", entry["reservation_id"], "--reason", "x", "--json"])
    assert result.exit_code == 0

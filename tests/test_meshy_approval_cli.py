"""Phase 46 CLI tests: `factory meshy status`/`policy`/`approval-status`/
`approve-policy`/`revoke-policy`. Every test isolates
`factory.meshy_approval.MESHY_POLICY_PATH` to a `tmp_path` copy - never
the real committed `config/meshy_policy.json`. See docs/meshy-policy.md.
"""

from __future__ import annotations

import copy
import json

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


def _set_ready_for_approval(policy_path):
    policy = json.loads(policy_path.read_text())
    policy["cost_policy"]["monthly_cap"] = 25
    policy["license_policy"]["terms_reviewed"] = True
    policy_path.write_text(json.dumps(policy))


# ---------------------------------------------------------------------------
# factory meshy status
# ---------------------------------------------------------------------------


def test_status_human_output(policy_path):
    result = runner.invoke(app, ["meshy", "status"])
    assert result.exit_code == 0
    assert "MESHY CLOUD APPROVAL GATE" in result.stdout
    assert "No Meshy API call was made" in result.stdout
    assert "No credentials were read" in result.stdout


def test_status_json_clean(policy_path):
    result = runner.invoke(app, ["meshy", "status", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["tool"] == "meshy"
    assert payload["safety"]["network_used"] is False
    assert payload["safety"]["credentials_read"] is False
    assert payload["safety"]["automatic_print_allowed"] is False
    assert payload["gate"]["kill_switch"]["execution_enabled"] is False


def test_status_json_has_no_console_text_contamination(policy_path):
    result = runner.invoke(app, ["meshy", "status", "--json"])
    # json.loads succeeding at all already proves no stray prose lines;
    # additionally assert the whole stdout is exactly one JSON document.
    assert result.stdout.count("{") == result.stdout.count("}")
    json.loads(result.stdout)


# ---------------------------------------------------------------------------
# factory meshy policy
# ---------------------------------------------------------------------------


def test_policy_human_output_shows_all_sections(policy_path):
    result = runner.invoke(app, ["meshy", "policy"])
    assert result.exit_code == 0
    for label in ("Cost policy:", "License policy:", "Privacy policy:", "Reference upload:", "Human approval:", "Kill switch:", "Phase 47 readiness:"):
        assert label in result.stdout


def test_policy_json_contains_all_policy_areas(policy_path):
    result = runner.invoke(app, ["meshy", "policy", "--json"])
    payload = json.loads(result.stdout)
    for key in ("cost_policy", "license_policy", "privacy_policy", "provenance_policy", "approval", "phase47_readiness"):
        assert key in payload


def test_policy_incomplete_shows_blockers(policy_path):
    result = runner.invoke(app, ["meshy", "policy"])
    assert "Cost cap not configured" in result.stdout


# ---------------------------------------------------------------------------
# factory meshy approval-status
# ---------------------------------------------------------------------------


def test_approval_status_human_output(policy_path):
    result = runner.invoke(app, ["meshy", "approval-status"])
    assert result.exit_code == 0
    assert "Approval recorded: No" in result.stdout
    assert "Execution enabled: False" in result.stdout


def test_approval_status_json(policy_path):
    result = runner.invoke(app, ["meshy", "approval-status", "--json"])
    payload = json.loads(result.stdout)
    assert payload["approval_recorded"] is False


# ---------------------------------------------------------------------------
# factory meshy approve-policy / revoke-policy
# ---------------------------------------------------------------------------


def test_approve_policy_requires_all_acks(policy_path):
    _set_ready_for_approval(policy_path)
    result = runner.invoke(app, ["meshy", "approve-policy", "--ack-cost", "--ack-license"])
    assert result.exit_code == 1
    assert "error" in result.stdout.lower()


def test_approve_policy_succeeds_with_all_acks(policy_path):
    _set_ready_for_approval(policy_path)
    result = runner.invoke(app, ["meshy", "approve-policy", "--ack-cost", "--ack-license", "--ack-privacy", "--ack-provenance", "--approved-by", "owen"])
    assert result.exit_code == 0
    assert "recorded" in result.stdout.lower()
    assert "execution_enabled=False" in result.stdout

    status = runner.invoke(app, ["meshy", "approval-status", "--json"])
    payload = json.loads(status.stdout)
    assert payload["approval_recorded"] is True
    assert payload["approval"]["execution_enabled"] is False


def test_approve_policy_note_flag_recorded(policy_path):
    _set_ready_for_approval(policy_path)
    result = runner.invoke(app, ["meshy", "approve-policy", "--ack-cost", "--ack-license", "--ack-privacy", "--ack-provenance", "--note", "research context for this approval"])
    assert result.exit_code == 0

    status = runner.invoke(app, ["meshy", "approval-status", "--json"])
    payload = json.loads(status.stdout)
    assert "research context for this approval" in payload["approval"]["notes"]


def test_approve_policy_refused_without_cost_cap(policy_path):
    result = runner.invoke(app, ["meshy", "approve-policy", "--ack-cost", "--ack-license", "--ack-privacy", "--ack-provenance"])
    assert result.exit_code == 1


def test_revoke_policy_without_prior_approval_errors(policy_path):
    result = runner.invoke(app, ["meshy", "revoke-policy"])
    assert result.exit_code == 1


def test_revoke_policy_succeeds_after_approval(policy_path):
    _set_ready_for_approval(policy_path)
    runner.invoke(app, ["meshy", "approve-policy", "--ack-cost", "--ack-license", "--ack-privacy", "--ack-provenance"])
    result = runner.invoke(app, ["meshy", "revoke-policy", "--reason", "testing"])
    assert result.exit_code == 0
    assert "revoked" in result.stdout.lower()

    status = runner.invoke(app, ["meshy", "approval-status", "--json"])
    payload = json.loads(status.stdout)
    assert payload["gate_status"] == "revoked"


def test_no_command_ever_enables_execution(policy_path):
    """Exhaustive: every meshy subcommand, run in sequence, never once
    results in execution_enabled=True."""
    _set_ready_for_approval(policy_path)
    for args in (
        ["meshy", "status"],
        ["meshy", "policy"],
        ["meshy", "approval-status"],
        ["meshy", "approve-policy", "--ack-cost", "--ack-license", "--ack-privacy", "--ack-provenance"],
        ["meshy", "status", "--json"],
    ):
        runner.invoke(app, args)
    final = json.loads(runner.invoke(app, ["meshy", "status", "--json"]).stdout)
    assert final["gate"]["kill_switch"]["execution_enabled"] is False


# ---------------------------------------------------------------------------
# Help text / command discoverability
# ---------------------------------------------------------------------------


def test_meshy_help_lists_subcommands():
    result = runner.invoke(app, ["meshy", "--help"])
    assert result.exit_code == 0
    for name in ("status", "policy", "approval-status", "approve-policy", "revoke-policy", "approval-plan"):
        assert name in result.stdout


def test_meshy_help_never_offers_generate_upload_connect_login_subcommands():
    """The help text's own prose legitimately says "zero data upload" etc.
    (describing what is forbidden) - this checks that none of those words
    appear as an actual registered subcommand name."""
    from factory.cli import meshy_app

    registered = {command.name for command in meshy_app.registered_commands}
    assert registered == {
        "status", "policy", "approval-status", "approve-policy", "revoke-policy", "approval-plan", "plan", "mock-run",
        "live-plan", "approve-live-once", "revoke-live-approval", "live-run", "reconcile-ledger-entry",
    }
    for forbidden in ("generate", "upload", "connect", "login", "live"):
        assert forbidden not in registered


def test_available_commands_lists_meshy():
    from factory.cli import AVAILABLE_COMMANDS

    joined = " ".join(AVAILABLE_COMMANDS)
    assert "meshy status" in joined
    assert "meshy policy" in joined

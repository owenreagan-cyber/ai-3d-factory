"""Phase 46 safety tests: hard proof that `factory.meshy_approval` (and its
CLI wiring) never touches the network, never reads a credential, and never
runs a subprocess. Unlike a source-text scan alone, the network/credential
tests here actively monkeypatch the primitive to raise, so a future
regression that adds a real network/credential call would fail loudly
here rather than passing silently. See docs/meshy-policy.md.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import inspect
import json
import os
import socket
import subprocess

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
# Static source scan: no network/HTTP import anywhere in this phase's code
# ---------------------------------------------------------------------------


def test_module_imports_no_network_capable_library():
    tree = ast.parse(inspect.getsource(m))
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module.split(".")[0])
    forbidden = {"socket", "requests", "httpx", "aiohttp", "urllib", "http", "ftplib", "smtplib"}
    assert imported_names.isdisjoint(forbidden), f"forbidden network import(s) found: {imported_names & forbidden}"


def test_module_makes_no_subprocess_call_at_all():
    source = inspect.getsource(m)
    assert "subprocess" not in source
    assert "os.system" not in source
    assert "shell=True" not in source


def test_module_never_uses_open_osascript_pkill():
    source = inspect.getsource(m)
    for forbidden in ("osascript", "AppleScript", "pkill", "System Events"):
        # allow the word only inside a comment/docstring that is itself
        # warning against it, never as an actual invoked command string
        assert f'"{forbidden}' not in source and f"'{forbidden}" not in source


def test_no_requests_dependency_in_this_repo_at_all():
    """This repo has no HTTP client dependency installed at all - the
    strongest possible guarantee that no code path (this phase's or any
    other) can accidentally make a real HTTP call via a library import."""
    for lib in ("requests", "httpx", "aiohttp"):
        assert importlib.util.find_spec(lib) is None, f"unexpected network library present: {lib}"


# ---------------------------------------------------------------------------
# Active guards: network/subprocess primitives raise if ever touched
# ---------------------------------------------------------------------------


def _boom(*args, **kwargs):
    raise AssertionError("factory.meshy_approval must never open a network socket or run a subprocess")


@pytest.fixture(autouse=True)
def _guard_network_and_subprocess(monkeypatch):
    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)
    monkeypatch.setattr(os, "system", _boom)
    yield


def test_evaluate_gate_succeeds_with_network_and_subprocess_blocked(policy_path):
    gate = m.evaluate_meshy_gate()
    assert gate["gate_status"] == "needs_cost_policy"


def test_readiness_succeeds_with_network_and_subprocess_blocked(policy_path):
    readiness = m.evaluate_meshy_phase47_readiness()
    assert readiness["ready_for_phase47"] is False


def test_approve_and_revoke_succeed_with_network_and_subprocess_blocked(policy_path):
    _set_ready_for_approval(policy_path)
    m.record_meshy_policy_approval(ack_cost=True, ack_license=True, ack_privacy=True, ack_provenance=True)
    m.revoke_meshy_policy_approval()


def test_every_meshy_cli_command_succeeds_with_network_and_subprocess_blocked(policy_path):
    _set_ready_for_approval(policy_path)
    for args in (
        ["meshy", "status"], ["meshy", "status", "--json"],
        ["meshy", "policy"], ["meshy", "policy", "--json"],
        ["meshy", "approval-status"], ["meshy", "approval-status", "--json"],
        ["meshy", "approve-policy", "--ack-cost", "--ack-license", "--ack-privacy", "--ack-provenance"],
        ["meshy", "revoke-policy"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, f"{args} failed: {result.stdout}"


def test_classification_helpers_succeed_with_network_and_subprocess_blocked():
    m.classify_reference_cloud_upload_permission("unknown")
    m.classify_data_class_cloud_permission("student_photo")


def test_preview_board_meshy_summary_succeeds_with_network_and_subprocess_blocked(policy_path):
    summary = m.summarize_meshy_policy_for_board()
    assert summary["cloud_use_allowed"] is False


# ---------------------------------------------------------------------------
# Credential safety
# ---------------------------------------------------------------------------


def test_module_never_calls_os_environ_for_a_credential_name():
    source = inspect.getsource(m)
    assert "os.environ" not in source
    assert "os.getenv" not in source
    assert "getenv(" not in source


def test_no_credential_value_ever_appears_in_gate_or_status_output(monkeypatch, policy_path):
    """Even if a Meshy-like env var happens to be set on the machine
    running this test, no meshy_approval output may contain its value -
    because no code path here ever reads it in the first place."""
    monkeypatch.setenv("MESHY_API_KEY", "sk-super-secret-value-should-never-appear")
    gate = m.evaluate_meshy_gate()
    serialized = json.dumps(gate, default=str)
    assert "sk-super-secret-value-should-never-appear" not in serialized

    result = runner.invoke(app, ["meshy", "status", "--json"])
    assert "sk-super-secret-value-should-never-appear" not in result.stdout

    verbose_result = runner.invoke(app, ["meshy", "policy"])
    assert "sk-super-secret-value-should-never-appear" not in verbose_result.stdout


def test_module_source_never_mentions_meshy_api_key_literal():
    """This module doesn't even check for the *existence* of a Meshy
    credential env var, matching the spec's stated preference - so its
    source should not reference the env var name at all."""
    source = inspect.getsource(m)
    assert "MESHY_API_KEY" not in source


def test_dotenv_never_loaded_by_this_module():
    """The module docstring legitimately mentions ".env" descriptively
    (documenting that it never reads one) - this checks for an actual
    load call/import, not the substring."""
    source = inspect.getsource(m)
    assert "dotenv" not in source
    assert "open(\".env\"" not in source
    assert "load_dotenv" not in source


# ---------------------------------------------------------------------------
# Approval/policy file write safety: no secrets ever written
# ---------------------------------------------------------------------------


def test_approval_record_never_contains_a_credential_field(policy_path):
    _set_ready_for_approval(policy_path)
    m.record_meshy_policy_approval(ack_cost=True, ack_license=True, ack_privacy=True, ack_provenance=True, approved_by="owen")
    written = json.loads(policy_path.read_text())
    serialized = json.dumps(written)
    for forbidden in ("api_key", "apikey", "secret", "token", "credential"):
        assert forbidden not in serialized.lower()


def test_policy_file_write_stays_local_json_no_network(policy_path):
    _set_ready_for_approval(policy_path)
    # subprocess/socket are already patched to raise via the autouse fixture -
    # a passing call here is itself proof no network path exists.
    m.record_meshy_policy_approval(ack_cost=True, ack_license=True, ack_privacy=True, ack_provenance=True)
    assert policy_path.exists()


# ---------------------------------------------------------------------------
# Write-safety scope: meshy commands take no project path argument, so
# they can never target examples/ or projects/ in the first place.
# ---------------------------------------------------------------------------


def test_no_meshy_command_accepts_a_project_directory_argument():
    from factory.cli import meshy_app

    for command in meshy_app.registered_commands:
        for param in command.callback.__code__.co_varnames[: command.callback.__code__.co_argcount]:
            assert param not in ("project_dir",), f"{command.name} unexpectedly takes a project_dir argument"

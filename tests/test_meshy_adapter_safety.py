"""Phase 47A safety tests: proves - not just asserts by inspection - that
the mocked Meshy adapter never contacts a network, never reads a
credential, never invokes a subprocess, and never leaks a secret. Also
statically scans the new Phase 47A source files for forbidden imports/
calls.
"""

from __future__ import annotations

import ast
import copy
import json
import socket
import subprocess

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


@pytest.fixture
def approved_policy_path(tmp_path, monkeypatch):
    path = tmp_path / "meshy_policy.json"
    path.write_text(json.dumps(copy.deepcopy(_APPROVED_POLICY)))
    monkeypatch.setattr(approval, "MESHY_POLICY_PATH", path)
    return path


_PHASE_47A_MODULES = (
    "factory.meshy_models",
    "factory.meshy_mock_transport",
    "factory.meshy_adapter",
)


def _module_source_path(module_name: str) -> str:
    import importlib

    module = importlib.import_module(module_name)
    return module.__file__


# ---------------------------------------------------------------------------
# Static AST scans
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", _PHASE_47A_MODULES)
def test_no_forbidden_network_or_subprocess_imports(module_name):
    path = _module_source_path(module_name)
    tree = ast.parse(open(path).read())
    forbidden = {"socket", "requests", "httpx", "aiohttp", "urllib", "subprocess"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(forbidden), f"{module_name} imports forbidden module(s): {imported & forbidden}"


@pytest.mark.parametrize("module_name", _PHASE_47A_MODULES)
def test_no_os_system_or_shell_calls(module_name):
    path = _module_source_path(module_name)
    tree = ast.parse(open(path).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "system" and isinstance(func.value, ast.Name) and func.value.id == "os":
                pytest.fail(f"{module_name} calls os.system()")


@pytest.mark.parametrize("module_name", _PHASE_47A_MODULES)
def test_no_credential_env_var_access(module_name):
    """No new Phase 47A code may call `os.environ.get`/`os.getenv` for
    anything resembling a Meshy API key or `.env` - credential handling
    is explicitly deferred to a future, separately-approved Phase 47B."""
    path = _module_source_path(module_name)
    tree = ast.parse(open(path).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
            pytest.fail(f"{module_name} references os.{node.attr} - credential/env access is forbidden in Phase 47A")
        if isinstance(node, ast.Call):
            func = node.func
            called_name = func.attr if isinstance(func, ast.Attribute) else (func.id if isinstance(func, ast.Name) else None)
            if called_name in ("getenv", "load_dotenv"):
                pytest.fail(f"{module_name} calls {called_name}() - credential/env access is forbidden in Phase 47A")


def test_no_http_client_import_anywhere_in_phase_47a():
    """`requests`/`httpx`/`aiohttp` must not even be importable from any
    Phase 47A module - covers the case where an import is nested inside
    a function (not caught by the module-level AST scan above)."""
    for module_name in _PHASE_47A_MODULES:
        path = _module_source_path(module_name)
        source = open(path).read()
        for lib in ("requests", "httpx", "aiohttp"):
            assert f"import {lib}" not in source, f"{module_name} imports {lib}"


# ---------------------------------------------------------------------------
# Live proof: real code paths still work with network/subprocess poisoned
# ---------------------------------------------------------------------------


def test_plan_survives_network_and_subprocess_disabled(approved_policy_path, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("factory meshy plan must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    result = runner.invoke(app, ["meshy", "plan", "--prompt", "a rounded concept", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["mock_execution_allowed"] is True


def test_mock_run_survives_network_and_subprocess_disabled(approved_policy_path, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("factory meshy mock-run must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    result = runner.invoke(app, ["meshy", "mock-run", "--prompt", "a rounded concept", "--confirm-mock", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["task_id"].startswith("mock-meshy-")
    assert payload["final_status"] == "SUCCEEDED"


def test_mock_run_all_scenarios_survive_network_and_subprocess_disabled(approved_policy_path, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    for scenario in ("success", "failure", "rate_limited", "server_error", "expired_artifact"):
        result = runner.invoke(app, ["meshy", "mock-run", "--prompt", "x", "--confirm-mock", "--scenario", scenario, "--json"])
        assert result.exit_code == 0, (scenario, result.stdout)


# ---------------------------------------------------------------------------
# Secret hygiene
# ---------------------------------------------------------------------------


def test_fake_credential_env_var_never_leaks_into_plan_output(approved_policy_path, monkeypatch):
    monkeypatch.setenv("MESHY_API_KEY", "fake-secret-should-never-appear")
    result = runner.invoke(app, ["meshy", "plan", "--prompt", "a rounded concept", "--json"])
    assert "fake-secret-should-never-appear" not in result.stdout


def test_fake_credential_env_var_never_leaks_into_mock_run_output(approved_policy_path, monkeypatch):
    monkeypatch.setenv("MESHY_API_KEY", "fake-secret-should-never-appear")
    result = runner.invoke(app, ["meshy", "mock-run", "--prompt", "a rounded concept", "--confirm-mock", "--json"])
    assert "fake-secret-should-never-appear" not in result.stdout


# ---------------------------------------------------------------------------
# Task ID namespacing / kill switch / live execution never settable
# ---------------------------------------------------------------------------


def test_every_mock_task_id_is_namespaced(approved_policy_path):
    for scenario in ("success", "failure"):
        result = runner.invoke(app, ["meshy", "mock-run", "--prompt", "x", "--confirm-mock", "--scenario", scenario, "--json"])
        payload = json.loads(result.stdout)
        assert payload["task_id"].startswith("mock-meshy-")


def test_kill_switch_untouched_by_mock_run(approved_policy_path):
    from factory import future_cloud_tools

    before = future_cloud_tools.get_future_cloud_tool("meshy")
    runner.invoke(app, ["meshy", "mock-run", "--prompt", "x", "--confirm-mock"])
    after = future_cloud_tools.get_future_cloud_tool("meshy")
    assert before == after
    assert after["enabled"] is False


def test_live_execution_allowed_always_false_across_all_results(approved_policy_path):
    from factory import meshy_adapter as adapter

    plan = adapter.plan_text_to_3d_request(prompt="x")
    assert plan["live_execution_allowed"] is False
    for scenario in ("success", "failure", "rate_limited", "server_error", "expired_artifact"):
        result = adapter.run_mock_text_to_3d_request(plan, scenario=scenario)
        # no field in the result can ever claim live execution happened
        assert result["live_api_used"] is False
        assert result.get("credits_spent") == 0

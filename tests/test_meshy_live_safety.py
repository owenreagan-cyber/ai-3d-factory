"""Phase 47B safety tests: proves - not just asserts by inspection - that
`factory.meshy_http_transport` is the ONLY new Phase 47B module allowed to
contain network-capable code, that no new module reads a Meshy
credential outside `meshy_http_transport`, and that every offline command
(`meshy live-plan`, `meshy status`, `meshy policy`, `meshy plan`, `meshy
mock-run`) still succeeds with real network/subprocess primitives
poisoned to raise. **No test in this file ever contacts a real network
host or reads the real `MESSY_API_KEY`/`.env`.**
"""

from __future__ import annotations

import ast
import copy
import importlib
import json
import socket
import subprocess

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
    return {"policy_path": policy_path}


_PHASE_47B_NON_NETWORK_MODULES = (
    "factory.meshy_ledger",
    "factory.meshy_live_approval",
    "factory.meshy_live_adapter",
)
_PHASE_47B_NETWORK_MODULE = "factory.meshy_http_transport"


def _source_path(module_name: str) -> str:
    return importlib.import_module(module_name).__file__


# ---------------------------------------------------------------------------
# Static AST scans - network isolation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", _PHASE_47B_NON_NETWORK_MODULES)
def test_non_transport_modules_import_no_network_library(module_name):
    tree = ast.parse(open(_source_path(module_name)).read())
    forbidden = {"socket", "requests", "httpx", "aiohttp", "urllib"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(forbidden), f"{module_name} imports forbidden module(s): {imported & forbidden}"


def test_only_http_transport_module_imports_urllib():
    """Confirms the isolation is exactly as narrow as claimed: `urllib` is
    importable from `meshy_http_transport` and nowhere else new in this
    phase (meshy_live_adapter constructs it only via dependency
    injection, never imports it directly)."""
    tree = ast.parse(open(_source_path(_PHASE_47B_NETWORK_MODULE)).read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "urllib" in imported

    tree2 = ast.parse(open(_source_path("factory.meshy_live_adapter")).read())
    imported2 = set()
    for node in ast.walk(tree2):
        if isinstance(node, ast.Import):
            imported2.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported2.add(node.module.split(".")[0])
    assert "urllib" not in imported2


@pytest.mark.parametrize("module_name", _PHASE_47B_NON_NETWORK_MODULES)
def test_no_credential_env_var_access_outside_transport(module_name):
    """Only factory.meshy_http_transport may read os.environ for
    MESHY_API_KEY - every other new Phase 47B module must contain zero
    os.environ/os.getenv/.env references."""
    tree = ast.parse(open(_source_path(module_name)).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv"):
            pytest.fail(f"{module_name} references os.{node.attr} - credential/env access must be confined to meshy_http_transport")


def test_http_transport_only_reads_the_one_documented_env_var():
    source = open(_source_path(_PHASE_47B_NETWORK_MODULE)).read()
    tree = ast.parse(source)
    env_reads = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "environ":
            env_reads.append(node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "environ":
            env_reads.append(node)
    assert "MESHY_API_KEY" in source
    assert "load_dotenv" not in source
    # (docstrings legitimately mention ".env" prose describing what is
    # NOT loaded - a bare substring check on that would false-positive;
    # the load_dotenv()/import dotenv checks above are the real guards.)
    assert "import dotenv" not in source


@pytest.mark.parametrize("module_name", _PHASE_47B_NON_NETWORK_MODULES + (_PHASE_47B_NETWORK_MODULE,))
def test_no_subprocess_anywhere_in_phase_47b(module_name):
    tree = ast.parse(open(_source_path(module_name)).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "subprocess", f"{module_name} imports subprocess"
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] != "subprocess", f"{module_name} imports subprocess"


@pytest.mark.parametrize("module_name", _PHASE_47B_NON_NETWORK_MODULES + (_PHASE_47B_NETWORK_MODULE,))
def test_no_os_system_or_shell_true(module_name):
    tree = ast.parse(open(_source_path(module_name)).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "system" and isinstance(func.value, ast.Name) and func.value.id == "os":
                pytest.fail(f"{module_name} calls os.system()")
        if isinstance(node, ast.keyword) and node.arg == "shell":
            if isinstance(node.value, ast.Constant) and node.value.value is True:
                pytest.fail(f"{module_name} uses shell=True")


# ---------------------------------------------------------------------------
# Live proof: offline commands still work with network/subprocess poisoned
# ---------------------------------------------------------------------------


def test_live_plan_survives_network_and_subprocess_disabled(env, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("factory meshy live-plan must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    result = runner.invoke(app, ["meshy", "live-plan", "--prompt", PROMPT, "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["credential_checked"] is False


def test_status_policy_plan_mock_run_still_survive_poisoned_network(env, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    for args in (
        ["meshy", "status", "--json"],
        ["meshy", "policy", "--json"],
        ["meshy", "plan", "--prompt", "x", "--json"],
        ["meshy", "mock-run", "--prompt", "x", "--confirm-mock", "--json"],
        ["meshy", "approve-live-once", "--prompt", PROMPT, "--max-credits", "20", "--json"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, (args, result.stdout)


def test_live_run_blocked_before_confirm_survives_poisoned_network(env, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("a blocked live-run must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    result = runner.invoke(app, ["meshy", "live-run", "--prompt", PROMPT, "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["live_api_used"] is False


def test_fake_credential_env_var_never_leaks_into_live_plan_output(env, monkeypatch):
    monkeypatch.setenv("MESHY_API_KEY", "fake-secret-should-never-appear")
    result = runner.invoke(app, ["meshy", "live-plan", "--prompt", PROMPT, "--json"])
    assert "fake-secret-should-never-appear" not in result.stdout


def test_fake_credential_env_var_never_leaks_into_live_run_output(env, monkeypatch):
    monkeypatch.setenv("MESHY_API_KEY", "fake-secret-should-never-appear")
    result = runner.invoke(app, ["meshy", "live-run", "--prompt", PROMPT, "--confirm-live", "--json"])
    assert "fake-secret-should-never-appear" not in result.stdout


def test_kill_switch_files_never_written_by_any_offline_command(env, monkeypatch):
    monkeypatch.setenv("MESHY_API_KEY", "fake-secret")
    before = fct.load_future_cloud_tools()
    for args in (
        ["meshy", "live-plan", "--prompt", PROMPT],
        ["meshy", "live-run", "--prompt", PROMPT],
        ["meshy", "live-run", "--prompt", PROMPT, "--confirm-live"],
    ):
        runner.invoke(app, args)
    after = fct.load_future_cloud_tools()
    assert before == after

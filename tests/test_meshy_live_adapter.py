"""Phase 47B tests: `factory.meshy_live_adapter`'s locked live-execution
order, live-plan, and live-run - using ONLY a fake, injected transport
and a fake, injected credential-provider spy. **No test in this file
ever constructs a real `HttpMeshyTransport` or
`LiveMeshyCredentialProvider`, and no test ever touches the real
`MESHY_API_KEY` environment variable or the real network.**
"""

from __future__ import annotations

import copy
import json

import pytest

from factory import future_cloud_tools as fct
from factory import meshy_approval as approval
from factory import meshy_ledger as L
from factory import meshy_live_adapter as la
from factory import meshy_live_approval as A
from factory.meshy_mock_transport import MeshyTransport, MeshyTransportError
from factory.meshy_models import compute_prompt_hash

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
        "provenance_policy_acknowledged": True, "cloud_data_policy_acknowledged": True,
        "execution_enabled": False,  # flipped True in individual tests that need the kill switch enabled
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


def _enable_kill_switch(env):
    policy = json.loads(env["policy_path"].read_text())
    policy["approval"]["execution_enabled"] = True
    env["policy_path"].write_text(json.dumps(policy))
    fct_data = json.loads(env["fct_path"].read_text())
    fct_data["tools"]["meshy"]["enabled"] = True
    env["fct_path"].write_text(json.dumps(fct_data))


def _create_approval(*, max_credits=20, project=None):
    return A.create_one_shot_approval(prompt_hash=compute_prompt_hash(PROMPT), model="meshy-7", max_credits=max_credits, project=project)


class _FakeTransport(MeshyTransport):
    """Never touches a real credential/network. Optionally calls a spy
    credential provider itself (matching HttpMeshyTransport's real
    behavior) so tests can prove *when* the credential is read."""

    def __init__(self, credential_provider=None, *, scenario="success"):
        self._credential_provider = credential_provider
        self.scenario = scenario
        self._polls = 0

    def submit_task(self, request):
        if self._credential_provider is not None:
            self._credential_provider.get_api_key()
        if self.scenario == "submit_fails":
            raise MeshyTransportError("network_error", "simulated submit failure")
        return {"id": "real-fake-task-1", "status": "PENDING", "type": "text-to-3d"}

    def get_task(self, task_id):
        self._polls += 1
        if self.scenario == "task_failed":
            return {"id": task_id, "status": "FAILED", "task_error": {"message": "simulated failure"}}
        if self.scenario == "never_terminal":
            return {"id": task_id, "status": "IN_PROGRESS"}
        if self.scenario == "unrecognized_status":
            return {"id": task_id, "status": "WEIRD_STATUS"}
        return {"id": task_id, "status": "IN_PROGRESS"} if self._polls < 2 else {
            "id": task_id, "status": "SUCCEEDED", "model_urls": {"stl": "https://cdn.example.com/fake.stl"},
            "consumed_credits": 20, "created_at": "1", "started_at": "1", "finished_at": "2",
        }

    def download_artifact(self, model_url, destination):
        from pathlib import Path

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # A minimal, genuinely valid watertight tetrahedron-ish ASCII STL
        # so Factory validation has something real to inspect.
        destination.write_text(
            "solid t\n"
            "facet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\n"
            "facet normal 0 0 -1\nouter loop\nvertex 0 0 0\nvertex 0 1 0\nvertex 1 0 0\nendloop\nendfacet\n"
            "endsolid t\n"
        )
        return destination


class _SpyCredentialProvider:
    def __init__(self):
        self.call_count = 0

    def get_api_key(self):
        self.call_count += 1
        return "fake-key-never-real"


def _no_sleep(seconds):
    return None


# ---------------------------------------------------------------------------
# Live plan - fully offline
# ---------------------------------------------------------------------------


def test_live_plan_never_reads_credential_or_network(env, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("live-plan must never touch network")

    import socket

    monkeypatch.setattr(socket, "socket", _boom)
    plan = la.plan_live_text_to_3d_request(prompt=PROMPT)
    assert plan["credential_checked"] is False
    assert plan["network_used"] is False


def test_live_plan_blocked_without_approval(env):
    plan = la.plan_live_text_to_3d_request(prompt=PROMPT)
    assert plan["every_gate_satisfied"] is False
    assert plan["approval_status"] == "missing"


def test_live_plan_never_consumes_approval(env):
    record = _create_approval()
    la.plan_live_text_to_3d_request(prompt=PROMPT)
    la.plan_live_text_to_3d_request(prompt=PROMPT)
    found = A.find_eligible_approval(prompt_hash=compute_prompt_hash(PROMPT), model="meshy-7", request_type="text_to_3d", max_credits=20, project=None)
    assert found is not None
    assert found["approval_id"] == record["approval_id"]


def test_live_plan_never_reserves_budget(env):
    _create_approval()
    la.plan_live_text_to_3d_request(prompt=PROMPT)
    assert L.SpendLedger().total_today() == 0


def test_live_plan_all_gates_satisfied_when_everything_ready(env):
    _enable_kill_switch(env)
    _create_approval()
    plan = la.plan_live_text_to_3d_request(prompt=PROMPT)
    assert plan["every_gate_satisfied"] is True
    assert plan["blockers"] == []


def test_live_plan_json_clean(env):
    plan = la.plan_live_text_to_3d_request(prompt=PROMPT)
    json.dumps(plan)  # must not raise


# ---------------------------------------------------------------------------
# Locked gate order - credential provider must never be called when any
# of the first 5 gates blocks.
# ---------------------------------------------------------------------------


def test_policy_blocks_credential_never_called(env, monkeypatch):
    policy = json.loads(env["policy_path"].read_text())
    policy["approval"]["approval_scope"] = None
    policy["cost_policy"]["credit_policy"]["max_credits_per_request"] = None
    policy["license_policy"]["terms_reviewed"] = False
    env["policy_path"].write_text(json.dumps(policy))
    _enable_kill_switch(env)
    _create_approval()

    spy = _SpyCredentialProvider()
    result = la.run_live_text_to_3d_request(prompt=PROMPT, project=None, confirm_live=True, credential_provider_factory=lambda: spy, transport_factory=lambda cp: _FakeTransport(cp))
    assert result["errors"][0]["error_code"] == "policy_blocked"
    assert spy.call_count == 0


def test_budget_blocks_credential_never_called(env):
    _enable_kill_switch(env)
    _create_approval(max_credits=1000)  # approval covers it, but the policy cap does not
    policy = json.loads(env["policy_path"].read_text())
    policy["cost_policy"]["credit_policy"]["max_credits_per_request"] = 1  # below the 20-credit estimate
    env["policy_path"].write_text(json.dumps(policy))

    spy = _SpyCredentialProvider()
    result = la.run_live_text_to_3d_request(prompt=PROMPT, confirm_live=True, credential_provider_factory=lambda: spy, transport_factory=lambda cp: _FakeTransport(cp))
    assert result["errors"][0]["error_code"] == "budget_exceeded"
    assert spy.call_count == 0


def test_kill_switch_blocks_credential_never_called(env):
    _create_approval()
    # kill switch left disabled (default env fixture state)
    spy = _SpyCredentialProvider()
    result = la.run_live_text_to_3d_request(prompt=PROMPT, confirm_live=True, credential_provider_factory=lambda: spy, transport_factory=lambda cp: _FakeTransport(cp))
    assert result["errors"][0]["error_code"] == "kill_switch_disabled"
    assert spy.call_count == 0


def test_approval_missing_blocks_credential_never_called(env):
    _enable_kill_switch(env)
    # no approval created
    spy = _SpyCredentialProvider()
    result = la.run_live_text_to_3d_request(prompt=PROMPT, confirm_live=True, credential_provider_factory=lambda: spy, transport_factory=lambda cp: _FakeTransport(cp))
    assert result["errors"][0]["error_code"] == "live_execution_not_approved"
    assert spy.call_count == 0


def test_confirm_live_missing_blocks_credential_never_called(env):
    _enable_kill_switch(env)
    _create_approval()
    spy = _SpyCredentialProvider()
    result = la.run_live_text_to_3d_request(prompt=PROMPT, confirm_live=False, credential_provider_factory=lambda: spy, transport_factory=lambda cp: _FakeTransport(cp))
    assert result["errors"][0]["error_code"] == "live_execution_not_approved"
    assert spy.call_count == 0


def test_all_gates_pass_credential_called_exactly_once(env, tmp_path):
    _enable_kill_switch(env)
    project = tmp_path / "proj"
    project.mkdir()
    _create_approval(project=str(project))
    spy = _SpyCredentialProvider()
    result = la.run_live_text_to_3d_request(
        prompt=PROMPT, project=str(project), confirm_live=True,
        credential_provider_factory=lambda: spy, transport_factory=lambda cp: _FakeTransport(cp), sleep_fn=_no_sleep,
    )
    assert spy.call_count == 1
    assert result["final_status"] == "SUCCEEDED"
    assert result["task_id"] == "real-fake-task-1"


# ---------------------------------------------------------------------------
# One-shot semantics: a second run requires a brand-new approval
# ---------------------------------------------------------------------------


def test_second_run_after_success_requires_new_approval(env, tmp_path):
    _enable_kill_switch(env)
    project = tmp_path / "proj"
    project.mkdir()
    _create_approval(project=str(project))
    la.run_live_text_to_3d_request(prompt=PROMPT, project=str(project), confirm_live=True, credential_provider_factory=lambda: _SpyCredentialProvider(), transport_factory=lambda cp: _FakeTransport(cp), sleep_fn=_no_sleep)

    spy2 = _SpyCredentialProvider()
    result2 = la.run_live_text_to_3d_request(prompt=PROMPT, project=str(project), confirm_live=True, credential_provider_factory=lambda: spy2, transport_factory=lambda cp: _FakeTransport(cp), sleep_fn=_no_sleep)
    assert result2["errors"][0]["error_code"] == "live_execution_not_approved"
    assert spy2.call_count == 0


def test_no_automatic_retry_on_submission_failure(env, tmp_path):
    _enable_kill_switch(env)
    project = tmp_path / "proj"
    project.mkdir()
    _create_approval(project=str(project))
    result = la.run_live_text_to_3d_request(
        prompt=PROMPT, project=str(project), confirm_live=True,
        credential_provider_factory=lambda: _SpyCredentialProvider(),
        transport_factory=lambda cp: _FakeTransport(cp, scenario="submit_fails"), sleep_fn=_no_sleep,
    )
    assert result["automatic_retry_performed"] is False
    assert result["retry_allowed"] is False
    assert L.SpendLedger().total_today() == 20  # reservation retained, not released, despite the failure


def test_task_failed_reports_error_and_retains_reservation(env, tmp_path):
    _enable_kill_switch(env)
    project = tmp_path / "proj"
    project.mkdir()
    _create_approval(project=str(project))
    result = la.run_live_text_to_3d_request(
        prompt=PROMPT, project=str(project), confirm_live=True,
        credential_provider_factory=lambda: _SpyCredentialProvider(),
        transport_factory=lambda cp: _FakeTransport(cp, scenario="task_failed"), sleep_fn=_no_sleep,
    )
    assert result["errors"][0]["error_code"] == "task_failed"
    assert L.SpendLedger().total_today() == 20


def test_polling_timeout_bounded(env, tmp_path, monkeypatch):
    _enable_kill_switch(env)
    project = tmp_path / "proj"
    project.mkdir()
    _create_approval(project=str(project))
    monkeypatch.setattr(la, "POLL_MAX_ATTEMPTS", 2)
    result = la.run_live_text_to_3d_request(
        prompt=PROMPT, project=str(project), confirm_live=True,
        credential_provider_factory=lambda: _SpyCredentialProvider(),
        transport_factory=lambda cp: _FakeTransport(cp, scenario="never_terminal"), sleep_fn=_no_sleep,
    )
    assert result["errors"][0]["error_code"] == "task_timeout"


def test_unrecognized_provider_status_stops(env, tmp_path):
    _enable_kill_switch(env)
    project = tmp_path / "proj"
    project.mkdir()
    _create_approval(project=str(project))
    result = la.run_live_text_to_3d_request(
        prompt=PROMPT, project=str(project), confirm_live=True,
        credential_provider_factory=lambda: _SpyCredentialProvider(),
        transport_factory=lambda cp: _FakeTransport(cp, scenario="unrecognized_status"), sleep_fn=_no_sleep,
    )
    assert "unknown_provider_status" in result["errors"][0]["message"]


def test_missing_project_blocks_persistence_on_success(env):
    _enable_kill_switch(env)
    _create_approval(project=None)
    result = la.run_live_text_to_3d_request(
        prompt=PROMPT, project=None, confirm_live=True,
        credential_provider_factory=lambda: _SpyCredentialProvider(),
        transport_factory=lambda cp: _FakeTransport(cp), sleep_fn=_no_sleep,
    )
    assert result["final_status"] == "SUCCEEDED"
    assert result["receipt"] is None
    assert any(e["error_code"] == "invalid_request" for e in result["errors"])


def test_never_overwrites_existing_artifact(env, tmp_path):
    _enable_kill_switch(env)
    project = tmp_path / "proj"
    project.mkdir()
    existing = project / "generated" / "meshy" / "raw" / "real-fake-task-1.stl"
    existing.parent.mkdir(parents=True)
    existing.write_text("pre-existing content")
    _create_approval(project=str(project))
    result = la.run_live_text_to_3d_request(
        prompt=PROMPT, project=str(project), confirm_live=True,
        credential_provider_factory=lambda: _SpyCredentialProvider(),
        transport_factory=lambda cp: _FakeTransport(cp), sleep_fn=_no_sleep,
    )
    assert any(e["error_code"] == "invalid_request" for e in result["errors"])
    assert existing.read_text() == "pre-existing content"


def test_receipt_never_contains_mock_execution_true(env, tmp_path):
    _enable_kill_switch(env)
    project = tmp_path / "proj"
    project.mkdir()
    _create_approval(project=str(project))
    result = la.run_live_text_to_3d_request(
        prompt=PROMPT, project=str(project), confirm_live=True,
        credential_provider_factory=lambda: _SpyCredentialProvider(),
        transport_factory=lambda cp: _FakeTransport(cp), sleep_fn=_no_sleep,
    )
    assert result["receipt"]["mock_execution"] is False
    assert result["receipt"]["live_api_used"] is True
    assert result["receipt"]["automatic_print_allowed"] is False


def test_fake_credential_never_leaks_into_result(env, tmp_path):
    _enable_kill_switch(env)
    project = tmp_path / "proj"
    project.mkdir()
    _create_approval(project=str(project))
    result = la.run_live_text_to_3d_request(
        prompt=PROMPT, project=str(project), confirm_live=True,
        credential_provider_factory=lambda: _SpyCredentialProvider(),
        transport_factory=lambda cp: _FakeTransport(cp), sleep_fn=_no_sleep,
    )
    assert "fake-key-never-real" not in json.dumps(result, default=str)


def test_kill_switch_reads_raw_policy_field_not_hardcoded_gate_value(env):
    """factory.meshy_approval.evaluate_meshy_gate() hardcodes
    kill_switch.execution_enabled=False always - this module must read
    the raw config/meshy_policy.json value directly, or it could never
    observe a human manually flipping it."""
    _enable_kill_switch(env)
    state = la.check_kill_switch()
    assert state["policy_execution_enabled"] is True
    assert state["future_cloud_tools_enabled"] is True
    assert state["both_enabled"] is True

    gate = approval.evaluate_meshy_gate()
    assert gate["kill_switch"]["execution_enabled"] is False  # Phase 46's own hardcoded invariant, unchanged

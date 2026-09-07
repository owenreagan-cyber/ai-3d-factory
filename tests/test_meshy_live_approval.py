"""Phase 47B tests: `factory.meshy_live_approval`'s one-shot live-call
approval records. Every test isolates `APPROVAL_PATH` to a `tmp_path`
location - never the real `state/meshy_live_approvals.json`. See
docs/meshy-live-transport.md "One-shot approval".
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from factory import meshy_live_approval as A


@pytest.fixture
def approval_path(tmp_path, monkeypatch):
    path = tmp_path / "approvals.json"
    monkeypatch.setattr(A, "APPROVAL_PATH", path)
    import factory.meshy_ledger as L

    monkeypatch.setattr(L, "_LOCK_PATH", tmp_path / "ledger.lock")
    return path


def test_create_and_find_eligible(approval_path):
    A.create_one_shot_approval(prompt_hash="abc", model="meshy-7", max_credits=20, project=None)
    found = A.find_eligible_approval(prompt_hash="abc", model="meshy-7", request_type="text_to_3d", max_credits=20, project=None)
    assert found is not None
    assert found["status"] == "armed"


def test_wrong_prompt_hash_not_eligible(approval_path):
    A.create_one_shot_approval(prompt_hash="abc", model="meshy-7", max_credits=20, project=None)
    found = A.find_eligible_approval(prompt_hash="different", model="meshy-7", request_type="text_to_3d", max_credits=20, project=None)
    assert found is None


def test_wrong_model_not_eligible(approval_path):
    A.create_one_shot_approval(prompt_hash="abc", model="meshy-7", max_credits=20, project=None)
    found = A.find_eligible_approval(prompt_hash="abc", model="meshy-6", request_type="text_to_3d", max_credits=20, project=None)
    assert found is None


def test_credit_cap_must_cover_estimate(approval_path):
    A.create_one_shot_approval(prompt_hash="abc", model="meshy-7", max_credits=20, project=None)
    assert A.find_eligible_approval(prompt_hash="abc", model="meshy-7", request_type="text_to_3d", max_credits=25, project=None) is None
    assert A.find_eligible_approval(prompt_hash="abc", model="meshy-7", request_type="text_to_3d", max_credits=20, project=None) is not None
    assert A.find_eligible_approval(prompt_hash="abc", model="meshy-7", request_type="text_to_3d", max_credits=15, project=None) is not None


def test_expiry(approval_path):
    record = A.create_one_shot_approval(prompt_hash="abc", model="meshy-7", max_credits=20, project=None, expires_in_seconds=60)
    data = json.loads(approval_path.read_text())
    data["approvals"][0]["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    approval_path.write_text(json.dumps(data))
    found = A.find_eligible_approval(prompt_hash="abc", model="meshy-7", request_type="text_to_3d", max_credits=20, project=None)
    assert found is None


def test_consumption(approval_path):
    record = A.create_one_shot_approval(prompt_hash="abc", model="meshy-7", max_credits=20, project=None)
    consumed = A.consume_approval(record["approval_id"])
    assert consumed["status"] == "consumed"
    assert consumed["consumed_at"] is not None


def test_second_use_blocked_after_consumption(approval_path):
    record = A.create_one_shot_approval(prompt_hash="abc", model="meshy-7", max_credits=20, project=None)
    A.consume_approval(record["approval_id"])
    assert A.find_eligible_approval(prompt_hash="abc", model="meshy-7", request_type="text_to_3d", max_credits=20, project=None) is None
    with pytest.raises(A.ApprovalError):
        A.consume_approval(record["approval_id"])


def test_revocation(approval_path):
    record = A.create_one_shot_approval(prompt_hash="abc", model="meshy-7", max_credits=20, project=None)
    A.revoke_approval(record["approval_id"], reason="changed my mind")
    assert A.find_eligible_approval(prompt_hash="abc", model="meshy-7", request_type="text_to_3d", max_credits=20, project=None) is None
    data = json.loads(approval_path.read_text())
    assert data["approvals"][0]["status"] == "revoked"
    assert data["approvals"][0]["revocation_reason"] == "changed my mind"


def test_project_pinning(approval_path):
    A.create_one_shot_approval(prompt_hash="abc", model="meshy-7", max_credits=20, project="projects/a")
    assert A.find_eligible_approval(prompt_hash="abc", model="meshy-7", request_type="text_to_3d", max_credits=20, project="projects/a") is not None
    assert A.find_eligible_approval(prompt_hash="abc", model="meshy-7", request_type="text_to_3d", max_credits=20, project="projects/b") is None
    assert A.find_eligible_approval(prompt_hash="abc", model="meshy-7", request_type="text_to_3d", max_credits=20, project=None) is None


def test_approval_absent_returns_none(approval_path):
    assert A.find_eligible_approval(prompt_hash="abc", model="meshy-7", request_type="text_to_3d", max_credits=20, project=None) is None


def test_malformed_approval_file_fails_closed(approval_path):
    approval_path.write_text("{ not valid json")
    with pytest.raises(Exception):
        A.find_eligible_approval(prompt_hash="abc", model="meshy-7", request_type="text_to_3d", max_credits=20, project=None)


def test_non_positive_max_credits_rejected(approval_path):
    with pytest.raises(A.ApprovalError):
        A.create_one_shot_approval(prompt_hash="abc", model="meshy-7", max_credits=0, project=None)
    with pytest.raises(A.ApprovalError):
        A.create_one_shot_approval(prompt_hash="abc", model="meshy-7", max_credits=-5, project=None)


def test_expires_in_bounded(approval_path):
    with pytest.raises(A.ApprovalError):
        A.create_one_shot_approval(prompt_hash="abc", model="meshy-7", max_credits=20, project=None, expires_in_seconds=999999)
    with pytest.raises(A.ApprovalError):
        A.create_one_shot_approval(prompt_hash="abc", model="meshy-7", max_credits=20, project=None, expires_in_seconds=0)


def test_approval_id_namespaced(approval_path):
    record = A.create_one_shot_approval(prompt_hash="abc", model="meshy-7", max_credits=20, project=None)
    assert record["approval_id"].startswith("meshy-approval-")


def test_never_auto_created_by_load(approval_path):
    """Merely calling load_approvals()/find_eligible_approval() must never
    create a record."""
    A.find_eligible_approval(prompt_hash="abc", model="meshy-7", request_type="text_to_3d", max_credits=20, project=None)
    assert not approval_path.exists()

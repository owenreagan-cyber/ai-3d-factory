"""Phase 47B tests: `factory.meshy_ledger`'s persistent spend ledger.

Every test isolates `LEDGER_PATH`/`_LOCK_PATH` to a `tmp_path` location -
never the real `state/meshy_spend_ledger.json`. See
docs/meshy-live-transport.md "Persistent budget ledger".
"""

from __future__ import annotations

import json

import pytest

from factory import meshy_ledger as L


@pytest.fixture
def ledger_path(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    monkeypatch.setattr(L, "LEDGER_PATH", path)
    monkeypatch.setattr(L, "_LOCK_PATH", tmp_path / "ledger.lock")
    return path


def test_reservation_before_any_network_call(ledger_path):
    """Reserving must not require a task_id yet - it happens before submission."""
    ledger = L.SpendLedger()
    entry = ledger.reserve(request_id="r1", project=None, request_type="text_to_3d", model="meshy-7", estimated_credits=20, policy_version=1, approval_reference="a1")
    assert entry["status"] == "reserved"
    assert entry["task_id"] is None
    assert entry["actual_credits"] is None


def test_reservation_counts_toward_totals_immediately(ledger_path):
    ledger = L.SpendLedger()
    ledger.reserve(request_id="r1", project="proj-a", request_type="text_to_3d", model="meshy-7", estimated_credits=20, policy_version=1, approval_reference="a1")
    assert ledger.total_for_project("proj-a") == 20
    assert ledger.total_today() == 20
    assert ledger.total_this_month() == 20


def test_reconciliation_updates_actual_credits(ledger_path):
    ledger = L.SpendLedger()
    entry = ledger.reserve(request_id="r1", project=None, request_type="text_to_3d", model="meshy-7", estimated_credits=20, policy_version=1, approval_reference="a1")
    ledger.mark_submitted(entry["reservation_id"], task_id="task-1")
    ledger.mark_succeeded(entry["reservation_id"], actual_credits=18)
    assert ledger.total_today() == 18


def test_unknown_outcome_retains_full_estimated_reservation(ledger_path):
    """A failure with unknown credit consumption must NOT release the
    reservation - it stays counted at the original estimate."""
    ledger = L.SpendLedger()
    entry = ledger.reserve(request_id="r1", project=None, request_type="text_to_3d", model="meshy-7", estimated_credits=20, policy_version=1, approval_reference="a1")
    ledger.mark_submitted(entry["reservation_id"], task_id="task-1")
    ledger.mark_unknown(entry["reservation_id"], reason="network error mid-poll")
    assert ledger.total_today() == 20
    entries = ledger._entries()
    assert entries[0]["status"] == "unknown"


def test_per_project_cap_isolated_from_other_projects(ledger_path):
    ledger = L.SpendLedger()
    ledger.reserve(request_id="r1", project="proj-a", request_type="text_to_3d", model="meshy-7", estimated_credits=20, policy_version=1, approval_reference="a1")
    ledger.reserve(request_id="r2", project="proj-b", request_type="text_to_3d", model="meshy-7", estimated_credits=30, policy_version=1, approval_reference="a2")
    assert ledger.total_for_project("proj-a") == 20
    assert ledger.total_for_project("proj-b") == 30
    assert ledger.total_today() == 50  # global total spans all projects


def test_daily_total_excludes_entries_from_other_days(ledger_path):
    ledger = L.SpendLedger()
    entry = ledger.reserve(request_id="r1", project=None, request_type="text_to_3d", model="meshy-7", estimated_credits=20, policy_version=1, approval_reference="a1")
    data = json.loads(ledger_path.read_text())
    data["entries"][0]["timestamp"] = "2020-01-01T00:00:00+00:00"
    ledger_path.write_text(json.dumps(data))
    assert ledger.total_today() == 0
    assert ledger.total_this_month() == 0


def test_atomic_write_leaves_no_temp_file_behind(ledger_path):
    ledger = L.SpendLedger()
    ledger.reserve(request_id="r1", project=None, request_type="text_to_3d", model="meshy-7", estimated_credits=20, policy_version=1, approval_reference="a1")
    leftovers = list(ledger_path.parent.glob("*.tmp-*"))
    assert leftovers == []


def test_corrupt_ledger_fails_closed(ledger_path):
    ledger_path.write_text("{ not valid json")
    ledger = L.SpendLedger()
    with pytest.raises(L.LedgerCorruptedError):
        ledger.total_today()


def test_missing_entries_key_fails_closed(ledger_path):
    ledger_path.write_text(json.dumps({"not_entries": []}))
    ledger = L.SpendLedger()
    with pytest.raises(L.LedgerCorruptedError):
        ledger.total_today()


def test_missing_ledger_file_starts_empty(ledger_path):
    ledger = L.SpendLedger()
    assert ledger.total_today() == 0


def test_update_unknown_reservation_id_raises(ledger_path):
    ledger = L.SpendLedger()
    with pytest.raises(L.LedgerError):
        ledger.mark_submitted("does-not-exist", task_id="x")


def test_concurrent_reservations_do_not_lose_updates(ledger_path):
    """Simulates two 'overlapping' reservations by performing them
    sequentially through separate SpendLedger instances (the realistic
    single-process/CLI-invocation scenario) - both must be present and
    correctly totaled afterward, proving the lock+atomic-write path
    doesn't silently drop a concurrent-looking write."""
    ledger_a = L.SpendLedger()
    ledger_b = L.SpendLedger()
    entry_a = ledger_a.reserve(request_id="r1", project=None, request_type="text_to_3d", model="meshy-7", estimated_credits=20, policy_version=1, approval_reference="a1")
    entry_b = ledger_b.reserve(request_id="r2", project=None, request_type="text_to_3d", model="meshy-7", estimated_credits=15, policy_version=1, approval_reference="a2")
    assert ledger_a.total_today() == 35
    assert entry_a["reservation_id"] != entry_b["reservation_id"]


def test_lock_failure_raises_ledger_lock_error(ledger_path, monkeypatch):
    def _boom_flock(*a, **k):
        raise OSError("simulated lock contention")

    import fcntl

    monkeypatch.setattr(fcntl, "flock", _boom_flock)
    ledger = L.SpendLedger()
    with pytest.raises(L.LedgerLockError):
        ledger.reserve(request_id="r1", project=None, request_type="text_to_3d", model="meshy-7", estimated_credits=20, policy_version=1, approval_reference="a1")

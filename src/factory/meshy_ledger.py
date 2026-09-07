"""Phase 47B: persistent local Meshy spend ledger.

**This module never contacts a network, never reads a credential, and
never spends anything itself** - it only tracks, locally, what a real
live call has (or may have) cost, so `factory.meshy_live_adapter` can
enforce `config/meshy_policy.json`'s real credit caps across process
restarts (Phase 47A's `factory.meshy_adapter.InMemoryCreditLedger` only
ever tracked one process's lifetime - deliberately, per that phase's own
spec - so it cannot enforce a real `daily_cap`/`monthly_cap` on its own).

Design source: `docs/meshy-live-readiness.md` sections 11-13. Stored at
`state/meshy_spend_ledger.json` - machine-local, gitignored (see
`.gitignore`), never `config/` (committed, non-secret *policy*, not
runtime spend history) and never inside a project's own `generated/`
directory (caps are Factory-wide across every project).

**Reservation, never deletion:** a reservation is written *before* any
network call is attempted and is never removed - only ever transitioned
to `submitted` -> `succeeded` or `unknown` (a genuinely uncertain
outcome, e.g. a network error mid-poll). There is deliberately no
"release"/delete path in this phase: `docs/meshy-live-readiness.md`
section 12 requires an unknown-outcome failure "must never silently
disappear from the ledger" - an under-counted ledger is exactly how an
accidental over-cap spend could happen on a later run.

`SpendLedger` exposes the same `total_for_project()`/`total_today()`/
`total_this_month()` duck-typed interface Phase 47A's
`InMemoryCreditLedger` already established, so
`factory.meshy_adapter.check_budget()` enforces caps against this
*persistent* ledger with zero duplicated budget logic - the exact same
function, just given a different ledger object.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from factory import project_store

LEDGER_PATH = project_store.STATE_DIR / "meshy_spend_ledger.json"
_LOCK_PATH = project_store.STATE_DIR / "meshy_spend_ledger.lock"

LEDGER_STATUSES = ("reserved", "submitted", "succeeded", "failed", "unknown", "confirmed_zero_rejected_before_submission")


class LedgerError(Exception):
    """Raised for any ledger failure a caller must treat as blocking
    (never as "proceed with an empty/best-effort ledger")."""


class LedgerCorruptedError(LedgerError):
    """The ledger file exists but is not valid JSON / not the expected
    shape. Fail closed: callers must treat this as `budget_exceeded`,
    never as "no prior spend"."""


class LedgerLockError(LedgerError):
    """A concurrent writer could not be excluded. Fail closed - the
    caller must stop rather than risk a lost-update race on the caps
    this ledger exists to enforce."""


def _atomic_write_json(path: Path, data: Any) -> None:
    """Temp-file-then-`os.replace()` - the same atomicity guarantee
    `docs/meshy-live-readiness.md` section 13 recommends. `os.replace()`
    is atomic on POSIX and Windows alike; a crash mid-write leaves either
    the old file or nothing renamed yet, never a half-written one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + f".tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp_path, path)


@contextmanager
def _locked() -> Iterator[None]:
    """Advisory file lock guarding read-modify-write ledger updates.
    Fails closed: if `fcntl` isn't available (non-POSIX) or the lock
    can't be acquired, raise rather than proceed unlocked - cheap
    insurance against the reservation race
    `docs/meshy-live-readiness.md` section 12/13 calls out, never load-
    bearing for this phase's own single-process CLI invocations (a
    one-shot approval already prevents a *meaningful* concurrent-`live-run`
    attack surface)."""
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl
    except ImportError as exc:  # pragma: no cover - POSIX-only dev/CI environment
        raise LedgerLockError(f"file locking unavailable on this platform: {exc}") from exc

    with open(_LOCK_PATH, "w") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise LedgerLockError(f"could not acquire the ledger lock: {exc}") from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def _load_raw() -> dict[str, Any]:
    if not LEDGER_PATH.is_file():
        return {"entries": []}
    try:
        data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LedgerCorruptedError(f"{LEDGER_PATH} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise LedgerCorruptedError(f"{LEDGER_PATH} is missing the expected top-level 'entries' list")
    return data


class SpendLedger:
    """Persistent, local, append-preserving credit ledger. Every method
    either reads the current on-disk state fresh or performs one locked
    read-modify-write - never caches across calls, so a second process
    (or a second `SpendLedger()` in the same process) always sees the
    latest reservations."""

    def _entries(self) -> list[dict[str, Any]]:
        return _load_raw()["entries"]

    def _spent(self, *, project: str | None, since: datetime | None = None, granularity: str | None = None) -> int:
        total = 0
        for entry in self._entries():
            if project is not None and entry.get("project") != project:
                continue
            if since is not None or granularity is not None:
                ts = entry.get("timestamp")
                if not ts:
                    continue
                entry_dt = datetime.fromisoformat(ts)
                now = datetime.now(timezone.utc)
                if granularity == "day" and entry_dt.date() != now.date():
                    continue
                if granularity == "month" and (entry_dt.year, entry_dt.month) != (now.year, now.month):
                    continue
            credits = entry.get("actual_credits")
            if credits is None:
                credits = entry.get("estimated_credits")
            total += credits or 0
        return total

    # Duck-typed to match factory.meshy_adapter.InMemoryCreditLedger so
    # check_budget() works against either unchanged.
    def total_for_project(self, project_id: str | None) -> int:
        return self._spent(project=project_id)

    def total_today(self) -> int:
        return self._spent(project=None, granularity="day")

    def total_this_month(self) -> int:
        return self._spent(project=None, granularity="month")

    def reserve(
        self, *, request_id: str, project: str | None, request_type: str, model: str,
        estimated_credits: int, policy_version: int, approval_reference: str,
    ) -> dict[str, Any]:
        """Step 2 of the reserve-before-submit sequence
        (`docs/meshy-live-readiness.md` section 12) - written *before*
        any network call. Returns the new entry (with its
        `reservation_id`)."""
        entry = {
            "reservation_id": f"meshy-ledger-{uuid.uuid4()}",
            "request_id": request_id,
            "task_id": None,
            "project": project,
            "timestamp": project_store.utc_now_iso(),
            "request_type": request_type,
            "model": model,
            "estimated_credits": estimated_credits,
            "actual_credits": None,
            "status": "reserved",
            "policy_version": policy_version,
            "approval_reference": approval_reference,
        }
        with _locked():
            data = _load_raw()
            data["entries"].append(entry)
            _atomic_write_json(LEDGER_PATH, data)
        return entry

    def _update(self, reservation_id: str, **fields: Any) -> dict[str, Any]:
        with _locked():
            data = _load_raw()
            for entry in data["entries"]:
                if entry.get("reservation_id") == reservation_id:
                    entry.update(fields)
                    _atomic_write_json(LEDGER_PATH, data)
                    return entry
        raise LedgerError(f"no ledger entry with reservation_id={reservation_id!r}")

    def mark_submitted(self, reservation_id: str, *, task_id: str) -> dict[str, Any]:
        return self._update(reservation_id, status="submitted", task_id=task_id)

    def mark_succeeded(self, reservation_id: str, *, actual_credits: int | None) -> dict[str, Any]:
        return self._update(reservation_id, status="succeeded", actual_credits=actual_credits)

    def mark_unknown(self, reservation_id: str, *, reason: str) -> dict[str, Any]:
        """Terminal-but-uncertain outcome (task FAILED/CANCELED/timed out,
        or a network error mid-poll/download). Never `"failed"` with the
        reservation removed - the estimated credits stay counted in every
        total until a human manually reconciles the entry, per section 12's
        "retain reservation conservatively" rule (this repo has no
        confirmed answer for whether Meshy bills failed tasks - see the
        Phase 46.6/47A.5 "9 unknowns" #1)."""
        return self._update(reservation_id, status="unknown", **{"unknown_reason": reason})

    def reconcile_rejected_before_submission(self, reservation_id: str, *, reason: str) -> dict[str, Any]:
        """Explicit, human-invoked reconciliation (Phase 47B.7) for an
        `"unknown"` entry that can be positively confirmed to have consumed
        zero credits - e.g. an HTTP 401/403 credential rejection, which
        Meshy's auth layer returns before any task is created
        (`HttpMeshyTransport.submit_task()` only returns a task id after a
        2xx response with a `result` field - see `factory.meshy_http_transport`).

        Refuses to reconcile an entry that isn't currently `"unknown"`, or
        that carries a `task_id` (any evidence a task may actually have
        been created) - this is a narrow, auditable state transition, never
        a silent rewrite: the original `timestamp`/`unknown_reason` are
        preserved untouched, and `reconciled_at`/`reconciled_reason` are
        added alongside them so the full history remains visible."""
        entries = self._entries()
        entry = next((e for e in entries if e.get("reservation_id") == reservation_id), None)
        if entry is None:
            raise LedgerError(f"no ledger entry with reservation_id={reservation_id!r}")
        if entry.get("status") != "unknown":
            raise LedgerError(
                f"reservation {reservation_id!r} is not in 'unknown' status (status={entry.get('status')!r}) - refusing to reconcile"
            )
        if entry.get("task_id"):
            raise LedgerError(
                f"reservation {reservation_id!r} has a task_id ({entry['task_id']!r}) - a task may have been "
                "created, refusing to reconcile as zero-cost"
            )
        return self._update(
            reservation_id,
            status="confirmed_zero_rejected_before_submission",
            actual_credits=0,
            reconciled_at=project_store.utc_now_iso(),
            reconciled_reason=reason,
        )

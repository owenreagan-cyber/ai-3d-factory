"""Phase 47B: one-shot live-call approval records.

**This module never contacts Meshy, never reads a credential, and never
enables execution by itself.** Recording an approval here is *not*
blanket "live Meshy execution is now permitted forever" - it is a single,
narrowly-scoped, single-use permission slip for exactly one future
`live-run` invocation, matching the exact prompt/model/credit-cap (and
optionally project) it was created for. See
`docs/meshy-live-readiness.md` section 15.

Stored at `state/meshy_live_approvals.json` - machine-local, gitignored,
alongside `factory.meshy_ledger`'s spend ledger (same directory, same
atomic-write/lock helpers, reused rather than duplicated).

Consuming an approval and reserving ledger credits are the two halves of
"the first submission attempt" (`docs/meshy-live-readiness.md` section
15) - `factory.meshy_live_adapter` performs both, back-to-back, each
individually atomic (this repo does not implement true cross-file
transactions across two separate JSON files; see
`docs/meshy-live-transport.md` "Limitations").
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from factory import project_store
from factory.meshy_ledger import LedgerCorruptedError, _atomic_write_json, _locked

APPROVAL_PATH = project_store.STATE_DIR / "meshy_live_approvals.json"

# "created" is folded into "armed" (there is no meaningful gap between
# "a human ran approve-live-once" and "this approval is now eligible for
# one live-run") - both remain in the vocabulary per
# docs/meshy-live-readiness.md section 15's suggested set, but this
# module only ever writes "armed" as the initial status.
APPROVAL_STATUSES = ("created", "armed", "consumed", "expired", "revoked")

APPROVAL_SCOPES = ("first_live_call",)

_DEFAULT_EXPIRES_IN_SECONDS = 3600
_MAX_EXPIRES_IN_SECONDS = 24 * 3600  # a bounded ceiling - "short-lived", never indefinite


class ApprovalError(Exception):
    pass


def _load_raw() -> dict[str, Any]:
    if not APPROVAL_PATH.is_file():
        return {"approvals": []}
    try:
        data = json.loads(APPROVAL_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LedgerCorruptedError(f"{APPROVAL_PATH} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("approvals"), list):
        raise LedgerCorruptedError(f"{APPROVAL_PATH} is missing the expected top-level 'approvals' list")
    return data


def load_approvals() -> list[dict[str, Any]]:
    """Fail-closed: a corrupted approval file raises rather than silently
    returning an empty list (which would look identical to "no approval
    recorded yet" and could mask a real, already-consumed approval)."""
    return _load_raw()["approvals"]


def create_one_shot_approval(
    *, prompt_hash: str, model: str, max_credits: int, request_type: str = "text_to_3d",
    project: str | None = None, expires_in_seconds: int = _DEFAULT_EXPIRES_IN_SECONDS,
) -> dict[str, Any]:
    """Explicit, human-invoked write (`factory meshy approve-live-once`).
    Never auto-created by any plan/status/run command. `expires_in_seconds`
    is clamped to `_MAX_EXPIRES_IN_SECONDS` - "short-lived", never a
    de-facto permanent grant."""
    if not (0 < expires_in_seconds <= _MAX_EXPIRES_IN_SECONDS):
        raise ApprovalError(f"expires_in_seconds must be between 1 and {_MAX_EXPIRES_IN_SECONDS} (24h), got {expires_in_seconds}")
    if max_credits <= 0:
        raise ApprovalError(f"max_credits must be positive, got {max_credits}")

    now = datetime.now(timezone.utc)
    record = {
        "approval_id": f"meshy-approval-{uuid.uuid4()}",
        "scope": "first_live_call",
        "prompt_hash": prompt_hash,
        "model": model,
        "max_credits": max_credits,
        "request_type": request_type,
        "project": project,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=expires_in_seconds)).isoformat(),
        "consumed_at": None,
        "status": "armed",
    }
    with _locked():
        data = _load_raw()
        data["approvals"].append(record)
        _atomic_write_json(APPROVAL_PATH, data)
    return record


def _is_eligible(record: dict[str, Any], *, now: datetime) -> bool:
    if record.get("status") != "armed":
        return False
    if record.get("consumed_at"):
        return False
    expires_at = record.get("expires_at")
    if expires_at and datetime.fromisoformat(expires_at) <= now:
        return False
    return True


def find_eligible_approval(
    *, prompt_hash: str, model: str, request_type: str, max_credits: int, project: str | None,
) -> dict[str, Any] | None:
    """Read-only lookup - never consumes, never mutates. Matches on every
    pinned field (prompt hash, model, request type, project) and requires
    the approval's own `max_credits` be `>= max_credits` (the estimated
    cost of the request being planned/run) - an approval is scoped to "at
    most this many credits", not "exactly these many"."""
    now = datetime.now(timezone.utc)
    for record in load_approvals():
        if not _is_eligible(record, now=now):
            continue
        if record.get("prompt_hash") != prompt_hash:
            continue
        if record.get("model") != model:
            continue
        if record.get("request_type") != request_type:
            continue
        if record.get("project") != project:
            continue
        if (record.get("max_credits") or 0) < max_credits:
            continue
        return record
    return None


def consume_approval(approval_id: str) -> dict[str, Any]:
    """Explicit, single-use write - performed only at step 7 of the
    locked live-execution order (`factory.meshy_live_adapter`), in the
    same code path (though a separate atomic file) as the ledger
    reservation. Raises if the approval no longer exists or is no longer
    `armed` - never silently re-consumes."""
    with _locked():
        data = _load_raw()
        for record in data["approvals"]:
            if record.get("approval_id") == approval_id:
                if record.get("status") != "armed" or record.get("consumed_at"):
                    raise ApprovalError(f"approval {approval_id!r} is not eligible for consumption (status={record.get('status')!r})")
                record["status"] = "consumed"
                record["consumed_at"] = project_store.utc_now_iso()
                _atomic_write_json(APPROVAL_PATH, data)
                return record
    raise ApprovalError(f"no approval with approval_id={approval_id!r}")


def revoke_approval(approval_id: str, *, reason: str | None = None) -> dict[str, Any]:
    """Explicit, human-invoked write. Local file only - no network, no
    remote revocation."""
    with _locked():
        data = _load_raw()
        for record in data["approvals"]:
            if record.get("approval_id") == approval_id:
                record["status"] = "revoked"
                record.setdefault("revocation_reason", reason)
                _atomic_write_json(APPROVAL_PATH, data)
                return record
    raise ApprovalError(f"no approval with approval_id={approval_id!r}")

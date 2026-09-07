"""Phase 47A: Mocked Meshy Adapter & API Contract.

**This module never contacts Meshy or any network endpoint, never reads
or validates a credential, never spends money or credits, and never
enables live execution.** It proves the *architecture* a future,
separately-approved Phase 47B would need - request planning, policy/
budget gating, an asynchronous task lifecycle, provenance, a receipt, and
a validation/preview handoff - entirely against `MockMeshyTransport`
(`factory.meshy_mock_transport`).

    Policy Approved -> Mocked Adapter -> Mocked Request Planning ->
    Mocked Task Lifecycle -> Mocked Artifact Retrieval ->
    Factory Validation -> Factory Preview -> Human Review ->
    47A Review -> Separate 47B Approval -> One Controlled Real API Call

This module reaches, at most, the "Mocked Artifact Retrieval" /
"Factory Validation" / "Factory Preview" stages - never further.
`live_execution_allowed` is hardcoded `False` on every result this module
returns, with no code path that ever sets it `True`; the same is true of
`config/future_cloud_tools.json`'s Meshy kill switch, which this module
reads but never writes.

Reuses rather than duplicates:

- `factory.meshy_approval.evaluate_meshy_gate()`/`load_meshy_policy()`
  (Phase 46) - the actual policy/approval/cost-cap gate. This module
  never re-implements policy evaluation; it only adds one more gate
  concept on top (`mock_execution_allowed` vs. `live_execution_allowed`
  - see `check_policy_gate()` below), which Phase 46 itself does not
  need to know about.
- `factory.meshy_models` (this phase) - the request/response/task-state
  vocabulary, grounded in `docs/meshy-current-research.md`.
- `factory.meshy_mock_transport.MockMeshyTransport` (this phase) - the
  only transport implementation; no real HTTP client is imported
  anywhere in this module.
- `factory.validators.mesh_validate.validate_mesh()` - the same Factory
  mesh validator every other phase's generated/exported mesh goes
  through. No Meshy-specific validator exists or is added here. A mock
  response's own `meshy_printability_claim` field (if present) is never
  read by this module for validation purposes - see
  `tests/test_meshy_adapter.py::test_mock_printable_claim_does_not_bypass_factory_validation`.
- `factory.previews.render_preview.render_preview()` - the same local
  preview renderer `factory blender qualify`/`factory render` already
  use. No Meshy-specific preview/visual-QA subsystem exists or is added
  here.

No credential is read anywhere in this module - there is no
`os.environ.get("MESHY_API_KEY")` (or similar) call, no `.env` load, and
no `LiveMeshyCredentialProvider` (it does not exist; Phase 47B would add
one later). No `subprocess` call exists in this module or anything it
imports for Meshy purposes. See `docs/meshy-adapter.md`.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

from factory import meshy_approval, project_store
from factory.meshy_mock_transport import MeshyTransportError, MockMeshyTransport
from factory.meshy_models import (
    DEFAULT_AI_MODEL,
    build_text_to_3d_request,
    check_prompt_privacy_hook,
)
from factory.previews.render_preview import render_preview
from factory.validators.mesh_validate import validate_mesh

MESHY_ADAPTER_VERSION = 1

# Bounded polling - the mock transport never sleeps and never takes real
# time, but the *bound* itself matters: it proves the adapter cannot spin
# forever even against a well-behaved mocked "still processing" response,
# matching the "no automatic retry"/"no unbounded polling" design
# principle a future real transport would also need.
_MAX_MOCK_POLLS = 5

_SAFETY_BLOCK: dict[str, Any] = {
    "network_used": False,
    "credentials_read": False,
    "meshy_api_calls": 0,
    "credits_spent": 0,
    "money_spent": 0,
    "live_transport_implemented": False,
    "live_execution_allowed": False,
    "automatic_print_allowed": False,
}


# ---------------------------------------------------------------------------
# Policy gate - one more concept layered on top of Phase 46's own gate
# ---------------------------------------------------------------------------


def check_policy_gate() -> dict[str, Any]:
    """Joins Phase 46's `evaluate_meshy_gate()` with the mock-vs-live
    distinction this phase's spec requires be kept explicit and never
    collapsed into one boolean: `mock_execution_allowed` tracks whether
    the Phase 46 policy has been approved (mocked execution needs a
    reviewed, approved policy to exercise real budget/policy logic
    meaningfully); `live_execution_allowed` is hardcoded `False` - no
    combination of policy state in this repo can ever set it `True`."""
    gate = meshy_approval.evaluate_meshy_gate()
    policy_approved = gate["gate_status"] == "approved_for_future_api_integration"

    blockers = list(gate["blockers"])
    if not policy_approved:
        blockers.append(
            "Meshy policy is not approved_for_future_api_integration - run `factory meshy approval-plan` "
            "then `factory meshy approve-policy` after reviewing cost/license policy."
        )

    return {
        "policy_approved": policy_approved,
        "policy_gate_status": gate["gate_status"],
        "mock_execution_allowed": policy_approved,
        "live_execution_allowed": False,
        "kill_switch_enabled": gate["kill_switch"]["enabled"],
        "blockers": blockers,
    }


# ---------------------------------------------------------------------------
# Budget check + in-memory credit ledger
# ---------------------------------------------------------------------------


class InMemoryCreditLedger:
    """A future-safe credit-ledger shape (`request_id`/`task_id`/
    `estimated_credits`/`actual_credits`/`project_id`/`timestamp`/
    `status`), kept entirely in memory. Per the spec: "Phase 47A should
    use a mocked/in-memory ledger unless persistence is clearly
    required... Prefer no persistence in 47A." This ledger's lifetime is
    exactly one Python process/CLI invocation - it never reads or writes
    a file, so "daily"/"monthly" totals are only ever totals *within this
    ledger instance*, never real cross-run spend history. A future
    Phase 47B that needs real persistent spend tracking would replace
    this, not extend it in place."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def record(self, *, request_id: str, task_id: str | None, estimated_credits: int | None, actual_credits: int | None, project_id: str | None, status: str) -> dict[str, Any]:
        entry = {
            "request_id": request_id,
            "task_id": task_id,
            "estimated_credits": estimated_credits,
            "actual_credits": actual_credits,
            "project_id": project_id,
            "timestamp": project_store.utc_now_iso(),
            "status": status,
        }
        self.entries.append(entry)
        return entry

    def _spent(self, *, project_id: str | None) -> int:
        return sum(
            (e["actual_credits"] if e["actual_credits"] is not None else e["estimated_credits"]) or 0
            for e in self.entries
            if project_id is None or e["project_id"] == project_id
        )

    def total_for_project(self, project_id: str | None) -> int:
        return self._spent(project_id=project_id)

    def total_today(self) -> int:
        return self._spent(project_id=None)

    def total_this_month(self) -> int:
        return self._spent(project_id=None)


def check_budget(
    estimated_credits: int | None,
    *,
    cost_policy: dict[str, Any],
    ledger: InMemoryCreditLedger | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Enforces `config/meshy_policy.json`'s actual configured caps -
    never a second, parallel budget scheme. `estimated_credits is None`
    (an unknown/undocumented cost) is always blocked, matching
    `cost_policy["unknown_price_behavior"]`, which this repo's policy
    already defaults to `"block"`. Comparisons are `> cap` (a request
    exactly at the cap is allowed, matching "25-credit request allowed"
    against a `max_credits_per_request: 25` cap in the Phase 47A spec's
    own budget-test list)."""
    credit_policy = cost_policy.get("credit_policy") or {}
    unknown_behavior = cost_policy.get("unknown_price_behavior", "block")

    if estimated_credits is None:
        return {
            "allowed": False,
            "error_code": "unknown_cost",
            "reason": f"Estimated cost is unknown (undocumented combination) and unknown_price_behavior={unknown_behavior!r} blocks this request.",
            "estimated_credits": None,
        }
    if estimated_credits < 0:
        return {"allowed": False, "error_code": "invalid_request", "reason": f"estimated_credits {estimated_credits} is negative - not a valid cost.", "estimated_credits": estimated_credits}

    per_request_cap = credit_policy.get("max_credits_per_request")
    if per_request_cap is not None and estimated_credits > per_request_cap:
        return {
            "allowed": False,
            "error_code": "budget_exceeded",
            "reason": f"Estimated {estimated_credits} credits exceeds max_credits_per_request cap of {per_request_cap}.",
            "estimated_credits": estimated_credits,
        }

    if ledger is not None:
        for label, cap_field, totalizer in (
            ("max_credits_per_project", "max_credits_per_project", lambda: ledger.total_for_project(project_id)),
            ("max_credits_per_day", "max_credits_per_day", ledger.total_today),
            ("max_credits_per_month", "max_credits_per_month", ledger.total_this_month),
        ):
            cap = credit_policy.get(cap_field)
            if cap is None:
                continue
            spent_so_far = totalizer()
            if spent_so_far + estimated_credits > cap:
                return {
                    "allowed": False,
                    "error_code": "budget_exceeded",
                    "reason": f"{spent_so_far} credits already spent + {estimated_credits} estimated would exceed {cap_field} cap of {cap}.",
                    "estimated_credits": estimated_credits,
                }

    return {"allowed": True, "error_code": None, "reason": None, "estimated_credits": estimated_credits}


# ---------------------------------------------------------------------------
# Request planning - dry-run only, never touches the transport
# ---------------------------------------------------------------------------


def plan_text_to_3d_request(
    *,
    prompt: str,
    ai_model: str = DEFAULT_AI_MODEL,
    mode: str = "preview",
    target_polygon_count: int | None = None,
    output_format: str = "stl",
    ultra_mode: bool = False,
    texture_resolution: str | None = None,
    ledger: InMemoryCreditLedger | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """The full Phase 47A request plan - never calls the transport, never
    writes anything. See the Phase 47A spec's "Request model" section for
    the field list this dict carries."""
    request = build_text_to_3d_request(
        prompt=prompt, ai_model=ai_model, mode=mode, target_polygon_count=target_polygon_count,
        output_format=output_format, ultra_mode=ultra_mode, texture_resolution=texture_resolution,
    )
    policy_check = check_policy_gate()
    cost_policy = meshy_approval.load_meshy_policy()["cost_policy"]
    budget_check = check_budget(request["estimated_credits"], cost_policy=cost_policy, ledger=ledger, project_id=project_id)
    privacy_warnings = check_prompt_privacy_hook(prompt)

    blockers: list[str] = []
    if not policy_check["mock_execution_allowed"]:
        blockers.extend(policy_check["blockers"])
    if not budget_check["allowed"]:
        blockers.append(budget_check["reason"])

    mock_execution_allowed = policy_check["mock_execution_allowed"] and budget_check["allowed"]

    approval = meshy_approval.load_meshy_policy()["approval"]
    provenance = {
        "tool": "meshy",
        "tool_model_version": ai_model,
        "factory_phase_version": MESHY_ADAPTER_VERSION,
        "request_type": request["request_type"],
        "prompt_hash": request["prompt_hash"],
        "prompt_record": prompt,
        "reference_ids": [],
        "reference_source_license_metadata": [],
        "input_fingerprints": [],
        "human_approver": approval.get("approved_by"),
        "cost_estimate": request["estimated_credits"],
        "configured_cost_cap": cost_policy.get("credit_policy", {}).get("max_credits_per_request"),
        "execution_confirmation": False,
        "mock": True,
        "live_api_used": False,
        "commercial_policy_status": meshy_approval.load_meshy_policy()["license_policy"].get("commercial_use_verified", False),
    }

    return {
        **request,
        "policy_check": policy_check,
        "budget_check": budget_check,
        "privacy_warnings": privacy_warnings,
        "provenance": provenance,
        "blockers": blockers,
        "warnings": list(privacy_warnings),
        "confirmation_required": True,
        "mock_execution_allowed": mock_execution_allowed,
        "live_execution_allowed": False,
        "dry_run": True,
        "no_automatic_print": True,
    }


# ---------------------------------------------------------------------------
# Mocked execution - the full lifecycle, offline, against MockMeshyTransport
# ---------------------------------------------------------------------------


def _inventory(directory: Path) -> set[str]:
    return {str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()}


def _blocked_result(*, error_code: str, message: str, plan: dict[str, Any], start: float) -> dict[str, Any]:
    return {
        "meshy_adapter_version": MESHY_ADAPTER_VERSION,
        "task_id": None,
        "lifecycle": [],
        "final_status": None,
        "errors": [{"error_code": error_code, "message": message}],
        "warnings": list(plan.get("warnings", [])),
        "artifact_path": None,
        "validation_state": None,
        "preview_state": None,
        "receipt": None,
        "temporary_artifacts_created": False,
        "temporary_artifacts_cleaned": True,
        "unexpected_files": [],
        "retry_allowed": False,
        "automatic_retry_performed": False,
        "mock": True,
        "live_api_used": False,
        "credits_spent": 0,
        "duration_ms": round((time.monotonic() - start) * 1000, 1),
        "no_automatic_print": True,
    }


def run_mock_text_to_3d_request(
    plan: dict[str, Any],
    *,
    scenario: str = "success",
    project_dir: Path | None = None,
    ledger: InMemoryCreditLedger | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Executes the full mocked Text-to-3D lifecycle against
    `MockMeshyTransport`: submit -> bounded poll -> (on success) download
    the fixed local STL fixture -> Factory validation -> Factory preview
    -> build the receipt. Never called unless the caller has already
    obtained explicit human confirmation (see `factory meshy mock-run
    --confirm-mock`); this function itself does not gate on a
    confirmation flag, since the CLI layer is the correct place for that
    check (matching `factory.blender_adapter`'s `confirm_fixture`
    pattern).

    Writes only when `project_dir` is given (into
    `<project_dir>/generated/meshy/`) - otherwise everything happens
    inside one `tempfile.TemporaryDirectory()`, inventoried before/after
    for unexpected-file detection, and verified cleaned afterward. Never
    writes into `examples/` unless a caller explicitly passes an
    `examples/...` path as `project_dir` (the same "explicit human
    target, not this module's decision" pattern every other write-capable
    command in this repo uses).
    """
    start = time.monotonic()

    if not plan.get("mock_execution_allowed"):
        error_code = plan.get("budget_check", {}).get("error_code") or ("policy_blocked" if not plan.get("policy_check", {}).get("mock_execution_allowed") else "invalid_request")
        message = "; ".join(plan.get("blockers") or ["mock execution is not allowed for this plan"])
        return _blocked_result(error_code=error_code or "policy_blocked", message=message, plan=plan, start=start)

    transport = MockMeshyTransport(scenario=scenario)
    lifecycle: list[str] = []
    errors: list[dict[str, str]] = []
    warnings: list[str] = list(plan.get("warnings", []))
    retry_allowed = False
    task_id: str | None = None
    final_task: dict[str, Any] | None = None

    try:
        task = transport.submit_task(plan)
    except MeshyTransportError as exc:
        errors.append({"error_code": exc.error_code, "message": exc.message})
        result = _blocked_result(error_code=exc.error_code, message=exc.message, plan=plan, start=start)
        result["retry_allowed"] = False  # never surfaced as true regardless of the mocked advisory's own flag
        return result

    task_id = task["id"]
    lifecycle.append(task["status"])
    final_task = task

    for _ in range(_MAX_MOCK_POLLS):
        if final_task["status"] in ("SUCCEEDED", "FAILED", "CANCELED"):
            break
        final_task = transport.get_task(task_id)
        lifecycle.append(final_task["status"])
    else:
        errors.append({"error_code": "task_timeout", "message": f"Task did not reach a terminal state within {_MAX_MOCK_POLLS} mocked polls."})

    artifact_path: Path | None = None
    validation_state: str | None = None
    preview_state: str | None = None
    unexpected_files: list[str] = []
    temporary_artifacts_created = False
    temporary_artifacts_cleaned = True
    persisted = project_dir is not None

    if final_task["status"] == "FAILED":
        task_error = (final_task.get("task_error") or {}).get("message", "task failed")
        errors.append({"error_code": "task_failed", "message": task_error})
    elif final_task["status"] == "CANCELED":
        errors.append({"error_code": "task_failed", "message": "task was canceled"})
    elif final_task["status"] == "SUCCEEDED":
        model_urls = final_task.get("model_urls") or {}
        stl_url = model_urls.get("stl")

        def _do_download_and_validate(base_dir: Path) -> None:
            nonlocal artifact_path, validation_state, preview_state, unexpected_files
            before = _inventory(base_dir)
            stl_path = base_dir / "mock_concept.stl"
            try:
                transport.download_artifact(stl_url, stl_path)
            except MeshyTransportError as exc:
                errors.append({"error_code": exc.error_code, "message": exc.message})
                return
            after = _inventory(base_dir)
            unexpected_files = sorted((after - before) - {"mock_concept.stl"})
            if unexpected_files:
                warnings.append(f"Unexpected file(s) created: {unexpected_files}")

            artifact_path = stl_path
            try:
                # Never reads final_task's own "meshy_printability_claim" -
                # Factory validation always runs regardless of any provider claim.
                report = validate_mesh(stl_path)
                overall = report.get("overall_status")
                validation_state = {"PASS": "PASS", "WARN": "WARN"}.get(overall, "FAIL")
                if validation_state == "FAIL":
                    errors.append({"error_code": "validation_failed", "message": "Factory mesh validation reported FAIL for the mocked artifact."})
            except Exception as exc:  # validator failure must not abort the run
                validation_state = "FAIL"
                errors.append({"error_code": "validation_failed", "message": f"{type(exc).__name__}: {exc}"})

            try:
                preview_path = base_dir / "mock_concept_preview.png"
                preview_result = render_preview(stl_path, preview_path)
                preview_status = preview_result.get("status")
                preview_state = {"PASS": "PASS", "WARN": "WARN"}.get(preview_status, "FAIL")
                if preview_state == "FAIL":
                    errors.append({"error_code": "preview_failed", "message": preview_result.get("detail", "preview render failed")})
            except Exception as exc:  # preview failure must not abort the run
                preview_state = "FAIL"
                errors.append({"error_code": "preview_failed", "message": f"{type(exc).__name__}: {exc}"})

        if persisted:
            base_dir = Path(project_dir) / "generated" / "meshy"
            base_dir.mkdir(parents=True, exist_ok=True)
            _do_download_and_validate(base_dir)
            temporary_artifacts_created = False
            temporary_artifacts_cleaned = True
        else:
            tmp_dir_path: str | None = None
            try:
                with tempfile.TemporaryDirectory(prefix="factory-meshy-mock-") as tmp_dir:
                    tmp_dir_path = tmp_dir
                    temporary_artifacts_created = True
                    _do_download_and_validate(Path(tmp_dir))
                    # artifact_path points inside tmp_dir, which is about to be
                    # removed - callers reading this result after return must
                    # treat artifact_path as evidence-only, never a live path.
                temporary_artifacts_cleaned = tmp_dir_path is not None and not Path(tmp_dir_path).exists()
            except Exception as exc:
                temporary_artifacts_cleaned = tmp_dir_path is not None and not Path(tmp_dir_path).exists() if tmp_dir_path else True
                errors.append({"error_code": "receipt_failed", "message": f"unexpected error during mocked execution: {exc}"})

    consumed_credits = final_task.get("consumed_credits") if final_task.get("status") == "SUCCEEDED" else 0
    credits_spent = 0  # mocked - never real credits, regardless of what the fixture's consumed_credits says

    if ledger is not None:
        ledger.record(
            request_id=plan["prompt_hash"], task_id=task_id, estimated_credits=plan.get("estimated_credits"),
            actual_credits=consumed_credits, project_id=project_id, status=final_task.get("status", "unknown"),
        )

    receipt = None
    if not errors or validation_state is not None:
        receipt = {
            "meshy_task_id": task_id,
            "meshy_task_type": final_task.get("type"),
            "ai_model": plan.get("model"),
            "requested_target_formats": plan.get("target_formats"),
            "model_urls": final_task.get("model_urls"),
            "consumed_credits": final_task.get("consumed_credits"),
            "created_at": final_task.get("created_at"),
            "started_at": final_task.get("started_at"),
            "finished_at": final_task.get("finished_at"),
            "expires_at": final_task.get("expires_at"),
            "status": final_task.get("status"),
            "task_error": final_task.get("task_error"),
            "human_approver": plan.get("provenance", {}).get("human_approver"),
            "cost_estimate_before_request": plan.get("estimated_credits"),
            "configured_cost_cap_at_request_time": plan.get("provenance", {}).get("configured_cost_cap"),
            "execution_confirmation": True,
            "input_fingerprint": plan.get("prompt_hash"),
            "output_artifact_paths": [str(artifact_path)] if artifact_path else [],
            "output_fingerprints": [],
            "formats": plan.get("target_formats"),
            "validation_state": validation_state,
            "preview_state": preview_state,
            "warnings": warnings,
            "printability_result_if_returned": None,  # never populated from the mock's own printability claim
            "repair_operations_if_any": [],
            "human_review_state": "required",
            "mock_execution": True,
            "live_api_used": False,
            "credits_spent": 0,
            "money_spent": 0,
            "commercial_policy_status": plan.get("provenance", {}).get("commercial_policy_status", False),
            "no_automatic_print": True,
        }
        if persisted:
            receipt_path = Path(project_dir) / "generated" / "meshy_receipt.json"
            project_store.save_json(receipt_path, receipt)

    return {
        "meshy_adapter_version": MESHY_ADAPTER_VERSION,
        "task_id": task_id,
        "lifecycle": lifecycle,
        "final_status": final_task.get("status") if final_task else None,
        "errors": errors,
        "warnings": warnings,
        "artifact_path": str(artifact_path) if artifact_path else None,
        "validation_state": validation_state,
        "preview_state": preview_state,
        "receipt": receipt,
        "receipt_path": str(Path(project_dir) / "generated" / "meshy_receipt.json") if persisted and receipt else None,
        "temporary_artifacts_created": temporary_artifacts_created,
        "temporary_artifacts_cleaned": temporary_artifacts_cleaned,
        "unexpected_files": unexpected_files,
        "retry_allowed": retry_allowed,
        "automatic_retry_performed": False,
        "mock": True,
        "live_api_used": False,
        "credits_spent": credits_spent,
        "duration_ms": round((time.monotonic() - start) * 1000, 1),
        "no_automatic_print": True,
    }


# ---------------------------------------------------------------------------
# Compact runtime-state view for Engine Registry / Preview Board rendering
# ---------------------------------------------------------------------------


def summarize_mock_adapter_state() -> dict[str, Any]:
    """Static facts about this phase's own architecture - no policy read,
    no I/O. `factory.cli`/`factory.preview_board` use this to render the
    Engine Registry / Preview Board distinction the spec requires stay
    visible: mock adapter implemented, live transport not implemented,
    live execution disabled."""
    return {
        "mock_adapter_implemented": True,
        # Phase 47B added factory.meshy_http_transport.HttpMeshyTransport -
        # the code exists, but is never constructed unless every gate in
        # factory.meshy_live_adapter's locked order has already passed.
        # This flag is honest about *implementation*, never *authorization*.
        "live_transport_implemented": True,
        "live_execution_enabled": False,
        "supported_request_types": ["text_to_3d"],
    }


def build_safety_block() -> dict[str, Any]:
    return dict(_SAFETY_BLOCK)

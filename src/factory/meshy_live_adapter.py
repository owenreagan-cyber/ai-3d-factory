"""Phase 47B: live Meshy request planning + the gated live-run
orchestrator.

**This module enforces the locked live-execution order
(`docs/meshy-live-readiness.md` section 14) and does not itself contain
any network-capable code** - it only ever constructs
`factory.meshy_http_transport.HttpMeshyTransport`/`LiveMeshyCredentialProvider`,
and only after every earlier gate has passed:

    1. parse local request                              (no I/O)
    2. local policy check    (factory.meshy_approval.evaluate_meshy_gate())
    3. local budget check    (factory.meshy_ledger.SpendLedger + config/meshy_policy.json)
    4. kill-switch check     (config/future_cloud_tools.json AND policy.approval.execution_enabled - BOTH required)
    5. one-shot approval check (factory.meshy_live_approval.find_eligible_approval())
    6. explicit --confirm-live
    7. only then: read MESHY_API_KEY (LiveMeshyCredentialProvider.get_api_key())
    8. only then: construct HttpMeshyTransport
    9. only then: make the network call (submit_task())

Every one of steps 2-6 failing short-circuits *before* step 7 - this is
architecturally enforced (not just documented) by `run_live_text_to_3d_request()`
never even constructing a credential provider until every earlier check
has returned "allowed". See `tests/test_meshy_live_adapter.py`'s
dedicated per-gate tests proving the credential provider is never
invoked when any of steps 2-6 blocks.

`plan_live_text_to_3d_request()` is completely offline: it never reads a
credential, never reserves ledger credit, and never consumes a one-shot
approval - it only *reports* whether each gate would currently pass,
exactly like `factory meshy live-plan`'s spec example.

Reuses rather than duplicates: `factory.meshy_models` (request/prompt/
cost model), `factory.meshy_approval` (Phase 46 policy gate),
`factory.future_cloud_tools` (Phase 16 kill switch), `factory.meshy_ledger`
(persistent budget), `factory.meshy_live_approval` (one-shot approval),
`factory.validators.mesh_validate`/`factory.previews.render_preview`
(the same Factory validation/preview path every mesh in this repo goes
through - no Meshy-specific validator or visual-QA subsystem).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from factory import future_cloud_tools, meshy_approval, project_store
from factory.meshy_adapter import check_budget
from factory.meshy_http_transport import MESHY_API_BASE, HttpMeshyTransport, LiveMeshyCredentialProvider, MeshyCredentialError
from factory.meshy_ledger import LedgerError, SpendLedger
from factory.meshy_live_approval import find_eligible_approval
from factory.meshy_mock_transport import MeshyTransport, MeshyTransportError
from factory.meshy_models import DEFAULT_AI_MODEL, build_text_to_3d_request, check_prompt_privacy_hook
from factory.previews.render_preview import render_preview
from factory.validators.mesh_validate import validate_mesh

MESHY_LIVE_ADAPTER_VERSION = 1
API_VERSION = "v2"
ENDPOINT = f"{MESHY_API_BASE}/openapi/v2/text-to-3d"

# Bounded polling (docs/meshy-live-readiness.md section 8). Injectable
# sleep_fn lets tests skip the real delay while keeping the same bound
# structure a real deadline would enforce.
POLL_INITIAL_DELAY_SECONDS = 5.0
POLL_INTERVAL_SECONDS = 5.0
POLL_MAX_ATTEMPTS = 24


class LiveExecutionBlocked(Exception):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def check_kill_switch() -> dict[str, Any]:
    """Reads the two independent kill-switch flags directly from their
    committed/local files - **not** through
    `meshy_approval.evaluate_meshy_gate()`, which deliberately hardcodes
    `kill_switch.execution_enabled=False` (Phase 46's own invariant, so
    that phase's code can never be tricked into reporting execution
    enabled). This module is the first phase allowed to read the raw
    `approval.execution_enabled` field, because checking whether a human
    has manually flipped it is precisely this gate's job."""
    future_cloud_enabled = bool(future_cloud_tools.get_future_cloud_tool("meshy").get("enabled", False))
    policy_execution_enabled = bool(meshy_approval.load_meshy_policy().get("approval", {}).get("execution_enabled", False))
    return {
        "future_cloud_tools_enabled": future_cloud_enabled,
        "policy_execution_enabled": policy_execution_enabled,
        "both_enabled": future_cloud_enabled and policy_execution_enabled,
    }


def _base_plan(*, prompt: str, model: str, mode: str, target_polygon_count: int | None, ultra_mode: bool, project: str | None) -> dict[str, Any]:
    request = build_text_to_3d_request(prompt=prompt, ai_model=model, mode=mode, target_polygon_count=target_polygon_count, ultra_mode=ultra_mode)
    gate = meshy_approval.evaluate_meshy_gate()
    policy_approved = gate["gate_status"] == "approved_for_future_api_integration"
    cost_policy = meshy_approval.load_meshy_policy()["cost_policy"]

    try:
        ledger = SpendLedger()
        budget_check = check_budget(request["estimated_credits"], cost_policy=cost_policy, ledger=ledger, project_id=project)
        ledger_unavailable = False
    except LedgerError as exc:
        budget_check = {"allowed": False, "error_code": "budget_exceeded", "reason": f"spend ledger unavailable - failing closed: {exc}", "estimated_credits": request["estimated_credits"]}
        ledger_unavailable = True

    kill_switch = check_kill_switch()
    prompt_hash = request["prompt_hash"]
    approval_record = find_eligible_approval(
        prompt_hash=prompt_hash, model=model, request_type="text_to_3d",
        max_credits=request["estimated_credits"] or 0, project=project,
    )

    blockers: list[str] = []
    if not policy_approved:
        blockers.append("Meshy policy is not approved_for_future_api_integration.")
    if not budget_check["allowed"]:
        blockers.append(budget_check["reason"])
    if not kill_switch["both_enabled"]:
        blockers.append(
            "Kill switch disabled - requires BOTH config/future_cloud_tools.json tools.meshy.enabled=true "
            "AND config/meshy_policy.json approval.execution_enabled=true."
        )
    if approval_record is None:
        blockers.append("No eligible one-shot live-call approval found for this exact prompt/model/credit-cap/project.")

    every_gate_satisfied = not blockers  # --confirm-live and credential are checked only at run time, never here

    return {
        **request,
        "meshy_live_adapter_version": MESHY_LIVE_ADAPTER_VERSION,
        "endpoint": ENDPOINT,
        "api_version": API_VERSION,
        "policy_approved": policy_approved,
        "budget_check": budget_check,
        "ledger_unavailable": ledger_unavailable,
        "kill_switch": kill_switch,
        "approval_status": "eligible" if approval_record else "missing",
        "approval_id": approval_record["approval_id"] if approval_record else None,
        "privacy_warnings": check_prompt_privacy_hook(prompt),
        "blockers": blockers,
        "every_gate_satisfied": every_gate_satisfied,
        "credential_checked": False,
        "network_used": False,
        "live_execution_blocked": True,  # always true from plan/run's own perspective before --confirm-live + credential succeed
        "no_automatic_print": True,
    }


def plan_live_text_to_3d_request(
    *, prompt: str, model: str = DEFAULT_AI_MODEL, mode: str = "preview",
    target_polygon_count: int | None = None, ultra_mode: bool = False, project: str | None = None,
) -> dict[str, Any]:
    """`factory meshy live-plan` - fully offline. Never reads a
    credential, never reserves budget, never consumes a one-shot
    approval - only reports each gate's current status."""
    return _base_plan(prompt=prompt, model=model, mode=mode, target_polygon_count=target_polygon_count, ultra_mode=ultra_mode, project=project)


def _map_transport_error(exc: MeshyTransportError) -> dict[str, str]:
    return {"error_code": exc.error_code, "message": exc.message}


def run_live_text_to_3d_request(
    *, prompt: str, model: str = DEFAULT_AI_MODEL, mode: str = "preview",
    target_polygon_count: int | None = None, ultra_mode: bool = False, project: str | None = None,
    confirm_live: bool = False,
    credential_provider_factory: Callable[[], Any] | None = None,
    transport_factory: Callable[[Any], MeshyTransport] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """The gated live-run orchestrator. Exactly one `submit_task()` call,
    ever, per invocation - there is no retry loop around it, not even a
    `max_retries=1` loop (see `docs/meshy-live-readiness.md` section 9:
    "an absence of a loop", not a bounded one).

    `credential_provider_factory`/`transport_factory` exist purely for
    test injection (never used in the default/real path except to
    construct the real `LiveMeshyCredentialProvider`/`HttpMeshyTransport`
    at step 7/8, after every earlier gate has already passed) - see
    `tests/test_meshy_live_adapter.py`'s dedicated ordering tests.
    """
    start = time.monotonic()
    plan = _base_plan(prompt=prompt, model=model, mode=mode, target_polygon_count=target_polygon_count, ultra_mode=ultra_mode, project=project)

    def _blocked(error_code: str, message: str) -> dict[str, Any]:
        return {
            "meshy_live_adapter_version": MESHY_LIVE_ADAPTER_VERSION,
            "task_id": None, "final_status": None, "errors": [{"error_code": error_code, "message": message}],
            "warnings": list(plan.get("privacy_warnings", [])), "artifact_path": None, "validation_status": None,
            "preview_status": None, "receipt": None, "receipt_path": None, "retry_allowed": False,
            "automatic_retry_performed": False, "mock_execution": False, "live_api_used": False,
            "credits_spent": 0, "money_spent": 0, "duration_ms": round((time.monotonic() - start) * 1000, 1),
            "no_automatic_print": True,
        }

    # Steps 2-5: every one of these must pass before step 6 is even
    # consulted, and credential/transport construction (steps 7-8) is
    # only ever reached after step 6 too - see the module docstring.
    if not plan["policy_approved"]:
        return _blocked("policy_blocked", "Meshy policy is not approved_for_future_api_integration.")
    if not plan["budget_check"]["allowed"]:
        return _blocked(plan["budget_check"]["error_code"] or "budget_exceeded", plan["budget_check"]["reason"])
    if not plan["kill_switch"]["both_enabled"]:
        return _blocked("kill_switch_disabled", "Both future_cloud_tools.meshy.enabled and policy.approval.execution_enabled must be true.")
    if plan["approval_id"] is None:
        return _blocked("live_execution_not_approved", "No eligible one-shot live-call approval found for this exact prompt/model/credit-cap/project.")
    if not confirm_live:
        return _blocked("live_execution_not_approved", "Pass --confirm-live to actually execute this approved, budget-checked live request.")

    # Step 7/8: reserve budget + consume the one-shot approval, THEN
    # (only then) construct the credential provider/transport.
    from factory.meshy_live_approval import consume_approval  # local import: keeps this the one call site

    ledger = SpendLedger()
    try:
        reservation = ledger.reserve(
            request_id=plan["prompt_hash"], project=project, request_type="text_to_3d", model=model,
            estimated_credits=plan["estimated_credits"], policy_version=meshy_approval.load_meshy_policy().get("policy_version", 1),
            approval_reference=plan["approval_id"],
        )
    except LedgerError as exc:
        return _blocked("budget_exceeded", f"could not reserve budget - failing closed: {exc}")

    try:
        consume_approval(plan["approval_id"])
    except Exception as exc:  # approval consumption failed (already consumed by a racing invocation, etc.) - never proceed
        ledger.mark_unknown(reservation["reservation_id"], reason=f"approval consumption failed after reservation: {exc}")
        return _blocked("live_execution_not_approved", f"one-shot approval could not be consumed: {exc}")

    credential_provider = (credential_provider_factory or LiveMeshyCredentialProvider)()
    transport = (transport_factory or (lambda cp: HttpMeshyTransport(cp)))(credential_provider)

    errors: list[dict[str, str]] = []
    warnings: list[str] = list(plan.get("privacy_warnings", []))
    task_id: str | None = None
    final_task: dict[str, Any] | None = None

    try:
        try:
            task = transport.submit_task(plan)
        except MeshyCredentialError as exc:
            ledger.mark_unknown(reservation["reservation_id"], reason=f"credential error before submission: {exc}")
            return _blocked("live_execution_not_approved", f"credential unavailable: {exc}")
        except MeshyTransportError as exc:
            # Submission itself is the one-shot boundary - a failure here
            # (network error, non-2xx, malformed response) still keeps the
            # reservation (we cannot be certain no request reached Meshy).
            ledger.mark_unknown(reservation["reservation_id"], reason=f"submission failed: {exc.message}")
            errors.append(_map_transport_error(exc))
            result = _blocked(exc.error_code, exc.message)
            result["errors"] = errors
            return result

        task_id = task["id"]
        ledger.mark_submitted(reservation["reservation_id"], task_id=task_id)
        final_task = task

        sleep_fn(POLL_INITIAL_DELAY_SECONDS)
        for attempt in range(POLL_MAX_ATTEMPTS):
            if final_task["status"] in ("SUCCEEDED", "FAILED", "CANCELED"):
                break
            try:
                final_task = transport.get_task(task_id)
            except MeshyTransportError as exc:
                # Polling failures retry the read-only get_task() call
                # (bounded by the same attempt count) - the task was
                # already submitted/billed, so re-reading its status
                # costs nothing and creates no duplicate task.
                warnings.append(f"poll attempt {attempt + 1} failed: {exc.message}")
                sleep_fn(POLL_INTERVAL_SECONDS)
                continue
            if final_task["status"] not in ("PENDING", "IN_PROGRESS", "SUCCEEDED", "FAILED", "CANCELED"):
                ledger.mark_unknown(reservation["reservation_id"], reason=f"unrecognized provider status {final_task['status']!r}")
                errors.append({"error_code": "invalid_request", "message": f"unknown_provider_status: {final_task['status']!r}"})
                result = _blocked("invalid_request", f"unrecognized provider task status {final_task['status']!r}")
                result["errors"] = errors
                return result
            sleep_fn(POLL_INTERVAL_SECONDS)
        else:
            ledger.mark_unknown(reservation["reservation_id"], reason="polling exceeded the bounded attempt count without reaching a terminal state")
            errors.append({"error_code": "task_timeout", "message": f"task did not reach a terminal state within {POLL_MAX_ATTEMPTS} bounded polls"})
            result = _blocked("task_timeout", f"task {task_id} did not reach a terminal state within {POLL_MAX_ATTEMPTS} bounded polls")
            result["task_id"] = task_id
            result["errors"] = errors
            return result

        if final_task["status"] in ("FAILED", "CANCELED"):
            ledger.mark_unknown(reservation["reservation_id"], reason=f"task ended {final_task['status']}")
            message = (final_task.get("task_error") or {}).get("message", f"task {final_task['status'].lower()}")
            errors.append({"error_code": "task_failed", "message": message})
            result = _blocked("task_failed", message)
            result["task_id"] = task_id
            result["final_status"] = final_task["status"]
            result["errors"] = errors
            return result

        # SUCCEEDED - reconcile, download once, validate/preview, receipt.
        actual_credits = final_task.get("consumed_credits")
        ledger.mark_succeeded(reservation["reservation_id"], actual_credits=actual_credits)

        model_urls = final_task.get("model_urls") or {}
        stl_url = model_urls.get("stl")
        artifact_path: Path | None = None
        validation_status: str | None = None
        preview_status: str | None = None
        download_status = "not_attempted"
        receipt = None
        receipt_path = None

        if not stl_url:
            errors.append({"error_code": "artifact_missing", "message": "task succeeded but model_urls has no 'stl' entry"})
        elif project is None:
            errors.append({"error_code": "invalid_request", "message": "a live-run against a SUCCEEDED task requires --project (a disposable project directory) to persist the artifact/receipt"})
        else:
            raw_dir = Path(project) / "generated" / "meshy" / "raw"
            processed_dir = Path(project) / "generated" / "meshy" / "processed"
            raw_path = raw_dir / f"{task_id}.stl"
            processed_path = processed_dir / f"{task_id}.stl"
            if raw_path.exists() or processed_path.exists():
                errors.append({"error_code": "invalid_request", "message": f"refusing to overwrite existing artifact at {raw_path} or {processed_path}"})
            else:
                try:
                    transport.download_artifact(stl_url, raw_path)
                    download_status = "succeeded"
                    processed_dir.mkdir(parents=True, exist_ok=True)
                    processed_path.write_bytes(raw_path.read_bytes())  # identical bytes for this STL-native first call
                    artifact_path = processed_path
                except MeshyTransportError as exc:
                    download_status = "failed"
                    errors.append(_map_transport_error(exc))

            if artifact_path is not None:
                try:
                    report = validate_mesh(artifact_path)
                    validation_status = {"PASS": "PASS", "WARN": "WARN"}.get(report.get("overall_status"), "FAIL")
                    if validation_status == "FAIL":
                        errors.append({"error_code": "validation_failed", "message": "Factory mesh validation reported FAIL"})
                except Exception as exc:
                    validation_status = "FAIL"
                    errors.append({"error_code": "validation_failed", "message": f"{type(exc).__name__}: {exc}"})
                try:
                    preview_result = render_preview(artifact_path, processed_dir / f"{task_id}_preview.png")
                    preview_status = {"PASS": "PASS", "WARN": "WARN"}.get(preview_result.get("status"), "FAIL")
                except Exception as exc:
                    preview_status = "FAIL"
                    errors.append({"error_code": "preview_failed", "message": f"{type(exc).__name__}: {exc}"})

                receipt = {
                    "meshy_task_id": task_id, "mock_execution": False, "live_api_used": True,
                    "provider": "meshy", "api_version": API_VERSION, "endpoint": ENDPOINT,
                    "ai_model": model, "cost_estimate_before_request": plan["estimated_credits"],
                    "consumed_credits": actual_credits, "ledger_reservation_id": reservation["reservation_id"],
                    "live_call_approval": plan["approval_id"], "submit_status": "succeeded",
                    "final_status": final_task["status"], "download_status": download_status,
                    "created_at": final_task.get("created_at"), "started_at": final_task.get("started_at"),
                    "finished_at": final_task.get("finished_at"), "expires_at": final_task.get("expires_at"),
                    "output_artifact_paths": [str(artifact_path)], "artifact_fingerprint": None,
                    "validation_status": validation_status, "preview_status": preview_status,
                    "human_review_state": "required", "commercial_use_verified": False,
                    "kill_switch_state": plan["kill_switch"], "warnings": warnings,
                    "no_automatic_print": True, "automatic_print_allowed": False,
                }
                receipt_path = Path(project) / "generated" / "meshy_receipt.json"
                project_store.save_json(receipt_path, receipt)

        return {
            "meshy_live_adapter_version": MESHY_LIVE_ADAPTER_VERSION, "task_id": task_id,
            "final_status": final_task["status"], "errors": errors, "warnings": warnings,
            "artifact_path": str(artifact_path) if artifact_path else None,
            "validation_status": validation_status, "preview_status": preview_status,
            "receipt": receipt, "receipt_path": str(receipt_path) if receipt_path else None,
            "retry_allowed": False, "automatic_retry_performed": False, "mock_execution": False,
            "live_api_used": True, "credits_spent": actual_credits or 0, "money_spent": 0,
            "duration_ms": round((time.monotonic() - start) * 1000, 1), "no_automatic_print": True,
        }
    finally:
        pass  # no cleanup step currently needed; kept as an explicit hook point for future artifact-containment additions

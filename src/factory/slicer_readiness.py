"""Phase 36: Slicer Review Readiness Promotion and Review Package.

The formal bridge between a completed Phase 35 export/validate/render
pipeline and human slicer review:

    Guided Export Pipeline -> STL Validation and Preview -> Artifact
    Finalization -> Slicer Review Readiness -> Human Approval ->
    Manual Slicer Review -> (never automatic printing)

**This is a thin assessment/promotion layer over already-computed
state - it never re-implements mesh validation, render-freshness
checking, review-gate logic, slicer detection, artifact fingerprinting,
manifest-completeness checks, or manufacturing checks.** It reads
`factory.project_inspection.summarize_project()` (which already reuses
Phase 8-35's own logic - `export_pipeline_summary`, `generation_gate_summary`,
`generation_execution_summary`, `health_signals`, `render_coverage`),
`factory.review_gate.evaluate_review_gate()` (the existing pass/warn/fail
gate, never rewritten here), and `factory.slicer.local_slicer_probe.probe_slicers()`
(existing read-only slicer discovery) - and combines them into one
deterministic readiness assessment, score, and (only with explicit
confirmation) a local review package conforming to the pre-existing
`schemas/slicer_review.schema.json`.

**Read-only unless explicitly creating an approved package or recording
approval.** `assess_slicer_readiness()` never writes anything. Only
`record_approval()` and `create_review_package()` write, and only when
explicitly called (the CLI gates both behind explicit flags -
`--approve` and `--create-package --confirm-package` respectively).

**Technical readiness and human approval are separate states, never
conflated.** A project can be `ready_for_review_package`-eligible on
every technical signal and still have no approval recorded - approval is
always a separate, explicit, human-recorded action, and it is invalidated
automatically the moment a relevant artifact's fingerprint changes.

**Never slices, uploads, queues, or prints anything.** This phase's only
output is a human-reviewable assessment and a local review package -
`slicer_review/slicer_review_manifest.json`'s `auto_print_allowed` field
is always `false`, exactly like the pre-existing schema's own hard-coded
constant. See `docs/slicer-readiness.md`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from factory import project_store
from factory.export_pipeline import EXPORT_RECEIPT_FILENAME, GENERATED_DIRNAME
from factory.manufacturing.manifest import compute_assembly_intent
from factory.project_inspection import summarize_project
from factory.review_gate import evaluate_review_gate
from factory.slicer.local_slicer_probe import probe_slicers

READINESS_STATES = (
    "unsupported_project_state",
    "blocked",
    "not_ready",
    "stale_artifacts",
    "needs_validation",
    "needs_preview",
    "needs_manifest_completion",
    "needs_information",
    "needs_human_approval",
    "ready_for_review_package",
    "review_package_created",
)

# States in which a human has something concrete and current enough to
# stand behind - the only two `ready_for_slicer_review` ever resolves to
# `True` for. A high readiness_score never overrides this - see
# `_evaluate_readiness_status()`.
_READY_STATES = ("ready_for_review_package", "review_package_created")

# generated/slicer_readiness_receipt.json - a second sibling of Phase 34's
# generation receipt and Phase 35's export receipt. Records approval and
# package state only; the technical assessment itself is never cached here
# - it is always recomputed fresh from source data on every call. Never
# written by a dry-run assessment.
READINESS_RECEIPT_FILENAME = "slicer_readiness_receipt.json"

SLICER_REVIEW_DIRNAME = "slicer_review"
REVIEW_PACKAGE_FILENAME = "slicer_review_manifest.json"
REVIEW_PACKAGE_README_FILENAME = "README.md"

NO_AUTOMATIC_PRINT_LINES = (
    "This assessment and package never invoke a slicer, upload a file, submit a print job, "
    "or contact a printer/network.",
    "auto_print_allowed is always false - print submission remains a separate, explicit, "
    "human-initiated action outside this repo's automation.",
    "Human slicer review is still required after this package is created.",
)

# ---------------------------------------------------------------------------
# Scoring weights - documented, deterministic, and capped by hard blockers.
# Sum to 1.0. See docs/slicer-readiness.md "Readiness scoring" for the
# rationale behind each weight and every per-category formula.
# ---------------------------------------------------------------------------
CATEGORY_WEIGHTS = {
    "stl": 0.25,
    "validation": 0.25,
    "preview": 0.15,
    "manifest": 0.15,
    "manufacturing": 0.10,
    "receipts": 0.05,
    "review_gate": 0.05,
}

_VALIDATION_POINTS = {"passed": 1.0, "PASS": 1.0, "passed_with_warnings": 0.7, "WARN": 0.7, "failed": 0.0, "FAIL": 0.0, "unavailable": 0.0, "not_run": 0.0}
_TBD_MATERIAL_MARKERS = ("tbd", "unresolved", "unknown")


def _file_fingerprint(path: Path) -> str:
    """Same `sha256:<hex digest>` convention `factory.export_pipeline` already
    uses - reused here (not re-derived independently) for artifact
    fingerprint traceability across CAD source, STL, validation reports,
    and previews.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _relative_path(path: Path, project_dir: Path) -> str:
    path = Path(path)
    try:
        return path.relative_to(Path(project_dir)).as_posix()
    except ValueError:
        return path.as_posix()


# Public aliases (Phase 37): factory.manual_review_workspace sits directly
# above this module (the same "top-level consumer" relationship
# preview_board.py and review_gate.py already have) and reuses these
# exact fingerprint/path/manifest helpers rather than re-deriving them -
# see that module's own docstring. Kept as plain aliases (not a rename) so
# every existing internal call site and test in this module is untouched.
file_fingerprint = _file_fingerprint
relative_path = _relative_path


def _is_unresolved_material_value(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return True
    lowered = value.lower()
    return any(marker in lowered for marker in _TBD_MATERIAL_MARKERS)


# ---------------------------------------------------------------------------
# Sub-assessments - each reuses an existing module's already-computed
# output; none re-implements a check.
# ---------------------------------------------------------------------------


def _stl_assessment(export_summary: dict[str, Any]) -> dict[str, Any]:
    """Reuses `factory.export_pipeline.summarize_export_pipeline()`'s output
    (already folded into `export_pipeline_summary` by `summarize_project()`)
    - never re-derives STL freshness independently.
    """
    expected = export_summary.get("expected_stl_count") or 0
    current = export_summary.get("current_stl_count") or 0
    stale = export_summary.get("stale_stl_count") or 0
    missing = max(expected - current - stale, 0)
    return {"expected": expected, "current": current, "stale": stale, "missing": missing}


def _validation_assessment(project_dir: Path, export_receipt: dict[str, Any] | None) -> dict[str, Any]:
    """Reuses each source file's already-written validation record from the
    Phase 35 export receipt (never re-runs `factory.validators.mesh_validate`).
    """
    statuses: list[str] = []
    for record in (export_receipt or {}).get("exports", []):
        status = record.get("validation", {}).get("status")
        if status:
            statuses.append(status)

    pass_count = sum(1 for s in statuses if s == "passed")
    warning_count = sum(1 for s in statuses if s == "passed_with_warnings")
    failure_count = sum(1 for s in statuses if s == "failed")
    unavailable_count = sum(1 for s in statuses if s == "unavailable")
    not_run_count = sum(1 for s in statuses if s in (None, "not_run")) + max(
        0, (export_receipt and len(export_receipt.get("exports", [])) or 0) - len(statuses)
    )
    return {
        "statuses": statuses,
        "pass_count": pass_count,
        "warning_count": warning_count,
        "failure_count": failure_count,
        "unavailable_count": unavailable_count,
        "not_run_count": not_run_count,
    }


def _preview_assessment(export_receipt: dict[str, Any] | None) -> dict[str, Any]:
    """Reuses each source file's already-written render record from the
    Phase 35 export receipt (which itself reuses
    `factory.render_coverage.compute_render_coverage()` for staleness -
    never re-derived here).
    """
    statuses = []
    for record in (export_receipt or {}).get("exports", []):
        status = record.get("render", {}).get("status")
        if status:
            statuses.append(status)
    current = sum(1 for s in statuses if s == "passed")
    stale = sum(1 for s in statuses if s == "stale")
    missing = sum(1 for s in statuses if s in ("not_run", "failed", "unavailable"))
    return {"current": current, "stale": stale, "missing": missing, "statuses": statuses}


def _manifest_assessment(project_dir: Path) -> dict[str, Any]:
    """Reads `part_manifest.json` and `build_plan.json` directly (simple
    reads, not a duplicated validator) and reuses
    `factory.manufacturing.manifest.compute_assembly_intent()` for
    multipart status - never re-implements assembly-intent logic.
    """
    project_dir = Path(project_dir)
    manifest_path = project_dir / "part_manifest.json"
    build_plan_path = project_dir / "build_plan.json"

    manifest_readable = manifest_path.is_file()
    manifest: dict[str, Any] = {}
    if manifest_readable:
        try:
            manifest = project_store.load_json(manifest_path)
        except (OSError, ValueError):
            manifest_readable = False

    build_plan: dict[str, Any] = {}
    if build_plan_path.is_file():
        try:
            build_plan = project_store.load_json(build_plan_path)
        except (OSError, ValueError):
            build_plan = {}

    parts = manifest.get("parts", []) if isinstance(manifest.get("parts"), list) else []
    assembly_intent = compute_assembly_intent(build_plan) if build_plan else None

    unresolved_material_parts = [
        p.get("part_name") for p in parts if _is_unresolved_material_value(p.get("material"))
    ]
    unresolved_color_parts = [p.get("part_name") for p in parts if _is_unresolved_material_value(p.get("color"))]

    target_printer = build_plan.get("target_printer") or {}
    printer_resolved = bool(target_printer.get("resolved"))

    return {
        "manifest_readable": manifest_readable,
        "part_count": len(parts),
        "assembly_intent": assembly_intent,
        "unresolved_material_parts": unresolved_material_parts,
        "unresolved_color_parts": unresolved_color_parts,
        "printer_resolved": printer_resolved,
        "printer_display_name": target_printer.get("display_name"),
        "selected_manufacturing_option": build_plan.get("selected_manufacturing_option"),
    }


# Public alias (Phase 37) - see the note by `file_fingerprint`/`relative_path` above.
manifest_assessment = _manifest_assessment


def _receipts_assessment(project_dir: Path, export_receipt: dict[str, Any] | None) -> dict[str, Any]:
    project_dir = Path(project_dir)
    generation_receipt_path = project_dir / GENERATED_DIRNAME / "generation_receipt.json"
    export_receipt_path = project_dir / GENERATED_DIRNAME / EXPORT_RECEIPT_FILENAME
    return {
        "generation_receipt_present": generation_receipt_path.is_file(),
        "generation_receipt_path": _relative_path(generation_receipt_path, project_dir)
        if generation_receipt_path.is_file()
        else None,
        "export_receipt_present": export_receipt_path.is_file(),
        "export_receipt_path": _relative_path(export_receipt_path, project_dir)
        if export_receipt_path.is_file()
        else None,
        "export_receipt_covers_current_stl": bool(export_receipt) and bool(export_receipt.get("exports")),
    }


# ---------------------------------------------------------------------------
# Scoring - each sub-score is 0-100; the overall score is a fixed, documented
# weighted sum. Never used to bypass a hard blocker - see
# `_evaluate_readiness_status()`, which computes `readiness_status`
# (and therefore `ready_for_slicer_review`) entirely independently of score.
# ---------------------------------------------------------------------------


def _stl_score(stl: dict[str, Any]) -> float:
    if stl["expected"] == 0:
        return 0.0
    return 100.0 * stl["current"] / stl["expected"]


def _validation_score(validation: dict[str, Any]) -> float:
    if not validation["statuses"]:
        return 0.0
    points = [_VALIDATION_POINTS.get(s, 0.0) for s in validation["statuses"]]
    return 100.0 * (sum(points) / len(points))


def _preview_score(preview: dict[str, Any]) -> float:
    total = preview["current"] + preview["stale"] + preview["missing"]
    if total == 0:
        return 0.0
    return 100.0 * preview["current"] / total


def _manifest_score(manifest: dict[str, Any]) -> float:
    if not manifest["manifest_readable"]:
        return 0.0
    status = (manifest["assembly_intent"] or {}).get("status")
    if status in ("single_piece_ready", "multipart_ready"):
        return 100.0
    if status == "multipart_incomplete":
        return 50.0
    if status == "no_option_selected":
        return 25.0
    return 60.0  # readable manifest, no build_plan/assembly_intent computed yet


def _manufacturing_score(manifest: dict[str, Any]) -> float:
    part_count = manifest["part_count"] or 1
    material_resolved_fraction = 1 - (len(manifest["unresolved_material_parts"]) / part_count)
    color_resolved_fraction = 1 - (len(manifest["unresolved_color_parts"]) / part_count)
    material_score = 100.0 * (material_resolved_fraction + color_resolved_fraction) / 2
    printer_score = 100.0 if manifest["printer_resolved"] else 0.0
    return (material_score + printer_score) / 2


def _receipts_score(receipts: dict[str, Any]) -> float:
    present = sum([receipts["generation_receipt_present"], receipts["export_receipt_present"]])
    return 50.0 * present


def _review_gate_score(review_gate_result: str) -> float:
    return {"pass": 100.0, "warn": 60.0, "fail": 0.0}.get(review_gate_result, 0.0)


def _overall_score(sub_scores: dict[str, float]) -> int:
    total = sum(sub_scores[name] * weight for name, weight in CATEGORY_WEIGHTS.items())
    return round(total)


# ---------------------------------------------------------------------------
# Readiness status - priority order, first match wins. Mirrors the exact
# style of factory.generation_gate.evaluate_generation_gate() and
# factory.export_pipeline.plan_export(): a fixed, documented decision
# ladder rather than an ad hoc combination of conditions.
# ---------------------------------------------------------------------------


def _evaluate_readiness_status(
    *,
    review_gate_result: dict[str, Any],
    design_orchestrator_summary: dict[str, Any] | None,
    stl: dict[str, Any],
    validation: dict[str, Any],
    preview: dict[str, Any],
    manifest: dict[str, Any],
    approval_status: str,
    package_status: str,
    blocking_reasons: list[str],
    warnings: list[str],
) -> str:
    """See docs/slicer-readiness.md "Decision states" for the full
    reasoning behind this exact order.
    """
    if review_gate_result["result"] == "fail":
        blocking_reasons.extend(item["message"] for item in review_gate_result["blocking_items"])
        return "blocked"
    if validation["failure_count"] > 0:
        blocking_reasons.append(f"{validation['failure_count']} STL(s) failed validation - fix the underlying geometry before proceeding.")
        return "blocked"
    if manifest["assembly_intent"] and manifest["assembly_intent"].get("multipart_incomplete"):
        blocking_reasons.append(manifest["assembly_intent"]["note"])
        return "blocked"

    if stl["expected"] == 0 or (stl["current"] == 0 and stl["missing"] > 0 and stl["stale"] == 0):
        blocking_reasons.append("No current STL exists yet - run `factory export-from-cad --confirm-export` first.")
        return "not_ready"
    if stl["stale"] > 0 or preview["stale"] > 0:
        blocking_reasons.append(
            f"{stl['stale']} STL(s) and {preview['stale']} preview(s) are stale relative to their source - re-export/re-render before proceeding."
        )
        return "stale_artifacts"
    if stl["missing"] > 0:
        blocking_reasons.append(f"{stl['missing']} required STL(s) are still missing.")
        return "not_ready"
    if validation["not_run_count"] > 0 or (validation["pass_count"] + validation["warning_count"] + validation["failure_count"]) < stl["current"]:
        blocking_reasons.append("Validation has not run for every current STL yet.")
        return "needs_validation"
    if preview["missing"] > 0:
        blocking_reasons.append(f"{preview['missing']} required preview render(s) are missing.")
        return "needs_preview"
    if not manifest["manifest_readable"]:
        blocking_reasons.append("part_manifest.json is missing or unreadable.")
        return "needs_manifest_completion"
    if manifest["unresolved_material_parts"] or manifest["unresolved_color_parts"] or not manifest["printer_resolved"]:
        if manifest["unresolved_material_parts"]:
            warnings.append(f"Material unconfirmed for: {', '.join(manifest['unresolved_material_parts'])}.")
        if manifest["unresolved_color_parts"]:
            warnings.append(f"Color unconfirmed for: {', '.join(manifest['unresolved_color_parts'])}.")
        if not manifest["printer_resolved"]:
            warnings.append("Target printer is not resolved/confirmed.")
        return "needs_manifest_completion"

    # Review Gate's own semantics (docs/review-gate.md): "warn" is
    # explicitly *not* blocking - only "fail" (handled above) prevents
    # slicer review. A warn result is preserved visibly in `warnings` but
    # never itself gates progression to approval - preserving a review-gate
    # warning invisibly, or silently upgrading it to a blocker, would both
    # contradict review_gate.py's own documented result semantics.
    if review_gate_result["result"] == "warn":
        warnings.extend(item["message"] for item in review_gate_result["warning_items"])
    if validation["warning_count"] > 0:
        warnings.append(f"{validation['warning_count']} STL(s) passed validation with warnings - review before approving.")

    # Every physical artifact checks out, but the underlying project intake/
    # design intent (Phase 33's Design Orchestrator) may still be thin -
    # e.g. a bare-bones brief that was hand-advanced straight to CAD
    # generation without fleshing out design intent. This is a genuinely
    # different signal from any check above: the *files* are fine, the
    # *design record* is not.
    #
    # "Needs Information" is Phase 33's ordinary, common resting state for
    # most projects before design-intent polish - gating approval on it
    # would be overly strict, so it is folded into `warnings` only, same
    # as review-gate's own "warn" above. Only "Not Ready" (a much lower
    # bar - overall score < 25%, see docs/design-orchestrator.md) gates
    # here; it is the one state genuinely thin enough to hold off approval
    # for, without yet being a hard blocker.
    orchestrator_state = (design_orchestrator_summary or {}).get("readiness_state")
    if orchestrator_state == "Needs Information":
        warnings.append(
            "Project readiness (Phase 33) is still 'Needs Information' - design intent/brief may be "
            "thin even though physical artifacts are ready. See `factory readiness`."
        )
    elif orchestrator_state == "Not Ready":
        warnings.append(
            "Project readiness (Phase 33) is 'Not Ready' - design intent/brief is thin even though "
            "physical artifacts are ready. See `factory readiness`."
        )
        return "needs_information"

    if approval_status not in ("approved",):
        return "needs_human_approval"
    if package_status in ("current",):
        return "review_package_created"
    return "ready_for_review_package"


# ---------------------------------------------------------------------------
# Public assessment entry point
# ---------------------------------------------------------------------------


def assess_slicer_readiness(project_dir: Path) -> dict[str, Any]:
    """The core, read-only slicer-review-readiness assessment. Never writes
    anything, never invokes a slicer, never creates a package, never
    records approval. Reuses `factory.project_inspection.summarize_project()`,
    `factory.review_gate.evaluate_review_gate()`, and
    `factory.slicer.local_slicer_probe.probe_slicers()` rather than
    re-deriving any of their logic.
    """
    project_dir = Path(project_dir)

    project_summary = summarize_project(project_dir)
    review_gate_result = evaluate_review_gate(project_dir)
    export_summary = project_summary.get("export_pipeline_summary") or {}
    export_receipt = _read_export_receipt(project_dir)

    stl = _stl_assessment(export_summary)
    validation = _validation_assessment(project_dir, export_receipt)
    preview = _preview_assessment(export_receipt)
    manifest = _manifest_assessment(project_dir)
    receipts = _receipts_assessment(project_dir, export_receipt)

    readiness_receipt = read_slicer_readiness_receipt(project_dir)
    approval_status, approval_note = _current_approval_status(project_dir, readiness_receipt)
    package_status, package_path = _current_package_status(project_dir, readiness_receipt)

    blocking_reasons: list[str] = []
    warnings: list[str] = []
    advisories: list[str] = []

    readiness_status = _evaluate_readiness_status(
        review_gate_result=review_gate_result,
        design_orchestrator_summary=project_summary.get("design_orchestrator_summary"),
        stl=stl,
        validation=validation,
        preview=preview,
        manifest=manifest,
        approval_status=approval_status,
        package_status=package_status,
        blocking_reasons=blocking_reasons,
        warnings=warnings,
    )

    sub_scores = {
        "stl": _stl_score(stl),
        "validation": _validation_score(validation),
        "preview": _preview_score(preview),
        "manifest": _manifest_score(manifest),
        "manufacturing": _manufacturing_score(manifest),
        "receipts": _receipts_score(receipts),
        "review_gate": _review_gate_score(review_gate_result["result"]),
    }
    readiness_score = _overall_score(sub_scores)

    detected_slicers = probe_slicers()
    if not any(s["found"] for s in detected_slicers):
        advisories.append(
            "No local slicer detected - a review package may still be created; slicer detection is "
            "advisory only, never required for technical package readiness."
        )

    next_actions = _next_actions(readiness_status, manifest, validation)

    ready_for_slicer_review = readiness_status in _READY_STATES

    return {
        "project_path": str(project_dir),
        "project_name": project_summary.get("project_name"),
        "readiness_status": readiness_status,
        "readiness_score": readiness_score,
        "readiness_sub_scores": sub_scores,
        "ready_for_slicer_review": ready_for_slicer_review,
        "human_approval_required": not ready_for_slicer_review or approval_status != "approved",
        "approval_recorded": approval_status == "approved",
        "approval_status": approval_status,
        "approval_note": approval_note,
        "stl_count": stl["expected"],
        "current_stl_count": stl["current"],
        "stale_stl_count": stl["stale"],
        "missing_stl_count": stl["missing"],
        "validation_status": _aggregate_label(validation),
        "validation_pass_count": validation["pass_count"],
        "validation_warning_count": validation["warning_count"],
        "validation_failure_count": validation["failure_count"],
        "preview_status": _aggregate_preview_label(preview),
        "current_preview_count": preview["current"],
        "stale_preview_count": preview["stale"],
        "missing_preview_count": preview["missing"],
        "manifest_status": "readable" if manifest["manifest_readable"] else "missing_or_unreadable",
        "manifest_complete": manifest["manifest_readable"]
        and not manifest["unresolved_material_parts"]
        and not manifest["unresolved_color_parts"]
        and manifest["printer_resolved"],
        "multipart_status": (manifest["assembly_intent"] or {}).get("status"),
        "material_status": "unresolved" if manifest["unresolved_material_parts"] or manifest["unresolved_color_parts"] else "confirmed",
        "printer_status": "confirmed" if manifest["printer_resolved"] else "unresolved",
        "export_receipt_status": "present" if receipts["export_receipt_present"] else "missing",
        "generation_receipt_status": "present" if receipts["generation_receipt_present"] else "missing",
        "manufacturing_status": manifest["selected_manufacturing_option"] is not None,
        "review_gate_status": review_gate_result["result"],
        "blockers": blocking_reasons,
        "warnings": warnings,
        "advisories": advisories,
        "next_actions": next_actions,
        "local_slicer_status": "detected" if any(s["found"] for s in detected_slicers) else "not_detected",
        "detected_slicers": detected_slicers,
        "package_available": package_status != "not_created",
        "package_status": package_status,
        "package_path": package_path,
        "dry_run": True,
        "no_automatic_print": True,
    }


def _aggregate_label(validation: dict[str, Any]) -> str:
    if validation["failure_count"] > 0:
        return "failed"
    if not validation["statuses"]:
        return "not_run"
    if validation["not_run_count"] > 0:
        return "partial"
    if validation["warning_count"] > 0:
        return "passed_with_warnings"
    return "passed"


def _aggregate_preview_label(preview: dict[str, Any]) -> str:
    if preview["missing"] > 0 and preview["current"] == 0:
        return "missing"
    if preview["stale"] > 0:
        return "stale"
    if preview["missing"] > 0:
        return "partial"
    if preview["current"] > 0:
        return "current"
    return "missing"


def _next_actions(readiness_status: str, manifest: dict[str, Any], validation: dict[str, Any]) -> list[str]:
    actions = {
        "unsupported_project_state": ["Fix the project's brief.json/part_manifest.json before assessing readiness."],
        "blocked": ["Resolve the blocking reason(s) above before proceeding."],
        "not_ready": ["Run `factory export-from-cad --confirm-export` to export the required STL(s)."],
        "stale_artifacts": ["Re-run `factory export-from-cad --confirm-export --overwrite-stl --all` to refresh stale artifacts."],
        "needs_validation": ["Run `factory export-from-cad --validate` (or `--all`) to validate every current STL."],
        "needs_preview": ["Run `factory export-from-cad --render` (or `--all`) to render every required preview."],
        "needs_manifest_completion": [],
        "needs_information": ["Review the review-gate warning(s) above."],
        "needs_human_approval": ["Review the assessment, then run `factory slicer-readiness <project> --approve` once satisfied."],
        "ready_for_review_package": ["Create a review package: `factory slicer-readiness <project> --create-package --confirm-package`."],
        "review_package_created": ["Open the parts in a local slicer for manual review - see slicer_review/README.md."],
    }.get(readiness_status, [])
    actions = list(actions)
    if readiness_status == "needs_manifest_completion":
        if not manifest["manifest_readable"]:
            actions.append("Ensure part_manifest.json exists and is valid JSON.")
        if manifest["unresolved_material_parts"]:
            actions.append("Confirm final material for: " + ", ".join(manifest["unresolved_material_parts"]))
        if manifest["unresolved_color_parts"]:
            actions.append("Confirm final color for: " + ", ".join(manifest["unresolved_color_parts"]))
        if not manifest["printer_resolved"]:
            actions.append("Resolve the target printer in build_plan.json (see `factory plan`).")
    return actions


def _read_export_receipt(project_dir: Path) -> dict[str, Any] | None:
    from factory.export_pipeline import read_export_receipt

    return read_export_receipt(project_dir)


def read_slicer_readiness_receipt(project_dir: Path) -> dict[str, Any] | None:
    """Read-only: `<project_dir>/generated/slicer_readiness_receipt.json` if
    it exists, else `None`. Never writes, never triggers approval or
    package creation.
    """
    receipt_path = Path(project_dir) / GENERATED_DIRNAME / READINESS_RECEIPT_FILENAME
    if not receipt_path.is_file():
        return None
    try:
        return project_store.load_json(receipt_path)
    except (OSError, ValueError):
        return None


def _current_approval_status(project_dir: Path, readiness_receipt: dict[str, Any] | None) -> tuple[str, str | None]:
    """`"not_approved"` / `"approved"` / `"invalidated"` - approval is
    automatically invalidated (never silently trusted) the moment any
    recorded artifact fingerprint no longer matches the current one.
    """
    if not readiness_receipt or not readiness_receipt.get("approval", {}).get("approved"):
        return "not_approved", None

    approval = readiness_receipt["approval"]
    recorded_fingerprints = readiness_receipt.get("artifact_fingerprints", {})
    for rel_path, recorded_fp in recorded_fingerprints.items():
        current_path = Path(project_dir) / rel_path
        if not current_path.is_file():
            return "invalidated", approval.get("note")
        if _file_fingerprint(current_path) != recorded_fp:
            return "invalidated", approval.get("note")
    return "approved", approval.get("note")


def _current_package_status(project_dir: Path, readiness_receipt: dict[str, Any] | None) -> tuple[str, str | None]:
    """`"not_created"` / `"current"` / `"stale"` / `"unknown"`."""
    package_path = Path(project_dir) / SLICER_REVIEW_DIRNAME / REVIEW_PACKAGE_FILENAME
    if not package_path.is_file():
        return "not_created", None

    if not readiness_receipt or not readiness_receipt.get("package"):
        return "unknown", _relative_path(package_path, project_dir)

    recorded_fingerprints = readiness_receipt.get("package", {}).get("artifact_fingerprints", {})
    for rel_path, recorded_fp in recorded_fingerprints.items():
        current_path = Path(project_dir) / rel_path
        if not current_path.is_file() or _file_fingerprint(current_path) != recorded_fp:
            return "stale", _relative_path(package_path, project_dir)
    return "current", _relative_path(package_path, project_dir)


def evaluate_slicer_readiness_for_path(path: Path) -> dict[str, Any]:
    """Convenience entry point `factory slicer-readiness <path>` uses."""
    return assess_slicer_readiness(path)


# ---------------------------------------------------------------------------
# Artifact fingerprint snapshot - shared by both write paths (approval and
# package creation) so the two always agree on what "the current relevant
# artifacts" means.
# ---------------------------------------------------------------------------


def _snapshot_artifact_fingerprints(project_dir: Path, export_receipt: dict[str, Any] | None) -> dict[str, str]:
    """Fingerprint every source CAD file and current STL the export receipt
    knows about, plus every validation report and render it references.
    Never fingerprints a stale or missing file - only what's actually on
    disk right now.
    """
    project_dir = Path(project_dir)
    fingerprints: dict[str, str] = {}
    for record in (export_receipt or {}).get("exports", []):
        for rel in (record.get("source_file"), record.get("output_stl")):
            if rel:
                path = project_dir / rel
                if path.is_file():
                    fingerprints[rel] = _file_fingerprint(path)
        validation_report = record.get("validation", {}).get("report_path")
        if validation_report and (project_dir / validation_report).is_file():
            fingerprints[validation_report] = _file_fingerprint(project_dir / validation_report)
        render_path = record.get("render", {}).get("render_path")
        if render_path and (project_dir / render_path).is_file():
            fingerprints[render_path] = _file_fingerprint(project_dir / render_path)

    manifest_path = project_dir / "part_manifest.json"
    if manifest_path.is_file():
        fingerprints["part_manifest.json"] = _file_fingerprint(manifest_path)
    build_plan_path = project_dir / "build_plan.json"
    if build_plan_path.is_file():
        fingerprints["build_plan.json"] = _file_fingerprint(build_plan_path)

    return fingerprints


def write_slicer_readiness_receipt(project_dir: Path, updates: dict[str, Any]) -> Path:
    """Upsert `generated/slicer_readiness_receipt.json` - merges `updates`
    into whatever's already there (never wholesale-replaces an unrelated
    top-level key such as a prior `package` block when only recording a
    new `approval`, and vice versa).
    """
    project_dir = Path(project_dir)
    receipt_path = project_dir / GENERATED_DIRNAME / READINESS_RECEIPT_FILENAME
    receipt = read_slicer_readiness_receipt(project_dir) or {"project": str(project_dir), "no_automatic_print": True}
    receipt.update(updates)
    receipt["no_automatic_print"] = True
    receipt["updated_at"] = project_store.utc_now_iso()
    project_store.save_json(receipt_path, receipt)
    return receipt_path


class ApprovalNotAllowedError(Exception):
    """Raised when `record_approval()` is called on a project that has not
    yet reached technical readiness - approval must never be recordable
    on a blocked/not-ready project, and this exception is the defensive
    guard against a caller (CLI or otherwise) skipping that check.
    """


def record_approval(project_dir: Path, *, note: str | None = None, approved_by: str | None = None) -> dict[str, Any]:
    """Explicitly record human approval for slicer review. Writes
    `generated/slicer_readiness_receipt.json` only - never invokes a
    slicer, never creates a print job, never implies print authorization
    (see `NO_AUTOMATIC_PRINT_LINES`).

    Only allowed once every technical signal is already satisfied
    (`readiness_status in ("needs_human_approval", "ready_for_review_package",
    "review_package_created")`) - raises `ApprovalNotAllowedError` on a
    blocked/not-ready project rather than silently recording an approval
    that doesn't mean anything yet.
    """
    project_dir = Path(project_dir)
    assessment = assess_slicer_readiness(project_dir)
    if assessment["readiness_status"] not in ("needs_human_approval", "ready_for_review_package", "review_package_created"):
        raise ApprovalNotAllowedError(
            f"cannot record approval - readiness_status is {assessment['readiness_status']!r}, "
            f"not technically ready yet. Blockers: {assessment['blockers']}"
        )

    export_receipt = _read_export_receipt(project_dir)
    fingerprints = _snapshot_artifact_fingerprints(project_dir, export_receipt)

    approval = {
        "approved": True,
        "approved_by": approved_by,
        "approved_at": project_store.utc_now_iso(),
        "note": note,
    }
    receipt_path = write_slicer_readiness_receipt(
        project_dir,
        {
            "technical_readiness": assessment["readiness_status"],
            "readiness_score": assessment["readiness_score"],
            "approval": approval,
            "artifact_fingerprints": fingerprints,
        },
    )
    return {"receipt_path": str(receipt_path), "approval": approval, "artifact_fingerprints": fingerprints}


# ---------------------------------------------------------------------------
# Review checklist - tailored only from already-known project data; never
# invents a recommendation the project's own data doesn't support.
# ---------------------------------------------------------------------------


def build_review_checklist(project_dir: Path, assessment: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    multipart = manifest["part_count"] > 1
    printer_name = manifest.get("printer_display_name")

    items = [
        "Project identity: confirm project name and version.",
        "Project identity: confirm the correct STL set is loaded.",
        "Geometry: inspect all parts in the slicer.",
        "Geometry: verify scale and dimensions match the intended measurements.",
        "Geometry: verify there are no unintended disconnected shells.",
        "Geometry: review any wall-thickness warnings from validation.",
        "Geometry: verify expected holes, slots, and clearances.",
        "Orientation: choose print orientation for each part.",
        "Orientation: confirm support requirements.",
        "Orientation: review overhangs and bridges.",
        "Material: confirm filament type.",
        "Material: confirm filament color.",
    ]
    if multipart:
        items.append("Material: confirm multi-material assignments across parts.")
        items.append("Material: confirm AMS slot mapping where applicable.")
    items.extend(
        [
            f"Printer: confirm target printer{f' ({printer_name})' if printer_name else ''}.",
            "Printer: confirm build-volume fit.",
            "Printer: confirm nozzle size.",
            "Printer: confirm layer height.",
            "Print strategy: review infill.",
            "Print strategy: review walls/perimeters.",
            "Print strategy: review top and bottom layers.",
            "Print strategy: review adhesion strategy.",
        ]
    )
    if multipart:
        items.append("Print strategy: review purge and prime behavior for multi-color printing.")
    items.extend(
        [
            "Risk: confirm tolerances for mechanical parts.",
            "Risk: confirm fragile features.",
            "Risk: confirm moving parts or clips.",
            "Risk: confirm safety-sensitive geometry.",
            "Approval: human slicer review completed.",
            "Approval: no automatic printing occurred.",
            "Approval: print submission remains a separate, explicit action.",
        ]
    )
    return items


# ---------------------------------------------------------------------------
# Review package creation - the one other write path. Conforms to the
# pre-existing schemas/slicer_review.schema.json (project_name, status,
# parts_for_review, human_checklist, human_approval, auto_print_allowed)
# rather than inventing a new, incompatible shape.
# ---------------------------------------------------------------------------


class PackageNotAllowedError(Exception):
    """Raised when `create_review_package()` is called while a hard blocker
    is present, or without prior approval.
    """


class PackageCollisionError(Exception):
    """Raised when a review package already exists and `overwrite=False`."""


def create_review_package(
    project_dir: Path, *, output_dir: str | None = None, overwrite: bool = False
) -> dict[str, Any]:
    """Write `slicer_review/slicer_review_manifest.json` (schema-conformant)
    plus a human-readable `slicer_review/README.md` checklist. **References
    existing STL/validation/render files by relative path - never copies
    them**, mirroring `factory.preview_package`'s own established
    "reference, don't duplicate" convention.

    Only allowed when `readiness_status` is `"ready_for_review_package"` or
    `"review_package_created"` (i.e. approved and technically ready) -
    raises `PackageNotAllowedError` otherwise. Never overwrites an existing
    package without `overwrite=True` (raises `PackageCollisionError`).
    Never touches source CAD, STL, validation, or render files.
    """
    project_dir = Path(project_dir)
    assessment = assess_slicer_readiness(project_dir)
    if assessment["readiness_status"] not in ("ready_for_review_package", "review_package_created"):
        raise PackageNotAllowedError(
            f"cannot create a review package - readiness_status is {assessment['readiness_status']!r}. "
            f"Blockers: {assessment['blockers']}"
        )

    package_dir = project_dir / (output_dir or SLICER_REVIEW_DIRNAME)
    package_path = package_dir / REVIEW_PACKAGE_FILENAME
    if package_path.is_file() and not overwrite:
        raise PackageCollisionError(f"{package_path} already exists - pass overwrite=True to replace it")

    manifest = _manifest_assessment(project_dir)
    export_receipt = _read_export_receipt(project_dir)
    readiness_receipt = read_slicer_readiness_receipt(project_dir)
    approval = (readiness_receipt or {}).get("approval") or {}

    parts_for_review = []
    manifest_path = project_dir / "part_manifest.json"
    manifest_json = project_store.load_json(manifest_path) if manifest_path.is_file() else {"parts": []}
    for part in manifest_json.get("parts", []):
        parts_for_review.append(
            {
                "part_name": part.get("part_name"),
                "file_path": part.get("file_path"),
                "material": part.get("material"),
                "color": part.get("color"),
            }
        )

    checklist = build_review_checklist(project_dir, assessment, manifest)
    fingerprints = _snapshot_artifact_fingerprints(project_dir, export_receipt)

    generation_receipt_path = (
        f"{GENERATED_DIRNAME}/generation_receipt.json" if assessment["generation_receipt_status"] == "present" else None
    )
    export_receipt_path = (
        f"{GENERATED_DIRNAME}/{EXPORT_RECEIPT_FILENAME}" if assessment["export_receipt_status"] == "present" else None
    )

    package_manifest = {
        "project_name": assessment["project_name"],
        "status": "slicer_review_ready",
        "parts_for_review": parts_for_review,
        "human_checklist": checklist,
        "human_approval": {
            "approved": bool(approval.get("approved")),
            "approved_by": approval.get("approved_by"),
            "approved_at": approval.get("approved_at"),
            "notes": approval.get("note"),
        },
        "auto_print_allowed": False,
        "readiness_score": assessment["readiness_score"],
        "readiness_status": assessment["readiness_status"],
        "artifact_fingerprints": fingerprints,
        "source_cad_references": [r.get("source_file") for r in (export_receipt or {}).get("exports", [])],
        "generation_receipt_path": generation_receipt_path,
        "export_receipt_path": export_receipt_path,
        "warnings": list(assessment["warnings"]),
        "no_automatic_print": True,
    }

    project_store.save_json(package_path, package_manifest)
    readme_path = package_dir / REVIEW_PACKAGE_README_FILENAME
    readme_path.write_text(_render_package_readme(assessment, checklist), encoding="utf-8")

    write_slicer_readiness_receipt(
        project_dir,
        {
            "package": {
                "package_path": _relative_path(package_path, project_dir),
                "artifact_fingerprints": fingerprints,
                "created_at": project_store.utc_now_iso(),
            }
        },
    )

    return {
        "package_path": str(package_path),
        "readme_path": str(readme_path),
        "manifest": package_manifest,
    }


def _render_package_readme(assessment: dict[str, Any], checklist: list[str]) -> str:
    lines = [
        f"# Slicer Review Package - {assessment['project_name']}",
        "",
        f"Readiness score: {assessment['readiness_score']}% ({assessment['readiness_status']})",
        "",
        "## Human checklist",
        "",
    ]
    lines.extend(f"- [ ] {item}" for item in checklist)
    lines.append("")
    lines.append("## Warnings to review")
    lines.append("")
    if assessment["warnings"]:
        lines.extend(f"- {w}" for w in assessment["warnings"])
    else:
        lines.append("None recorded.")
    lines.append("")
    lines.append("## No automatic print")
    lines.append("")
    lines.extend(NO_AUTOMATIC_PRINT_LINES)
    lines.append("")
    return "\n".join(lines)


def summarize_slicer_readiness(project_dir: Path) -> dict[str, Any]:
    """Compact, read-only summary for the Preview Board's "Slicer Review
    Readiness" card (and any other caller that just wants the headline
    fields, not the full `assess_slicer_readiness()` payload). Never
    exports, validates, renders, approves, packages, or invokes a
    subprocess/slicer.

    **Architectural note - why this isn't a `factory.project_inspection`
    field:** every other Phase 26-35 additive summary lives on
    `summarize_project()` because `project_inspection.py` is the shared
    base layer those phases sit *below*. This phase is different: per the
    task's own requirement to consume the existing Review Gate result
    without rewriting it, `assess_slicer_readiness()` calls
    `factory.review_gate.evaluate_review_gate()` directly - and
    `review_gate.py` itself already imports
    `factory.project_inspection.summarize_project()`. Adding a
    `slicer_readiness_summary` field computed via this module *inside*
    `project_inspection.py` would therefore create a genuine circular
    import (`project_inspection -> slicer_readiness -> review_gate ->
    project_inspection`) - confirmed by actually attempting it. This
    module sits **above** `project_inspection.py` in the dependency graph
    (a top-level consumer, like `review_gate.py` and `preview_board.py`
    already are), not beneath it. `factory.preview_board.gather_board_data()`
    calls this function directly per project and merges its result into
    that project's dict alongside every other summary - the same visible
    effect as an additive `project_inspection` field, from a different,
    architecturally necessary layer. See docs/slicer-readiness.md
    "Architectural note".
    """
    assessment = assess_slicer_readiness(project_dir)
    return {
        "status": assessment["readiness_status"],
        "score": assessment["readiness_score"],
        "ready_for_package": assessment["readiness_status"] in ("ready_for_review_package", "review_package_created"),
        "human_approval_required": assessment["human_approval_required"],
        "approval_status": assessment["approval_status"],
        "stl_status": "current" if assessment["current_stl_count"] == assessment["stl_count"] and assessment["stl_count"] > 0 else ("stale" if assessment["stale_stl_count"] else "missing"),
        "validation_status": assessment["validation_status"],
        "preview_status": assessment["preview_status"],
        "manifest_status": "complete" if assessment["manifest_complete"] else "incomplete",
        "package_status": assessment["package_status"],
        "blocker_count": len(assessment["blockers"]),
        "warning_count": len(assessment["warnings"]),
        "next_action": assessment["next_actions"][0] if assessment["next_actions"] else None,
    }

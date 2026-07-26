"""Phase 37: Slicer Profile Inspection & Manual Review Workspace.

The Factory's first true pre-slicer review workspace - organizes
everything a human needs before opening Bambu Studio, OrcaSlicer, or
another slicer:

    Guided Export Pipeline -> STL Validation and Preview ->
    Slicer Review Readiness -> Human Approval -> Review Package ->
    Manual Review Workspace -> Human Slicer Review ->
    (never automatic printing)

**This is a thin organizing layer over already-computed state - it never
re-implements mesh validation, the artifact registry, the preview
package, Review Gate logic, slicer discovery, or receipt tracking.** It
reuses `factory.slicer_readiness.assess_slicer_readiness()` directly (which
itself already reuses `factory.project_inspection.summarize_project()`,
`factory.review_gate.evaluate_review_gate()`, and
`factory.slicer.local_slicer_probe.probe_slicers()`), plus
`factory.manufacturing.knowledge` for local printer/material reference
data. It adds two genuinely new things this repo did not have before:

1. A **printer/material profile inspection** - what's actually known
   locally about the project's target printer (nozzle, build volume, AMS
   availability) and materials (from `part_manifest.json`, cross-referenced
   against the local materials knowledge base), always reporting
   `"Unknown"` rather than inventing a value that isn't actually known.
2. A **structured, multi-category human review checklist** (Geometry,
   Scale, Orientation, Supports, Walls, Top/Bottom, Infill, Material,
   Color, AMS, Multipart Assembly, Moving Parts, Tolerances, Clearances,
   Fragile Features, Build Volume, Estimated Risks, Human Approval) plus a
   deterministic `review_confidence`/`remaining_risk` pair - richer than
   Phase 36's flat checklist, but never inventing a category item the
   project's own data doesn't support.

**Read-only unless explicitly creating a workspace.**
`assess_manual_review_workspace()` never writes anything. Only
`create_manual_review_workspace()` writes, and only when explicitly
called (the CLI gates it behind `--create-workspace --confirm-workspace`).

**This phase does NOT slice, does NOT generate G-code, and does NOT
print.** It only prepares an organized local review workspace -
`manual_review/review_manifest.json`'s `auto_print_allowed` field is
always `false`, reusing `factory.slicer_readiness.NO_AUTOMATIC_PRINT_LINES`
rather than re-declaring the same guarantee differently. See
`docs/manual-review-workspace.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import project_store
from factory.export_pipeline import EXPORT_RECEIPT_FILENAME, GENERATED_DIRNAME, read_export_receipt
from factory.manufacturing import knowledge
from factory.slicer_readiness import (
    NO_AUTOMATIC_PRINT_LINES,
    REVIEW_PACKAGE_FILENAME,
    SLICER_REVIEW_DIRNAME,
    assess_slicer_readiness,
    file_fingerprint,
    manifest_assessment,
    relative_path,
)

WORKSPACE_STATES = (
    "not_ready",
    "needs_approval",
    "ready_to_create",
    "stale_workspace",
    "workspace_created",
)

# States in which the underlying Phase 36 assessment is ready enough to
# stand behind and actually create a package/workspace - the same gate
# `create_review_package()` uses, reused rather than re-derived, since a
# workspace is never more permissive than the package it organizes.
_READY_STATES = ("ready_for_review_package", "review_package_created")

# `needs_human_approval` plus both `_READY_STATES` - every technical
# signal is already satisfied in all three; they differ only by whether
# approval has been recorded yet (slicer_readiness.py's own ladder ties
# approval_status and readiness_status together: unapproved -> exactly
# "needs_human_approval", approved -> exactly one of `_READY_STATES`). Use
# this broader set - not `_READY_STATES` alone - whenever "is this
# workspace-eligible once approved" is the actual question, e.g. computing
# `workspace_status`'s `not_ready` vs. `needs_approval` split.
_TECHNICALLY_READY_STATES = ("needs_human_approval",) + _READY_STATES

WORKSPACE_DIRNAME = "manual_review"
WORKSPACE_MANIFEST_FILENAME = "review_manifest.json"
WORKSPACE_README_FILENAME = "README.md"

# generated/manual_review_workspace_receipt.json - a fourth sibling of
# Phase 34's generation receipt, Phase 35's export receipt, and Phase 36's
# slicer readiness receipt. Holds only workspace creation state (path +
# artifact fingerprints); never restructures or overwrites any earlier
# receipt.
WORKSPACE_RECEIPT_FILENAME = "manual_review_workspace_receipt.json"

_CONFIDENCE_LEVELS = ("High", "Medium", "Low", "Unknown")
_RISK_LEVELS = ("Low", "Moderate", "High", "Unknown")

_UNRESOLVED_MATERIAL_MARKERS = ("tbd", "unresolved", "unknown")


def _is_unresolved(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return True
    lowered = value.lower()
    return any(marker in lowered for marker in _UNRESOLVED_MATERIAL_MARKERS)


# ---------------------------------------------------------------------------
# Printer profile inspection - reuses factory.manufacturing.knowledge
# (the existing local printer/accessory knowledge base) rather than
# inventing a second printer data source. Never contacts, discovers, or
# configures real hardware; never installs or launches a slicer.
# ---------------------------------------------------------------------------


def _printer_profile(build_plan: dict[str, Any]) -> dict[str, Any]:
    """What's actually known locally about the project's target printer.

    Reuses `factory.manufacturing.knowledge.get_printer()`/
    `printer_capabilities()` - never a second lookup table. Layer height is
    never present in this repo's printer knowledge base (it's a per-print
    slicer-profile choice, not a printer hardware attribute), so it is
    always reported as `"Unknown"` rather than guessed from a default.
    """
    target_printer = build_plan.get("target_printer") or {}
    if not target_printer.get("resolved"):
        return {
            "resolved": False,
            "printer_id": None,
            "display_name": "Unknown",
            "nozzle_mm": "Unknown",
            "layer_height_mm": "Unknown",
            "build_volume_mm": "Unknown",
            "ams_available": "Unknown",
            "multicolor_supported": "Unknown",
        }

    printer_id = target_printer.get("printer_id")
    printer = knowledge.get_printer(printer_id) if printer_id else None
    if printer is None:
        return {
            "resolved": True,
            "printer_id": printer_id,
            "display_name": target_printer.get("display_name") or "Unknown",
            "nozzle_mm": "Unknown",
            "layer_height_mm": "Unknown",
            "build_volume_mm": "Unknown",
            "ams_available": "Unknown",
            "multicolor_supported": "Unknown",
        }

    capabilities = knowledge.printer_capabilities(printer)
    return {
        "resolved": True,
        "printer_id": printer_id,
        "display_name": printer.get("display_name") or "Unknown",
        "nozzle_mm": printer.get("default_nozzle_mm", "Unknown"),
        "layer_height_mm": "Unknown",
        "build_volume_mm": printer.get("build_volume_mm") or "Unknown",
        "ams_available": capabilities["ams_supported"],
        "multicolor_supported": capabilities["multicolor_supported"],
    }


def _material_profile_lookup(material_value: str) -> dict[str, Any] | None:
    """Best-effort, exact (case-insensitive) match of a manifest material
    string against the local materials knowledge base. Never fuzzy-matches
    and never invents a profile for an unresolved/unmatched value - returns
    `None` rather than guessing.
    """
    if _is_unresolved(material_value):
        return None
    needle = material_value.strip().lower()
    for material in knowledge.load_materials().values():
        candidates = {str(material.get("material_id", "")).lower(), str(material.get("display_name", "")).lower()}
        if needle in candidates:
            return {
                "material_id": material.get("material_id"),
                "display_name": material.get("display_name"),
                "category": material.get("category"),
                "strength_class": material.get("strength_class"),
            }
    return None


def _material_summary(manifest_json: dict[str, Any]) -> dict[str, Any]:
    """Per-part material/color state, cross-referenced against the local
    materials knowledge base where a confident match exists. Reuses the
    same `"TBD - human decision"`/unresolved-marker convention
    `factory.slicer_readiness` already established - never a second
    definition of "unresolved".
    """
    parts = manifest_json.get("parts", []) if isinstance(manifest_json.get("parts"), list) else []
    part_summaries = []
    unresolved_material_parts = []
    unresolved_color_parts = []
    distinct_materials = set()

    for part in parts:
        part_name = part.get("part_name")
        material = part.get("material")
        color = part.get("color")
        material_unresolved = _is_unresolved(material)
        color_unresolved = _is_unresolved(color)
        if material_unresolved:
            unresolved_material_parts.append(part_name)
        else:
            distinct_materials.add(material.strip().lower())
        if color_unresolved:
            unresolved_color_parts.append(part_name)

        part_summaries.append(
            {
                "part_name": part_name,
                "material": material,
                "color": color,
                "material_profile": None if material_unresolved else _material_profile_lookup(material),
            }
        )

    return {
        "parts": part_summaries,
        "unresolved_material_parts": unresolved_material_parts,
        "unresolved_color_parts": unresolved_color_parts,
        "multi_material": len(distinct_materials) > 1,
        "part_count": len(parts),
    }


# ---------------------------------------------------------------------------
# Structured, multi-category review checklist - richer than Phase 36's
# flat list, but every category is included only when the project's own
# data actually supports it (never invented).
# ---------------------------------------------------------------------------


def build_structured_review_checklist(
    *, printer_profile: dict[str, Any], material_summary: dict[str, Any], manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    multipart = manifest["part_count"] > 1
    ams_relevant = printer_profile.get("ams_available") is True or material_summary["multi_material"]
    printer_known = bool(printer_profile.get("resolved")) and printer_profile.get("display_name") != "Unknown"
    build_volume_known = printer_known and isinstance(printer_profile.get("build_volume_mm"), dict)

    categories: list[dict[str, Any]] = [
        {
            "category": "Geometry",
            "items": [
                "Inspect all parts in the slicer.",
                "Verify there are no unintended disconnected shells.",
                "Review any wall-thickness warnings from validation.",
                "Verify expected holes, slots, and clearances.",
            ],
        },
        {
            "category": "Scale",
            "items": ["Verify scale and dimensions match the intended measurements."],
        },
        {
            "category": "Orientation",
            "items": [
                "Choose print orientation for each part.",
                "Review overhangs and bridges.",
            ],
        },
        {
            "category": "Supports",
            "items": ["Confirm support requirements and placement."],
        },
        {
            "category": "Walls",
            "items": ["Review wall/perimeter count and thickness."],
        },
        {
            "category": "Top/Bottom",
            "items": ["Review top and bottom layer count."],
        },
        {
            "category": "Infill",
            "items": ["Review infill density and pattern."],
        },
        {
            "category": "Material",
            "items": [f"Confirm filament type for {p['part_name']} ({p['material']})." for p in material_summary["parts"]]
            or ["Confirm filament type."],
        },
        {
            "category": "Color",
            "items": [f"Confirm color for {p['part_name']} ({p['color']})." for p in material_summary["parts"]]
            or ["Confirm color."],
        },
    ]

    if ams_relevant:
        categories.append(
            {
                "category": "AMS",
                "items": [
                    "Confirm AMS slot mapping for each material/color.",
                    "Confirm purge/prime tower behavior for multi-color printing.",
                ],
            }
        )

    if multipart:
        categories.append(
            {
                "category": "Multipart Assembly",
                "items": [
                    "Confirm the correct STL set for every part is loaded.",
                    "Confirm shared-origin/assembly alignment between parts.",
                ],
            }
        )

    categories.extend(
        [
            {
                "category": "Moving Parts",
                "items": ["Confirm clearance and fit for any moving parts, clips, or hinges - treat as prototype until physically tested."],
            },
            {
                "category": "Tolerances",
                "items": ["Confirm tolerances for mechanical/fitted parts."],
            },
            {
                "category": "Clearances",
                "items": ["Confirm clearances between adjacent or interlocking features."],
            },
            {
                "category": "Fragile Features",
                "items": ["Confirm fragile features (thin walls, small protrusions) are accounted for in orientation/supports."],
            },
        ]
    )

    if build_volume_known:
        volume = printer_profile["build_volume_mm"]
        categories.append(
            {
                "category": "Build Volume",
                "items": [f"Confirm parts fit within the target printer's build volume ({volume})."],
            }
        )
    elif printer_known:
        categories.append(
            {
                "category": "Build Volume",
                "items": ["Confirm parts fit within the target printer's build volume (dimensions not recorded locally)."],
            }
        )

    categories.extend(
        [
            {
                "category": "Estimated Risks",
                "items": ["Review the warnings and remaining_risk assessment below before proceeding."],
            },
            {
                "category": "Human Approval",
                "items": [
                    "Human slicer review completed.",
                    "No automatic printing occurred.",
                    "Print submission remains a separate, explicit action.",
                ],
            },
        ]
    )

    return categories


# ---------------------------------------------------------------------------
# Review confidence / remaining risk - purely deterministic, derived from
# the already-computed Phase 36 assessment plus printer/material
# resolution. Never a re-score of readiness itself.
# ---------------------------------------------------------------------------


def _review_confidence(assessment: dict[str, Any], printer_profile: dict[str, Any], material_summary: dict[str, Any]) -> str:
    if assessment["readiness_status"] == "unsupported_project_state":
        return "Unknown"
    if assessment["readiness_status"] not in _TECHNICALLY_READY_STATES:
        return "Low"
    fully_resolved = (
        assessment["readiness_score"] >= 85
        and printer_profile["resolved"]
        and not material_summary["unresolved_material_parts"]
        and not material_summary["unresolved_color_parts"]
        and assessment["validation_warning_count"] == 0
        and not assessment["warnings"]
    )
    return "High" if fully_resolved else "Medium"


def _remaining_risk(assessment: dict[str, Any], printer_profile: dict[str, Any], material_summary: dict[str, Any]) -> str:
    if assessment["readiness_status"] == "unsupported_project_state":
        return "Unknown"
    if assessment["readiness_status"] in ("blocked", "not_ready", "stale_artifacts", "needs_validation", "needs_preview"):
        return "High"

    risk_points = 0
    if not printer_profile["resolved"]:
        risk_points += 1
    if material_summary["unresolved_material_parts"] or material_summary["unresolved_color_parts"]:
        risk_points += 1
    if assessment["validation_warning_count"] > 0:
        risk_points += 1

    if risk_points == 0:
        return "Low"
    if risk_points <= 2:
        return "Moderate"
    return "High"


# ---------------------------------------------------------------------------
# Compact per-category summaries - thin extracts of the already-computed
# assessment, never re-derived independently.
# ---------------------------------------------------------------------------


def _stl_summary(assessment: dict[str, Any]) -> dict[str, Any]:
    return {
        "expected": assessment["stl_count"],
        "current": assessment["current_stl_count"],
        "stale": assessment["stale_stl_count"],
        "missing": assessment["missing_stl_count"],
    }


def _preview_summary(assessment: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": assessment["preview_status"],
        "current": assessment["current_preview_count"],
        "stale": assessment["stale_preview_count"],
        "missing": assessment["missing_preview_count"],
    }


def _validation_summary(assessment: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": assessment["validation_status"],
        "passed": assessment["validation_pass_count"],
        "passed_with_warnings": assessment["validation_warning_count"],
        "failed": assessment["validation_failure_count"],
    }


def _receipt_summary(assessment: dict[str, Any]) -> dict[str, Any]:
    return {
        "generation_receipt_status": assessment["generation_receipt_status"],
        "export_receipt_status": assessment["export_receipt_status"],
        "review_package_status": assessment["package_status"],
        "review_package_path": assessment["package_path"],
    }


# ---------------------------------------------------------------------------
# Workspace status - mirrors the exact style of
# factory.slicer_readiness's own state ladder: a fixed, documented priority
# order rather than an ad hoc combination of conditions.
# ---------------------------------------------------------------------------


def _compute_workspace_status(readiness_status: str, approval_status: str, workspace_file_status: str) -> str:
    if readiness_status not in _TECHNICALLY_READY_STATES:
        return "not_ready"
    if approval_status != "approved":
        return "needs_approval"
    if workspace_file_status == "current":
        return "workspace_created"
    if workspace_file_status == "stale":
        return "stale_workspace"
    return "ready_to_create"


def _next_actions(workspace_status: str) -> list[str]:
    return {
        "not_ready": ["Resolve technical readiness first - see `factory slicer-readiness <project>`."],
        "needs_approval": ["Record human approval - see `factory slicer-readiness <project> --approve`."],
        "ready_to_create": ["Create the manual review workspace: `factory review-workspace <project> --create-workspace --confirm-workspace`."],
        "stale_workspace": ["Re-create the workspace to reflect updated artifacts: `factory review-workspace <project> --create-workspace --confirm-workspace --force-workspace` (or a fresh `--output-dir`)."],
        "workspace_created": ["Open the parts in a local slicer for manual review - see manual_review/README.md."],
    }.get(workspace_status, [])


# ---------------------------------------------------------------------------
# Receipt read/write - a fourth sibling receipt, following the exact
# upsert-without-clobbering convention every prior phase's receipt uses.
# ---------------------------------------------------------------------------


def read_workspace_receipt(project_dir: Path) -> dict[str, Any] | None:
    """Read-only: `<project_dir>/generated/manual_review_workspace_receipt.json`
    if it exists, else `None`. Never writes, never triggers workspace
    creation."""
    receipt_path = Path(project_dir) / GENERATED_DIRNAME / WORKSPACE_RECEIPT_FILENAME
    if not receipt_path.is_file():
        return None
    try:
        return project_store.load_json(receipt_path)
    except (OSError, ValueError):
        return None


def _write_workspace_receipt(project_dir: Path, updates: dict[str, Any]) -> Path:
    project_dir = Path(project_dir)
    receipt_path = project_dir / GENERATED_DIRNAME / WORKSPACE_RECEIPT_FILENAME
    receipt = read_workspace_receipt(project_dir) or {"project": str(project_dir), "no_automatic_print": True}
    receipt.update(updates)
    receipt["no_automatic_print"] = True
    receipt["updated_at"] = project_store.utc_now_iso()
    project_store.save_json(receipt_path, receipt)
    return receipt_path


def _snapshot_workspace_fingerprints(project_dir: Path, export_receipt: dict[str, Any] | None) -> dict[str, str]:
    """Fingerprint every source CAD file, current STL, validation report,
    and render the export receipt knows about, plus `part_manifest.json`/
    `build_plan.json` and (if present) the Phase 36 review package itself -
    a workspace goes stale if any of those change, exactly the same
    convention `factory.slicer_readiness._snapshot_artifact_fingerprints()`
    already established for approval/package fingerprinting.
    """
    project_dir = Path(project_dir)
    fingerprints: dict[str, str] = {}
    for record in (export_receipt or {}).get("exports", []):
        for rel in (record.get("source_file"), record.get("output_stl")):
            if rel:
                path = project_dir / rel
                if path.is_file():
                    fingerprints[rel] = file_fingerprint(path)
        validation_report = record.get("validation", {}).get("report_path")
        if validation_report and (project_dir / validation_report).is_file():
            fingerprints[validation_report] = file_fingerprint(project_dir / validation_report)
        render_path = record.get("render", {}).get("render_path")
        if render_path and (project_dir / render_path).is_file():
            fingerprints[render_path] = file_fingerprint(project_dir / render_path)

    manifest_path = project_dir / "part_manifest.json"
    if manifest_path.is_file():
        fingerprints["part_manifest.json"] = file_fingerprint(manifest_path)
    build_plan_path = project_dir / "build_plan.json"
    if build_plan_path.is_file():
        fingerprints["build_plan.json"] = file_fingerprint(build_plan_path)
    package_path = project_dir / SLICER_REVIEW_DIRNAME / REVIEW_PACKAGE_FILENAME
    if package_path.is_file():
        fingerprints[relative_path(package_path, project_dir)] = file_fingerprint(package_path)

    return fingerprints


def _current_workspace_file_status(project_dir: Path, receipt: dict[str, Any] | None) -> tuple[str, str | None]:
    """`"not_created"` / `"current"` / `"stale"` / `"unknown"`."""
    workspace_path = Path(project_dir) / WORKSPACE_DIRNAME / WORKSPACE_MANIFEST_FILENAME
    if not workspace_path.is_file():
        return "not_created", None

    if not receipt or not receipt.get("workspace"):
        return "unknown", relative_path(workspace_path, project_dir)

    recorded_fingerprints = receipt.get("workspace", {}).get("artifact_fingerprints", {})
    for rel_path, recorded_fp in recorded_fingerprints.items():
        current_path = Path(project_dir) / rel_path
        if not current_path.is_file() or file_fingerprint(current_path) != recorded_fp:
            return "stale", relative_path(workspace_path, project_dir)
    return "current", relative_path(workspace_path, project_dir)


# ---------------------------------------------------------------------------
# Public assessment entry point
# ---------------------------------------------------------------------------


def assess_manual_review_workspace(project_dir: Path) -> dict[str, Any]:
    """The core, read-only manual-review-workspace assessment. Never writes
    anything, never invokes a slicer, never creates a workspace. Reuses
    `factory.slicer_readiness.assess_slicer_readiness()` for every
    technical/approval/package signal rather than re-deriving any of it.
    """
    project_dir = Path(project_dir)

    assessment = assess_slicer_readiness(project_dir)
    manifest = manifest_assessment(project_dir)

    build_plan_path = project_dir / "build_plan.json"
    build_plan = project_store.load_json(build_plan_path) if build_plan_path.is_file() else {}
    manifest_path = project_dir / "part_manifest.json"
    manifest_json = project_store.load_json(manifest_path) if manifest_path.is_file() else {"parts": []}

    printer_profile = _printer_profile(build_plan)
    material_summary = _material_summary(manifest_json)

    workspace_receipt = read_workspace_receipt(project_dir)
    workspace_file_status, workspace_path = _current_workspace_file_status(project_dir, workspace_receipt)

    workspace_status = _compute_workspace_status(
        assessment["readiness_status"], assessment["approval_status"], workspace_file_status
    )

    warnings = list(assessment["warnings"])
    if not printer_profile["resolved"]:
        warnings.append("Target printer is not resolved/confirmed - printer profile fields report 'Unknown'.")
    if material_summary["unresolved_material_parts"]:
        warnings.append(f"Material unconfirmed for: {', '.join(material_summary['unresolved_material_parts'])}.")
    if material_summary["unresolved_color_parts"]:
        warnings.append(f"Color unconfirmed for: {', '.join(material_summary['unresolved_color_parts'])}.")

    review_confidence = _review_confidence(assessment, printer_profile, material_summary)
    remaining_risk = _remaining_risk(assessment, printer_profile, material_summary)

    checklist = build_structured_review_checklist(
        printer_profile=printer_profile, material_summary=material_summary, manifest=manifest
    )

    return {
        "project": assessment["project_name"],
        "project_path": str(project_dir),
        "workspace_status": workspace_status,
        "technical_readiness": assessment["readiness_status"],
        "approval_status": assessment["approval_status"],
        "printer_summary": printer_profile,
        "material_summary": material_summary,
        "stl_summary": _stl_summary(assessment),
        "preview_summary": _preview_summary(assessment),
        "validation_summary": _validation_summary(assessment),
        "receipt_summary": _receipt_summary(assessment),
        "review_checklist": checklist,
        "review_confidence": review_confidence,
        "remaining_risk": remaining_risk,
        "warnings": warnings,
        "recommended_actions": _next_actions(workspace_status),
        "detected_slicers": assessment["detected_slicers"],
        "local_slicer_status": assessment["local_slicer_status"],
        "workspace_path": workspace_path,
        "dry_run": True,
        "no_automatic_print": True,
    }


def evaluate_manual_review_workspace_for_path(path: Path) -> dict[str, Any]:
    """Convenience entry point `factory review-workspace <path>` uses."""
    return assess_manual_review_workspace(path)


# ---------------------------------------------------------------------------
# Workspace creation - the one write path. References existing STL/
# validation/render/package files by relative path rather than copying
# them, mirroring `factory.preview_package`/`factory.slicer_readiness`'s own
# established "reference, don't duplicate" convention.
# ---------------------------------------------------------------------------


class WorkspaceNotAllowedError(Exception):
    """Raised when `create_manual_review_workspace()` is called before the
    underlying Phase 36 assessment is both technically ready and approved.
    """


class WorkspaceCollisionError(Exception):
    """Raised when a workspace already exists and `overwrite=False`."""


def create_manual_review_workspace(
    project_dir: Path, *, output_dir: str | None = None, overwrite: bool = False
) -> dict[str, Any]:
    """Write `manual_review/review_manifest.json` plus a human-readable
    `manual_review/README.md`. **References existing STL/validation/render/
    review-package files by relative path - never copies them.**

    Only allowed when the underlying Phase 36 assessment is
    `ready_for_review_package`/`review_package_created` *and* approved -
    raises `WorkspaceNotAllowedError` otherwise (mirroring
    `create_review_package()`'s own gate exactly, since a workspace is
    never more permissive than the package it organizes). Never overwrites
    an existing workspace without `overwrite=True`
    (raises `WorkspaceCollisionError`). Never touches source CAD, STL,
    validation, render, or review-package files.
    """
    project_dir = Path(project_dir)
    workspace = assess_manual_review_workspace(project_dir)
    if workspace["technical_readiness"] not in _READY_STATES or workspace["approval_status"] != "approved":
        raise WorkspaceNotAllowedError(
            f"cannot create a manual review workspace - technical_readiness is "
            f"{workspace['technical_readiness']!r}, approval_status is {workspace['approval_status']!r}. "
            f"Both must be ready/approved first (see `factory slicer-readiness <project>`)."
        )

    workspace_dir = project_dir / (output_dir or WORKSPACE_DIRNAME)
    workspace_path = workspace_dir / WORKSPACE_MANIFEST_FILENAME
    if workspace_path.is_file() and not overwrite:
        raise WorkspaceCollisionError(f"{workspace_path} already exists - pass overwrite=True to replace it")

    export_receipt = read_export_receipt(project_dir)
    fingerprints = _snapshot_workspace_fingerprints(project_dir, export_receipt)

    review_package_path = (
        f"{SLICER_REVIEW_DIRNAME}/{REVIEW_PACKAGE_FILENAME}"
        if workspace["receipt_summary"]["review_package_status"] in ("current", "stale", "unknown")
        else None
    )

    workspace_manifest = {
        "project": workspace["project"],
        "workspace_status": "workspace_created",
        "technical_readiness": workspace["technical_readiness"],
        "approval_status": workspace["approval_status"],
        "printer_summary": workspace["printer_summary"],
        "material_summary": workspace["material_summary"],
        "stl_summary": workspace["stl_summary"],
        "preview_summary": workspace["preview_summary"],
        "validation_summary": workspace["validation_summary"],
        "receipt_summary": workspace["receipt_summary"],
        "review_checklist": workspace["review_checklist"],
        "review_confidence": workspace["review_confidence"],
        "remaining_risk": workspace["remaining_risk"],
        "warnings": workspace["warnings"],
        "review_package_path": review_package_path,
        "artifact_fingerprints": fingerprints,
        "auto_print_allowed": False,
        "no_automatic_print": True,
    }

    project_store.save_json(workspace_path, workspace_manifest)
    readme_path = workspace_dir / WORKSPACE_README_FILENAME
    readme_path.write_text(_render_workspace_readme(workspace), encoding="utf-8")

    _write_workspace_receipt(
        project_dir,
        {
            "workspace": {
                "workspace_path": relative_path(workspace_path, project_dir),
                "artifact_fingerprints": fingerprints,
                "created_at": project_store.utc_now_iso(),
            }
        },
    )

    return {
        "workspace_path": str(workspace_path),
        "readme_path": str(readme_path),
        "manifest": workspace_manifest,
    }


def _render_workspace_readme(workspace: dict[str, Any]) -> str:
    lines = [
        f"# Manual Review Workspace - {workspace['project']}",
        "",
        f"Review confidence: {workspace['review_confidence']}  |  Remaining risk: {workspace['remaining_risk']}",
        "",
        "## Printer",
        "",
        f"- Display name: {workspace['printer_summary']['display_name']}",
        f"- Nozzle (mm): {workspace['printer_summary']['nozzle_mm']}",
        f"- Layer height (mm): {workspace['printer_summary']['layer_height_mm']}",
        f"- Build volume (mm): {workspace['printer_summary']['build_volume_mm']}",
        f"- AMS available: {workspace['printer_summary']['ams_available']}",
        "",
        "## Material",
        "",
    ]
    for part in workspace["material_summary"]["parts"]:
        lines.append(f"- **{part['part_name']}** - material: {part['material']}, color: {part['color']}")
    if not workspace["material_summary"]["parts"]:
        lines.append("- (no parts in part_manifest.json)")
    lines.append("")

    lines.append("## Review checklist")
    lines.append("")
    for category in workspace["review_checklist"]:
        lines.append(f"### {category['category']}")
        lines.append("")
        lines.extend(f"- [ ] {item}" for item in category["items"])
        lines.append("")

    lines.append("## Warnings")
    lines.append("")
    if workspace["warnings"]:
        lines.extend(f"- {w}" for w in workspace["warnings"])
    else:
        lines.append("None recorded.")
    lines.append("")

    lines.append("## Human sign-off")
    lines.append("")
    lines.append("- [ ] I have reviewed every checklist item above in a local slicer.")
    lines.append("- [ ] I understand no automatic printing has occurred.")
    lines.append("- [ ] Print submission remains a separate, explicit action I take myself.")
    lines.append("")

    lines.append("## No automatic print")
    lines.append("")
    lines.extend(NO_AUTOMATIC_PRINT_LINES)
    lines.append("")
    return "\n".join(lines)


def summarize_manual_review_workspace(project_dir: Path) -> dict[str, Any]:
    """Compact, read-only summary for the Preview Board's "Manual Review
    Workspace" card. Never assesses in a way that writes, never creates a
    workspace, never invokes a subprocess/slicer.

    **Architectural note - same reasoning as
    `factory.slicer_readiness.summarize_slicer_readiness()`:** this module
    calls `assess_slicer_readiness()`, which calls
    `factory.review_gate.evaluate_review_gate()`, which already imports
    `factory.project_inspection.summarize_project()`. Adding a
    `manual_review_summary` field computed via this module *inside*
    `project_inspection.py` would recreate the exact circular import Phase
    36 already discovered and worked around
    (`project_inspection -> manual_review_workspace -> slicer_readiness ->
    review_gate -> project_inspection`). `factory.preview_board.
    gather_board_data()` calls this function directly per project instead,
    the same architectural pattern as `slicer_readiness_summary`. See
    `docs/manual-review-workspace.md` "Architectural note".
    """
    workspace = assess_manual_review_workspace(project_dir)
    return {
        "workspace_status": workspace["workspace_status"],
        "printer_display_name": workspace["printer_summary"]["display_name"],
        "material_multi": workspace["material_summary"]["multi_material"],
        "material_unresolved": bool(
            workspace["material_summary"]["unresolved_material_parts"]
            or workspace["material_summary"]["unresolved_color_parts"]
        ),
        "review_confidence": workspace["review_confidence"],
        "remaining_risk": workspace["remaining_risk"],
        "package_available": workspace["receipt_summary"]["review_package_status"] in ("current", "stale", "unknown"),
        "warning_count": len(workspace["warnings"]),
        "next_action": workspace["recommended_actions"][0] if workspace["recommended_actions"] else None,
    }

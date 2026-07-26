"""Phase 38: Slicer Review Intelligence & Print Risk Analysis.

A deterministic, read-only analysis layer that identifies potential
slicer-review concerns before a human opens a slicer:

    Slicer Readiness -> Manual Review Workspace ->
    Slicer Review Intelligence -> Human Slicer Review ->
    (never automatic printing)

**This does NOT slice, does NOT generate G-code, does NOT control a
printer, and does NOT replace human slicer judgment.** It prepares a more
intelligent review experience on top of already-computed state - it never
re-implements mesh validation, dimension checks, printer/material
knowledge, artifact fingerprinting, or checklist generation. It reuses:

- `factory.manual_review_workspace.assess_manual_review_workspace()`
  (Phase 37) directly - itself already reusing
  `factory.slicer_readiness.assess_slicer_readiness()` (Phase 36),
  `factory.manufacturing.knowledge` (printer/material profiles), and
  `factory.slicer.local_slicer_probe.probe_slicers()`.
- `factory.export_pipeline.read_export_receipt()` - to find each current
  STL's already-written validation report path.
- `factory.validators.mesh_validate`'s already-computed `mesh_stats`
  (bounding box, volume, watertight, vertex/face counts) from each
  project's own `validation/<name>_validation.json` - never re-parses the
  STL itself.
- `factory.validators.dimension_check.check_build_volume_fit()` - called
  fresh with the project's own resolved target printer (the validation
  report's own embedded check may reflect the fleet's default printer
  instead - see `_build_volume_analysis()`'s docstring), never
  re-implemented.
- `factory.manufacturing.knowledge.get_printer()` - for the printer's
  `verified` flag (an unverified spec is a confidence signal, not a
  hard blocker).

**Only reports risks supported by existing measurable data - never
invents a finding.** Geometry risks are derived only from a part's own
already-measured bounding box/volume/watertight data; anything not
measurable (overhangs, bridging, supports, orientation) is surfaced as a
review *prompt*, never a claimed detection - this module never claims a
model "will fail," only that something is a "possible risk" worth human
review.

**Risk scoring is purely informational.** `risk_level` never blocks
progress and is never consulted by `factory.slicer_readiness` or
`factory.review_gate` - those modules' own hard blockers are completely
unaffected by anything computed here. See `docs/slicer-intelligence.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import project_store
from factory.export_pipeline import read_export_receipt
from factory.manual_review_workspace import assess_manual_review_workspace
from factory.manufacturing import knowledge
from factory.validators.dimension_check import check_build_volume_fit

ANALYSIS_STATES = ("no_geometry_data", "partial_geometry_data", "full_geometry_data")

BUILD_VOLUME_FIT_STATES = ("fits", "does_not_fit", "unknown")

CONFIDENCE_LEVELS = ("High", "Medium", "Low", "Unknown")
RISK_LEVELS = ("Low", "Moderate", "High", "Unknown")

NO_AUTOMATIC_PRINT_LINES = (
    "This analysis never invokes a slicer, generates G-code, or contacts a printer/network.",
    "Risk scoring is informational only - it never blocks printing and never overrides "
    "factory.slicer_readiness or factory.review_gate's own hard blockers.",
    "Human slicer review is still required after this analysis.",
)

# A part is only flagged "tall/narrow" once it's meaningfully large - avoids
# flagging small parts (a 6mm x 6mm x 20mm boss, say) where the aspect ratio
# looks dramatic but the part is trivially small.
_TALL_NARROW_MIN_HEIGHT_MM = 40.0
_TALL_NARROW_ASPECT_RATIO = 3.0

_FLAT_MAX_THIN_DIM_MM = 10.0
_FLAT_MIN_FOOTPRINT_DIM_MM = 50.0
_FLAT_ASPECT_RATIO = 6.0

# volume_mm3 / bounding_box_volume_mm3 - a low ratio means the mesh occupies
# a small fraction of its own bounding box (thin shells, lattices, intricate
# detail) - both values are already measured by mesh_validate, never
# re-derived independently.
_LOW_FILL_RATIO_THRESHOLD = 0.15


def _is_unresolved(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return True
    lowered = value.lower()
    return any(marker in lowered for marker in ("tbd", "unresolved", "unknown"))


# ---------------------------------------------------------------------------
# Geometry data collection - reads each current STL's already-written
# validation report; never re-parses the STL or re-runs mesh_validate.
# ---------------------------------------------------------------------------


def _load_part_geometry(project_dir: Path, export_receipt: dict[str, Any] | None) -> list[dict[str, Any]]:
    """One entry per source file the export receipt knows about:
    `{part_file, mesh_stats, validation_report_status}`. `mesh_stats` is
    `None` whenever no validation report exists yet, the report is
    unreadable, or the report predates mesh-level stats - never invented.
    """
    project_dir = Path(project_dir)
    parts: list[dict[str, Any]] = []
    for record in (export_receipt or {}).get("exports", []):
        output_stl = record.get("output_stl")
        report_path_rel = record.get("validation", {}).get("report_path")
        mesh_stats = None
        report_status = "missing"
        if report_path_rel:
            report_path = project_dir / report_path_rel
            if report_path.is_file():
                try:
                    report = project_store.load_json(report_path)
                    mesh_stats = report.get("mesh_stats")
                    report_status = "ok"
                except (OSError, ValueError):
                    report_status = "unreadable"
        parts.append({"part_file": output_stl, "mesh_stats": mesh_stats, "validation_report_status": report_status})
    return parts


# ---------------------------------------------------------------------------
# Build volume analysis - reuses check_build_volume_fit() (never
# reimplemented), applied fresh with the project's own resolved target
# printer (build_plan.json), plus a new (not previously computed anywhere)
# per-axis remaining-margin calculation.
# ---------------------------------------------------------------------------


def _best_fit_margin(bbox_mm: dict[str, float], build_volume_mm: dict[str, float]) -> dict[str, float] | None:
    """Find the axis permutation of `bbox_mm` that fits within
    `build_volume_mm` with the largest minimum per-axis margin, and return
    that permutation's `{x, y, z}` margins. Returns `None` if no
    permutation fits - never invents a margin for a part that doesn't fit.
    """
    from itertools import permutations

    dims = (bbox_mm.get("x", 0.0), bbox_mm.get("y", 0.0), bbox_mm.get("z", 0.0))
    volume_dims = (build_volume_mm.get("x", 0.0), build_volume_mm.get("y", 0.0), build_volume_mm.get("z", 0.0))

    best_margins = None
    best_min_margin = None
    for perm in permutations(dims):
        margins = tuple(v - d for d, v in zip(perm, volume_dims))
        if all(m >= 0 for m in margins):
            min_margin = min(margins)
            if best_min_margin is None or min_margin > best_min_margin:
                best_min_margin = min_margin
                best_margins = margins

    if best_margins is None:
        return None
    return {"x": round(best_margins[0], 2), "y": round(best_margins[1], 2), "z": round(best_margins[2], 2)}


def _build_volume_analysis(printer_summary: dict[str, Any], parts_geometry: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare each part's already-measured bounding box against the
    project's target printer's build volume. Reuses
    `factory.validators.dimension_check.check_build_volume_fit()` directly
    for the categorical PASS/WARN answer - this module only adds the
    per-axis remaining-margin computation, which didn't previously exist
    anywhere. Never invents a dimension: a part with no bounding box, or a
    project with no resolved printer, reports `"unknown"`.
    """
    printer_id = printer_summary.get("printer_id")
    printer = knowledge.get_printer(printer_id) if printer_id else None
    build_volume_mm = printer_summary.get("build_volume_mm")
    printer_resolved = bool(printer_summary.get("resolved")) and isinstance(build_volume_mm, dict)

    per_part: list[dict[str, Any]] = []
    for part in parts_geometry:
        mesh_stats = part.get("mesh_stats") or {}
        bbox_mm = mesh_stats.get("bounding_box_mm")
        if bbox_mm is None or not printer_resolved:
            per_part.append(
                {
                    "part_file": part.get("part_file"),
                    "fit_status": "unknown",
                    "remaining_margin_mm": None,
                    "detail": "No bounding box available" if bbox_mm is None else "No resolved printer with a known build volume",
                }
            )
            continue

        check = check_build_volume_fit(bbox_mm, printer)
        fits = check["status"] in ("PASS", "WARN") and "does not fit" not in check["detail"]
        margin = _best_fit_margin(bbox_mm, build_volume_mm) if fits else None
        per_part.append(
            {
                "part_file": part.get("part_file"),
                "fit_status": "fits" if fits else "does_not_fit",
                "remaining_margin_mm": margin,
                "detail": check["detail"],
            }
        )

    if not per_part:
        overall_fit = "unknown"
    elif any(p["fit_status"] == "does_not_fit" for p in per_part):
        overall_fit = "does_not_fit"
    elif any(p["fit_status"] == "unknown" for p in per_part):
        overall_fit = "unknown"
    else:
        overall_fit = "fits"

    # The aggregate margin shown at the top level is the tightest (smallest)
    # margin across every part that fits - the single number a human most
    # needs to see first, never an average that could mask a tight part.
    fitting_margins = [p["remaining_margin_mm"] for p in per_part if p["remaining_margin_mm"] is not None]
    aggregate_margin = None
    if fitting_margins:
        aggregate_margin = {
            axis: round(min(m[axis] for m in fitting_margins), 2) for axis in ("x", "y", "z")
        }

    return {
        "printer_display_name": printer_summary.get("display_name") or "Unknown",
        "printer_verified": bool(printer.get("verified")) if printer else None,
        "fit_status": overall_fit,
        "remaining_margin_mm": aggregate_margin,
        "parts": per_part,
    }


# ---------------------------------------------------------------------------
# Geometry risk analysis - only categories directly supported by already-
# measured bbox/volume/watertight data. Everything else (overhangs,
# bridging, supports, orientation) is a review prompt, never a claimed
# detection - see the *_considerations builders below.
# ---------------------------------------------------------------------------


def _geometry_risks_for_part(part_file: str | None, mesh_stats: dict[str, Any]) -> list[dict[str, str]]:
    risks: list[dict[str, str]] = []
    bbox = mesh_stats.get("bounding_box_mm")
    volume = mesh_stats.get("volume_mm3")
    is_watertight = mesh_stats.get("is_watertight")
    label = part_file or "this part"

    if bbox:
        x, y, z = bbox.get("x", 0.0), bbox.get("y", 0.0), bbox.get("z", 0.0)
        footprint_max = max(x, y)
        if z >= _TALL_NARROW_MIN_HEIGHT_MM and footprint_max > 0 and z >= _TALL_NARROW_ASPECT_RATIO * footprint_max:
            risks.append(
                {
                    "category": "Tall Narrow Geometry",
                    "message": f"Possible Risk: {label} is tall and narrow ({x:.1f} x {y:.1f} x {z:.1f} mm) - may need orientation review for stability.",
                }
            )

        smallest = min(x, y, z)
        others = sorted([x, y, z])[1:]
        if (
            smallest <= _FLAT_MAX_THIN_DIM_MM
            and others[0] >= _FLAT_MIN_FOOTPRINT_DIM_MM
            and smallest > 0
            and others[0] >= _FLAT_ASPECT_RATIO * smallest
        ):
            risks.append(
                {
                    "category": "Large Flat Areas",
                    "message": f"Possible Risk: {label} has a large flat area ({x:.1f} x {y:.1f} x {z:.1f} mm) - may be prone to warping; review bed adhesion strategy.",
                }
            )

        if volume is not None and is_watertight:
            bbox_volume = x * y * z
            if bbox_volume > 0:
                fill_ratio = volume / bbox_volume
                if fill_ratio < _LOW_FILL_RATIO_THRESHOLD:
                    risks.append(
                        {
                            "category": "Thin Features",
                            "message": f"Possible Risk: {label} has a low solid-fill ratio ({fill_ratio:.0%} of its bounding box) - may indicate thin walls or intricate detail; review wall thickness in the slicer.",
                        }
                    )

    if is_watertight is False:
        risks.append(
            {
                "category": "Fragile Features",
                "message": f"Possible Risk: {label} is not watertight - may indicate thin walls or geometry errors worth reviewing before slicing.",
            }
        )

    return risks


def _geometry_risks(parts_geometry: list[dict[str, Any]], part_count: int) -> list[dict[str, str]]:
    risks: list[dict[str, str]] = []
    for part in parts_geometry:
        mesh_stats = part.get("mesh_stats")
        if mesh_stats:
            risks.extend(_geometry_risks_for_part(part.get("part_file"), mesh_stats))

    if part_count > 1:
        risks.append(
            {
                "category": "Multi-part Alignment",
                "message": f"Possible Risk: {part_count} parts require assembly/alignment review in the slicer.",
            }
        )

    return risks


# ---------------------------------------------------------------------------
# Manufacturing risks - reuses already-computed workspace state; never a
# second manifest/printer/material check.
# ---------------------------------------------------------------------------


def _manufacturing_risks(workspace: dict[str, Any]) -> list[dict[str, str]]:
    risks: list[dict[str, str]] = []
    material_summary = workspace["material_summary"]
    printer_summary = workspace["printer_summary"]

    if material_summary["unresolved_material_parts"]:
        risks.append(
            {
                "category": "Material",
                "message": f"Material unconfirmed for: {', '.join(material_summary['unresolved_material_parts'])}.",
            }
        )
    if material_summary["unresolved_color_parts"]:
        risks.append(
            {
                "category": "Color",
                "message": f"Color unconfirmed for: {', '.join(material_summary['unresolved_color_parts'])}.",
            }
        )
    if not printer_summary["resolved"]:
        risks.append({"category": "Printer", "message": "Target printer is not resolved/confirmed."})

    if workspace["validation_summary"]["failed"] > 0:
        risks.append(
            {
                "category": "Validation",
                "message": f"{workspace['validation_summary']['failed']} STL(s) failed validation.",
            }
        )
    if workspace["validation_summary"]["passed_with_warnings"] > 0:
        risks.append(
            {
                "category": "Validation",
                "message": f"{workspace['validation_summary']['passed_with_warnings']} STL(s) passed validation with warnings.",
            }
        )

    return risks


# ---------------------------------------------------------------------------
# Material analysis - classification only, reusing the material_profile
# already computed by assess_manual_review_workspace(); never a second
# knowledge-base lookup.
# ---------------------------------------------------------------------------


def _material_analysis(material_summary: dict[str, Any]) -> list[dict[str, Any]]:
    entries = []
    for part in material_summary["parts"]:
        if _is_unresolved(part["material"]):
            status = "unresolved"
        elif part.get("material_profile") is not None:
            status = "known"
        else:
            status = "unknown_material"
        entries.append({"part_name": part["part_name"], "material": part["material"], "status": status})
    return entries


# ---------------------------------------------------------------------------
# Review prompts - never computed detections, always generic human review
# questions. Multi-material items only appear when the project's own data
# (printer AMS support or multiple resolved materials) actually supports
# them - mirrors factory.manual_review_workspace's own checklist
# convention exactly.
# ---------------------------------------------------------------------------


def _orientation_considerations() -> list[str]:
    return [
        "Review: strongest face placement.",
        "Review: cosmetic surface visibility.",
        "Review: support minimization.",
        "Review: layer-direction effects on strength.",
    ]


def _support_considerations(parts_geometry: list[dict[str, Any]]) -> list[str]:
    if not any(part.get("mesh_stats") for part in parts_geometry):
        return []
    return [
        "Support Review Needed - inspect overhangs.",
        "Support Review Needed - verify orientation.",
        "Support Review Needed - verify support strategy.",
    ]


def _adhesion_considerations(geometry_risks: list[dict[str, str]]) -> list[str]:
    if any(r["category"] == "Large Flat Areas" for r in geometry_risks):
        return [
            "Review bed adhesion strategy (brim/raft) for large flat areas.",
            "Review first-layer settings.",
        ]
    return []


def _multi_material_considerations(printer_summary: dict[str, Any], material_summary: dict[str, Any]) -> list[str]:
    ams_relevant = printer_summary.get("ams_available") is True or material_summary["multi_material"]
    if not ams_relevant:
        return []
    return [
        "Review color assignment per part.",
        "Review part separation for multi-color printing.",
        "Review assembly order for multi-part/multi-color prints.",
    ]


# ---------------------------------------------------------------------------
# Confidence / risk scoring - purely deterministic, informational only.
# ---------------------------------------------------------------------------


def _analysis_status(parts_geometry: list[dict[str, Any]]) -> str:
    if not parts_geometry:
        return "no_geometry_data"
    with_data = sum(1 for p in parts_geometry if p.get("mesh_stats"))
    if with_data == 0:
        return "no_geometry_data"
    if with_data < len(parts_geometry):
        return "partial_geometry_data"
    return "full_geometry_data"


def _confidence(analysis_status: str, parts_geometry: list[dict[str, Any]]) -> str:
    if analysis_status == "no_geometry_data":
        return "Unknown"
    if analysis_status == "partial_geometry_data":
        return "Low"
    full_stats = all(
        (p.get("mesh_stats") or {}).get("volume_mm3") is not None and (p.get("mesh_stats") or {}).get("is_watertight")
        for p in parts_geometry
    )
    return "High" if full_stats else "Medium"


def _risk_level(
    analysis_status: str,
    build_volume_analysis: dict[str, Any],
    geometry_risks: list[dict[str, str]],
    manufacturing_risks: list[dict[str, str]],
) -> str:
    if analysis_status == "no_geometry_data" and not manufacturing_risks:
        return "Unknown"
    if build_volume_analysis["fit_status"] == "does_not_fit":
        return "High"
    total_findings = len(geometry_risks) + len(manufacturing_risks)
    if total_findings >= 3:
        return "High"
    if total_findings >= 1:
        return "Moderate"
    return "Low"


def _review_priority(
    build_volume_analysis: dict[str, Any],
    geometry_risks: list[dict[str, str]],
    manufacturing_risks: list[dict[str, str]],
) -> list[str]:
    """Ordered, deduplicated review priorities - manufacturing risks (the
    cheapest to fix) first, then build-volume concerns, then geometry
    risks. Never invents an item beyond what was actually found."""
    priorities: list[str] = []
    if build_volume_analysis["fit_status"] == "does_not_fit":
        priorities.append("Confirm build-volume fit - part(s) may not fit the target printer.")
    for risk in manufacturing_risks:
        priorities.append(risk["message"])
    for risk in geometry_risks:
        priorities.append(risk["message"])
    return priorities


def _recommended_actions(analysis_status: str, workspace: dict[str, Any]) -> list[str]:
    if analysis_status == "no_geometry_data":
        return ["Export and validate STL(s) first - see `factory export-from-cad --validate`."]
    actions = list(workspace["recommended_actions"])
    actions.append("Review the priorities above before opening a local slicer.")
    return actions


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def evaluate_slicer_intelligence(project_dir: Path) -> dict[str, Any]:
    """The core, read-only slicer review intelligence analysis. Never
    writes anything, never invokes a slicer, never generates G-code, never
    contacts a printer/network. Reuses
    `factory.manual_review_workspace.assess_manual_review_workspace()` for
    every printer/material/technical-readiness signal rather than
    re-deriving any of it.
    """
    project_dir = Path(project_dir)
    workspace = assess_manual_review_workspace(project_dir)
    export_receipt = read_export_receipt(project_dir)
    parts_geometry = _load_part_geometry(project_dir, export_receipt)

    analysis_status = _analysis_status(parts_geometry)
    build_volume_analysis = _build_volume_analysis(workspace["printer_summary"], parts_geometry)
    geometry_risks = _geometry_risks(parts_geometry, workspace["material_summary"]["part_count"])
    manufacturing_risks = _manufacturing_risks(workspace)
    material_analysis = _material_analysis(workspace["material_summary"])

    orientation_considerations = _orientation_considerations()
    support_considerations = _support_considerations(parts_geometry)
    adhesion_considerations = _adhesion_considerations(geometry_risks)
    multi_material_considerations = _multi_material_considerations(
        workspace["printer_summary"], workspace["material_summary"]
    )

    confidence = _confidence(analysis_status, parts_geometry)
    risk_level = _risk_level(analysis_status, build_volume_analysis, geometry_risks, manufacturing_risks)
    review_priority = _review_priority(build_volume_analysis, geometry_risks, manufacturing_risks)

    warnings = list(workspace["warnings"])
    advisories: list[str] = []
    if build_volume_analysis["printer_verified"] is False:
        advisories.append(
            f"Printer '{build_volume_analysis['printer_display_name']}' build volume is an unverified "
            "placeholder - confirm before relying on the build-volume-fit result above."
        )
    if any(entry["status"] == "unknown_material" for entry in material_analysis):
        warnings.append("One or more materials are not recognized in the local materials knowledge base - confirm final filament.")

    return {
        "project": workspace["project"],
        "project_path": str(project_dir),
        "analysis_status": analysis_status,
        "printer": workspace["printer_summary"],
        "material": material_analysis,
        "build_volume_analysis": build_volume_analysis,
        "geometry_risks": geometry_risks,
        "manufacturing_risks": manufacturing_risks,
        "orientation_considerations": orientation_considerations,
        "support_considerations": support_considerations,
        "adhesion_considerations": adhesion_considerations,
        "multi_material_considerations": multi_material_considerations,
        "review_priority": review_priority,
        "risk_level": risk_level,
        "warnings": warnings,
        "advisories": advisories,
        "recommended_actions": _recommended_actions(analysis_status, workspace),
        "confidence": confidence,
        "detected_slicers": workspace["detected_slicers"],
        "local_slicer_status": workspace["local_slicer_status"],
        "dry_run": True,
        "no_automatic_print": True,
    }


def evaluate_slicer_intelligence_for_path(path: Path) -> dict[str, Any]:
    """Convenience entry point `factory slicer-inspect <path>` uses."""
    return evaluate_slicer_intelligence(path)


def summarize_slicer_intelligence(project_dir: Path) -> dict[str, Any]:
    """Compact, read-only summary for the Preview Board's "Slicer
    Intelligence" card. Never writes, never invokes a slicer.

    **Architectural note - same reasoning as Phase 36/37's own summary
    fields:** this module calls `assess_manual_review_workspace()`, which
    calls `assess_slicer_readiness()`, which calls
    `factory.review_gate.evaluate_review_gate()`, which already imports
    `factory.project_inspection.summarize_project()`. Adding a
    `slicer_intelligence_summary` field computed via this module *inside*
    `project_inspection.py` would recreate the exact circular import Phase
    36 already discovered and Phase 37 confirmed again transitively
    (`project_inspection -> slicer_intelligence -> manual_review_workspace
    -> slicer_readiness -> review_gate -> project_inspection`).
    `factory.preview_board.gather_board_data()` calls this function
    directly per project instead, the same architectural pattern as
    `slicer_readiness_summary`/`manual_review_summary`. See
    `docs/slicer-intelligence.md` "Architectural note".
    """
    analysis = evaluate_slicer_intelligence(project_dir)
    return {
        "risk_level": analysis["risk_level"],
        "build_volume_fit": analysis["build_volume_analysis"]["fit_status"],
        "review_item_count": len(analysis["review_priority"]),
        "top_priority": analysis["review_priority"][0] if analysis["review_priority"] else None,
        "confidence": analysis["confidence"],
        "warning_count": len(analysis["warnings"]),
    }

"""Local, read-only single-project inspection layer.

The shared foundation both `factory.preview_board` (multi-project static
board) and `factory.review_gate` (single-project pass/warn/fail gate)
build on, so neither has to re-derive brief/manifest/render/validation
state and the two can never disagree about the same underlying facts.
Extracted from `factory.preview_board` in Phase 13 to remove the circular
import pressure that kept `factory.review_gate` depending on
`factory.preview_board` internals - `review_gate` now depends only on
this module.

`summarize_project()` is the main entry point: read one project's
existing `brief.json`/`build_plan.json`/`part_manifest.json`/`cad/`/
`stl/`/`renders/`/`validation/` files (reusing `factory.preview_package`
and `factory.render_coverage` rather than duplicating their file-scanning
logic) and return a deterministic dict describing the project's
`visual_readiness_state`, `health_signals`, and `suggested_actions`.

This module never writes, renders, validates, exports, generates CAD,
invokes a slicer, launches Blender, calls Meshy, or contacts a printer/
network - pure local reads. It never sets or implies `human_approved` or
`print_ready` - the highest state it ever names is `slicer_review_ready`.
See docs/architecture.md, docs/preview-board.md, docs/review-gate.md, and
AGENT.md.

Phase 26 added a `design_intent_summary` field to `summarize_project()`'s
output - a compact, read-only visibility aid (quality standard, use case,
and the manufacturability advisory result from
`factory.design_intent_check`) for the preview board, `None` whenever the
project's `brief.json` has no `design_intent` block. It is derived from
the same `check_design_intent_manufacturability()` this module already
depends on transitively via `factory.design_intent_check` - no parsing
logic is duplicated - and never feeds into `visual_readiness_state`,
`health_signals`, or `suggested_actions`: it is display-only and does not
change readiness classification, approval, or print-readiness in any way.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import preview_package, project_store
from factory.design_intent_check import summarize_design_intent
from factory.render_coverage import compute_render_coverage, missing_and_stale_mesh_paths

VISUAL_READINESS_STATES = (
    "needs_brief",
    "cad_source_ready",
    "needs_stl_export",
    "needs_render",
    "slicer_review_ready",
    "blocked_or_incomplete",
)

HEALTH_SEVERITIES = ("info", "warning", "blocked", "ready")

ACTION_SAFETY = "manual_only"


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return project_store.load_json(path)
    except Exception:  # noqa: BLE001 - malformed JSON degrades to "missing/unreadable", not a crash
        return None


def _load_or_compute_preview_index(project_dir: Path) -> tuple[dict[str, Any], str]:
    """Return (index_data, status), status one of "ok"/"missing"/"unreadable".

    Prefers an existing `preview_package/index.json`; falls back to
    `preview_package.gather_preview_data()` (also read-only - it never
    writes) whenever the on-disk file isn't usable ("missing" - no file
    yet, or "unreadable" - a file exists but isn't valid JSON), so
    `summarize_project()` always has real data either way while still
    knowing which case it was.
    """
    index_path, _ = preview_package.preview_package_paths(project_dir)
    if not index_path.is_file():
        return preview_package.gather_preview_data(project_dir), "missing"
    existing = _safe_load_json(index_path)
    if existing is not None:
        return existing, "ok"
    return preview_package.gather_preview_data(project_dir), "unreadable"


def classify_visual_readiness(
    *,
    brief_status: str,
    manifest_status: str,
    cad_files: list[str],
    mesh_files: list[str],
    missing_renders: list[str],
    stale_renders: list[str],
    missing_visual_artifacts: list[str],
    stale_previews: list[str],
) -> str:
    """Deterministically classify a project's visual readiness.

    `brief_status`/`manifest_status` are each "missing", "unreadable", or
    "ok". Mirrors the "X_ready describes what's just been reached, next step
    implied" naming convention `project_store.PROJECT_STATUSES` already
    uses (e.g. `slicer_review_ready` there means "preview rendered, ready
    for slicer review" - same meaning here). Never returns/implies
    `human_approved` or `print_ready` - those aren't visual-readiness states
    and are never computed by this module.

    `missing_renders`/`stale_renders` come from `factory.render_coverage` -
    any mesh missing (or with a stale) render, whether that's every mesh or
    just one of several, resolves to `needs_render` (conservative: it's
    still just "run `factory render`", not a deeper problem). Orphan
    renders never block readiness by themselves (see docs/render-coverage.md);
    they're surfaced as an advisory warning instead. `missing_visual_artifacts`/
    `stale_previews` (from `factory.preview_package`, manifest-aware) remain
    the catch-all for anything render-coverage's directory-only view can't
    see, e.g. a manifest part whose file lives outside `stl/`.
    """
    if brief_status == "missing":
        return "needs_brief"
    if brief_status == "unreadable" or manifest_status == "unreadable":
        return "blocked_or_incomplete"
    if not cad_files and not mesh_files:
        return "cad_source_ready"
    if not mesh_files:
        return "needs_stl_export"
    if missing_renders:
        return "needs_render"
    if stale_renders or missing_visual_artifacts or stale_previews:
        return "blocked_or_incomplete"
    return "slicer_review_ready"


def _compute_validation_coverage(project_dir: Path, mesh_files: list[str]) -> tuple[list[str], int]:
    """Local, read-only check of which STLs already have a validation report.

    Mirrors the `<mesh_stem>_validation.json` naming convention `factory
    validate` already writes into `validation/`. Never runs validation
    itself - only checks whether the report file already exists; if
    `validation/` doesn't exist at all, every mesh is simply "missing" one.
    Returns (missing_validation_mesh_paths, validated_count).
    """
    validation_dir = project_dir / "validation"
    missing: list[str] = []
    validated_count = 0
    for mesh_rel_path in mesh_files:
        mesh_stem = Path(mesh_rel_path).stem
        report_path = validation_dir / f"{mesh_stem}_validation.json"
        if report_path.is_file():
            validated_count += 1
        else:
            missing.append(mesh_rel_path)
    return missing, validated_count


def _action(kind: str, label: str, command: str, reason: str) -> dict[str, str]:
    return {"kind": kind, "label": label, "command": command, "safety": ACTION_SAFETY, "reason": reason}


def build_suggested_actions(
    *,
    visual_readiness_state: str,
    project_path: str,
    brief_status: str,
    manifest_status: str,
    render_coverage: dict[str, Any],
    missing_visual_artifacts: list[str],
    stale_previews: list[str],
    validation_missing: list[str] | None = None,
) -> list[dict[str, str]]:
    """Build the deterministic list of safe, human-run next-step suggestions for one project.

    Every action is advisory only (`"safety": "manual_only"`) - this
    function never executes a command, never invokes a slicer/printer/
    network/cloud API, never launches Blender, never calls Meshy, and
    never sets `human_approved`/`print_ready`. `command` is always plain
    text for a human to read and, at most, copy - nothing here runs it.
    One primary suggestion set per project, driven by `visual_readiness_state`
    (the same precedence `classify_visual_readiness()` already computes),
    so the board never shows a next step that's already been superseded by
    a more fundamental one (e.g. it won't suggest rendering a project that
    doesn't have a brief yet). `validation_missing` is applied
    orthogonally on top - one `validate_mesh_manual` suggestion per STL
    without a local validation report, regardless of state, since checking
    geometry is independent of visual-readiness progress.
    """
    if visual_readiness_state == "needs_brief":
        actions: list[dict[str, str]] = [
            _action(
                "create_brief_missing",
                "Create the missing project brief",
                f"Create {project_path}/brief.json (see docs/file-lifecycle.md for the expected "
                f"fields), then run `factory plan {project_path}/brief.json`.",
                "brief.json is missing - this project has no recorded intent to plan or generate from yet.",
            )
        ]

    elif visual_readiness_state == "cad_source_ready":
        actions = [
            _action(
                "generate_cad_source",
                "Check CAD backend, then generate CAD source",
                f"factory route-cad {project_path}",
                "No CAD source (.scad/.py) exists yet. `factory route-cad` is read-only and "
                "recommends a backend without generating anything; run `factory generate-openscad` "
                "or `factory generate-cadquery` yourself afterward.",
            )
        ]

    elif visual_readiness_state == "needs_stl_export":
        actions = [
            _action(
                "export_stl_manual",
                "Export CAD source to STL",
                f"Review the CAD source under {project_path}/cad/, then export it yourself into "
                f"{project_path}/stl/ (see docs/openscad-generation.md / docs/cad-backends.md).",
                "CAD source exists but no STL has been exported yet. STL export is always a "
                "manual, human-run step in this repo.",
            )
        ]

    elif visual_readiness_state == "needs_render":
        actions = []
        for mesh_rel_path in missing_and_stale_mesh_paths(render_coverage):
            is_stale = mesh_rel_path not in render_coverage["missing_renders"]
            full_path = f"{project_path}/{mesh_rel_path}"
            reason = (
                "Existing render is older than this STL - re-run render after the mesh changed."
                if is_stale
                else "STL exists but the matching render PNG is missing."
            )
            actions.append(
                _action(
                    "render_missing_mesh",
                    "Re-render stale STL preview" if is_stale else "Render missing STL preview",
                    f"factory render {full_path}",
                    reason,
                )
            )

    elif visual_readiness_state == "slicer_review_ready":
        actions = [
            _action(
                "review_slicer_manually",
                "Open in your slicer for manual review",
                f"Manually open {project_path}/stl/*.stl in Bambu Studio/OrcaSlicer to review plate "
                "layout, materials/colors, orientation, and supports. Do not slice-and-send or print yet.",
                "All meshes have a fresh render and no missing/stale artifacts were detected - "
                "ready for human slicer review, not for printing.",
            )
        ]

    else:
        # blocked_or_incomplete
        reasons: list[str] = []
        if brief_status == "unreadable":
            reasons.append("brief.json exists but could not be parsed as JSON.")
        if manifest_status == "unreadable":
            reasons.append("part_manifest.json exists but could not be parsed as JSON.")
        if render_coverage["stale_renders"]:
            reasons.append(f"{len(render_coverage['stale_renders'])} render(s) are older than their STL.")
        if missing_visual_artifacts:
            reasons.append(f"{len(missing_visual_artifacts)} missing visual artifact(s) reported by the preview package.")
        if stale_previews:
            reasons.append(f"{len(stale_previews)} stale preview(s) reported by the preview package.")
        if not reasons:
            reasons.append("Project state does not yet resolve cleanly to a single next step.")

        actions = [
            _action(
                "inspect_blocked_project",
                "Investigate blocked/incomplete project state",
                f"factory report {project_path}  (and/or factory render-coverage {project_path} for "
                "render-specific detail)",
                " ".join(reasons),
            )
        ]

    for mesh_rel_path in (validation_missing or []):
        full_path = f"{project_path}/{mesh_rel_path}"
        actions.append(
            _action(
                "validate_mesh_manual",
                "Run local geometry validation",
                f"factory validate {full_path}",
                f"{mesh_rel_path} has no local validation report yet - run `factory validate` "
                "manually before trusting this mesh's geometry.",
            )
        )

    return actions


def _health_item(kind: str, severity: str, message: str, suggested_action_kind: str | None) -> dict[str, Any]:
    return {
        "kind": kind,
        "severity": severity,
        "message": message,
        "suggested_action_kind": suggested_action_kind,
    }


def build_health_signals(
    *,
    visual_readiness_state: str,
    brief_status: str,
    manifest_status: str,
    preview_package_status: str,
    selected_manufacturing_option: str | None,
    mesh_files: list[str],
    render_coverage: dict[str, Any],
    missing_visual_artifacts: list[str],
    stale_previews: list[str],
    validation_missing: list[str],
    validation_present_count: int,
) -> dict[str, Any]:
    """Build the deterministic `health_signals` summary for one project.

    Every item is advisory only - this never runs validation, never
    contacts a network/printer/slicer, and never marks anything
    `human_approved`/`print_ready`. Severities are chosen to always agree
    with `classify_visual_readiness()`'s own precedence: a condition is
    `"blocked"` here only when it's exactly the condition that would (or
    does) put the project into `blocked_or_incomplete`; a normal,
    expected, non-corrupt gap (missing brief/manifest, missing render) is
    `"warning"`; purely informational context (orphan renders, an
    unselected manufacturing option, an already-fresh cache) is `"info"`;
    and `"ready"` is used only for the one positive "ready for human
    slicer review" signal - never an approval or print-readiness claim.
    """
    items: list[dict[str, Any]] = []

    if brief_status == "missing":
        items.append(_health_item("brief_missing", "warning", "brief.json is missing.", "create_brief_missing"))
    elif brief_status == "unreadable":
        items.append(
            _health_item(
                "brief_unreadable", "blocked", "brief.json exists but could not be parsed as JSON.", "inspect_blocked_project"
            )
        )

    if manifest_status == "missing":
        items.append(_health_item("manifest_missing", "warning", "part_manifest.json is missing.", "inspect_blocked_project"))
    elif manifest_status == "unreadable":
        items.append(
            _health_item(
                "manifest_unreadable",
                "blocked",
                "part_manifest.json exists but could not be parsed as JSON.",
                "inspect_blocked_project",
            )
        )

    if brief_status == "ok" and not selected_manufacturing_option:
        items.append(
            _health_item(
                "manufacturing_option_not_selected",
                "info",
                "No manufacturing option has been selected yet - see `factory list-options` / `factory choose-option`.",
                None,
            )
        )

    if preview_package_status == "missing":
        items.append(
            _health_item(
                "preview_package_missing",
                "info",
                "No preview_package/index.json found yet - this summary was computed live instead. "
                "Run `factory preview-project` to persist it.",
                None,
            )
        )
    elif preview_package_status == "unreadable":
        items.append(
            _health_item(
                "preview_package_unreadable",
                "warning",
                "preview_package/index.json exists but could not be parsed as JSON - a fresh summary "
                "was computed instead. Re-run `factory preview-project` to rebuild it.",
                None,
            )
        )

    if render_coverage["missing_renders"]:
        items.append(
            _health_item(
                "render_missing",
                "warning",
                f"{len(render_coverage['missing_renders'])} STL file(s) have no matching render yet.",
                "render_missing_mesh",
            )
        )

    if render_coverage["stale_renders"]:
        # Whenever any stale render exists, classify_visual_readiness has
        # already resolved the project to blocked_or_incomplete (it only
        # reaches the stale-renders check once missing_renders is empty) -
        # "blocked" here always agrees with that.
        items.append(
            _health_item(
                "render_stale",
                "blocked",
                f"{len(render_coverage['stale_renders'])} render(s) are older than the STL they preview.",
                "render_missing_mesh",
            )
        )

    if render_coverage["orphan_renders"]:
        items.append(
            _health_item(
                "render_orphan",
                "info",
                f"{len(render_coverage['orphan_renders'])} render(s) have no matching STL currently on "
                "disk (kept for reference, never deleted).",
                None,
            )
        )

    # These manifest-aware fields only actually drive blocked_or_incomplete
    # once mesh files exist and render_coverage's own missing-render gate
    # has already passed - mirror that exact gate so "blocked" here is
    # always accurate, never a false alarm during an earlier stage.
    if mesh_files and not render_coverage["missing_renders"]:
        if missing_visual_artifacts:
            items.append(
                _health_item(
                    "missing_visual_artifacts",
                    "blocked",
                    f"{len(missing_visual_artifacts)} missing visual artifact(s) reported by the preview package.",
                    "inspect_blocked_project",
                )
            )
        if stale_previews:
            items.append(
                _health_item(
                    "stale_preview_artifacts",
                    "blocked",
                    f"{len(stale_previews)} stale preview(s) reported by the preview package.",
                    "inspect_blocked_project",
                )
            )

    if validation_missing:
        items.append(
            _health_item(
                "validation_missing",
                "warning",
                f"{len(validation_missing)} STL file(s) have no local validation report yet. "
                "Run `factory validate` manually for each mesh before trusting geometry.",
                "validate_mesh_manual",
            )
        )
    if validation_present_count:
        items.append(
            _health_item(
                "validation_present",
                "info",
                f"{validation_present_count} STL file(s) already have a local validation report on disk.",
                None,
            )
        )

    if visual_readiness_state == "slicer_review_ready":
        items.append(
            _health_item(
                "slicer_review_ready",
                "ready",
                "All meshes have fresh renders and no missing/stale artifacts were detected - ready "
                "for human slicer review (not print-ready).",
                "review_slicer_manually",
            )
        )

    if any(item["severity"] == "blocked" for item in items):
        summary = "blocked"
    elif any(item["severity"] == "warning" for item in items):
        summary = "attention_needed"
    else:
        summary = "ok"

    return {"summary": summary, "items": items}


def _compact_design_intent_summary(brief_path: Path) -> dict[str, Any] | None:
    """Compact, read-only `design_intent` summary for a project card.

    Wraps `factory.design_intent_check.summarize_design_intent()` (the full,
    detailed summary `factory report` shows) down to the three fields worth a
    board row: `quality_standard`, `use_case`, `manufacturability_result`.
    Returns `None` whenever the full summary is `None` (no `design_intent`
    block, unreadable file, or malformed shape) - not an error, most projects
    won't have one.
    """
    full = summarize_design_intent(brief_path)
    if full is None:
        return None
    return {
        "quality_standard": full["quality_standard"],
        "use_case": full["use_case"],
        "manufacturability_result": full["manufacturability_check"]["result"],
    }


def summarize_project(project_dir: Path, *, projects_root: Path | None = None) -> dict[str, Any]:
    """Read one project's existing files and summarize it for the board/gate.

    Read-only: never writes, generates, renders, exports, or contacts
    anything. Only reads `brief.json`, `build_plan.json`, and whatever
    `preview_package.gather_preview_data()`/an existing
    `preview_package/index.json` already read. `projects_root`, if given,
    is used only to compute a `project_dir`-relative-to-`projects_root`
    display path (`factory.preview_board` passes it; `factory.review_gate`
    doesn't need to).
    """
    project_dir = Path(project_dir)

    brief_path = project_dir / "brief.json"
    manifest_path = project_dir / "part_manifest.json"
    build_plan_path = project_dir / "build_plan.json"

    brief_status = "missing" if not brief_path.is_file() else ("ok" if _safe_load_json(brief_path) is not None else "unreadable")
    manifest_status = "missing" if not manifest_path.is_file() else ("ok" if _safe_load_json(manifest_path) is not None else "unreadable")
    build_plan = _safe_load_json(build_plan_path) or {}

    index, preview_package_status = _load_or_compute_preview_index(project_dir)
    preview_package_exists = preview_package_status == "ok"

    cad_files = index.get("cad_files", [])
    mesh_files = index.get("mesh_files", [])
    missing_visual_artifacts = index.get("missing_visual_artifacts", [])
    stale_previews = index.get("stale_previews", [])

    # Always computed fresh (cheap, read-only) rather than trusting whatever
    # a possibly-stale on-disk preview_package/index.json happens to have -
    # avoids any legacy-schema gap if that file predates this field.
    render_coverage = compute_render_coverage(project_dir)
    validation_missing, validation_present_count = _compute_validation_coverage(project_dir, mesh_files)

    warnings: list[str] = []
    if brief_status == "missing":
        warnings.append("brief.json is missing.")
    elif brief_status == "unreadable":
        warnings.append("brief.json exists but could not be parsed as JSON.")
    if manifest_status == "missing":
        warnings.append("part_manifest.json is missing.")
    elif manifest_status == "unreadable":
        warnings.append("part_manifest.json exists but could not be parsed as JSON.")
    if preview_package_status == "missing":
        warnings.append(
            "No preview_package/index.json found - this summary was computed on the fly "
            "(read-only). Run `factory preview-project` to persist it."
        )
    elif preview_package_status == "unreadable":
        warnings.append(
            "preview_package/index.json exists but could not be parsed as JSON - this summary was "
            "computed on the fly (read-only) instead. Re-run `factory preview-project` to rebuild it."
        )
    warnings.extend(missing_visual_artifacts)
    warnings.extend(stale_previews)
    warnings.extend(f"Orphan render (no matching STL): {r}" for r in render_coverage["orphan_renders"])

    project_name = index.get("project_name") or project_dir.name

    try:
        rel_dir = str(project_dir.resolve().relative_to(Path(projects_root).resolve())) if projects_root else project_dir.name
    except ValueError:
        rel_dir = project_dir.name

    visual_readiness_state = classify_visual_readiness(
        brief_status=brief_status,
        manifest_status=manifest_status,
        cad_files=cad_files,
        mesh_files=mesh_files,
        missing_renders=render_coverage["missing_renders"],
        stale_renders=render_coverage["stale_renders"],
        missing_visual_artifacts=missing_visual_artifacts,
        stale_previews=stale_previews,
    )

    # `project_dir` as given (by discover_projects(), it's projects_root
    # joined with the project's slug) is already in the same relative-to-CWD
    # form the user typed for projects_root, so suggested commands are
    # directly copy/paste-runnable without any extra path reconstruction.
    suggested_actions = build_suggested_actions(
        visual_readiness_state=visual_readiness_state,
        project_path=str(project_dir),
        brief_status=brief_status,
        manifest_status=manifest_status,
        render_coverage=render_coverage,
        missing_visual_artifacts=missing_visual_artifacts,
        stale_previews=stale_previews,
        validation_missing=validation_missing,
    )

    selected_manufacturing_option = index.get("selected_manufacturing_option")

    design_intent_summary = _compact_design_intent_summary(brief_path) if brief_status == "ok" else None

    health_signals = build_health_signals(
        visual_readiness_state=visual_readiness_state,
        brief_status=brief_status,
        manifest_status=manifest_status,
        preview_package_status=preview_package_status,
        selected_manufacturing_option=selected_manufacturing_option,
        mesh_files=mesh_files,
        render_coverage=render_coverage,
        missing_visual_artifacts=missing_visual_artifacts,
        stale_previews=stale_previews,
        validation_missing=validation_missing,
        validation_present_count=validation_present_count,
    )

    return {
        "project_name": project_name,
        "project_dir": rel_dir,
        "slug": project_dir.name,
        "brief_exists": brief_status != "missing",
        "brief_status": index.get("project_status") if brief_status == "ok" else None,
        "manufacturing_status": build_plan.get("status") if build_plan else None,
        "selected_manufacturing_option": selected_manufacturing_option,
        "manifest_exists": manifest_status != "missing",
        "render_coverage": render_coverage,
        "preview_package_exists": preview_package_exists,
        "cad_files": list(cad_files),
        "mesh_files": list(mesh_files),
        "render_files": list(index.get("render_files", [])),
        "visual_readiness_state": visual_readiness_state,
        "warnings": warnings,
        "suggested_actions": suggested_actions,
        "health_signals": health_signals,
        "design_intent_summary": design_intent_summary,
    }

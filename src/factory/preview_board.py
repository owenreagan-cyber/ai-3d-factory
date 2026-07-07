"""Local, static, multi-project visual preview board.

Aggregates every project under a `projects_root` directory into one static
board (`preview_board/index.json` + `preview_board/index.html`) for a human
(Owen) to visually sanity-check project state across the whole workspace at
a glance, before trusting any generated CAD/STL output. This is a read-mostly
aggregator on top of `factory.preview_package` - it reuses
`gather_preview_data()` for the per-project file scan instead of duplicating
it, and prefers an existing `preview_package/index.json` when one is already
on disk.

This module never generates CAD, renders images, exports STLs, runs
OpenSCAD, runs CadQuery, invokes a slicer, launches Blender, contacts a
network, or contacts a printer. The only files it writes are
`preview_board/index.json` and `preview_board/index.html` under the given
output directory - it never touches `brief.json`, `build_plan.json`,
`part_manifest.json`, or any file inside an individual project. See
docs/preview-board.md and AGENT.md.

Each project also gets a deterministic `suggested_actions` list
(`build_suggested_actions()`, Phase 10) - safe, copyable local commands for
the human to consider running next (e.g. `factory render <path>` for a
missing preview). Every action is advisory only (`"safety": "manual_only"`)
and this module never executes one, never invokes a slicer/printer/
network/cloud API, never launches Blender, and never calls Meshy.

Each project also gets a deterministic `health_signals` summary
(`build_health_signals()`, Phase 11): a `summary` of `"ok"`/
`"attention_needed"`/`"blocked"` plus structured `items` (missing/unreadable
brief or manifest, an unselected manufacturing option, render coverage
gaps, and local `validation/` report coverage - `factory validate` is
never run automatically, only checked for). Severities always agree with
`classify_visual_readiness()`'s own precedence, and the only `"ready"`
signal (`slicer_review_ready`) explicitly means "ready for human slicer
review", never an approval or print-readiness claim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import preview_package, project_store
from factory.render_coverage import compute_render_coverage, missing_and_stale_mesh_paths

BOARD_DIRNAME = "preview_board"
INDEX_FILENAME = "index.json"
HTML_FILENAME = "index.html"

VISUAL_READINESS_STATES = (
    "needs_brief",
    "cad_source_ready",
    "needs_stl_export",
    "needs_render",
    "slicer_review_ready",
    "blocked_or_incomplete",
)

REQUIRED_SAFETY_LINES = (
    "Local static preview only - no server, no cloud, no printer/slicer communication.",
    "This is a visual inspection aid, not an approval and not a print-readiness signal.",
    "Human visual inspection required.",
    "Human slicer review required.",
    "No project shown here is print-ready.",
)


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return project_store.load_json(path)
    except Exception:  # noqa: BLE001 - malformed JSON degrades to "missing/unreadable", not a crash
        return None


def discover_projects(projects_root: Path) -> list[Path]:
    """List immediate subdirectories of `projects_root` treated as projects.

    Read-only directory listing. Skips hidden directories (leading '.') and
    this module's own `preview_board` output directory, so re-running the
    board command against its own output doesn't treat the board as a project.
    """
    projects_root = Path(projects_root)
    if not projects_root.is_dir():
        return []
    return sorted(
        (p for p in projects_root.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name != BOARD_DIRNAME),
        key=lambda p: p.name,
    )


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


ACTION_SAFETY = "manual_only"


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
    doesn't have a brief yet). `validation_missing` (Phase 11) is applied
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


HEALTH_SEVERITIES = ("info", "warning", "blocked", "ready")


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


def summarize_project(project_dir: Path, *, projects_root: Path | None = None) -> dict[str, Any]:
    """Read one project's existing files and summarize it for the board.

    Read-only: never writes, generates, renders, exports, or contacts
    anything. Only reads `brief.json`, `build_plan.json`, and whatever
    `preview_package.gather_preview_data()`/an existing
    `preview_package/index.json` already read.
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
    }


def gather_board_data(projects_root: Path) -> dict[str, Any]:
    """Read every project under `projects_root` and compute the board index.

    Read-only: never writes, generates, renders, exports, or contacts
    anything.
    """
    projects_root = Path(projects_root)
    project_dirs = discover_projects(projects_root)
    projects = [summarize_project(p, projects_root=projects_root) for p in project_dirs]

    state_counts: dict[str, int] = {state: 0 for state in VISUAL_READINESS_STATES}
    for project in projects:
        state_counts[project["visual_readiness_state"]] += 1

    return {
        "generated_at": project_store.utc_now_iso(),
        "projects_root": str(projects_root),
        "project_count": len(projects),
        "state_counts": state_counts,
        "projects": projects,
        "notes": list(REQUIRED_SAFETY_LINES),
    }


def _escape_html(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_STATE_LABELS = {
    "needs_brief": "Needs brief",
    "cad_source_ready": "Ready for CAD source",
    "needs_stl_export": "Needs STL export",
    "needs_render": "Needs render",
    "slicer_review_ready": "Slicer review ready",
    "blocked_or_incomplete": "Blocked / incomplete",
}

_HEALTH_SUMMARY_LABELS = {
    "ok": "OK",
    "attention_needed": "Attention needed",
    "blocked": "Blocked",
}

_HEALTH_SEVERITY_LABELS = {
    "info": "Info",
    "warning": "Warning",
    "blocked": "Blocked",
    "ready": "Ready",
}


def _build_health_signals_html(projects: list[dict[str, Any]]) -> str:
    """Render each project's `health_signals` into a static 'Health signals' block.

    Plain text only - no JavaScript, no external CSS/CDN, no automatic
    action of any kind. This is a read-only summary of locally-derived
    signals (missing/unreadable files, render/validation coverage gaps) -
    never an approval or print-readiness determination.
    """
    blocks: list[str] = []
    for project in projects:
        signals = project.get("health_signals") or {"summary": "ok", "items": []}
        items = signals.get("items") or []
        summary = signals.get("summary", "ok")
        summary_label = _HEALTH_SUMMARY_LABELS.get(summary, summary)

        if items:
            item_rows = "".join(
                "<li>"
                f"<span class=\"health-severity health-{_escape_html(item['severity'])}\">"
                f"{_escape_html(_HEALTH_SEVERITY_LABELS.get(item['severity'], item['severity']))}</span> "
                f"{_escape_html(item['message'])}"
                "</li>"
                for item in items
            )
            items_html = f"<ul class=\"health-items\">{item_rows}</ul>"
        else:
            items_html = "<p class=\"none\">No health signals - nothing detected to flag.</p>"

        blocks.append(
            "<div class=\"project-health\">"
            f"<h3>{_escape_html(project['project_name'])} <code>{_escape_html(project['project_dir'])}</code> "
            f"<span class=\"badge health-summary-{_escape_html(summary)}\">{_escape_html(summary_label)}</span></h3>"
            + items_html
            + "</div>"
        )

    if not blocks:
        return "<p>No health signals - no projects were found under this projects_root.</p>"

    return "".join(blocks)


def _build_suggestions_html(projects: list[dict[str, Any]]) -> str:
    """Render each project's `suggested_actions` into a static 'Suggested next steps' block.

    Plain text/code blocks only - no external JS, no copy buttons, no
    automatic execution of anything. The human reads and, at most, copies
    the command text themselves.
    """
    blocks: list[str] = []
    for project in projects:
        actions = project.get("suggested_actions") or []
        if not actions:
            continue
        action_items = []
        for action in actions:
            action_items.append(
                "<div class=\"action\">"
                f"<p class=\"action-label\"><strong>{_escape_html(action['label'])}</strong> "
                f"<span class=\"safety-tag\">({_escape_html(action['safety'])})</span></p>"
                f"<pre><code>{_escape_html(action['command'])}</code></pre>"
                f"<p class=\"action-reason\">{_escape_html(action['reason'])}</p>"
                "</div>"
            )
        blocks.append(
            "<div class=\"project-suggestions\">"
            f"<h3>{_escape_html(project['project_name'])} <code>{_escape_html(project['project_dir'])}</code></h3>"
            + "".join(action_items)
            + "</div>"
        )

    if not blocks:
        return "<p>No suggested actions - either no projects were found, or nothing needs attention.</p>"

    return "".join(blocks)


def build_board_html(board: dict[str, Any]) -> str:
    """Render `gather_board_data()`'s output into a static, self-contained HTML page.

    No external CSS/JS, no CDN, no remote assets, no tracking - a single
    local file safe to open directly in a browser (file://).
    """
    rows: list[str] = []
    for project in board["projects"]:
        state = project["visual_readiness_state"]
        label = _STATE_LABELS.get(state, state)
        warnings_html = (
            "<ul class=\"warnings\">" + "".join(f"<li>{_escape_html(w)}</li>" for w in project["warnings"]) + "</ul>"
            if project["warnings"]
            else "<span class=\"none\">none</span>"
        )
        coverage = project["render_coverage"]
        coverage_text = f"{coverage['covered_count']}/{coverage['total_meshes']}"
        coverage_details = []
        if coverage["missing_renders"]:
            coverage_details.append(f"{len(coverage['missing_renders'])} missing")
        if coverage["stale_renders"]:
            coverage_details.append(f"{len(coverage['stale_renders'])} stale")
        if coverage["orphan_renders"]:
            coverage_details.append(f"{len(coverage['orphan_renders'])} orphan")
        if coverage_details:
            coverage_text += " (" + ", ".join(coverage_details) + ")"

        health = project.get("health_signals") or {"summary": "ok", "items": []}
        health_summary = health.get("summary", "ok")
        health_label = _HEALTH_SUMMARY_LABELS.get(health_summary, health_summary)
        health_count = len(health.get("items") or [])
        health_text = f"{health_label} ({health_count})" if health_count else health_label

        rows.append(
            "<tr>"
            f"<td>{_escape_html(project['project_name'])}<br><code>{_escape_html(project['project_dir'])}</code></td>"
            f"<td><span class=\"badge state-{_escape_html(state)}\">{_escape_html(label)}</span></td>"
            f"<td><span class=\"badge health-summary-{_escape_html(health_summary)}\">{_escape_html(health_text)}</span></td>"
            f"<td>{_escape_html(project['brief_status'] or '(none)')}</td>"
            f"<td>{_escape_html(project['manufacturing_status'] or '(none)')}</td>"
            f"<td>{_escape_html(project['selected_manufacturing_option'] or '(none)')}</td>"
            f"<td>{len(project['cad_files'])}</td>"
            f"<td>{len(project['mesh_files'])}</td>"
            f"<td>{len(project['render_files'])}</td>"
            f"<td>{_escape_html(coverage_text)}</td>"
            f"<td>{'yes' if project['preview_package_exists'] else 'no'}</td>"
            f"<td>{'yes' if project['manifest_exists'] else 'no'}</td>"
            f"<td>{warnings_html}</td>"
            "</tr>"
        )

    state_summary = " &nbsp; ".join(
        f"<span class=\"badge state-{state}\">{_STATE_LABELS[state]}: {board['state_counts'][state]}</span>"
        for state in VISUAL_READINESS_STATES
    )

    rows_html = "\n".join(rows) if rows else "<tr><td colspan=\"13\">No projects found under this projects_root.</td></tr>"

    notes_html = "".join(f"<li>{_escape_html(n)}</li>" for n in board["notes"])
    suggestions_html = _build_suggestions_html(board["projects"])
    health_signals_html = _build_health_signals_html(board["projects"])

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ai-3d-factory preview board</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 2rem; background: #fafafa; color: #1a1a1a; }}
  h1 {{ margin-bottom: 0.25rem; }}
  .meta {{ color: #555; margin-bottom: 1rem; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff; }}
  th, td {{ border: 1px solid #ddd; padding: 0.5rem 0.75rem; text-align: left; vertical-align: top; font-size: 0.9rem; }}
  th {{ background: #f0f0f0; }}
  code {{ font-size: 0.8rem; color: #666; }}
  .badge {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 0.75rem; font-size: 0.8rem; background: #e0e0e0; }}
  .state-needs_brief {{ background: #fde2e2; }}
  .state-cad_source_ready {{ background: #fff3cd; }}
  .state-needs_stl_export {{ background: #fff3cd; }}
  .state-needs_render {{ background: #fff3cd; }}
  .state-slicer_review_ready {{ background: #d4edda; }}
  .state-blocked_or_incomplete {{ background: #fde2e2; }}
  ul.warnings {{ margin: 0; padding-left: 1.1rem; }}
  .none {{ color: #999; }}
  .safety {{ margin-top: 1.5rem; padding: 1rem; background: #fff8e1; border: 1px solid #f0e0a0; }}
  .safety li {{ margin-bottom: 0.25rem; }}
  .suggestions {{ margin-top: 1.5rem; }}
  .suggestions-intro {{ color: #555; }}
  .project-suggestions {{ background: #fff; border: 1px solid #ddd; border-radius: 0.35rem; padding: 0.75rem 1rem; margin-bottom: 1rem; }}
  .project-suggestions h3 {{ margin: 0 0 0.5rem 0; font-size: 1rem; }}
  .action {{ margin-bottom: 0.75rem; padding-bottom: 0.75rem; border-bottom: 1px solid #eee; }}
  .action:last-child {{ margin-bottom: 0; padding-bottom: 0; border-bottom: none; }}
  .action-label {{ margin: 0 0 0.25rem 0; }}
  .safety-tag {{ color: #7a5c00; font-size: 0.8rem; font-weight: normal; }}
  .action pre {{ margin: 0.25rem 0; padding: 0.5rem 0.75rem; background: #f5f5f5; border: 1px solid #e0e0e0; border-radius: 0.25rem; overflow-x: auto; }}
  .action pre code {{ font-size: 0.85rem; color: #1a1a1a; user-select: all; }}
  .action-reason {{ margin: 0.25rem 0 0 0; color: #555; font-size: 0.85rem; }}
  .health {{ margin-top: 1.5rem; }}
  .health-intro {{ color: #555; }}
  .project-health {{ background: #fff; border: 1px solid #ddd; border-radius: 0.35rem; padding: 0.75rem 1rem; margin-bottom: 1rem; }}
  .project-health h3 {{ margin: 0 0 0.5rem 0; font-size: 1rem; }}
  ul.health-items {{ margin: 0; padding-left: 1.1rem; }}
  ul.health-items li {{ margin-bottom: 0.35rem; }}
  .health-severity {{ display: inline-block; padding: 0.1rem 0.4rem; border-radius: 0.6rem; font-size: 0.75rem; font-weight: 600; margin-right: 0.25rem; }}
  .health-info {{ background: #e0e0e0; color: #333; }}
  .health-warning {{ background: #fff3cd; color: #7a5c00; }}
  .health-blocked {{ background: #fde2e2; color: #8a1f1f; }}
  .health-ready {{ background: #d4edda; color: #1e5b2e; }}
  .health-summary-ok {{ background: #d4edda; }}
  .health-summary-attention_needed {{ background: #fff3cd; }}
  .health-summary-blocked {{ background: #fde2e2; }}
</style>
</head>
<body>
<h1>ai-3d-factory preview board</h1>
<p class="meta">Generated {_escape_html(board["generated_at"])} &middot; projects_root: <code>{_escape_html(board["projects_root"])}</code> &middot; {board["project_count"]} project(s)</p>
<p>{state_summary}</p>
<table>
<thead>
<tr>
  <th>Project</th>
  <th>Visual readiness</th>
  <th>Health</th>
  <th>Brief status</th>
  <th>Manufacturing status</th>
  <th>Selected option</th>
  <th>CAD files</th>
  <th>STL files</th>
  <th>Renders</th>
  <th>Render coverage</th>
  <th>Preview package</th>
  <th>Manifest</th>
  <th>Warnings / missing artifacts</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
<div class="health">
<h2>Health signals</h2>
<p class="health-intro">Local, read-only signals derived from files already on disk (missing/unreadable
JSON, render coverage gaps, validation report coverage). Advisory only - this is not an approval and
not a print-readiness determination, and nothing here was validated, rendered, or checked automatically.</p>
{health_signals_html}
</div>
<div class="suggestions">
<h2>Suggested next steps</h2>
<p class="suggestions-intro">Advisory only. Nothing on this page runs automatically - commands are
plain text for you to read, and copy yourself, only if and when you decide to run them.</p>
{suggestions_html}
</div>
<div class="safety">
<ul>
{notes_html}
</ul>
</div>
</body>
</html>
"""


def preview_board_paths(output_dir: Path) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    return output_dir / INDEX_FILENAME, output_dir / HTML_FILENAME


def write_preview_board(
    projects_root: Path,
    *,
    output_dir: Path | None = None,
    fmt: str = "both",
) -> dict[str, Any]:
    """Build/refresh the static preview board for every project under `projects_root`.

    Writes only `<output_dir>/index.json` and/or `<output_dir>/index.html`
    (`output_dir` defaults to `<projects_root>/preview_board/`) - never
    touches any file inside an individual project, never renders a new
    image, never exports geometry, and never contacts a
    printer/slicer/network.
    """
    if fmt not in ("json", "html", "both"):
        raise ValueError(f"Unknown format {fmt!r}. Allowed: json, html, both")

    projects_root = Path(projects_root)
    output_dir = Path(output_dir) if output_dir is not None else projects_root / BOARD_DIRNAME

    board = gather_board_data(projects_root)
    index_path, html_path = preview_board_paths(output_dir)

    result: dict[str, Any] = {"board": board, "index_path": None, "html_path": None}

    if fmt in ("json", "both"):
        project_store.save_json(index_path, board)
        result["index_path"] = index_path

    if fmt in ("html", "both"):
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(build_board_html(board), encoding="utf-8")
        result["html_path"] = html_path

    return result

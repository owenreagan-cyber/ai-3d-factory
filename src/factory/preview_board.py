"""Local, static, multi-project visual preview board.

Aggregates every project under a `projects_root` directory into one static
board (`preview_board/index.json` + `preview_board/index.html`) for a human
(Owen) to visually sanity-check project state across the whole workspace at
a glance, before trusting any generated CAD/STL output.

Per-project classification (`visual_readiness_state`, `health_signals`,
`suggested_actions`) is computed by `factory.project_inspection` (Phase 13)
- this module is responsible only for discovering projects under a
`projects_root`, aggregating their summaries, and rendering the static
JSON/HTML board. `factory.review_gate` builds on the same
`project_inspection` layer independently, so the two can never disagree
about the same underlying facts without either depending on the other.

This module never generates CAD, renders images, exports STLs, runs
OpenSCAD, runs CadQuery, invokes a slicer, launches Blender, contacts a
network, or contacts a printer. The only files it writes are
`preview_board/index.json` and `preview_board/index.html` under the given
output directory - it never touches `brief.json`, `build_plan.json`,
`part_manifest.json`, or any file inside an individual project. See
docs/preview-board.md, docs/architecture.md, and AGENT.md.

Each project also gets a deterministic `suggested_actions` list - safe,
copyable local commands for the human to consider running next (e.g.
`factory render <path>` for a missing preview). Every action is advisory
only (`"safety": "manual_only"`) and this module never executes one, never
invokes a slicer/printer/network/cloud API, never launches Blender, and
never calls Meshy.

Each project also gets a deterministic `health_signals` summary: a
`summary` of `"ok"`/`"attention_needed"`/`"blocked"` plus structured
`items` (missing/unreadable brief or manifest, an unselected manufacturing
option, render coverage gaps, and local `validation/` report coverage -
`factory validate` is never run automatically, only checked for).
Severities always agree with `classify_visual_readiness()`'s own
precedence, and the only `"ready"` signal (`slicer_review_ready`)
explicitly means "ready for human slicer review", never an approval or
print-readiness claim.

Phase 27 added a per-project "Design Intent" overview card to the HTML
output only (`_build_project_card_html()` and friends) - Project Header,
Design Intent, Manufacturing Overview, Artifacts, and Review Readiness,
built entirely from fields `factory.project_inspection.summarize_project()`
already computes (including Phase 26/27's `design_intent_summary`/
`design_intent_detail`). Purely presentational: no new field is added to
the JSON board shape, no existing HTML section is removed, and this phase
introduces no JavaScript, no external assets, and no new judgment,
scoring, or approval semantics. See `docs/design-intent-brief.md` and
`docs/preview-board.md`.

Phase 28 added a compact "Reference Board" section to that same card,
right after "Design Intent" (references feed design intent) - reference
count, a license-status breakdown, a usage-intent breakdown, and any
advisory warnings, built from `factory.project_inspection.summarize_project()`'s
new `reference_board_summary` field (`factory.reference_board`). Same
guarantees as Phase 27: purely presentational, no JavaScript, no external
assets, and this module never reads, fetches, or contacts any reference's
`source_url` - it only displays a structured local record. See
`docs/reference-board.md`.

Phase 30 added a compact "Project Intake" section, placed *first* in the
card (upstream of Design Intent in this repo's pipeline: User Idea ->
Project Intake -> Project Brief -> Design Intent -> ...) - category,
audience, environment, quality target, material assumptions, and advisory
warnings, built from `summarize_project()`'s new `intake_summary` field
(`factory.project_intake`, a fully deterministic keyword/regex heuristic
engine - no AI, no LLM, no network). Same guarantees as Phase 27/28: purely
presentational, no JavaScript, no external assets. See
`docs/project-intake.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import project_store
from factory.project_inspection import (
    ACTION_SAFETY,
    HEALTH_SEVERITIES,
    VISUAL_READINESS_STATES,
    build_health_signals,
    build_suggested_actions,
    classify_visual_readiness,
    summarize_project,
)

BOARD_DIRNAME = "preview_board"
INDEX_FILENAME = "index.json"
HTML_FILENAME = "index.html"

REQUIRED_SAFETY_LINES = (
    "Local static preview only - no server, no cloud, no printer/slicer communication.",
    "This is a visual inspection aid, not an approval and not a print-readiness signal.",
    "Human visual inspection required.",
    "Human slicer review required.",
    "No project shown here is print-ready.",
)


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

_MANUFACTURABILITY_RESULT_LABELS = {
    "fits_some_printers": "Fits configured printers",
    "fits_no_known_printers": "Does not fit any configured printer",
    "no_max_size": "No size declared",
    "invalid_max_size": "Declared size is invalid",
    "missing_printer_config": "No printers configured",
    "no_design_intent": "No design intent recorded",
    "unreadable_file": "Brief could not be read",
}

_INTAKE_CATEGORY_LABELS = {
    "sign": "Sign",
    "organizer": "Organizer",
    "toy": "Toy",
    "décor": "Décor",
    "fixture": "Fixture",
    "mechanical": "Mechanical",
    "educational": "Educational",
    "storage": "Storage",
    "replacement part": "Replacement part",
    "accessory": "Accessory",
    "unknown": "Unknown",
}

_INTAKE_ENVIRONMENT_LABELS = {
    "classroom": "Classroom",
    "office": "Office",
    "home": "Home",
    "garage": "Garage",
    "outdoor": "Outdoor",
    "unknown": "Unknown",
}

_INTAKE_QUALITY_LABELS = {
    "prototype": "Prototype",
    "functional": "Functional",
    "premium": "Premium",
    "etsy-worthy": "Etsy-worthy",
    "presentation": "Presentation",
    "gift": "Gift",
    "unknown": "Unknown",
}

_REFERENCE_LICENSE_LABELS = {
    "unknown": "unknown",
    "personal_use": "personal use",
    "commercial_allowed": "commercial allowed",
    "cc_by": "CC BY",
    "cc_by_sa": "CC BY-SA",
    "cc_by_nc": "CC BY-NC",
    "public_domain": "public domain",
    "proprietary": "proprietary",
    "custom": "custom",
}

_REFERENCE_USAGE_INTENT_LABELS = {
    "design_reference_only": "design reference only",
    "remix_candidate": "remix candidate",
    "dimensional_reference": "dimensional reference",
    "style_reference": "style reference",
    "functional_reference": "functional reference",
    "manufacturing_reference": "manufacturing reference",
}


def _text_or_fallback(value: Any, placeholder: str) -> str:
    """Escape `value` if it's a non-empty string, else render `placeholder` in a
    dimmed span - so a Design Intent field is never left blank in the HTML."""
    if isinstance(value, str) and value.strip():
        return _escape_html(value)
    return f'<span class="none">{_escape_html(placeholder)}</span>'


def _di_row(label: str, value_html: str) -> str:
    return f'<div class="di-row"><span class="di-label">{_escape_html(label)}:</span> <span class="di-value">{value_html}</span></div>'


def _build_project_intake_section_html(intake: dict[str, Any] | None) -> str:
    """Render one project's `intake_summary` (Phase 30) into a compact static
    'Project Intake' card section - category, audience, environment, quality
    target, material assumptions, and advisory warnings. Placed first in the
    card, upstream of Design Intent in this repo's pipeline (User Idea ->
    Project Intake -> Project Brief -> Design Intent -> ...). Plain text
    only - no JavaScript. Every field degrades to a clear fallback rather
    than ever being left blank. Deliberately compact: per-field confidence
    levels and less commonly needed fields (printer assumptions,
    manufacturing style, functional/visual goals, dimensional constraints,
    commercial intent) are available via `factory intake analyze --json`
    and are not duplicated here.
    """
    if not intake:
        return '<div class="project-intake"><p class="none">No intake analysis available for this project.</p></div>'

    category = (intake.get("category") or {}).get("value")
    category_html = _escape_html(_INTAKE_CATEGORY_LABELS.get(category, category or "Unknown"))

    audience = (intake.get("audience") or {}).get("value")
    audience_html = _text_or_fallback(audience, "Not specified")

    environment = (intake.get("environment") or {}).get("value")
    environment_html = _escape_html(_INTAKE_ENVIRONMENT_LABELS.get(environment, environment or "Unknown"))

    quality = (intake.get("quality_target") or {}).get("value")
    quality_html = _escape_html(_INTAKE_QUALITY_LABELS.get(quality, quality or "Unknown"))

    materials = (intake.get("material_assumptions") or {}).get("value") or []
    material_html = _escape_html(", ".join(materials)) if materials else '<span class="none">Not specified</span>'

    rows = "".join(
        _di_row(label, value_html)
        for label, value_html in (
            ("Category", category_html),
            ("Audience", audience_html),
            ("Environment", environment_html),
            ("Quality", quality_html),
            ("Material", material_html),
        )
    )

    warnings = intake.get("warnings") or []
    if warnings:
        warnings_html = "".join(f"<li>{_escape_html(w)}</li>" for w in warnings)
        rows += f'<div class="di-row"><span class="di-label">Warnings:</span></div><ul class="di-warnings">{warnings_html}</ul>'
    else:
        rows += _di_row("Warnings", '<span class="none">None</span>')

    return f'<div class="project-intake">{rows}</div>'


def _build_design_intent_section_html(detail: dict[str, Any] | None) -> str:
    """Render one project's `design_intent_detail` (Phase 27) into a static
    'Design Intent' card section - Quality Target, Purpose, Style, and Design
    Notes. Plain text only - no JavaScript. Every field degrades to a clear
    fallback ("Not specified"/"None") rather than ever being left blank; most
    projects have no `design_intent` block at all, which renders a single
    explanatory line instead of empty rows.
    """
    if not detail:
        return '<div class="design-intent"><p class="none">No design intent declared for this project.</p></div>'

    style_direction = detail.get("style_direction")
    style_html = (
        _escape_html(" / ".join(style_direction)) if style_direction else '<span class="none">Not specified</span>'
    )
    design_notes = detail.get("design_notes")
    notes_html = _escape_html(design_notes) if design_notes else '<span class="none">None</span>'

    rows = "".join(
        _di_row(label, value_html)
        for label, value_html in (
            ("Quality", _text_or_fallback(detail.get("quality_standard"), "Not specified")),
            ("Purpose", _text_or_fallback(detail.get("use_case"), "Not specified")),
            ("Style", style_html),
            ("Design notes", notes_html),
        )
    )
    return f'<div class="design-intent">{rows}</div>'


def _build_reference_board_section_html(summary: dict[str, Any] | None) -> str:
    """Render one project's `reference_board_summary` (Phase 28) into a compact
    static 'Reference Board' card section - reference count, a license-status
    breakdown, a usage-intent breakdown, and any advisory warnings (e.g. an
    unknown/proprietary license, a missing source_url, or a reference not yet
    attached to `design_intent.reference_inputs`). Placed next to Design
    Intent because references feed design intent. Plain text only - no
    JavaScript. Every field degrades to a clear fallback rather than ever
    being left blank; a project with no references at all renders a single
    explanatory line instead of empty rows. Never fetches, downloads, or
    otherwise contacts any reference's `source_url`.
    """
    summary = summary or {}
    count = summary.get("reference_count", 0)
    if not count:
        return '<div class="reference-board"><p class="none">No references recorded for this project.</p></div>'

    def _breakdown_text(counts: dict[str, int], labels: dict[str, str]) -> str:
        if not counts:
            return "Not specified"
        return ", ".join(f"{n} {labels.get(key, key)}" for key, n in sorted(counts.items()))

    license_html = _escape_html(_breakdown_text(summary.get("by_license") or {}, _REFERENCE_LICENSE_LABELS))
    usage_html = _escape_html(_breakdown_text(summary.get("by_usage_intent") or {}, _REFERENCE_USAGE_INTENT_LABELS))

    rows = "".join(
        _di_row(label, value_html)
        for label, value_html in (
            ("References", _escape_html(str(count))),
            ("License status", license_html),
            ("Usage", usage_html),
        )
    )

    warnings = summary.get("warnings") or []
    if warnings:
        warnings_html = "".join(f"<li>{_escape_html(w)}</li>" for w in warnings)
        rows += f'<div class="di-row"><span class="di-label">Warnings:</span></div><ul class="di-warnings">{warnings_html}</ul>'
    else:
        rows += _di_row("Warnings", '<span class="none">None</span>')

    return f'<div class="reference-board">{rows}</div>'


def _build_manufacturing_overview_html(project: dict[str, Any]) -> str:
    """Render one project's manufacturing-related state into a static
    'Manufacturing Overview' card section: `build_plan.json`'s manufacturing
    status/selected option (already tracked elsewhere on the board) alongside
    the Phase 27 `design_intent_detail`'s manufacturability fit result,
    declared reference input count, and any advisory warnings. Plain text
    only - no JavaScript. Every field degrades to a clear fallback rather than
    ever being left blank.
    """
    status_html = _text_or_fallback(project.get("manufacturing_status"), "Not specified")
    option_html = _text_or_fallback(project.get("selected_manufacturing_option"), "Not selected")

    detail = project.get("design_intent_detail")
    if detail:
        result = detail.get("manufacturability_result")
        manufacturing_html = _escape_html(_MANUFACTURABILITY_RESULT_LABELS.get(result, result or "Unknown"))
        reference_count = detail.get("reference_input_count") or 0
        warnings = detail.get("warnings") or []
    else:
        manufacturing_html = '<span class="none">Unknown</span>'
        reference_count = 0
        warnings = []

    rows = "".join(
        _di_row(label, value_html)
        for label, value_html in (
            ("Manufacturing status", status_html),
            ("Selected option", option_html),
            ("Design-intent fit", manufacturing_html),
            ("Reference inputs", _escape_html(str(reference_count))),
        )
    )

    if warnings:
        warnings_html = "".join(f"<li>{_escape_html(w)}</li>" for w in warnings)
        rows += f'<div class="di-row"><span class="di-label">Warnings:</span></div><ul class="di-warnings">{warnings_html}</ul>'
    else:
        rows += _di_row("Warnings", '<span class="none">None</span>')

    return f'<div class="manufacturing-overview">{rows}</div>'


def _build_artifact_badges_html(project: dict[str, Any]) -> str:
    """Render lightweight CSS-only status badges for CAD/STL/render presence -
    no JavaScript, no external assets."""

    def badge(present: bool, label: str) -> str:
        cls = "badge-present" if present else "badge-missing"
        text = f"{label} Present" if present else f"{label} Missing"
        return f'<span class="badge {cls}">{_escape_html(text)}</span>'

    return (
        '<div class="artifact-badges">'
        + badge(bool(project.get("cad_files")), "CAD")
        + badge(bool(project.get("mesh_files")), "STL")
        + badge(bool(project.get("render_files")), "Render")
        + "</div>"
    )


def _build_health_mini_html(project: dict[str, Any]) -> str:
    """Compact health-signal badge for a project's card - the full per-item
    breakdown remains in the existing 'Health signals' section further down
    the page (see `_build_health_signals_html`); this is just a glanceable
    pointer, not a duplicate of that detail."""
    health = project.get("health_signals") or {"summary": "ok", "items": []}
    summary = health.get("summary", "ok")
    label = _HEALTH_SUMMARY_LABELS.get(summary, summary)
    count = len(health.get("items") or [])
    text = f"{label} ({count})" if count else label
    return (
        '<div class="health-mini">'
        f'<span class="badge health-summary-{_escape_html(summary)}">{_escape_html(text)}</span> '
        '<span class="di-value">see &ldquo;Health signals&rdquo; below for details</span>'
        "</div>"
    )


def _build_review_readiness_html(project: dict[str, Any]) -> str:
    """Render a project's `visual_readiness_state` as a Review Ready / Review
    Not Ready badge. `slicer_review_ready` means ready for *human* slicer
    review only - never an approval or print-readiness claim, exactly as
    elsewhere on this board."""
    state = project.get("visual_readiness_state")
    ready = state == "slicer_review_ready"
    cls = "badge-review-ready" if ready else "badge-review-not-ready"
    text = "Review Ready" if ready else "Review Not Ready"
    state_label = _STATE_LABELS.get(state, state or "Unknown")
    return (
        '<div class="review-readiness">'
        f'<span class="badge {cls}">{_escape_html(text)}</span> '
        f'<span class="di-value">{_escape_html(state_label)}</span>'
        "</div>"
    )


def _build_project_card_html(project: dict[str, Any]) -> str:
    """Render one project's overview card: Project Header, Project Intake
    (Phase 30), Design Intent (Phase 27), Reference Board (Phase 28),
    Manufacturing Overview, Artifacts, Health Signals, and Review Readiness -
    in that order, matching this repo's pipeline (User Idea -> Project
    Intake -> Project Brief -> Design Intent -> Reference Board -> ...).
    Static HTML/CSS only - no JavaScript, no external assets. Purely
    presentational: it never recomputes or overrides
    `visual_readiness_state`, `health_signals`, or `suggested_actions`, it
    only displays fields `factory.project_inspection.summarize_project()`
    already computed.
    """
    project_name = project.get("project_name") or "(unnamed project)"
    project_dir = project.get("project_dir") or ""

    return (
        '<div class="project-card">'
        f'<h3 class="card-title">{_escape_html(project_name)} <code>{_escape_html(project_dir)}</code></h3>'
        '<div class="card-section"><h4>Project Intake</h4>'
        + _build_project_intake_section_html(project.get("intake_summary"))
        + "</div>"
        '<div class="card-section"><h4>Design Intent</h4>'
        + _build_design_intent_section_html(project.get("design_intent_detail"))
        + "</div>"
        '<div class="card-section"><h4>Reference Board</h4>'
        + _build_reference_board_section_html(project.get("reference_board_summary"))
        + "</div>"
        '<div class="card-section"><h4>Manufacturing Overview</h4>'
        + _build_manufacturing_overview_html(project)
        + "</div>"
        '<div class="card-section"><h4>Artifacts</h4>'
        + _build_artifact_badges_html(project)
        + "</div>"
        '<div class="card-section"><h4>Health Signals</h4>'
        + _build_health_mini_html(project)
        + "</div>"
        '<div class="card-section"><h4>Review Readiness</h4>'
        + _build_review_readiness_html(project)
        + "</div>"
        "</div>"
    )


def _build_project_cards_html(projects: list[dict[str, Any]]) -> str:
    """Render every project's Phase 27 overview card - see
    `_build_project_card_html`. This is additive presentation only; it never
    replaces the existing summary table, health-signals section, or
    suggested-actions section below it."""
    if not projects:
        return "<p>No projects found under this projects_root.</p>"
    return "".join(_build_project_card_html(project) for project in projects)


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
    project_cards_html = _build_project_cards_html(board["projects"])

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
  .cards {{ margin: 1.5rem 0; }}
  .cards-intro {{ color: #555; }}
  .project-card {{ background: #fff; border: 1px solid #ddd; border-radius: 0.5rem; padding: 1rem 1.25rem; margin-bottom: 1rem; }}
  .project-card .card-title {{ margin: 0 0 0.75rem 0; font-size: 1.15rem; }}
  .card-section {{ margin-bottom: 0.85rem; }}
  .card-section:last-child {{ margin-bottom: 0; }}
  .card-section h4 {{ margin: 0 0 0.35rem 0; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.04em; color: #777; }}
  .di-row {{ font-size: 0.9rem; margin-bottom: 0.2rem; }}
  .di-label {{ font-weight: 600; color: #444; }}
  .di-value {{ color: #1a1a1a; }}
  ul.di-warnings {{ margin: 0.25rem 0 0 0; padding-left: 1.1rem; font-size: 0.85rem; color: #7a5c00; }}
  .design-intent p.none, .reference-board p.none, .project-intake p.none {{ margin: 0; }}
  .artifact-badges .badge {{ margin-right: 0.35rem; }}
  .badge-present {{ background: #d4edda; color: #1e5b2e; }}
  .badge-missing {{ background: #eee; color: #666; }}
  .badge-review-ready {{ background: #d4edda; color: #1e5b2e; }}
  .badge-review-not-ready {{ background: #fde2e2; color: #8a1f1f; }}
</style>
</head>
<body>
<h1>ai-3d-factory preview board</h1>
<p class="meta">Generated {_escape_html(board["generated_at"])} &middot; projects_root: <code>{_escape_html(board["projects_root"])}</code> &middot; {board["project_count"]} project(s)</p>
<p>{state_summary}</p>
<div class="cards">
<h2>Project Overview</h2>
<p class="cards-intro">Design intent (if the brief declares one), manufacturing overview, artifact
presence, and readiness at a glance for each project. Advisory only - see the detailed sections
below for the full picture; nothing here is an approval or a print-readiness signal.</p>
{project_cards_html}
</div>
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

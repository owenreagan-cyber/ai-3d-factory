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

Phase 31 added a compact "Draft Brief" section right after "Project
Intake" - readiness status, percent populated, unknown-field count, and a
standing "Human review required" reminder, built from
`summarize_project()`'s new `draft_brief_summary` field
(`factory.brief_generator`, derived from `intake_summary` - never
re-parses free text). Same guarantees as every other card section here:
purely presentational, no JavaScript, no external assets, and this card
never writes anything - the only write path
(`factory intake suggest-brief --write`) is a separate, explicit,
human-run CLI command. See `docs/brief-generator.md`.

Phase 32 added a compact "Brief Update" section right after "Draft Brief"
- built from `summarize_project()`'s new `brief_update_summary` field
(`factory.brief_generator.summarize_brief_update()`, comparing the
project's existing `brief.json` against its draft). Deliberately terse:
when there's nothing meaningful to merge (the common case for a fully
human-authored brief), this renders one line ("Up to date - nothing to
merge.") rather than a whole block, so the board doesn't get noisy with a
mostly-empty section on every project. Same guarantees as every other card
section: purely presentational, and this card never merges or writes
anything - the only write path (`factory intake suggest-brief --write
--update`) is a separate, explicit, human-run CLI command. See "Merge mode
(Phase 32)" in `docs/brief-generator.md`.

Phase 33 added a "Project Readiness" dashboard section, placed *first* in
each project's card (a summary of everything below it, not a replacement
for any of it) - built from `summarize_project()`'s new
`design_orchestrator_summary` field (`factory.design_orchestrator`,
consumes the six summaries above without re-parsing any of them): overall
weighted readiness score, recommended downstream engine (OpenSCAD,
CadQuery, Blender, Meshy, FreeCAD, a hybrid workflow, manual design, or
"unknown"), the readiness state, and the top remaining advisories. Same
guarantees as every other card section: purely presentational, no
JavaScript, no external assets - and this module never generates CAD or
invokes any engine; `recommended_engine` is a string a human reads and
acts on themselves. Every existing detail card (Project Intake, Draft
Brief, Brief Update, Design Intent, Reference Board, Manufacturing
Overview, Artifacts, Health Signals, Review Readiness) is unchanged and
still follows the dashboard. See `docs/design-orchestrator.md`.

Phase 34 added a compact "Generation Gate" section, placed right after
"Project Readiness" (both are "meta" cards summarizing what's possible
next) - built from `summarize_project()`'s new `generation_gate_summary`
field (`factory.generation_gate`, a dry-run-only adapter/gate around this
repo's *existing* local CAD generation - the OpenSCAD and CadQuery
backends - that reuses `design_orchestrator`'s readiness evaluation
without duplicating any scoring or engine-recommendation logic): the gate
decision (Allowed, Needs Confirmation, Blocked, Unsupported Engine, or Dry
Run Only), the recommended engine, a Ready Yes/No badge, and (if not
ready) the top reason why. Same guarantees as every other card section:
purely presentational, no JavaScript, no external assets - and this board
never generates CAD or invokes any engine; the only write path (`factory
generate-from-readiness --confirm-generate`) is a separate, explicit,
human-run CLI command the preview board never invokes. Every existing
detail card is unchanged and still follows the dashboard. See
`docs/generation-gate.md`.
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
from factory.slicer_readiness import summarize_slicer_readiness
from factory.manual_review_workspace import summarize_manual_review_workspace
from factory.slicer_intelligence import summarize_slicer_intelligence
from factory.slicer_history import summarize_slicer_history
from factory.project_timeline import summarize_project_timeline

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
    anything. Merges `slicer_readiness_summary` (Phase 36),
    `manual_review_summary` (Phase 37), `slicer_intelligence_summary`
    (Phase 38), `slicer_history_summary` (Phase 39), and
    `timeline_summary` (Phase 40) into each project's dict here, at the
    aggregation point, rather than inside
    `factory.project_inspection.summarize_project()` itself - see the
    standing "Aggregation Layer Convention" in `docs/architecture.md` (and
    each module's own "Architectural note") for why: all five either
    directly or transitively consume `factory.review_gate`, which already
    imports `project_inspection`, so adding any of them inside
    `project_inspection.py` would be a circular import. This function is
    where those layers meet instead. `summarize_slicer_history()`/
    `summarize_project_timeline()` only ever read existing receipts/
    history if they already exist - neither ever writes one; history is
    only ever created by an explicit `factory slicer-inspect
    --save-analysis` call, never by board generation.
    """
    projects_root = Path(projects_root)
    project_dirs = discover_projects(projects_root)
    projects = [summarize_project(p, projects_root=projects_root) for p in project_dirs]
    for project, project_dir in zip(projects, project_dirs):
        project["slicer_readiness_summary"] = summarize_slicer_readiness(project_dir)
        project["manual_review_summary"] = summarize_manual_review_workspace(project_dir)
        project["slicer_intelligence_summary"] = summarize_slicer_intelligence(project_dir)
        project["slicer_history_summary"] = summarize_slicer_history(project_dir)
        project["timeline_summary"] = summarize_project_timeline(project_dir)

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


_READINESS_STATE_BADGE_CLASSES = {
    "Not Ready": "badge-missing",
    "Needs Information": "health-warning",
    "Ready For Mechanical CAD": "badge-present",
    "Ready For Organic Modeling": "badge-present",
    "Ready For Mixed Workflow": "badge-present",
    "Ready For Manufacturing Review": "badge-review-ready",
    "Blocked": "health-blocked",
}


def _build_project_readiness_section_html(summary: dict[str, Any] | None) -> str:
    """Render one project's `design_orchestrator_summary` (Phase 33) into a
    compact static 'Project Readiness' dashboard section - overall score,
    recommended engine, readiness state, and the top remaining advisories.
    Placed *first* in the card (a dashboard summarizing everything below
    it, not a replacement for any of it - every existing detail card
    stays). Plain text only - no JavaScript. This section never generates
    CAD or invokes any engine - `recommended_engine` is a string a human
    reads and acts on themselves.
    """
    if not summary:
        return '<div class="project-readiness"><p class="none">No readiness analysis available for this project.</p></div>'

    score = summary.get("score") or {}
    overall = score.get("overall")
    overall_html = f"{overall}%" if isinstance(overall, (int, float)) else "Unknown"

    state = summary.get("readiness_state") or "Unknown"
    state_badge_class = _READINESS_STATE_BADGE_CLASSES.get(state, "badge-missing")

    engine = summary.get("recommended_engine") or "Unknown"

    rows = "".join(
        _di_row(label, value_html)
        for label, value_html in (
            ("Overall", _escape_html(overall_html)),
            ("Ready for", _escape_html(engine)),
            ("Status", f'<span class="badge {state_badge_class}">{_escape_html(state)}</span>'),
        )
    )

    advisories = summary.get("advisories") or []
    if advisories:
        items_html = "".join(f"<li>{_escape_html(a)}</li>" for a in advisories)
        rows += f'<div class="di-row"><span class="di-label">Remaining:</span></div><ul class="di-warnings">{items_html}</ul>'
    else:
        rows += _di_row("Remaining", '<span class="none">None</span>')

    return f'<div class="project-readiness">{rows}</div>'


_GENERATION_GATE_DECISION_BADGE_CLASSES = {
    "Allowed": "badge-review-ready",
    "Needs Confirmation": "health-warning",
    "Blocked": "health-blocked",
    "Unsupported Engine": "badge-missing",
    "Dry Run Only": "health-warning",
}


def _build_generation_gate_section_html(
    summary: dict[str, Any] | None, execution_summary: dict[str, Any] | None = None
) -> str:
    """Render one project's `generation_gate_summary` (Phase 34) into a
    compact static 'Generation Gate' card section - decision, recommended
    engine, a Ready Yes/No badge, the top reason why (if not ready), and
    (Phase 34 execution receipts) whether a confirmed generation has ever
    actually run and when. Placed right after "Project Readiness" (both
    are "meta" cards summarizing what's possible next). Plain text only -
    no JavaScript. This card never generates CAD or invokes any engine -
    the only write path (`factory generate-from-readiness
    --confirm-generate`) is a separate, explicit, human-run CLI command
    the preview board never invokes; "Last execution"/"Receipt available"
    are read straight from `generation_execution_summary`
    (`factory.generation_gate.summarize_generation_execution()`), which
    itself only ever reads a receipt file already written by a prior,
    separate, human-run confirmed generation - never computed or inferred
    here.
    """
    if not summary:
        return '<div class="generation-gate"><p class="none">No generation gate analysis available for this project.</p></div>'

    decision = summary.get("decision") or "Unknown"
    badge_class = _GENERATION_GATE_DECISION_BADGE_CLASSES.get(decision, "badge-missing")
    engine = summary.get("recommended_engine") or "Unknown"
    ready_html = "Yes" if summary.get("ready") else "No"

    rows = "".join(
        _di_row(label, value_html)
        for label, value_html in (
            ("Decision", f'<span class="badge {badge_class}">{_escape_html(decision)}</span>'),
            ("Engine", _escape_html(engine)),
            ("Ready", _escape_html(ready_html)),
        )
    )
    rows += _di_row("Reason", _text_or_fallback(summary.get("reason"), "None"))

    execution_summary = execution_summary or {}
    receipt_available_html = "Yes" if execution_summary.get("receipt_available") else "No"
    rows += _di_row("Receipt available", _escape_html(receipt_available_html))
    rows += _di_row("Last execution", _text_or_fallback(execution_summary.get("last_execution"), "Never"))

    return f'<div class="generation-gate">{rows}</div>'


_EXPORT_STATUS_LABELS = {
    "current": "Current",
    "stale": "Stale",
    "missing": "Missing",
}

_EXPORT_VALIDATION_LABELS = {
    "not_run": "Not run",
    "passed": "Passed",
    "passed_with_warnings": "Passed with warnings",
    "failed": "Failed",
    "unavailable": "Unavailable",
    "partial": "Partial",
}

_EXPORT_PREVIEW_LABELS = {
    "not_run": "Missing",
    "passed": "Available",
    "stale": "Stale",
    "failed": "Failed",
    "unavailable": "Unavailable",
    "partial": "Partial",
}

_EXPORT_ARTIFACT_BADGE_CLASSES = {
    "current": "badge-review-ready",
    "passed": "badge-review-ready",
    "stale": "health-warning",
    "passed_with_warnings": "health-warning",
    "partial": "health-warning",
    "missing": "badge-missing",
    "not_run": "badge-missing",
    "failed": "health-blocked",
    "unavailable": "badge-missing",
}


def _build_export_pipeline_section_html(summary: dict[str, Any] | None) -> str:
    """Render one project's `export_pipeline_summary` (Phase 35) into a
    compact static 'Post-Generation Pipeline' card section - CAD source,
    STL, validation, and preview status, plus either the next suggested
    step or (once the pipeline is complete) a reminder that human review
    is still pending. Placed right after "Generation Gate" (all three -
    Project Readiness, Generation Gate, Post-Generation Pipeline - are
    "meta" cards summarizing what's possible next). Plain text only - no
    JavaScript. This card never exports, validates, renders, or invokes a
    subprocess - the only write/execution path
    (`factory export-from-cad --confirm-export`/`--validate`/`--render`)
    is a separate, explicit, human-run CLI command the preview board never
    invokes.
    """
    if not summary:
        return '<div class="export-pipeline"><p class="none">No export pipeline analysis available for this project.</p></div>'

    cad_status = summary.get("cad_source_status") or "missing"
    stl_status = summary.get("stl_status") or "missing"
    validation_status = summary.get("validation_status") or "not_run"
    preview_status = summary.get("preview_status") or "not_run"

    def _badge(value: str, label: str) -> str:
        badge_class = _EXPORT_ARTIFACT_BADGE_CLASSES.get(value, "badge-missing")
        return f'<span class="badge {badge_class}">{_escape_html(label)}</span>'

    rows = "".join(
        _di_row(label, value_html)
        for label, value_html in (
            ("CAD source", _badge(cad_status, _EXPORT_STATUS_LABELS.get(cad_status, cad_status.title()))),
            ("STL", _badge(stl_status, _EXPORT_STATUS_LABELS.get(stl_status, stl_status.title()))),
            (
                "Validation",
                _badge(validation_status, _EXPORT_VALIDATION_LABELS.get(validation_status, validation_status)),
            ),
            ("Preview", _badge(preview_status, _EXPORT_PREVIEW_LABELS.get(preview_status, preview_status))),
        )
    )

    if summary.get("pipeline_complete"):
        rows += _di_row("Review", "Pending human approval")
    else:
        rows += _di_row("Next step", _text_or_fallback(summary.get("next_step"), "None"))

    return f'<div class="export-pipeline">{rows}</div>'


_SLICER_READINESS_STATUS_LABELS = {
    "unsupported_project_state": "Unsupported project state",
    "blocked": "Blocked",
    "not_ready": "Not ready",
    "stale_artifacts": "Stale artifacts",
    "needs_validation": "Needs validation",
    "needs_preview": "Needs preview",
    "needs_manifest_completion": "Needs manifest completion",
    "needs_information": "Needs information",
    "needs_human_approval": "Needs human approval",
    "ready_for_review_package": "Ready for review package",
    "review_package_created": "Review package created",
}

_SLICER_READINESS_STATUS_BADGE_CLASSES = {
    "unsupported_project_state": "badge-missing",
    "blocked": "health-blocked",
    "not_ready": "health-blocked",
    "stale_artifacts": "health-warning",
    "needs_validation": "health-warning",
    "needs_preview": "health-warning",
    "needs_manifest_completion": "health-warning",
    "needs_information": "health-warning",
    "needs_human_approval": "health-warning",
    "ready_for_review_package": "badge-review-ready",
    "review_package_created": "badge-review-ready",
}

_SLICER_READINESS_APPROVAL_LABELS = {
    "not_approved": "Not approved",
    "approved": "Approved",
    "invalidated": "Invalidated - source changed",
}

_SLICER_READINESS_PACKAGE_LABELS = {
    "not_created": "Not created",
    "current": "Current",
    "stale": "Stale - source changed",
    "unknown": "Unknown",
}


def _build_slicer_readiness_section_html(summary: dict[str, Any] | None) -> str:
    """Render one project's `slicer_readiness_summary` (Phase 36) into a
    compact static 'Slicer Review Readiness' card section - technical
    readiness status, score, human approval status, and review package
    status. Placed right after "Post-Generation Pipeline" (all four - Project
    Readiness, Generation Gate, Post-Generation Pipeline, Slicer Review
    Readiness - are "meta" cards summarizing what's possible next). Plain
    text only - no JavaScript. This card never assesses, approves, or
    creates a package itself - it only displays what
    `factory.slicer_readiness.summarize_slicer_readiness()` already computed
    read-only from existing receipts/state; the only write paths (`factory
    slicer-readiness --approve` / `--create-package --confirm-package`) are
    separate, explicit, human-run CLI commands the preview board never
    invokes. It never opens a slicer, uploads a file, queues, or prints
    anything.
    """
    if not summary:
        return '<div class="slicer-readiness"><p class="none">No slicer readiness analysis available for this project.</p></div>'

    status = summary.get("status") or "unsupported_project_state"
    status_badge_class = _SLICER_READINESS_STATUS_BADGE_CLASSES.get(status, "badge-missing")
    status_label = _SLICER_READINESS_STATUS_LABELS.get(status, status)

    approval_status = summary.get("approval_status") or "not_approved"
    approval_label = _SLICER_READINESS_APPROVAL_LABELS.get(approval_status, approval_status)
    approval_badge_class = "badge-review-ready" if approval_status == "approved" else "badge-missing"

    package_status = summary.get("package_status") or "not_created"
    package_label = _SLICER_READINESS_PACKAGE_LABELS.get(package_status, package_status)
    package_badge_class = "badge-review-ready" if package_status == "current" else "badge-missing"

    score = summary.get("score")
    score_html = f"{score}%" if isinstance(score, (int, float)) else "Unknown"

    rows = "".join(
        _di_row(label, value_html)
        for label, value_html in (
            ("Status", f'<span class="badge {status_badge_class}">{_escape_html(status_label)}</span>'),
            ("Score", _escape_html(score_html)),
            ("Human approval", f'<span class="badge {approval_badge_class}">{_escape_html(approval_label)}</span>'),
            ("Review package", f'<span class="badge {package_badge_class}">{_escape_html(package_label)}</span>'),
        )
    )

    blocker_count = summary.get("blocker_count") or 0
    warning_count = summary.get("warning_count") or 0
    rows += _di_row("Blockers", _escape_html(str(blocker_count)))
    rows += _di_row("Warnings", _escape_html(str(warning_count)))
    rows += _di_row("Next action", _text_or_fallback(summary.get("next_action"), "None"))

    return f'<div class="slicer-readiness">{rows}</div>'


_WORKSPACE_STATUS_LABELS = {
    "not_ready": "Not ready",
    "needs_approval": "Needs approval",
    "ready_to_create": "Ready to create",
    "stale_workspace": "Stale",
    "workspace_created": "Ready",
}

_WORKSPACE_STATUS_BADGE_CLASSES = {
    "not_ready": "health-blocked",
    "needs_approval": "health-warning",
    "ready_to_create": "health-warning",
    "stale_workspace": "health-warning",
    "workspace_created": "badge-review-ready",
}

_CONFIDENCE_BADGE_CLASSES = {
    "High": "badge-review-ready",
    "Medium": "health-warning",
    "Low": "health-blocked",
    "Unknown": "badge-missing",
}

_RISK_BADGE_CLASSES = {
    "Low": "badge-review-ready",
    "Moderate": "health-warning",
    "High": "health-blocked",
    "Unknown": "badge-missing",
}


def _build_manual_review_workspace_section_html(summary: dict[str, Any] | None) -> str:
    """Render one project's `manual_review_summary` (Phase 37) into a
    compact static 'Manual Review Workspace' card section - workspace
    status, printer, material, review confidence, remaining risk, and
    review-package availability. Placed right after "Slicer Review
    Readiness" (all five - Project Readiness, Generation Gate,
    Post-Generation Pipeline, Slicer Review Readiness, Manual Review
    Workspace - are "meta" cards summarizing what's possible next). Plain
    text only - no JavaScript. This card never assesses or creates a
    workspace itself - it only displays what
    `factory.manual_review_workspace.summarize_manual_review_workspace()`
    already computed read-only from existing receipts/state; the only
    write path (`factory review-workspace --create-workspace
    --confirm-workspace`) is a separate, explicit, human-run CLI command
    the preview board never invokes. It never opens a slicer, generates
    G-code, or prints anything.
    """
    if not summary:
        return '<div class="manual-review-workspace"><p class="none">No manual review workspace analysis available for this project.</p></div>'

    status = summary.get("workspace_status") or "not_ready"
    status_badge_class = _WORKSPACE_STATUS_BADGE_CLASSES.get(status, "badge-missing")
    status_label = _WORKSPACE_STATUS_LABELS.get(status, status)

    confidence = summary.get("review_confidence") or "Unknown"
    confidence_badge_class = _CONFIDENCE_BADGE_CLASSES.get(confidence, "badge-missing")

    risk = summary.get("remaining_risk") or "Unknown"
    risk_badge_class = _RISK_BADGE_CLASSES.get(risk, "badge-missing")

    package_available = bool(summary.get("package_available"))
    package_badge_class = "badge-review-ready" if package_available else "badge-missing"
    package_label = "Available" if package_available else "Not available"

    printer_name = summary.get("printer_display_name") or "Unknown"
    material_label = "Multi-material" if summary.get("material_multi") else "Single material"
    if summary.get("material_unresolved"):
        material_label += " (unresolved)"

    rows = "".join(
        _di_row(label, value_html)
        for label, value_html in (
            ("Workspace", f'<span class="badge {status_badge_class}">{_escape_html(status_label)}</span>'),
            ("Printer", _escape_html(printer_name)),
            ("Material", _escape_html(material_label)),
            ("Review confidence", f'<span class="badge {confidence_badge_class}">{_escape_html(confidence)}</span>'),
            ("Remaining risk", f'<span class="badge {risk_badge_class}">{_escape_html(risk)}</span>'),
            ("Package", f'<span class="badge {package_badge_class}">{_escape_html(package_label)}</span>'),
        )
    )

    rows += _di_row("Next action", _text_or_fallback(summary.get("next_action"), "None"))
    rows += '<div class="di-row"><span class="di-label">Human review required</span></div>'

    return f'<div class="manual-review-workspace">{rows}</div>'


_BUILD_VOLUME_FIT_LABELS = {
    "fits": "Fits",
    "does_not_fit": "Does Not Fit",
    "unknown": "Unknown",
}

_BUILD_VOLUME_FIT_BADGE_CLASSES = {
    "fits": "badge-review-ready",
    "does_not_fit": "health-blocked",
    "unknown": "badge-missing",
}


def _relative_analysis_age_label(timestamp_iso: str | None) -> str:
    """Format a saved snapshot's timestamp as a short relative age label
    ("Today"/"Yesterday"/"N days ago") for the Preview Board card - never
    used for any decision, purely a display convenience."""
    if not timestamp_iso:
        return "Unknown"
    try:
        from datetime import datetime, timezone

        ts = datetime.fromisoformat(timestamp_iso)
        now = datetime.now(timezone.utc)
        delta_days = (now.date() - ts.date()).days
    except (TypeError, ValueError):
        return "Unknown"
    if delta_days == 0:
        return "Today"
    if delta_days == 1:
        return "Yesterday"
    if delta_days > 1:
        return f"{delta_days} days ago"
    return ts.date().isoformat()


def _build_slicer_intelligence_section_html(
    summary: dict[str, Any] | None, history_summary: dict[str, Any] | None = None
) -> str:
    """Render one project's `slicer_intelligence_summary` (Phase 38) into a
    compact static 'Slicer Intelligence' card section - risk level, build
    volume fit, review item count, top review priority, analysis
    confidence, and (Phase 39) the detected slicer profile plus a compact
    analysis-history addendum (last saved analysis age, change count since
    then). Placed right after "Manual Review Workspace" (all six - Project
    Readiness, Generation Gate, Post-Generation Pipeline, Slicer Review
    Readiness, Manual Review Workspace, Slicer Intelligence - are "meta"
    cards summarizing what's possible next). Plain text only - no
    JavaScript. This card never analyzes anything itself, never saves a
    history snapshot, and never compares anything live - it only displays
    what `factory.slicer_intelligence.summarize_slicer_intelligence()` and
    `factory.slicer_history.summarize_slicer_history()` already computed
    read-only from existing validation reports/receipts/history state. It
    never opens a slicer, generates G-code, or prints anything -
    `risk_level` here is purely informational, never a blocker. The
    history addendum rows are omitted entirely for a project with no saved
    snapshot yet, rather than showing a "Never"/"0" placeholder - kept
    deliberately quiet per this phase's "do not make the board noisy"
    requirement.
    """
    if not summary:
        return '<div class="slicer-intelligence"><p class="none">No slicer intelligence analysis available for this project.</p></div>'

    risk = summary.get("risk_level") or "Unknown"
    risk_badge_class = _RISK_BADGE_CLASSES.get(risk, "badge-missing")

    fit_status = summary.get("build_volume_fit") or "unknown"
    fit_badge_class = _BUILD_VOLUME_FIT_BADGE_CLASSES.get(fit_status, "badge-missing")
    fit_label = _BUILD_VOLUME_FIT_LABELS.get(fit_status, fit_status)

    confidence = summary.get("confidence") or "Unknown"
    confidence_badge_class = _CONFIDENCE_BADGE_CLASSES.get(confidence, "badge-missing")

    profile_name = summary.get("slicer_profile_name") or "Unknown"

    rows = "".join(
        _di_row(label, value_html)
        for label, value_html in (
            ("Profile", _escape_html(profile_name)),
            ("Risk", f'<span class="badge {risk_badge_class}">{_escape_html(risk)}</span>'),
            ("Build", f'<span class="badge {fit_badge_class}">{_escape_html(fit_label)}</span>'),
            ("Review items", _escape_html(str(summary.get("review_item_count") or 0))),
            ("Priority", _text_or_fallback(summary.get("top_priority"), "None")),
            ("Confidence", f'<span class="badge {confidence_badge_class}">{_escape_html(confidence)}</span>'),
        )
    )

    history_summary = history_summary or {}
    if history_summary.get("history_available"):
        latest = history_summary.get("latest_analysis") or {}
        age_label = _relative_analysis_age_label(latest.get("timestamp"))
        rows += _di_row("Last Analysis", _escape_html(age_label))

        changes_detected = history_summary.get("changes_detected")
        risk_change = history_summary.get("risk_change")
        if changes_detected is not None:
            rows += _di_row("Changes", _escape_html(f"{changes_detected} detected"))
            if changes_detected > 0 or risk_change:
                rows += '<div class="di-row"><span class="badge health-warning">Review Needed</span></div>'

    rows += '<div class="di-row"><span class="di-label">Human review required</span></div>'

    return f'<div class="slicer-intelligence">{rows}</div>'


def _build_project_timeline_section_html(summary: dict[str, Any] | None) -> str:
    """Render one project's `timeline_summary` (Phase 40) into a compact
    static 'Project Timeline' card section - total event count, how many
    have a real recorded date vs. are date-unavailable (predate
    `status_history` tracking), and the latest dated event. Placed right
    after "Slicer Intelligence" (all seven - Project Readiness, Generation
    Gate, Post-Generation Pipeline, Slicer Review Readiness, Manual Review
    Workspace, Slicer Intelligence, Project Timeline - are "meta" cards
    summarizing what's possible next). Plain text only - no JavaScript.
    This card never computes an event itself - it only displays what
    `factory.project_timeline.summarize_project_timeline()` already
    computed read-only from existing receipts/history; it never writes
    anything, never invokes a subprocess, never contacts a printer/slicer/
    network. Deliberately terse: the full chronological event list is
    `factory timeline <project>`'s job, not this card's - a project with
    no events yet renders a single explanatory line rather than an empty
    section.
    """
    if not summary:
        return '<div class="project-timeline"><p class="none">No timeline data available for this project.</p></div>'

    event_count = summary.get("event_count") or 0
    if event_count == 0:
        return '<div class="project-timeline"><p class="none">No timeline events recorded yet for this project.</p></div>'

    unavailable_count = summary.get("unavailable_event_count") or 0
    latest = summary.get("latest_event")

    rows = _di_row("Events", _escape_html(str(event_count)))
    if latest:
        latest_label = f"{latest.get('label')} ({latest.get('date')})"
        rows += _di_row("Latest", _escape_html(latest_label))
    if unavailable_count:
        rows += _di_row(
            "Tracking",
            _escape_html(f"Partial - {unavailable_count} early stage(s) predate history tracking"),
        )

    return f'<div class="project-timeline">{rows}</div>'


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


def _build_draft_brief_section_html(summary: dict[str, Any] | None) -> str:
    """Render one project's `draft_brief_summary` (Phase 31) into a compact
    static 'Draft Brief' card section - readiness status, percent populated,
    unknown-field count, and a standing "Human review required" reminder.
    Placed right after "Project Intake" (a draft brief is the next pipeline
    step after intake, before Design Intent). Plain text only - no
    JavaScript. This card never links to or triggers a write - `factory
    intake suggest-brief --write` is a separate, explicit, human-run
    command; nothing here writes a file.
    """
    if not summary:
        return '<div class="draft-brief"><p class="none">No draft brief available for this project.</p></div>'

    readiness = summary.get("readiness") or {}
    status = readiness.get("status") or "Unknown"
    percent = readiness.get("percent_populated")
    percent_html = f"{percent}%" if isinstance(percent, (int, float)) else "Unknown"
    unknown_count = readiness.get("unknown_count")
    unknown_html = str(unknown_count) if isinstance(unknown_count, int) else "Unknown"

    rows = "".join(
        _di_row(label, value_html)
        for label, value_html in (
            ("Status", f'<span class="badge badge-present">{_escape_html(status)}</span>'),
            ("Populated", _escape_html(percent_html)),
            ("Unknown fields", _escape_html(unknown_html)),
        )
    )
    rows += _di_row("Review", '<span class="none">Human review required</span>')

    return f'<div class="draft-brief">{rows}</div>'


def _build_brief_update_section_html(summary: dict[str, Any] | None) -> str:
    """Render one project's `brief_update_summary` (Phase 32) into a compact
    static 'Brief Update' card section - deliberately terse compared to the
    other cards: when there's nothing meaningful to merge (the common case
    for a fully human-authored brief), this renders a single line rather
    than a whole block, so the board doesn't get noisy with a mostly-empty
    section on every project. When a safe merge *is* available, it shows
    how many fields would be added vs. preserved. This card never links to
    or triggers a write - `factory intake suggest-brief --write --update`
    is a separate, explicit, human-run command; nothing here merges or
    writes a file.
    """
    if not summary:
        return '<div class="brief-update"><p class="none">No brief update analysis available for this project.</p></div>'

    if not summary.get("merge_available"):
        return '<div class="brief-update"><p class="none">Up to date - nothing to merge.</p></div>'

    add_count = summary.get("fields_to_add_count", 0)
    preserved_count = summary.get("fields_preserved_count", 0)

    rows = "".join(
        _di_row(label, value_html)
        for label, value_html in (
            ("Status", '<span class="badge badge-present">Merge available</span>'),
            ("Fields to add", _escape_html(str(add_count))),
            ("Preserved", _escape_html(str(preserved_count))),
        )
    )
    rows += _di_row("Review", '<span class="none">Human review required</span>')

    return f'<div class="brief-update">{rows}</div>'


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
    """Render one project's overview card: Project Readiness dashboard
    (Phase 33), Generation Gate (Phase 34), Post-Generation Pipeline
    (Phase 35), Slicer Review Readiness (Phase 36), Project Header, Project
    Intake (Phase 30), Draft Brief (Phase 31), Brief Update (Phase 32),
    Design Intent (Phase 27), Reference Board (Phase 28), Manufacturing
    Overview, Artifacts, Health Signals, and Review Readiness - in that
    order, matching this repo's pipeline (User Idea -> Project Intake ->
    Draft Brief -> Brief Merge/Update -> Design Intent -> Reference Board ->
    Project Readiness -> Design Orchestrator -> Readiness-Gated CAD Router
    -> CAD Source Generation -> Guided Export Pipeline -> Slicer Review
    Readiness Promotion -> ...). Static HTML/CSS only - no JavaScript, no
    external assets. Purely presentational: it never recomputes or
    overrides `visual_readiness_state`, `health_signals`, or
    `suggested_actions`, it only displays fields
    `factory.project_inspection.summarize_project()` already computed. The
    Project Readiness dashboard *summarizes* the cards below it - Phase 33
    adds it without removing or replacing any existing detail card. The
    Generation Gate card (Phase 34) is purely advisory too: this board
    never generates CAD, it only shows the dry-run decision
    `factory.generation_gate` already computed. The Post-Generation
    Pipeline card (Phase 35) is the same: this board never exports,
    validates, renders, or invokes a subprocess - it only shows what
    `factory.export_pipeline.summarize_export_pipeline()` already computed
    from the plan and (if one exists) `generated/export_receipt.json`. The
    Slicer Review Readiness card (Phase 36) is the same again: this board
    never assesses readiness, records an approval, or creates a review
    package - it only shows what
    `factory.slicer_readiness.summarize_slicer_readiness()` already computed
    read-only, and never opens a slicer or contacts a printer. The Manual
    Review Workspace card (Phase 37) is the same once more: this board
    never inspects a printer profile, scores review confidence, or creates
    a workspace - it only shows what
    `factory.manual_review_workspace.summarize_manual_review_workspace()`
    already computed read-only, and never opens a slicer, generates
    G-code, or prints anything. The Slicer Intelligence card (Phase 38) is
    the same once more: this board never analyzes build-volume fit or
    geometry risk itself - it only shows what
    `factory.slicer_intelligence.summarize_slicer_intelligence()` already
    computed read-only, and its `risk_level` is purely informational,
    never a blocker. Phase 39 extended this same card (not a new one) with
    a compact analysis-history addendum (detected slicer profile, last
    saved-analysis age, change count) sourced from
    `factory.slicer_history.summarize_slicer_history()` - this board never
    saves a history snapshot or runs a live comparison itself; those
    remain separate, explicit, human-run CLI actions
    (`factory slicer-inspect --save-analysis`/`--compare`). The Project
    Timeline card (Phase 40) is the same once more: this board never
    derives an event itself - it only shows what
    `factory.project_timeline.summarize_project_timeline()` already
    computed read-only from existing receipts/status_history. The full
    chronological event list lives in `factory timeline <project>`, not
    on this board.
    """
    project_name = project.get("project_name") or "(unnamed project)"
    project_dir = project.get("project_dir") or ""

    return (
        '<div class="project-card">'
        f'<h3 class="card-title">{_escape_html(project_name)} <code>{_escape_html(project_dir)}</code></h3>'
        '<div class="card-section"><h4>Project Readiness</h4>'
        + _build_project_readiness_section_html(project.get("design_orchestrator_summary"))
        + "</div>"
        '<div class="card-section"><h4>Generation Gate</h4>'
        + _build_generation_gate_section_html(
            project.get("generation_gate_summary"), project.get("generation_execution_summary")
        )
        + "</div>"
        '<div class="card-section"><h4>Post-Generation Pipeline</h4>'
        + _build_export_pipeline_section_html(project.get("export_pipeline_summary"))
        + "</div>"
        '<div class="card-section"><h4>Slicer Review Readiness</h4>'
        + _build_slicer_readiness_section_html(project.get("slicer_readiness_summary"))
        + "</div>"
        '<div class="card-section"><h4>Manual Review Workspace</h4>'
        + _build_manual_review_workspace_section_html(project.get("manual_review_summary"))
        + "</div>"
        '<div class="card-section"><h4>Slicer Intelligence</h4>'
        + _build_slicer_intelligence_section_html(
            project.get("slicer_intelligence_summary"), project.get("slicer_history_summary")
        )
        + "</div>"
        '<div class="card-section"><h4>Project Timeline</h4>'
        + _build_project_timeline_section_html(project.get("timeline_summary"))
        + "</div>"
        '<div class="card-section"><h4>Project Intake</h4>'
        + _build_project_intake_section_html(project.get("intake_summary"))
        + "</div>"
        '<div class="card-section"><h4>Draft Brief</h4>'
        + _build_draft_brief_section_html(project.get("draft_brief_summary"))
        + "</div>"
        '<div class="card-section"><h4>Brief Update</h4>'
        + _build_brief_update_section_html(project.get("brief_update_summary"))
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
  .design-intent p.none, .reference-board p.none, .project-intake p.none, .draft-brief p.none, .brief-update p.none, .project-readiness p.none, .generation-gate p.none, .export-pipeline p.none {{ margin: 0; }}
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

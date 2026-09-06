"""Phase 42: Project Health Dashboard & Unified Factory Status View.

The first unified, single-project health view - it aggregates existing
Factory intelligence (Phases 13, 26-41) into one deterministic dashboard.
**This module never recalculates readiness, never duplicates risk/
validation/artifact logic, never creates new approval rules, and never
overrides an existing blocker.** Every number, status, and message it
shows was already computed by an existing module; this module's own job
is arithmetic (a documented weighted average) and read-only aggregation,
never a second source of truth.

    Feature Modules -> Summary Models -> Project Health Dashboard -> Human Understanding

Reuses rather than duplicates:

- `factory.project_inspection.summarize_project()` - brief/manifest
  status, CAD/mesh files, `health_signals`, `design_orchestrator_summary`,
  `generation_gate_summary`, `generation_execution_summary`,
  `export_pipeline_summary`.
- `factory.slicer_readiness.assess_slicer_readiness()` - the full
  technical readiness assessment (blockers/warnings/advisories,
  `readiness_status`, `readiness_score`, approval/package state).
- `factory.manual_review_workspace.assess_manual_review_workspace()` -
  printer/material resolution, `workspace_status`, `review_confidence`,
  `remaining_risk`.
- `factory.slicer_intelligence.evaluate_slicer_intelligence()` -
  `risk_level`, geometry/manufacturing risks, build-volume fit.
- `factory.project_timeline.get_project_timeline()` /
  `summarize_project_timeline()` (Phase 40) - recent activity, event
  counts.
- `factory.artifact_history.get_artifact_history()` /
  `summarize_artifact_history()` (Phase 41) - latest version, changes
  since the previous version.
- `factory.project_store.PROJECT_STATUSES` - the repo's own canonical
  pipeline-stage ordering, reused directly for `completion_percentage`
  rather than a second stage-counting scheme.

No AI, no LLM, no network. No CAD generation, no OpenSCAD/CadQuery/
Blender/Meshy/FreeCAD execution, no slicer invocation, no G-code
generation, no printer communication. Every action this module surfaces
(`next_action`) is a string a human reads and acts on themselves - this
module never automates, executes, approves, or fixes anything.

**Architectural note - same reasoning as every Phase 36-41 summary
field:** `factory.slicer_readiness`/`factory.manual_review_workspace`/
`factory.slicer_intelligence` each transitively import
`factory.review_gate`, which already imports
`factory.project_inspection.summarize_project()`. This module calls all
three directly (the same "top-level consumer" relationship
`preview_board.py` already has), so it sits **above**
`project_inspection.py` in the dependency graph, never beneath it.
Adding `project_health_summary` *inside* `project_inspection.py` would
recreate the exact circular import Phase 36 discovered and every phase
since has avoided - see the "Aggregation Layer Convention" in
`docs/architecture.md`. `factory.preview_board.gather_board_data()`
merges `project_health_summary` in at the same aggregation point as
every other Phase 36-41 field instead.

See `docs/project-health.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import project_store
from factory.project_inspection import summarize_project
from factory.slicer_readiness import assess_slicer_readiness
from factory.manual_review_workspace import assess_manual_review_workspace
from factory.slicer_intelligence import evaluate_slicer_intelligence
from factory.project_timeline import get_project_timeline, summarize_project_timeline
from factory.artifact_history import get_artifact_history, summarize_artifact_history

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

LIFECYCLE_STAGES = (
    "idea",
    "intake",
    "briefing",
    "design",
    "planning",
    "cad_generation",
    "export",
    "validation",
    "review_preparation",
    "slicer_review",
    "complete",
    "blocked",
)

HEALTH_LEVELS = ("excellent", "good", "fair", "poor", "unknown")
CONFIDENCE_LEVELS = ("high", "medium", "low")

# Deterministic category weights for the overall health score - each
# category's own 0-100 percent is multiplied by its weight and summed.
# Documented here as the single source of truth; see docs/project-health.md
# "Scoring model" for the reasoning behind each weight and each category's
# formula. Sums to 1.0. **This score is purely informational - it never
# overrides a hard blocker.** A project can score 85% and still report
# `overall_status: "Blocked"`; see `evaluate_project_health()`.
HEALTH_CATEGORY_WEIGHTS: dict[str, float] = {
    "project_definition": 0.15,
    "design_intent": 0.10,
    "manufacturing_planning": 0.15,
    "cad_generation": 0.15,
    "artifact_completeness": 0.15,
    "validation": 0.15,
    "review_readiness": 0.15,
}

# Same weighting convention `factory.slicer_readiness._VALIDATION_POINTS`
# already established (1.0/0.7/0.0) - reused here rather than a second
# validation-scoring scale, applied to `export_pipeline_summary`'s own
# already-aggregated `validation_status` label instead of re-deriving it
# from raw per-file statuses.
_VALIDATION_STATUS_POINTS = {
    "passed": 1.0,
    "passed_with_warnings": 0.7,
    "partial": 0.35,
    "failed": 0.0,
    "not_run": 0.0,
}

_HEALTH_LEVEL_THRESHOLDS = (
    (85, "excellent"),
    (65, "good"),
    (40, "fair"),
)


# ---------------------------------------------------------------------------
# Health score - one deterministic weighted percentage per category
# ---------------------------------------------------------------------------


def _score_project_definition(design_orchestrator_summary: dict[str, Any] | None) -> int:
    """Reuses the Design Orchestrator's own already-computed `intake`/
    `brief` category percentages (Phase 33) - never re-parses intake/brief
    text a second time."""
    categories = (design_orchestrator_summary or {}).get("score", {}).get("categories", {})
    intake = categories.get("intake", 0) or 0
    brief = categories.get("brief", 0) or 0
    return round((intake + brief) / 2)


def _score_design_intent(design_orchestrator_summary: dict[str, Any] | None) -> int:
    """Reuses the Design Orchestrator's own `design_intent`/`reference_board`
    category percentages (Phase 33) - never re-derives either."""
    categories = (design_orchestrator_summary or {}).get("score", {}).get("categories", {})
    design_intent = categories.get("design_intent", 0) or 0
    reference_board = categories.get("reference_board", 0) or 0
    return round((design_intent + reference_board) / 2)


def _score_manufacturing_planning(
    design_orchestrator_summary: dict[str, Any] | None, selected_manufacturing_option: str | None
) -> int:
    """Full credit once a manufacturing option has actually been selected
    (`build_plan.json`'s `selected_manufacturing_option`, Phase 4);
    otherwise reuses the Design Orchestrator's own `manufacturing` category
    percentage (material/printer signal confidence, Phase 33) - never a
    second manufacturing-readiness check."""
    if selected_manufacturing_option:
        return 100
    categories = (design_orchestrator_summary or {}).get("score", {}).get("categories", {})
    return round(categories.get("manufacturing", 0) or 0)


def _score_cad_generation(
    generation_execution_summary: dict[str, Any] | None,
    generation_gate_summary: dict[str, Any] | None,
    cad_files: list[str],
) -> int:
    """Reuses Phase 34's own execution receipt (`receipt_available`) and
    gate decision - never re-evaluates whether generation is possible."""
    if (generation_execution_summary or {}).get("receipt_available"):
        return 100
    if cad_files:
        return 75
    if (generation_gate_summary or {}).get("decision") in ("Allowed", "Needs Confirmation"):
        return 40
    return 0


def _score_artifact_completeness(export_pipeline_summary: dict[str, Any] | None) -> int:
    """Reuses Phase 35's own expected-vs-current STL counts - never
    re-derives export state."""
    summary = export_pipeline_summary or {}
    expected = summary.get("expected_stl_count") or 0
    if not expected:
        return 0
    current = summary.get("current_stl_count") or 0
    return round(100 * current / expected)


def _score_validation(export_pipeline_summary: dict[str, Any] | None) -> int:
    """Reuses Phase 35's own aggregated `validation_status` label - never
    re-reads individual validation reports."""
    status = (export_pipeline_summary or {}).get("validation_status")
    return round(100 * _VALIDATION_STATUS_POINTS.get(status, 0.0))


def _score_review_readiness(readiness_assessment: dict[str, Any]) -> int:
    """Reuses Phase 36's own already-computed `readiness_score` directly -
    the single most authoritative "ready for slicer review" percentage
    this repo has; never re-derived."""
    return round(readiness_assessment.get("readiness_score", 0) or 0)


def compute_health_score(
    *,
    design_orchestrator_summary: dict[str, Any] | None,
    generation_gate_summary: dict[str, Any] | None,
    generation_execution_summary: dict[str, Any] | None,
    export_pipeline_summary: dict[str, Any] | None,
    readiness_assessment: dict[str, Any],
    selected_manufacturing_option: str | None,
    cad_files: list[str],
) -> dict[str, Any]:
    """Deterministic, weighted health score (0-100) plus a per-category
    breakdown - see `HEALTH_CATEGORY_WEIGHTS` above and
    `docs/project-health.md` "Scoring model" for exactly how each category
    percent is derived. Every category is read straight off an
    already-computed summary; this function performs no independent
    assessment of its own.
    """
    categories = {
        "project_definition": _score_project_definition(design_orchestrator_summary),
        "design_intent": _score_design_intent(design_orchestrator_summary),
        "manufacturing_planning": _score_manufacturing_planning(design_orchestrator_summary, selected_manufacturing_option),
        "cad_generation": _score_cad_generation(generation_execution_summary, generation_gate_summary, cad_files),
        "artifact_completeness": _score_artifact_completeness(export_pipeline_summary),
        "validation": _score_validation(export_pipeline_summary),
        "review_readiness": _score_review_readiness(readiness_assessment),
    }
    overall = round(sum(categories[name] * weight for name, weight in HEALTH_CATEGORY_WEIGHTS.items()))
    return {"overall": overall, "categories": categories}


def _health_level(overall: int) -> str:
    """Purely informational label derived from the score alone - never
    read by `_is_hard_blocked()`/`_determine_overall_status()`; a
    "poor"/"unknown" health level never implies, nor is implied by,
    `overall_status`."""
    for threshold, level in _HEALTH_LEVEL_THRESHOLDS:
        if overall >= threshold:
            return level
    return "poor"


# ---------------------------------------------------------------------------
# Lifecycle stage - derived from existing evidence, read-only
# ---------------------------------------------------------------------------

_STAGE_BY_BRIEF_STATUS = {
    "idea": "idea",
    "brief_created": "briefing",
    "plan_drafted": "planning",
    "plan_approved": "planning",
    "manufacturing_option_selected": "planning",
    "cad_generated": "cad_generation",
    "mesh_exported": "export",
    "geometry_validated": "validation",
    "dimension_validated": "validation",
    "preview_rendered": "review_preparation",
    "slicer_review_ready": "slicer_review",
    "human_approved": "complete",
    "print_ready": "complete",
}

_STAGE_BY_READINESS_STATUS = {
    "not_ready": "export",
    "stale_artifacts": "export",
    "needs_validation": "validation",
    "needs_preview": "validation",
    "needs_manifest_completion": "review_preparation",
    "needs_information": "review_preparation",
    "needs_human_approval": "review_preparation",
    "ready_for_review_package": "slicer_review",
    "review_package_created": "slicer_review",
}


def _is_hard_blocked(
    design_orchestrator_summary: dict[str, Any] | None,
    health_signals: dict[str, Any],
    readiness_assessment: dict[str, Any],
) -> bool:
    """A genuine obstruction - never just "hasn't reached this stage yet".

    Deliberately narrower than `readiness_status == "blocked"`: that
    status also fires for entirely normal in-progress states (e.g. an STL
    exists but hasn't been rendered yet), which `factory.review_gate`
    correctly treats as blocking *for slicer review specifically* but
    which is not a genuine project-level problem. A real obstruction is
    one of: a manufacturability block (Phase 25 - the part doesn't fit
    any configured printer), a corrupted/stale record
    (`health_signals["summary"] == "blocked"` - unreadable brief/manifest,
    a stale render, missing/stale preview artifacts), or an actual failed
    STL validation. See docs/project-health.md "Blocked vs. not-yet-reached".
    """
    if (design_orchestrator_summary or {}).get("readiness_state") == "Blocked":
        return True
    if health_signals.get("summary") == "blocked":
        return True
    if (readiness_assessment.get("validation_failure_count") or 0) > 0:
        return True
    return False


def _determine_lifecycle_stage(
    *,
    brief_exists: bool,
    brief_json_status: str | None,
    intake_summary: dict[str, Any] | None,
    design_intent_summary: dict[str, Any] | None,
    cad_files: list[str],
    mesh_files: list[str],
    readiness_status: str,
    export_pipeline_summary: dict[str, Any] | None,
    hard_blocked: bool,
) -> str:
    """Deterministic lifecycle-stage decision tree - see
    `docs/project-health.md` "Lifecycle stages" for the full reasoning.
    Receipt-based signals (export/validation/readiness state) take
    precedence over `brief.json`'s own coarser `status` field once CAD
    exists, since `status` is not always advanced for every micro-step;
    `brief.json["status"]` remains authoritative only for the early
    pre-CAD stages, where no receipt-based signal exists yet. Read-only -
    never mutates `brief.json` or any other file.
    """
    if hard_blocked:
        return "blocked"

    if not brief_exists:
        category = (intake_summary or {}).get("category") or {}
        has_signal = category.get("value") not in (None, "unknown")
        return "intake" if has_signal else "idea"

    if brief_json_status == "brief_created" and design_intent_summary is not None:
        stage = "design"
    else:
        stage = _STAGE_BY_BRIEF_STATUS.get(brief_json_status or "", "briefing")

    if not cad_files and not mesh_files:
        return stage

    if cad_files and not mesh_files:
        return "cad_generation"

    # mesh_files exist - the receipt-backed slicer-readiness stack is a
    # more precise, more current signal than brief.json's own status for
    # every remaining stage.
    refined = _STAGE_BY_READINESS_STATUS.get(readiness_status)
    if refined:
        stage = refined
    elif (export_pipeline_summary or {}).get("validation_status") in ("not_run", None) or (
        export_pipeline_summary or {}
    ).get("preview_status") in ("not_run", "missing", None):
        # `readiness_status` resolved to "blocked" here (missing render is
        # itself a blocking condition for `factory.review_gate`, reached
        # before slicer_readiness's own "needs_validation"/"needs_preview"
        # branches) - export_pipeline's own validation/preview status is a
        # more precise signal for this genuinely normal, not-yet-validated
        # in-progress state.
        stage = "validation"
    elif stage not in ("complete",):
        stage = "export"

    if brief_json_status in ("human_approved", "print_ready"):
        stage = "complete"

    return stage


def _completion_percentage(brief_json_status: str | None) -> int:
    """Reuses `factory.project_store.PROJECT_STATUSES`'s own canonical
    pipeline ordering directly - never a second stage-counting scheme.
    Distinct from `health_score`: this measures *progress through the
    pipeline*, not the *quality* of what's been done so far."""
    if brief_json_status is None:
        return 0
    index = project_store.status_index(brief_json_status)
    if index < 0:
        return 0
    return round(100 * index / (len(project_store.PROJECT_STATUSES) - 1))


def _determine_overall_status(
    *,
    lifecycle_stage: str,
    hard_blocked: bool,
    readiness_status: str,
) -> str:
    """A short, human-readable status sentence - computed entirely
    independently of `health_score`, so a high score can never mask a
    real blocker (`overall_status` says "Blocked" regardless of what
    `health_score` happens to be)."""
    if hard_blocked:
        return "Blocked"
    if lifecycle_stage == "complete":
        return "Complete"
    if readiness_status in ("ready_for_review_package", "review_package_created"):
        return "Ready for Slicer Review"
    if readiness_status == "needs_human_approval":
        return "Awaiting Human Approval"
    return f"In Progress - {lifecycle_stage.replace('_', ' ').title()}"


# ---------------------------------------------------------------------------
# Blockers / warnings / risks / strengths - aggregated, never rewritten
# ---------------------------------------------------------------------------


def _item(source: str, message: str) -> dict[str, str]:
    return {"source": source, "message": message}


# `export_pipeline.plan_export()`'s own `blocking_reasons` are contextual
# to "what would happen if you tried to (re-)export right now" - several
# of its decisions are entirely normal not-yet-reached states, not
# genuine obstructions: `"blocked"` just means no CAD source exists yet
# (true for every pre-CAD-generation project), `"manual_export_required"`
# is this repo's expected, always-manual CadQuery policy, `"output_collision"`
# means a current STL already exists and is protected from being silently
# overwritten, and `"needs_confirmation"` means nothing has run yet only
# because `--confirm-export` wasn't passed. Only `"unsupported_source"`/
# `"ambiguous_source"` (malformed or conflicting CAD source actually
# present) and `"export_tool_missing"` (the local OpenSCAD executable
# genuinely isn't available) represent a real obstruction. Surfacing any
# of the others as a project-level blocker would misreport a perfectly
# normal early-stage or already-exported project as stuck.
_EXPORT_PIPELINE_GENUINE_BLOCK_DECISIONS = frozenset({"unsupported_source", "ambiguous_source", "export_tool_missing"})


def _aggregate_blockers(
    export_pipeline_summary: dict[str, Any] | None, readiness_assessment: dict[str, Any], hard_blocked: bool
) -> list[dict[str, str]]:
    """Every message here is read verbatim from the module that produced
    it - never rewritten, never re-derived. `readiness_assessment["blockers"]`
    is a flat string list with no structured "kind" to filter on, and its
    `readiness_status == "blocked"` also fires for entirely normal
    in-progress states (see `_is_hard_blocked()`) - those "haven't gotten
    there yet" facts are already carried in `warnings` (via
    `project_inspection`'s own missing-artifact messages), so
    `readiness_assessment["blockers"]` is only surfaced here when
    `hard_blocked` is actually `True`, to avoid reporting a healthy,
    normally-progressing project as blocked."""
    blockers: list[dict[str, str]] = []
    export_pipeline_summary = export_pipeline_summary or {}
    if export_pipeline_summary.get("decision") in _EXPORT_PIPELINE_GENUINE_BLOCK_DECISIONS:
        for message in export_pipeline_summary.get("blockers") or []:
            blockers.append(_item("export_pipeline", message))
    if hard_blocked:
        for message in readiness_assessment.get("blockers") or []:
            blockers.append(_item("slicer_readiness", message))
    return blockers


def _aggregate_warnings(
    project_summary: dict[str, Any], intelligence: dict[str, Any]
) -> list[dict[str, str]]:
    """`intelligence["warnings"]` (Phase 38/39) already includes every
    warning `factory.manual_review_workspace`/`factory.slicer_readiness`
    produced beneath it (each layer appends to the one below rather than
    replacing it) - reused here as the single, already-deduplicated
    warning list for the whole slicer-review stack, alongside
    `project_inspection`'s own (unrelated) brief/manifest/render-coverage
    warnings."""
    warnings: list[dict[str, str]] = []
    for message in project_summary.get("warnings") or []:
        warnings.append(_item("project_inspection", message))
    for message in intelligence.get("warnings") or []:
        warnings.append(_item("slicer_intelligence", message))
    return warnings


def _aggregate_risks(intelligence: dict[str, Any]) -> list[dict[str, str]]:
    """Reuses Phase 38's own `geometry_risks`/`manufacturing_risks`
    verbatim (each already `{"category", "message"}`) - never a second
    risk-detection pass."""
    risks: list[dict[str, str]] = []
    for risk in intelligence.get("geometry_risks") or []:
        risks.append({"category": risk.get("category", ""), "message": risk.get("message", "")})
    for risk in intelligence.get("manufacturing_risks") or []:
        risks.append({"category": risk.get("category", ""), "message": risk.get("message", "")})
    return risks


def _aggregate_strengths(
    *,
    readiness_assessment: dict[str, Any],
    design_intent_summary: dict[str, Any] | None,
    reference_board_summary: dict[str, Any] | None,
    artifact_summary: dict[str, Any],
    timeline_summary: dict[str, Any],
) -> list[str]:
    """Positive signals - each a direct restatement of an existing boolean/
    enum this repo already computed, never a new judgment call."""
    strengths: list[str] = []
    if readiness_assessment.get("approval_status") == "approved":
        strengths.append("Human approval has been recorded.")
    if readiness_assessment.get("package_available"):
        strengths.append("A slicer review package has been created.")
    if readiness_assessment.get("validation_status") == "passed":
        strengths.append("All STL validations passed with no warnings.")
    if (readiness_assessment.get("readiness_score") or 0) >= 90:
        strengths.append("Technical slicer-readiness score is excellent (90% or higher).")
    if design_intent_summary is not None:
        strengths.append("Design intent has been declared for this project.")
    if (reference_board_summary or {}).get("reference_count"):
        strengths.append("Reference materials are attached to this project.")
    if artifact_summary.get("history_available") and artifact_summary.get("changed_since_previous") == []:
        strengths.append("Artifacts are stable since the last recorded version.")
    if timeline_summary.get("event_count") and not timeline_summary.get("unavailable_event_count"):
        strengths.append("Full timeline history is available for this project.")
    return strengths


# ---------------------------------------------------------------------------
# Next action - a single deterministic recommendation, never automated
# ---------------------------------------------------------------------------


def _determine_next_action(
    *,
    hard_blocked: bool,
    lifecycle_stage: str,
    project_summary: dict[str, Any],
    generation_gate_summary: dict[str, Any] | None,
    export_pipeline_summary: dict[str, Any] | None,
    readiness_assessment: dict[str, Any],
    workspace: dict[str, Any],
) -> str:
    """One deterministic, human-readable next step - preferring each
    layer's own already-computed "what to do next" text over inventing
    new phrasing. This is a recommendation only; nothing here executes,
    generates, validates, approves, or slices anything."""
    if hard_blocked:
        return "Resolve the blocking issue(s) above before proceeding."

    if not project_summary.get("brief_exists"):
        for action in project_summary.get("suggested_actions") or []:
            if action.get("kind") == "create_brief_missing":
                return action["label"]
        return "Create project brief"

    if lifecycle_stage in ("intake", "briefing", "design", "planning"):
        gate = generation_gate_summary or {}
        if gate.get("decision") in ("Allowed", "Needs Confirmation"):
            return "Generate CAD (`factory generate-from-readiness <project> --confirm-generate`)."
        if gate.get("reason"):
            return f"Generate CAD - first: {gate['reason']}."
        return "Generate CAD"

    if lifecycle_stage == "cad_generation":
        return (export_pipeline_summary or {}).get("next_step") or "Export STL"

    if lifecycle_stage in ("export", "validation"):
        return (export_pipeline_summary or {}).get("next_step") or "Run validation"

    if lifecycle_stage == "review_preparation":
        actions = readiness_assessment.get("next_actions") or []
        return actions[0] if actions else "Review the readiness assessment above."

    if lifecycle_stage == "slicer_review":
        actions = workspace.get("recommended_actions") or []
        return actions[0] if actions else "Open slicer review workspace"

    if lifecycle_stage == "complete":
        return "Human final review"

    return "Review project state - see summaries above."


# ---------------------------------------------------------------------------
# Confidence - how much this evaluation can be trusted, not how good it is
# ---------------------------------------------------------------------------


def _determine_confidence(
    *,
    project_summary: dict[str, Any],
    readiness_assessment: dict[str, Any],
    artifact_summary: dict[str, Any],
) -> str:
    """Lower confidence the less receipt-backed evidence exists - never a
    judgment about how *good* the project is, only about how much real
    data this evaluation had to work with."""
    missing = 0
    if project_summary.get("brief_status") is None:
        missing += 1
    if not project_summary.get("manifest_exists"):
        missing += 1
    if readiness_assessment.get("export_receipt_status") == "missing":
        missing += 1
    if readiness_assessment.get("generation_receipt_status") == "missing":
        missing += 1
    if not artifact_summary.get("history_available"):
        missing += 1

    if missing <= 1:
        return "high"
    if missing <= 3:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Recent activity - a thin window over Phase 40's own timeline
# ---------------------------------------------------------------------------

_RECENT_ACTIVITY_WINDOW = 5


def _recent_activity(project_dir: Path) -> list[dict[str, Any]]:
    """The most recent dated timeline events (Phase 40) - never re-parses
    a receipt itself, only reads `factory.project_timeline`'s own
    already-computed, already-ordered event list."""
    events = get_project_timeline(project_dir)
    dated = [e for e in events if e["date"] is not None]
    recent = dated[-_RECENT_ACTIVITY_WINDOW:]
    return [
        {"label": e["label"], "date": e["date"], "severity": e["severity"], "category": e["category"]}
        for e in reversed(recent)
    ]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def evaluate_project_health(project_dir: Path) -> dict[str, Any]:
    """The core, read-only Project Health evaluation. Never writes
    anything, never invokes a subprocess, never contacts a printer/slicer/
    network. Aggregates - never recalculates - every existing Factory
    summary; see the module docstring for the full reuse list.
    """
    project_dir = Path(project_dir)

    project_summary = summarize_project(project_dir)
    readiness_assessment = assess_slicer_readiness(project_dir)
    workspace = assess_manual_review_workspace(project_dir)
    intelligence = evaluate_slicer_intelligence(project_dir)
    timeline_summary = summarize_project_timeline(project_dir)
    artifact_summary = summarize_artifact_history(project_dir)

    design_orchestrator_summary = project_summary.get("design_orchestrator_summary")
    generation_gate_summary = project_summary.get("generation_gate_summary")
    generation_execution_summary = project_summary.get("generation_execution_summary")
    export_pipeline_summary = project_summary.get("export_pipeline_summary")
    health_signals = project_summary.get("health_signals") or {}

    hard_blocked = _is_hard_blocked(design_orchestrator_summary, health_signals, readiness_assessment)

    lifecycle_stage = _determine_lifecycle_stage(
        brief_exists=project_summary.get("brief_exists", False),
        brief_json_status=project_summary.get("brief_status"),
        intake_summary=project_summary.get("intake_summary"),
        design_intent_summary=project_summary.get("design_intent_summary"),
        cad_files=project_summary.get("cad_files") or [],
        mesh_files=project_summary.get("mesh_files") or [],
        readiness_status=readiness_assessment["readiness_status"],
        export_pipeline_summary=export_pipeline_summary,
        hard_blocked=hard_blocked,
    )

    overall_status = _determine_overall_status(
        lifecycle_stage=lifecycle_stage,
        hard_blocked=hard_blocked,
        readiness_status=readiness_assessment["readiness_status"],
    )

    health_score = compute_health_score(
        design_orchestrator_summary=design_orchestrator_summary,
        generation_gate_summary=generation_gate_summary,
        generation_execution_summary=generation_execution_summary,
        export_pipeline_summary=export_pipeline_summary,
        readiness_assessment=readiness_assessment,
        selected_manufacturing_option=project_summary.get("selected_manufacturing_option"),
        cad_files=project_summary.get("cad_files") or [],
    )
    health_level = _health_level(health_score["overall"])

    blockers = _aggregate_blockers(export_pipeline_summary, readiness_assessment, hard_blocked)
    warnings = _aggregate_warnings(project_summary, intelligence)
    risks = _aggregate_risks(intelligence)
    strengths = _aggregate_strengths(
        readiness_assessment=readiness_assessment,
        design_intent_summary=project_summary.get("design_intent_summary"),
        reference_board_summary=project_summary.get("reference_board_summary"),
        artifact_summary=artifact_summary,
        timeline_summary=timeline_summary,
    )

    next_action = _determine_next_action(
        hard_blocked=hard_blocked,
        lifecycle_stage=lifecycle_stage,
        project_summary=project_summary,
        generation_gate_summary=generation_gate_summary,
        export_pipeline_summary=export_pipeline_summary,
        readiness_assessment=readiness_assessment,
        workspace=workspace,
    )

    confidence = _determine_confidence(
        project_summary=project_summary, readiness_assessment=readiness_assessment, artifact_summary=artifact_summary
    )

    return {
        "project": project_summary.get("project_name"),
        "project_dir": str(project_dir),
        "overall_status": overall_status,
        "health_score": health_score["overall"],
        "health_score_categories": health_score["categories"],
        "health_level": health_level,
        "lifecycle_stage": lifecycle_stage,
        "completion_percentage": _completion_percentage(project_summary.get("brief_status")),
        "current_phase": lifecycle_stage,
        "next_action": next_action,
        "blockers": blockers,
        "warnings": warnings,
        "risks": risks,
        "strengths": strengths,
        "recent_activity": _recent_activity(project_dir),
        "timeline_summary": timeline_summary,
        "artifact_summary": artifact_summary,
        "readiness_summary": {
            "status": readiness_assessment["readiness_status"],
            "score": readiness_assessment["readiness_score"],
            "approval_status": readiness_assessment["approval_status"],
            "package_status": readiness_assessment["package_status"],
        },
        "review_summary": {
            "workspace_status": workspace["workspace_status"],
            "review_confidence": workspace["review_confidence"],
            "remaining_risk": workspace["remaining_risk"],
            "package_available": readiness_assessment["package_available"],
        },
        "slicer_summary": {
            "risk_level": intelligence["risk_level"],
            "confidence": intelligence["confidence"],
            "build_volume_fit": intelligence["build_volume_analysis"]["fit_status"],
            "review_item_count": len(intelligence["review_priority"]),
        },
        "manufacturing_summary": {
            "selected_manufacturing_option": project_summary.get("selected_manufacturing_option"),
            "printer_display_name": workspace["printer_summary"]["display_name"],
            "material_multi": workspace["material_summary"]["multi_material"],
            "material_unresolved": bool(
                workspace["material_summary"]["unresolved_material_parts"]
                or workspace["material_summary"]["unresolved_color_parts"]
            ),
        },
        "engine_summary": {
            "recommended_engine": (design_orchestrator_summary or {}).get("recommended_engine"),
            "readiness_state": (design_orchestrator_summary or {}).get("readiness_state"),
            "engine_rationale": (design_orchestrator_summary or {}).get("engine_rationale"),
        },
        "confidence": confidence,
        "no_automatic_print": True,
    }


def evaluate_project_health_for_path(path: Path) -> dict[str, Any]:
    """Convenience entry point `factory health <path>` uses."""
    return evaluate_project_health(path)


# ---------------------------------------------------------------------------
# Compact summary for Project Inspection / Preview Board
# ---------------------------------------------------------------------------


def summarize_project_health(project_dir: Path) -> dict[str, Any]:
    """Compact, read-only summary for the Preview Board's "Project
    Health" card (and any other caller that just wants the headline
    fields). Never writes, never invokes a subprocess.

    **Architectural note - same reasoning as every Phase 36-41 summary
    field:** this module calls `factory.slicer_readiness`/
    `factory.manual_review_workspace`/`factory.slicer_intelligence`
    directly, each of which transitively imports
    `factory.review_gate.evaluate_review_gate()`, which already imports
    `factory.project_inspection.summarize_project()`. Adding a
    `project_health_summary` field computed via this module *inside*
    `project_inspection.py` would recreate the same circular import every
    prior phase in this range has hit and avoided - see the "Aggregation
    Layer Convention" in `docs/architecture.md`.
    `factory.preview_board.gather_board_data()` calls this function
    directly per project instead, the same architectural pattern as
    `slicer_readiness_summary`/`manual_review_summary`/
    `slicer_intelligence_summary`/`timeline_summary`/
    `artifact_history_summary`.
    """
    health = evaluate_project_health(project_dir)
    return {
        "status": health["overall_status"],
        "score": health["health_score"],
        "health_level": health["health_level"],
        "lifecycle_stage": health["lifecycle_stage"],
        "blocker_count": len(health["blockers"]),
        "warning_count": len(health["warnings"]),
        "next_action": health["next_action"],
    }

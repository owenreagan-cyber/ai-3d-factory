"""Phase 52: Manufacturing Readiness Intelligence & Final Production Gate.

The final aggregation layer over every prior readiness signal this repo
has ever computed. Answers exactly one question:

    "Is this project ready to enter manufacturing preparation?"

It never answers:

    "Should the printer automatically start?"

    Manufacturing readiness  !=  printing approval.
    Automatic printing remains impossible.

**This is a pure aggregation layer. It computes nothing that a lower
module hasn't already computed, validates no geometry, contacts no
printer/slicer/network, and never modifies an artifact.** No code path
in this module calls Meshy, launches Blender, executes CAD, invokes a
slicer, or contacts a printer.

## Why this module exists, and why it is not a second `design_review`/`project_health`

`factory.design_review` (Phase 51) is already a complete, closed-form
manufacturing-readiness ladder - but scoped only to the hybrid
(Meshy -> Blender -> CAD) pipeline. `factory.project_health` (Phase 42)
is the equivalent complete ladder for the traditional
(brief -> orchestrator -> CAD -> export) pipeline. **By explicit design,
neither reads the other** (see `design_review`'s own module docstring,
"Why this is not `factory.project_health`"). Nearly everything this
module's report needs - readiness state, score, blockers, warnings,
printer/material status, human confirmations - already exists verbatim
inside one of those two modules' own return dicts.

The one genuinely new thing Phase 52 adds is the **pipeline-agnostic
union**: one closed-form ladder that answers the readiness question
regardless of which pipeline a project actually took, by reading
whichever of the two aggregators actually has evidence for this project
(`_is_hybrid_pipeline()` below - the same `artifact_chain`-presence
check `factory.design_review.summarize_design_review()` itself already
uses to decide "is there a hybrid chain here"), plus folding in
`factory.artifact_history`/`factory.project_timeline` as lineage/
completeness context neither aggregator surfaces on its own, plus one
new blocker rule (an impossible build-volume fit) that today isn't
escalated to blocker severity by either aggregator.

Reuses rather than duplicates:

- `factory.design_review.evaluate_design_review()` - the complete hybrid-
  pipeline ladder (readiness state, weighted score, blockers, warnings,
  required human confirmations, printer/material summaries). Safe to call
  on any project, hybrid or not - it reports `"not_reviewed"` honestly
  when no hybrid chain exists.
- `factory.project_health.evaluate_project_health()` - the complete
  traditional-pipeline ladder (overall status, weighted health score,
  blockers, warnings, lifecycle stage, readiness/review/manufacturing
  summaries). Also safe to call on any project.
- `factory.slicer_intelligence.evaluate_slicer_intelligence()` - read
  directly, once, only for `build_volume_analysis.fit_status` (a field
  neither aggregator above surfaces) - never a second geometry/print-risk
  analysis.
- `factory.artifact_history.summarize_artifact_history()` /
  `factory.project_timeline.summarize_project_timeline()` - read-only
  lineage/completeness context. No new timeline category or artifact-
  history classification rule is added.

Does **not** duplicate: mesh validation, printer-capability lookups,
design-intent parsing, artifact-chain parsing, or scale analysis - every
one of those stays exactly where Phases 36-51 already put it.

## Readiness state ladder

`READINESS_STATES` deliberately excludes `approved_for_print` and
`automatic_manufacture_ready` - matching this repo's standing
`config/agent_policy.json` ceiling (`status_gates.max_automatic_status:
"slicer_review_ready"`), the same ceiling every other readiness ladder in
this repo already respects. `manufacturing_review_ready` is reused with
the exact same meaning `factory.design_review` already gives it
("printer and material are both confirmed") - not a second, conflicting
definition of the same name.

A high `readiness_score` never overrides a blocker: `blocked` is decided
first, before the score is even consulted, in `_determine_readiness_state()`.

See `docs/manufacturing-readiness.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory.artifact_history import summarize_artifact_history
from factory.design_review import evaluate_design_review
from factory.project_health import LIFECYCLE_STAGES, evaluate_project_health
from factory.project_timeline import summarize_project_timeline
from factory.slicer_intelligence import evaluate_slicer_intelligence

MANUFACTURING_READINESS_VERSION = 1

# Closed, ordered vocabulary - deliberately excludes `approved_for_print`
# and `automatic_manufacture_ready`. `manufacturing_review_ready` reuses
# `factory.design_review.READINESS_STATES`'s own name with the identical
# meaning (printer + material both confirmed) - not a second definition.
READINESS_STATES = (
    "not_ready",
    "needs_information",
    "design_review_complete",
    "manufacturing_review_ready",
    "human_approval_required",
    "slicer_preparation_ready",
    "blocked",
)

# Deliberate ordering note (see docs/manufacturing-readiness.md
# "Readiness states"): the spec this phase was built from lists
# `slicer_preparation_ready` before `human_approval_required`, but
# `factory.slicer_readiness.READINESS_STATES`'s own state machine reaches
# `needs_human_approval` strictly *before* `ready_for_review_package`/
# `review_package_created` - approval is a precondition of the package
# being "ready", never the reverse. `human_approval_required` therefore
# fires first (the single remaining requirement is a human's approval
# action); `slicer_preparation_ready` fires only once slicer_readiness
# itself confirms the package is current/created. Both rungs are reached
# in ladder order below regardless of the tuple's declaration order.

# Every field below is a status label with evidence behind it - never a
# guess. `"needs_information"` is the only allowed value for anything
# this repo hasn't actually confirmed (never a guessed material, nozzle,
# layer height, printer, or process setting).
_CONFIRMED = "confirmed"
_NEEDS_INFO = "needs_information"

_SAFETY_BLOCK: dict[str, bool] = {
    "meshy_contacted": False,
    "blender_launched": False,
    "cad_executed": False,
    "slicer_executed": False,
    "printer_contacted": False,
    "network_used": False,
    "geometry_modified": False,
    "gcode_generated": False,
    "automatic_print_allowed": False,
    "automatic_approval_granted": False,
}


def build_safety_block() -> dict[str, bool]:
    """Static, hardcoded invariants - never per-call telemetry. Mirrors
    `factory.design_review.build_safety_block()`'s identical convention."""
    return dict(_SAFETY_BLOCK)


# ---------------------------------------------------------------------------
# Pipeline lens - which of the two complete aggregators actually has
# evidence for this project. Reuses the exact same check
# `factory.design_review.summarize_design_review()` already makes; never
# re-derives artifact-chain presence independently.
# ---------------------------------------------------------------------------


def _is_hybrid_pipeline(design_review: dict[str, Any]) -> bool:
    return any(stage["present"] for stage in design_review["artifact_chain"])


def _artifact_status(*, is_hybrid: bool, design_review: dict[str, Any], health: dict[str, Any]) -> str:
    """`"absent"` / `"partial"` / `"present"` / `"unknown"` - never a
    binary yes/no. For the hybrid pipeline, `"partial"` means at least one
    but not all three of Meshy/Blender-adaptation/CAD-augmentation stages
    are present. For the traditional pipeline, reuses
    `factory.project_health.LIFECYCLE_STAGES`'s own ordinal position
    (has the project reached `cad_generation` or later) rather than a
    second file-existence check."""
    if is_hybrid:
        present_count = sum(1 for s in design_review["artifact_chain"] if s["present"])
        return "present" if present_count == len(design_review["artifact_chain"]) else "partial"
    stage = health["lifecycle_stage"]
    if stage not in LIFECYCLE_STAGES:
        return "unknown"
    if stage == "blocked":
        return "unknown"
    return "present" if LIFECYCLE_STAGES.index(stage) >= LIFECYCLE_STAGES.index("cad_generation") else "absent"


def _geometry_status(*, is_hybrid: bool, artifact_status: str, design_review: dict[str, Any], health: dict[str, Any]) -> str:
    """`"not_available"` / `"validated"` / `"warnings"` / `"failed"` -
    reuses each pipeline's own already-computed geometry/validation score
    verbatim (`design_review.score_categories["geometry"]` for the hybrid
    lens, `health.health_score_categories["validation"]` for the
    traditional lens). Never re-validates a mesh."""
    if artifact_status == "absent":
        return "not_available"
    score = design_review["score_categories"]["geometry"]["score"] if is_hybrid else health["health_score_categories"]["validation"]
    if score >= 90:
        return "validated"
    if score > 0:
        return "warnings"
    return "failed"


# ---------------------------------------------------------------------------
# Human confirmation checklist - one flat, explicit checklist, reusing
# factory.design_review's own already-computed `required_human_confirmations`
# (genuinely pipeline-agnostic: printer/material come from
# factory.manual_review_workspace, which reads build_plan.json/
# part_manifest.json regardless of which pipeline produced the artifact)
# plus two new items this phase adds: slicer_review_complete and
# final_artifact_approved, both sourced from factory.project_health's own
# passthrough of factory.slicer_readiness.assess_slicer_readiness() -
# never re-derived.
# ---------------------------------------------------------------------------

_CONFIRMATION_ITEM_RENAME = {
    "design_intent_confirmed": "design_intent_confirmed",
    "dimensions_confirmed": "dimensions_confirmed",
    "manufacturing_purpose_confirmed": "manufacturing_purpose_confirmed",
    "material_confirmed": "material_selected",
    "printer_confirmed": "printer_selected",
}


def _build_human_confirmation_checklist(
    *, design_review: dict[str, Any], health: dict[str, Any]
) -> list[dict[str, Any]]:
    checklist = [
        {"item": _CONFIRMATION_ITEM_RENAME[c["item"]], "confirmed": c["confirmed"], "detail": c["detail"]}
        for c in design_review["required_human_confirmations"]
    ]
    slicer_status = health["readiness_summary"]["status"]
    slicer_review_complete = slicer_status in _SLICER_PACKAGE_READY_STATES
    checklist.append(
        {
            "item": "slicer_review_complete",
            "confirmed": slicer_review_complete,
            "detail": "Has factory.slicer_readiness reached ready_for_review_package/review_package_created (a current review package exists)?",
        }
    )
    approval_status = health["readiness_summary"]["approval_status"]
    checklist.append(
        {
            "item": "final_artifact_approved",
            "confirmed": approval_status == "approved",
            "detail": "Has a human recorded approval via factory.slicer_readiness (approval_status == 'approved')?",
        }
    )
    return checklist


# ---------------------------------------------------------------------------
# Blocker/warning union - de-duplicated, tagged by source pipeline, never
# silently dropping one pipeline's blocker because the other pipeline's
# list happened to be empty.
# ---------------------------------------------------------------------------


def _tag(items: list[dict[str, str]], pipeline: str) -> list[dict[str, str]]:
    return [{"pipeline": pipeline, "source": i["source"], "message": i["message"]} for i in items]


def _dedupe(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, str]] = []
    for item in items:
        key = (item["source"], item["message"])
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _aggregate_blockers_and_warnings(
    *, design_review: dict[str, Any], health: dict[str, Any], intelligence: dict[str, Any]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    blockers = _tag(design_review["blockers"], "hybrid") + _tag(health["blockers"], "traditional")
    warnings = _tag(design_review["warnings"], "hybrid") + _tag(health["warnings"], "traditional")

    # The one new blocker rule this phase adds: an impossible build-volume
    # fit is a genuine manufacturing obstruction (matches the spec's own
    # BLOCKER example), but today neither design_review nor project_health
    # escalates slicer_intelligence's own already-computed fit_status to
    # blocker severity - this reads that one field directly, it never
    # re-runs the build-volume analysis itself.
    fit_status = (intelligence.get("build_volume_analysis") or {}).get("fit_status")
    if fit_status == "does_not_fit":
        blockers.append(
            {
                "pipeline": "shared",
                "source": "slicer_intelligence",
                "message": "Build volume analysis reports this part does not fit the configured target printer.",
            }
        )

    return _dedupe(blockers), _dedupe(warnings)


# ---------------------------------------------------------------------------
# Readiness state - deterministic decision tree, first match wins. A high
# readiness_score never overrides a blocker: `blocked` is decided before
# the score is even read.
# ---------------------------------------------------------------------------

_SLICER_NEEDS_APPROVAL_STATES = ("needs_human_approval",)
_SLICER_PACKAGE_READY_STATES = ("ready_for_review_package", "review_package_created")


def _determine_readiness_state(
    *,
    blockers: list[dict[str, str]],
    artifact_status: str,
    checklist: list[dict[str, Any]],
    slicer_status: str,
) -> str:
    if blockers:
        return "blocked"
    if artifact_status == "absent":
        return "not_ready"

    by_item = {c["item"]: c["confirmed"] for c in checklist}
    core_design_confirmed = (
        by_item["design_intent_confirmed"] and by_item["dimensions_confirmed"] and by_item["manufacturing_purpose_confirmed"]
    )
    if not core_design_confirmed:
        return "needs_information"

    printer_material_confirmed = by_item["material_selected"] and by_item["printer_selected"]
    if not printer_material_confirmed:
        return "design_review_complete"

    if slicer_status in _SLICER_PACKAGE_READY_STATES:
        return "slicer_preparation_ready"
    if slicer_status in _SLICER_NEEDS_APPROVAL_STATES:
        return "human_approval_required"
    return "manufacturing_review_ready"


# ---------------------------------------------------------------------------
# Recommended next steps - concrete, grounded in already-computed facts.
# Reuses factory.design_review's own recommended_actions (hybrid lens) or
# factory.project_health's own next_action (traditional lens) rather than
# inventing new phrasing.
# ---------------------------------------------------------------------------


def _recommended_next_steps(
    *, is_hybrid: bool, design_review: dict[str, Any], health: dict[str, Any], checklist: list[dict[str, Any]]
) -> list[str]:
    steps: list[str] = list(design_review["recommended_actions"]) if is_hybrid else []
    if not is_hybrid and health.get("next_action"):
        steps.append(health["next_action"])

    by_item = {c["item"]: c for c in checklist}
    if not by_item["slicer_review_complete"]["confirmed"]:
        steps.append("Create/refresh the slicer review package (`factory slicer-readiness <project> --create-package --confirm-package`).")
    if not by_item["final_artifact_approved"]["confirmed"]:
        steps.append("Record human approval before proceeding (`factory slicer-readiness <project> --approve`).")

    seen: set[str] = set()
    deduped: list[str] = []
    for step in steps:
        if step not in seen:
            seen.add(step)
            deduped.append(step)
    return deduped


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def evaluate_manufacturing_readiness(project_dir: Path) -> dict[str, Any]:
    """The core, read-only Manufacturing Readiness evaluation. Never
    writes anything, never invokes Meshy/Blender/CAD/a slicer/a printer/a
    network, never modifies geometry. `automatic_print_allowed` is always
    `False`. Aggregates - never recalculates - every existing Factory
    readiness signal; see the module docstring for the full reuse list.
    """
    project_dir = Path(project_dir)

    design_review = evaluate_design_review(project_dir)
    health = evaluate_project_health(project_dir)
    intelligence = evaluate_slicer_intelligence(project_dir)
    artifact_summary = summarize_artifact_history(project_dir)
    timeline_summary = summarize_project_timeline(project_dir)

    is_hybrid = _is_hybrid_pipeline(design_review)
    pipeline = "hybrid" if is_hybrid else "traditional"

    artifact_status = _artifact_status(is_hybrid=is_hybrid, design_review=design_review, health=health)
    geometry_status = _geometry_status(is_hybrid=is_hybrid, artifact_status=artifact_status, design_review=design_review, health=health)

    checklist = _build_human_confirmation_checklist(design_review=design_review, health=health)
    by_item = {c["item"]: c["confirmed"] for c in checklist}

    slicer_status = health["readiness_summary"]["status"]
    human_review_status = health["readiness_summary"]["approval_status"]

    blockers, warnings = _aggregate_blockers_and_warnings(design_review=design_review, health=health, intelligence=intelligence)

    readiness_state = _determine_readiness_state(
        blockers=blockers, artifact_status=artifact_status, checklist=checklist, slicer_status=slicer_status
    )
    assert readiness_state in READINESS_STATES

    confidence = design_review["confidence"] if is_hybrid else health["confidence"]
    if is_hybrid:
        readiness_score = design_review["design_quality_score"]
        readiness_score_source = "design_review"
        readiness_score_weights = design_review["score_weights"]
    else:
        readiness_score = health["health_score"]
        readiness_score_source = "project_health"
        readiness_score_weights = None  # project_health does not expose its category weights as a public constant here

    completed_requirements = [c["item"] for c in checklist if c["confirmed"]]
    missing_requirements = [c["item"] for c in checklist if not c["confirmed"]]

    recommended_next_steps = _recommended_next_steps(
        is_hybrid=is_hybrid, design_review=design_review, health=health, checklist=checklist
    )
    if blockers:
        recommended_next_steps = [f"Resolve blocker ({b['source']}): {b['message']}" for b in blockers] + recommended_next_steps

    return {
        "manufacturing_readiness_version": MANUFACTURING_READINESS_VERSION,
        "project": str(project_dir),
        "pipeline": pipeline,
        "readiness_state": readiness_state,
        "readiness_score": readiness_score,
        "readiness_score_source": readiness_score_source,
        "readiness_score_weights": readiness_score_weights,
        "confidence": confidence,
        "artifact_status": artifact_status,
        "design_status": _CONFIRMED if by_item["design_intent_confirmed"] else _NEEDS_INFO,
        "geometry_status": geometry_status,
        "scale_status": _CONFIRMED if by_item["dimensions_confirmed"] else _NEEDS_INFO,
        "manufacturing_status": _CONFIRMED if by_item["manufacturing_purpose_confirmed"] else _NEEDS_INFO,
        "printer_status": _CONFIRMED if by_item["printer_selected"] else _NEEDS_INFO,
        "material_status": _CONFIRMED if by_item["material_selected"] else _NEEDS_INFO,
        "slicer_status": slicer_status,
        "human_review_status": human_review_status,
        "blockers": blockers,
        "warnings": warnings,
        "human_confirmation_checklist": checklist,
        "completed_requirements": completed_requirements,
        "missing_requirements": missing_requirements,
        "recommended_next_steps": recommended_next_steps,
        "printer_summary": design_review["printer_summary"],
        "material_summary": design_review["material_summary"],
        "lineage_summary": {
            "artifact_version_count": artifact_summary["version_count"],
            "artifact_history_available": artifact_summary["history_available"],
            "timeline_event_count": timeline_summary["event_count"],
            "timeline_unavailable_event_count": timeline_summary["unavailable_event_count"],
        },
        "no_geometry_modified": True,
        "automatic_print_allowed": False,
    }


def evaluate_manufacturing_readiness_for_path(path: Path) -> dict[str, Any]:
    """Convenience entry point `factory manufacturing-readiness <project>` uses."""
    return evaluate_manufacturing_readiness(path)


# ---------------------------------------------------------------------------
# Preview Board summary - wired in at the aggregation point
# (factory.preview_board.gather_board_data()), never inside
# factory.project_health/factory.design_review/project_inspection. See the
# standing "Aggregation Layer Convention" in docs/architecture.md.
# ---------------------------------------------------------------------------


def summarize_manufacturing_readiness(project_dir: Path) -> dict[str, Any]:
    """Compact, read-only summary for the Preview Board. Always computed
    fresh (never reads a saved snapshot, so it can never go stale) - never
    writes, never invokes Meshy/Blender/CAD/a subprocess of any kind."""
    report = evaluate_manufacturing_readiness(project_dir)
    return {
        "available": True,
        "readiness_state": report["readiness_state"],
        "readiness_score": report["readiness_score"],
        "top_blockers": [b["message"] for b in report["blockers"]][:2],
        "top_warnings": [w["message"] for w in report["warnings"]][:2],
    }

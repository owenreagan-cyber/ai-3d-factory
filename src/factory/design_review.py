"""Phase 51: Hybrid Design Quality Review & Manufacturing Readiness Gate.

The final intelligence layer over the Meshy -> Blender -> CAD pipeline
(Phases 47-50): answers **"is this hybrid artifact chain actually ready
for human manufacturing review?"** - never "is it ready to print."

    Generated artifact   != Good design
    Validated mesh       != Manufacturing ready
    Manufacturing ready  != Human approved
    Human approved       != Print approved
    Automatic printing remains impossible.

**This is review only. It never executes, generates, repairs, or
modifies geometry, and it never approves anything.** No code path in
this module calls Meshy, launches Blender, executes CAD (OpenSCAD/
CadQuery), invokes a slicer, or contacts a printer/network.

## Why this is not `factory.project_health`, and does not touch it

`factory.project_health` (Phase 42) already aggregates a deterministic,
weighted health score for a project - but its every input
(`design_orchestrator_summary`, `generation_gate_summary`,
`export_pipeline_summary`, `slicer_readiness`'s own manifest-driven
assessment) is scoped to the **traditional, CAD-first pipeline**
(`brief.json` -> Design Orchestrator -> CAD generation -> `export_receipt.json`
-> `part_manifest.json`). It has no field, anywhere, that reads a Meshy
receipt, a Blender adaptation receipt, or a CAD augmentation receipt -
for a hybrid AI-generated project, most of `project_health`'s categories
score `0`, not because the project is unhealthy, but because it took a
different path `project_health` was never taught to look for.

This phase does not extend or duplicate that scoring - `factory.project_health`
is untouched, exactly like every prior Meshy/Blender/CAD-adjacent phase's
own stated invariant. Instead, `factory.design_review` is a **parallel,
narrower lens specific to the hybrid pipeline**, reusing the same
underlying reuse targets `project_health` already established the
pattern for (Phase 36/38/48/49/50's own summary functions), just applied
to a different input chain.

## Why this is not `docs/design-quality-standard.md`'s "Etsy-worthy" bar

That document is explicit: **"A mesh that passes `factory validate`
(watertight, manifold, reasonable dimensions) has cleared a geometry
sanity check - it has not cleared this standard."** Nothing in this
module can judge silhouette, proportion, style, or polish - those
require an actual human eye (or a vision-capable AI this repo does not
invoke). `design_quality_score` measures **pipeline readiness and
evidentiary completeness** - is there a declared intent, is the lineage
consistent, is the geometry valid, is the scale confirmed, is the
manufacturing purpose classified, does the expected mechanical feature
exist, is print-readiness data available - never aesthetic merit. See
"Limitations" in `docs/design-review.md` for this distinction stated in
full; every score this module returns carries its own traceable inputs
precisely so a human never mistakes a high number for "this looks good."

Reuses rather than duplicates:

- `factory.blender_adaptation.read_blender_adaptation_receipt()` /
  `factory.cad_augmentation.read_cad_augmentation_receipt()` - the two
  existing receipt readers for the two real execution gates this repo
  has. This module never re-reads either receipt file itself.
- `factory.hybrid_workflow.assess_scale()` /
  `assess_manufacturing_intent()` - the one existing scale-plausibility
  check and manufacturing-intent classifier (Phase 48), applied here to
  whatever the *current, most-downstream* artifact actually is (which
  `factory.hybrid_workflow.build_adaptation_plan()` itself cannot know,
  since it has no Blender/CAD-augmentation receipt awareness - see
  `docs/hybrid-workflow.md`).
- `factory.design_intent_check.summarize_design_intent()` - the one
  existing reader of a project's declared `design_intent` block.
- `factory.validators.mesh_validate.validate_mesh()` - the one Factory
  mesh validator. No second geometry check exists here.
- `factory.slicer_intelligence.evaluate_slicer_intelligence()` /
  `factory.slicer_readiness.assess_slicer_readiness()` - the existing
  print-readiness/risk assessment. Reused verbatim; for a project with no
  `part_manifest.json`/`export_receipt.json` (true of most hybrid
  projects), these honestly report "no parts"/"unresolved" - a real,
  useful signal ("printer not configured"), not a bug to route around.
- `factory.project_timeline.get_project_timeline()` - read-only, to
  cross-check that each receipt's own claimed lineage is corroborated by
  the timeline. No new timeline category is added by this phase; no new
  lineage system is built.

See `docs/design-review.md`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from factory import project_store
from factory.blender_adaptation import read_blender_adaptation_receipt
from factory.cad_augmentation import read_cad_augmentation_receipt
from factory.design_intent_check import summarize_design_intent
from factory.hybrid_workflow import assess_manufacturing_intent, assess_scale
from factory.manual_review_workspace import assess_manual_review_workspace
from factory.slicer_intelligence import evaluate_slicer_intelligence
from factory.slicer_readiness import assess_slicer_readiness
from factory.validators.mesh_validate import validate_mesh

DESIGN_REVIEW_VERSION = 1

# Closed, ordered vocabulary - deliberately excludes "approved_for_print"
# and anything stronger than "approved_for_slicer_review", matching this
# repo's standing `config/agent_policy.json` ceiling
# (`status_gates.max_automatic_status: "slicer_review_ready"`). No code
# path in this module ever returns a state beyond that ceiling.
READINESS_STATES = (
    "not_reviewed",
    "needs_information",
    "design_review_ready",
    "manufacturing_review_ready",
    "approved_for_slicer_review",
    "blocked",
)

# Explicit, documented weights (sum to 1.0) - see docs/design-review.md
# "Scoring model" for the reasoning behind each. Never a single magic
# number: every category score below carries its own `reasoning` and
# `inputs` fields.
QUALITY_CATEGORY_WEIGHTS: dict[str, float] = {
    "design_intent": 0.20,
    "geometry": 0.20,
    "scale": 0.15,
    "manufacturing": 0.20,
    "lineage": 0.10,
    "review_readiness": 0.15,
}
assert abs(sum(QUALITY_CATEGORY_WEIGHTS.values()) - 1.0) < 1e-9

CONFIDENCE_LEVELS = ("high", "medium", "low")

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
    `factory.blender_adaptation.build_safety_block()`/
    `factory.cad_augmentation.build_safety_block()`'s identical
    convention."""
    return dict(_SAFETY_BLOCK)


def _file_fingerprint(path: Path) -> str:
    """`sha256:<hex digest>` - the exact convention already established
    throughout this repo for every other artifact fingerprint. Never
    re-derived differently here."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _read_real_meshy_receipt(project_dir: Path) -> dict[str, Any] | None:
    """Read-only: a real (non-mock) Meshy receipt, if one exists - mirrors
    `factory.project_timeline._events_from_meshy_receipt()`'s own
    "never a mocked receipt" rule exactly (a Phase 47A mocked receipt is
    architecture-proving only, never a project-timeline- or review-
    worthy fact)."""
    receipt_path = Path(project_dir) / "generated" / "meshy_receipt.json"
    if not receipt_path.is_file():
        return None
    try:
        receipt = project_store.load_json(receipt_path)
    except (OSError, ValueError):
        return None
    if not receipt.get("live_api_used") or receipt.get("mock_execution"):
        return None
    return receipt


# ---------------------------------------------------------------------------
# Artifact chain resolution - read-only, reuses the two existing receipt
# readers. Never re-implements Meshy/Blender/CAD-augmentation's own
# receipt formats.
# ---------------------------------------------------------------------------


def _resolve_artifact_chain(project_dir: Path) -> dict[str, Any]:
    """The full Meshy -> Blender -> CAD lineage picture for one project,
    read entirely from existing receipts. Never invents a fact no receipt
    already recorded; a stage that never ran is `present: False`, never
    silently assumed.
    """
    project_dir = Path(project_dir)
    meshy_receipt = _read_real_meshy_receipt(project_dir)
    blender_receipt = read_blender_adaptation_receipt(project_dir)
    cad_receipt = read_cad_augmentation_receipt(project_dir)

    stages: list[dict[str, Any]] = []
    broken_links: list[str] = []

    meshy_artifact = None
    if meshy_receipt:
        artifact_paths = meshy_receipt.get("output_artifact_paths") or []
        meshy_artifact = artifact_paths[0] if artifact_paths else None
    stages.append(
        {
            "stage": "meshy",
            "present": meshy_receipt is not None,
            "artifact": meshy_artifact,
            "detail": f"task_id={meshy_receipt.get('meshy_task_id')}" if meshy_receipt else None,
        }
    )

    stages.append(
        {
            "stage": "blender_adaptation",
            "present": blender_receipt is not None,
            "artifact": (blender_receipt or {}).get("output_artifact"),
            "detail": f"workflow={blender_receipt.get('workflow')}" if blender_receipt else None,
        }
    )
    if blender_receipt:
        parent_rel = blender_receipt.get("input_artifact")
        parent_path = project_dir / parent_rel if parent_rel else None
        recorded_hash = blender_receipt.get("input_hash")
        if parent_path and parent_path.is_file() and recorded_hash:
            if _file_fingerprint(parent_path) != recorded_hash:
                broken_links.append(
                    f"blender_adaptation's recorded input ({parent_rel}) no longer matches its recorded "
                    "fingerprint - the file changed after adaptation ran."
                )
        elif parent_path and not parent_path.is_file():
            broken_links.append(f"blender_adaptation's recorded input ({parent_rel}) no longer exists on disk.")

    stages.append(
        {
            "stage": "cad_augmentation",
            "present": cad_receipt is not None,
            "artifact": (cad_receipt or {}).get("output_artifact"),
            "detail": f"cad_engine={cad_receipt.get('cad_engine')}" if cad_receipt else None,
        }
    )
    if cad_receipt:
        parent_rel = cad_receipt.get("input_artifact")
        parent_path = project_dir / parent_rel if parent_rel else None
        recorded_hash = cad_receipt.get("input_hash")
        if parent_path and parent_path.is_file() and recorded_hash:
            if _file_fingerprint(parent_path) != recorded_hash:
                broken_links.append(
                    f"cad_augmentation's recorded input ({parent_rel}) no longer matches its recorded "
                    "fingerprint - the file changed after augmentation ran."
                )
        elif parent_path and not parent_path.is_file():
            broken_links.append(f"cad_augmentation's recorded input ({parent_rel}) no longer exists on disk.")

    # The organic (body) component is whichever is the most-downstream
    # organic-origin artifact; the mechanical component only exists if
    # CAD augmentation actually ran. Never boolean-merged - these stay
    # two independent paths, matching Phase 50's own "never a fused
    # mesh" design.
    if blender_receipt:
        organic_path = project_dir / blender_receipt["output_artifact"]
        organic_source = "blender_adapted"
    elif meshy_receipt and meshy_artifact:
        organic_path = Path(meshy_artifact)
        organic_source = "meshy"
    elif cad_receipt:
        organic_path = project_dir / cad_receipt["input_artifact"]
        organic_source = "unknown_origin"
    else:
        organic_path = None
        organic_source = None

    mechanical_path = project_dir / cad_receipt["output_artifact"] if cad_receipt else None

    any_stage_present = any(s["present"] for s in stages)

    return {
        "stages": stages,
        "organic_artifact_path": str(organic_path) if organic_path else None,
        "organic_source": organic_source,
        "mechanical_artifact_path": str(mechanical_path) if mechanical_path else None,
        "any_stage_present": any_stage_present,
        "chain_consistent": not broken_links,
        "broken_links": broken_links,
        "meshy_receipt": meshy_receipt,
        "blender_receipt": blender_receipt,
        "cad_receipt": cad_receipt,
    }


# ---------------------------------------------------------------------------
# Per-category scoring - each returns {"score", "confidence"?, "reasoning",
# "inputs"} for full traceability. Every input is read from an existing
# system; nothing here is independently re-derived.
# ---------------------------------------------------------------------------


def _score_lineage(chain: dict[str, Any]) -> dict[str, Any]:
    if not chain["any_stage_present"]:
        return {
            "score": 100,
            "reasoning": "No artifact chain exists yet - vacuously consistent (nothing to break).",
            "inputs": {"stages_present": []},
        }
    if chain["broken_links"]:
        return {
            "score": 0,
            "reasoning": "One or more recorded parent artifacts no longer match their recorded fingerprint or no longer exist - the chain's provenance is broken.",
            "inputs": {"broken_links": chain["broken_links"]},
        }
    return {
        "score": 100,
        "reasoning": "Every present stage's recorded parent fingerprint matches the current file on disk.",
        "inputs": {"stages_present": [s["stage"] for s in chain["stages"] if s["present"]]},
    }


def _validate_if_exists(path: str | None) -> dict[str, Any] | None:
    if not path or not Path(path).is_file():
        return None
    try:
        return validate_mesh(Path(path))
    except Exception as exc:  # never let a re-validation crash block the review
        return {"overall_status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}


_VALIDATION_STATUS_POINTS = {"PASS": 100, "WARN": 70, "FAIL": 0}


def _score_geometry(organic_report: dict[str, Any] | None, mechanical_report: dict[str, Any] | None) -> dict[str, Any]:
    reports = [r for r in (organic_report, mechanical_report) if r is not None]
    if not reports:
        return {
            "score": 0,
            "reasoning": "No artifact exists yet to validate.",
            "inputs": {"organic_status": None, "mechanical_status": None},
        }
    points = [_VALIDATION_STATUS_POINTS.get(r.get("overall_status"), 0) for r in reports]
    return {
        "score": round(sum(points) / len(points)),
        "reasoning": "Average of factory.validators.mesh_validate.validate_mesh() overall_status across every present component (organic body and/or CAD-augmented feature).",
        "inputs": {
            "organic_status": (organic_report or {}).get("overall_status"),
            "mechanical_status": (mechanical_report or {}).get("overall_status"),
        },
    }


def _score_scale(scale_assessment: dict[str, Any], blender_receipt: dict[str, Any] | None) -> dict[str, Any]:
    if blender_receipt and blender_receipt.get("single_shot_human_confirmation"):
        return {
            "score": 100,
            "reasoning": "Scale was explicitly human-confirmed and executed via a real, gated Blender adaptation (Phase 49) - factory.blender_adaptation.run_organic_cleanup_workflow() requires --confirm and a fresh target dimension for exactly this reason.",
            "inputs": {
                "scale_factor_applied": blender_receipt.get("scale_factor_applied"),
                "target_max_dimension_mm": blender_receipt.get("target_max_dimension_mm"),
            },
        }
    if scale_assessment.get("implausible"):
        return {
            "score": 0,
            "reasoning": "factory.hybrid_workflow.assess_scale() reports the current dimensions as implausible relative to expected size.",
            "inputs": {k: scale_assessment.get(k) for k in ("current_dimensions_mm", "expected_dimensions_mm", "scale_factor")},
        }
    confidence = scale_assessment.get("confidence")
    score = {"high": 80, "medium": 50, "low": 40, "unknown": 10}.get(confidence, 10)
    return {
        "score": score,
        "reasoning": f"factory.hybrid_workflow.assess_scale() confidence is {confidence!r}: {scale_assessment.get('reason')}",
        "inputs": {"confidence": confidence, "current_dimensions_mm": scale_assessment.get("current_dimensions_mm")},
    }


def _score_manufacturing(manufacturing_intent: dict[str, Any]) -> dict[str, Any]:
    confidence = manufacturing_intent.get("confidence")
    score = {"high": 100, "medium": 80, "low": 40, "unknown": 0}.get(confidence, 0)
    return {
        "score": score,
        "reasoning": f"factory.hybrid_workflow.assess_manufacturing_intent() confidence is {confidence!r}: {manufacturing_intent.get('reason')}",
        "inputs": {"candidate_intents": manufacturing_intent.get("candidate_intents"), "confidence": confidence},
    }


def _score_design_intent(design_intent_summary: dict[str, Any] | None, manufacturing_intent: dict[str, Any]) -> dict[str, Any]:
    if design_intent_summary is not None and (design_intent_summary.get("use_case") or "").strip():
        return {
            "score": 100,
            "reasoning": "A human declared design_intent.use_case in brief.json - the strongest available signal of intended purpose.",
            "inputs": {"use_case": design_intent_summary.get("use_case")},
        }
    if design_intent_summary is not None:
        return {
            "score": 60,
            "reasoning": "A design_intent block exists in brief.json, but use_case is not declared - purpose is only partially stated.",
            "inputs": {"design_intent_present": True, "use_case": None},
        }
    if manufacturing_intent.get("confidence") == "low":
        return {
            "score": 30,
            "reasoning": "No design_intent declared - purpose is only a weak, low-confidence default inferred from artifact origin (never a substitute for a human's actual answer).",
            "inputs": {"design_intent_present": False},
        }
    return {
        "score": 0,
        "reasoning": "No design_intent declared and no artifact-origin signal to even weakly guess from.",
        "inputs": {"design_intent_present": False},
    }


def _score_functional_completeness(workflow_type: str, mechanical_expected: bool, cad_receipt: dict[str, Any] | None) -> dict[str, Any]:
    if not mechanical_expected:
        return {
            "score": 100,
            "reasoning": f"workflow_type {workflow_type!r} does not expect a mechanical/functional feature - nothing missing.",
            "inputs": {"workflow_type": workflow_type, "mechanical_expected": False},
        }
    if cad_receipt is not None:
        return {
            "score": 100,
            "reasoning": "A mechanical feature was expected and factory.cad_augmentation's receipt confirms one was actually generated.",
            "inputs": {"workflow_type": workflow_type, "mechanical_expected": True, "cad_augmentation_present": True},
        }
    return {
        "score": 0,
        "reasoning": f"workflow_type {workflow_type!r} expects a mechanical/functional feature, but no cad_augmentation_receipt.json exists yet.",
        "inputs": {"workflow_type": workflow_type, "mechanical_expected": True, "cad_augmentation_present": False},
    }


def _score_review_readiness(readiness_assessment: dict[str, Any]) -> dict[str, Any]:
    """Reuses Phase 36's own already-computed `readiness_score` directly -
    the same reuse `factory.project_health._score_review_readiness()`
    already established for the traditional pipeline, applied here
    verbatim regardless of pipeline origin."""
    score = round(readiness_assessment.get("readiness_score", 0) or 0)
    return {
        "score": score,
        "reasoning": "factory.slicer_readiness.assess_slicer_readiness()'s own readiness_score, reused verbatim - never re-derived.",
        "inputs": {"readiness_status": readiness_assessment.get("readiness_status")},
    }


def compute_quality_score(categories: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Deterministic, weighted design_quality_score (0-100) plus the full
    per-category breakdown - see `QUALITY_CATEGORY_WEIGHTS` and
    `docs/design-review.md` "Scoring model". Every category's own
    `reasoning`/`inputs` travel with the score - never a magic number."""
    overall = round(sum(categories[name]["score"] * weight for name, weight in QUALITY_CATEGORY_WEIGHTS.items()))
    return {"overall": overall, "categories": categories, "weights": dict(QUALITY_CATEGORY_WEIGHTS)}


# ---------------------------------------------------------------------------
# Human checkpoints - explicit, never inferred
# ---------------------------------------------------------------------------


def _required_human_confirmations(
    *,
    design_intent_summary: dict[str, Any] | None,
    scale_score_entry: dict[str, Any],
    manufacturing_score_entry: dict[str, Any],
    workspace: dict[str, Any],
) -> list[dict[str, Any]]:
    """Every entry names a specific, concrete confirmation a human must
    make - never a vague "review this." `confirmed` is read straight off
    existing evidence; nothing here is ever auto-confirmed."""
    material_unresolved = bool(
        workspace["material_summary"]["unresolved_material_parts"] or workspace["material_summary"]["unresolved_color_parts"]
    )
    printer_confirmed = bool(workspace["printer_summary"].get("printer_id"))
    return [
        {"item": "design_intent_confirmed", "confirmed": design_intent_summary is not None, "detail": "Has a human declared design_intent.use_case in brief.json?"},
        {"item": "dimensions_confirmed", "confirmed": scale_score_entry["score"] >= 80, "detail": "Has the target size been explicitly confirmed (Blender adaptation execution, or a declared max_size_mm)?"},
        {"item": "manufacturing_purpose_confirmed", "confirmed": manufacturing_score_entry["score"] >= 80, "detail": "Is the manufacturing intent (decorative/functional/mechanical/...) confidently classified?"},
        {"item": "material_confirmed", "confirmed": not material_unresolved, "detail": "Is a material assigned for every part, with no unresolved color/material?"},
        {"item": "printer_confirmed", "confirmed": printer_confirmed, "detail": "Is a target printer actually selected (not just a fleet default)?"},
    ]


# ---------------------------------------------------------------------------
# Readiness state - deterministic decision tree, first match wins
# ---------------------------------------------------------------------------


def _determine_readiness_state(
    *,
    chain: dict[str, Any],
    blockers: list[dict[str, str]],
    confirmations: list[dict[str, Any]],
    readiness_assessment: dict[str, Any],
) -> str:
    if blockers:
        return "blocked"
    if not chain["any_stage_present"]:
        return "not_reviewed"
    if any(not c["confirmed"] for c in confirmations):
        return "needs_information"
    if readiness_assessment.get("readiness_status") in ("ready_for_review_package", "review_package_created"):
        return "approved_for_slicer_review"
    printer_and_material_ok = next(c["confirmed"] for c in confirmations if c["item"] == "printer_confirmed") and next(
        c["confirmed"] for c in confirmations if c["item"] == "material_confirmed"
    )
    if printer_and_material_ok:
        return "manufacturing_review_ready"
    return "design_review_ready"


# ---------------------------------------------------------------------------
# Recommended actions - concrete, grounded in already-computed facts
# ---------------------------------------------------------------------------


def _recommended_actions(
    *,
    confirmations: list[dict[str, Any]],
    chain: dict[str, Any],
    readiness_state: str,
    intelligence: dict[str, Any],
) -> list[str]:
    actions: list[str] = []
    by_item = {c["item"]: c for c in confirmations}
    if not by_item["dimensions_confirmed"]["confirmed"]:
        actions.append("Confirm target size before manufacturing (run `factory blender-adapt plan` with a --target-max-mm, or declare design_intent.manufacturability_constraints.max_size_mm).")
    if not by_item["printer_confirmed"]["confirmed"]:
        actions.append("Configure a printer profile before manufacturing review.")
    if not by_item["material_confirmed"]["confirmed"]:
        actions.append("Confirm material/color for every part before manufacturing review.")
    if not by_item["manufacturing_purpose_confirmed"]["confirmed"]:
        actions.append("Confirm the manufacturing purpose (decorative, functional, mechanical, replacement, educational, or collectible) in design_intent.use_case.")
    if not by_item["design_intent_confirmed"]["confirmed"]:
        actions.append("Declare a design_intent block in brief.json describing intended style/function.")
    if chain["broken_links"]:
        actions.append("Re-run the affected adaptation/augmentation step - its recorded source artifact has changed since it ran.")
    for message in intelligence.get("geometry_risks") or []:
        actions.append(f"Review geometry risk: {message.get('message')}")
    if readiness_state not in ("approved_for_slicer_review",):
        actions.append("Requires human slicer review before any further status advances.")
    return actions


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def evaluate_design_review(project_dir: Path) -> dict[str, Any]:
    """The core, read-only Hybrid Design Quality Review. Never writes
    anything, never invokes Meshy/Blender/CAD/a slicer/a printer/a
    network, never modifies geometry. `automatic_print_allowed` is always
    `False`.
    """
    project_dir = Path(project_dir)
    chain = _resolve_artifact_chain(project_dir)

    organic_report = _validate_if_exists(chain["organic_artifact_path"])
    mechanical_report = _validate_if_exists(chain["mechanical_artifact_path"])

    brief_path = project_dir / "brief.json"
    design_intent_summary = summarize_design_intent(brief_path) if brief_path.is_file() else None
    use_case = design_intent_summary.get("use_case") if design_intent_summary else None
    max_size_mm = design_intent_summary.get("max_size_mm") if design_intent_summary else None

    organic_mesh_stats = (organic_report or {}).get("mesh_stats") or {}
    scale_assessment = assess_scale(organic_mesh_stats, use_case=use_case, design_intent_max_size_mm=max_size_mm)

    artifact_type = {"meshy": "meshy_organic", "blender_adapted": "blender_adapted", "unknown_origin": "unknown"}.get(
        chain["organic_source"], "unknown"
    )
    manufacturing_intent = assess_manufacturing_intent(use_case=use_case, artifact_type=artifact_type)

    mechanical_expected = bool(manufacturing_intent.get("mechanical_features_expected"))
    # "Expected" (from declared/inferred intent) or "actually present" (a
    # CAD augmentation receipt already exists) both make this a hybrid
    # workflow for review purposes - a human adding a mechanical feature
    # without it being flagged by the (coarse, keyword-only) intent
    # classifier is still a real hybrid artifact, not a misclassification
    # to penalize.
    workflow_type_label = "hybrid_organic_mechanical" if (mechanical_expected or chain["cad_receipt"] is not None) else "organic_concept_to_print"

    workspace = assess_manual_review_workspace(project_dir)
    readiness_assessment = assess_slicer_readiness(project_dir)
    intelligence = evaluate_slicer_intelligence(project_dir)

    categories = {
        "design_intent": _score_design_intent(design_intent_summary, manufacturing_intent),
        "lineage": _score_lineage(chain),
        "geometry": _score_geometry(organic_report, mechanical_report),
        "scale": _score_scale(scale_assessment, chain["blender_receipt"]),
        "manufacturing": _score_manufacturing(manufacturing_intent),
        "review_readiness": _score_review_readiness(readiness_assessment),
    }
    # functional_completeness is reported but deliberately excluded from
    # the weighted score - it is a binary "is the expected feature
    # present" gate, already fully captured as a blocker/warning below,
    # not a graded quality dimension (see docs/design-review.md).
    functional_completeness = _score_functional_completeness(workflow_type_label, mechanical_expected, chain["cad_receipt"])

    quality_score = compute_quality_score(categories)
    confirmations = _required_human_confirmations(
        design_intent_summary=design_intent_summary,
        scale_score_entry=categories["scale"],
        manufacturing_score_entry=categories["manufacturing"],
        workspace=workspace,
    )

    blockers: list[dict[str, str]] = []
    if categories["geometry"]["score"] == 0 and chain["any_stage_present"]:
        blockers.append({"source": "geometry", "message": "Factory mesh validation reported FAIL (or no artifact) for a component in this chain."})
    if chain["broken_links"]:
        for message in chain["broken_links"]:
            blockers.append({"source": "lineage", "message": message})
    if functional_completeness["score"] == 0:
        blockers.append({"source": "functional_completeness", "message": functional_completeness["reasoning"]})

    warnings: list[dict[str, str]] = []
    if (organic_report or {}).get("overall_status") == "WARN":
        warnings.append({"source": "geometry", "message": "Organic component validation reported WARN."})
    if (mechanical_report or {}).get("overall_status") == "WARN":
        warnings.append({"source": "geometry", "message": "Mechanical (CAD-augmented) component validation reported WARN."})
    for message in intelligence.get("warnings") or []:
        warnings.append({"source": "slicer_intelligence", "message": message})

    strengths: list[str] = []
    if chain["blender_receipt"] and chain["blender_receipt"].get("single_shot_human_confirmation"):
        strengths.append("Scale adaptation was explicitly human-confirmed and executed.")
    if chain["cad_receipt"] and chain["cad_receipt"].get("single_shot_human_confirmation"):
        strengths.append("CAD augmentation was explicitly human-confirmed and executed.")
    if design_intent_summary is not None and use_case:
        strengths.append("Design intent and use case are clearly declared.")
    if chain["any_stage_present"] and not chain["broken_links"]:
        strengths.append("Artifact lineage is fully consistent - no broken parent/child fingerprints.")

    readiness_state = _determine_readiness_state(
        chain=chain, blockers=blockers, confirmations=confirmations, readiness_assessment=readiness_assessment
    )
    assert readiness_state in READINESS_STATES

    recommended_actions = _recommended_actions(
        confirmations=confirmations, chain=chain, readiness_state=readiness_state, intelligence=intelligence
    )

    unresolved_confirmations = sum(1 for c in confirmations if not c["confirmed"])
    if blockers or chain["broken_links"]:
        confidence = "low"
    elif unresolved_confirmations <= 1:
        confidence = "high"
    elif unresolved_confirmations <= 3:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "design_review_version": DESIGN_REVIEW_VERSION,
        "project": str(project_dir),
        "artifact_chain": chain["stages"],
        "organic_artifact": chain["organic_artifact_path"],
        "mechanical_artifact": chain["mechanical_artifact_path"],
        "chain_consistent": chain["chain_consistent"],
        "workflow_type": workflow_type_label,
        "manufacturing_intent": manufacturing_intent,
        "functional_completeness": functional_completeness,
        "design_quality_score": quality_score["overall"],
        "score_categories": quality_score["categories"],
        "score_weights": quality_score["weights"],
        "manufacturing_readiness": readiness_state,
        "confidence": confidence,
        "strengths": strengths,
        "risks": [{"category": r.get("category", ""), "message": r.get("message", "")} for r in (intelligence.get("geometry_risks") or []) + (intelligence.get("manufacturing_risks") or [])],
        "blockers": blockers,
        "warnings": warnings,
        "required_human_confirmations": confirmations,
        "recommended_actions": recommended_actions,
        "printer_summary": workspace["printer_summary"],
        "material_summary": workspace["material_summary"],
        "no_geometry_modified": True,
        "automatic_print_allowed": False,
        "automatic_approval_granted": False,
    }


def evaluate_design_review_for_path(path: Path) -> dict[str, Any]:
    """Convenience entry point `factory design-review <project>` uses."""
    return evaluate_design_review(path)


# ---------------------------------------------------------------------------
# Optional persistence - a read-only analysis SNAPSHOT, never an
# execution receipt. Only ever written when explicitly requested
# (`factory design-review <project> --save`) - never a side effect of a
# plain review call.
# ---------------------------------------------------------------------------

REPORT_FILENAME = "design_review_report.json"


def save_design_review_report(project_dir: Path) -> Path:
    """Write `generated/design_review_report.json` - a versioned,
    fingerprinted snapshot of `evaluate_design_review()`'s own output at
    this moment. Never overwrites an execution receipt (a different
    filename from every `*_receipt.json` in this repo) and is itself
    always overwritable (each call recomputes and replaces the prior
    snapshot - there is no execution to protect here, only an analysis
    a human may want to re-run and re-save).
    """
    project_dir = Path(project_dir)
    review = evaluate_design_review(project_dir)
    report_path = project_dir / "generated" / REPORT_FILENAME
    report = {
        "design_review_version": DESIGN_REVIEW_VERSION,
        "generated_at": project_store.utc_now_iso(),
        "review": review,
    }
    project_store.save_json(report_path, report)
    return report_path


def read_design_review_report(project_dir: Path) -> dict[str, Any] | None:
    """Read-only: the most recently saved snapshot, if one exists, else
    `None`. Never triggers a save."""
    report_path = Path(project_dir) / "generated" / REPORT_FILENAME
    if not report_path.is_file():
        return None
    try:
        return project_store.load_json(report_path)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Preview Board summary - wired in at the aggregation point
# (factory.preview_board.gather_board_data()), never inside
# factory.project_health/project_inspection. See the standing
# "Aggregation Layer Convention" in docs/architecture.md.
# ---------------------------------------------------------------------------


def summarize_design_review(project_dir: Path) -> dict[str, Any]:
    """Compact, read-only summary for the Preview Board. Always computed
    fresh (never reads a saved snapshot, so it can never go stale) -
    never writes, never invokes Meshy/Blender/CAD/a subprocess of any
    kind."""
    review = evaluate_design_review(project_dir)
    if not review["artifact_chain"] or not any(s["present"] for s in review["artifact_chain"]):
        return {
            "review_available": False,
            "manufacturing_readiness": "not_reviewed",
            "design_quality_score": None,
            "top_risks": [],
        }
    top_risks = [b["message"] for b in review["blockers"]][:2] + [r["message"] for r in review["risks"]][: max(0, 2 - len(review["blockers"]))]
    return {
        "review_available": True,
        "manufacturing_readiness": review["manufacturing_readiness"],
        "design_quality_score": review["design_quality_score"],
        "top_risks": top_risks[:2],
    }

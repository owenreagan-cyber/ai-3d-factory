"""Phase 48: Hybrid Design Workflow Manager.

The adaptation layer between generative AI concept output and
manufacturing-ready Factory output. Meshy (Phase 47) proved it can
produce a real, watertight, previewable concept - and also proved that
concept is not automatically manufacturing-ready (the first real live
artifact, a piggy bank, came back at a ~1.9 *meter* bounding box - see
`docs/meshy-live-transport.md` and the Phase 47B.7 post-flight review).
This module is the planning layer that sits between "an artifact exists"
and "an artifact is ready for the existing validate -> preview ->
review-gate -> slicer-readiness -> human-approval pipeline":

    Input artifact -> Assessment -> Adaptation recommendation ->
    Tool routing -> Transformation plan -> Validation requirements ->
    Human checkpoints

**This module never transforms anything.** It reads whatever already
exists (a Meshy receipt, a CAD generation/export receipt, an optional
`design_intent` block in `brief.json`) and produces one deterministic,
read-only `AdaptationPlan` - a recommendation a human reviews, never an
action taken. `automatic_execution_allowed` is hardcoded `False` in
every plan this module ever returns; there is no code path here that
calls Blender, a CAD backend, a slicer, or a printer, and no code path
that rescales, repairs, remeshes, or otherwise mutates a mesh file.

**Not the same thing as `factory.design_orchestrator`.** That module
(Phase 33) recommends an engine *before* any generation happens, from
intake/brief/design-intent signals alone (it already has a `"Hybrid
Workflow"` value in its own `RECOMMENDED_ENGINES` for a mixed organic+
mechanical signal). This module operates strictly *after* generation,
on an artifact that already exists, deciding what adaptation that
specific artifact needs next. Neither module re-implements the other;
`build_adaptation_plan()` never re-derives an engine recommendation for
work that hasn't started yet - that remains `design_orchestrator`'s job.

Reuses rather than duplicates:

- `factory.meshy_live_adapter`'s receipt shape (`generated/meshy_receipt.json`)
  and `factory.generation_gate.read_last_execution_receipt()` /
  `factory.export_pipeline.read_export_receipt()` for CAD-origin artifacts
  - the same receipts `factory.project_timeline` already reads.
- `factory.validators.mesh_validate.validate_mesh()` - the one real mesh
  validator in this repo. This module re-runs it read-only against an
  artifact path already recorded in a receipt; it never writes a second
  validation report and never invents its own watertight/manifold check.
- `factory.design_intent_check.summarize_design_intent()` - the one
  existing reader of a project's optional `design_intent.use_case` /
  `design_intent.manufacturability_constraints.max_size_mm` fields. This
  module never re-parses `brief.json` itself.
- `factory.engine_registry.get_tool_registry()` - the one existing source
  of per-tool suitability (`organic_modeling_suitability`,
  `mechanical_design_suitability`, `mesh_cleanup_suitability`, etc.) for
  tool routing. This module never re-scores a tool's suitability itself.
- `factory.blender_gate.evaluate_blender_execution_gate()` (Phase 45) -
  the one existing source of "is Blender actually usable right now, and
  for which workflows". A recommended Blender adaptation step always
  carries this gate's real `gate_status`/`project_execution_approved`
  verbatim; it never claims Blender is ready when the gate says otherwise.
- `factory.project_timeline`/`factory.artifact_history` - a future,
  real adaptation artifact enters through those existing systems
  (Phase 40/41), never a second lineage/version model. This phase adds
  no new persisted receipt writer of its own; there is nothing to write
  yet, since nothing here executes.

See `docs/hybrid-workflow.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import project_store
from factory.blender_gate import evaluate_blender_execution_gate
from factory.design_intent_check import summarize_design_intent
from factory.engine_registry import get_tool_registry
from factory.export_pipeline import read_export_receipt
from factory.generation_gate import read_last_execution_receipt
from factory.validators.mesh_validate import validate_mesh

HYBRID_WORKFLOW_VERSION = 1

# Minimum useful set (Phase 48 spec) - deliberately not exhaustive. "unknown"
# is a real, honest outcome for a project with no input artifact yet.
WORKFLOW_TYPES = (
    "organic_concept_to_print",
    "mechanical_part_refinement",
    "hybrid_organic_mechanical",
    "replacement_part_reconstruction",
    "functional_product_design",
    "decorative_collectible",
    "unknown",
)

ARTIFACT_TYPES = ("meshy_organic", "cad_mechanical", "blender_adapted", "unknown")

# Never "ready" outright - this repo's own convention (see
# config/agent_policy.json's status_gates.max_automatic_status) is that no
# automatic process ever asserts more than "ready for human review".
MANUFACTURING_READINESS_STATES = ("not_ready", "needs_human_review", "unknown")

# Candidate CAD tool ids this module will ever recommend by name - a fixed,
# small, hand-reviewed list (never every registry entry with a matching
# suitability field, which would also catch slicers/GUI apps that happen to
# score "high" on an unrelated axis).
_CAD_TOOL_IDS = ("cadquery", "openscad_stable", "freecad")

# Verbatim from Phase 48's own spec - human-declared examples, never
# invented, never treated as a universal size table. Used only as a
# low-confidence advisory when no project-specific design_intent size
# exists; a human must still confirm any real target size.
_USE_CASE_SIZE_HINTS_MM = {
    "figurine": (100.0, 200.0),
    "desk object": (50.0, 300.0),
}

_INTENT_KEYWORDS = {
    "replacement_part": ("replacement", "spare part", "broken part", "repair part"),
    "functional": ("functional", "tool", "bracket", "mount", "holder", "fixture"),
    "load_bearing": ("load-bearing", "load bearing", "structural", "weight-bearing"),
    "mechanical": ("mechanical", "moving part", "hinge", "gear", "assembly"),
    "educational": ("classroom", "educational", "teaching", "student"),
    "collectible": ("collectible", "figurine", "display", "decorative", "gift"),
}


# ---------------------------------------------------------------------------
# Input artifact discovery - read-only, reuses existing receipt readers
# ---------------------------------------------------------------------------


def _find_input_artifact(project_dir: Path) -> dict[str, Any]:
    """Reads whatever generation evidence already exists for this project -
    never writes, never validates, never picks between receipts on
    anything but existence. A Meshy receipt is checked first (this
    module's motivating case); a CAD generation/export receipt second;
    otherwise `"none"`."""
    project_dir = Path(project_dir)

    meshy_receipt_path = project_dir / "generated" / "meshy_receipt.json"
    if meshy_receipt_path.is_file():
        try:
            receipt = project_store.load_json(meshy_receipt_path)
        except (OSError, ValueError):
            receipt = None
        if isinstance(receipt, dict):
            artifact_paths = receipt.get("output_artifact_paths") or []
            return {
                "artifact_type": "meshy_organic",
                "artifact_path": Path(artifact_paths[0]) if artifact_paths else None,
                "source": "meshy_receipt",
                "mock_execution": receipt.get("mock_execution"),
                "receipt_validation_status": receipt.get("validation_status"),
                "receipt_preview_status": receipt.get("preview_status"),
                "provider_task_id": receipt.get("meshy_task_id"),
            }

    generation_receipt = read_last_execution_receipt(project_dir)
    export_receipt = read_export_receipt(project_dir)
    if generation_receipt or export_receipt:
        # A generation_receipt.json only exists for a run that went through
        # the full generation gate (factory.generation_gate); a project
        # that only ran factory.export_pipeline directly still has real
        # CAD-origin geometry (OpenSCAD/CadQuery are this repo's only two
        # non-Meshy generators) and an artifact worth adapting - so either
        # receipt alone is sufficient evidence, and export_receipt is
        # always checked for the actual artifact path.
        artifact_path = None
        for record in (export_receipt or {}).get("exports", []):
            output_stl = record.get("output_stl") or record.get("source_file")
            if output_stl:
                artifact_path = project_dir / output_stl
                break
        return {
            "artifact_type": "cad_mechanical",
            "artifact_path": artifact_path,
            "source": "generation_receipt" if generation_receipt else "export_receipt",
            "engine": (generation_receipt or {}).get("engine"),
            "receipt_validation_status": None,
            "receipt_preview_status": None,
            "provider_task_id": None,
        }

    return {
        "artifact_type": "none",
        "artifact_path": None,
        "source": None,
        "receipt_validation_status": None,
        "receipt_preview_status": None,
        "provider_task_id": None,
    }


# ---------------------------------------------------------------------------
# Scale assessment - genuinely new capability (no existing scale-plausibility
# check anywhere in this repo; factory.validators.dimension_check only
# checks fit against a configured printer's build volume, a different
# question). Never rescales; always requires human confirmation.
# ---------------------------------------------------------------------------


def assess_scale(
    mesh_stats: dict[str, Any] | None, *, use_case: str | None, design_intent_max_size_mm: Any = None
) -> dict[str, Any]:
    """Compares a mesh's actual bounding box against whatever expected-size
    evidence already exists for this project - a project's own declared
    `design_intent.manufacturability_constraints.max_size_mm` first (high
    confidence, human-declared), a loose `use_case` keyword hint second
    (low confidence, advisory only, using Phase 48's own example table
    verbatim), or nothing at all (unknown - never guessed). Never
    rescales anything; `requires_human_confirmation` is always `True`."""
    mesh_stats = mesh_stats or {}
    current = mesh_stats.get("bounding_box_mm")

    expected: dict[str, float] | None = None
    confidence = "unknown"
    reason = "No declared design-intent size and no matching use-case hint - cannot assess plausibility."

    if isinstance(design_intent_max_size_mm, (list, tuple)) and len(design_intent_max_size_mm) == 3:
        try:
            x, y, z = (float(v) for v in design_intent_max_size_mm)
        except (TypeError, ValueError):
            x = y = z = None  # type: ignore[assignment]
        if x is not None:
            expected = {"max_x_mm": x, "max_y_mm": y, "max_z_mm": z}
            confidence = "high"
            reason = "Compared against this project's own declared design_intent.manufacturability_constraints.max_size_mm."
    elif use_case:
        lowered = use_case.lower()
        for key, (lo, hi) in _USE_CASE_SIZE_HINTS_MM.items():
            if key in lowered:
                expected = {"min_mm": lo, "max_mm": hi}
                confidence = "low"
                reason = f"No declared max_size_mm; loosely inferred from use_case containing {key!r} - advisory only, not a universal size rule."
                break

    scale_factor = None
    implausible = False
    if current and expected:
        largest_current = max(current.values())
        if "max_x_mm" in expected:
            largest_expected = max(v for v in (expected["max_x_mm"], expected["max_y_mm"], expected["max_z_mm"]) if v is not None)
        else:
            largest_expected = expected["max_mm"]
        if largest_expected:
            scale_factor = round(largest_current / largest_expected, 4)
            implausible = scale_factor > 2.0 or scale_factor < 0.5

    return {
        "current_dimensions_mm": current,
        "expected_dimensions_mm": expected,
        "scale_factor": scale_factor,
        "implausible": implausible,
        "confidence": confidence,
        "reason": reason,
        "requires_human_confirmation": True,
    }


# ---------------------------------------------------------------------------
# Manufacturing intent - reuses design_intent_check's existing `use_case`
# reader; never re-parses brief.json itself. A coarse, low-confidence,
# always-human-confirmed keyword classification, never authoritative.
# ---------------------------------------------------------------------------


def assess_manufacturing_intent(*, use_case: str | None, artifact_type: str) -> dict[str, Any]:
    """Best-effort, always-advisory classification of manufacturing intent
    (decorative / functional / load-bearing / mechanical / educational /
    replacement-part / collectible) from a project's own declared
    `design_intent.use_case` text - never invented, never a substitute for
    a human's actual answer. `requires_human_confirmation` is always
    `True`."""
    text = (use_case or "").lower()
    matched = [tag for tag, keywords in _INTENT_KEYWORDS.items() if any(kw in text for kw in keywords)]

    if matched:
        confidence = "medium"
        reason = f"Matched keyword(s) in this project's declared design_intent.use_case: {use_case!r}."
    elif artifact_type == "meshy_organic":
        matched = ["collectible"]
        confidence = "low"
        reason = (
            "No design_intent.use_case declared. Meshy is reserved for organic concept "
            "generation in this repo (docs/meshy-approval-gate.md), so a decorative/collectible "
            "default is a weak guess only, not a real classification."
        )
    else:
        confidence = "unknown"
        reason = "No design_intent.use_case declared and no keyword signal available."

    return {
        "candidate_intents": matched,
        "confidence": confidence,
        "reason": reason,
        "mechanical_features_expected": "mechanical" in matched or "load_bearing" in matched,
        "requires_human_confirmation": True,
    }


# ---------------------------------------------------------------------------
# Tool routing - reuses engine_registry + blender_gate; never a second
# engine selector, never a competing suitability score.
# ---------------------------------------------------------------------------


def _organic_adaptation_step() -> dict[str, Any]:
    gate = evaluate_blender_execution_gate()
    return {
        "step": "blender_organic_adaptation",
        "tool": "blender",
        "description": (
            "Clean geometry, correct scale/orientation, and prepare the organic Meshy "
            "concept for downstream mechanical feature work - reusing Phase 45's Blender "
            "gate, never a second Blender path."
        ),
        "engine_gate_status": gate["gate_status"],
        "engine_project_execution_approved": gate["project_execution_approved"],
        "requires_human_confirmation": True,
        "automatic_execution_allowed": False,
    }


def _mechanical_augmentation_step(registry: dict[str, dict[str, Any]]) -> dict[str, Any]:
    candidates = sorted(
        tool_id
        for tool_id in _CAD_TOOL_IDS
        if tool_id in registry and registry[tool_id].get("mechanical_design_suitability") == "high"
    )
    return {
        "step": "cad_mechanical_augmentation",
        "tool": None,
        "candidate_tools": candidates,
        "description": (
            "Add mechanical/functional features (e.g. a coin slot, a flat base, a mounting "
            "feature) with dimensional precision a sculpted mesh alone doesn't guarantee - "
            "reusing factory.engine_registry's existing mechanical_design_suitability field, "
            "never re-scored here."
        ),
        "requires_human_confirmation": True,
        "automatic_execution_allowed": False,
    }


def _validation_step() -> dict[str, Any]:
    return {
        "step": "factory_validation",
        "tool": "factory.validators.mesh_validate",
        "description": "Re-run the existing Factory mesh validator against the adapted artifact - never a Meshy/Blender/CAD-specific validator.",
        "requires_human_confirmation": False,
        "automatic_execution_allowed": False,
    }


def route_tools(*, workflow_type: str) -> dict[str, Any]:
    """Deterministic tool routing for a given workflow type - reuses
    `factory.engine_registry.get_tool_registry()` and
    `factory.blender_gate.evaluate_blender_execution_gate()` directly;
    never a second engine-selection heuristic (that remains
    `factory.design_orchestrator`'s job, for pre-generation decisions
    only)."""
    registry = get_tool_registry()

    if workflow_type in ("organic_concept_to_print", "decorative_collectible"):
        steps = [_organic_adaptation_step(), _validation_step()]
        recommended_engine = "blender"
        rationale = "Organic Meshy output needs cleanup/scale/orientation adaptation (high organic_modeling_suitability + mesh_cleanup_suitability) before validation - no mechanical precision features required."
    elif workflow_type in ("mechanical_part_refinement", "replacement_part_reconstruction", "functional_product_design"):
        steps = [_mechanical_augmentation_step(registry), _validation_step()]
        recommended_engine = "cad"
        rationale = "Mechanical/functional/replacement-part work needs dimensional precision (high mechanical_design_suitability) - a sculpted organic mesh is the wrong tool for this."
    elif workflow_type == "hybrid_organic_mechanical":
        steps = [_organic_adaptation_step(), _mechanical_augmentation_step(registry), _validation_step()]
        recommended_engine = "blender_then_cad"
        rationale = "Organic body shape (Blender adaptation) plus functional/mechanical features (CAD augmentation) - matches the piggy-bank motivating example: body from Meshy, cleanup in Blender, coin slot/base as CAD augmentation."
    else:
        steps = [_validation_step()]
        recommended_engine = None
        rationale = "Workflow type unknown or no clear routing signal - defer to human judgment before recommending a specific tool chain."

    return {"steps": steps, "recommended_engine": recommended_engine, "rationale": rationale}


# ---------------------------------------------------------------------------
# Workflow-type classification
# ---------------------------------------------------------------------------


def _classify_workflow_type(*, artifact_type: str, manufacturing_intent: dict[str, Any]) -> str:
    if artifact_type == "meshy_organic":
        if manufacturing_intent["mechanical_features_expected"]:
            return "hybrid_organic_mechanical"
        if "replacement_part" in manufacturing_intent["candidate_intents"]:
            return "replacement_part_reconstruction"
        if "collectible" in manufacturing_intent["candidate_intents"]:
            return "decorative_collectible"
        return "organic_concept_to_print"
    if artifact_type == "cad_mechanical":
        if "replacement_part" in manufacturing_intent["candidate_intents"]:
            return "replacement_part_reconstruction"
        if "functional" in manufacturing_intent["candidate_intents"]:
            return "functional_product_design"
        return "mechanical_part_refinement"
    return "unknown"


def _manufacturing_readiness(*, artifact_type: str, issues_found: list[str]) -> str:
    if artifact_type == "none":
        return "unknown"
    if issues_found:
        return "not_ready"
    return "needs_human_review"


# ---------------------------------------------------------------------------
# Public: full project-level plan
# ---------------------------------------------------------------------------


def build_adaptation_plan(project_dir: Path) -> dict[str, Any]:
    """The full, deterministic, read-only `AdaptationPlan` for one project.
    Never writes anything, never invokes Blender/CAD/a slicer/a printer,
    never rescales or repairs a mesh. `automatic_execution_allowed` is
    always `False`."""
    project_dir = Path(project_dir)
    artifact_info = _find_input_artifact(project_dir)
    artifact_type = artifact_info["artifact_type"]
    issues: list[str] = []

    if artifact_type == "none":
        return {
            "hybrid_workflow_version": HYBRID_WORKFLOW_VERSION,
            "input_artifact": None,
            "artifact_type": "none",
            "workflow_type": "unknown",
            "current_state": {},
            "issues_found": ["No input artifact found for this project (no generated/meshy_receipt.json and no CAD generation receipt)."],
            "recommended_engine": None,
            "engine_rationale": "No artifact to adapt yet.",
            "adaptation_steps": [],
            "required_human_confirmations": ["Generate or import an initial concept/CAD artifact before requesting an adaptation plan."],
            "validation_plan": [],
            "preview_plan": [],
            "scale_assessment": None,
            "manufacturing_intent": None,
            "manufacturing_readiness": "unknown",
            "automatic_execution_allowed": False,
            "no_automatic_print": True,
        }

    artifact_path = artifact_info.get("artifact_path")
    validation_report: dict[str, Any] | None = None
    if artifact_path and Path(artifact_path).is_file():
        try:
            validation_report = validate_mesh(artifact_path)
        except Exception as exc:  # never let a re-validation crash block plan generation
            issues.append(f"Could not re-validate artifact: {type(exc).__name__}: {exc}")
    elif artifact_path:
        issues.append(f"Artifact path recorded in receipt does not exist on disk: {artifact_path}")

    mesh_stats = (validation_report or {}).get("mesh_stats") or {}
    if validation_report and validation_report.get("overall_status") == "FAIL":
        issues.append("Factory mesh validation reported FAIL - do not proceed to adaptation until this is fixed.")
    elif validation_report and validation_report.get("overall_status") == "WARN":
        issues.append("Factory mesh validation reported WARN - review before adaptation (see current_state.validation_overall_status).")

    brief_path = project_dir / "brief.json"
    design_intent = summarize_design_intent(brief_path) if brief_path.is_file() else None
    use_case = design_intent.get("use_case") if design_intent else None
    max_size_mm = design_intent.get("max_size_mm") if design_intent else None
    if design_intent is None:
        issues.append("No design_intent recorded for this project - manufacturing intent and scale checks are advisory-only until a human provides one.")

    scale_assessment = assess_scale(mesh_stats, use_case=use_case, design_intent_max_size_mm=max_size_mm)
    if scale_assessment["implausible"]:
        issues.append(
            "scale_not_manufacturing_ready: current dimensions are implausible relative to expected size "
            f"(scale_factor={scale_assessment['scale_factor']}) - a human must confirm target dimensions before any scaling."
        )
    elif scale_assessment["expected_dimensions_mm"] is None:
        issues.append("scale_not_manufacturing_ready: no declared or inferable expected size - current dimensions cannot be judged plausible.")

    manufacturing_intent = assess_manufacturing_intent(use_case=use_case, artifact_type=artifact_type)
    workflow_type = _classify_workflow_type(artifact_type=artifact_type, manufacturing_intent=manufacturing_intent)
    routing = route_tools(workflow_type=workflow_type)

    required_confirmations = [
        "Confirm workflow_type and manufacturing_intent classification (both are advisory, low/medium confidence).",
        "Confirm target dimensions before any scaling action (scale_assessment.requires_human_confirmation is always true).",
    ]
    for step in routing["steps"]:
        if step.get("requires_human_confirmation"):
            required_confirmations.append(f"Approve {step['step']} before it is performed.")

    current_state = {
        "artifact_path": str(artifact_path) if artifact_path else None,
        "artifact_source": artifact_info.get("source"),
        "provider_task_id": artifact_info.get("provider_task_id"),
        "mock_execution": artifact_info.get("mock_execution"),
        "receipt_validation_status": artifact_info.get("receipt_validation_status"),
        "receipt_preview_status": artifact_info.get("receipt_preview_status"),
        "validation_overall_status": (validation_report or {}).get("overall_status"),
        "mesh_stats": mesh_stats,
    }

    return {
        "hybrid_workflow_version": HYBRID_WORKFLOW_VERSION,
        "input_artifact": str(artifact_path) if artifact_path else None,
        "artifact_type": artifact_type,
        "workflow_type": workflow_type,
        "current_state": current_state,
        "issues_found": issues,
        "recommended_engine": routing["recommended_engine"],
        "engine_rationale": routing["rationale"],
        "adaptation_steps": routing["steps"],
        "required_human_confirmations": required_confirmations,
        "validation_plan": ["Re-run factory.validators.mesh_validate.validate_mesh() against the adapted artifact before any human review."],
        "preview_plan": ["Re-run factory.previews.render_preview.render_preview() against the adapted artifact before any human review."],
        "scale_assessment": scale_assessment,
        "manufacturing_intent": manufacturing_intent,
        "manufacturing_readiness": _manufacturing_readiness(artifact_type=artifact_type, issues_found=issues),
        "automatic_execution_allowed": False,
        "no_automatic_print": True,
    }


def build_adaptation_plan_for_path(path: Path) -> dict[str, Any]:
    """Convenience entry point `factory workflow plan <project>` uses."""
    return build_adaptation_plan(path)


# ---------------------------------------------------------------------------
# Public: lightweight standalone artifact assessment (no project/receipt
# context needed) - `factory workflow assess <artifact>`.
# ---------------------------------------------------------------------------


def assess_artifact_file(path: Path) -> dict[str, Any]:
    """A quick, standalone read on one mesh file that isn't (yet) part of a
    project's `generated/` pipeline - reuses `validate_mesh()`/
    `assess_scale()` exactly like `build_adaptation_plan()` does, without
    any receipt/design-intent context. Never writes, never repairs."""
    path = Path(path)
    if not path.is_file():
        return {
            "file": str(path),
            "error": "file_not_found",
            "validation_overall_status": None,
            "mesh_stats": None,
            "scale_assessment": None,
            "no_automatic_print": True,
        }
    try:
        report = validate_mesh(path)
    except Exception as exc:
        return {
            "file": str(path),
            "error": f"{type(exc).__name__}: {exc}",
            "validation_overall_status": None,
            "mesh_stats": None,
            "scale_assessment": None,
            "no_automatic_print": True,
        }

    mesh_stats = report.get("mesh_stats") or {}
    scale_assessment = assess_scale(mesh_stats, use_case=None, design_intent_max_size_mm=None)
    return {
        "file": str(path),
        "error": None,
        "validation_overall_status": report.get("overall_status"),
        "mesh_stats": mesh_stats,
        "scale_assessment": scale_assessment,
        "no_automatic_print": True,
    }


# ---------------------------------------------------------------------------
# Preview Board summary - wired in at the aggregation point
# (factory.preview_board.gather_board_data()), never inside
# factory.project_health/project_inspection. See the standing
# "Aggregation Layer Convention" in docs/architecture.md.
# ---------------------------------------------------------------------------


def summarize_hybrid_workflow(project_dir: Path) -> dict[str, Any]:
    """Compact, read-only summary for the Preview Board. Never writes,
    never invokes a subprocess. Returns a `plan_available: False` shape
    for a project with no input artifact yet, rather than omitting the
    field entirely - consistent with every other Phase 40+ board summary."""
    plan = build_adaptation_plan(project_dir)
    if plan["artifact_type"] == "none":
        return {
            "plan_available": False,
            "workflow_type": None,
            "manufacturing_readiness": "unknown",
            "issue_count": 0,
            "recommended_engine": None,
        }
    return {
        "plan_available": True,
        "workflow_type": plan["workflow_type"],
        "manufacturing_readiness": plan["manufacturing_readiness"],
        "issue_count": len(plan["issues_found"]),
        "recommended_engine": plan["recommended_engine"],
    }

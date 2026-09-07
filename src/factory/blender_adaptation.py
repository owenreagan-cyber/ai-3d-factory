"""Phase 49: Blender Adaptation Execution Gate & Controlled Organic
Cleanup Workflow.

Proves exactly one safe Blender adaptation workflow end to end:

    Meshy artifact -> Blender controlled adaptation -> Factory artifact
    -> Validation -> Preview -> Human review

**This is the first module in this repo that executes real Blender
automation against a real project artifact.** `docs/blender-adapter.md`
(Phase 45) pre-documented exactly this future step - output isolated to
`<project>/generated/blender/`, refuse to overwrite, feed
`factory.project_timeline`/`factory.artifact_history` additively - and
named it "a future real Blender project-generation phase (not Phase
45)". This is that phase. It answers as narrowly as Phase 45 did:
**exactly one workflow (`organic_cleanup_workflow`: import a Meshy/CAD-
origin STL, apply one explicit uniform scale factor, export a new child
STL), never general Blender automation, never mesh repair, never
remeshing/decimating/smoothing.**

    AI output            != manufacturing ready
    Blender output        != approved product
    Validation            != human approval
    Human approval         != print approval
    Automatic printing remains impossible.

## Why real execution is safe to add in this phase, without touching
## `config/future_local_tools.json`

`docs/blender-local-track.md` requires "a separate, later, explicit
[human] decision" before `config/future_local_tools.json`'s
`tools.blender.enabled`/`allows_automation`/`allows_background_execution`
may ever become `true` - and Phase 45's own gate-checklist item 1 named
that phase's *own dated spec* as the explicit human instruction that
narrowly authorized its one-shot fixture pipeline, **without** flipping
that config. This phase follows the identical precedent: this phase's
own dated spec is the explicit human instruction that narrowly
authorizes exactly `organic_cleanup_workflow`, with mandatory
per-invocation human confirmation (never a standing "automation is on"
state) - so `config/future_local_tools.json` stays untouched here too.
`allows_automation`/`allows_background_execution` correctly continue to
mean "Blender runs unattended, on its own" - never true of this phase's
design, since every single real execution requires a fresh
`--confirm` on that exact call, with nothing cached or persisted between
calls.

Reuses rather than duplicates:

- `factory.blender_gate.evaluate_blender_execution_gate()` /
  `factory.blender_gate.plan_organic_cleanup_execution()` - the one
  existing Blender permission/planning system. This module never invents
  a second one.
- `factory.blender_adapter.qualify_blender_adapter()` /
  `factory.blender_adapter.run_organic_cleanup_workflow()` - the one
  module in this repo that ever passes Blender to `subprocess`. This
  module never launches Blender itself.
- `factory.hybrid_workflow.assess_scale()` (Phase 48) - the one existing
  scale-plausibility check. Never re-derived here.
- `factory.design_intent_check.summarize_design_intent()` - the one
  existing reader of a project's declared `design_intent` block.
- `factory.validators.mesh_validate.validate_mesh()` /
  `factory.previews.render_preview.render_preview()` - the one existing
  Factory validator/preview renderer. No Blender-specific validator or
  visual-QA subsystem exists or is added here.
- `factory.project_timeline`/`factory.artifact_history` - a real
  adaptation receipt enters through those existing systems additively
  (see the new `_events_from_blender_adaptation_receipt()` adapter in
  `factory.project_timeline`), never a second lineage/version model.

See `docs/blender-adaptation.md`.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from factory import blender_adapter, blender_gate, project_store
from factory.design_intent_check import summarize_design_intent
from factory.hybrid_workflow import assess_scale
from factory.previews.render_preview import render_preview
from factory.validators.mesh_validate import validate_mesh

BLENDER_ADAPTATION_VERSION = 1

WORKFLOW_TYPE = "organic_cleanup_workflow"

RECEIPT_FILENAME = "blender_adaptation_receipt.json"
GENERATED_DIRNAME = "generated"
OUTPUT_SUBDIR = Path("generated") / "blender" / "adapted"

EXECUTION_STATUSES = ("not_run", "succeeded", "failed", "blocked")

_SAFETY_BLOCK: dict[str, bool] = {
    "gui_launched": False,
    "network_used": False,
    "slicer_executed": False,
    "gcode_generated": False,
    "printer_contacted": False,
    "meshy_contacted": False,
    "original_artifact_modified": False,
    "automatic_print_allowed": False,
    "automatic_execution_allowed": False,
}


def build_safety_block() -> dict[str, bool]:
    """Static, hardcoded invariants - never per-call telemetry. Mirrors
    every other `_SAFETY_BLOCK`-shaped helper in this repo
    (`factory.blender_adapter.build_blender_report()`,
    `factory.tool_qualification.build_qualification_report()`)."""
    return dict(_SAFETY_BLOCK)


def _file_fingerprint(path: Path) -> str:
    """`sha256:<hex digest>` - the exact convention already established by
    `factory.export_pipeline`/`factory.meshy_live_adapter`/
    `factory.blender_adapter` for every other artifact fingerprint in this
    repo. Never re-derived differently here."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _infer_source_engine(artifact_path: Path) -> str:
    """Advisory-only heuristic from the artifact's own path, mirroring
    `factory.hybrid_workflow`'s own advisory-only artifact-type reads -
    never a claim of certainty. `organic_cleanup_workflow` is designed for
    a Meshy-origin artifact (the motivating piggy-bank case), but a CAD-
    origin mesh needing scale correction is not refused either."""
    parts = set(Path(artifact_path).parts)
    if "meshy" in parts:
        return "meshy"
    if "blender" in parts:
        return "blender_adapted"
    if "cad" in parts or "stl" in parts:
        return "cad"
    return "unknown"


def _output_artifact_path(project_dir: Path, input_stl_path: Path) -> Path:
    """Deterministic, Factory-computed child-artifact path - never a
    caller-supplied output path (see docs/blender-adaptation.md "no
    arbitrary output paths"). `<project>/generated/blender/adapted/<stem>_adapted.stl`
    - a sibling of `generated/meshy/processed/` in spirit, never mixed
    into `stl/`/`renders/` (docs/file-lifecycle.md's Phase 45 note)."""
    return Path(project_dir) / OUTPUT_SUBDIR / f"{Path(input_stl_path).stem}_adapted.stl"


def _receipt_path(project_dir: Path) -> Path:
    return Path(project_dir) / GENERATED_DIRNAME / RECEIPT_FILENAME


def read_blender_adaptation_receipt(project_dir: Path) -> dict[str, Any] | None:
    """Read-only: the receipt if a real `organic_cleanup_workflow`
    execution has ever completed for this project, else `None`. Never
    writes, never triggers execution."""
    receipt_path = _receipt_path(project_dir)
    if not receipt_path.is_file():
        return None
    try:
        return project_store.load_json(receipt_path)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Planning - pure, read-only. Never invokes Blender, never writes a file,
# regardless of any argument.
# ---------------------------------------------------------------------------


def build_adaptation_execution_plan(
    artifact_path: Path, *, target_max_dimension_mm: float | None = None
) -> dict[str, Any]:
    """The full, deterministic, read-only execution plan for adapting one
    artifact via `organic_cleanup_workflow`. Never launches Blender, never
    writes anything. `automatic_execution_allowed` is always `False`.

    `target_max_dimension_mm`, if given, is the human-specified largest
    bounding-box dimension (mm) the adapted artifact should have -
    `organic_cleanup_workflow` only ever applies one *uniform* scale
    factor (never anisotropic per-axis scaling), computed as
    `target_max_dimension_mm / current_largest_dimension_mm`. If omitted,
    the plan still reports `scale_assessment` (reusing
    `factory.hybrid_workflow.assess_scale()` against whatever
    `design_intent` size evidence already exists) but cannot compute a
    `scale_factor`, and is never `execution_allowed`.
    """
    # Resolved up front so every path this function derives/returns
    # (input_artifact, project, output_artifact, and the receipt's later
    # project-relative fingerprints) is consistently absolute - never a
    # mix of resolved and cwd-relative forms that would make
    # `project_store_relative()`'s `relative_to()` silently fall back to
    # an unstripped path.
    artifact_path = Path(artifact_path).resolve()
    project_dir = project_store.find_project_root(artifact_path)
    # `issues` is shown to a human in full (blocking and advisory alike);
    # `blockers` is the strict subset that actually prevents execution -
    # never conflated, so an advisory-only note (e.g. a WARN validation
    # status, or no design_intent on file) never silently blocks a plan
    # that is otherwise perfectly executable.
    issues: list[str] = []
    blockers: list[str] = []

    validation_report: dict[str, Any] | None = None
    if artifact_path.is_file():
        try:
            validation_report = validate_mesh(artifact_path)
        except Exception as exc:  # never let a re-validation crash block plan generation
            issues.append(f"Could not validate artifact: {type(exc).__name__}: {exc}")
    else:
        blockers.append(f"input artifact does not exist: {artifact_path}")

    mesh_stats = (validation_report or {}).get("mesh_stats") or {}
    if validation_report and validation_report.get("overall_status") == "FAIL":
        blockers.append("Factory mesh validation reported FAIL for the input artifact - do not proceed to adaptation until this is fixed.")
    elif validation_report and validation_report.get("overall_status") == "WARN":
        issues.append("Factory mesh validation reported WARN - review before adaptation (see current_state.validation_overall_status).")

    use_case = None
    max_size_mm = None
    if project_dir is not None:
        brief_path = project_dir / "brief.json"
        design_intent = summarize_design_intent(brief_path) if brief_path.is_file() else None
        if design_intent is not None:
            use_case = design_intent.get("use_case")
            max_size_mm = design_intent.get("max_size_mm")
        else:
            issues.append("No design_intent recorded for this project - scale plausibility is advisory-only until a human provides one.")

    scale_assessment = assess_scale(mesh_stats, use_case=use_case, design_intent_max_size_mm=max_size_mm)

    current = mesh_stats.get("bounding_box_mm") or {}
    largest_current_mm = max(current.values()) if current else None
    scale_factor: float | None = None
    if target_max_dimension_mm is not None and largest_current_mm:
        scale_factor = round(target_max_dimension_mm / largest_current_mm, 6)

    if project_dir is None:
        blockers.append(
            "artifact does not live under projects/<slug>/ - a project directory is required to write an "
            "adapted child artifact and receipt; this plan cannot be executed."
        )
        output_artifact_path = None
        gate_plan: dict[str, Any] = {
            "workflow": WORKFLOW_TYPE,
            "gate_status": "not_evaluated",
            "blockers": [],
            "warnings": [],
            "execution_allowed": False,
            "blender_path": None,
            "blender_version": "unknown",
        }
    else:
        output_artifact_path = _output_artifact_path(project_dir, artifact_path)
        gate_plan = blender_gate.plan_organic_cleanup_execution(
            input_stl_path=artifact_path, output_stl_path=output_artifact_path, scale_factor=scale_factor
        )
        blockers.extend(gate_plan["blockers"])

    issues = blockers + issues

    return {
        "blender_adaptation_version": BLENDER_ADAPTATION_VERSION,
        "input_artifact": str(artifact_path),
        "input_artifact_exists": artifact_path.is_file(),
        "project": str(project_dir) if project_dir else None,
        "source_engine": _infer_source_engine(artifact_path),
        "workflow_type": WORKFLOW_TYPE,
        "blender_gate_status": gate_plan["gate_status"],
        "adaptation_operations": list(blender_gate.ORGANIC_CLEANUP_OPERATIONS),
        "current_dimensions_mm": current,
        "scale_assessment": scale_assessment,
        "target_dimensions": {
            "target_max_dimension_mm": target_max_dimension_mm,
            "note": (
                "organic_cleanup_workflow applies one uniform scale factor only - a single target "
                "max dimension, never independent per-axis targets."
            ),
        },
        "proposed_scale_factor": scale_factor,
        "requires_human_confirmation": True,
        "output_artifact": str(output_artifact_path) if output_artifact_path else None,
        "validation_plan": {"validator": "factory.validators.mesh_validate.validate_mesh", "reused": True},
        "preview_plan": {"renderer": "factory.previews.render_preview.render_preview", "reused": True},
        "issues_found": issues,
        "blockers": blockers,
        "warnings": gate_plan["warnings"],
        "execution_allowed": gate_plan["execution_allowed"] and not blockers,
        "dry_run": True,
        "automatic_execution_allowed": False,
        "no_automatic_print": True,
    }


def build_adaptation_execution_plan_for_path(path: Path, *, target_max_dimension_mm: float | None = None) -> dict[str, Any]:
    """Convenience entry point `factory blender-adapt plan <artifact>` uses."""
    return build_adaptation_execution_plan(path, target_max_dimension_mm=target_max_dimension_mm)


# ---------------------------------------------------------------------------
# Execution - the only real-Blender-invoking path in this module (via
# factory.blender_adapter, never a subprocess call of its own). Only ever
# runs when every gate below passes; nothing is cached or trusted from a
# prior call.
# ---------------------------------------------------------------------------


def run_organic_cleanup_workflow(
    artifact_path: Path, *, target_max_dimension_mm: float, confirm: bool = False, confirmed_by: str | None = None
) -> dict[str, Any]:
    """The gated `organic_cleanup_workflow` execution entry point. Requires,
    every single call, freshly re-checked, nothing cached:

    1. A valid adaptation plan (`build_adaptation_execution_plan()` - no
       `issues_found`, `execution_allowed`).
    2. Blender's own gate (`factory.blender_gate.evaluate_blender_execution_gate()`)
       detected, plus a **fresh** full fixture-qualification proof
       (`factory.blender_adapter.qualify_blender_adapter(confirm_fixture=True)`
       reaching `adapter_qualification_status == "qualified"`) - proving
       the headless/fixture/validate/preview/cleanup pipeline actually
       works on this exact call, immediately before touching the real
       artifact. Nothing about a prior qualification run is ever trusted.
    3. `confirm=True` - explicit, per-invocation human confirmation.
       There is no standing "approved" state this repo persists anywhere.
    4. Output path approval - the output path is always the one
       deterministic, Factory-computed child-artifact path
       (`_output_artifact_path()`); this function never accepts an
       arbitrary caller-supplied output path, and refuses to overwrite an
       existing file at that path.

    Returns a result dict; writes `generated/blender_adaptation_receipt.json`
    and the adapted child STL under `generated/blender/adapted/` only on
    `organic_cleanup_status == "succeeded"`. The original input artifact is
    never modified, moved, or deleted.
    """
    start = time.monotonic()
    plan = build_adaptation_execution_plan(artifact_path, target_max_dimension_mm=target_max_dimension_mm)

    def _blocked(reason: str) -> dict[str, Any]:
        return {
            "blender_adaptation_version": BLENDER_ADAPTATION_VERSION,
            "workflow_type": WORKFLOW_TYPE,
            "organic_cleanup_status": "blocked",
            "plan": plan,
            "errors": [reason],
            "warnings": [],
            "fixture_qualification": None,
            "receipt": None,
            "receipt_path": None,
            "output_artifact": None,
            "human_confirmed": confirm,
            "automatic_execution_allowed": False,
            "no_automatic_print": True,
            "duration_ms": round((time.monotonic() - start) * 1000, 1),
        }

    if plan["blockers"] or not plan["execution_allowed"]:
        return _blocked("adaptation plan is not execution-allowed - see plan.blockers")
    if not confirm:
        return _blocked("Pass --confirm to actually execute this planned, gate-checked adaptation.")

    project_dir = Path(plan["project"])
    output_artifact_path = Path(plan["output_artifact"])
    scale_factor = plan["proposed_scale_factor"]

    gate = blender_gate.evaluate_blender_execution_gate()
    if not gate["detected"]:
        return _blocked("Blender not detected locally - see `factory blender inspect`.")

    # Fresh, never-cached fixture-qualification proof, immediately before
    # touching the real artifact - see docstring point 2 above.
    qualification = blender_adapter.qualify_blender_adapter(confirm_fixture=True)
    if qualification["adapter_qualification_status"] != "qualified":
        result = _blocked(
            "Fresh Blender fixture-qualification proof did not reach 'qualified' - refusing to run "
            "organic_cleanup_workflow against a real artifact. Run `factory blender qualify "
            "--confirm-fixture --verbose` to see why."
        )
        result["fixture_qualification"] = qualification
        return result

    execution = blender_adapter.run_organic_cleanup_workflow(
        gate["detected_path"],
        input_stl_path=Path(plan["input_artifact"]),
        final_output_path=output_artifact_path,
        scale_factor=scale_factor,
    )

    errors = list(execution["errors"])
    warnings = list(execution["warnings"])
    receipt = None
    receipt_path = None

    if execution["organic_cleanup_status"] == "succeeded":
        try:
            output_report = validate_mesh(output_artifact_path)
            validation_status = output_report.get("overall_status")
            if validation_status == "FAIL":
                errors.append("Factory mesh validation reported FAIL for the adapted output artifact")
        except Exception as exc:
            output_report = None
            validation_status = "FAIL"
            errors.append(f"{type(exc).__name__}: {exc}")

        preview_path = output_artifact_path.with_name(f"{output_artifact_path.stem}_preview.png")
        try:
            preview_result = render_preview(output_artifact_path, preview_path)
            preview_status = preview_result.get("status")
            if preview_status == "FAIL":
                errors.append("Factory preview render failed for the adapted output artifact")
        except Exception as exc:
            preview_status = "FAIL"
            errors.append(f"{type(exc).__name__}: {exc}")

        input_path = Path(plan["input_artifact"])
        receipt = {
            "blender_adaptation_version": BLENDER_ADAPTATION_VERSION,
            "workflow": WORKFLOW_TYPE,
            "input_artifact": project_store_relative(project_dir, input_path),
            "input_hash": _file_fingerprint(input_path),
            "output_artifact": project_store_relative(project_dir, output_artifact_path),
            "output_hash": execution.get("output_hash"),
            "blender_version": gate["detected_version"],
            "blender_path": gate["detected_path"],
            "operations": list(blender_gate.ORGANIC_CLEANUP_OPERATIONS),
            "scale_factor_applied": scale_factor,
            "target_max_dimension_mm": target_max_dimension_mm,
            "source_dimensions_mm": plan["current_dimensions_mm"],
            "output_dimensions_mm": (output_report or {}).get("mesh_stats", {}).get("bounding_box_mm"),
            "single_shot_human_confirmation": True,
            "confirmed_by": confirmed_by,
            "fixture_qualification_status": qualification["adapter_qualification_status"],
            "validation_status": validation_status,
            "preview_status": preview_status,
            "started_at": project_store.utc_now_iso(),
            "finished_at": project_store.utc_now_iso(),
            "human_review_state": "required",
            "project_execution_approved": False,
            "automatic_print_allowed": False,
            "no_automatic_print": True,
            "warnings": warnings,
        }
        receipt_path = _receipt_path(project_dir)
        if receipt_path.exists():
            errors.append(f"refusing to overwrite an existing receipt at {receipt_path} - a project may only run this workflow once per input artifact via this receipt path")
        else:
            project_store.save_json(receipt_path, receipt)

    status = "succeeded" if (execution["organic_cleanup_status"] == "succeeded" and not any("refusing to overwrite" in e for e in errors) and receipt_path and receipt_path.is_file()) else "failed"

    return {
        "blender_adaptation_version": BLENDER_ADAPTATION_VERSION,
        "workflow_type": WORKFLOW_TYPE,
        "organic_cleanup_status": status,
        "plan": plan,
        "execution": execution,
        "fixture_qualification": qualification,
        "errors": errors,
        "warnings": warnings,
        "receipt": receipt,
        "receipt_path": str(receipt_path) if receipt_path and receipt_path.is_file() else None,
        "output_artifact": str(output_artifact_path) if status == "succeeded" else None,
        "human_confirmed": True,
        "automatic_execution_allowed": False,
        "no_automatic_print": True,
        "duration_ms": round((time.monotonic() - start) * 1000, 1),
    }


def project_store_relative(project_dir: Path, path: Path) -> str:
    """Project-relative path string, falling back to the absolute path if
    `path` isn't actually under `project_dir` - mirrors
    `factory.export_pipeline._relative_path()`'s exact fallback behavior."""
    try:
        return Path(path).relative_to(Path(project_dir)).as_posix()
    except ValueError:
        return Path(path).as_posix()


# ---------------------------------------------------------------------------
# Preview Board summary - wired in at the aggregation point
# (factory.preview_board.gather_board_data()), never inside
# factory.project_health/project_inspection. See the standing
# "Aggregation Layer Convention" in docs/architecture.md.
# ---------------------------------------------------------------------------


def summarize_blender_adaptation(project_dir: Path) -> dict[str, Any]:
    """Compact, read-only summary for the Preview Board. Never writes,
    never invokes Blender or a subprocess of any kind - reads the receipt
    if one already exists, nothing more."""
    receipt = read_blender_adaptation_receipt(project_dir)
    if receipt is None:
        return {
            "adaptation_available": False,
            "workflow": None,
            "output_artifact": None,
            "validation_status": None,
            "human_confirmed": None,
        }
    return {
        "adaptation_available": True,
        "workflow": receipt.get("workflow"),
        "output_artifact": receipt.get("output_artifact"),
        "validation_status": receipt.get("validation_status"),
        "human_confirmed": receipt.get("single_shot_human_confirmation"),
    }

"""Phase 50: CAD Augmentation Execution Gate & Organic-Mechanical Hybrid
Workflow.

The controlled bridge from an already-adapted organic artifact to a
manufacturing-ready hybrid product:

    Blender adapted organic artifact -> CAD augmentation -> Factory
    validation -> Preview -> Human review

**This is the first module in this repo that executes real CAD
generation *and* export against a real project artifact in one gated
step.** Phase 49 (`docs/blender-adaptation.md`) proved a Blender
adaptation step can be safely, narrowly executed against a real
artifact; this phase proves the same discipline extends one step further
- adding an engineered functional feature (a coin slot, a mounting/base
interface) next to an AI-generated organic body, never *replacing* or
*merging into* it.

    AI concept        != engineering design
    CAD output         != manufacturing approved
    Validation           != human approval
    Human approval         != print approval
    Automatic printing remains impossible.

## Never a fused mesh - a second, separate part

`factory.validators.multipart_check`'s own standing policy (Phase 0/1,
`docs/slicer-review-workflow.md`) is: **prefer separate aligned STL files
sharing one origin over a single fused mesh for multi-color/multi-
material work.** This phase follows that exactly. `organic_mechanical_augmentation`
never booleans, merges, or otherwise combines the organic mesh's own
triangle data with the newly generated CAD feature - it produces one new,
independent STL (the "mechanical component"), which becomes part of the
same product alongside the existing organic artifact (the "organic
component") the same way every other multi-part project in this repo
already works (`examples/multipart-classroom-sign/`,
`examples/storage-bin-lid/`). This also sidesteps a real, unresolved
technical risk this phase deliberately does not take on: booleaning a
CAD kernel solid against an arbitrary, possibly non-manifold-adjacent,
multi-million-triangle organic mesh is exactly the kind of "automatic
parametric reconstruction"/"complex assembly" this phase's own spec
excludes.

## Why OpenSCAD executes and CadQuery does not

`docs/cad-backends.md` states, repeatedly and unconditionally (not just
"not yet"): **this repo does not import or execute the CadQuery source it
writes** - `factory.cad.cadquery_backend.generate_cadquery()` writes `.py`
source only, and `factory.export_pipeline` itself refuses to run it
(`"manual_export_required"`, regardless of `--confirm-export`). Unlike
`docs/blender-adapter.md`, which explicitly staged "a future real Blender
project-generation phase" that Phase 49 then became, no CadQuery doc
anywhere in this repo stages an analogous future execution phase - the
policy is written as a standing, unconditional rule, not a narrowed-for-
now placeholder. This phase does not relax it. `factory.tool_qualification`'s
own in-process CadQuery capability probe (`cq.Workplane("XY").box(10, 10,
10)`) remains the one, narrow, throwaway-fixture exception it has always
been - never extended here to a real project artifact.

**OpenSCAD, by contrast, already has a complete, safe, tested, bounded
execution path in this repo** (`factory.export_pipeline`, Phase 35) and
is explicitly the right tool for "simple parametric additions" (a coin
slot, mounting holes, a flat base plate - exactly this workflow's scope).
This phase's one real execution therefore routes through OpenSCAD only -
reusing `factory.export_pipeline.run_scad_source_to_stl()` (the one new
function that phase's own module gained), never inventing a second
subprocess-execution mechanism. CadQuery and FreeCAD are still reported
as candidate engines (per `factory.engine_registry`'s own suitability
data) for a human's awareness, but neither is ever executed by this
phase - `recommended_cad_engine` and `cad_operations` never claim
otherwise.

Reuses rather than duplicates:

- `factory.engine_registry.get_tool_registry()` - the one existing source
  of per-tool `mechanical_design_suitability`, exactly like
  `factory.hybrid_workflow._mechanical_augmentation_step()`'s own
  `candidate_tools` list. This module never re-scores a tool's
  suitability itself.
- `factory.export_pipeline.resolve_openscad_executable()` /
  `run_scad_source_to_stl()` - the one existing, bounded OpenSCAD
  execution path. No second subprocess call exists anywhere in this
  module.
- `factory.validators.mesh_validate.validate_mesh()` /
  `factory.previews.render_preview.render_preview()` - the same Factory
  validator/renderer every other mesh in this repo goes through. No
  CAD-specific validator or visual-QA subsystem exists here.
- `factory.blender_adaptation.read_blender_adaptation_receipt()` - to
  describe the organic component's own lineage (workflow, scale factor)
  when the input artifact is itself a Blender-adapted child artifact -
  never a second lineage reader.
- `factory.project_timeline`/`factory.artifact_history` - a completed
  augmentation receipt enters those existing systems additively (one new
  event category, one new path-classification rule), never a second
  lineage/version model.

See `docs/cad-augmentation.md`.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from factory import engine_registry, export_pipeline, project_store
from factory.blender_adaptation import read_blender_adaptation_receipt
from factory.previews.render_preview import render_preview
from factory.validators.mesh_validate import validate_mesh

CAD_AUGMENTATION_VERSION = 1

WORKFLOW_TYPE = "organic_mechanical_augmentation"

RECEIPT_FILENAME = "cad_augmentation_receipt.json"
OUTPUT_SUBDIR = Path("generated") / "cad_augmentation"
FEATURE_FILENAME_TEMPLATE = "{stem}_feature.scad"
OUTPUT_FILENAME_TEMPLATE = "{stem}_feature.stl"

# Fixed, deterministic operation sequence - rendered verbatim in every
# plan a human reviews before confirming. Never repair, remesh, boolean-
# merge with the organic mesh, or any broader CAD use.
CAD_AUGMENTATION_OPERATIONS = ("generate_scad_source", "export_stl")

# The same fixed, small, hand-reviewed candidate list
# `factory.hybrid_workflow._mechanical_augmentation_step()` already uses
# (never re-derived independently) - the tool ids this module will ever
# report as a candidate engine, filtered by `engine_registry`'s own
# `mechanical_design_suitability` field, never re-scored here.
_CAD_TOOL_IDS = ("cadquery", "openscad_stable", "freecad")

# The one tool id this module ever actually executes - see the module
# docstring's "Why OpenSCAD executes and CadQuery does not".
_EXECUTABLE_ENGINE_ID = "openscad_stable"

_SAFETY_BLOCK: dict[str, bool] = {
    "gui_launched": False,
    "network_used": False,
    "slicer_executed": False,
    "gcode_generated": False,
    "printer_contacted": False,
    "meshy_contacted": False,
    "cadquery_executed": False,
    "original_artifact_modified": False,
    "mesh_boolean_merge_performed": False,
    "automatic_print_allowed": False,
    "automatic_execution_allowed": False,
}


def build_safety_block() -> dict[str, bool]:
    """Static, hardcoded invariants - never per-call telemetry. Mirrors
    `factory.blender_adaptation.build_safety_block()`'s identical
    convention."""
    return dict(_SAFETY_BLOCK)


def _file_fingerprint(path: Path) -> str:
    """`sha256:<hex digest>` - the exact convention already established by
    `factory.export_pipeline`/`factory.blender_adaptation` for every other
    artifact fingerprint in this repo."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def project_store_relative(project_dir: Path, path: Path) -> str:
    """Project-relative path string, falling back to the absolute path if
    `path` isn't actually under `project_dir` - mirrors
    `factory.blender_adaptation.project_store_relative()`'s identical
    fallback behavior."""
    try:
        return Path(path).relative_to(Path(project_dir)).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _output_paths(project_dir: Path, input_stl_path: Path) -> tuple[Path, Path]:
    """Deterministic, Factory-computed feature-source/output paths - never
    caller-supplied. `<project>/generated/cad_augmentation/<stem>_feature.scad`
    and `.stl` - a sibling of `generated/blender/adapted/` in spirit,
    never mixed into `cad/`/`stl/` as if it were the general-purpose
    `factory generate-openscad` pipeline's own output."""
    stem = Path(input_stl_path).stem
    out_dir = Path(project_dir) / OUTPUT_SUBDIR
    return out_dir / FEATURE_FILENAME_TEMPLATE.format(stem=stem), out_dir / OUTPUT_FILENAME_TEMPLATE.format(stem=stem)


def _receipt_path(project_dir: Path) -> Path:
    return Path(project_dir) / "generated" / RECEIPT_FILENAME


def read_cad_augmentation_receipt(project_dir: Path) -> dict[str, Any] | None:
    """Read-only: the receipt if a real `organic_mechanical_augmentation`
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
# CAD routing - reuses engine_registry directly; never a second selector.
# ---------------------------------------------------------------------------


def _select_cad_engine() -> dict[str, Any]:
    """Candidate engines (mechanical_design_suitability == "high", the
    same fixed tool-id list and registry field
    `factory.hybrid_workflow._mechanical_augmentation_step()` already
    uses) and the single engine this module will actually execute.
    `recommended_cad_engine` never claims a candidate other than
    `_EXECUTABLE_ENGINE_ID` will be executed - CadQuery/FreeCAD stay
    reported, never run. Never selects all of them."""
    registry = engine_registry.get_tool_registry()
    candidates = sorted(
        tool_id
        for tool_id in _CAD_TOOL_IDS
        if tool_id in registry and registry[tool_id].get("mechanical_design_suitability") == "high"
    )
    executable = _EXECUTABLE_ENGINE_ID if _EXECUTABLE_ENGINE_ID in candidates else None
    return {
        "candidate_engines": candidates,
        "recommended_cad_engine": executable,
        "rationale": (
            "OpenSCAD is the only candidate with an existing, bounded, already-tested local "
            "execution path in this repo (factory.export_pipeline) - CadQuery is never executed "
            "(docs/cad-backends.md's standing policy) and FreeCAD has no execution path at all "
            "(metadata_only, cli_available=False). See docs/cad-augmentation.md."
            if executable
            else "openscad_stable did not qualify as a high-mechanical-design-suitability candidate "
            "in factory.engine_registry - this workflow has no executable engine right now."
        ),
    }


def _organic_component_info(artifact_path: Path, project_dir: Path | None) -> dict[str, Any]:
    """Read-only description of the input (organic) artifact - reuses
    `factory.blender_adaptation.read_blender_adaptation_receipt()` when
    the artifact is itself a Blender-adapted child artifact, never a
    second lineage reader."""
    info: dict[str, Any] = {
        "artifact_path": str(artifact_path),
        "is_blender_adapted": False,
        "blender_workflow": None,
        "blender_scale_factor_applied": None,
    }
    if project_dir is None:
        return info
    receipt = read_blender_adaptation_receipt(project_dir)
    if receipt is None:
        return info
    output_rel = receipt.get("output_artifact")
    try:
        artifact_rel = project_store_relative(project_dir, artifact_path)
    except Exception:
        artifact_rel = None
    if output_rel and artifact_rel and output_rel == artifact_rel:
        info["is_blender_adapted"] = True
        info["blender_workflow"] = receipt.get("workflow")
        info["blender_scale_factor_applied"] = receipt.get("scale_factor_applied")
    return info


# ---------------------------------------------------------------------------
# Parameter model - explicit only, never guessed.
# ---------------------------------------------------------------------------

_BASE_PARAM_NAMES = ("base_width_mm", "base_length_mm", "base_height_mm")
_COIN_SLOT_PARAM_NAMES = ("coin_slot_width_mm", "coin_slot_length_mm", "coin_slot_depth_mm")
_MOUNTING_PARAM_NAMES = ("mounting_hole_diameter_mm",)


def _required_parameters(params: dict[str, float | None]) -> dict[str, Any]:
    """Every critical dimension this workflow could use, whether or not it
    was actually requested for this call - each entry records `required`
    (is this parameter mandatory given what else was requested),
    `provided` (was a value actually given), and `value`. Never a guessed
    default for a `required` parameter; `requires_human_input` lists
    exactly the required-but-missing ones."""
    coin_slot_requested = any(params.get(name) is not None for name in _COIN_SLOT_PARAM_NAMES)
    mounting_requested = any(params.get(name) is not None for name in _MOUNTING_PARAM_NAMES)

    entries: list[dict[str, Any]] = []
    for name in _BASE_PARAM_NAMES:
        entries.append({"name": name, "required": True, "provided": params.get(name) is not None, "value": params.get(name)})
    for name in _COIN_SLOT_PARAM_NAMES:
        entries.append(
            {"name": name, "required": coin_slot_requested, "provided": params.get(name) is not None, "value": params.get(name)}
        )
    for name in _MOUNTING_PARAM_NAMES:
        entries.append(
            {"name": name, "required": False, "provided": params.get(name) is not None, "value": params.get(name)}
        )

    requires_human_input = [e["name"] for e in entries if e["required"] and not e["provided"]]

    return {
        "parameters": entries,
        "coin_slot_requested": coin_slot_requested,
        "mounting_holes_requested": mounting_requested,
        "requires_human_input": requires_human_input,
        "all_required_provided": not requires_human_input,
    }


# ---------------------------------------------------------------------------
# OpenSCAD feature-source generation - pure text, never writes, never
# invokes OpenSCAD. Private to this module (not part of `factory
# generate-openscad`'s general-purpose template list in
# factory.openscad.templates - this is a fixed, single-purpose template
# tied to one project artifact, not a project-scaffolding template).
# ---------------------------------------------------------------------------


def _render_functional_feature_scad(
    *,
    base_width_mm: float,
    base_length_mm: float,
    base_height_mm: float,
    coin_slot_width_mm: float | None,
    coin_slot_length_mm: float | None,
    coin_slot_depth_mm: float | None,
    coin_slot_position_x_mm: float | None,
    coin_slot_position_y_mm: float | None,
    mounting_hole_diameter_mm: float | None,
    mounting_hole_margin_mm: float,
) -> str:
    """Return OpenSCAD source text for one parametric functional-feature
    base plate - a flat base with an optional coin slot and optional
    4-corner mounting holes. Never executed here; never writes a file.
    Mirrors `factory.cad.cadquery_backend._mechanical_plate_source()`'s
    own parametrization style (box + optional cutouts), reimplemented in
    OpenSCAD since this phase never executes CadQuery."""
    coin_slot = coin_slot_width_mm is not None and coin_slot_length_mm is not None and coin_slot_depth_mm is not None
    mounting_holes = mounting_hole_diameter_mm is not None
    slot_x = coin_slot_position_x_mm if coin_slot_position_x_mm is not None else base_width_mm / 2
    slot_y = coin_slot_position_y_mm if coin_slot_position_y_mm is not None else base_length_mm / 2

    lines = [
        "// functional_feature.scad",
        "// Parametric functional base plate generated by ai-3d-factory",
        "// (factory.cad_augmentation, organic_mechanical_augmentation workflow).",
        "// This is a mechanical AUGMENTATION part, never a fused/merged copy of the",
        "// organic body - print/assemble alongside the organic artifact as a",
        "// separate, aligned part sharing the same origin. See docs/cad-augmentation.md.",
        "// Geometry sanity check passed does not mean print-ready - human slicer",
        "// review is still required. See AGENT.md.",
        "",
        "// ---- Parameters (all in millimeters) ----",
        f"base_width_mm = {base_width_mm!r};",
        f"base_length_mm = {base_length_mm!r};",
        f"base_height_mm = {base_height_mm!r};",
        f"coin_slot = {'true' if coin_slot else 'false'};",
        f"coin_slot_width_mm = {(coin_slot_width_mm or 0)!r};",
        f"coin_slot_length_mm = {(coin_slot_length_mm or 0)!r};",
        f"coin_slot_depth_mm = {(coin_slot_depth_mm or 0)!r};",
        f"coin_slot_position_x_mm = {slot_x!r};  // centered on base_width_mm if not explicitly given",
        f"coin_slot_position_y_mm = {slot_y!r};  // centered on base_length_mm if not explicitly given",
        f"mounting_holes = {'true' if mounting_holes else 'false'};",
        f"mounting_hole_diameter_mm = {(mounting_hole_diameter_mm or 0)!r};",
        f"mounting_hole_margin_mm = {mounting_hole_margin_mm!r};  // distance of hole centers from each edge",
        "",
        "module functional_base_plate() {",
        "    difference() {",
        "        cube([base_width_mm, base_length_mm, base_height_mm]);",
        "",
        "        if (coin_slot) {",
        "            translate([",
        "                coin_slot_position_x_mm - coin_slot_width_mm / 2,",
        "                coin_slot_position_y_mm - coin_slot_length_mm / 2,",
        "                base_height_mm - coin_slot_depth_mm",
        "            ])",
        "                cube([coin_slot_width_mm, coin_slot_length_mm, coin_slot_depth_mm + 1]);",
        "        }",
        "",
        "        if (mounting_holes) {",
        "            for (pos = [",
        "                [mounting_hole_margin_mm, mounting_hole_margin_mm],",
        "                [base_width_mm - mounting_hole_margin_mm, mounting_hole_margin_mm],",
        "                [mounting_hole_margin_mm, base_length_mm - mounting_hole_margin_mm],",
        "                [base_width_mm - mounting_hole_margin_mm, base_length_mm - mounting_hole_margin_mm]",
        "            ]) {",
        "                translate([pos[0], pos[1], -1])",
        "                    cylinder(h = base_height_mm + 2, d = mounting_hole_diameter_mm, $fn = 32);",
        "            }",
        "        }",
        "    }",
        "}",
        "",
        "functional_base_plate();",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Planning - pure, read-only. Never invokes OpenSCAD, never writes a file,
# regardless of any argument.
# ---------------------------------------------------------------------------


def build_augmentation_plan(artifact_path: Path, **params: float | None) -> dict[str, Any]:
    """The full, deterministic, read-only augmentation plan for one
    artifact via `organic_mechanical_augmentation`. Never generates CAD
    source, never invokes OpenSCAD, never writes anything.
    `automatic_execution_allowed` is always `False`.

    `params` accepts `base_width_mm`/`base_length_mm`/`base_height_mm`
    (required), `coin_slot_width_mm`/`coin_slot_length_mm`/
    `coin_slot_depth_mm`/`coin_slot_position_x_mm`/`coin_slot_position_y_mm`
    (all optional; the first three become required together the moment
    any one of them is given), and `mounting_hole_diameter_mm`/
    `mounting_hole_margin_mm` (optional, `mounting_hole_margin_mm`
    defaults to 8.0mm - a placement convenience, never a critical
    dimension - mirroring `factory.cad.cadquery_backend`'s identical
    default).
    """
    artifact_path = Path(artifact_path).resolve()
    project_dir = project_store.find_project_root(artifact_path)
    params = dict(params)
    params.setdefault("mounting_hole_margin_mm", 8.0)

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

    if validation_report and validation_report.get("overall_status") == "FAIL":
        blockers.append("Factory mesh validation reported FAIL for the input (organic) artifact - do not proceed to augmentation until this is fixed.")
    elif validation_report and validation_report.get("overall_status") == "WARN":
        issues.append("Factory mesh validation reported WARN for the input (organic) artifact - review before augmentation.")

    if project_dir is None:
        blockers.append(
            "artifact does not live under projects/<slug>/ - a project directory is required to write "
            "an augmented feature artifact and receipt; this plan cannot be executed."
        )
        feature_scad_path = None
        output_stl_path = None
    else:
        feature_scad_path, output_stl_path = _output_paths(project_dir, artifact_path)
        if output_stl_path.exists():
            blockers.append(f"refusing to overwrite an existing file at the planned output path: {output_stl_path}")

    routing = _select_cad_engine()
    if routing["recommended_cad_engine"] is None:
        blockers.append("no executable CAD engine available for this workflow - see routing.rationale")

    param_model = _required_parameters(params)
    if param_model["requires_human_input"]:
        blockers.append(f"missing required parameter(s): {', '.join(param_model['requires_human_input'])}")

    organic_component = _organic_component_info(artifact_path, project_dir)
    mesh_stats = (validation_report or {}).get("mesh_stats") or {}
    organic_component["mesh_stats"] = mesh_stats
    organic_component["validation_overall_status"] = (validation_report or {}).get("overall_status")

    mechanical_component = {
        "coin_slot_requested": param_model["coin_slot_requested"],
        "mounting_holes_requested": param_model["mounting_holes_requested"],
        "parameters": param_model["parameters"],
    }

    human_confirmations = [
        "Confirm every required parameter's numeric value is correct for this specific artifact - none are guessed.",
        "Confirm the recommended_cad_engine and cad_operations before requesting execution.",
        "Approve the generated feature part after reviewing its own validation/preview - a Blender/Meshy-adjacent"
        " part passing geometry validation is never the same as it being print-ready or functionally correct.",
    ]

    return {
        "cad_augmentation_version": CAD_AUGMENTATION_VERSION,
        "input_artifact": str(artifact_path),
        "input_artifact_exists": artifact_path.is_file(),
        "project": str(project_dir) if project_dir else None,
        "workflow_type": WORKFLOW_TYPE,
        "organic_component": organic_component,
        "mechanical_component": mechanical_component,
        "recommended_cad_engine": routing["recommended_cad_engine"],
        "candidate_engines": routing["candidate_engines"],
        "engine_rationale": routing["rationale"],
        "cad_operations": list(CAD_AUGMENTATION_OPERATIONS),
        "required_parameters": param_model["parameters"],
        "requires_human_input": param_model["requires_human_input"],
        "human_confirmations": human_confirmations,
        "output_feature_source": str(feature_scad_path) if feature_scad_path else None,
        "output_artifact": str(output_stl_path) if output_stl_path else None,
        "validation_plan": {"validator": "factory.validators.mesh_validate.validate_mesh", "reused": True},
        "preview_plan": {"renderer": "factory.previews.render_preview.render_preview", "reused": True},
        "issues_found": blockers + issues,
        "blockers": blockers,
        "execution_allowed": not blockers,
        "dry_run": True,
        "automatic_execution_allowed": False,
        "no_automatic_print": True,
    }


def build_augmentation_plan_for_path(path: Path, **params: float | None) -> dict[str, Any]:
    """Convenience entry point `factory cad-augment plan <artifact>` uses."""
    return build_augmentation_plan(path, **params)


# ---------------------------------------------------------------------------
# Execution - the only OpenSCAD-invoking path in this module (via
# factory.export_pipeline, never a subprocess call of its own). Only ever
# runs when every gate below passes; nothing is cached or trusted from a
# prior call.
# ---------------------------------------------------------------------------


def run_organic_mechanical_augmentation(
    artifact_path: Path, *, confirm: bool = False, confirmed_by: str | None = None, **params: float | None
) -> dict[str, Any]:
    """The gated `organic_mechanical_augmentation` execution entry point.
    Requires, every single call, freshly re-checked, nothing cached:

    1. A valid augmentation plan (`build_augmentation_plan()` - no
       `blockers`, `execution_allowed`) - every required parameter
       provided, a resolvable project, an executable CAD engine, a
       non-colliding output path.
    2. `confirm=True` - explicit, per-invocation human confirmation.
    3. Output path approval - the feature source and output STL paths are
       always the two deterministic, Factory-computed paths under
       `generated/cad_augmentation/`; this function never accepts an
       arbitrary caller-supplied output path, and refuses to overwrite an
       existing file at either.

    Writes `generated/cad_augmentation_receipt.json` and the generated
    `.scad`/`.stl` pair only on success. The original (organic) input
    artifact is never modified, moved, or deleted; no mesh boolean-merge
    of any kind is ever performed.
    """
    start = time.monotonic()
    plan = build_augmentation_plan(artifact_path, **params)

    def _blocked(reason: str) -> dict[str, Any]:
        return {
            "cad_augmentation_version": CAD_AUGMENTATION_VERSION,
            "workflow_type": WORKFLOW_TYPE,
            "augmentation_status": "blocked",
            "plan": plan,
            "errors": [reason],
            "receipt": None,
            "receipt_path": None,
            "output_artifact": None,
            "human_confirmed": confirm,
            "automatic_execution_allowed": False,
            "no_automatic_print": True,
            "duration_ms": round((time.monotonic() - start) * 1000, 1),
        }

    if plan["blockers"] or not plan["execution_allowed"]:
        return _blocked("augmentation plan is not execution-allowed - see plan.blockers")
    if not confirm:
        return _blocked("Pass --confirm to actually execute this planned, parameter-checked augmentation.")

    project_dir = Path(plan["project"])
    input_path = Path(plan["input_artifact"])
    feature_scad_path = Path(plan["output_feature_source"])
    output_stl_path = Path(plan["output_artifact"])

    scad_source = _render_functional_feature_scad(
        base_width_mm=params["base_width_mm"],
        base_length_mm=params["base_length_mm"],
        base_height_mm=params["base_height_mm"],
        coin_slot_width_mm=params.get("coin_slot_width_mm"),
        coin_slot_length_mm=params.get("coin_slot_length_mm"),
        coin_slot_depth_mm=params.get("coin_slot_depth_mm"),
        coin_slot_position_x_mm=params.get("coin_slot_position_x_mm"),
        coin_slot_position_y_mm=params.get("coin_slot_position_y_mm"),
        mounting_hole_diameter_mm=params.get("mounting_hole_diameter_mm"),
        mounting_hole_margin_mm=params.get("mounting_hole_margin_mm", 8.0),
    )
    feature_scad_path.parent.mkdir(parents=True, exist_ok=True)
    if feature_scad_path.exists():
        return _blocked(f"refusing to overwrite an existing file at {feature_scad_path}")
    feature_scad_path.write_text(scad_source, encoding="utf-8")

    export_result = export_pipeline.run_scad_source_to_stl(feature_scad_path, output_stl_path)

    errors = list(export_result["errors"])
    receipt = None
    receipt_path = None

    if export_result["success"]:
        try:
            output_report = validate_mesh(output_stl_path)
            validation_status = output_report.get("overall_status")
            if validation_status == "FAIL":
                errors.append("Factory mesh validation reported FAIL for the generated feature artifact")
        except Exception as exc:
            output_report = None
            validation_status = "FAIL"
            errors.append(f"{type(exc).__name__}: {exc}")

        preview_path = output_stl_path.with_name(f"{output_stl_path.stem}_preview.png")
        try:
            preview_result = render_preview(output_stl_path, preview_path)
            preview_status = preview_result.get("status")
            if preview_status == "FAIL":
                errors.append("Factory preview render failed for the generated feature artifact")
        except Exception as exc:
            preview_status = "FAIL"
            errors.append(f"{type(exc).__name__}: {exc}")

        receipt = {
            "cad_augmentation_version": CAD_AUGMENTATION_VERSION,
            "workflow": WORKFLOW_TYPE,
            "input_artifact": project_store_relative(project_dir, input_path),
            "input_hash": _file_fingerprint(input_path),
            "feature_source": project_store_relative(project_dir, feature_scad_path),
            "output_artifact": project_store_relative(project_dir, output_stl_path),
            "output_hash": export_result.get("output_fingerprint"),
            "cad_engine": "openscad_stable",
            "cad_engine_version": export_result.get("export_tool_version"),
            "operations": list(CAD_AUGMENTATION_OPERATIONS),
            "parameters": {k: v for k, v in params.items() if v is not None},
            "single_shot_human_confirmation": True,
            "confirmed_by": confirmed_by,
            "validation_status": validation_status,
            "preview_status": preview_status,
            "human_review_state": "required",
            "project_execution_approved": False,
            "automatic_print_allowed": False,
            "no_automatic_print": True,
            "mesh_boolean_merge_performed": False,
            "started_at": export_result.get("started_at"),
            "finished_at": export_result.get("completed_at"),
        }
        receipt_path = _receipt_path(project_dir)
        if receipt_path.exists():
            errors.append(f"refusing to overwrite an existing receipt at {receipt_path}")
        else:
            project_store.save_json(receipt_path, receipt)

    # `receipt_path.is_file()` alone is not proof *this call* wrote it - a
    # stale pre-existing receipt at that same path is also a file, and
    # must never be mistaken for a successful write this call performed
    # (see the "refusing to overwrite an existing receipt" branch above).
    status = "succeeded" if (
        export_result["success"]
        and receipt_path
        and receipt_path.is_file()
        and not any("refusing to overwrite an existing receipt" in e for e in errors)
    ) else "failed"

    return {
        "cad_augmentation_version": CAD_AUGMENTATION_VERSION,
        "workflow_type": WORKFLOW_TYPE,
        "augmentation_status": status,
        "plan": plan,
        "export": export_result,
        "errors": errors,
        "receipt": receipt,
        "receipt_path": str(receipt_path) if receipt_path and receipt_path.is_file() else None,
        "output_artifact": str(output_stl_path) if status == "succeeded" else None,
        "human_confirmed": True,
        "automatic_execution_allowed": False,
        "no_automatic_print": True,
        "duration_ms": round((time.monotonic() - start) * 1000, 1),
    }


# ---------------------------------------------------------------------------
# Preview Board summary - wired in at the aggregation point
# (factory.preview_board.gather_board_data()), never inside
# factory.project_health/project_inspection. See the standing
# "Aggregation Layer Convention" in docs/architecture.md.
# ---------------------------------------------------------------------------


def summarize_cad_augmentation(project_dir: Path) -> dict[str, Any]:
    """Compact, read-only summary for the Preview Board. Never writes,
    never invokes OpenSCAD or any subprocess of any kind - reads the
    receipt if one already exists, nothing more."""
    receipt = read_cad_augmentation_receipt(project_dir)
    if receipt is None:
        return {
            "augmentation_available": False,
            "workflow": None,
            "output_artifact": None,
            "validation_status": None,
            "human_confirmed": None,
        }
    return {
        "augmentation_available": True,
        "workflow": receipt.get("workflow"),
        "output_artifact": receipt.get("output_artifact"),
        "validation_status": receipt.get("validation_status"),
        "human_confirmed": receipt.get("single_shot_human_confirmation"),
    }

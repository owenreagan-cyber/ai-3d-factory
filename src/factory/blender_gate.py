"""Phase 45: Blender Local Execution Gate.

Read-only permission/readiness/dry-run planning for the first controlled
local Blender execution path. **This module never launches Blender and
never calls `subprocess`** - see `factory.blender_adapter` for the
bounded execution layer this module gates and plans for.

    specialized probes -> factory.engine_registry -> factory.tool_qualification
        -> factory.blender_gate -> factory.blender_adapter -> CLI

The locked safety progression this phase implements (see
`docs/blender-adapter.md`):

    Detected -> Metadata Qualified -> Headless Runtime Qualified ->
    Fixture Execution Qualified -> Adapter Qualified ->
    Project Execution Eligible -> Explicit Human Confirmation ->
    Actual Project Execution

This module (and `factory.blender_adapter`) can reach, at most, "Adapter
Qualified" for exactly one narrow, Factory-owned workflow
(`fixture_organic_model`) - never further. "Project Execution Eligible"
and everything after it remain entirely unimplemented; nothing in this
phase makes real project generation possible, and
`project_execution_approved` is hardcoded `False` everywhere a result
carries that field.

Reuses rather than duplicates:

- `factory.engine_registry.probe_all_tools()` (Phase 43) - Blender's own
  `detected`/`detected_path` (the `.app` bundle directory)/
  `detected_version` (an `Info.plist` read, never a subprocess). This
  module never re-implements that detection; it only resolves the actual
  executable *inside* the bundle (`Contents/MacOS/Blender` on macOS) from
  the already-detected bundle path - itself a read-only `Path.is_file()`
  check, never a launch.
- `factory.future_local_tools.load_future_local_tools()` (Phase 21) - the
  existing `config/future_local_tools.json` gate config. This module
  never invents a second gate config; it reads the same one
  `factory check-local-tools` already reports.

See `docs/blender-adapter.md` for the full gate-checklist reconciliation
and `docs/blender-local-track.md` for the original (still standing,
now-amended) required-gates checklist this phase's own checklist is
mapped against.

**Phase 49 addendum:** this module is additively extended with exactly
one more supported workflow, `organic_cleanup_workflow` - the first, and
this phase's only, real *project*-artifact Blender workflow (Meshy/CAD-
origin STL in, uniform-scale-adapted STL out). `plan_organic_cleanup_execution()`
below is pure planning - like `plan_blender_fixture_execution()`, it never
launches Blender. The real, gated execution path lives in
`factory.blender_adaptation` (which reuses `evaluate_blender_execution_gate()`
verbatim rather than inventing a second permission system) and
`factory.blender_adapter.run_organic_cleanup_workflow()` (the one
additional bounded subprocess call this phase adds - `blender_adapter.py`
remains the only module in this repo that ever passes Blender to
`subprocess`). See `docs/blender-adaptation.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import engine_registry, future_local_tools, project_store

# ---------------------------------------------------------------------------
# Vocabulary - stable, closed, documented in docs/blender-adapter.md
# ---------------------------------------------------------------------------

GATE_STATUSES = ("blocked", "not_detected", "ready_for_fixture_qualification", "fixture_qualified")

# The workflows this phase's adapter supports. `fixture_organic_model`
# (Phase 45) is a one-shot, throwaway, never-persisted proof pipeline.
# `organic_cleanup_workflow` (Phase 49) is the first - and, this phase,
# only - real *project*-artifact workflow: import a Meshy/CAD-origin STL,
# apply one explicit uniform scale factor, export a new child STL. See
# docs/blender-adaptation.md "Supported workflow scope" - explicitly
# excludes character generation, Geometry Nodes automation, sculpting,
# texture generation, asset downloads, add-ons, retopology, mesh repair,
# remeshing, decimation, smoothing, prompt-to-Blender, and every other
# broader Blender use.
SUPPORTED_WORKFLOW_IDS = ("fixture_organic_model", "organic_cleanup_workflow")

FIXTURE_SCRIPT_PATH = project_store.REPO_ROOT / "blender_fixtures" / "factory_qualification_fixture.py"
FIXTURE_OUTPUT_FILENAME = "qualification_fixture.stl"

# Phase 49: the one Factory-owned script for the one real project-artifact
# workflow this phase implements. Lives outside src/ for the identical
# reason FIXTURE_SCRIPT_PATH does - see that script's own docstring and
# blender_fixtures/factory_organic_cleanup_workflow.py's.
ORGANIC_CLEANUP_SCRIPT_PATH = project_store.REPO_ROOT / "blender_fixtures" / "factory_organic_cleanup_workflow.py"

# Fixed, deterministic operation sequence for organic_cleanup_workflow -
# never repair/remesh/decimate/smooth (see docs/blender-adaptation.md).
# Rendered verbatim in every adaptation plan's `adaptation_operations`
# field so a human reviewing a plan sees exactly what would run, in order,
# before ever confirming it.
ORGANIC_CLEANUP_OPERATIONS = ("import_stl", "apply_scale_factor", "export_stl")

# The pre-existing 10-item checklist from docs/blender-local-track.md's
# "Required future gates before implementation" - preserved verbatim
# (never silently reinterpreted), reconciled additively against this
# phase's own 15-item checklist below.
_ORIGINAL_GATE_ITEMS: tuple[str, ...] = (
    "Explicit human approval to enable Blender automation.",
    "Local Blender path/version check.",
    "Dry-run mode.",
    "Output directory isolation.",
    "No overwriting original meshes.",
    "Repaired mesh provenance metadata.",
    "Before/after validation reports.",
    "Before/after render previews.",
    "`factory review-gate` remains required.",
    "No slicer/printer communication.",
)

# The Phase 45 spec's own 15-item checklist, each mapped to the original
# item(s) above it reconciles with (`None` where a requirement is new in
# this phase), a status, and an honest note - never a silent pass. See
# `docs/blender-adapter.md` "Gate checklist reconciliation" for the full
# prose version of this table.
_GATE_CHECKLIST: tuple[dict[str, Any], ...] = (
    {
        "item": "Explicit human approval for Blender local execution phase.",
        "maps_to_original": (0,),
        "status": "partially_satisfied",
        "note": (
            "Satisfied narrowly for THIS phase's one-shot, Factory-owned qualification-fixture "
            "pipeline only - this phase's own spec is the dated, explicit human instruction that "
            "authorized it. NOT satisfied for real project automation (mesh repair/render on an "
            "actual project): config/future_local_tools.json's blender.enabled stays false and "
            "requires_explicit_human_approval stays true - a separate, later, explicit decision."
        ),
    },
    {
        "item": "Blender path/version known.",
        "maps_to_original": (1,),
        "status": "satisfied",
        "note": (
            "Path/version from factory.engine_registry (Phase 43, .app bundle + Info.plist, no "
            "subprocess); this phase additionally corroborates the version via one real, bounded "
            "`--version` subprocess call. Still an auto-discovered path, not a human-reviewed one - "
            "see docs/blender-adapter.md 'Limitations'."
        ),
    },
    {
        "item": "Headless/background invocation verified.",
        "maps_to_original": (),
        "status": "satisfied",
        "note": (
            "New in this phase. One bounded `blender --background --factory-startup -Y "
            "--offline-mode --version` subprocess call, run fresh on every `factory blender "
            "qualify` invocation - never cached, never assumed from a prior run."
        ),
    },
    {
        "item": "Dry-run planning exists.",
        "maps_to_original": (2,),
        "status": "satisfied",
        "note": "`plan_blender_fixture_execution()` below - never launches Blender.",
    },
    {
        "item": "Output isolated to safe directories.",
        "maps_to_original": (3,),
        "status": "partially_satisfied",
        "note": (
            "Satisfied for the qualification fixture (a tempfile.TemporaryDirectory(), never "
            "examples/ or projects/). NOT implemented for a real future project workflow's "
            "<project>/generated/blender/ output directory - documented only, see "
            "docs/blender-adapter.md 'Receipt and output-directory mapping for a future phase'."
        ),
    },
    {
        "item": "Existing artifacts protected from overwrite.",
        "maps_to_original": (4,),
        "status": "satisfied",
        "note": (
            "The qualification fixture never touches any project file - there is no project "
            "involved, so there is nothing to overwrite. A real future project workflow's "
            "refuse-by-default overwrite policy is documented only, not implemented this phase."
        ),
    },
    {
        "item": "Provenance recorded.",
        "maps_to_original": (5,),
        "status": "deferred",
        "note": (
            "The qualification fixture is never persisted as a project artifact, so no "
            "part_manifest.json provenance entry is ever written by this phase. The future "
            "provenance field mapping for a real Blender-generated project artifact is documented "
            "only - see docs/blender-adapter.md 'Provenance model'."
        ),
    },
    {
        "item": "Generated mesh validated through Factory validators.",
        "maps_to_original": (6,),
        "status": "satisfied",
        "note": (
            "factory.validators.mesh_validate.validate_mesh() reused directly on the exported "
            "fixture STL - never a second validator. 'Before/after' (the original item's repair-"
            "workflow framing) does not apply to a freshly generated fixture; a future repair "
            "workflow still owes both passes."
        ),
    },
    {
        "item": "Generated mesh preview/render path verified.",
        "maps_to_original": (7,),
        "status": "satisfied",
        "note": (
            "factory.previews.render_preview.render_preview() reused directly - never a "
            "Blender-specific render/visual-QA subsystem. 'Before/after' does not apply to "
            "generation; a future repair workflow still owes both passes."
        ),
    },
    {
        "item": "Review Gate remains required.",
        "maps_to_original": (8,),
        "status": "satisfied",
        "note": (
            "Unchanged - the fixture never enters any project's pipeline, so review-gate is not "
            "even reached. Nothing in this phase sets human_approved/print_ready or bypasses "
            "factory review-gate for any future real workflow."
        ),
    },
    {
        "item": "No slicer/printer contact.",
        "maps_to_original": (9,),
        "status": "satisfied",
        "note": "Never invoked, never contacted - verified by tests/test_blender_adapter_safety.py.",
    },
    {
        "item": "No network.",
        "maps_to_original": (9,),
        "status": "satisfied",
        "note": (
            "`--offline-mode` is passed on every real Blender invocation this phase makes, "
            "forcing network access off regardless of the user's Blender preference, in addition "
            "to the fixture script itself importing no network-capable module."
        ),
    },
    {
        "item": "Bounded subprocess execution.",
        "maps_to_original": (),
        "status": "satisfied",
        "note": "Argument list, shell=False, hard timeout, captured stdout/stderr - see factory.blender_adapter.",
    },
    {
        "item": "No arbitrary external Python.",
        "maps_to_original": (),
        "status": "satisfied",
        "note": (
            "Exactly one Factory-owned, repository-reviewed script "
            "(blender_fixtures/factory_qualification_fixture.py) is ever passed to `--python`; "
            "no command in this repo accepts a user- or project-supplied script path."
        ),
    },
    {
        "item": "Temporary fixture cleanup verified.",
        "maps_to_original": (),
        "status": "satisfied",
        "note": "tempfile.TemporaryDirectory() plus an explicit post-hoc Path.exists() check - never assumed.",
    },
)


def reconcile_gate_checklist() -> list[dict[str, Any]]:
    """The full old-vs-new gate checklist reconciliation table - read-only,
    no I/O beyond the module-level constants above. See
    `docs/blender-adapter.md` "Gate checklist reconciliation"."""
    return [dict(item) for item in _GATE_CHECKLIST]


def _resolve_blender_binary(app_bundle_path: str) -> str | None:
    """Given the `.app` bundle path `factory.engine_registry` already
    detected, resolve the actual macOS executable inside it. A plain
    `Path.is_file()` check - never a launch, never a second filesystem
    scan for the bundle itself."""
    candidate = Path(app_bundle_path) / "Contents" / "MacOS" / "Blender"
    return str(candidate) if candidate.is_file() else None


def resolve_blender_binary() -> dict[str, Any]:
    """Read-only Blender detection, joined from Phase 43's registry probe.
    Never calls subprocess, never scans the filesystem beyond the single
    `Contents/MacOS/Blender` existence check above."""
    probe = engine_registry.probe_all_tools(include_version_subprocess=False).get("blender", {})
    detected = bool(probe.get("detected"))
    app_bundle_path = probe.get("detected_path")
    binary_path = _resolve_blender_binary(app_bundle_path) if detected and app_bundle_path else None
    warnings = list(probe.get("probe_warnings", []))
    if detected and app_bundle_path and not binary_path:
        warnings.append(f"detected .app bundle at {app_bundle_path!r} but no Contents/MacOS/Blender executable inside it")

    return {
        "detected": detected and binary_path is not None,
        "app_bundle_path": app_bundle_path,
        "binary_path": binary_path,
        "detected_version": probe.get("detected_version", "unknown"),
        "warnings": warnings,
    }


def plan_blender_fixture_execution() -> dict[str, Any]:
    """Dry-run plan for the one supported `fixture_organic_model`
    workflow - never launches Blender. See docs/blender-adapter.md
    "Blender plan model"."""
    resolved = resolve_blender_binary()
    future_local = future_local_tools.get_future_local_tool("blender")

    blockers: list[str] = []
    warnings: list[str] = list(resolved["warnings"])
    if not resolved["detected"]:
        blockers.append("Blender not detected locally (no Contents/MacOS/Blender executable found under the detected .app bundle).")

    gate_status = "not_detected" if not resolved["detected"] else ("blocked" if blockers else "ready_for_fixture_qualification")

    return {
        "project": None,
        "engine": "blender",
        "blender_path": resolved["binary_path"],
        "blender_version": resolved["detected_version"],
        "workflow": "fixture_organic_model",
        "execution_mode": "headless",
        "source_inputs": ["blender_fixtures/factory_qualification_fixture.py (Factory-owned, static)"],
        "expected_outputs": [FIXTURE_OUTPUT_FILENAME],
        "output_directory": "a fresh tempfile.TemporaryDirectory() (never examples/ or projects/)",
        "gate_status": gate_status,
        "blockers": blockers,
        "warnings": warnings,
        "overwrite_conflicts": [],
        "provenance_plan": {
            "note": (
                "Qualification fixtures are throwaway evidence, never persisted as a project "
                "artifact - no part_manifest.json entry is written. A future real project "
                "workflow's provenance mapping is documented in docs/blender-adapter.md, not "
                "implemented here."
            )
        },
        "validation_plan": {"validator": "factory.validators.mesh_validate.validate_mesh", "reused": True},
        "preview_plan": {"renderer": "factory.previews.render_preview.render_preview", "reused": True},
        "confirmation_required": True,
        "execution_allowed": gate_status == "ready_for_fixture_qualification",
        "dry_run": True,
        "project_execution_approved": False,
        "no_automatic_print": True,
        "notes": [
            f"config/future_local_tools.json gate status: {future_local.get('status', 'unknown')!r}, "
            f"enabled={future_local.get('enabled', False)} - unchanged by this phase; still governs real "
            "project automation, never this narrow fixture-qualification pipeline.",
        ],
    }


def plan_organic_cleanup_execution(
    *, input_stl_path: Path, output_stl_path: Path, scale_factor: float | None
) -> dict[str, Any]:
    """Dry-run plan for the one supported project-artifact workflow,
    `organic_cleanup_workflow` - never launches Blender, never reads the
    input mesh's own bytes (that's `factory.blender_adaptation`'s job, via
    the existing `factory.validators.mesh_validate.validate_mesh()`).
    Mirrors `plan_blender_fixture_execution()`'s shape/spirit, extended
    with the two paths and the one explicit scale factor a real
    project-artifact run additionally needs. See docs/blender-adaptation.md.
    """
    resolved = resolve_blender_binary()
    future_local = future_local_tools.get_future_local_tool("blender")
    input_stl_path = Path(input_stl_path)
    output_stl_path = Path(output_stl_path)

    blockers: list[str] = []
    warnings: list[str] = list(resolved["warnings"])
    if not resolved["detected"]:
        blockers.append("Blender not detected locally (no Contents/MacOS/Blender executable found under the detected .app bundle).")
    if not input_stl_path.is_file():
        blockers.append(f"input artifact does not exist: {input_stl_path}")
    if output_stl_path.exists():
        blockers.append(f"refusing to overwrite an existing file at the planned output path: {output_stl_path}")
    if scale_factor is None:
        blockers.append("no target dimension given - a human must supply --target-max-mm before this plan can be executed.")
    elif scale_factor <= 0:
        blockers.append(f"computed scale_factor must be positive, got {scale_factor}")

    gate_status = "not_detected" if not resolved["detected"] else ("blocked" if blockers else "ready_for_project_execution")

    return {
        "workflow": "organic_cleanup_workflow",
        "engine": "blender",
        "blender_path": resolved["binary_path"],
        "blender_version": resolved["detected_version"],
        "input_artifact": str(input_stl_path),
        "output_artifact": str(output_stl_path),
        "scale_factor": scale_factor,
        "operations": list(ORGANIC_CLEANUP_OPERATIONS),
        "execution_mode": "headless",
        "gate_status": gate_status,
        "blockers": blockers,
        "warnings": warnings,
        "validation_plan": {"validator": "factory.validators.mesh_validate.validate_mesh", "reused": True},
        "preview_plan": {"renderer": "factory.previews.render_preview.render_preview", "reused": True},
        "confirmation_required": True,
        "execution_allowed": gate_status == "ready_for_project_execution",
        "dry_run": True,
        "project_execution_approved": False,
        "automatic_execution_allowed": False,
        "no_automatic_print": True,
        "notes": [
            f"config/future_local_tools.json gate status: {future_local.get('status', 'unknown')!r}, "
            f"enabled={future_local.get('enabled', False)} - unchanged by this phase. Real execution for "
            "this one workflow is authorized narrowly by this phase's own dated spec (the same pattern "
            "Phase 45's fixture pipeline used), never by flipping this repo-wide config flag - see "
            "docs/blender-adaptation.md.",
        ],
    }


def evaluate_blender_execution_gate() -> dict[str, Any]:
    """Top-level read-only gate summary - `factory blender inspect`'s data
    source. Never launches Blender."""
    resolved = resolve_blender_binary()
    plan = plan_blender_fixture_execution()
    checklist = reconcile_gate_checklist()
    unsatisfied = [item["item"] for item in checklist if item["status"] not in ("satisfied",)]
    return {
        "detected": resolved["detected"],
        "detected_path": resolved["binary_path"],
        "detected_version": resolved["detected_version"],
        "gate_status": plan["gate_status"],
        "supported_workflows": list(SUPPORTED_WORKFLOW_IDS),
        "plan": plan,
        "gate_checklist": checklist,
        "unsatisfied_or_partial_gate_items": unsatisfied,
        "project_execution_approved": False,
        "no_automatic_print": True,
    }

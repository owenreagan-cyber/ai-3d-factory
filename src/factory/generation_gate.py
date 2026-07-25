"""Phase 34: local, deterministic Readiness-Gated CAD Generation Router.

The first gated bridge between the Design Orchestrator (Phase 33) and
this repo's *existing* local CAD generation backends:

    Project Readiness -> Design Orchestrator -> Readiness-Gated CAD Router
    -> CAD Engine -> Preview -> Review Gate

**This is an adapter/gate around existing local generation, not a second
CAD backend.** It never generates geometry itself - it only decides
*whether* `factory.openscad.generate.generate_openscad()` or
`factory.cad.cadquery_backend.generate_cadquery()` (both already
implemented, in earlier phases) are allowed to run, and if so, with which
template/parameters. See `docs/generation-gate.md`.

**Dry run by default.** Every entry point here defaults to
`confirm_generate=False` - it always computes and returns a full
*generation plan* (what would be generated, with what backend/template,
and what's still missing), and never calls a generation backend unless
`confirm_generate=True` is explicitly passed *and* every readiness gate
independently passes. No file is ever written by this module except via
the one, explicit, opt-in path.

**Reuses, never duplicates, readiness scoring or engine recommendation.**
Every function here takes an already-computed
`design_orchestrator_summary` (Phase 33,
`factory.design_orchestrator.evaluate_project_readiness()`) as input - the
readiness score, state, and recommended engine are read, never
recomputed.

**Only engines with a real, already-implemented local backend can ever be
generated.** Today that's `OpenSCAD` and `CadQuery` (`factory.cad.backend.get_backend_registry()`
already documents both as `"available"`/`"not_installed"`, never
`"future"`/`"future_gated"`). Any other recommended engine (`Blender`,
`Meshy (Concept Only)`, `FreeCAD`, `Hybrid Workflow`, `Manual Design`,
`Unknown`) always returns the `"Unsupported Engine"` decision - this
module never launches Blender, never calls Meshy, never generates
FreeCAD source, never installs anything, never contacts a network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import project_store
from factory.cad import cadquery_backend
from factory.cad.backend import is_cadquery_available
from factory.design_orchestrator import evaluate_readiness_for_path
from factory.openscad.generate import (
    GeneratedFileExistsError,
    GenerateResult,
    ProjectNotInitializedError,
    generate_openscad,
)
from factory.project_intake import analyze as analyze_intake

DECISIONS = ("Allowed", "Needs Confirmation", "Blocked", "Unsupported Engine", "Dry Run Only")

# Engines this gate can actually generate, today - must exactly match
# factory.cad.backend.get_backend_registry()'s "available"/"not_installed"
# entries (never its "future"/"future_gated" ones). Anything recommended
# outside this set is always "Unsupported Engine" - Blender/Meshy/FreeCAD/
# Hybrid Workflow/Manual Design/Unknown never reach a generation call.
SUPPORTED_ENGINES = ("OpenSCAD", "CadQuery")

# Matches factory.cad.backend.get_backend_registry()'s backend_id for each
# SUPPORTED_ENGINES entry - the receipt's "backend" field is this, not the
# human-facing "engine" display name.
_ENGINE_BACKEND_IDS = {"OpenSCAD": "openscad", "CadQuery": "cadquery"}

# generated/generation_receipt.json - where write_generation_receipt() writes,
# relative to a project directory. No established "generated-artifact"
# location already existed in this repo for this purpose (cad/, stl/,
# renders/, validation/, slicer_review/, final_candidate/ are all
# PROJECT_SUBDIRS with a different, earlier-phase purpose - see
# factory.project_store), so this phase introduces this one, scoped
# specifically to execution receipts.
GENERATED_DIRNAME = "generated"
RECEIPT_FILENAME = "generation_receipt.json"

# A "conservative threshold," per this phase's own requirement - matches
# Design Orchestrator's own internal boundary for its "Ready For ..."
# states (see factory.design_orchestrator.determine_readiness_state()),
# so this gate never disagrees with what "ready" already means elsewhere
# in this pipeline.
MINIMUM_READINESS_SCORE = 60

# Advisories (Phase 33's own vocabulary - factory.design_orchestrator.generate_readiness_advisories())
# that represent missing information critical enough to block generation
# outright, even if the overall score happens to clear the threshold.
_CRITICAL_ADVISORIES = ("Dimensions missing", "Material unspecified", "Printer unspecified")

_READY_FOR_PREFIX = "Ready For"


def _select_openscad_plan(intake_summary: dict[str, Any] | None) -> dict[str, Any] | None:
    """Deterministic OpenSCAD template selection - only `"sign"` maps
    confidently to an existing local template (`ALLOWED_TEMPLATES` in
    `factory.openscad.templates` is `("test-cube", "nameplate", "sign",
    "multipart-nameplate")`; `"sign"` is the one that fits every
    OpenSCAD-leaning category this repo's own category->engine mapping
    produces - see `docs/design-orchestrator.md`). Returns `None` (no
    plan) rather than guessing a template for a category with no confident
    local match - generation is never attempted blind.
    """
    intake_summary = intake_summary or {}
    project_name = (intake_summary.get("project_name") or {}).get("value")
    text = project_name if isinstance(project_name, str) and project_name.strip() else "Untitled"
    return {
        "engine": "OpenSCAD",
        "template": "sign",
        "params": {"text": text},
        "human_summary": f'OpenSCAD "sign" template, text={text!r}',
    }


def _select_cadquery_plan(intake_summary: dict[str, Any] | None) -> dict[str, Any] | None:
    """CadQuery has exactly one local template
    (`factory.cad.cadquery_backend.ALLOWED_TEMPLATES == ("mechanical-plate",)`)
    - a generic dimensioned plate/bracket shape with optional mounting
    holes and an engraved label. Always selected when CadQuery is the
    recommended engine, using the generator's own conservative defaults
    (declared dimensional_constraints are free text like `"48-inch"`, not
    a confirmed `[length, width, thickness]` triple - never guessed into
    specific dimension parameters).
    """
    return {
        "engine": "CadQuery",
        "template": "mechanical-plate",
        "params": {"length_mm": 80.0, "width_mm": 50.0, "thickness_mm": 5.0, "corner_radius_mm": 4.0},
        "human_summary": "CadQuery \"mechanical-plate\" template (default dimensions - review before treating as final)",
    }


def plan_generation(
    intake_summary: dict[str, Any] | None, design_orchestrator_summary: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Deterministic generation plan for the recommended engine - which
    local template and parameters would be used, or `None` if no
    confident local template exists for the recommended engine/category
    combination. Never invents a template; never itself generates
    anything.
    """
    engine = (design_orchestrator_summary or {}).get("recommended_engine")
    if engine == "OpenSCAD":
        return _select_openscad_plan(intake_summary)
    if engine == "CadQuery":
        return _select_cadquery_plan(intake_summary)
    return None


def evaluate_generation_gate(
    intake_summary: dict[str, Any] | None,
    design_orchestrator_summary: dict[str, Any] | None,
    *,
    confirm_generate: bool = False,
) -> dict[str, Any]:
    """The core, pure gate decision - takes an already-computed
    `design_orchestrator_summary` (Phase 33) and `intake_summary`
    (Phase 30) and decides whether local CAD generation is allowed.

    Returns:
    ```
    {
      "decision": one of DECISIONS,
      "recommended_engine": str,
      "readiness_state": str,
      "readiness_score": int,
      "plan": {...} | None,                 # see plan_generation()
      "required_before_generation": [str, ...],
      "confirm_generate": bool,              # echoes the input, for the CLI/board to display
    }
    ```

    Priority order (first match wins) - see `docs/generation-gate.md`
    "Decision states" for the full reasoning:
    1. `readiness_state == "Blocked"` -> `"Blocked"`, always, regardless
       of engine/score/confirmation.
    2. `recommended_engine` not in `SUPPORTED_ENGINES` -> `"Unsupported
       Engine"` - Blender/Meshy/FreeCAD/Hybrid Workflow/Manual
       Design/Unknown never reach a generation call from this gate.
    3. CadQuery recommended but the `cadquery` package isn't installed in
       this environment -> `"Unsupported Engine"` (same bucket - "not
       available here," distinct from "not implemented at all").
    4. Readiness state isn't one of the four `"Ready For ..."` states, or
       the overall score is below `MINIMUM_READINESS_SCORE`, or a
       critical advisory (`Dimensions missing`/`Material unspecified`/
       `Printer unspecified`) is present, or no local template plan could
       be determined -> `"Dry Run Only"` - even `--confirm-generate`
       cannot force generation past this gate.
    5. Otherwise: `"Needs Confirmation"` if `confirm_generate` is `False`,
       `"Allowed"` if `True` - this is the only state this function ever
       returns that a caller should treat as "safe to actually generate."

    Never writes anything, never invokes any CAD engine, never contacts a
    network - this function only decides, `run_generation()` is the one
    place that acts on `"Allowed"`.
    """
    orchestrator = design_orchestrator_summary or {}
    readiness_state = orchestrator.get("readiness_state", "Not Ready")
    engine = orchestrator.get("recommended_engine", "Unknown")
    score = orchestrator.get("score") or {}
    overall = score.get("overall", 0)
    advisories = orchestrator.get("advisories") or []

    plan = plan_generation(intake_summary, orchestrator)
    required: list[str] = []

    if readiness_state == "Blocked":
        decision = "Blocked"
        required.append("project readiness is blocked - see design_orchestrator_summary for why")
    elif engine not in SUPPORTED_ENGINES:
        decision = "Unsupported Engine"
        required.append(f"{engine} has no local generation backend wired to this gate")
    elif engine == "CadQuery" and not is_cadquery_available():
        decision = "Unsupported Engine"
        required.append("the cadquery package is not installed in this environment")
    else:
        critical_missing = [a for a in advisories if a in _CRITICAL_ADVISORIES]
        ready_state_ok = readiness_state.startswith(_READY_FOR_PREFIX)
        score_ok = isinstance(overall, (int, float)) and overall >= MINIMUM_READINESS_SCORE

        if critical_missing:
            required.extend(a.lower() for a in critical_missing)
        if not ready_state_ok:
            required.append(f"readiness state is {readiness_state!r}, not one of the \"Ready For ...\" states")
        if not score_ok:
            required.append(f"readiness score {overall}% is below the {MINIMUM_READINESS_SCORE}% threshold")
        if plan is None:
            required.append(f"no local template is available for engine {engine!r} and this project's category")

        if required:
            decision = "Dry Run Only"
        elif not confirm_generate:
            decision = "Needs Confirmation"
            required.append("human confirmation required (--confirm-generate)")
        else:
            decision = "Allowed"

    return {
        "decision": decision,
        "recommended_engine": engine,
        "readiness_state": readiness_state,
        "readiness_score": overall,
        "plan": plan,
        "required_before_generation": required,
        "confirm_generate": confirm_generate,
    }


def run_generation(project_dir: Path, gate_result: dict[str, Any]) -> dict[str, Any]:
    """Execute the one, explicit write path this module has - calls the
    existing `factory.openscad.generate.generate_openscad()` or
    `factory.cad.cadquery_backend.generate_cadquery()` (both already
    implemented in earlier phases; this function never re-implements CAD
    generation itself) using `gate_result["plan"]`.

    **Only ever called when `gate_result["decision"] == "Allowed"`** - the
    CLI/caller is responsible for checking that first; this function
    raises `ValueError` if called with any other decision, as a defensive
    guard against accidentally generating when the gate said no.

    Returns `{"written_files": [str, ...], "warnings": [str, ...]}`.
    Never invokes OpenSCAD/CadQuery/Blender/Meshy/FreeCAD binaries, never
    exports an STL, never contacts a network/printer/slicer - identical
    guarantees to the underlying generators it calls.
    """
    if gate_result.get("decision") != "Allowed":
        raise ValueError(
            f"run_generation() called with decision {gate_result.get('decision')!r}, not 'Allowed' - "
            "this is a programming error in the caller, not a user-facing condition."
        )

    plan = gate_result["plan"]
    engine = plan["engine"]
    project_dir = Path(project_dir)

    if engine == "OpenSCAD":
        result: GenerateResult = generate_openscad(project_dir, plan["template"], plan["params"].get("text"))
        return {
            "written_files": [str(p) for p in result.written_files],
            "warnings": [],
        }

    if engine == "CadQuery":
        cq_result = cadquery_backend.generate_cadquery(
            project_dir,
            plan["template"],
            length_mm=plan["params"]["length_mm"],
            width_mm=plan["params"]["width_mm"],
            thickness_mm=plan["params"]["thickness_mm"],
            corner_radius_mm=plan["params"]["corner_radius_mm"],
        )
        return {
            "written_files": [str(p) for p in cq_result.written_files],
            "warnings": [],
        }

    raise ValueError(f"run_generation() has no adapter for engine {engine!r} - this should be unreachable.")


def summarize_generation_gate(
    intake_summary: dict[str, Any] | None, design_orchestrator_summary: dict[str, Any] | None
) -> dict[str, Any]:
    """Compact summary for `factory.project_inspection.summarize_project()`'s
    `generation_gate_summary` field and the preview board's "Generation
    Gate" card - always evaluated as a dry run (`confirm_generate=False`),
    since project inspection is read-only and must never trigger actual
    generation. Returns `{"decision", "recommended_engine", "ready",
    "reason"}` - a compact view, not the full plan/required-before list
    (that stays in `factory generate-from-readiness`'s output).
    """
    gate_result = evaluate_generation_gate(intake_summary, design_orchestrator_summary, confirm_generate=False)
    ready = gate_result["decision"] in ("Allowed", "Needs Confirmation")
    reason = gate_result["required_before_generation"][0] if gate_result["required_before_generation"] else None
    return {
        "decision": gate_result["decision"],
        "recommended_engine": gate_result["recommended_engine"],
        "ready": ready,
        "reason": reason,
    }


def evaluate_generation_gate_for_path(path: Path, *, confirm_generate: bool = False) -> dict[str, Any]:
    """Convenience entry point for `factory generate-from-readiness <path>`
    - computes `intake_summary` and the Design Orchestrator's readiness
    evaluation the same way `factory readiness <path>` does (reusing
    `factory.project_intake.analyze()` and
    `factory.design_orchestrator.evaluate_readiness_for_path()` directly,
    never re-implementing either), then evaluates the gate. Works for a
    single project directory or a plain-text/Markdown idea file, same as
    every other Phase 30-33 path-based entry point.
    """
    path = Path(path)
    intake_summary = analyze_intake(path)
    orchestrator_summary = evaluate_readiness_for_path(path)
    return evaluate_generation_gate(intake_summary, orchestrator_summary, confirm_generate=confirm_generate)


# ---------------------------------------------------------------------------
# Execution receipts and artifact tracking.
#
# Everything below only runs *after* run_generation() has already, actually
# succeeded (decision == "Allowed", confirm_generate == True) - never for a
# dry run, "Needs Confirmation", "Blocked", "Unsupported Engine", or "Dry Run
# Only". It never re-generates, re-validates, or re-scores anything: sizes
# and existence are read straight off the filesystem, and manifest/
# validation state is read from files the existing generators/validators
# already wrote (factory.openscad.generate/factory.cad.cadquery_backend for
# part_manifest.json, `factory validate` for validation/*.json) - never
# recomputed here. See docs/generation-gate.md "Execution receipts" and
# "Artifact tracking".
# ---------------------------------------------------------------------------


def _relative_path(path: Path, project_dir: Path) -> str:
    """POSIX-style path relative to `project_dir`, falling back to the raw
    path unchanged if it isn't actually under `project_dir` (e.g. a
    differently-rooted path passed in by a caller). Never raises.
    """
    path = Path(path)
    try:
        return path.relative_to(Path(project_dir)).as_posix()
    except ValueError:
        return path.as_posix()


def _cad_source_category(path_str: str) -> str:
    suffix = Path(path_str).suffix.lower()
    if suffix == ".scad":
        return "OpenSCAD"
    if suffix == ".py":
        return "CadQuery"
    return "Other"


def _manifest_parts_for_written_files(project_dir: Path, written_files: list[str]) -> list[dict[str, Any]]:
    """Read-only: return only the `part_manifest.json` entries this
    generation run actually touched, matched by `cad_source` against
    `written_files` (both compared as project-relative POSIX paths). Reads
    the manifest `run_generation()` itself already upserted via
    `factory.openscad.generate._upsert_manifest_parts` or
    `factory.cad.manifest.upsert_cadquery_manifest_entry` - never
    re-derives or re-scores a single field of it.
    """
    manifest_path = Path(project_dir) / "part_manifest.json"
    if not manifest_path.is_file():
        return []
    manifest = project_store.load_json(manifest_path)
    written_rel = {_relative_path(Path(p), project_dir) for p in written_files}
    return [part for part in manifest.get("parts", []) if part.get("cad_source") in written_rel]


def _validation_status_for_mesh(project_dir: Path, mesh_rel_path: str) -> dict[str, Any]:
    """Read-only: does a `factory validate` report already exist for this
    expected STL? Never runs `factory.validators.mesh_validate` itself -
    this only checks for (and reads) a report that command may have
    already written, mirroring the same `validation/<stem>_validation.json`
    naming convention `factory.project_inspection._compute_validation_coverage`
    and the `factory validate` CLI command already use (never duplicated,
    only read). Right after a fresh confirmed generation there is normally
    no STL yet - export is always a separate, manual, human-run step (see
    docs/generation-gate.md) - so `"not_yet_validated"` is the expected,
    honest common case, not an error.
    """
    stem = Path(mesh_rel_path).stem
    report_path = Path(project_dir) / "validation" / f"{stem}_validation.json"
    if not report_path.is_file():
        return {"status": "not_yet_validated", "report_path": None}
    try:
        report = project_store.load_json(report_path)
    except (OSError, ValueError):
        return {"status": "not_yet_validated", "report_path": None}
    return {
        "status": report.get("overall_status", "UNKNOWN"),
        "report_path": _relative_path(report_path, project_dir),
    }


def _preview_status_for_mesh(project_dir: Path, mesh_rel_path: str) -> dict[str, Any]:
    """Read-only: does a `factory render` preview PNG already exist for this
    expected STL? Mirrors the `renders/<stem>_preview.png` naming
    convention the `factory render` CLI command already uses - never
    invokes rendering itself.
    """
    stem = Path(mesh_rel_path).stem
    render_path = Path(project_dir) / "renders" / f"{stem}_preview.png"
    exists = render_path.is_file()
    return {
        "status": "present" if exists else "not_yet_rendered",
        "render_path": _relative_path(render_path, project_dir) if exists else None,
    }


def build_artifact_tracking(project_dir: Path, written_files: list[str]) -> dict[str, Any]:
    """Normalized view of every artifact category this phase's spec calls
    out - CAD (broken down into OpenSCAD/CadQuery), STL, Manifest,
    Validation, Preview, Review - for one confirmed generation run. Purely
    read-only and purely a reflection of state already on disk or already
    computed by an existing generator/validator; this function never
    writes, generates, validates, or renders anything itself. `"review"` is
    deliberately left as a pointer to `factory review-gate` rather than a
    computed field - `factory.review_gate.evaluate_review_gate()` needs
    `factory.project_inspection.summarize_project()`, and this module must
    never import `project_inspection` (see
    `test_module_never_imports_project_inspection` in
    tests/test_generation_gate.py) - `project_inspection` imports *this*
    module, not the other way around.
    """
    project_dir = Path(project_dir)

    cad_source = [{"path": rel, "category": _cad_source_category(rel)} for rel in written_files]

    parts = _manifest_parts_for_written_files(project_dir, written_files)
    stl: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []
    preview: list[dict[str, Any]] = []
    for part in parts:
        part_name = part.get("part_name")
        mesh_rel_path = part.get("file_path")
        if not mesh_rel_path:
            continue
        mesh_path = project_dir / mesh_rel_path
        exists = mesh_path.is_file()
        stl.append(
            {
                "part_name": part_name,
                "expected_path": mesh_rel_path,
                "exists": exists,
                "size_bytes": mesh_path.stat().st_size if exists else None,
            }
        )
        validation.append({"part_name": part_name, **_validation_status_for_mesh(project_dir, mesh_rel_path)})
        preview.append({"part_name": part_name, **_preview_status_for_mesh(project_dir, mesh_rel_path)})

    return {
        "cad_source": cad_source,
        "manifest": {
            "path": "part_manifest.json" if (project_dir / "part_manifest.json").is_file() else None,
            "parts": parts,
        },
        "stl": stl,
        "validation": validation,
        "preview": preview,
        "review": (
            "Not assessed by this command - run `factory review-gate <project_dir>` for human "
            "slicer-review readiness."
        ),
    }


def _summarize_validation_status(validation_entries: list[dict[str, Any]]) -> str:
    """Collapse per-part validation entries (see build_artifact_tracking())
    into the receipt's single flat `validation_status` field. Never runs a
    validator - purely a summary of already-read report statuses.
    """
    if not validation_entries:
        return "not_applicable"
    statuses = {entry["status"] for entry in validation_entries}
    if statuses == {"not_yet_validated"}:
        return "not_yet_validated"
    if statuses <= {"PASS"}:
        return "PASS"
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "mixed"


def build_execution_receipt(
    project_dir: Path, gate_result: dict[str, Any], generation_result: dict[str, Any]
) -> dict[str, Any]:
    """Build the normalized execution-receipt payload for one confirmed,
    successful generation run - see docs/generation-gate.md "Execution
    receipts" for the full field reference. Only ever called after
    `run_generation()` has already returned successfully; every field here
    is read from `gate_result`/`generation_result` (already computed by
    `evaluate_generation_gate()`/`run_generation()`) or from files those
    calls already wrote - this function never generates, validates, or
    re-scores anything itself.
    """
    project_dir = Path(project_dir)
    plan = gate_result.get("plan") or {}
    engine = plan.get("engine") or gate_result.get("recommended_engine") or "Unknown"
    written_files = list(generation_result.get("written_files") or [])

    files_generated = [_relative_path(Path(p), project_dir) for p in written_files]
    artifact_sizes: dict[str, int | None] = {}
    for raw, rel in zip(written_files, files_generated):
        raw_path = Path(raw)
        artifact_sizes[rel] = raw_path.stat().st_size if raw_path.is_file() else None

    artifact_tracking = build_artifact_tracking(project_dir, files_generated)

    return {
        "project": str(project_dir),
        "engine": engine,
        "backend": _ENGINE_BACKEND_IDS.get(engine, str(engine).lower()),
        "template": plan.get("template"),
        "readiness_score": gate_result.get("readiness_score"),
        "readiness_state": gate_result.get("readiness_state"),
        "execution_decision": gate_result.get("decision"),
        "files_generated": files_generated,
        "artifact_sizes": artifact_sizes,
        "artifact_tracking": artifact_tracking,
        "validation_status": _summarize_validation_status(artifact_tracking["validation"]),
        "warnings": list(generation_result.get("warnings") or []),
        "errors": [],
        "success": True,
        "timestamp": project_store.utc_now_iso(),
    }


def write_generation_receipt(
    project_dir: Path, gate_result: dict[str, Any], generation_result: dict[str, Any]
) -> Path:
    """Write `<project_dir>/generated/generation_receipt.json` for one
    confirmed, successful generation run.

    **Only ever called after `run_generation()` has already returned
    successfully** (`gate_result["decision"] == "Allowed"`) - the CLI is
    responsible for that ordering, same convention as `run_generation()`
    itself. Dry runs, "Needs Confirmation", "Blocked", "Unsupported
    Engine", and "Dry Run Only" never reach this function and never
    produce a receipt (see docs/generation-gate.md "Execution receipts").
    One receipt reflects the most recent confirmed run for this project,
    not a history - a later confirmed run overwrites it. No console/print
    confirmation is ever triggered by this function itself; that decision
    is left entirely to the caller (`factory generate-from-readiness`
    surfaces the path via `--json` output only).
    """
    project_dir = Path(project_dir)
    receipt = build_execution_receipt(project_dir, gate_result, generation_result)
    receipt_path = project_dir / GENERATED_DIRNAME / RECEIPT_FILENAME
    project_store.save_json(receipt_path, receipt)
    return receipt_path


def read_last_execution_receipt(project_dir: Path) -> dict[str, Any] | None:
    """Read-only: return the contents of
    `<project_dir>/generated/generation_receipt.json` if one exists, else
    `None`. Never writes, never triggers generation, never raises on a
    missing or unreadable file.
    """
    receipt_path = Path(project_dir) / GENERATED_DIRNAME / RECEIPT_FILENAME
    if not receipt_path.is_file():
        return None
    try:
        return project_store.load_json(receipt_path)
    except (OSError, ValueError):
        return None


def summarize_generation_execution(project_dir: Path) -> dict[str, Any]:
    """Compact, additive summary of this project's *execution history* (as
    opposed to `summarize_generation_gate()`, which summarizes the current
    dry-run *decision*) - backs
    `factory.project_inspection.summarize_project()`'s
    `generation_execution_summary` field and the Preview Board's
    "Last execution"/"Receipt available" rows. Deliberately a separate
    function/field from `summarize_generation_gate()` rather than added
    fields on it, so that function's existing shape
    (`{"decision", "recommended_engine", "ready", "reason"}`) stays exactly
    as every current Generation Gate test already pins it. Read-only:
    never writes, never triggers generation.
    """
    receipt = read_last_execution_receipt(project_dir)
    if receipt is None:
        return {"receipt_available": False, "last_execution": None, "last_execution_engine": None}
    return {
        "receipt_available": True,
        "last_execution": receipt.get("timestamp"),
        "last_execution_engine": receipt.get("engine"),
    }

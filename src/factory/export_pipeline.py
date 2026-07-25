"""Phase 35: local, deterministic Guided Export Pipeline.

The next gated step after Phase 34's Readiness-Gated CAD Generation Router:

    CAD Source Generation -> Guided Export Pipeline -> STL Verification ->
    Validation and Preview -> Artifact Finalization -> Human Review Gate ->
    Slicer Review -> (never automatic printing)

**This orchestrates existing local commands - it never re-implements CAD
generation, STL export, mesh validation, or preview rendering.** It calls
the existing `factory.validators.mesh_validate.validate_mesh()` and
`factory.previews.render_preview.render_preview()` directly, and its one
new capability - actually invoking the OpenSCAD CLI to export an STL - is
the first automated subprocess execution in this repo; everything else
here is planning, verification, and bookkeeping around existing pieces.

**Dry run by default.** Every entry point defaults to `confirm_export=False`
- it always computes and returns a full *export plan* (which CAD source
would be exported, with which tool, to which output, and what's blocking
it), and never invokes a subprocess or writes a file unless
`confirm_export=True` is explicitly passed *and* every gate independently
passes. No file is ever written by this module except via the one,
explicit, opt-in path (`run_export()`/`run_export_pipeline()`).

**OpenSCAD only for automatic export.** CadQuery source (`cad/*.py`) is
never executed by this module - running a generated CadQuery script means
running arbitrary local Python that imports `cadquery`, which this repo's
existing architecture (`factory.cad.cadquery_backend`, `docs/cad-backends.md`)
has always treated as an explicit, manual, human-run step
("It does not import or execute the CadQuery source it writes"). This
phase does not silently change that policy - a CadQuery-sourced project
always resolves to `"manual_export_required"`, with the exact manual
command surfaced as an advisory, never executed here.

**Never sends anything to a printer or slicer.** This module's job ends at
STL export + validation + preview render - exactly where `factory
validate`/`factory render` already stopped. See `docs/export-pipeline.md`.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from factory import project_store
from factory.cad.backend import is_cadquery_available
from factory.generation_gate import GENERATED_DIRNAME, read_last_execution_receipt
from factory.manufacturing import knowledge
from factory.previews.render_preview import render_preview
from factory.render_coverage import compute_render_coverage
from factory.validators.mesh_validate import validate_mesh
from factory.validators.multipart_check import check_manifest as check_multipart_manifest

DECISIONS = (
    "needs_confirmation",
    "allowed",
    "blocked",
    "unsupported_source",
    "ambiguous_source",
    "manual_export_required",
    "export_tool_missing",
    "output_collision",
    "stale_output_detected",
    "export_failed",
    "validation_failed",
    "render_failed",
    "partial_pipeline",
    "completed",
)

# Only engines with a real, already-implemented local generation backend
# (factory.cad.backend.get_backend_registry()) ever reach this module in
# the first place - matches factory.generation_gate.SUPPORTED_ENGINES
# exactly, so the two modules never disagree about what "CAD source"
# means in this repo.
_SOURCE_EXTENSION_ENGINES = {".scad": "OpenSCAD", ".py": "CadQuery"}
SUPPORTED_SOURCE_ENGINES = ("OpenSCAD", "CadQuery")
_ENGINE_BACKEND_IDS = {"OpenSCAD": "openscad", "CadQuery": "cadquery"}

# generated/export_receipt.json - a sibling of Phase 34's
# generated/generation_receipt.json (factory.generation_gate.RECEIPT_FILENAME),
# never merged into it: Phase 34's receipt reflects one CAD *generation*
# run and is read by tests pinning its exact shape; this phase's receipt
# reflects a project's *export/validate/render* history and can be
# upserted many times (once per source file, across many separate runs)
# without ever touching Phase 34's file. See docs/export-pipeline.md
# "Receipts".
EXPORT_RECEIPT_FILENAME = "export_receipt.json"

# Local, macOS-first executable discovery, mirroring the exact style
# factory.slicer.local_slicer_probe.probe_slicers() already uses for
# Bambu Studio/OrcaSlicer: a known .app bundle path, then a PATH binary.
# Read-only discovery only - resolving the executable never installs,
# downloads, or launches anything.
_OPENSCAD_APP_BINARY_PATHS = ("/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD",)
_OPENSCAD_PATH_BINARY = "openscad"

EXPORT_TIMEOUT_SECONDS = 120
_VERSION_PROBE_TIMEOUT_SECONDS = 10

VALIDATION_STATUSES = ("not_run", "passed", "passed_with_warnings", "failed", "unavailable", "partial")
RENDER_STATUSES = ("not_run", "passed", "stale", "failed", "unavailable", "partial")


class UnsafePathError(ValueError):
    """Raised when a `--source`/`--output-dir` path would escape the project directory."""


def resolve_openscad_executable() -> str | None:
    """Locate a local OpenSCAD CLI executable, without installing or launching anything.

    Checks the standard macOS `.app` bundle location, then `PATH` via
    `shutil.which()` - same discovery style as
    `factory.slicer.local_slicer_probe.probe_slicers()`. Returns `None` if
    not found; never raises, never downloads, never installs.
    """
    for candidate in _OPENSCAD_APP_BINARY_PATHS:
        if Path(candidate).is_file():
            return candidate
    return shutil.which(_OPENSCAD_PATH_BINARY)


def _file_fingerprint(path: Path) -> str:
    """A stable content fingerprint for change detection - `sha256:<hex digest>`.

    Read-only; never modifies the file. Used to detect a stale STL (source
    changed since export) more reliably than a modification-time
    comparison alone (see `_stl_freshness()`).
    """
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _relative_path(path: Path, project_dir: Path) -> str:
    path = Path(path)
    try:
        return path.relative_to(Path(project_dir)).as_posix()
    except ValueError:
        return path.as_posix()


def _format_epoch(epoch: float) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc).isoformat()


def _safe_join(project_dir: Path, candidate: Path) -> Path:
    """Join `candidate` (absolute or project-relative) onto `project_dir` and
    verify it stays inside it. Raises `UnsafePathError` if it would escape
    - never silently clamps or truncates a path.

    The containment check compares fully-resolved (symlink-free) paths -
    the safety guarantee callers actually need - but the *returned* path
    keeps `project_dir`'s original, unresolved prefix, so downstream
    `_relative_path()` calls against that same `project_dir` stay exact
    (resolving here would otherwise turn e.g. macOS's `/tmp` into
    `/private/tmp` and silently break every relative-path computation for
    the rest of the plan).
    """
    project_dir = Path(project_dir)
    joined = candidate if candidate.is_absolute() else project_dir / candidate

    resolved_project = project_dir.resolve()
    resolved_joined = joined.resolve()
    if resolved_joined != resolved_project and resolved_project not in resolved_joined.parents:
        raise UnsafePathError(f"{candidate} resolves outside the project directory ({resolved_project})")
    return joined


def _discover_cad_sources(project_dir: Path) -> dict[str, list[Path]]:
    """Read-only: every recognized CAD source file under `<project_dir>/cad/`,
    grouped by engine (`"OpenSCAD"` -> `.scad` files, `"CadQuery"` -> `.py`
    files), each list sorted for determinism. Files with an unrecognized
    extension are omitted here - see `_unrecognized_cad_sources()`.
    """
    cad_dir = Path(project_dir) / "cad"
    if not cad_dir.is_dir():
        return {}
    grouped: dict[str, list[Path]] = {}
    for path in sorted(cad_dir.iterdir()):
        if not path.is_file():
            continue
        engine = _SOURCE_EXTENSION_ENGINES.get(path.suffix.lower())
        if engine:
            grouped.setdefault(engine, []).append(path)
    return grouped


def _unrecognized_cad_sources(project_dir: Path) -> list[Path]:
    cad_dir = Path(project_dir) / "cad"
    if not cad_dir.is_dir():
        return []
    return sorted(
        p for p in cad_dir.iterdir() if p.is_file() and p.suffix.lower() not in _SOURCE_EXTENSION_ENGINES
    )


def _expected_stl_path(source_path: Path, output_dir: Path) -> Path:
    return output_dir / f"{source_path.stem}.stl"


def _stl_freshness(
    source_path: Path, stl_path: Path, prior_receipt: dict[str, Any] | None, source_rel: str
) -> str:
    """`"current"` / `"stale"` / `"unknown"` / `"missing"` - never treats mere
    file *existence* as currentness (per this phase's own requirement).

    Prefers a fingerprint comparison against a prior export receipt entry
    for this exact source file (the strongest signal - immune to mtime
    resets from e.g. a fresh git checkout); falls back to a modification-
    time comparison, mirroring the same epsilon-guarded convention
    `factory.render_coverage.compute_render_coverage()` already uses.
    """
    if not stl_path.is_file():
        return "missing"
    if not source_path.is_file():
        return "unknown"

    if prior_receipt:
        for record in prior_receipt.get("exports") or []:
            if record.get("source_file") == source_rel:
                recorded_fingerprint = record.get("source_fingerprint")
                if recorded_fingerprint:
                    return "current" if recorded_fingerprint == _file_fingerprint(source_path) else "stale"

    return "current" if stl_path.stat().st_mtime + 1e-6 >= source_path.stat().st_mtime else "stale"


def _validation_report_path(project_dir: Path, stl_rel_path: str) -> Path:
    stem = Path(stl_rel_path).stem
    return Path(project_dir) / "validation" / f"{stem}_validation.json"


def _render_path(project_dir: Path, stl_rel_path: str) -> Path:
    stem = Path(stl_rel_path).stem
    return Path(project_dir) / "renders" / f"{stem}_preview.png"


def _cadquery_manual_command(source_rel: str) -> str:
    return f"python {source_rel}"


# ---------------------------------------------------------------------------
# Planning - pure, read-only. Never invokes a subprocess, never writes a
# file, regardless of `confirm_export`.
# ---------------------------------------------------------------------------


def plan_export(
    project_dir: Path,
    *,
    source: str | None = None,
    output_dir: str | None = None,
    overwrite_stl: bool = False,
    confirm_export: bool = False,
) -> dict[str, Any]:
    """The core, pure export-plan decision - never invokes a subprocess,
    never writes a file, regardless of `confirm_export`. Calling this
    twice with unchanged files on disk returns an equal dict (no
    nondeterministic timestamps are included - see docs/export-pipeline.md
    "Dry-run behavior").

    Priority order (first match wins) - see docs/export-pipeline.md
    "Decision states" for the full reasoning:
    1. An explicit `--source`/`--output-dir` outside the project directory
       -> `"blocked"`.
    2. No recognized CAD source under `cad/` -> `"blocked"`.
    3. `--source` given but its extension isn't recognized, or (no
       `--source`) only unrecognized files exist -> `"unsupported_source"`.
    4. No `--source` given and *both* OpenSCAD and CadQuery source exist
       -> `"ambiguous_source"` - pass `--source` to disambiguate.
    5. Resolved engine is CadQuery -> `"manual_export_required"`, always -
       this repo's existing CadQuery policy is manual-only and this phase
       does not change that, regardless of `confirm_export`.
    6. Resolved engine is OpenSCAD but no local `openscad` executable is
       found -> `"export_tool_missing"`, always - `confirm_export` cannot
       force this.
    7. Any expected output STL already exists and `overwrite_stl` is
       `False` -> `"output_collision"` - `confirm_export` cannot force
       past an unresolved collision.
    8. Otherwise: `"needs_confirmation"` if `confirm_export` is `False`,
       `"allowed"` if `True`.
    """
    project_dir = Path(project_dir)
    project_name = project_dir.name
    blocking_reasons: list[str] = []
    advisories: list[str] = []

    try:
        output_directory = _safe_join(project_dir, Path(output_dir) if output_dir else Path("stl"))
    except UnsafePathError as exc:
        return _blocked_plan(project_dir, project_name, confirm_export, [str(exc)])

    grouped = _discover_cad_sources(project_dir)
    unrecognized = _unrecognized_cad_sources(project_dir)

    if source is not None:
        try:
            selected_path = _safe_join(project_dir, Path(source))
        except UnsafePathError as exc:
            return _blocked_plan(project_dir, project_name, confirm_export, [str(exc)])
        if not selected_path.is_file():
            return _blocked_plan(
                project_dir, project_name, confirm_export, [f"--source {source!r} does not exist"]
            )
        engine = _SOURCE_EXTENSION_ENGINES.get(selected_path.suffix.lower())
        if engine is None:
            return _unsupported_source_plan(project_dir, project_name, confirm_export, [selected_path], None)
        source_files = [selected_path]
        selected_source = _relative_path(selected_path, project_dir)
    elif len(grouped) > 1:
        found = ", ".join(f"{engine} ({len(paths)} file(s))" for engine, paths in sorted(grouped.items()))
        blocking_reasons.append(f"multiple CAD source engines present ({found}) - pass --source to disambiguate")
        return _finish_plan(
            project_dir=project_dir,
            project_name=project_name,
            source_engine=None,
            source_backend=None,
            source_files=[],
            selected_source=None,
            export_supported=False,
            export_tool=None,
            export_tool_available=None,
            export_command=None,
            output_directory=output_directory,
            expected_stl_files=[],
            existing_stl_files=[],
            stale_stl_files=[],
            output_collisions=[],
            decision="ambiguous_source",
            blocking_reasons=blocking_reasons,
            advisories=advisories,
            confirm_export=confirm_export,
        )
    elif not grouped:
        if unrecognized:
            return _unsupported_source_plan(project_dir, project_name, confirm_export, unrecognized, None)
        return _blocked_plan(
            project_dir,
            project_name,
            confirm_export,
            ["no CAD source found under cad/ - run factory generate-openscad or factory generate-cadquery first"],
        )
    else:
        ((engine, source_files),) = grouped.items()
        selected_source = None

    source_rel_paths = [_relative_path(p, project_dir) for p in source_files]
    source_fingerprints = {rel: _file_fingerprint(p) for rel, p in zip(source_rel_paths, source_files)}
    source_modified_times = {rel: _format_epoch(p.stat().st_mtime) for rel, p in zip(source_rel_paths, source_files)}

    expected_stl_paths = [_expected_stl_path(p, output_directory) for p in source_files]
    expected_stl_rel = [_relative_path(p, project_dir) for p in expected_stl_paths]

    prior_receipt = read_export_receipt(project_dir)
    existing_stl_files: list[str] = []
    stale_stl_files: list[str] = []
    output_collisions: list[dict[str, Any]] = []
    for source_path, stl_path, stl_rel, source_rel in zip(
        source_files, expected_stl_paths, expected_stl_rel, source_rel_paths
    ):
        freshness = _stl_freshness(source_path, stl_path, prior_receipt, source_rel)
        if freshness != "missing":
            existing_stl_files.append(stl_rel)
            output_collisions.append({"expected_path": stl_rel, "freshness": freshness})
            if freshness == "stale":
                stale_stl_files.append(stl_rel)

    if engine == "CadQuery":
        for source_rel in source_rel_paths:
            advisories.append(
                f"CadQuery source export remains a manual, human-run step in this repo - run "
                f"`{_cadquery_manual_command(source_rel)}` yourself, then re-run with --validate/--render "
                "to check the result. See docs/cad-backends.md."
            )
        if not is_cadquery_available():
            advisories.append(
                "the cadquery package is not installed in this environment either - the manual command "
                "above will also fail until it is"
            )
        return _finish_plan(
            project_dir=project_dir,
            project_name=project_name,
            source_engine="CadQuery",
            source_backend=_ENGINE_BACKEND_IDS["CadQuery"],
            source_files=source_rel_paths,
            source_fingerprints=source_fingerprints,
            source_modified_times=source_modified_times,
            selected_source=selected_source,
            export_supported=False,
            export_tool="manual (python <source>.py)",
            export_tool_available=False,
            export_command=None,
            output_directory=output_directory,
            expected_stl_files=expected_stl_rel,
            existing_stl_files=existing_stl_files,
            stale_stl_files=stale_stl_files,
            output_collisions=output_collisions,
            decision="manual_export_required",
            blocking_reasons=blocking_reasons,
            advisories=advisories,
            confirm_export=confirm_export,
        )

    # engine == "OpenSCAD" from here on.
    executable = resolve_openscad_executable()
    export_tool_available = executable is not None
    export_commands = (
        {rel: [executable, "-o", stl_rel, rel] for rel, stl_rel in zip(source_rel_paths, expected_stl_rel)}
        if executable
        else None
    )

    if not export_tool_available:
        blocking_reasons.append(
            "no local `openscad` executable found - install it via ai-3d-factory-installer, or export "
            "manually per slicer_review/openscad_export_instructions.md"
        )
        decision = "export_tool_missing"
    else:
        unresolved_collisions = [c for c in output_collisions if not overwrite_stl]
        if unresolved_collisions and not overwrite_stl:
            for collision in unresolved_collisions:
                blocking_reasons.append(
                    f"{collision['expected_path']} already exists ({collision['freshness']}) - pass "
                    "--overwrite-stl to replace it"
                )
            decision = "output_collision"
        elif overwrite_stl and output_collisions:
            advisories.append(f"--overwrite-stl passed - will overwrite {len(output_collisions)} existing STL(s)")
            decision = "allowed" if confirm_export else "needs_confirmation"
        else:
            decision = "allowed" if confirm_export else "needs_confirmation"

    return _finish_plan(
        project_dir=project_dir,
        project_name=project_name,
        source_engine="OpenSCAD",
        source_backend=_ENGINE_BACKEND_IDS["OpenSCAD"],
        source_files=source_rel_paths,
        source_fingerprints=source_fingerprints,
        source_modified_times=source_modified_times,
        selected_source=selected_source,
        export_supported=True,
        export_tool="OpenSCAD CLI",
        export_tool_available=export_tool_available,
        export_command=export_commands,
        output_directory=output_directory,
        expected_stl_files=expected_stl_rel,
        existing_stl_files=existing_stl_files,
        stale_stl_files=stale_stl_files,
        output_collisions=output_collisions,
        decision=decision,
        blocking_reasons=blocking_reasons,
        advisories=advisories,
        confirm_export=confirm_export,
    )


def _finish_plan(
    *,
    project_dir: Path,
    project_name: str,
    source_engine: str | None,
    source_backend: str | None,
    source_files: list[str],
    selected_source: str | None,
    export_supported: bool | None,
    export_tool: str | None,
    export_tool_available: bool | None,
    export_command: dict[str, list[str]] | None,
    output_directory: Path,
    expected_stl_files: list[str],
    existing_stl_files: list[str],
    stale_stl_files: list[str],
    output_collisions: list[dict[str, Any]],
    decision: str,
    blocking_reasons: list[str],
    advisories: list[str],
    confirm_export: bool,
    source_fingerprints: dict[str, str] | None = None,
    source_modified_times: dict[str, str] | None = None,
) -> dict[str, Any]:
    validation_plan = {
        "will_run": bool(expected_stl_files),
        "expected_reports": [str(_validation_report_path(project_dir, p).relative_to(project_dir)) for p in expected_stl_files],
    }
    render_plan = {
        "will_run": bool(expected_stl_files),
        "expected_renders": [str(_render_path(project_dir, p).relative_to(project_dir)) for p in expected_stl_files],
    }
    return {
        "project_path": str(project_dir),
        "project_name": project_name,
        "source_engine": source_engine,
        "source_backend": source_backend,
        "source_files": source_files,
        "source_fingerprints": source_fingerprints or {},
        "source_modified_times": source_modified_times or {},
        "selected_source": selected_source,
        "export_supported": export_supported,
        "export_tool": export_tool,
        "export_tool_available": export_tool_available,
        "export_command": export_command,
        "output_directory": _relative_path(output_directory, project_dir),
        "expected_stl_files": expected_stl_files,
        "existing_stl_files": existing_stl_files,
        "stale_stl_files": stale_stl_files,
        "output_collisions": output_collisions,
        "confirmation_required": decision == "needs_confirmation",
        "export_allowed": decision == "allowed",
        "decision": decision,
        "blocking_reasons": blocking_reasons,
        "advisories": advisories,
        "validation_plan": validation_plan,
        "render_plan": render_plan,
        "receipt_path": str(Path(project_dir) / GENERATED_DIRNAME / EXPORT_RECEIPT_FILENAME),
        "dry_run": not confirm_export,
    }


def _blocked_plan(project_dir: Path, project_name: str, confirm_export: bool, reasons: list[str]) -> dict[str, Any]:
    return _finish_plan(
        project_dir=project_dir,
        project_name=project_name,
        source_engine=None,
        source_backend=None,
        source_files=[],
        selected_source=None,
        export_supported=None,
        export_tool=None,
        export_tool_available=None,
        export_command=None,
        output_directory=Path(project_dir) / "stl",
        expected_stl_files=[],
        existing_stl_files=[],
        stale_stl_files=[],
        output_collisions=[],
        decision="blocked",
        blocking_reasons=reasons,
        advisories=[],
        confirm_export=confirm_export,
    )


def _unsupported_source_plan(
    project_dir: Path, project_name: str, confirm_export: bool, files: list[Path], _unused: None
) -> dict[str, Any]:
    rels = [_relative_path(p, project_dir) for p in files]
    return _finish_plan(
        project_dir=project_dir,
        project_name=project_name,
        source_engine=None,
        source_backend=None,
        source_files=rels,
        selected_source=None,
        export_supported=False,
        export_tool=None,
        export_tool_available=None,
        export_command=None,
        output_directory=Path(project_dir) / "stl",
        expected_stl_files=[],
        existing_stl_files=[],
        stale_stl_files=[],
        output_collisions=[],
        decision="unsupported_source",
        blocking_reasons=[f"unrecognized CAD source type(s): {', '.join(rels)} - only .scad and .py are supported"],
        advisories=[],
        confirm_export=confirm_export,
    )


def evaluate_export_pipeline_for_path(
    path: Path,
    *,
    source: str | None = None,
    output_dir: str | None = None,
    overwrite_stl: bool = False,
    confirm_export: bool = False,
) -> dict[str, Any]:
    """Convenience entry point `factory export-from-cad <path>` uses."""
    return plan_export(
        path, source=source, output_dir=output_dir, overwrite_stl=overwrite_stl, confirm_export=confirm_export
    )


# ---------------------------------------------------------------------------
# Execution - the only write/subprocess paths in this module. Only ever
# called when a plan's decision is "allowed" (OpenSCAD export) or
# regardless-of-decision for validate/render against an STL that already
# exists (see run_export_pipeline()).
# ---------------------------------------------------------------------------


def run_export(project_dir: Path, plan: dict[str, Any], source_rel: str) -> dict[str, Any]:
    """Execute one confirmed, allowed OpenSCAD export for `source_rel` (one
    entry of `plan["source_files"]`). Only ever called when
    `plan["decision"] == "allowed"` - raises `ValueError` otherwise, as a
    defensive guard mirroring `factory.generation_gate.run_generation()`.

    Uses argument-list subprocess execution (never a shell string), a
    bounded timeout, and verifies the output actually exists and is
    non-empty before ever reporting success - a zero exit code alone is
    never treated as success. Writes only inside `plan["output_directory"]`.
    Never invokes a slicer or printer.
    """
    if plan.get("decision") != "allowed":
        raise ValueError(
            f"run_export() called with decision {plan.get('decision')!r}, not 'allowed' - "
            "this is a programming error in the caller, not a user-facing condition."
        )

    project_dir = Path(project_dir)
    source_path = project_dir / source_rel
    stl_rel = f"{plan['output_directory']}/{Path(source_rel).stem}.stl"
    stl_path = project_dir / stl_rel

    result: dict[str, Any] = {
        "source_file": source_rel,
        "output_stl": stl_rel,
        "export_tool": plan.get("export_tool"),
        "command": None,
        "started_at": project_store.utc_now_iso(),
        "completed_at": None,
        "duration_seconds": None,
        "exit_code": None,
        "stdout_summary": "",
        "stderr_summary": "",
        "success": False,
        "errors": [],
    }

    if not source_path.is_file():
        result["errors"].append(f"source file no longer exists: {source_rel}")
        result["completed_at"] = project_store.utc_now_iso()
        return result

    pre_export_fingerprint = _file_fingerprint(source_path)
    recorded_fingerprint = plan.get("source_fingerprints", {}).get(source_rel)
    if recorded_fingerprint and pre_export_fingerprint != recorded_fingerprint:
        result["errors"].append(
            f"source changed since planning ({source_rel}) - re-run the plan before exporting"
        )
        result["completed_at"] = project_store.utc_now_iso()
        return result

    executable = resolve_openscad_executable()
    if not executable:
        result["errors"].append("no local `openscad` executable found")
        result["completed_at"] = project_store.utc_now_iso()
        return result

    command = [executable, "-o", str(stl_path), str(source_path)]
    result["command"] = command

    start = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=EXPORT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        result["duration_seconds"] = round(time.monotonic() - start, 3)
        result["errors"].append(f"export timed out after {EXPORT_TIMEOUT_SECONDS}s")
        result["stdout_summary"] = (exc.stdout or "")[:2000] if isinstance(exc.stdout, str) else ""
        result["stderr_summary"] = (exc.stderr or "")[:2000] if isinstance(exc.stderr, str) else ""
        result["completed_at"] = project_store.utc_now_iso()
        return result
    except OSError as exc:
        result["duration_seconds"] = round(time.monotonic() - start, 3)
        result["errors"].append(f"failed to launch exporter: {exc}")
        result["completed_at"] = project_store.utc_now_iso()
        return result

    duration = round(time.monotonic() - start, 3)
    result["duration_seconds"] = duration
    result["exit_code"] = completed.returncode
    result["stdout_summary"] = (completed.stdout or "")[:2000]
    result["stderr_summary"] = (completed.stderr or "")[:2000]
    result["completed_at"] = project_store.utc_now_iso()

    if completed.returncode != 0:
        result["errors"].append(f"exporter exited with code {completed.returncode}")
        return result

    # A zero exit code alone is never treated as success - verify the file
    # actually exists, is non-empty, and looks like a mesh export.
    if not stl_path.is_file():
        result["errors"].append("exporter exited 0 but the expected output file was not created")
        return result

    size_bytes = stl_path.stat().st_size
    if size_bytes == 0:
        result["errors"].append("exported STL is empty (0 bytes)")
        return result

    if stl_path.suffix.lower() != ".stl":
        result["errors"].append(f"unexpected output extension: {stl_path.suffix!r}")
        return result

    result["success"] = True
    result["output_size_bytes"] = size_bytes
    result["output_fingerprint"] = _file_fingerprint(stl_path)
    result["source_fingerprint"] = pre_export_fingerprint
    result["export_tool_version"] = _probe_tool_version(executable)
    return result


def _probe_tool_version(executable: str) -> str | None:
    """Best-effort `<tool> --version` probe - never raises, never blocks
    export on failure. Execution-time only (never called during planning),
    so a dry-run plan never spawns a subprocess.
    """
    try:
        completed = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=_VERSION_PROBE_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (completed.stdout or completed.stderr or "").strip()
    return text or None


def run_validation(project_dir: Path, stl_rel_path: str, printer: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the existing mesh validator against one exported STL and write
    its report using the exact same convention `factory validate` already
    uses (`validation/<stem>_validation.json`). Never re-implements mesh
    validation - calls `factory.validators.mesh_validate.validate_mesh()`
    directly, and never suppresses or reinterprets its PASS/WARN/FAIL
    result (only normalizes the label - see `_normalize_validation_status()`).
    """
    project_dir = Path(project_dir)
    stl_path = project_dir / stl_rel_path
    if printer is None:
        primary_id = knowledge.get_primary_printer_id()
        printer = knowledge.get_printer(primary_id) if primary_id else None

    report = validate_mesh(stl_path, printer)
    report_path = _validation_report_path(project_dir, stl_rel_path)
    project_store.save_json(report_path, report)

    return {
        "status": _normalize_validation_status(report),
        "report_path": _relative_path(report_path, project_dir),
        "overall_status": report.get("overall_status"),
    }


def _normalize_validation_status(report: dict[str, Any]) -> str:
    overall = report.get("overall_status")
    if overall == "FAIL":
        trimesh_missing = any(
            c.get("name") == "trimesh_available" and c.get("status") == "FAIL" for c in report.get("checks", [])
        )
        return "unavailable" if trimesh_missing else "failed"
    if overall == "WARN":
        return "passed_with_warnings"
    if overall == "PASS":
        return "passed"
    return "failed"


def run_render(project_dir: Path, stl_rel_path: str) -> dict[str, Any]:
    """Run the existing preview renderer against one exported STL, using the
    current `renders/<stem>_preview.png` convention. Never re-implements
    rendering - calls `factory.previews.render_preview.render_preview()`
    directly.
    """
    project_dir = Path(project_dir)
    stl_path = project_dir / stl_rel_path
    output_path = _render_path(project_dir, stl_rel_path)

    result = render_preview(stl_path, output_path)
    status = "passed" if result["status"] == "PASS" else "failed"

    render_record = {"status": status, "render_path": None, "detail": result["detail"]}
    if status == "passed" and output_path.is_file() and output_path.stat().st_size > 0:
        render_record["render_path"] = _relative_path(output_path, project_dir)
        render_record["size_bytes"] = output_path.stat().st_size
    elif status == "passed":
        # Defensive: render_preview() reported PASS but the file is missing
        # or empty - never trust a reported success without verifying it.
        render_record["status"] = "failed"
        render_record["detail"] = "renderer reported success but no non-empty output file was found"
    return render_record


def run_export_pipeline(
    project_dir: Path,
    plan: dict[str, Any],
    *,
    validate: bool = False,
    render: bool = False,
    all_steps: bool = False,
    resume: bool = False,
) -> dict[str, Any]:
    """Orchestrate export (+ optional validate/render) for every source file
    in `plan["source_files"]`, then write the export receipt.

    - CadQuery sources are never exported here (see `plan_export()`); if
      `validate`/`render`/`all_steps` is requested and the expected STL
      already exists on disk (a human already ran the manual command),
      validation/render still run against it - those two steps never
      touch CAD source and are safe regardless of which engine produced
      the mesh.
    - OpenSCAD sources are only exported when `plan["decision"] ==
      "allowed"`.
    - `resume=True` skips a source file's export/validate/render step if
      the receipt already records it as current for that exact source
      fingerprint - see docs/export-pipeline.md "Resume behavior".

    Returns `{"per_source": [...], "pipeline_state": str}` and writes
    `generated/export_receipt.json` - unless nothing was actually
    attempted (e.g. every file was already current under `--resume`), in
    which case the prior receipt is left untouched.
    """
    validate = validate or all_steps
    render = render or all_steps
    project_dir = Path(project_dir)
    prior_receipt = read_export_receipt(project_dir)
    per_source: list[dict[str, Any]] = []
    any_attempted = False

    for source_rel in plan["source_files"]:
        stl_rel = f"{plan['output_directory']}/{Path(source_rel).stem}.stl"
        record: dict[str, Any] = {
            "source_file": source_rel,
            "output_stl": stl_rel,
            "export": None,
            "validation": {"status": "not_run"},
            "render": {"status": "not_run"},
        }

        source_path = project_dir / source_rel
        current_fingerprint = _file_fingerprint(source_path) if source_path.is_file() else None
        prior_record = _prior_record_for(prior_receipt, source_rel)
        already_current = (
            resume
            and prior_record is not None
            and prior_record.get("export", {}).get("success")
            and prior_record["export"].get("source_fingerprint") == current_fingerprint
            and (project_dir / stl_rel).is_file()
        )

        if plan["source_engine"] == "OpenSCAD" and plan["decision"] == "allowed" and not already_current:
            any_attempted = True
            export_result = run_export(project_dir, plan, source_rel)
            record["export"] = export_result
        elif already_current:
            record["export"] = prior_record["export"]
        elif plan["source_engine"] == "CadQuery":
            record["export"] = {
                "success": None,
                "manual_command": _cadquery_manual_command(source_rel),
                "note": "CadQuery export remains a manual, human-run step - not executed by this pipeline.",
            }
        else:
            record["export"] = prior_record["export"] if prior_record else None

        stl_exists = (project_dir / stl_rel).is_file()
        export_ok = bool(record["export"] and record["export"].get("success"))

        if (validate or render) and stl_exists and (export_ok or plan["source_engine"] == "CadQuery" or already_current):
            if validate:
                if already_current and prior_record and prior_record.get("validation", {}).get("status") not in (None, "not_run"):
                    record["validation"] = prior_record["validation"]
                else:
                    any_attempted = True
                    record["validation"] = run_validation(project_dir, stl_rel)
            if render:
                if already_current and prior_record and prior_record.get("render", {}).get("status") not in (None, "not_run"):
                    record["render"] = prior_record["render"]
                else:
                    any_attempted = True
                    record["render"] = run_render(project_dir, stl_rel)

        record["pipeline_state"] = _record_pipeline_state(record)
        per_source.append(record)

    overall_state = _overall_pipeline_state(per_source)

    multipart_check_results: list[dict[str, Any]] = []
    if validate and len(plan["source_files"]) > 1:
        multipart_check_results = run_multipart_check(project_dir)

    if any_attempted:
        write_export_receipt(project_dir, per_source, overall_state)

    return {"per_source": per_source, "pipeline_state": overall_state, "multipart_check": multipart_check_results}


def run_multipart_check(project_dir: Path) -> list[dict[str, Any]]:
    """Reuse `factory.validators.multipart_check.check_manifest()` against
    this project's `part_manifest.json` - never re-implements multipart/
    manifest consistency checks. Read-only aside from being called as part
    of a confirmed pipeline run; this function itself never writes
    anything (its results are folded into the export receipt by the
    caller).
    """
    project_dir = Path(project_dir)
    manifest_path = project_dir / "part_manifest.json"
    if not manifest_path.is_file():
        return []
    manifest = project_store.load_json(manifest_path)

    build_plan_path = project_dir / "build_plan.json"
    required_part_names = None
    if build_plan_path.is_file():
        build_plan = project_store.load_json(build_plan_path)
        required_part_names = [
            p.get("part_name") for p in build_plan.get("required_parts", []) if p.get("part_name")
        ] or None

    return check_multipart_manifest(manifest, project_dir, required_part_names=required_part_names)


def _prior_record_for(prior_receipt: dict[str, Any] | None, source_rel: str) -> dict[str, Any] | None:
    if not prior_receipt:
        return None
    for record in prior_receipt.get("exports") or []:
        if record.get("source_file") == source_rel:
            return record
    return None


def _record_pipeline_state(record: dict[str, Any]) -> str:
    export = record.get("export")
    if export is not None and export.get("success") is False:
        return "export_failed"
    validation_status = record.get("validation", {}).get("status", "not_run")
    if validation_status == "failed":
        return "validation_failed"
    render_status = record.get("render", {}).get("status", "not_run")
    if render_status == "failed":
        return "render_failed"
    if validation_status == "not_run" or render_status == "not_run":
        return "partial_pipeline"
    return "completed"


def _overall_pipeline_state(per_source: list[dict[str, Any]]) -> str:
    if not per_source:
        return "partial_pipeline"
    states = {r["pipeline_state"] for r in per_source}
    for failure_state in ("export_failed", "validation_failed", "render_failed"):
        if failure_state in states:
            return failure_state
    if states == {"completed"}:
        return "completed"
    return "partial_pipeline"


# ---------------------------------------------------------------------------
# Execution receipts - a sibling of Phase 34's generation_receipt.json.
# ---------------------------------------------------------------------------


def read_export_receipt(project_dir: Path) -> dict[str, Any] | None:
    """Read-only: `<project_dir>/generated/export_receipt.json` if it
    exists, else `None`. Never writes, never triggers export.
    """
    receipt_path = Path(project_dir) / GENERATED_DIRNAME / EXPORT_RECEIPT_FILENAME
    if not receipt_path.is_file():
        return None
    try:
        return project_store.load_json(receipt_path)
    except (OSError, ValueError):
        return None


def write_export_receipt(project_dir: Path, per_source: list[dict[str, Any]], pipeline_state: str) -> Path:
    """Upsert `generated/export_receipt.json`, one entry per source file,
    keyed by `source_file` - the same upsert-by-key pattern
    `factory.openscad.generate._upsert_manifest_parts()` and
    `factory.cad.manifest.upsert_cadquery_manifest_entry()` already use for
    `part_manifest.json`. A record for a source file this run did not touch
    is preserved untouched - **a failed or partial run never destroys a
    prior successful record for a different (or the same, if this run
    didn't touch it) source file.**
    """
    project_dir = Path(project_dir)
    receipt_path = project_dir / GENERATED_DIRNAME / EXPORT_RECEIPT_FILENAME
    receipt = read_export_receipt(project_dir) or {"project": str(project_dir), "no_automatic_print": True, "exports": []}
    receipt["no_automatic_print"] = True
    exports = receipt.setdefault("exports", [])
    by_source = {e.get("source_file"): e for e in exports}

    for record in per_source:
        source_file = record["source_file"]
        by_source[source_file] = record
    receipt["exports"] = list(by_source.values())
    receipt["last_completed_stage"] = pipeline_state
    receipt["pipeline_state"] = pipeline_state
    receipt["updated_at"] = project_store.utc_now_iso()

    project_store.save_json(receipt_path, receipt)
    return receipt_path


def summarize_export_pipeline(project_dir: Path) -> dict[str, Any]:
    """Compact, additive, read-only summary for
    `factory.project_inspection.summarize_project()`'s
    `export_pipeline_summary` field and the Preview Board's
    "Post-Generation Pipeline" card. Always a dry-run evaluation - never
    exports, validates, renders, or invokes a subprocess. Stale-render
    detection reuses `factory.render_coverage.compute_render_coverage()`
    (mtime-based render-vs-mesh comparison) rather than re-deriving it.
    """
    project_dir = Path(project_dir)
    plan = plan_export(project_dir)
    receipt = read_export_receipt(project_dir)
    render_coverage = compute_render_coverage(project_dir)

    expected = plan["expected_stl_files"]
    current_count = sum(1 for c in plan["output_collisions"] if c["freshness"] == "current")
    stale_count = len(plan["stale_stl_files"])

    validation_statuses = []
    preview_statuses = []
    if receipt:
        for record in receipt.get("exports", []):
            v_status = record.get("validation", {}).get("status")
            if v_status and v_status != "not_run":
                validation_statuses.append(v_status)
            r_status = record.get("render", {}).get("status")
            if r_status and r_status != "not_run":
                render_rel = record.get("render", {}).get("render_path")
                is_stale = render_rel is not None and render_rel in render_coverage["stale_renders"]
                preview_statuses.append("stale" if is_stale else r_status)

    pipeline_complete = bool(receipt) and receipt.get("pipeline_state") == "completed"
    cad_source_status = "current" if plan["source_files"] else "missing"
    if not expected:
        stl_status = "missing"
    elif stale_count:
        stl_status = "stale"
    elif current_count == len(expected):
        stl_status = "current"
    else:
        stl_status = "missing"

    return {
        "decision": plan["decision"],
        "source_engine": plan["source_engine"],
        "source_count": len(plan["source_files"]),
        "exporter": plan["export_tool"],
        "exporter_available": plan["export_tool_available"],
        "expected_stl_count": len(expected),
        "current_stl_count": current_count,
        "stale_stl_count": stale_count,
        "cad_source_status": cad_source_status,
        "stl_status": stl_status,
        "validation_status": _aggregate_status(validation_statuses),
        "preview_status": _aggregate_status(preview_statuses),
        "last_completed_stage": receipt.get("last_completed_stage") if receipt else None,
        "pipeline_complete": pipeline_complete,
        "next_step": None if pipeline_complete else _next_step_label(plan, receipt),
        "blockers": list(plan["blocking_reasons"]),
        "receipt_path": plan["receipt_path"] if receipt else None,
    }


_NEXT_STEP_BY_DECISION = {
    "blocked": "Add CAD source (factory generate-openscad / generate-cadquery)",
    "unsupported_source": "Remove or replace unrecognized CAD source",
    "ambiguous_source": "Disambiguate CAD source (--source)",
    "manual_export_required": "Manually export CadQuery source, then re-run with --validate --render",
    "export_tool_missing": "Install OpenSCAD",
    "output_collision": "Resolve output collision (--overwrite-stl) or review the existing STL",
    "needs_confirmation": "Confirm STL export (--confirm-export)",
}


def _next_step_label(plan: dict[str, Any], receipt: dict[str, Any] | None) -> str:
    """Human-facing "what to do next" label for the Preview Board's compact
    card and the CLI - derived entirely from the already-computed plan/
    receipt, never a new judgment about readiness.
    """
    label = _NEXT_STEP_BY_DECISION.get(plan["decision"])
    if label:
        return label
    if plan["decision"] == "allowed":
        return "Run export (--confirm-export)"
    if not receipt:
        return "Run validation and preview (--validate --render)"
    for record in receipt.get("exports", []):
        if record.get("validation", {}).get("status") in (None, "not_run"):
            return "Run validation (--validate)"
        if record.get("render", {}).get("status") in (None, "not_run"):
            return "Run preview render (--render)"
    return "Review pipeline state"


def _aggregate_status(statuses: list[str]) -> str:
    if not statuses:
        return "not_run"
    unique = set(statuses)
    if len(unique) == 1:
        return next(iter(unique))
    return "partial"


def build_artifact_registry(project_dir: Path) -> dict[str, Any]:
    """Normalize this project's full artifact state (CAD source, STL,
    validation, preview, review, receipts) into one read-only structure -
    the `artifact_registry` field of `factory export-from-cad --json`.

    Reuses the plan (`plan_export()`) and both receipts
    (`read_export_receipt()`, and Phase 34's
    `factory.generation_gate.read_last_execution_receipt()`) rather than
    re-deriving anything. **"review" is deliberately a pointer string, not
    a computed result** - `factory.review_gate.evaluate_review_gate()`
    needs `factory.project_inspection.summarize_project()`, and this
    module must stay a leaf the same way `factory.generation_gate` does
    (`project_inspection` imports *this* module for its own additive
    field, so the reverse import would be circular). Never exports,
    validates, renders, or invokes a subprocess.
    """
    project_dir = Path(project_dir)
    plan = plan_export(project_dir)
    export_receipt = read_export_receipt(project_dir)
    generation_receipt_path = Path(project_dir) / GENERATED_DIRNAME / "generation_receipt.json"

    collision_by_path = {c["expected_path"]: c["freshness"] for c in plan["output_collisions"]}

    cad_entries = []
    for rel in plan["source_files"]:
        source_path = project_dir / rel
        cad_entries.append(
            {
                "path": rel,
                "type": Path(rel).suffix.lstrip("."),
                "engine": plan["source_engine"],
                "size_bytes": source_path.stat().st_size if source_path.is_file() else None,
                "fingerprint": plan["source_fingerprints"].get(rel),
                "status": "current",  # the source itself is always "current" relative to itself
            }
        )

    stl_entries = []
    validation_entries = []
    preview_entries = []
    for stl_rel in plan["expected_stl_files"]:
        stl_path = project_dir / stl_rel
        record = _prior_record_for(export_receipt, _source_for_stl(plan, stl_rel))
        stl_entries.append(
            {
                "path": stl_rel,
                "size_bytes": stl_path.stat().st_size if stl_path.is_file() else None,
                "fingerprint": (record or {}).get("export", {}).get("output_fingerprint") if record else None,
                "source_cad": _source_for_stl(plan, stl_rel),
                "status": collision_by_path.get(stl_rel, "missing"),
                "validation_status": (record or {}).get("validation", {}).get("status", "not_run") if record else "not_run",
            }
        )
        validation = (record or {}).get("validation") if record else None
        if validation:
            report = project_store.load_json(project_dir / validation["report_path"]) if validation.get("report_path") and (project_dir / validation["report_path"]).is_file() else {}
            checks = report.get("checks", [])
            validation_entries.append(
                {
                    "report_path": validation.get("report_path"),
                    "validator": "factory.validators.mesh_validate",
                    "status": validation.get("status"),
                    "warning_count": sum(1 for c in checks if c.get("status") == "WARN"),
                    "failure_count": sum(1 for c in checks if c.get("status") == "FAIL"),
                }
            )
        render = (record or {}).get("render") if record else None
        if render and render.get("status") != "not_run":
            render_path = project_dir / render["render_path"] if render.get("render_path") else None
            preview_entries.append(
                {
                    "path": render.get("render_path"),
                    "size_bytes": render_path.stat().st_size if render_path and render_path.is_file() else None,
                    "source_stl": stl_rel,
                    "status": collision_by_path.get(stl_rel, "missing"),
                }
            )

    return {
        "cad_source": cad_entries,
        "stl": stl_entries,
        "validation": validation_entries,
        "preview": preview_entries,
        "review": {
            "note": "Not computed here - run `factory review-gate <project_dir>` for human slicer-review readiness.",
        },
        "receipts": {
            "generation_receipt_path": str(generation_receipt_path) if generation_receipt_path.is_file() else None,
            "export_receipt_path": plan["receipt_path"] if export_receipt else None,
            "last_completed_stage": export_receipt.get("last_completed_stage") if export_receipt else None,
        },
    }


def _source_for_stl(plan: dict[str, Any], stl_rel: str) -> str | None:
    for source_rel, expected in zip(plan["source_files"], plan["expected_stl_files"]):
        if expected == stl_rel:
            return source_rel
    return None

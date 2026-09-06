"""Phase 45: Blender bounded headless execution adapter.

The only module in this repo that ever passes Blender to `subprocess`.
Every invocation here is: an absolute, already-resolved binary path (from
`factory.blender_gate.resolve_blender_binary()`, itself sourced from
Phase 43's `.app` bundle detection - never a fresh PATH lookup, never a
guess), an argument list (never a shell string), `shell=False` (the
default - never overridden), a hard timeout, `--background` (headless,
no visible window - Blender's own standard, universally-documented
non-interactive mode), `--factory-startup` (skip the user's
`startup.blend`), `-Y`/`--disable-autoexec` (defense in depth - already
Blender's own default), and `--offline-mode` (force network off
regardless of the user's Blender preference).

    Detected -> Metadata Qualified -> Headless Runtime Qualified ->
    Fixture Execution Qualified -> Adapter Qualified ->
    Project Execution Eligible -> Explicit Human Confirmation ->
    Actual Project Execution

This module reaches, at most, "Adapter Qualified" - never further.
`project_execution_approved` is hardcoded `False` on every result this
module returns, with no code path that ever sets it `True`.

Two, and only two, real Blender invocations exist in this module:

1. `verify_headless_runtime()` - `blender --background --factory-startup
   -Y --offline-mode --version`. No `-P`/`--python`/`--python-expr` flag
   is ever passed here - Blender executes zero Python of any kind for
   this check. Run fresh on every `factory blender qualify` call; never
   cached, never trusted from a prior run.
2. `run_fixture_qualification()` - the same flags, plus `--python
   blender_fixtures/factory_qualification_fixture.py -- <tmp_stl_path>`
   and `--python-exit-code 1` (a distinguishable non-zero exit if the
   fixture script itself raises). The script is the one, fixed,
   Factory-owned, repository-reviewed file at
   `factory.blender_gate.FIXTURE_SCRIPT_PATH` - never a path any caller
   can override, never anything derived from project or user input. See
   that file's own docstring and `tests/test_blender_adapter_safety.py`
   for the static safety contract it is held to.

Reuses rather than duplicates:

- `factory.validators.mesh_validate.validate_mesh()` - the same Factory
  mesh validator Phase 44's OpenSCAD qualification and
  `factory.export_pipeline.run_validation()` both already call. No
  Blender-specific validator exists or is added here.
- `factory.previews.render_preview.render_preview()` - the same local
  trimesh+matplotlib preview `factory render` already uses. No
  Blender-specific render/visual-QA subsystem exists or is added here;
  Blender's own render engine is never invoked for this purpose.

No install, no upgrade, no GUI launch, no AppleScript/`osascript`/`open`/
`pkill`, no add-on install, no network call (see `--offline-mode` above),
no printer contact, no G-code generation, no Homebrew mutation, no
persisted qualification state, anywhere in this module.

See `docs/blender-adapter.md`.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from factory import blender_gate
from factory.previews.render_preview import render_preview
from factory.validators.mesh_validate import validate_mesh

# ---------------------------------------------------------------------------
# Vocabulary - stable, closed, documented in docs/blender-adapter.md
# ---------------------------------------------------------------------------

HEADLESS_RUNTIME_STATUSES = ("verified", "not_verified", "not_attempted", "requires_manual_desktop_qualification")
FIXTURE_EXECUTION_STATUSES = ("not_run", "succeeded", "failed", "skipped")
ADAPTER_QUALIFICATION_STATUSES = ("not_detected", "not_qualified", "partially_qualified", "qualified")
CHECK_STATUSES = ("pass", "warn", "fail", "skip")

_HEADLESS_PROBE_TIMEOUT_SECONDS = 60
_FIXTURE_TIMEOUT_SECONDS = 180

_SAFETY_BLOCK: dict[str, bool] = {
    "software_installed": False,
    "software_upgraded": False,
    "addon_installed": False,
    "gui_launched": False,
    "network_used": False,
    "slicer_executed": False,
    "gcode_generated": False,
    "printer_contacted": False,
    "project_files_modified": False,
    "automatic_print_allowed": False,
}

# Common, always-present safety flags for every real Blender invocation
# this module makes - see the module docstring for what each one buys.
_COMMON_SAFETY_FLAGS = ("--background", "--factory-startup", "-Y", "--offline-mode")


def _elapsed_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 1)


def _check(check_id: str, label: str, status: str, evidence: str) -> dict[str, Any]:
    assert status in CHECK_STATUSES, status
    return {"check_id": check_id, "label": label, "status": status, "evidence": evidence}


def _empty_result(*, reason: str) -> dict[str, Any]:
    return {
        "tool_id": "blender",
        "display_name": "Blender",
        "detected": False,
        "detected_version": "unknown",
        "detected_path": None,
        "headless_runtime_status": "not_attempted",
        "headless_runtime_evidence": reason,
        "fixture_execution_status": "skipped",
        "fixture_checks": [],
        "adapter_qualification_status": "not_detected",
        "warnings": [],
        "errors": [reason],
        "temporary_artifacts_created": False,
        "temporary_artifacts_cleaned": True,
        "unexpected_files": [],
        "network_used": False,
        "gui_launched": False,
        "printer_contacted": False,
        "automatic_print_allowed": False,
        "project_execution_approved": False,
        "duration_ms": 0.0,
    }


def verify_headless_runtime(binary_path: str) -> dict[str, Any]:
    """One bounded, real `blender --background --factory-startup -Y
    --offline-mode --version` subprocess call. Argument list, `shell=False`,
    hard timeout, no Python of any kind executed. Returns a check dict."""
    command = [binary_path, *_COMMON_SAFETY_FLAGS, "--version"]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=_HEADLESS_PROBE_TIMEOUT_SECONDS, shell=False)
    except subprocess.TimeoutExpired:
        return _check("blender_headless_runtime", "Headless runtime verified", "fail", f"timed out after {_HEADLESS_PROBE_TIMEOUT_SECONDS}s")
    except OSError as exc:
        return _check("blender_headless_runtime", "Headless runtime verified", "fail", f"failed to launch: {exc}")

    if completed.returncode != 0:
        return _check(
            "blender_headless_runtime",
            "Headless runtime verified",
            "fail",
            f"exit code {completed.returncode}: {(completed.stderr or '')[:300]}",
        )
    stdout = (completed.stdout or "").strip()
    return _check("blender_headless_runtime", "Headless runtime verified", "pass", stdout.splitlines()[0] if stdout else "exit code 0")


def _inventory(directory: Path) -> set[str]:
    return {str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()}


def run_fixture_qualification(binary_path: str) -> dict[str, Any]:
    """The full, bounded, one-shot fixture pipeline. Always calls
    `verify_headless_runtime()` first - fresh, never trusted from a prior
    call. Only proceeds to the fixture script if that check passes.

    Every temporary file lives inside one `tempfile.TemporaryDirectory()`,
    inventoried before and after the single Blender invocation (unexpected-
    file detection - any file besides the expected STL is reported as a
    warning; nothing can escape the directory since the output path is
    constructed by this function, never by the fixture script or any
    external input). Cleanup is verified with an explicit `Path.exists()`
    check after the context manager exits, never assumed.
    """
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[str] = []
    unexpected_files: list[str] = []

    headless_check = verify_headless_runtime(binary_path)
    checks.append(headless_check)
    if headless_check["status"] != "pass":
        errors.append("Headless runtime check failed - fixture execution skipped.")
        return {
            "fixture_execution_status": "skipped",
            "checks": checks,
            "warnings": warnings,
            "errors": errors,
            "temporary_artifacts_created": False,
            "temporary_artifacts_cleaned": True,
            "unexpected_files": unexpected_files,
        }

    fixture_export_ok = False
    validation_status: str | None = None
    preview_status: str | None = None
    temporary_artifacts_created = False
    temporary_artifacts_cleaned = True
    tmp_dir_path: str | None = None

    try:
        with tempfile.TemporaryDirectory(prefix="factory-blender-qualify-") as tmp_dir:
            tmp_dir_path = tmp_dir
            temporary_artifacts_created = True
            tmp_dir_obj = Path(tmp_dir)
            before = _inventory(tmp_dir_obj)
            stl_path = tmp_dir_obj / blender_gate.FIXTURE_OUTPUT_FILENAME

            command = [
                binary_path,
                *_COMMON_SAFETY_FLAGS,
                "--python-exit-code",
                "1",
                "--python",
                str(blender_gate.FIXTURE_SCRIPT_PATH),
                "--",
                str(stl_path),
            ]
            try:
                completed = subprocess.run(command, capture_output=True, text=True, timeout=_FIXTURE_TIMEOUT_SECONDS, shell=False)
            except subprocess.TimeoutExpired:
                checks.append(_check("blender_fixture_exported", "Fixture executed", "fail", f"timed out after {_FIXTURE_TIMEOUT_SECONDS}s"))
                errors.append("Blender fixture execution timed out")
            except OSError as exc:
                checks.append(_check("blender_fixture_exported", "Fixture executed", "fail", f"failed to launch: {exc}"))
                errors.append("failed to launch Blender for fixture execution")
            else:
                if completed.returncode == 0:
                    checks.append(_check("blender_fixture_exported", "Fixture executed", "pass", "exit code 0"))
                else:
                    checks.append(
                        _check(
                            "blender_fixture_exported",
                            "Fixture executed",
                            "fail",
                            f"exit code {completed.returncode}: {(completed.stderr or '')[:300]}",
                        )
                    )
                    errors.append(f"Blender fixture execution exited with code {completed.returncode}")

                after = _inventory(tmp_dir_obj)
                expected_relative = stl_path.relative_to(tmp_dir_obj).as_posix()
                unexpected_files = sorted((after - before) - {expected_relative})
                if unexpected_files:
                    warnings.append(f"Blender created unexpected file(s) in the temp directory: {unexpected_files}")

                stl_exists = stl_path.is_file()
                stl_nonempty = stl_exists and stl_path.stat().st_size > 0
                if stl_exists and stl_nonempty:
                    checks.append(_check("blender_stl_output_valid", "STL exists and is non-empty", "pass", f"{stl_path.stat().st_size} bytes"))
                    fixture_export_ok = True
                else:
                    reason = "missing" if not stl_exists else "empty"
                    checks.append(_check("blender_stl_output_valid", "STL exists and is non-empty", "fail", reason))
                    errors.append(f"exported STL {reason}")

                if fixture_export_ok:
                    try:
                        report = validate_mesh(stl_path)
                        overall = report.get("overall_status")
                        validation_status = "pass" if overall == "PASS" else ("warn" if overall == "WARN" else "fail")
                        checks.append(_check("blender_factory_validation", "Factory mesh validation completed", validation_status, f"overall_status={overall}"))
                        if validation_status == "fail":
                            errors.append("Factory validation reported FAIL for the qualification fixture")
                    except Exception as exc:  # validator failure must not abort qualification
                        validation_status = "fail"
                        checks.append(_check("blender_factory_validation", "Factory mesh validation completed", "fail", f"{type(exc).__name__}: {exc}"))

                    try:
                        preview_path = tmp_dir_obj / "qualification_fixture_preview.png"
                        preview_result = render_preview(stl_path, preview_path)
                        preview_status = preview_result.get("status")
                        preview_check_status = "pass" if preview_status == "PASS" else ("warn" if preview_status == "WARN" else "fail")
                        checks.append(_check("blender_factory_preview", "Factory preview render completed", preview_check_status, preview_result.get("detail", "")))
                        if preview_check_status == "fail":
                            errors.append("Factory preview render failed for the qualification fixture")
                    except Exception as exc:  # preview failure must not abort qualification
                        preview_status = "FAIL"
                        checks.append(_check("blender_factory_preview", "Factory preview render completed", "fail", f"{type(exc).__name__}: {exc}"))
                else:
                    checks.append(_check("blender_factory_validation", "Factory mesh validation completed", "skip", "no STL to validate"))
                    checks.append(_check("blender_factory_preview", "Factory preview render completed", "skip", "no STL to render"))

        temporary_artifacts_cleaned = not Path(tmp_dir_path).exists()
        checks.append(_check("blender_cleanup", "Temporary artifacts cleaned", "pass" if temporary_artifacts_cleaned else "fail", tmp_dir_path or ""))
    except Exception as exc:  # never let a fixture/cleanup surprise abort qualification
        temporary_artifacts_cleaned = not Path(tmp_dir_path).exists() if tmp_dir_path else True
        checks.append(_check("blender_cleanup", "Temporary artifacts cleaned", "pass" if temporary_artifacts_cleaned else "fail", str(exc)))
        errors.append(f"unexpected error during fixture qualification: {exc}")

    all_pass_or_warn = fixture_export_ok and validation_status in ("pass", "warn") and preview_status in ("PASS", "WARN")
    fixture_execution_status = "succeeded" if all_pass_or_warn else "failed"

    return {
        "fixture_execution_status": fixture_execution_status,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "temporary_artifacts_created": temporary_artifacts_created,
        "temporary_artifacts_cleaned": temporary_artifacts_cleaned,
        "unexpected_files": unexpected_files,
    }


def qualify_blender_adapter(*, confirm_fixture: bool = False) -> dict[str, Any]:
    """Public entry point `factory blender qualify [--confirm-fixture]`
    uses. Always attempts `verify_headless_runtime()` fresh (one bounded,
    real, Python-free subprocess call). Only additionally runs
    `run_fixture_qualification()` when `confirm_fixture=True` - the
    explicit human confirmation this phase's whole design hinges on.
    `project_execution_approved` is hardcoded `False` regardless of
    outcome."""
    start = time.monotonic()
    resolved = blender_gate.resolve_blender_binary()

    if not resolved["detected"]:
        result = _empty_result(reason="Blender not detected locally (no Contents/MacOS/Blender executable found).")
        result["duration_ms"] = _elapsed_ms(start)
        return result

    binary_path = resolved["binary_path"]
    detected_version = resolved["detected_version"]

    checks: list[dict[str, Any]] = [_check("blender_binary_detected", "Binary detected", "pass", binary_path)]
    warnings = list(resolved["warnings"])
    errors: list[str] = []
    fixture_execution_status = "not_run"
    unexpected_files: list[str] = []
    temporary_artifacts_created = False
    temporary_artifacts_cleaned = True

    if not confirm_fixture:
        headless_check = verify_headless_runtime(binary_path)
        checks.append(headless_check)
        headless_status = "verified" if headless_check["status"] == "pass" else "not_verified"
        if headless_check["status"] != "pass":
            errors.append("Headless runtime check did not pass.")
    else:
        fixture_result = run_fixture_qualification(binary_path)
        checks.extend(fixture_result["checks"])
        warnings.extend(fixture_result["warnings"])
        errors.extend(fixture_result["errors"])
        fixture_execution_status = fixture_result["fixture_execution_status"]
        unexpected_files = fixture_result["unexpected_files"]
        temporary_artifacts_created = fixture_result["temporary_artifacts_created"]
        temporary_artifacts_cleaned = fixture_result["temporary_artifacts_cleaned"]
        headless_check = next((c for c in fixture_result["checks"] if c["check_id"] == "blender_headless_runtime"), None)
        headless_status = "verified" if headless_check and headless_check["status"] == "pass" else "not_verified"

    if fixture_execution_status == "succeeded":
        adapter_status = "qualified"
    elif headless_status == "verified":
        adapter_status = "not_qualified"
    else:
        adapter_status = "not_qualified"

    assert adapter_status in ADAPTER_QUALIFICATION_STATUSES, adapter_status
    assert headless_status in HEADLESS_RUNTIME_STATUSES, headless_status
    assert fixture_execution_status in FIXTURE_EXECUTION_STATUSES, fixture_execution_status

    return {
        "tool_id": "blender",
        "display_name": "Blender",
        "detected": True,
        "detected_version": detected_version,
        "detected_path": binary_path,
        "headless_runtime_status": headless_status,
        "headless_runtime_evidence": headless_check["evidence"] if headless_check else "not attempted",
        "fixture_execution_status": fixture_execution_status,
        "fixture_checks": checks,
        "adapter_qualification_status": adapter_status,
        "warnings": warnings,
        "errors": errors,
        "temporary_artifacts_created": temporary_artifacts_created,
        "temporary_artifacts_cleaned": temporary_artifacts_cleaned,
        "unexpected_files": unexpected_files,
        "network_used": False,
        "gui_launched": False,
        "printer_contacted": False,
        "automatic_print_allowed": False,
        "project_execution_approved": False,
        "duration_ms": _elapsed_ms(start),
    }


BLENDER_ADAPTER_VERSION = 1


def build_blender_report(*, confirm_fixture: bool = False) -> dict[str, Any]:
    """The full `{blender_adapter_version, gate, qualification,
    project_execution_approved, safety}` JSON contract `factory blender
    qualify [--confirm-fixture] [--json]` returns. `gate` is always the
    read-only, zero-subprocess `factory.blender_gate.evaluate_blender_execution_gate()`
    result; `qualification` is the (possibly real, bounded) execution
    result above. `project_execution_approved` is hardcoded `False` here
    too, for a caller that only reads the top level of this dict."""
    return {
        "blender_adapter_version": BLENDER_ADAPTER_VERSION,
        "gate": blender_gate.evaluate_blender_execution_gate(),
        "qualification": qualify_blender_adapter(confirm_fixture=confirm_fixture),
        "project_execution_approved": False,
        "safety": dict(_SAFETY_BLOCK),
    }

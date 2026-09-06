"""Phase 44: Local Tool Environment Qualification.

Answers a question `factory.engine_registry` (Phase 43) deliberately does
not: **"can this detected local tool actually perform the minimum
capability the Factory expects from it?"** Detection is a filesystem/PATH/
package-metadata fact; qualification is evidence gathered by actually
exercising (in a narrow, bounded, temporary-fixture way) what the tool can
do. Neither one is execution approval:

    Detected  !=  Qualified  !=  Execution Approved

A tool may be `detected: true`, `qualification_status: "qualified"`, and
`execution_approved: false` all at once - qualification is evidence for a
later, separate, human/engine-specific approval decision (Phase 45 for
Blender, etc.), never that decision itself. **`execution_approved` is
hardcoded `False` on every single result in this module, with no code path
that ever sets it `True`.**

    specialized probes -> factory.engine_registry -> factory.tool_qualification -> CLI / Preview Board

Reuses rather than duplicates:

- `factory.engine_registry.probe_all_tools()` (Phase 43) - every tool's
  detection/version/path; this module never re-implements a `.app` bundle
  scan, a `PATH` lookup, or the CadQuery/OpenSCAD detection checks.
  `include_version_subprocess=True` is passed through for the OpenSCAD
  `--version` probe (the same safe, timeout-bounded call
  `factory.export_pipeline._probe_tool_version()` already established) -
  this module adds no second version-probe implementation for OpenSCAD.
- `factory.engine_registry.get_tool_registry()` - `display_name` and
  `local_or_cloud` for each tool, never a second copy of that metadata.
- `factory.validators.mesh_validate.validate_mesh()` - the exact same
  Factory mesh validator `factory.export_pipeline.run_validation()` calls
  in production, called here directly (no report file is written - this
  module has no write path into a project) against a temporary
  qualification fixture, never a second validation implementation.

Safety posture (see `docs/tool-qualification.md` for the full policy):

- **OpenSCAD** is the only tool given a real, bounded local-execution
  qualification: one `openscad -o <tmp>.stl <tmp>.scad` subprocess call
  against a fixed, hand-written 10mm cube fixture in a
  `tempfile.TemporaryDirectory()` - argument-list, `shell=False`, a hard
  timeout, and the temp directory is always cleaned up (Python's context
  manager removes it; failure to do so is detected and reported honestly,
  never silently claimed).
- **CadQuery**, if installed, gets an equivalent in-process capability
  test: `cadquery.Workplane("XY").box(10, 10, 10)` exported to a temporary
  STL. This is **not** "arbitrary project Python" - it never imports,
  executes, or evaluates any project- or user-authored CadQuery source
  (the concern `factory.cad.cadquery_backend`'s own "never imports/
  executes the CadQuery source it writes" policy addresses); it only
  calls the already-installed, vetted `cadquery` library's own documented
  API with fixed, hand-written qualification code - the same trust
  boundary as importing any other already-installed Python dependency.
- **Blender and FreeCAD are never passed to `subprocess`, ever, in this
  phase.** `docs/blender-local-track.md`'s existing "no subprocess call,
  no headless invocation" rule for Blender is treated as authoritative
  and binding here too (the same rule `factory.engine_registry` already
  extended to FreeCAD by symmetry) - qualification for both stops at
  `metadata_only` (path + `Info.plist` version, both already computed by
  `probe_all_tools()`). A future Phase 45 gate review, not this phase, is
  the place to decide whether a bounded `blender --background --version`
  probe is ever safe to add.
- **Bambu Studio, OrcaSlicer, PrusaSlicer** are GUI-only
  (`cli_available: False` in the registry) - qualification stops at
  `metadata_only` (path + `Info.plist` version) for the same reason: no
  documented-safe headless flag exists for any of them in this repo.
- **Meshy, Plasticity, Autodesk Fusion, Onshape, Bambu Connect** are
  registry-only in this phase - `qualification_status: "unsupported"`
  regardless of whether `probe_all_tools()` happens to report them
  detected (a GUI-only app like Plasticity *could* be installed locally;
  that alone still never qualifies it - "detected merely because
  installed" is exactly the conflation this phase's design principles
  forbid). None of these five is ever executed, contacted, or
  authenticated to by this module.

No install, no upgrade, no GUI launch, no AppleScript/`osascript`/`open`/
`pkill`, no network call, no printer contact, no G-code generation, no
Homebrew mutation, anywhere in this module.

See `docs/tool-qualification.md`.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from factory import engine_registry, project_store
from factory.validators.mesh_validate import validate_mesh

# ---------------------------------------------------------------------------
# Vocabulary - stable, closed, documented in docs/tool-qualification.md
# ---------------------------------------------------------------------------

QUALIFICATION_VERSION = 1

QUALIFICATION_STATUSES = (
    "qualified",
    "partially_qualified",
    "unqualified",
    "not_installed",
    "not_tested",
    "requires_manual_qualification",
    "probe_failed",
    "unsupported",
)

QUALIFICATION_LEVELS = (
    "metadata_only",
    "cli_verified",
    "capability_verified",
    "factory_workflow_verified",
    "manual_required",
)

CHECK_STATUSES = ("pass", "warn", "fail", "skip")

# The 8 tools this phase actually gathers qualification evidence for.
QUALIFICATION_SCOPE_TOOL_IDS = (
    "openscad_stable",
    "openscad_snapshot",
    "cadquery",
    "blender",
    "freecad",
    "bambu_studio",
    "orcaslicer",
    "prusaslicer",
)

# The 5 tools that remain permanently registered (Phase 43) but are never
# qualified in this phase, regardless of local detection - see the module
# docstring's "Meshy, Plasticity, Autodesk Fusion, Onshape, Bambu Connect" note.
DEFERRED_TOOL_IDS = (
    "meshy",
    "plasticity",
    "autodesk_fusion",
    "onshape",
    "bambu_connect",
)

assert set(QUALIFICATION_SCOPE_TOOL_IDS) | set(DEFERRED_TOOL_IDS) == set(engine_registry.TOOL_IDS)
assert not (set(QUALIFICATION_SCOPE_TOOL_IDS) & set(DEFERRED_TOOL_IDS))

_OPENSCAD_EXPORT_TIMEOUT_SECONDS = 30
_MINIMAL_SCAD_FIXTURE = "cube([10, 10, 10]);\n"

_METADATA_ONLY_POLICY_NOTES: dict[str, str] = {
    "blender": (
        "No subprocess call is made for Blender in this phase - docs/blender-local-track.md's "
        "'no subprocess call, no headless invocation' rule is treated as authoritative here too. "
        "Whether a bounded headless version probe is ever safe is Phase 45's decision, not this one's."
    ),
    "freecad": (
        "No subprocess call is made for FreeCAD in this phase, by the same reasoning "
        "factory.engine_registry already applies to it (symmetry with the Blender rule above) - "
        "no established safe FreeCAD headless convention exists in this repo yet."
    ),
    "bambu_studio": (
        "Bambu Studio is a GUI-only slicer (cli_available=False in the registry) - no headless probe "
        "is attempted; qualification stops at path/version metadata."
    ),
    "orcaslicer": (
        "OrcaSlicer is a GUI-only slicer (cli_available=False in the registry) - no headless probe "
        "is attempted; qualification stops at path/version metadata."
    ),
    "prusaslicer": (
        "PrusaSlicer is a GUI-only slicer (cli_available=False in the registry) - no headless probe "
        "is attempted; qualification stops at path/version metadata."
    ),
}

_DEFERRED_TOOL_NOTES: dict[str, str] = {
    "meshy": (
        "Cloud-gated (config/future_cloud_tools.json) - never called, never authenticated, no network "
        "contact. Cloud/cost/license approval is Phase 46; this phase performs no qualification work for it."
    ),
    "onshape": (
        "Cloud-only, no local install to detect - permanent future cloud CAD entry (docs/engine-registry.md). "
        "Not qualified in this phase."
    ),
    "plasticity": (
        "Permanent future/experimental registry entry - GUI-only, human-oriented direct/NURBS modeling. "
        "Not automated, not qualified in this phase, regardless of whether it happens to be locally installed."
    ),
    "autodesk_fusion": (
        "Permanent future external-engine registry entry - account/cloud/licensing concerns out of scope "
        "here. Not qualified in this phase, regardless of whether it happens to be locally installed."
    ),
    "bambu_connect": (
        "Registry-only, printing_adjacent_disabled - out of scope for every phase through this one. "
        "Not qualified in this phase, regardless of whether it happens to be locally installed."
    ),
}

_SAFETY_BLOCK: dict[str, bool] = {
    "software_installed": False,
    "software_upgraded": False,
    "gui_launched": False,
    "network_used": False,
    "slicer_executed": False,
    "gcode_generated": False,
    "printer_contacted": False,
    "automatic_print_allowed": False,
}


class UnknownToolError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _elapsed_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 1)


def _check(check_id: str, label: str, status: str, evidence: str) -> dict[str, Any]:
    assert status in CHECK_STATUSES, status
    return {"check_id": check_id, "label": label, "status": status, "evidence": evidence, "duration_ms": None}


def _result(
    *,
    tool_id: str,
    display_name: str,
    detected: bool,
    detected_version: str,
    detected_path: str | None,
    qualification_status: str,
    qualification_level: str,
    checks: list[dict[str, Any]],
    capabilities_verified: list[str],
    capabilities_unverified: list[str],
    warnings: list[str],
    errors: list[str],
    evidence: list[str],
    duration_ms: float,
    temporary_artifacts_created: bool,
    temporary_artifacts_cleaned: bool,
) -> dict[str, Any]:
    assert qualification_status in QUALIFICATION_STATUSES, qualification_status
    assert qualification_level in QUALIFICATION_LEVELS, qualification_level
    qualified_at = project_store.utc_now_iso() if qualification_status in ("qualified", "partially_qualified") else None
    return {
        "tool_id": tool_id,
        "display_name": display_name,
        "detected": detected,
        "detected_version": detected_version,
        "detected_path": detected_path,
        "qualification_status": qualification_status,
        "qualification_level": qualification_level,
        "checks": checks,
        "capabilities_verified": list(capabilities_verified),
        "capabilities_unverified": list(capabilities_unverified),
        "warnings": list(warnings),
        "errors": list(errors),
        "evidence": list(evidence),
        # Always False. No code path in this module ever sets this True -
        # execution approval is owned by later, engine-specific phases/gates.
        "execution_approved": False,
        "qualified_at": qualified_at,
        "duration_ms": duration_ms,
        "temporary_artifacts_created": temporary_artifacts_created,
        "temporary_artifacts_cleaned": temporary_artifacts_cleaned,
        "network_used": False,
        "gui_launched": False,
        "printer_contacted": False,
        "automatic_print_allowed": False,
    }


# ---------------------------------------------------------------------------
# OpenSCAD (stable) - the only tool qualified all the way to
# `factory_workflow_verified` in this phase, since the Factory already uses
# it in production (factory.export_pipeline).
# ---------------------------------------------------------------------------


def _qualify_openscad_stable(display_name: str, probe: dict[str, Any]) -> dict[str, Any]:
    start = time.monotonic()
    checks: list[dict[str, Any]] = []
    warnings = list(probe.get("probe_warnings", []))
    errors: list[str] = []
    capabilities_verified: list[str] = []
    capabilities_unverified: list[str] = []

    detected = bool(probe.get("detected"))
    checks.append(
        _check(
            "openscad_binary_detected",
            "Binary detected",
            "pass" if detected else "fail",
            probe.get("detected_path") or "no local `openscad` executable found (.app bundle or PATH)",
        )
    )
    if not detected:
        return _result(
            tool_id="openscad_stable",
            display_name=display_name,
            detected=False,
            detected_version="unknown",
            detected_path=None,
            qualification_status="not_installed",
            qualification_level="metadata_only",
            checks=checks,
            capabilities_verified=[],
            capabilities_unverified=["cli_stl_export"],
            warnings=[],
            errors=["OpenSCAD not detected locally"],
            evidence=["No local OpenSCAD executable found."],
            duration_ms=_elapsed_ms(start),
            temporary_artifacts_created=False,
            temporary_artifacts_cleaned=True,
        )

    version = probe.get("detected_version", "unknown")
    executable = probe.get("detected_path")
    cli_ok = version != "unknown" and not any("version probe failed" in w for w in warnings)
    checks.append(_check("openscad_cli_responds", "CLI responds", "pass" if cli_ok else "warn", version))
    evidence = [f"Detected executable: {executable}", f"Version: {version}"]

    export_ok = False
    validation_check_status: str | None = None
    temporary_artifacts_created = False
    temporary_artifacts_cleaned = True
    tmp_dir_path: str | None = None

    try:
        with tempfile.TemporaryDirectory(prefix="factory-openscad-qualify-") as tmp_dir:
            tmp_dir_path = tmp_dir
            temporary_artifacts_created = True
            scad_path = Path(tmp_dir) / "qualification_fixture.scad"
            stl_path = Path(tmp_dir) / "qualification_fixture.stl"
            scad_path.write_text(_MINIMAL_SCAD_FIXTURE)

            command = [executable, "-o", str(stl_path), str(scad_path)]
            try:
                completed = subprocess.run(
                    command, capture_output=True, text=True, timeout=_OPENSCAD_EXPORT_TIMEOUT_SECONDS
                )
            except subprocess.TimeoutExpired:
                checks.append(
                    _check(
                        "openscad_temp_scad_exported",
                        "Temporary SCAD exported",
                        "fail",
                        f"export timed out after {_OPENSCAD_EXPORT_TIMEOUT_SECONDS}s",
                    )
                )
                errors.append("OpenSCAD export timed out")
            except OSError as exc:
                checks.append(
                    _check("openscad_temp_scad_exported", "Temporary SCAD exported", "fail", f"failed to launch: {exc}")
                )
                errors.append("failed to launch OpenSCAD for export")
            else:
                if completed.returncode == 0:
                    checks.append(_check("openscad_temp_scad_exported", "Temporary SCAD exported", "pass", "exit code 0"))
                else:
                    checks.append(
                        _check(
                            "openscad_temp_scad_exported",
                            "Temporary SCAD exported",
                            "fail",
                            f"exit code {completed.returncode}: {(completed.stderr or '')[:300]}",
                        )
                    )
                    errors.append(f"OpenSCAD export exited with code {completed.returncode}")

                stl_exists = stl_path.is_file()
                stl_nonempty = stl_exists and stl_path.stat().st_size > 0
                stl_valid_ext = stl_path.suffix.lower() == ".stl"
                if stl_exists and stl_nonempty and stl_valid_ext:
                    checks.append(
                        _check("openscad_stl_output_valid", "STL exists and is non-empty", "pass", f"{stl_path.stat().st_size} bytes")
                    )
                    export_ok = True
                    capabilities_verified.append("cli_stl_export")
                else:
                    reason = "missing" if not stl_exists else ("empty" if not stl_nonempty else "unexpected extension")
                    checks.append(_check("openscad_stl_output_valid", "STL exists and is non-empty", "fail", reason))
                    errors.append(f"exported STL {reason}")
                    capabilities_unverified.append("cli_stl_export")

                if export_ok:
                    try:
                        report = validate_mesh(stl_path)
                        overall = report.get("overall_status")
                        validation_check_status = "pass" if overall == "PASS" else ("warn" if overall == "WARN" else "fail")
                        checks.append(
                            _check(
                                "openscad_factory_validation",
                                "Factory mesh validation completed",
                                validation_check_status,
                                f"overall_status={overall}",
                            )
                        )
                        if validation_check_status in ("pass", "warn"):
                            capabilities_verified.append("factory_mesh_validation")
                        else:
                            capabilities_unverified.append("factory_mesh_validation")
                            errors.append("Factory validation reported FAIL for the qualification fixture")
                    except Exception as exc:  # validator failure must not abort qualification
                        validation_check_status = "fail"
                        checks.append(
                            _check(
                                "openscad_factory_validation",
                                "Factory mesh validation completed",
                                "fail",
                                f"{type(exc).__name__}: {exc}",
                            )
                        )
                        capabilities_unverified.append("factory_mesh_validation")
                else:
                    checks.append(
                        _check("openscad_factory_validation", "Factory mesh validation completed", "skip", "no STL to validate")
                    )
                    capabilities_unverified.append("factory_mesh_validation")

        temporary_artifacts_cleaned = not Path(tmp_dir_path).exists()
        checks.append(
            _check(
                "openscad_cleanup",
                "Temporary artifacts cleaned",
                "pass" if temporary_artifacts_cleaned else "fail",
                tmp_dir_path or "",
            )
        )
    except Exception as exc:  # never let a fixture/cleanup surprise abort qualification
        temporary_artifacts_cleaned = not Path(tmp_dir_path).exists() if tmp_dir_path else True
        checks.append(
            _check("openscad_cleanup", "Temporary artifacts cleaned", "pass" if temporary_artifacts_cleaned else "fail", str(exc))
        )
        errors.append(f"unexpected error during temporary fixture qualification: {exc}")
        if not temporary_artifacts_cleaned:
            warnings.append(f"cleanup may have failed - reported honestly, never assumed successful: {tmp_dir_path}")

    if export_ok and validation_check_status in ("pass", "warn"):
        status, level = "qualified", "factory_workflow_verified"
    elif export_ok:
        status, level = "partially_qualified", "capability_verified"
    elif cli_ok:
        status, level = "partially_qualified", "cli_verified"
    else:
        status, level = "unqualified", "metadata_only"

    return _result(
        tool_id="openscad_stable",
        display_name=display_name,
        detected=True,
        detected_version=version,
        detected_path=executable,
        qualification_status=status,
        qualification_level=level,
        checks=checks,
        capabilities_verified=capabilities_verified,
        capabilities_unverified=capabilities_unverified,
        warnings=warnings,
        errors=errors,
        evidence=evidence,
        duration_ms=_elapsed_ms(start),
        temporary_artifacts_created=temporary_artifacts_created,
        temporary_artifacts_cleaned=temporary_artifacts_cleaned,
    )


def _qualify_openscad_snapshot(display_name: str, probe: dict[str, Any]) -> dict[str, Any]:
    """No separate snapshot-channel detection path exists yet (see
    `docs/engine-registry.md` "OpenSCAD: stable vs. snapshot") - whatever
    local `openscad` binary exists is always attributed to
    `openscad_stable`. Building a real second detection path, and deciding
    its qualification, remains explicitly future work."""
    start = time.monotonic()
    checks = [
        _check(
            "openscad_snapshot_detection",
            "Separate snapshot-channel detection",
            "skip",
            "No separate snapshot-channel detection path exists yet - the only local `openscad` binary found "
            "is always attributed to openscad_stable (see docs/engine-registry.md).",
        )
    ]
    return _result(
        tool_id="openscad_snapshot",
        display_name=display_name,
        detected=False,
        detected_version="unknown",
        detected_path=None,
        qualification_status="not_installed",
        qualification_level="metadata_only",
        checks=checks,
        capabilities_verified=[],
        capabilities_unverified=["cli_stl_export"],
        warnings=["No distinguishable snapshot channel exists to qualify in this phase."],
        errors=[],
        evidence=["Snapshot-channel qualification requires a distinct detection path - future work."],
        duration_ms=_elapsed_ms(start),
        temporary_artifacts_created=False,
        temporary_artifacts_cleaned=True,
    )


# ---------------------------------------------------------------------------
# CadQuery - an in-process capability test (never "arbitrary project
# Python" - see module docstring), factored into its own function so tests
# can monkeypatch it without a real `cadquery` install.
# ---------------------------------------------------------------------------


def _run_cadquery_capability_probe(tmp_dir: Path) -> dict[str, Any]:
    """Construct one tiny, fixed, deterministic mechanical solid in memory
    using the installed `cadquery` package, then export it to a temporary
    STL. Fixed, hand-written qualification code only - never imports,
    executes, or evaluates any project- or user-authored CadQuery source.
    """
    import cadquery as cq

    solid = cq.Workplane("XY").box(10, 10, 10)
    stl_path = tmp_dir / "qualification_fixture.stl"
    cq.exporters.export(solid, str(stl_path))
    return {"stl_path": stl_path}


def _qualify_cadquery(display_name: str, probe: dict[str, Any]) -> dict[str, Any]:
    start = time.monotonic()
    checks: list[dict[str, Any]] = []
    warnings = list(probe.get("probe_warnings", []))
    errors: list[str] = []
    capabilities_verified: list[str] = []
    capabilities_unverified: list[str] = []

    detected = bool(probe.get("detected"))
    checks.append(
        _check(
            "cadquery_package_detected",
            "Package detected",
            "pass" if detected else "fail",
            "cadquery is importable (find_spec)" if detected else "cadquery is not installed - this repo never installs or upgrades it",
        )
    )
    if not detected:
        return _result(
            tool_id="cadquery",
            display_name=display_name,
            detected=False,
            detected_version="unknown",
            detected_path=None,
            qualification_status="not_installed",
            qualification_level="metadata_only",
            checks=checks,
            capabilities_verified=[],
            capabilities_unverified=["step_export", "stl_export"],
            warnings=[],
            errors=["cadquery package not installed"],
            evidence=["cadquery is not importable in this environment."],
            duration_ms=_elapsed_ms(start),
            temporary_artifacts_created=False,
            temporary_artifacts_cleaned=True,
        )

    version = probe.get("detected_version", "unknown")
    checks.append(_check("cadquery_version_metadata", "Version metadata", "pass" if version != "unknown" else "warn", version))
    evidence = [f"Version: {version}"]

    capability_ok = False
    export_ok = False
    validation_check_status: str | None = None
    temporary_artifacts_created = False
    temporary_artifacts_cleaned = True
    tmp_dir_path: str | None = None

    try:
        with tempfile.TemporaryDirectory(prefix="factory-cadquery-qualify-") as tmp_dir:
            tmp_dir_path = tmp_dir
            temporary_artifacts_created = True
            try:
                probe_out = _run_cadquery_capability_probe(Path(tmp_dir))
            except Exception as exc:
                checks.append(
                    _check(
                        "cadquery_capability_construct",
                        "Minimal solid constructed in memory",
                        "fail",
                        f"{type(exc).__name__}: {exc}",
                    )
                )
                capabilities_unverified.append("cadquery_source_generation")
                errors.append(f"CadQuery in-process capability test failed: {exc}")
            else:
                capability_ok = True
                checks.append(
                    _check(
                        "cadquery_capability_construct",
                        "Minimal solid constructed in memory",
                        "pass",
                        "10mm cube built via cadquery.Workplane",
                    )
                )
                capabilities_verified.append("cadquery_source_generation")

                stl_path = probe_out["stl_path"]
                stl_exists = stl_path.is_file()
                stl_nonempty = stl_exists and stl_path.stat().st_size > 0
                if stl_exists and stl_nonempty:
                    checks.append(_check("cadquery_stl_export", "STL exported", "pass", f"{stl_path.stat().st_size} bytes"))
                    export_ok = True
                    capabilities_verified.append("stl_export")
                else:
                    checks.append(_check("cadquery_stl_export", "STL exported", "fail", "missing or empty"))
                    capabilities_unverified.append("stl_export")
                    errors.append("CadQuery STL export produced no usable output")

                if export_ok:
                    try:
                        report = validate_mesh(stl_path)
                        overall = report.get("overall_status")
                        validation_check_status = "pass" if overall == "PASS" else ("warn" if overall == "WARN" else "fail")
                        checks.append(
                            _check(
                                "cadquery_factory_validation",
                                "Factory mesh validation completed",
                                validation_check_status,
                                f"overall_status={overall}",
                            )
                        )
                        if validation_check_status in ("pass", "warn"):
                            capabilities_verified.append("factory_mesh_validation")
                        else:
                            capabilities_unverified.append("factory_mesh_validation")
                    except Exception as exc:
                        validation_check_status = "fail"
                        checks.append(
                            _check(
                                "cadquery_factory_validation",
                                "Factory mesh validation completed",
                                "fail",
                                f"{type(exc).__name__}: {exc}",
                            )
                        )
                        capabilities_unverified.append("factory_mesh_validation")
                else:
                    checks.append(
                        _check("cadquery_factory_validation", "Factory mesh validation completed", "skip", "no STL to validate")
                    )
                    capabilities_unverified.append("factory_mesh_validation")

        temporary_artifacts_cleaned = not Path(tmp_dir_path).exists()
        checks.append(
            _check(
                "cadquery_cleanup",
                "Temporary artifacts cleaned",
                "pass" if temporary_artifacts_cleaned else "fail",
                tmp_dir_path or "",
            )
        )
    except Exception as exc:
        temporary_artifacts_cleaned = not Path(tmp_dir_path).exists() if tmp_dir_path else True
        checks.append(
            _check("cadquery_cleanup", "Temporary artifacts cleaned", "pass" if temporary_artifacts_cleaned else "fail", str(exc))
        )
        errors.append(f"unexpected error during CadQuery qualification: {exc}")
        if not temporary_artifacts_cleaned:
            warnings.append(f"cleanup may have failed - reported honestly, never assumed successful: {tmp_dir_path}")

    if export_ok and validation_check_status in ("pass", "warn"):
        status, level = "qualified", "factory_workflow_verified"
    elif capability_ok:
        status, level = "partially_qualified", "capability_verified"
    else:
        status, level = "unqualified", "metadata_only"

    return _result(
        tool_id="cadquery",
        display_name=display_name,
        detected=True,
        detected_version=version,
        detected_path=None,
        qualification_status=status,
        qualification_level=level,
        checks=checks,
        capabilities_verified=capabilities_verified,
        capabilities_unverified=capabilities_unverified,
        warnings=warnings,
        errors=errors,
        evidence=evidence,
        duration_ms=_elapsed_ms(start),
        temporary_artifacts_created=temporary_artifacts_created,
        temporary_artifacts_cleaned=temporary_artifacts_cleaned,
    )


# ---------------------------------------------------------------------------
# Blender / FreeCAD / Bambu Studio / OrcaSlicer / PrusaSlicer - metadata
# only, by policy (see module docstring) - never a subprocess.
# ---------------------------------------------------------------------------


def _qualify_metadata_only_gui_tool(tool_id: str, display_name: str, probe: dict[str, Any]) -> dict[str, Any]:
    start = time.monotonic()
    detected = bool(probe.get("detected"))
    version = probe.get("detected_version", "unknown")
    path = probe.get("detected_path")

    checks = [
        _check(f"{tool_id}_detected", "Application/binary detected", "pass" if detected else "fail", path or "not found")
    ]
    if detected:
        checks.append(_check(f"{tool_id}_version_metadata", "Version metadata", "pass" if version != "unknown" else "warn", version))
    checks.append(_check(f"{tool_id}_headless_probe", "Headless/CLI probe", "skip", _METADATA_ONLY_POLICY_NOTES[tool_id]))

    if not detected:
        return _result(
            tool_id=tool_id,
            display_name=display_name,
            detected=False,
            detected_version="unknown",
            detected_path=None,
            qualification_status="not_installed",
            qualification_level="metadata_only",
            checks=checks,
            capabilities_verified=[],
            capabilities_unverified=[],
            warnings=[],
            errors=[],
            evidence=["Not detected locally."],
            duration_ms=_elapsed_ms(start),
            temporary_artifacts_created=False,
            temporary_artifacts_cleaned=True,
        )

    return _result(
        tool_id=tool_id,
        display_name=display_name,
        detected=True,
        detected_version=version,
        detected_path=path,
        qualification_status="requires_manual_qualification",
        qualification_level="metadata_only",
        checks=checks,
        capabilities_verified=[],
        capabilities_unverified=[],
        warnings=["Detected, but qualification for this tool stops at metadata only in this phase - see checks for the policy reason."],
        errors=[],
        evidence=[f"Detected at: {path}", f"Version: {version}"],
        duration_ms=_elapsed_ms(start),
        temporary_artifacts_created=False,
        temporary_artifacts_cleaned=True,
    )


# ---------------------------------------------------------------------------
# Deferred/registry-only tools - never qualified in this phase, regardless
# of detection (see module docstring).
# ---------------------------------------------------------------------------


def _qualify_deferred_tool(tool_id: str, display_name: str, probe: dict[str, Any]) -> dict[str, Any]:
    start = time.monotonic()
    note = _DEFERRED_TOOL_NOTES[tool_id]
    checks = [_check(f"{tool_id}_deferred", "Qualification deferred", "skip", note)]
    return _result(
        tool_id=tool_id,
        display_name=display_name,
        detected=bool(probe.get("detected", False)),
        detected_version=probe.get("detected_version", "unknown"),
        detected_path=probe.get("detected_path"),
        qualification_status="unsupported",
        qualification_level="manual_required",
        checks=checks,
        capabilities_verified=[],
        capabilities_unverified=[],
        warnings=[],
        errors=[],
        evidence=[note],
        duration_ms=_elapsed_ms(start),
        temporary_artifacts_created=False,
        temporary_artifacts_cleaned=True,
    )


# ---------------------------------------------------------------------------
# Dispatch and public entry points
# ---------------------------------------------------------------------------

_DEFAULT_PROBE_RESULT: dict[str, Any] = {
    "detected": False,
    "detected_path": None,
    "detected_version": "unknown",
    "probe_status": "not_probed",
    "probe_warnings": [],
}


def _qualify_one(tool_id: str, probe_results: dict[str, dict[str, Any]], registry: dict[str, dict[str, Any]]) -> dict[str, Any]:
    display_name = registry[tool_id]["display_name"]
    probe = probe_results.get(tool_id) or _DEFAULT_PROBE_RESULT
    try:
        if tool_id == "openscad_stable":
            return _qualify_openscad_stable(display_name, probe)
        if tool_id == "openscad_snapshot":
            return _qualify_openscad_snapshot(display_name, probe)
        if tool_id == "cadquery":
            return _qualify_cadquery(display_name, probe)
        if tool_id in ("blender", "freecad", "bambu_studio", "orcaslicer", "prusaslicer"):
            return _qualify_metadata_only_gui_tool(tool_id, display_name, probe)
        if tool_id in DEFERRED_TOOL_IDS:
            return _qualify_deferred_tool(tool_id, display_name, probe)
        raise AssertionError(f"unhandled tool_id {tool_id!r}")  # pragma: no cover - TOOL_IDS is exhaustive above
    except Exception as exc:  # one tool's qualification must never abort the rest
        return _result(
            tool_id=tool_id,
            display_name=display_name,
            detected=False,
            detected_version="unknown",
            detected_path=None,
            qualification_status="probe_failed",
            qualification_level="metadata_only",
            checks=[_check(f"{tool_id}_qualification", "Qualification attempt", "fail", f"{type(exc).__name__}: {exc}")],
            capabilities_verified=[],
            capabilities_unverified=[],
            warnings=[],
            errors=[f"qualification raised {type(exc).__name__}: {exc}"],
            evidence=[],
            duration_ms=0.0,
            temporary_artifacts_created=False,
            temporary_artifacts_cleaned=True,
        )


def qualify_tool(tool_id: str) -> dict[str, Any]:
    """Qualify exactly one tool by id. Raises `UnknownToolError` for an
    unrecognized `tool_id` (never silently returns a placeholder for a
    typo); a genuine per-tool qualification failure is instead captured
    inside the returned result (`qualification_status: "probe_failed"`).
    """
    if tool_id not in engine_registry.TOOL_IDS:
        known = ", ".join(engine_registry.TOOL_IDS)
        raise UnknownToolError(f"Unknown tool_id {tool_id!r}. Known tool ids: {known}")
    registry = engine_registry.get_tool_registry(probe=False)
    probe_results = engine_registry.probe_all_tools(include_version_subprocess=(tool_id == "openscad_stable"))
    return _qualify_one(tool_id, probe_results, registry)


def qualify_all_tools() -> dict[str, dict[str, Any]]:
    """Qualify every registered tool. A single tool's qualification
    failure is captured in its own result and never aborts the rest (see
    `_qualify_one()`'s `try`/`except`)."""
    registry = engine_registry.get_tool_registry(probe=False)
    probe_results = engine_registry.probe_all_tools(include_version_subprocess=True)
    return {tool_id: _qualify_one(tool_id, probe_results, registry) for tool_id in engine_registry.TOOL_IDS}


def summarize_qualification(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Deterministic counts given the same `results` - never recomputed
    from anything but the results actually passed in."""
    registry = engine_registry.get_tool_registry(probe=False)
    counts = {status: 0 for status in QUALIFICATION_STATUSES}
    for result in results.values():
        counts[result["qualification_status"]] += 1
    cloud_gated = sum(1 for tool_id in results if registry.get(tool_id, {}).get("local_or_cloud") == "cloud")
    return {
        "total_tools": len(engine_registry.TOOL_IDS),
        "qualification_scope": len(QUALIFICATION_SCOPE_TOOL_IDS),
        "qualified": counts["qualified"],
        "partially_qualified": counts["partially_qualified"],
        "unqualified": counts["unqualified"],
        "not_installed": counts["not_installed"],
        "not_tested": counts["not_tested"],
        "manual_required": counts["requires_manual_qualification"],
        "cloud_gated": cloud_gated,
        "unsupported": counts["unsupported"],
        "failed": counts["probe_failed"],
        # Always 0 - execution_approved is hardcoded False on every result;
        # kept as a live sum (not a literal 0) so a future regression that
        # somehow flips one would be caught rather than silently hidden.
        "execution_approved": sum(1 for result in results.values() if result["execution_approved"]),
    }


def build_qualification_report(*, tool_id: str | None = None) -> dict[str, Any]:
    """The full `{qualification_version, results, summary, safety}` JSON
    contract `factory engines qualify [<tool_id>] [--json]` returns.
    `results` is always a list (one entry when `tool_id` is given) so the
    shape is identical whether qualifying one tool or all of them.
    """
    if tool_id is not None:
        results = {tool_id: qualify_tool(tool_id)}
    else:
        results = qualify_all_tools()
    return {
        "qualification_version": QUALIFICATION_VERSION,
        "results": list(results.values()),
        "summary": summarize_qualification(results),
        "safety": dict(_SAFETY_BLOCK),
    }

"""Phase 44 tests: `factory.tool_qualification`'s OpenSCAD progressive
qualification workflow (the only tool qualified end-to-end in this phase).

Covers: not installed, version success/timeout/failure, temp fixture
generation, empty/missing STL rejection, Factory validator reuse (pass/warn/
fail preserved honestly), cleanup success/failure reporting, and the
snapshot channel handled separately from stable. See docs/tool-qualification.md.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from factory import tool_qualification as tq


def _probe(**overrides) -> dict:
    base = {"detected": False, "detected_path": None, "detected_version": "unknown", "probe_status": "not_installed", "probe_warnings": []}
    base.update(overrides)
    return base


def test_openscad_not_installed():
    result = tq._qualify_openscad_stable("OpenSCAD (stable)", _probe())
    assert result["detected"] is False
    assert result["qualification_status"] == "not_installed"
    assert result["qualification_level"] == "metadata_only"
    assert result["checks"][0]["status"] == "fail"


def test_openscad_version_success_reaches_factory_workflow_verified(monkeypatch, tmp_path):
    fake = _fake_openscad_script(tmp_path)
    probe = _probe(detected=True, detected_path=str(fake), detected_version="fake 1.0", probe_status="detected")
    monkeypatch.setattr(tq, "validate_mesh", lambda path: {"overall_status": "PASS"})
    result = tq._qualify_openscad_stable("OpenSCAD (stable)", probe)
    assert result["qualification_status"] == "qualified"
    assert result["qualification_level"] == "factory_workflow_verified"
    assert "cli_stl_export" in result["capabilities_verified"]
    assert "factory_mesh_validation" in result["capabilities_verified"]
    assert result["temporary_artifacts_created"] is True
    assert result["temporary_artifacts_cleaned"] is True


def test_openscad_validation_warn_still_counts_as_qualified(monkeypatch, tmp_path):
    fake = _fake_openscad_script(tmp_path)
    probe = _probe(detected=True, detected_path=str(fake), detected_version="fake 1.0")
    monkeypatch.setattr(tq, "validate_mesh", lambda path: {"overall_status": "WARN"})
    result = tq._qualify_openscad_stable("OpenSCAD (stable)", probe)
    assert result["qualification_status"] == "qualified"


def test_openscad_validation_fail_downgrades_to_partially_qualified(monkeypatch, tmp_path):
    fake = _fake_openscad_script(tmp_path)
    probe = _probe(detected=True, detected_path=str(fake), detected_version="fake 1.0")
    monkeypatch.setattr(tq, "validate_mesh", lambda path: {"overall_status": "FAIL", "checks": []})
    result = tq._qualify_openscad_stable("OpenSCAD (stable)", probe)
    assert result["qualification_status"] == "partially_qualified"
    assert result["qualification_level"] == "capability_verified"
    assert "factory_mesh_validation" in result["capabilities_unverified"]


def test_openscad_validator_raising_is_handled_honestly(monkeypatch, tmp_path):
    fake = _fake_openscad_script(tmp_path)
    probe = _probe(detected=True, detected_path=str(fake), detected_version="fake 1.0")

    def _boom(path):
        raise RuntimeError("trimesh exploded")

    monkeypatch.setattr(tq, "validate_mesh", _boom)
    result = tq._qualify_openscad_stable("OpenSCAD (stable)", probe)
    assert result["qualification_status"] == "partially_qualified"
    checks_by_id = {c["check_id"]: c for c in result["checks"]}
    assert checks_by_id["openscad_factory_validation"]["status"] == "fail"


def test_openscad_export_timeout_reported_and_does_not_raise(monkeypatch, tmp_path):
    fake = tmp_path / "hangs-openscad"
    fake.write_text("#!/bin/sh\nsleep 5\n")
    fake.chmod(0o755)
    probe = _probe(detected=True, detected_path=str(fake), detected_version="fake 1.0")
    monkeypatch.setattr(tq, "_OPENSCAD_EXPORT_TIMEOUT_SECONDS", 0.05)
    result = tq._qualify_openscad_stable("OpenSCAD (stable)", probe)
    assert result["qualification_status"] in ("partially_qualified", "unqualified")
    assert any("timed out" in e for e in result["errors"])
    assert result["temporary_artifacts_cleaned"] is True


def test_openscad_export_nonzero_exit_handled(monkeypatch, tmp_path):
    fake = tmp_path / "failing-openscad"
    fake.write_text("#!/bin/sh\necho 'bad geometry' 1>&2\nexit 1\n")
    fake.chmod(0o755)
    probe = _probe(detected=True, detected_path=str(fake), detected_version="fake 1.0")
    result = tq._qualify_openscad_stable("OpenSCAD (stable)", probe)
    checks_by_id = {c["check_id"]: c for c in result["checks"]}
    assert checks_by_id["openscad_temp_scad_exported"]["status"] == "fail"
    assert checks_by_id["openscad_stl_output_valid"]["status"] == "fail"
    assert result["qualification_status"] in ("partially_qualified", "unqualified")


def test_openscad_missing_stl_output_rejected(monkeypatch, tmp_path):
    fake = tmp_path / "no-output-openscad"
    fake.write_text("#!/bin/sh\nexit 0\n")  # exits 0 but never writes the STL
    fake.chmod(0o755)
    probe = _probe(detected=True, detected_path=str(fake), detected_version="fake 1.0")
    result = tq._qualify_openscad_stable("OpenSCAD (stable)", probe)
    checks_by_id = {c["check_id"]: c for c in result["checks"]}
    assert checks_by_id["openscad_stl_output_valid"]["status"] == "fail"
    assert "missing" in checks_by_id["openscad_stl_output_valid"]["evidence"]


def test_openscad_empty_stl_rejected(monkeypatch, tmp_path):
    fake = tmp_path / "empty-output-openscad"
    fake.write_text(
        "#!/bin/sh\n"
        "out=\"\"\n"
        "while [ $# -gt 0 ]; do case \"$1\" in -o) out=\"$2\"; shift 2 ;; *) shift ;; esac; done\n"
        "touch \"$out\"\n"  # zero bytes
    )
    fake.chmod(0o755)
    probe = _probe(detected=True, detected_path=str(fake), detected_version="fake 1.0")
    result = tq._qualify_openscad_stable("OpenSCAD (stable)", probe)
    checks_by_id = {c["check_id"]: c for c in result["checks"]}
    assert checks_by_id["openscad_stl_output_valid"]["status"] == "fail"
    assert "empty" in checks_by_id["openscad_stl_output_valid"]["evidence"]


def test_openscad_version_probe_failure_reflected_but_not_fatal(monkeypatch, tmp_path):
    fake = _fake_openscad_script(tmp_path)
    probe = _probe(
        detected=True,
        detected_path=str(fake),
        detected_version="unknown",
        probe_warnings=["version probe failed: boom"],
    )
    monkeypatch.setattr(tq, "validate_mesh", lambda path: {"overall_status": "PASS"})
    result = tq._qualify_openscad_stable("OpenSCAD (stable)", probe)
    checks_by_id = {c["check_id"]: c for c in result["checks"]}
    assert checks_by_id["openscad_cli_responds"]["status"] == "warn"
    # export/validation still run and can still reach qualified even if --version failed
    assert result["qualification_status"] == "qualified"


def test_openscad_snapshot_never_conflated_with_stable():
    result = tq._qualify_openscad_snapshot("OpenSCAD (snapshot/development)", _probe(probe_status="not_applicable"))
    assert result["tool_id"] == "openscad_snapshot"
    assert result["qualification_status"] == "not_installed"
    assert result["detected"] is False
    assert result["checks"][0]["status"] == "skip"


def test_openscad_stable_and_snapshot_are_independent_results(monkeypatch, tmp_path):
    fake = _fake_openscad_script(tmp_path)
    stable_probe = _probe(detected=True, detected_path=str(fake), detected_version="fake 1.0")
    monkeypatch.setattr(tq, "validate_mesh", lambda path: {"overall_status": "PASS"})
    stable_result = tq._qualify_openscad_stable("OpenSCAD (stable)", stable_probe)
    snapshot_result = tq._qualify_openscad_snapshot("OpenSCAD (snapshot/development)", _probe())
    assert stable_result["qualification_status"] == "qualified"
    assert snapshot_result["qualification_status"] == "not_installed"


def _fake_openscad_script(tmp_path):
    script = tmp_path / "fake-openscad"
    script.write_text(
        "#!/bin/sh\n"
        "out=\"\"\n"
        "while [ $# -gt 0 ]; do\n"
        "  case \"$1\" in\n"
        "    -o) out=\"$2\"; shift 2 ;;\n"
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        "printf 'solid x\\nendsolid x\\n' > \"$out\"\n"
    )
    script.chmod(0o755)
    return script

"""Phase 44 tests: `factory.tool_qualification`'s CadQuery qualification.

Covers: package absent/present, version discovered, the in-process capability
test (never real project/user Python), export verification, import failure,
and Factory validator reuse. See docs/tool-qualification.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from factory import tool_qualification as tq


def _probe(**overrides) -> dict:
    base = {"detected": False, "detected_path": None, "detected_version": "unknown", "probe_status": "not_installed", "probe_warnings": []}
    base.update(overrides)
    return base


def test_cadquery_package_absent():
    result = tq._qualify_cadquery("CadQuery", _probe())
    assert result["detected"] is False
    assert result["qualification_status"] == "not_installed"
    assert result["qualification_level"] == "metadata_only"


def test_cadquery_present_and_capability_test_succeeds(monkeypatch, tmp_path):
    def _fake_probe_out(tmp_dir: Path):
        stl_path = tmp_dir / "qualification_fixture.stl"
        stl_path.write_text("solid x\nendsolid x\n")
        return {"stl_path": stl_path}

    monkeypatch.setattr(tq, "_run_cadquery_capability_probe", _fake_probe_out)
    monkeypatch.setattr(tq, "validate_mesh", lambda path: {"overall_status": "PASS"})
    probe = _probe(detected=True, detected_version="2.4.0")
    result = tq._qualify_cadquery("CadQuery", probe)
    assert result["qualification_status"] == "qualified"
    assert result["qualification_level"] == "factory_workflow_verified"
    assert "cadquery_source_generation" in result["capabilities_verified"]
    assert "stl_export" in result["capabilities_verified"]
    assert result["temporary_artifacts_created"] is True
    assert result["temporary_artifacts_cleaned"] is True


def test_cadquery_version_discovered_from_probe():
    probe = _probe(detected=True, detected_version="2.4.0")

    def _boom(tmp_dir):
        raise RuntimeError("no OCC bindings")

    import factory.tool_qualification as tq_module

    orig = tq_module._run_cadquery_capability_probe
    try:
        tq_module._run_cadquery_capability_probe = _boom
        result = tq_module._qualify_cadquery("CadQuery", probe)
    finally:
        tq_module._run_cadquery_capability_probe = orig
    assert result["detected_version"] == "2.4.0"


def test_cadquery_capability_construct_failure_never_executes_arbitrary_python(monkeypatch):
    """A capability-probe import/construct failure must be caught, never
    escape as an unhandled exception, and never imply arbitrary project
    Python was ever run."""

    def _boom(tmp_dir):
        raise ImportError("cadquery import failed")

    monkeypatch.setattr(tq, "_run_cadquery_capability_probe", _boom)
    probe = _probe(detected=True, detected_version="2.4.0")
    result = tq._qualify_cadquery("CadQuery", probe)
    assert result["qualification_status"] == "unqualified"
    assert result["qualification_level"] == "metadata_only"
    checks_by_id = {c["check_id"]: c for c in result["checks"]}
    assert checks_by_id["cadquery_capability_construct"]["status"] == "fail"


def test_cadquery_export_missing_output_handled(monkeypatch, tmp_path):
    def _fake_probe_out(tmp_dir: Path):
        # Claims success but never actually writes the file.
        return {"stl_path": tmp_dir / "does_not_exist.stl"}

    monkeypatch.setattr(tq, "_run_cadquery_capability_probe", _fake_probe_out)
    probe = _probe(detected=True, detected_version="2.4.0")
    result = tq._qualify_cadquery("CadQuery", probe)
    assert result["qualification_status"] == "partially_qualified"
    assert result["qualification_level"] == "capability_verified"
    checks_by_id = {c["check_id"]: c for c in result["checks"]}
    assert checks_by_id["cadquery_stl_export"]["status"] == "fail"


def test_cadquery_validator_reused_not_reimplemented(monkeypatch):
    calls = []

    def _fake_probe_out(tmp_dir: Path):
        stl_path = tmp_dir / "qualification_fixture.stl"
        stl_path.write_text("solid x\nendsolid x\n")
        return {"stl_path": stl_path}

    def _tracking_validate(path):
        calls.append(path)
        return {"overall_status": "PASS"}

    monkeypatch.setattr(tq, "_run_cadquery_capability_probe", _fake_probe_out)
    monkeypatch.setattr(tq, "validate_mesh", _tracking_validate)
    probe = _probe(detected=True, detected_version="2.4.0")
    tq._qualify_cadquery("CadQuery", probe)
    assert len(calls) == 1


def test_cadquery_qualification_never_imports_arbitrary_project_python():
    """Source inspection: the CadQuery qualification path never calls
    `exec`/`eval`/`importlib.import_module` against anything project- or
    user-supplied - it only ever imports the fixed `cadquery` dependency
    itself inside `_run_cadquery_capability_probe`."""
    import inspect

    source = inspect.getsource(tq._qualify_cadquery)
    for forbidden in ("exec(", "eval(", "import_module", "compile("):
        assert forbidden not in source

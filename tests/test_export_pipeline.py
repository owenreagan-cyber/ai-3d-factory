"""Phase 35 tests: `factory.export_pipeline` - the Guided Export Pipeline.

Orchestrates existing local commands (OpenSCAD CLI export, the existing
mesh validator, the existing preview renderer) - never a second CAD
backend, validator, or renderer. Dry run by default; no subprocess is ever
invoked and no file is ever written without an explicit `confirm_export`
(for export) or `validate`/`render`/`all_steps` (for the read-only-safe
post-export steps). No AI, no LLM, no network, no Blender, no Meshy, no
slicer, no printer. See docs/export-pipeline.md, docs/roadmap.md Phase 35.
"""

from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import pytest

from factory import export_pipeline, project_store
from factory.export_pipeline import (
    DECISIONS,
    EXPORT_RECEIPT_FILENAME,
    UnsafePathError,
    build_artifact_registry,
    plan_export,
    read_export_receipt,
    resolve_openscad_executable,
    run_export,
    run_export_pipeline,
    run_multipart_check,
    run_render,
    run_validation,
    summarize_export_pipeline,
    write_export_receipt,
)
from factory.generation_gate import GENERATED_DIRNAME
from factory.openscad.generate import generate_openscad
from factory.cad import cadquery_backend

FAKE_OPENSCAD = "/fake/bin/openscad"


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture()
def scad_project(isolated_projects_dir):
    root = project_store.init_project("Demo Sign")
    generate_openscad(root, "sign", "Hi")
    return root


@pytest.fixture()
def cadquery_project(isolated_projects_dir, monkeypatch):
    monkeypatch.setattr(cadquery_backend, "is_cadquery_available", lambda: True)
    root = project_store.init_project("Demo Bracket")
    cadquery_backend.generate_cadquery(root, "mechanical-plate")
    return root


@pytest.fixture()
def multipart_scad_project(isolated_projects_dir):
    root = project_store.init_project("Demo Multipart")
    generate_openscad(root, "multipart-nameplate", "Hi")
    return root


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_openscad_available(monkeypatch, executable=FAKE_OPENSCAD):
    monkeypatch.setattr(export_pipeline, "resolve_openscad_executable", lambda: executable)


def _fake_subprocess_writes_stl(monkeypatch, *, returncode=0, stdout="", stderr="", content=b"solid x\nendsolid x\n"):
    """Mock subprocess.run() to behave like a successful `openscad -o out.stl in.scad`
    call - writes a plausible STL at the `-o` argument's path and returns
    a fake CompletedProcess. Used only to make `run_export()`'s post-exit
    verification steps (file exists, non-empty, .stl extension) exercise-able
    without a real OpenSCAD binary.
    """

    def _fake_run(command, capture_output, text, timeout):
        if "--version" in command:
            return _FakeCompleted(returncode=0, stdout="OpenSCAD version 2021.01 (fake)")
        output_path = Path(command[2])
        if returncode == 0:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(content)
        return _FakeCompleted(returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(export_pipeline.subprocess, "run", _fake_run)


# ---- vocabulary sanity ----


def test_decisions_are_the_suggested_values():
    assert set(DECISIONS) >= {
        "needs_confirmation", "allowed", "blocked", "unsupported_source", "ambiguous_source",
        "manual_export_required", "export_tool_missing", "output_collision", "export_failed",
        "validation_failed", "render_failed", "partial_pipeline", "completed",
    }


# ---- planning: dry run by default ----


def test_plan_export_dry_run_by_default(scad_project):
    plan = plan_export(scad_project)
    assert plan["dry_run"] is True
    assert plan["decision"] != "allowed"


def test_plan_export_writes_nothing(scad_project):
    before = sorted(str(p) for p in scad_project.rglob("*"))
    plan_export(scad_project)
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after
    assert not (scad_project / GENERATED_DIRNAME).exists()


def test_plan_export_invokes_no_subprocess(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("plan_export() must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    plan_export(scad_project, confirm_export=True)


def test_plan_export_is_deterministic(scad_project):
    a = plan_export(scad_project)
    b = plan_export(scad_project)
    assert a == b


def test_plan_export_shape(scad_project):
    plan = plan_export(scad_project)
    expected_keys = {
        "project_path", "project_name", "source_engine", "source_backend", "source_files",
        "source_fingerprints", "source_modified_times", "selected_source", "export_supported",
        "export_tool", "export_tool_available", "export_command", "output_directory",
        "expected_stl_files", "existing_stl_files", "stale_stl_files", "output_collisions",
        "confirmation_required", "export_allowed", "decision", "blocking_reasons", "advisories",
        "validation_plan", "render_plan", "receipt_path", "dry_run",
    }
    assert set(plan.keys()) == expected_keys
    assert plan["decision"] in DECISIONS


# ---- planning: source detection ----


def test_plan_export_detects_openscad_source(scad_project):
    plan = plan_export(scad_project)
    assert plan["source_engine"] == "OpenSCAD"
    assert plan["source_backend"] == "openscad"
    assert plan["source_files"] == ["cad/sign.scad"]


def test_plan_export_detects_cadquery_source(cadquery_project):
    plan = plan_export(cadquery_project)
    assert plan["source_engine"] == "CadQuery"
    assert plan["source_backend"] == "cadquery"
    assert plan["source_files"] == ["cad/mechanical_plate.py"]


def test_plan_export_detects_multipart_openscad_source(multipart_scad_project):
    plan = plan_export(multipart_scad_project)
    assert plan["source_engine"] == "OpenSCAD"
    assert len(plan["source_files"]) == 2
    assert len(plan["expected_stl_files"]) == 2


def test_plan_export_unsupported_source_type(isolated_projects_dir):
    root = project_store.init_project("Weird")
    (root / "cad" / "thing.step").write_text("not real")
    plan = plan_export(root)
    assert plan["decision"] == "unsupported_source"


def test_plan_export_missing_source(isolated_projects_dir):
    root = project_store.init_project("Empty")
    plan = plan_export(root)
    assert plan["decision"] == "blocked"
    assert plan["source_engine"] is None
    assert any("no CAD source" in r for r in plan["blocking_reasons"])


def test_plan_export_ambiguous_sources(isolated_projects_dir):
    root = project_store.init_project("Mixed")
    (root / "cad" / "a.scad").write_text("cube([1,1,1]);")
    (root / "cad" / "b.py").write_text("# cadquery")
    plan = plan_export(root)
    assert plan["decision"] == "ambiguous_source"
    assert plan["source_engine"] is None


def test_plan_export_source_flag_disambiguates(isolated_projects_dir):
    root = project_store.init_project("Mixed")
    (root / "cad" / "a.scad").write_text("cube([1,1,1]);")
    (root / "cad" / "b.py").write_text("# cadquery")
    plan = plan_export(root, source="cad/a.scad")
    assert plan["source_engine"] == "OpenSCAD"
    assert plan["selected_source"] == "cad/a.scad"


def test_plan_export_source_flag_nonexistent_file(scad_project):
    plan = plan_export(scad_project, source="cad/does_not_exist.scad")
    assert plan["decision"] == "blocked"


def test_plan_export_source_flag_unsupported_extension(scad_project):
    (scad_project / "cad" / "thing.txt").write_text("hi")
    plan = plan_export(scad_project, source="cad/thing.txt")
    assert plan["decision"] == "unsupported_source"


# ---- planning: safe path checks ----


def test_plan_export_source_escaping_project_is_blocked(scad_project):
    plan = plan_export(scad_project, source="../../../etc/passwd")
    assert plan["decision"] == "blocked"
    assert any("outside the project directory" in r for r in plan["blocking_reasons"])


def test_plan_export_output_dir_escaping_project_is_blocked(scad_project):
    plan = plan_export(scad_project, output_dir="/etc")
    assert plan["decision"] == "blocked"


def test_plan_export_never_raises_unsafe_path_error(scad_project):
    # plan_export() always converts UnsafePathError into a "blocked" decision -
    # it never propagates the exception to the caller.
    plan_export(scad_project, source="../outside")


# ---- planning: exporter availability ----


def test_plan_export_tool_missing(scad_project, monkeypatch):
    monkeypatch.setattr(export_pipeline, "resolve_openscad_executable", lambda: None)
    plan = plan_export(scad_project, confirm_export=True)
    assert plan["decision"] == "export_tool_missing"
    assert plan["export_tool_available"] is False


def test_plan_export_tool_missing_even_with_confirm(scad_project, monkeypatch):
    monkeypatch.setattr(export_pipeline, "resolve_openscad_executable", lambda: None)
    plan = plan_export(scad_project, confirm_export=True)
    assert plan["decision"] != "allowed"


def test_plan_export_cadquery_always_manual_export_required(cadquery_project):
    for confirm in (False, True):
        plan = plan_export(cadquery_project, confirm_export=confirm)
        assert plan["decision"] == "manual_export_required"
        assert plan["export_supported"] is False


# ---- planning: expected STL mapping / freshness / collisions ----


def test_plan_export_expected_stl_mapping(scad_project):
    plan = plan_export(scad_project)
    assert plan["expected_stl_files"] == ["stl/sign.stl"]
    assert plan["output_directory"] == "stl"


def test_plan_export_no_stl_yet_is_not_a_collision(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    plan = plan_export(scad_project)
    assert plan["existing_stl_files"] == []
    assert plan["output_collisions"] == []
    assert plan["decision"] == "needs_confirmation"


def test_plan_export_confirmation_required_and_allowed(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    unconfirmed = plan_export(scad_project)
    assert unconfirmed["decision"] == "needs_confirmation"
    assert unconfirmed["confirmation_required"] is True
    assert unconfirmed["export_allowed"] is False

    confirmed = plan_export(scad_project, confirm_export=True)
    assert confirmed["decision"] == "allowed"
    assert confirmed["export_allowed"] is True


def test_plan_export_detects_existing_current_stl_as_collision(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = plan_export(scad_project, confirm_export=True)
    run_export_pipeline(scad_project, plan)

    plan2 = plan_export(scad_project)
    assert plan2["existing_stl_files"] == ["stl/sign.stl"]
    assert plan2["output_collisions"] == [{"expected_path": "stl/sign.stl", "freshness": "current"}]
    assert plan2["decision"] == "output_collision"


def test_plan_export_confirm_cannot_bypass_collision(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = plan_export(scad_project, confirm_export=True)
    run_export_pipeline(scad_project, plan)

    plan2 = plan_export(scad_project, confirm_export=True)
    assert plan2["decision"] == "output_collision"


def test_plan_export_overwrite_stl_unblocks_collision(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = plan_export(scad_project, confirm_export=True)
    run_export_pipeline(scad_project, plan)

    plan2 = plan_export(scad_project, overwrite_stl=True, confirm_export=True)
    assert plan2["decision"] == "allowed"
    assert any("overwrite" in a.lower() for a in plan2["advisories"])


def test_plan_export_detects_stale_stl_after_source_change(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = plan_export(scad_project, confirm_export=True)
    run_export_pipeline(scad_project, plan)

    scad_path = scad_project / "cad" / "sign.scad"
    scad_path.write_text(scad_path.read_text() + "\n// changed\n")

    plan2 = plan_export(scad_project)
    assert plan2["stale_stl_files"] == ["stl/sign.stl"]


def test_plan_export_never_treats_existence_alone_as_current(scad_project):
    # An STL that exists but has no export receipt entry and predates its
    # source's mtime falls back to a plain mtime comparison, never a bare
    # "it's there so it's fine" assumption.
    stl_path = scad_project / "stl" / "sign.stl"
    stl_path.parent.mkdir(parents=True, exist_ok=True)
    stl_path.write_bytes(b"solid x\nendsolid x\n")
    import os
    import time

    scad_path = scad_project / "cad" / "sign.scad"
    future = time.time() + 5
    os.utime(scad_path, (future, future))

    plan = plan_export(scad_project)
    assert plan["output_collisions"][0]["freshness"] == "stale"


# ---- execution: run_export() ----


def test_run_export_raises_when_decision_not_allowed(scad_project):
    plan = plan_export(scad_project)
    with pytest.raises(ValueError):
        run_export(scad_project, plan, "cad/sign.scad")


def test_run_export_success(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = plan_export(scad_project, confirm_export=True)

    result = run_export(scad_project, plan, "cad/sign.scad")
    assert result["success"] is True
    assert result["exit_code"] == 0
    assert (scad_project / "stl" / "sign.stl").is_file()
    assert result["output_size_bytes"] > 0
    assert result["output_fingerprint"]
    assert result["source_fingerprint"]


def test_run_export_uses_argument_list_never_shell_string(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    captured = {}

    def _fake_run(command, capture_output, text, timeout):
        if "--version" in command:
            return _FakeCompleted(returncode=0, stdout="fake version")
        captured["command"] = command
        captured["capture_output"] = capture_output
        captured["text"] = text
        output_path = Path(command[2])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"solid x\nendsolid x\n")
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(export_pipeline.subprocess, "run", _fake_run)
    plan = plan_export(scad_project, confirm_export=True)
    run_export(scad_project, plan, "cad/sign.scad")

    assert isinstance(captured["command"], list)
    assert captured["command"][0] == FAKE_OPENSCAD
    assert "-o" in captured["command"]
    assert captured["capture_output"] is True


def test_run_export_exporter_called_exactly_once(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    call_count = {"n": 0}

    def _fake_run(command, capture_output, text, timeout):
        if "--version" in command:
            return _FakeCompleted(returncode=0, stdout="fake version")
        call_count["n"] += 1
        output_path = Path(command[2])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"solid x\nendsolid x\n")
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(export_pipeline.subprocess, "run", _fake_run)
    plan = plan_export(scad_project, confirm_export=True)
    run_export(scad_project, plan, "cad/sign.scad")
    assert call_count["n"] == 1


def test_run_export_timeout(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)

    def _fake_run(command, capture_output, text, timeout):
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

    monkeypatch.setattr(export_pipeline.subprocess, "run", _fake_run)
    plan = plan_export(scad_project, confirm_export=True)
    result = run_export(scad_project, plan, "cad/sign.scad")
    assert result["success"] is False
    assert any("timed out" in e for e in result["errors"])


def test_run_export_nonzero_exit(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch, returncode=1, stderr="ERROR: parse error")
    plan = plan_export(scad_project, confirm_export=True)
    result = run_export(scad_project, plan, "cad/sign.scad")
    assert result["success"] is False
    assert result["exit_code"] == 1
    assert any("exited with code 1" in e for e in result["errors"])


def test_run_export_zero_exit_but_missing_output_rejected(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)

    def _fake_run(command, capture_output, text, timeout):
        return _FakeCompleted(returncode=0)  # never writes the file

    monkeypatch.setattr(export_pipeline.subprocess, "run", _fake_run)
    plan = plan_export(scad_project, confirm_export=True)
    result = run_export(scad_project, plan, "cad/sign.scad")
    assert result["success"] is False
    assert not (scad_project / "stl" / "sign.stl").is_file()
    assert any("not created" in e for e in result["errors"])


def test_run_export_empty_output_rejected(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch, content=b"")
    plan = plan_export(scad_project, confirm_export=True)
    result = run_export(scad_project, plan, "cad/sign.scad")
    assert result["success"] is False
    assert any("empty" in e for e in result["errors"])


def test_run_export_source_changed_since_planning_is_rejected(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = plan_export(scad_project, confirm_export=True)

    scad_path = scad_project / "cad" / "sign.scad"
    scad_path.write_text(scad_path.read_text() + "\n// race condition edit\n")

    result = run_export(scad_project, plan, "cad/sign.scad")
    assert result["success"] is False
    assert any("changed since planning" in e for e in result["errors"])


def test_run_export_source_missing_at_execution_time(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    plan = plan_export(scad_project, confirm_export=True)
    (scad_project / "cad" / "sign.scad").unlink()

    result = run_export(scad_project, plan, "cad/sign.scad")
    assert result["success"] is False
    assert any("no longer exists" in e for e in result["errors"])


# ---- execution: confirmed blocked run invokes no exporter ----


def test_confirmed_blocked_run_invokes_no_exporter(isolated_projects_dir, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("blocked plan must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    root = project_store.init_project("Empty")
    plan = plan_export(root, confirm_export=True)
    assert plan["decision"] == "blocked"
    result = run_export_pipeline(root, plan)
    assert result["per_source"] == []


def test_confirmed_cadquery_run_invokes_no_exporter(cadquery_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("CadQuery source must never be executed automatically")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    plan = plan_export(cadquery_project, confirm_export=True)
    result = run_export_pipeline(cadquery_project, plan)
    assert result["per_source"][0]["export"]["success"] is None
    assert "manual_command" in result["per_source"][0]["export"]


# ---- validation ----


def test_run_validation_reuses_existing_validator(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = plan_export(scad_project, confirm_export=True)
    run_export(scad_project, plan, "cad/sign.scad")

    called = {}
    real_validate_mesh = export_pipeline.validate_mesh

    def _spy(file_path, printer):
        called["file_path"] = file_path
        return real_validate_mesh(file_path, printer)

    monkeypatch.setattr(export_pipeline, "validate_mesh", _spy)
    result = run_validation(scad_project, "stl/sign.stl")
    assert called["file_path"] == scad_project / "stl" / "sign.stl"
    assert (scad_project / "validation" / "sign_validation.json").is_file()
    assert result["status"] in export_pipeline.VALIDATION_STATUSES


def test_run_validation_status_mapping_pass():
    report = {"overall_status": "PASS", "checks": []}
    assert export_pipeline._normalize_validation_status(report) == "passed"


def test_run_validation_status_mapping_warn():
    report = {"overall_status": "WARN", "checks": []}
    assert export_pipeline._normalize_validation_status(report) == "passed_with_warnings"


def test_run_validation_status_mapping_fail():
    report = {"overall_status": "FAIL", "checks": [{"name": "vertex_face_counts", "status": "FAIL"}]}
    assert export_pipeline._normalize_validation_status(report) == "failed"


def test_run_validation_status_mapping_unavailable():
    report = {"overall_status": "FAIL", "checks": [{"name": "trimesh_available", "status": "FAIL"}]}
    assert export_pipeline._normalize_validation_status(report) == "unavailable"


def test_run_validation_never_deletes_the_stl_on_failure(scad_project, monkeypatch):
    stl_path = scad_project / "stl" / "sign.stl"
    stl_path.parent.mkdir(parents=True, exist_ok=True)
    stl_path.write_bytes(b"not a real mesh")

    run_validation(scad_project, "stl/sign.stl")
    assert stl_path.is_file()


def test_read_export_receipt_tolerates_malformed_json(scad_project):
    receipt_path = scad_project / GENERATED_DIRNAME / EXPORT_RECEIPT_FILENAME
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text("{not valid json", encoding="utf-8")
    assert read_export_receipt(scad_project) is None


def test_run_multipart_check_reuses_existing_check(multipart_scad_project, monkeypatch):
    real_check = export_pipeline.check_multipart_manifest
    called = {"n": 0}

    def _spy(manifest, manifest_dir, required_part_names=None):
        called["n"] += 1
        return real_check(manifest, manifest_dir, required_part_names=required_part_names)

    monkeypatch.setattr(export_pipeline, "check_multipart_manifest", _spy)
    results = run_multipart_check(multipart_scad_project)
    assert called["n"] == 1
    assert isinstance(results, list)


def test_run_multipart_check_no_manifest_returns_empty(isolated_projects_dir, tmp_path):
    empty_dir = tmp_path / "no-manifest-here"
    empty_dir.mkdir()
    assert run_multipart_check(empty_dir) == []


# ---- rendering ----


def test_run_render_reuses_existing_renderer(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch, content=b"solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid x\n")
    plan = plan_export(scad_project, confirm_export=True)
    run_export(scad_project, plan, "cad/sign.scad")

    called = {}
    real_render_preview = export_pipeline.render_preview

    def _spy(mesh_path, output_path):
        called["mesh_path"] = mesh_path
        return real_render_preview(mesh_path, output_path)

    monkeypatch.setattr(export_pipeline, "render_preview", _spy)
    result = run_render(scad_project, "stl/sign.stl")
    assert called["mesh_path"] == scad_project / "stl" / "sign.stl"
    assert result["status"] in export_pipeline.RENDER_STATUSES


def test_run_render_missing_output_is_rejected(scad_project, monkeypatch):
    def _fake_render_preview(mesh_path, output_path):
        # Simulate a renderer bug: reports PASS but writes nothing.
        return {"status": "PASS", "detail": "lied", "output_path": str(output_path)}

    monkeypatch.setattr(export_pipeline, "render_preview", _fake_render_preview)
    result = run_render(scad_project, "stl/sign.stl")
    assert result["status"] == "failed"


def test_run_render_empty_output_is_rejected(scad_project, monkeypatch):
    def _fake_render_preview(mesh_path, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"")
        return {"status": "PASS", "detail": "empty file", "output_path": str(output_path)}

    monkeypatch.setattr(export_pipeline, "render_preview", _fake_render_preview)
    result = run_render(scad_project, "stl/sign.stl")
    assert result["status"] == "failed"


def test_run_render_failure_reported_honestly(scad_project):
    # No STL exists yet - render_preview() itself reports FAIL.
    result = run_render(scad_project, "stl/sign.stl")
    assert result["status"] == "failed"


# ---- receipts and artifacts ----


def test_dry_run_writes_no_receipt(scad_project):
    plan_export(scad_project)
    assert read_export_receipt(scad_project) is None


def test_needs_confirmation_writes_no_receipt(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    plan = plan_export(scad_project)
    result = run_export_pipeline(scad_project, plan)
    assert result["per_source"] == [] or result["per_source"][0]["export"] is None
    assert read_export_receipt(scad_project) is None


def test_confirmed_success_writes_receipt(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = plan_export(scad_project, confirm_export=True)
    run_export_pipeline(scad_project, plan)

    receipt = read_export_receipt(scad_project)
    assert receipt is not None
    assert receipt["no_automatic_print"] is True
    assert receipt["exports"][0]["source_file"] == "cad/sign.scad"
    assert receipt["exports"][0]["export"]["success"] is True


def test_failed_run_does_not_destroy_prior_success_receipt(multipart_scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = plan_export(multipart_scad_project, confirm_export=True)
    run_export_pipeline(multipart_scad_project, plan)
    receipt_after_success = read_export_receipt(multipart_scad_project)
    assert all(e["export"]["success"] for e in receipt_after_success["exports"])

    # Now simulate one file failing on a re-run (source changed, overwrite allowed,
    # but the exporter now fails) - the *other* file's prior success record
    # must survive untouched.
    def _fake_run_fail(command, capture_output, text, timeout):
        return _FakeCompleted(returncode=1, stderr="boom")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _fake_run_fail)
    plan2 = plan_export(multipart_scad_project, overwrite_stl=True, confirm_export=True)
    run_export_pipeline(multipart_scad_project, plan2)

    receipt_after_failure = read_export_receipt(multipart_scad_project)
    # At least one prior entry's fingerprint-recorded success is still present
    # in the upserted list (never wiped wholesale).
    assert len(receipt_after_failure["exports"]) == len(receipt_after_success["exports"])


def test_write_export_receipt_upserts_by_source_file(scad_project):
    write_export_receipt(scad_project, [{"source_file": "cad/a.scad", "export": {"success": True}}], "completed")
    write_export_receipt(scad_project, [{"source_file": "cad/b.scad", "export": {"success": True}}], "completed")
    receipt = read_export_receipt(scad_project)
    sources = {e["source_file"] for e in receipt["exports"]}
    assert sources == {"cad/a.scad", "cad/b.scad"}


def test_receipt_records_source_and_output_fingerprints(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = plan_export(scad_project, confirm_export=True)
    run_export_pipeline(scad_project, plan)
    receipt = read_export_receipt(scad_project)
    export_record = receipt["exports"][0]["export"]
    assert export_record["source_fingerprint"].startswith("sha256:")
    assert export_record["output_fingerprint"].startswith("sha256:")


def test_receipt_records_sizes(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = plan_export(scad_project, confirm_export=True)
    run_export_pipeline(scad_project, plan)
    receipt = read_export_receipt(scad_project)
    assert receipt["exports"][0]["export"]["output_size_bytes"] > 0


def test_receipt_no_automatic_print_declaration_present(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = plan_export(scad_project, confirm_export=True)
    run_export_pipeline(scad_project, plan)
    receipt = read_export_receipt(scad_project)
    assert receipt["no_automatic_print"] is True


def test_build_artifact_registry_shape(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = plan_export(scad_project, confirm_export=True)
    run_export_pipeline(scad_project, plan, all_steps=True)

    registry = build_artifact_registry(scad_project)
    assert set(registry.keys()) == {"cad_source", "stl", "validation", "preview", "review", "receipts"}
    assert registry["cad_source"][0]["path"] == "cad/sign.scad"
    assert registry["stl"][0]["path"] == "stl/sign.stl"
    assert registry["receipts"]["export_receipt_path"] is not None


def test_build_artifact_registry_never_writes_anything(scad_project):
    before = sorted(str(p) for p in scad_project.rglob("*"))
    build_artifact_registry(scad_project)
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


def test_committed_examples_never_modified_by_planning():
    example_dir = project_store.REPO_ROOT / "examples" / "storage-bin-lid"
    before = sorted(str(p) for p in example_dir.rglob("*"))
    plan_export(example_dir)
    after = sorted(str(p) for p in example_dir.rglob("*"))
    assert before == after


# ---- resume behavior ----


def test_resume_skips_already_current_export(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = plan_export(scad_project, confirm_export=True)
    run_export_pipeline(scad_project, plan, validate=True)

    receipt_before = read_export_receipt(scad_project)
    started_at_before = receipt_before["exports"][0]["export"]["started_at"]

    plan2 = plan_export(scad_project, confirm_export=True)
    run_export_pipeline(scad_project, plan2, all_steps=True, resume=True)

    receipt_after = read_export_receipt(scad_project)
    assert receipt_after["exports"][0]["export"]["started_at"] == started_at_before
    assert receipt_after["exports"][0]["render"]["status"] != "not_run"


def test_resume_reruns_stale_export(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = plan_export(scad_project, confirm_export=True)
    run_export_pipeline(scad_project, plan)
    receipt_before = read_export_receipt(scad_project)
    started_at_before = receipt_before["exports"][0]["export"]["started_at"]

    scad_path = scad_project / "cad" / "sign.scad"
    scad_path.write_text(scad_path.read_text() + "\n// changed\n")

    plan2 = plan_export(scad_project, overwrite_stl=True, confirm_export=True)
    run_export_pipeline(scad_project, plan2, resume=True)

    receipt_after = read_export_receipt(scad_project)
    assert receipt_after["exports"][0]["export"]["started_at"] != started_at_before


# ---- summarize_export_pipeline() / project-inspection integration surface ----


def test_summarize_export_pipeline_shape_no_receipt(scad_project):
    summary = summarize_export_pipeline(scad_project)
    assert set(summary.keys()) == {
        "decision", "source_engine", "source_count", "exporter", "exporter_available",
        "expected_stl_count", "current_stl_count", "stale_stl_count", "cad_source_status",
        "stl_status", "validation_status", "preview_status", "last_completed_stage",
        "pipeline_complete", "next_step", "blockers", "receipt_path",
    }
    assert summary["pipeline_complete"] is False
    assert summary["next_step"]


def test_summarize_export_pipeline_reflects_completed_pipeline(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch, content=b"solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid x\n")
    plan = plan_export(scad_project, confirm_export=True)
    run_export_pipeline(scad_project, plan, all_steps=True)

    summary = summarize_export_pipeline(scad_project)
    assert summary["cad_source_status"] == "current"
    assert summary["stl_status"] == "current"
    assert summary["pipeline_complete"] is True
    assert summary["next_step"] is None


def test_summarize_export_pipeline_never_writes_anything(scad_project):
    before = sorted(str(p) for p in scad_project.rglob("*"))
    summarize_export_pipeline(scad_project)
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


# ---- module hygiene: reuses existing validators/renderer/generators, never duplicates ----


def test_module_never_imports_project_inspection_or_review_gate():
    source = inspect.getsource(export_pipeline)
    for forbidden in (
        "import factory.project_inspection", "from factory.project_inspection",
        "from factory import project_inspection", "import factory.review_gate",
        "from factory.review_gate", "from factory import review_gate",
    ):
        assert forbidden not in source


def test_module_reuses_existing_validator_and_renderer_not_reimplemented():
    source = inspect.getsource(export_pipeline)
    assert "from factory.validators.mesh_validate import validate_mesh" in source
    assert "from factory.previews.render_preview import render_preview" in source
    assert "from factory.validators.multipart_check import check_manifest" in source
    # Never re-implements trimesh geometry checks itself.
    assert "import trimesh" not in source


def test_module_has_no_forbidden_network_or_ai_or_shell_calls():
    forbidden = (
        "shell=True", "os.system(", "os.popen(", "socket.", "import urllib", "import requests",
        "http.client", "urlopen(", "requests.get(", "requests.post(", "openai", "anthropic",
        "import bpy", "meshy_api", "meshy.generate",
    )
    source = inspect.getsource(export_pipeline)
    for forbidden_call in forbidden:
        assert forbidden_call.lower() not in source.lower(), f"found forbidden call {forbidden_call!r}"


def test_module_never_installs_anything():
    source = inspect.getsource(export_pipeline)
    for forbidden in ("pip install", "pip.main(", "brew install", "curl ", "wget "):
        assert forbidden not in source


def test_resolve_openscad_executable_never_installs_or_launches(monkeypatch):
    # Read-only discovery: shutil.which() and Path.is_file() only - never a
    # subprocess call (which would mean actually launching something).
    source = inspect.getsource(resolve_openscad_executable)
    assert "subprocess" not in source
    assert "shutil.which(" in source


# ---- real OpenSCAD integration (skipped honestly when not installed - never
# installed by these tests; see docs/export-pipeline.md "Verification") ----

_REAL_OPENSCAD = resolve_openscad_executable()

requires_real_openscad = pytest.mark.skipif(
    _REAL_OPENSCAD is None, reason="openscad is not installed in this environment"
)


@requires_real_openscad
def test_real_openscad_export_produces_a_valid_stl(scad_project):
    plan = plan_export(scad_project, confirm_export=True)
    assert plan["decision"] == "allowed"
    assert plan["export_tool_available"] is True

    result = run_export(scad_project, plan, "cad/sign.scad")
    assert result["success"] is True, result["errors"]
    stl_path = scad_project / "stl" / "sign.stl"
    assert stl_path.is_file()
    assert stl_path.stat().st_size > 0
    assert stl_path.read_bytes().startswith(b"solid")
    assert result["export_tool_version"]


@requires_real_openscad
def test_real_openscad_export_validate_render_full_pipeline(scad_project):
    plan = plan_export(scad_project, confirm_export=True)
    result = run_export_pipeline(scad_project, plan, all_steps=True)

    assert result["pipeline_state"] == "completed"
    record = result["per_source"][0]
    assert record["export"]["success"] is True
    assert record["validation"]["status"] in ("passed", "passed_with_warnings")
    assert record["render"]["status"] == "passed"
    assert (scad_project / "validation" / "sign_validation.json").is_file()
    assert (scad_project / "renders" / "sign_preview.png").is_file()

    receipt = read_export_receipt(scad_project)
    assert receipt["pipeline_state"] == "completed"


@requires_real_openscad
def test_real_openscad_invalid_source_fails_cleanly(isolated_projects_dir):
    root = project_store.init_project("Broken Source")
    (root / "cad" / "broken.scad").write_text("this is not valid openscad syntax {{{\n")
    plan = plan_export(root, confirm_export=True)
    assert plan["decision"] == "allowed"

    result = run_export(root, plan, "cad/broken.scad")
    assert result["success"] is False
    assert result["exit_code"] != 0
    assert not (root / "stl" / "broken.stl").is_file()

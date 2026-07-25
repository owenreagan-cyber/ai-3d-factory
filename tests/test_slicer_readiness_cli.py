"""Phase 36 tests: the `factory slicer-readiness` CLI - a thin wrapper
around `factory.slicer_readiness`. Read-only by default; `--approve` and
`--create-package --confirm-package` are the only write paths, and each
requires its own explicit flag. No AI, no LLM, no network, no Blender, no
Meshy, no slicer, no printer, no automatic print submission. See
docs/slicer-readiness.md, docs/roadmap.md Phase 36.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory import export_pipeline, project_store
from factory.cli import app
from factory.openscad.generate import generate_openscad
from factory.slicer_readiness import (
    REVIEW_PACKAGE_FILENAME,
    SLICER_REVIEW_DIRNAME,
    read_slicer_readiness_receipt,
)

runner = CliRunner()
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


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_openscad_available(monkeypatch, executable=FAKE_OPENSCAD):
    monkeypatch.setattr(export_pipeline, "resolve_openscad_executable", lambda: executable)


def _fake_subprocess_writes_stl(monkeypatch, *, content=b"solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid x\n"):
    def _fake_run(command, capture_output, text, timeout):
        if "--version" in command:
            return _FakeCompleted(returncode=0, stdout="OpenSCAD version 2021.01 (fake)")
        output_path = Path(command[2])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(export_pipeline.subprocess, "run", _fake_run)


def _fully_ready(project_dir, monkeypatch):
    """Reach `needs_human_approval` via the real pipeline - every technical
    signal satisfied, only approval outstanding."""
    brief_path = project_dir / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["design_intent"] = {
        "quality_standard": "premium",
        "use_case": "classroom nameplate sign",
        "style_direction": ["clean", "modern"],
        "reference_inputs": ["Classroom sign example"],
        "manufacturability_constraints": {"max_size_mm": [120, 40, 5]},
    }
    project_store.save_json(brief_path, brief)
    project_store.save_json(
        project_dir / "reference_board.json",
        {
            "references": [
                {
                    "title": "Classroom sign example",
                    "source_type": "image",
                    "license": "public_domain",
                    "attached_to": "design_intent.reference_inputs",
                    "source_url": "https://example.com/sign",
                }
            ]
        },
    )
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = export_pipeline.plan_export(project_dir, confirm_export=True)
    export_pipeline.run_export_pipeline(project_dir, plan, all_steps=True)

    build_plan = project_store.load_json(project_dir / "build_plan.json")
    build_plan["selected_manufacturing_option"] = "single_piece"
    build_plan["target_printer"] = {
        "printer_id": "test-printer",
        "display_name": "Test Printer",
        "resolved": True,
        "resolved_from": "test",
        "capabilities": None,
    }
    project_store.save_json(project_dir / "build_plan.json", build_plan)
    return project_dir


# ---- human-readable output ----


def test_slicer_readiness_human_readable(scad_project):
    result = runner.invoke(app, ["slicer-readiness", str(scad_project)])
    assert result.exit_code == 0, result.stdout
    assert "Slicer Review Readiness" in result.stdout
    assert "Technical readiness:" in result.stdout
    assert "Readiness score:" in result.stdout
    assert "STL files:" in result.stdout
    assert "Validation:" in result.stdout
    assert "Previews:" in result.stdout
    assert "Manifest:" in result.stdout
    assert "Export receipts:" in result.stdout
    assert "Local slicer:" in result.stdout
    assert "Human approval:" in result.stdout
    assert "Review package:" in result.stdout
    assert "No slicer was opened." in result.stdout
    assert "No file was uploaded." in result.stdout
    assert "No print was started." in result.stdout


def test_slicer_readiness_shows_blocking_reasons_when_blocked(scad_project):
    result = runner.invoke(app, ["slicer-readiness", str(scad_project)])
    assert result.exit_code == 0, result.stdout
    assert "Blocking reasons:" in result.stdout


def test_slicer_readiness_warnings_default_to_a_count(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    result = runner.invoke(app, ["slicer-readiness", str(scad_project)])
    assert result.exit_code == 0, result.stdout
    assert "pass --include-warnings to list them" in result.stdout


def test_slicer_readiness_include_warnings_lists_them(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    result = runner.invoke(app, ["slicer-readiness", str(scad_project), "--include-warnings"])
    assert result.exit_code == 0, result.stdout
    assert "pass --include-warnings" not in result.stdout


# ---- JSON contract: never mixed with plain text ----


def test_slicer_readiness_json_is_the_only_output(scad_project):
    result = runner.invoke(app, ["slicer-readiness", str(scad_project), "--json"])
    json.loads(result.stdout)


def test_slicer_readiness_json_missing_project_is_clean_json():
    result = runner.invoke(app, ["slicer-readiness", "/no/such/project", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["errors"]
    assert payload["no_automatic_print"] is True


def test_slicer_readiness_json_shape(scad_project):
    result = runner.invoke(app, ["slicer-readiness", str(scad_project), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["readiness_status"] == "blocked"
    assert payload["dry_run"] is True
    assert payload["no_automatic_print"] is True
    assert payload["approval_result"] is None
    assert payload["package_result"] is None
    assert payload["errors"] == []


def test_slicer_readiness_help_never_touches_a_project():
    result = runner.invoke(app, ["slicer-readiness", "--help"])
    assert result.exit_code == 0, result.stdout
    assert "slicer" in result.stdout.lower()


def test_slicer_readiness_never_modifies_committed_examples():
    example_dir = project_store.REPO_ROOT / "examples" / "storage-bin-lid"
    before = sorted(str(p) for p in example_dir.rglob("*"))
    runner.invoke(app, ["slicer-readiness", str(example_dir)])
    runner.invoke(app, ["slicer-readiness", str(example_dir), "--json"])
    after = sorted(str(p) for p in example_dir.rglob("*"))
    assert before == after


def test_slicer_readiness_never_invokes_a_subprocess(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("read-only slicer-readiness must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    result = runner.invoke(app, ["slicer-readiness", str(scad_project)])
    assert result.exit_code == 0, result.stdout


# ---- --approve ----


def test_approve_requires_technical_readiness(scad_project):
    result = runner.invoke(app, ["slicer-readiness", str(scad_project), "--approve"])
    assert result.exit_code == 1, result.stdout
    assert "error" in result.stdout.lower()


def test_approve_succeeds_when_ready(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    result = runner.invoke(app, ["slicer-readiness", str(scad_project), "--approve", "--approval-note", "ship it"])
    assert result.exit_code == 0, result.stdout
    assert "approved" in result.stdout.lower()
    receipt = read_slicer_readiness_receipt(scad_project)
    assert receipt["approval"]["approved"] is True
    assert receipt["approval"]["note"] == "ship it"


def test_approve_json_is_clean(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    result = runner.invoke(app, ["slicer-readiness", str(scad_project), "--approve", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["approval_result"] is not None
    assert payload["errors"] == []


def test_approve_error_json_is_clean(scad_project):
    result = runner.invoke(app, ["slicer-readiness", str(scad_project), "--approve", "--json"])
    assert result.exit_code == 1, result.stdout
    payload = json.loads(result.stdout)
    assert payload["errors"]


def test_approve_never_creates_a_package(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    runner.invoke(app, ["slicer-readiness", str(scad_project), "--approve"])
    assert not (scad_project / SLICER_REVIEW_DIRNAME / REVIEW_PACKAGE_FILENAME).exists()


# ---- --create-package / --confirm-package ----


def test_create_package_without_confirm_package_is_rejected(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    runner.invoke(app, ["slicer-readiness", str(scad_project), "--approve"])
    result = runner.invoke(app, ["slicer-readiness", str(scad_project), "--create-package"])
    assert result.exit_code == 1, result.stdout
    assert "--confirm-package" in result.stdout
    assert not (scad_project / SLICER_REVIEW_DIRNAME / REVIEW_PACKAGE_FILENAME).exists()


def test_create_package_without_confirm_package_json_is_clean(scad_project):
    result = runner.invoke(app, ["slicer-readiness", str(scad_project), "--create-package", "--json"])
    assert result.exit_code == 1, result.stdout
    payload = json.loads(result.stdout)
    assert payload["errors"]


def test_create_package_requires_prior_approval(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    result = runner.invoke(app, ["slicer-readiness", str(scad_project), "--create-package", "--confirm-package"])
    assert result.exit_code == 1, result.stdout
    assert not (scad_project / SLICER_REVIEW_DIRNAME / REVIEW_PACKAGE_FILENAME).exists()


def test_create_package_succeeds_when_approved(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    runner.invoke(app, ["slicer-readiness", str(scad_project), "--approve"])
    result = runner.invoke(app, ["slicer-readiness", str(scad_project), "--create-package", "--confirm-package"])
    assert result.exit_code == 0, result.stdout
    assert "package created" in result.stdout.lower()
    assert (scad_project / SLICER_REVIEW_DIRNAME / REVIEW_PACKAGE_FILENAME).is_file()


def test_create_package_json_reports_package_path(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    runner.invoke(app, ["slicer-readiness", str(scad_project), "--approve"])
    result = runner.invoke(app, ["slicer-readiness", str(scad_project), "--create-package", "--confirm-package", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["package_result"]["package_path"]


def test_create_package_collision_without_force_is_rejected(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    runner.invoke(app, ["slicer-readiness", str(scad_project), "--approve"])
    runner.invoke(app, ["slicer-readiness", str(scad_project), "--create-package", "--confirm-package"])
    result = runner.invoke(app, ["slicer-readiness", str(scad_project), "--create-package", "--confirm-package"])
    assert result.exit_code == 1, result.stdout


def test_create_package_force_package_allows_recreation(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    runner.invoke(app, ["slicer-readiness", str(scad_project), "--approve"])
    runner.invoke(app, ["slicer-readiness", str(scad_project), "--create-package", "--confirm-package"])
    result = runner.invoke(
        app, ["slicer-readiness", str(scad_project), "--create-package", "--confirm-package", "--force-package"]
    )
    assert result.exit_code == 0, result.stdout


def test_create_package_never_invokes_a_subprocess(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    runner.invoke(app, ["slicer-readiness", str(scad_project), "--approve"])

    def _boom(*a, **k):
        raise AssertionError("--create-package must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    result = runner.invoke(app, ["slicer-readiness", str(scad_project), "--create-package", "--confirm-package"])
    assert result.exit_code == 0, result.stdout


# ---- --refresh is accepted but never changes behavior ----


def test_refresh_flag_is_accepted_and_inert(scad_project):
    with_refresh = runner.invoke(app, ["slicer-readiness", str(scad_project), "--refresh", "--json"])
    without_refresh = runner.invoke(app, ["slicer-readiness", str(scad_project), "--json"])
    assert json.loads(with_refresh.stdout)["readiness_status"] == json.loads(without_refresh.stdout)["readiness_status"]

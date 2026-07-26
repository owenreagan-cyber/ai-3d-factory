"""Phase 37 tests: the `factory review-workspace` CLI - a thin wrapper
around `factory.manual_review_workspace`. Read-only by default;
`--create-workspace --confirm-workspace` is the only write path. No AI,
no LLM, no network, no slicer, no G-code generation, no automatic
printing. See docs/manual-review-workspace.md, docs/roadmap.md Phase 37.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory import export_pipeline, project_store
from factory.cli import app
from factory.openscad.generate import generate_openscad
from factory.manual_review_workspace import (
    WORKSPACE_DIRNAME,
    WORKSPACE_MANIFEST_FILENAME,
    read_workspace_receipt,
)
from factory.slicer_readiness import record_approval

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


def _fully_approved(project_dir, monkeypatch):
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
        "printer_id": "bambu_h2d",
        "display_name": "Bambu Lab H2D",
        "resolved": True,
        "resolved_from": "test",
        "capabilities": None,
    }
    project_store.save_json(project_dir / "build_plan.json", build_plan)

    manifest = project_store.load_json(project_dir / "part_manifest.json")
    for part in manifest.get("parts", []):
        part["material"] = "PLA"
        part["color"] = "white"
    project_store.save_json(project_dir / "part_manifest.json", manifest)

    record_approval(project_dir)
    return project_dir


# ---- human-readable output ----


def test_review_workspace_human_readable(scad_project):
    result = runner.invoke(app, ["review-workspace", str(scad_project)])
    assert result.exit_code == 0, result.stdout
    assert "Manual Review Workspace" in result.stdout
    assert "Workspace status:" in result.stdout
    assert "Technical readiness:" in result.stdout
    assert "Printer:" in result.stdout
    assert "Material:" in result.stdout
    assert "Current STL files:" in result.stdout
    assert "Validation summary:" in result.stdout
    assert "Preview summary:" in result.stdout
    assert "Receipts:" in result.stdout
    assert "Review confidence:" in result.stdout
    assert "Remaining risk:" in result.stdout
    assert "Review checklist:" in result.stdout
    assert "No slicer was opened." in result.stdout
    assert "No G-code was generated." in result.stdout
    assert "No print was started." in result.stdout


def test_review_workspace_shows_recommended_actions(scad_project):
    result = runner.invoke(app, ["review-workspace", str(scad_project)])
    assert result.exit_code == 0, result.stdout
    assert "Recommended next actions:" in result.stdout


def test_review_workspace_shows_warnings_when_present(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    result = runner.invoke(app, ["review-workspace", str(scad_project)])
    assert result.exit_code == 0, result.stdout
    assert "Outstanding warnings:" in result.stdout


# ---- JSON contract: never mixed with plain text ----


def test_review_workspace_json_is_the_only_output(scad_project):
    result = runner.invoke(app, ["review-workspace", str(scad_project), "--json"])
    json.loads(result.stdout)


def test_review_workspace_json_missing_project_is_clean_json():
    result = runner.invoke(app, ["review-workspace", "/no/such/project", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["errors"]
    assert payload["no_automatic_print"] is True


def test_review_workspace_json_shape(scad_project):
    result = runner.invoke(app, ["review-workspace", str(scad_project), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["workspace_status"] == "not_ready"
    assert payload["dry_run"] is True
    assert payload["no_automatic_print"] is True
    assert payload["workspace_result"] is None
    assert payload["errors"] == []


def test_review_workspace_help_never_touches_a_project():
    result = runner.invoke(app, ["review-workspace", "--help"])
    assert result.exit_code == 0, result.stdout
    assert "workspace" in result.stdout.lower()


def test_review_workspace_never_modifies_committed_examples():
    example_dir = project_store.REPO_ROOT / "examples" / "storage-bin-lid"
    before = sorted(str(p) for p in example_dir.rglob("*"))
    runner.invoke(app, ["review-workspace", str(example_dir)])
    runner.invoke(app, ["review-workspace", str(example_dir), "--json"])
    after = sorted(str(p) for p in example_dir.rglob("*"))
    assert before == after


def test_review_workspace_never_invokes_a_subprocess(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("read-only review-workspace must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    result = runner.invoke(app, ["review-workspace", str(scad_project)])
    assert result.exit_code == 0, result.stdout


# ---- --create-workspace / --confirm-workspace ----


def test_create_workspace_without_confirm_workspace_is_rejected(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    result = runner.invoke(app, ["review-workspace", str(scad_project), "--create-workspace"])
    assert result.exit_code == 1, result.stdout
    assert "--confirm-workspace" in result.stdout
    assert not (scad_project / WORKSPACE_DIRNAME / WORKSPACE_MANIFEST_FILENAME).exists()


def test_create_workspace_without_confirm_workspace_json_is_clean(scad_project):
    result = runner.invoke(app, ["review-workspace", str(scad_project), "--create-workspace", "--json"])
    assert result.exit_code == 1, result.stdout
    payload = json.loads(result.stdout)
    assert payload["errors"]


def test_create_workspace_requires_technical_readiness_and_approval(scad_project):
    result = runner.invoke(app, ["review-workspace", str(scad_project), "--create-workspace", "--confirm-workspace"])
    assert result.exit_code == 1, result.stdout
    assert not (scad_project / WORKSPACE_DIRNAME / WORKSPACE_MANIFEST_FILENAME).exists()


def test_create_workspace_succeeds_when_approved(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    result = runner.invoke(app, ["review-workspace", str(scad_project), "--create-workspace", "--confirm-workspace"])
    assert result.exit_code == 0, result.stdout
    assert "workspace created" in result.stdout.lower()
    assert (scad_project / WORKSPACE_DIRNAME / WORKSPACE_MANIFEST_FILENAME).is_file()


def test_create_workspace_json_reports_workspace_path(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    result = runner.invoke(app, ["review-workspace", str(scad_project), "--create-workspace", "--confirm-workspace", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["workspace_result"]["workspace_path"]


def test_create_workspace_collision_without_force_is_rejected(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    runner.invoke(app, ["review-workspace", str(scad_project), "--create-workspace", "--confirm-workspace"])
    result = runner.invoke(app, ["review-workspace", str(scad_project), "--create-workspace", "--confirm-workspace"])
    assert result.exit_code == 1, result.stdout


def test_create_workspace_force_workspace_allows_recreation(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    runner.invoke(app, ["review-workspace", str(scad_project), "--create-workspace", "--confirm-workspace"])
    result = runner.invoke(
        app, ["review-workspace", str(scad_project), "--create-workspace", "--confirm-workspace", "--force-workspace"]
    )
    assert result.exit_code == 0, result.stdout


def test_create_workspace_never_invokes_a_subprocess(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)

    def _boom(*a, **k):
        raise AssertionError("--create-workspace must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    result = runner.invoke(app, ["review-workspace", str(scad_project), "--create-workspace", "--confirm-workspace"])
    assert result.exit_code == 0, result.stdout


def test_create_workspace_writes_receipt(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    runner.invoke(app, ["review-workspace", str(scad_project), "--create-workspace", "--confirm-workspace"])
    receipt = read_workspace_receipt(scad_project)
    assert receipt is not None
    assert "workspace" in receipt

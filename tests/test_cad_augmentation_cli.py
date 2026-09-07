"""Phase 50 CLI tests: `factory cad-augment plan` / `factory cad-augment
execute`. Kept as its own Typer group, separate from `factory workflow`
(planning-only) and `factory blender-adapt` (a different workflow).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory import export_pipeline, project_store
from factory.cli import app, cad_augment_app

runner = CliRunner()

_MINIMAL_STL = (
    "solid t\n"
    "facet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\n"
    "facet normal 0 0 -1\nouter loop\nvertex 0 0 0\nvertex 0 1 0\nvertex 1 0 0\nendloop\nendfacet\n"
    "endsolid t\n"
)


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture()
def blender_adapted_project(isolated_projects_dir):
    root = project_store.init_project("Piggy Bank")
    adapted_dir = root / "generated" / "blender" / "adapted"
    adapted_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = adapted_dir / "01a07ca5_adapted.stl"
    artifact_path.write_text(_MINIMAL_STL)
    return root, artifact_path


def _fake_openscad_writes_stl(monkeypatch):
    monkeypatch.setattr(export_pipeline, "resolve_openscad_executable", lambda: "/fake/bin/openscad")

    class _FakeCompleted:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(command, capture_output, text, timeout):
        if "--version" in command:
            return _FakeCompleted(returncode=0, stdout="OpenSCAD version 2021.01 (fake)")
        output_path = Path(command[2])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(_MINIMAL_STL.encode())
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(export_pipeline.subprocess, "run", _fake_run)


def test_cad_augment_plan_json(blender_adapted_project):
    _, artifact_path = blender_adapted_project
    result = runner.invoke(
        app,
        ["cad-augment", "plan", str(artifact_path), "--base-width-mm", "120", "--base-length-mm", "80", "--base-height-mm", "10", "--json"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["plan"]["workflow_type"] == "organic_mechanical_augmentation"
    assert payload["plan"]["automatic_execution_allowed"] is False
    assert all(v is False for v in payload["safety"].values())


def test_cad_augment_plan_human_readable(blender_adapted_project):
    _, artifact_path = blender_adapted_project
    result = runner.invoke(app, ["cad-augment", "plan", str(artifact_path)])
    assert result.exit_code == 0
    assert "CAD AUGMENTATION PLAN" in result.stdout
    assert "Automatic printing remains impossible" in result.stdout


def test_cad_augment_plan_reports_missing_parameters(blender_adapted_project):
    _, artifact_path = blender_adapted_project
    result = runner.invoke(app, ["cad-augment", "plan", str(artifact_path)])
    assert result.exit_code == 0
    assert "Missing required parameter" in result.stdout


def test_cad_augment_execute_blocked_without_confirm(blender_adapted_project):
    _, artifact_path = blender_adapted_project
    result = runner.invoke(
        app,
        ["cad-augment", "execute", str(artifact_path), "--base-width-mm", "120", "--base-length-mm", "80", "--base-height-mm", "10", "--json"],
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["result"]["augmentation_status"] == "blocked"


def test_cad_augment_execute_requires_base_dimensions():
    result = runner.invoke(app, ["cad-augment", "execute", "some.stl", "--confirm"])
    assert result.exit_code != 0


def test_cad_augment_execute_succeeds_with_confirm(blender_adapted_project, monkeypatch):
    project_dir, artifact_path = blender_adapted_project
    _fake_openscad_writes_stl(monkeypatch)

    result = runner.invoke(
        app,
        [
            "cad-augment", "execute", str(artifact_path),
            "--base-width-mm", "120", "--base-length-mm", "80", "--base-height-mm", "10",
            "--confirm", "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["result"]["augmentation_status"] == "succeeded"
    assert (project_dir / "generated" / "cad_augmentation_receipt.json").is_file()


def test_cad_augment_execute_human_readable_succeeds(blender_adapted_project, monkeypatch):
    _, artifact_path = blender_adapted_project
    _fake_openscad_writes_stl(monkeypatch)

    result = runner.invoke(
        app,
        [
            "cad-augment", "execute", str(artifact_path),
            "--base-width-mm", "120", "--base-length-mm", "80", "--base-height-mm", "10",
            "--confirm",
        ],
    )
    assert result.exit_code == 0
    assert "CAD AUGMENTATION EXECUTION" in result.stdout
    assert "Automatic printing remains impossible" in result.stdout


def test_no_run_arbitrary_file_style_command_exists():
    """No arbitrary-execution interface - every command name is a fixed,
    narrow verb (mirrors `factory blender-adapt`'s identical guarantee)."""
    registered = {c.name for c in cad_augment_app.registered_commands}
    assert registered == {"plan", "execute"}


def test_top_level_help_lists_cad_augment_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "cad-augment" in result.stdout

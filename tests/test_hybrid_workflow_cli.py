"""Phase 48 CLI tests: `factory workflow plan` / `factory workflow assess`.
Both are read-only planning commands - neither ever executes an
adaptation, and there is deliberately no `workflow execute` command.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory import project_store
from factory.cli import app, workflow_app

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
def meshy_project(isolated_projects_dir):
    root = project_store.init_project("Piggy Bank")
    artifact_dir = root / "generated" / "meshy" / "processed"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "01a07ca5.stl"
    artifact_path.write_text(_MINIMAL_STL)
    receipt = {
        "meshy_task_id": "01a07ca5-0c06-7459-b1f4-68f383774fae",
        "mock_execution": False, "live_api_used": True, "ai_model": "meshy-7",
        "validation_status": "WARN", "preview_status": "PASS",
        "output_artifact_paths": [str(artifact_path)],
    }
    project_store.save_json(root / "generated" / "meshy_receipt.json", receipt)
    return root


def test_workflow_plan_json(meshy_project):
    result = runner.invoke(app, ["workflow", "plan", str(meshy_project), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["artifact_type"] == "meshy_organic"
    assert payload["recommended_engine"] == "blender"
    assert payload["automatic_execution_allowed"] is False


def test_workflow_plan_human_readable(meshy_project):
    result = runner.invoke(app, ["workflow", "plan", str(meshy_project)])
    assert result.exit_code == 0
    assert "HYBRID WORKFLOW PLAN" in result.stdout
    assert "Automatic execution is impossible" in result.stdout


def test_workflow_plan_rejects_nonexistent_directory(tmp_path):
    result = runner.invoke(app, ["workflow", "plan", str(tmp_path / "does-not-exist")])
    assert result.exit_code == 1


def test_workflow_assess_json(tmp_path):
    stl_path = tmp_path / "sample.stl"
    stl_path.write_text(_MINIMAL_STL)
    result = runner.invoke(app, ["workflow", "assess", str(stl_path), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["error"] is None
    assert payload["scale_assessment"]["requires_human_confirmation"] is True


def test_workflow_assess_human_readable(tmp_path):
    stl_path = tmp_path / "sample.stl"
    stl_path.write_text(_MINIMAL_STL)
    result = runner.invoke(app, ["workflow", "assess", str(stl_path)])
    assert result.exit_code == 0
    assert "ARTIFACT ASSESSMENT" in result.stdout
    assert "A human must confirm" in result.stdout


def test_workflow_assess_missing_file_errors(tmp_path):
    result = runner.invoke(app, ["workflow", "assess", str(tmp_path / "nope.stl")])
    assert result.exit_code == 1


def test_help_lists_new_commands():
    result = runner.invoke(app, ["workflow", "--help"])
    assert "plan" in result.stdout
    assert "assess" in result.stdout


def test_no_execute_command_exists():
    """Planning first - no `workflow execute` unless a future phase
    explicitly approves actual transformations."""
    registered = {c.name for c in workflow_app.registered_commands}
    assert registered == {"plan", "assess"}
    assert "execute" not in registered


def test_top_level_help_lists_workflow_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "workflow" in result.stdout

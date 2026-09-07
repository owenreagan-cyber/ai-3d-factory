"""Phase 49 Preview Board tests: `blender_adaptation_summary` wiring into
`factory.preview_board.gather_board_data()` at the aggregation point only
- never inside `factory.project_health`/`factory.project_inspection` (per
the standing Aggregation Layer Convention). Never invokes Blender or any
subprocess during board generation.
"""

from __future__ import annotations

import socket
import subprocess

import pytest

from factory import blender_adaptation, project_store
from factory.preview_board import gather_board_data

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
    return root, artifact_path


def test_board_includes_blender_adaptation_summary_field(isolated_projects_dir, meshy_project):
    data = gather_board_data(isolated_projects_dir)
    assert data["project_count"] == 1
    assert "blender_adaptation_summary" in data["projects"][0]


def test_summary_reports_unavailable_before_any_execution(isolated_projects_dir, meshy_project):
    data = gather_board_data(isolated_projects_dir)
    summary = data["projects"][0]["blender_adaptation_summary"]
    assert summary["adaptation_available"] is False
    assert summary["workflow"] is None


def test_summary_reflects_a_completed_receipt(isolated_projects_dir, meshy_project):
    project_dir, artifact_path = meshy_project
    receipt = {
        "blender_adaptation_version": 1,
        "workflow": "organic_cleanup_workflow",
        "input_artifact": "generated/meshy/processed/01a07ca5.stl",
        "input_hash": "sha256:abc",
        "output_artifact": "generated/blender/adapted/01a07ca5_adapted.stl",
        "output_hash": "sha256:def",
        "validation_status": "PASS",
        "preview_status": "PASS",
        "single_shot_human_confirmation": True,
    }
    project_store.save_json(project_dir / "generated" / "blender_adaptation_receipt.json", receipt)

    data = gather_board_data(isolated_projects_dir)
    summary = data["projects"][0]["blender_adaptation_summary"]
    assert summary["adaptation_available"] is True
    assert summary["workflow"] == "organic_cleanup_workflow"
    assert summary["validation_status"] == "PASS"
    assert summary["human_confirmed"] is True


def test_board_generation_never_invokes_blender_or_subprocess(isolated_projects_dir, meshy_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("preview board generation must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    data = gather_board_data(isolated_projects_dir)
    assert data["project_count"] == 1


def test_summarize_blender_adaptation_reused_directly_not_reimplemented(isolated_projects_dir, meshy_project):
    """The board's summary must come from
    factory.blender_adaptation.summarize_blender_adaptation() - never a
    second read of the receipt."""
    project_dir, _ = meshy_project
    data = gather_board_data(isolated_projects_dir)
    direct = blender_adaptation.summarize_blender_adaptation(project_dir)
    assert data["projects"][0]["blender_adaptation_summary"] == direct

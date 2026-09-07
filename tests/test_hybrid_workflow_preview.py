"""Phase 48 preview-board tests: `hybrid_workflow_summary` is wired into
`factory.preview_board.gather_board_data()` at the aggregation point only
(never inside `factory.project_health`/`factory.project_inspection` - see
the standing "Aggregation Layer Convention" in docs/architecture.md), and
never changes any project's `health_score`/`visual_readiness_state`
merely because a hybrid-workflow plan exists.
"""

from __future__ import annotations

import pytest

from factory import project_store
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


def _make_plain_project(isolated_projects_dir):
    return project_store.init_project("Plain Project")


def _make_meshy_project(isolated_projects_dir):
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


def test_board_data_includes_hybrid_workflow_summary_field(isolated_projects_dir):
    _make_plain_project(isolated_projects_dir)
    board = gather_board_data(isolated_projects_dir)
    assert board["projects"]
    for project in board["projects"]:
        assert "hybrid_workflow_summary" in project


def test_no_artifact_project_reports_plan_unavailable(isolated_projects_dir):
    _make_plain_project(isolated_projects_dir)
    board = gather_board_data(isolated_projects_dir)
    summary = board["projects"][0]["hybrid_workflow_summary"]
    assert summary["plan_available"] is False


def test_meshy_project_reports_plan_available_with_recommendation(isolated_projects_dir):
    _make_meshy_project(isolated_projects_dir)
    board = gather_board_data(isolated_projects_dir)
    summary = board["projects"][0]["hybrid_workflow_summary"]
    assert summary["plan_available"] is True
    assert summary["recommended_engine"] == "blender"


def test_hybrid_workflow_summary_does_not_change_health_score(isolated_projects_dir):
    """A project's health_score must come purely from
    factory.project_health - never bumped or penalized merely because a
    hybrid-workflow plan/recommendation exists."""
    plain = _make_plain_project(isolated_projects_dir)
    board_before = gather_board_data(isolated_projects_dir)
    health_before = board_before["projects"][0]["project_health_summary"]["score"]

    # Attach a Meshy artifact to the SAME project after the fact - the
    # health score must be computed independently of hybrid_workflow_summary.
    artifact_dir = plain / "generated" / "meshy" / "processed"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "01a07ca5.stl"
    artifact_path.write_text(_MINIMAL_STL)
    project_store.save_json(
        plain / "generated" / "meshy_receipt.json",
        {
            "meshy_task_id": "01a07ca5-0c06-7459-b1f4-68f383774fae",
            "mock_execution": False, "live_api_used": True, "ai_model": "meshy-7",
            "validation_status": "WARN", "preview_status": "PASS",
            "output_artifact_paths": [str(artifact_path)],
        },
    )
    board_after = gather_board_data(isolated_projects_dir)
    health_after = board_after["projects"][0]["project_health_summary"]["score"]
    assert health_after == health_before


def test_board_generation_stays_read_only_with_hybrid_workflow_wired_in(isolated_projects_dir, monkeypatch):
    import socket
    import subprocess

    _make_meshy_project(isolated_projects_dir)

    def _boom(*a, **k):
        raise AssertionError("preview board generation must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    gather_board_data(isolated_projects_dir)

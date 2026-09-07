"""Phase 51 Preview Board tests: `design_review_summary` wiring into
`factory.preview_board.gather_board_data()` at the aggregation point only
- never inside `factory.project_health`/`factory.project_inspection` (per
the standing Aggregation Layer Convention). Never invokes Meshy/Blender/
CAD/a subprocess during board generation.
"""

from __future__ import annotations

import socket
import subprocess

import pytest

from factory import design_review, project_store
from factory.preview_board import gather_board_data, write_preview_board

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
    artifact_path = adapted_dir / "abc_adapted.stl"
    artifact_path.write_text(_MINIMAL_STL)
    project_store.save_json(
        root / "generated" / "blender_adaptation_receipt.json",
        {
            "workflow": "organic_cleanup_workflow",
            "input_artifact": "generated/meshy/processed/abc.stl", "input_hash": "sha256:x",
            "output_artifact": "generated/blender/adapted/abc_adapted.stl",
            "output_hash": design_review._file_fingerprint(artifact_path),
            "single_shot_human_confirmation": True, "validation_status": "PASS",
        },
    )
    return root


def test_board_includes_design_review_summary_field(isolated_projects_dir, blender_adapted_project):
    data = gather_board_data(isolated_projects_dir)
    assert data["project_count"] == 1
    assert "design_review_summary" in data["projects"][0]


def test_summary_reports_unavailable_with_no_artifact(isolated_projects_dir):
    project_store.init_project("Nothing Yet")
    data = gather_board_data(isolated_projects_dir)
    summary = data["projects"][0]["design_review_summary"]
    assert summary["review_available"] is False


def test_summary_reflects_the_chain(isolated_projects_dir, blender_adapted_project):
    data = gather_board_data(isolated_projects_dir)
    summary = data["projects"][0]["design_review_summary"]
    assert summary["review_available"] is True
    assert isinstance(summary["design_quality_score"], int)
    assert isinstance(summary["top_risks"], list)
    assert len(summary["top_risks"]) <= 2


def test_board_generation_never_invokes_execution_or_subprocess(isolated_projects_dir, blender_adapted_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("preview board generation must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    data = gather_board_data(isolated_projects_dir)
    assert data["project_count"] == 1


def test_summarize_design_review_reused_directly_not_reimplemented(isolated_projects_dir, blender_adapted_project):
    data = gather_board_data(isolated_projects_dir)
    direct = design_review.summarize_design_review(blender_adapted_project)
    assert data["projects"][0]["design_review_summary"] == direct


def test_html_card_renders_without_error(isolated_projects_dir, blender_adapted_project, tmp_path):
    output_dir = tmp_path / "board_output"
    write_preview_board(isolated_projects_dir, output_dir=output_dir, fmt="html")
    html = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "Hybrid Design Review" in html

"""Phase 52 Preview Board tests: `manufacturing_readiness_summary` wiring
into `factory.preview_board.gather_board_data()` at the aggregation point
only - never inside `factory.project_health`/`factory.design_review`/
`factory.project_inspection` (per the standing Aggregation Layer
Convention). Never invokes Meshy/Blender/CAD/a subprocess during board
generation.
"""

from __future__ import annotations

import socket
import subprocess

import pytest

from factory import manufacturing_readiness, project_store
from factory.design_review import _file_fingerprint
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
    meshy_dir = root / "generated" / "meshy" / "processed"
    meshy_dir.mkdir(parents=True, exist_ok=True)
    parent_path = meshy_dir / "abc.stl"
    parent_path.write_text(_MINIMAL_STL)

    adapted_dir = root / "generated" / "blender" / "adapted"
    adapted_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = adapted_dir / "abc_adapted.stl"
    artifact_path.write_text(_MINIMAL_STL)
    project_store.save_json(
        root / "generated" / "blender_adaptation_receipt.json",
        {
            "workflow": "organic_cleanup_workflow",
            "input_artifact": "generated/meshy/processed/abc.stl", "input_hash": _file_fingerprint(parent_path),
            "output_artifact": "generated/blender/adapted/abc_adapted.stl",
            "output_hash": _file_fingerprint(artifact_path),
            "single_shot_human_confirmation": True, "validation_status": "PASS",
        },
    )
    return root


def test_board_includes_manufacturing_readiness_summary_field(isolated_projects_dir, blender_adapted_project):
    data = gather_board_data(isolated_projects_dir)
    assert data["project_count"] == 1
    assert "manufacturing_readiness_summary" in data["projects"][0]


def test_summary_available_even_with_no_hybrid_chain(isolated_projects_dir):
    project_store.init_project("Nothing Yet")
    data = gather_board_data(isolated_projects_dir)
    summary = data["projects"][0]["manufacturing_readiness_summary"]
    assert summary["available"] is True
    assert summary["readiness_state"] == "not_ready"


def test_summary_reflects_the_chain(isolated_projects_dir, blender_adapted_project):
    data = gather_board_data(isolated_projects_dir)
    summary = data["projects"][0]["manufacturing_readiness_summary"]
    assert summary["readiness_state"] in manufacturing_readiness.READINESS_STATES
    assert isinstance(summary["readiness_score"], int)
    assert len(summary["top_blockers"]) <= 2
    assert len(summary["top_warnings"]) <= 2


def test_board_generation_never_invokes_execution_or_subprocess(isolated_projects_dir, blender_adapted_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("preview board generation must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    data = gather_board_data(isolated_projects_dir)
    assert data["project_count"] == 1


def test_summarize_manufacturing_readiness_reused_directly_not_reimplemented(isolated_projects_dir, blender_adapted_project):
    data = gather_board_data(isolated_projects_dir)
    direct = manufacturing_readiness.summarize_manufacturing_readiness(blender_adapted_project)
    assert data["projects"][0]["manufacturing_readiness_summary"] == direct


def test_html_card_renders_without_error(isolated_projects_dir, blender_adapted_project, tmp_path):
    output_dir = tmp_path / "board_output"
    write_preview_board(isolated_projects_dir, output_dir=output_dir, fmt="html")
    html = (output_dir / "index.html").read_text(encoding="utf-8")
    assert "Manufacturing Readiness" in html

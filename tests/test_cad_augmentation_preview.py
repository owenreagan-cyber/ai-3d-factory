"""Phase 50 Preview Board tests: `cad_augmentation_summary` wiring into
`factory.preview_board.gather_board_data()` at the aggregation point only
- never inside `factory.project_health`/`factory.project_inspection` (per
the standing Aggregation Layer Convention). Never invokes OpenSCAD or any
subprocess during board generation.
"""

from __future__ import annotations

import socket
import subprocess

import pytest

from factory import cad_augmentation, project_store
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
def blender_adapted_project(isolated_projects_dir):
    root = project_store.init_project("Piggy Bank")
    adapted_dir = root / "generated" / "blender" / "adapted"
    adapted_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = adapted_dir / "01a07ca5_adapted.stl"
    artifact_path.write_text(_MINIMAL_STL)
    return root, artifact_path


def test_board_includes_cad_augmentation_summary_field(isolated_projects_dir, blender_adapted_project):
    data = gather_board_data(isolated_projects_dir)
    assert data["project_count"] == 1
    assert "cad_augmentation_summary" in data["projects"][0]


def test_summary_reports_unavailable_before_any_execution(isolated_projects_dir, blender_adapted_project):
    data = gather_board_data(isolated_projects_dir)
    summary = data["projects"][0]["cad_augmentation_summary"]
    assert summary["augmentation_available"] is False
    assert summary["workflow"] is None


def test_summary_reflects_a_completed_receipt(isolated_projects_dir, blender_adapted_project):
    project_dir, _ = blender_adapted_project
    receipt = {
        "cad_augmentation_version": 1,
        "workflow": "organic_mechanical_augmentation",
        "input_artifact": "generated/blender/adapted/01a07ca5_adapted.stl",
        "input_hash": "sha256:abc",
        "output_artifact": "generated/cad_augmentation/01a07ca5_adapted_feature.stl",
        "output_hash": "sha256:def",
        "cad_engine": "openscad_stable",
        "validation_status": "PASS",
        "preview_status": "PASS",
        "single_shot_human_confirmation": True,
    }
    project_store.save_json(project_dir / "generated" / "cad_augmentation_receipt.json", receipt)

    data = gather_board_data(isolated_projects_dir)
    summary = data["projects"][0]["cad_augmentation_summary"]
    assert summary["augmentation_available"] is True
    assert summary["workflow"] == "organic_mechanical_augmentation"
    assert summary["validation_status"] == "PASS"
    assert summary["human_confirmed"] is True


def test_board_generation_never_invokes_openscad_or_subprocess(isolated_projects_dir, blender_adapted_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("preview board generation must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    data = gather_board_data(isolated_projects_dir)
    assert data["project_count"] == 1


def test_summarize_cad_augmentation_reused_directly_not_reimplemented(isolated_projects_dir, blender_adapted_project):
    project_dir, _ = blender_adapted_project
    data = gather_board_data(isolated_projects_dir)
    direct = cad_augmentation.summarize_cad_augmentation(project_dir)
    assert data["projects"][0]["cad_augmentation_summary"] == direct

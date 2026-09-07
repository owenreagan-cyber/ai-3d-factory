"""Phase 52 CLI tests: `factory manufacturing-readiness <project>`. A
single, flat, read-only-by-default command - no `plan`/`execute`
subcommands, no `approve`/`print`/`manufacture` verb.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from factory import project_store
from factory.cli import app
from factory.design_review import _file_fingerprint

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


def test_manufacturing_readiness_json(blender_adapted_project):
    result = runner.invoke(app, ["manufacturing-readiness", str(blender_adapted_project), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["report"]["automatic_print_allowed"] is False
    assert all(v is False for v in payload["safety"].values())


def test_manufacturing_readiness_human_readable(blender_adapted_project):
    result = runner.invoke(app, ["manufacturing-readiness", str(blender_adapted_project)])
    assert result.exit_code == 0
    assert "MANUFACTURING READINESS" in result.stdout
    assert "Automatic printing remains" in result.stdout
    assert "impossible" in result.stdout


def test_manufacturing_readiness_verbose_shows_warnings(blender_adapted_project):
    result = runner.invoke(app, ["manufacturing-readiness", str(blender_adapted_project), "--verbose"])
    assert result.exit_code == 0
    assert "Warnings:" in result.stdout or "warnings" in result.stdout.lower()


def test_manufacturing_readiness_rejects_nonexistent_directory(tmp_path):
    result = runner.invoke(app, ["manufacturing-readiness", str(tmp_path / "does-not-exist")])
    assert result.exit_code == 1


def test_manufacturing_readiness_never_writes(blender_adapted_project):
    files_before = sorted(p.relative_to(blender_adapted_project) for p in blender_adapted_project.rglob("*") if p.is_file())
    runner.invoke(app, ["manufacturing-readiness", str(blender_adapted_project)])
    runner.invoke(app, ["manufacturing-readiness", str(blender_adapted_project), "--json"])
    runner.invoke(app, ["manufacturing-readiness", str(blender_adapted_project), "--verbose"])
    files_after = sorted(p.relative_to(blender_adapted_project) for p in blender_adapted_project.rglob("*") if p.is_file())
    assert files_before == files_after


def test_no_forbidden_verbs_registered():
    """No approve/print/manufacture/execute/send command exists anywhere
    in the top-level app for this phase's feature."""
    registered_names = {c.name for c in app.registered_commands}
    for forbidden in ("approve", "print", "manufacture", "send", "approve-print"):
        assert forbidden not in registered_names


def test_top_level_help_lists_manufacturing_readiness_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "manufacturing-readiness" in result.stdout

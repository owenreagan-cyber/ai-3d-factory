"""Phase 51 CLI tests: `factory design-review <project>`. A single,
flat, read-only-by-default command - no `plan`/`execute` subcommands, no
`approve`/`print`/`manufacture` verb.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from factory import design_review, project_store
from factory.cli import app

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


def test_design_review_json(blender_adapted_project):
    result = runner.invoke(app, ["design-review", str(blender_adapted_project), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["review"]["automatic_print_allowed"] is False
    assert all(v is False for v in payload["safety"].values())
    assert "report_path" not in payload


def test_design_review_human_readable(blender_adapted_project):
    result = runner.invoke(app, ["design-review", str(blender_adapted_project)])
    assert result.exit_code == 0
    assert "HYBRID DESIGN QUALITY REVIEW" in result.stdout
    assert "Automatic printing remains impossible" in result.stdout


def test_design_review_rejects_nonexistent_directory(tmp_path):
    result = runner.invoke(app, ["design-review", str(tmp_path / "does-not-exist")])
    assert result.exit_code == 1


def test_design_review_default_never_writes(blender_adapted_project):
    files_before = sorted(p.relative_to(blender_adapted_project) for p in blender_adapted_project.rglob("*") if p.is_file())
    runner.invoke(app, ["design-review", str(blender_adapted_project)])
    runner.invoke(app, ["design-review", str(blender_adapted_project), "--json"])
    files_after = sorted(p.relative_to(blender_adapted_project) for p in blender_adapted_project.rglob("*") if p.is_file())
    assert files_before == files_after


def test_design_review_save_writes_snapshot(blender_adapted_project):
    result = runner.invoke(app, ["design-review", str(blender_adapted_project), "--save", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    report_path = blender_adapted_project / "generated" / "design_review_report.json"
    assert payload["report_path"] == str(report_path)
    assert report_path.is_file()


def test_no_forbidden_verbs_registered():
    """No approve/print/manufacture/execute command exists anywhere in
    the top-level app for this phase's feature."""
    registered_names = {c.name for c in app.registered_commands}
    for forbidden in ("approve", "print", "manufacture"):
        assert forbidden not in registered_names


def test_top_level_help_lists_design_review_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "design-review" in result.stdout

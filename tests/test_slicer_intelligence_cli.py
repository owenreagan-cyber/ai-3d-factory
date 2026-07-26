"""Phase 38 tests: the `factory slicer-inspect` CLI - a thin, entirely
read-only wrapper around `factory.slicer_intelligence`. No AI, no LLM, no
network, no slicer, no G-code generation, no printer communication. See
docs/slicer-intelligence.md, docs/roadmap.md Phase 38.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory import export_pipeline, project_store
from factory.cli import app
from factory.openscad.generate import generate_openscad

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


def _fully_ready(project_dir, monkeypatch):
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
    return project_dir


# ---- human-readable output ----


def test_slicer_inspect_human_readable(scad_project):
    result = runner.invoke(app, ["slicer-inspect", str(scad_project)])
    assert result.exit_code == 0, result.stdout
    assert "Slicer Review Intelligence" in result.stdout
    assert "Project:" in result.stdout
    assert "Printer:" in result.stdout
    assert "Build Volume:" in result.stdout
    assert "Risk:" in result.stdout
    assert "Confidence:" in result.stdout
    assert "No slicer was opened." in result.stdout
    assert "No G-code was generated." in result.stdout
    assert "No print was started." in result.stdout


def test_slicer_inspect_shows_review_priorities_when_present(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    result = runner.invoke(app, ["slicer-inspect", str(scad_project)])
    assert result.exit_code == 0, result.stdout
    assert "Review Priorities:" in result.stdout


def test_slicer_inspect_shows_warnings_when_present(scad_project):
    result = runner.invoke(app, ["slicer-inspect", str(scad_project)])
    assert result.exit_code == 0, result.stdout
    assert "Warnings:" in result.stdout


def test_slicer_inspect_shows_margin_when_build_volume_fits(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    result = runner.invoke(app, ["slicer-inspect", str(scad_project)])
    assert result.exit_code == 0, result.stdout
    assert "remaining margin" in result.stdout


# ---- JSON contract: never mixed with plain text ----


def test_slicer_inspect_json_is_the_only_output(scad_project):
    result = runner.invoke(app, ["slicer-inspect", str(scad_project), "--json"])
    json.loads(result.stdout)


def test_slicer_inspect_json_missing_project_is_clean_json():
    result = runner.invoke(app, ["slicer-inspect", "/no/such/project", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["errors"]
    assert payload["no_automatic_print"] is True


def test_slicer_inspect_json_shape(scad_project):
    result = runner.invoke(app, ["slicer-inspect", str(scad_project), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["analysis_status"] == "no_geometry_data"
    assert payload["dry_run"] is True
    assert payload["no_automatic_print"] is True
    assert payload["errors"] == []


def test_slicer_inspect_help_never_touches_a_project():
    result = runner.invoke(app, ["slicer-inspect", "--help"])
    assert result.exit_code == 0, result.stdout
    assert "slicer" in result.stdout.lower()


def test_slicer_inspect_never_modifies_committed_examples():
    example_dir = project_store.REPO_ROOT / "examples" / "storage-bin-lid"
    before = sorted(str(p) for p in example_dir.rglob("*"))
    runner.invoke(app, ["slicer-inspect", str(example_dir)])
    runner.invoke(app, ["slicer-inspect", str(example_dir), "--json"])
    after = sorted(str(p) for p in example_dir.rglob("*"))
    assert before == after


def test_slicer_inspect_never_invokes_a_subprocess(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("read-only slicer-inspect must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    result = runner.invoke(app, ["slicer-inspect", str(scad_project)])
    assert result.exit_code == 0, result.stdout


def test_slicer_inspect_never_makes_a_network_call(scad_project, monkeypatch):
    import socket

    def _boom(*a, **k):
        raise AssertionError("slicer-inspect must never open a network socket")

    monkeypatch.setattr(socket, "socket", _boom)
    result = runner.invoke(app, ["slicer-inspect", str(scad_project)])
    assert result.exit_code == 0, result.stdout

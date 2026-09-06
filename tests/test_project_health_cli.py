"""Phase 42 tests: the `factory health` CLI - a thin, entirely read-only
wrapper around `factory.project_health`. No AI, no LLM, no network, no
slicer, no G-code generation, no printer communication, no approval, no
readiness recalculation. See docs/project-health.md, docs/roadmap.md
Phase 42.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory import export_pipeline, project_store
from factory.cli import app
from factory.openscad.generate import generate_openscad
from factory.slicer_readiness import record_approval

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


def _export_all(project_dir, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = export_pipeline.plan_export(project_dir, confirm_export=True)
    export_pipeline.run_export_pipeline(project_dir, plan, all_steps=True)


def _fully_approved(project_dir, monkeypatch):
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
    _export_all(project_dir, monkeypatch)

    build_plan_path = project_dir / "build_plan.json"
    build_plan = project_store.load_json(build_plan_path)
    build_plan["selected_manufacturing_option"] = "single_piece"
    build_plan["target_printer"] = {
        "printer_id": "bambu_h2d",
        "display_name": "Bambu Lab H2D",
        "resolved": True,
        "resolved_from": "test",
        "capabilities": None,
    }
    project_store.save_json(build_plan_path, build_plan)

    manifest_path = project_dir / "part_manifest.json"
    manifest = project_store.load_json(manifest_path)
    for part in manifest.get("parts", []):
        part["material"] = "PLA"
        part["color"] = "white"
    project_store.save_json(manifest_path, manifest)

    record_approval(project_dir)
    return project_dir


# ---------------------------------------------------------------------------
# Human-readable output
# ---------------------------------------------------------------------------


def test_health_human_readable(scad_project):
    result = runner.invoke(app, ["health", str(scad_project)])
    assert result.exit_code == 0, result.stdout
    assert "PROJECT HEALTH" in result.stdout
    assert "Status:" in result.stdout
    assert "Health:" in result.stdout
    assert "Lifecycle:" in result.stdout
    assert "Next Action:" in result.stdout
    assert "Human approval required. No automatic printing." in result.stdout


def test_health_ready_for_slicer_review(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    result = runner.invoke(app, ["health", str(scad_project)])
    assert result.exit_code == 0, result.stdout
    assert "Ready for Slicer Review" in result.stdout
    assert "Blockers:\n0" in result.stdout


def test_health_missing_project_dir():
    result = runner.invoke(app, ["health", "/no/such/project"])
    assert result.exit_code == 1
    assert "error" in result.stdout.lower()


def test_health_verbose_shows_extra_detail(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    result = runner.invoke(app, ["health", str(scad_project), "--verbose"])
    assert result.exit_code == 0, result.stdout
    assert "Health score breakdown:" in result.stdout
    assert "Recent Activity:" in result.stdout
    assert "Artifact History:" in result.stdout
    assert "Strengths:" in result.stdout


def test_health_non_verbose_omits_extra_detail(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    result = runner.invoke(app, ["health", str(scad_project)])
    assert result.exit_code == 0, result.stdout
    assert "Health score breakdown:" not in result.stdout
    assert "Recent Activity:" not in result.stdout


# ---------------------------------------------------------------------------
# JSON contract
# ---------------------------------------------------------------------------


def test_health_json_is_the_only_output(scad_project):
    result = runner.invoke(app, ["health", str(scad_project), "--json"])
    json.loads(result.stdout)


def test_health_json_missing_project_is_clean_json():
    result = runner.invoke(app, ["health", "/no/such/project", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["errors"]
    assert payload["no_automatic_print"] is True


def test_health_json_shape(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    result = runner.invoke(app, ["health", str(scad_project), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    for key in (
        "project", "overall_status", "health_score", "health_level", "lifecycle_stage",
        "completion_percentage", "next_action", "blockers", "warnings", "risks", "strengths",
        "timeline_summary", "artifact_summary", "readiness_summary", "review_summary",
        "slicer_summary", "manufacturing_summary", "engine_summary", "confidence",
        "no_automatic_print", "errors",
    ):
        assert key in payload, key
    assert payload["errors"] == []
    assert payload["no_automatic_print"] is True
    assert payload["overall_status"] == "Ready for Slicer Review"


def test_health_json_deterministic(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    a = runner.invoke(app, ["health", str(scad_project), "--json"])
    b = runner.invoke(app, ["health", str(scad_project), "--json"])
    assert json.loads(a.stdout) == json.loads(b.stdout)


def test_health_json_score_never_bypasses_blocked_status(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    brief_path = scad_project / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["design_intent"]["manufacturability_constraints"] = {"max_size_mm": [99999, 99999, 99999]}
    project_store.save_json(brief_path, brief)

    result = runner.invoke(app, ["health", str(scad_project), "--json"])
    payload = json.loads(result.stdout)
    assert payload["overall_status"] == "Blocked"
    assert payload["health_score"] > 0


def test_health_help_never_touches_a_project():
    result = runner.invoke(app, ["health", "--help"])
    assert result.exit_code == 0, result.stdout
    assert "health" in result.stdout.lower()
    assert "--verbose" in result.stdout
    assert "--json" in result.stdout


def test_health_command_listed_in_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.stdout
    assert "health" in result.stdout


# ---------------------------------------------------------------------------
# Safety: no writes, no subprocess, no network
# ---------------------------------------------------------------------------


def test_health_never_modifies_committed_examples():
    example_dir = project_store.REPO_ROOT / "examples" / "storage-bin-lid"
    before = sorted(str(p) for p in example_dir.rglob("*"))
    runner.invoke(app, ["health", str(example_dir)])
    runner.invoke(app, ["health", str(example_dir), "--json"])
    runner.invoke(app, ["health", str(example_dir), "--verbose"])
    after = sorted(str(p) for p in example_dir.rglob("*"))
    assert before == after


def test_health_never_writes_anything(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    before = sorted(str(p) for p in scad_project.rglob("*"))
    runner.invoke(app, ["health", str(scad_project)])
    runner.invoke(app, ["health", str(scad_project), "--json"])
    runner.invoke(app, ["health", str(scad_project), "--verbose"])
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


def test_health_never_invokes_a_subprocess(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("read-only health command must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    result = runner.invoke(app, ["health", str(scad_project)])
    assert result.exit_code == 0, result.stdout


def test_health_never_makes_a_network_call(scad_project, monkeypatch):
    import socket

    def _boom(*a, **k):
        raise AssertionError("health command must never open a network socket")

    monkeypatch.setattr(socket, "socket", _boom)
    result = runner.invoke(app, ["health", str(scad_project)])
    assert result.exit_code == 0, result.stdout

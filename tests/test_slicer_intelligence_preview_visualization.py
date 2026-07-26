"""Phase 38 tests: wiring `slicer_intelligence_summary` into the Preview
Board (via `factory.preview_board.gather_board_data()`, not
`factory.project_inspection.summarize_project()` - see the architectural
note below) and rendering a compact "Slicer Intelligence" card in the
Preview Board HTML. See docs/slicer-intelligence.md, docs/preview-board.md,
docs/roadmap.md Phase 38.

**Architectural note:** this field lives outside `project_inspection.py`
for the same reason Phase 36/37's own summary fields do -
`factory.slicer_intelligence` calls
`factory.manual_review_workspace.assess_manual_review_workspace()`, which
calls `factory.slicer_readiness.assess_slicer_readiness()`, which calls
`factory.review_gate.evaluate_review_gate()`, which already imports
`summarize_project()`. Adding the field inside `project_inspection.py`
would recreate the exact circular import Phase 36 already discovered.
These tests exist to prove the board stays entirely read-only even with
this extra per-project call, and that every existing detail card is
preserved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory import export_pipeline, project_store
from factory.cli import app
from factory.openscad.generate import generate_openscad
from factory.preview_board import VISUAL_READINESS_STATES, build_board_html, gather_board_data

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


def _minimal_board(projects=None):
    return {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "projects_root": "/tmp/projects",
        "project_count": len(projects or []),
        "state_counts": {state: 0 for state in VISUAL_READINESS_STATES},
        "projects": projects or [],
        "notes": ["Local static preview only.", "Human slicer review required."],
    }


def _empty_render_coverage() -> dict:
    return {
        "project_dir": "/tmp/projects/demo",
        "mesh_files": [],
        "render_files": [],
        "covered": [],
        "missing_renders": [],
        "orphan_renders": [],
        "stale_renders": [],
        "total_meshes": 0,
        "total_renders": 0,
        "covered_count": 0,
        "all_meshes_have_renders": False,
        "visually_complete_for_slicer_review": False,
        "notes": [],
    }


def _full_project(**overrides) -> dict:
    project = {
        "project_name": "Demo",
        "project_dir": "demo",
        "slug": "demo",
        "brief_exists": True,
        "brief_status": "cad_generated",
        "manufacturing_status": None,
        "selected_manufacturing_option": None,
        "manifest_exists": True,
        "preview_package_exists": True,
        "cad_files": [],
        "mesh_files": [],
        "render_files": [],
        "render_coverage": _empty_render_coverage(),
        "visual_readiness_state": "needs_brief",
        "warnings": [],
    }
    project.update(overrides)
    return project


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


# ---- gather_board_data() integration ----


def test_gather_board_data_includes_slicer_intelligence_summary(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    project = board["projects"][0]
    assert "slicer_intelligence_summary" in project
    assert project["slicer_intelligence_summary"]["build_volume_fit"] == "unknown"


def test_gather_board_data_never_writes_anything(isolated_projects_dir, scad_project):
    before = sorted(str(p) for p in scad_project.rglob("*"))
    gather_board_data(isolated_projects_dir)
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


def test_gather_board_data_never_invokes_a_subprocess(isolated_projects_dir, scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("gather_board_data() must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    gather_board_data(isolated_projects_dir)


def test_gather_board_data_reflects_geometry_data(isolated_projects_dir, scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    board = gather_board_data(isolated_projects_dir)
    project = board["projects"][0]
    assert project["slicer_intelligence_summary"]["confidence"] in ("High", "Medium")


# ---- Preview Board HTML: Slicer Intelligence card ----


def test_html_includes_slicer_intelligence_section_heading(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    assert "Slicer Intelligence" in html


def test_html_slicer_intelligence_appears_after_manual_review_workspace_before_project_intake(
    isolated_projects_dir, scad_project
):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    workspace_index = html.find("<h4>Manual Review Workspace</h4>")
    intelligence_index = html.find("<h4>Slicer Intelligence</h4>")
    intake_index = html.find("<h4>Project Intake</h4>")
    assert workspace_index != -1
    assert intelligence_index != -1
    assert intake_index != -1
    assert workspace_index < intelligence_index < intake_index


def test_html_slicer_intelligence_shows_risk_build_items_priority_confidence(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    start = html.find("<h4>Slicer Intelligence</h4>")
    end = html.find("<h4>Project Intake</h4>", start)
    section = html[start:end]
    assert "Risk:" in section
    assert "Build:" in section
    assert "Review items:" in section
    assert "Priority:" in section
    assert "Confidence:" in section
    assert "Human review required" in section


def test_html_slicer_intelligence_missing_summary_key_renders_cleanly():
    project = _full_project()
    assert "slicer_intelligence_summary" not in project
    html = build_board_html(_minimal_board([project]))
    assert "No slicer intelligence analysis available for this project." in html


def test_html_never_leaves_slicer_intelligence_value_blank(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    start = html.find("<h4>Slicer Intelligence</h4>")
    end = html.find("<h4>Project Intake</h4>", start)
    section = html[start:end]
    assert 'di-value"></span>' not in section


# ---- existing detail cards preserved ----


def test_existing_detail_cards_still_present_alongside_slicer_intelligence_card(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "Project Readiness" in html
    assert "Generation Gate" in html
    assert "Post-Generation Pipeline" in html
    assert "Slicer Review Readiness" in html
    assert "Manual Review Workspace" in html
    assert "Health signals" in html
    assert "Suggested next steps" in html
    assert "Design Intent" in html
    assert "Reference Board" in html
    assert "Project Intake" in html
    assert "Draft Brief" in html
    assert "Brief Update" in html


# ---- Board never analyzes in a way that writes, launches a slicer, or generates G-code ----


def test_gather_board_data_never_launches_a_slicer(isolated_projects_dir, scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must never launch a slicer binary")

    monkeypatch.setattr(export_pipeline.subprocess, "Popen", _boom, raising=False)
    gather_board_data(isolated_projects_dir)


# ---- Escaping / no external assets ----


def test_html_slicer_intelligence_section_escapes_values():
    project = _full_project(
        slicer_intelligence_summary={
            "risk_level": "<script>alert(1)</script>",
            "build_volume_fit": "<b>fits</b>",
            "review_item_count": 2,
            "top_priority": "<img src=x onerror=alert(1)>",
            "confidence": "Unknown",
            "warning_count": 1,
        },
    )
    html = build_board_html(_minimal_board([project]))
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_html_slicer_intelligence_section_has_no_external_assets_or_ai_calls():
    forbidden = ("http://", "<script", "cdn.", "fetch(", "openai", "anthropic")
    project = _full_project(
        slicer_intelligence_summary={
            "risk_level": "Moderate",
            "build_volume_fit": "fits",
            "review_item_count": 3,
            "top_priority": "Confirm orientation.",
            "confidence": "High",
            "warning_count": 0,
        },
    )
    html = build_board_html(_minimal_board([project]))
    for term in forbidden:
        assert term not in html


# ---- regression: CLI/JSON compatibility, other pipelines unaffected ----


def test_cli_preview_board_html_includes_slicer_intelligence_section(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout
    html = (isolated_projects_dir / "preview_board" / "index.html").read_text()
    assert "Slicer Intelligence" in html


def test_preview_board_json_includes_additive_slicer_intelligence_summary(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    board = json.loads((isolated_projects_dir / "preview_board" / "index.json").read_text())
    project = board["projects"][0]
    assert project["slicer_intelligence_summary"]["build_volume_fit"] == "unknown"
    # Existing Phase 26-37 fields untouched by this phase.
    assert "manual_review_summary" in project
    assert "slicer_readiness_summary" in project
    assert "export_pipeline_summary" in project
    assert "design_orchestrator_summary" in project


def test_review_gate_cli_unaffected_by_slicer_intelligence_summary(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["review-gate", "--json", str(scad_project)])
    payload = json.loads(result.stdout)
    assert "slicer_intelligence_summary" not in payload


def test_slicer_readiness_cli_unaffected_by_slicer_intelligence(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["slicer-readiness", str(scad_project), "--json"])
    payload = json.loads(result.stdout)
    assert "slicer_intelligence_summary" not in payload


def test_review_workspace_cli_unaffected_by_slicer_intelligence(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["review-workspace", str(scad_project), "--json"])
    payload = json.loads(result.stdout)
    assert "slicer_intelligence_summary" not in payload

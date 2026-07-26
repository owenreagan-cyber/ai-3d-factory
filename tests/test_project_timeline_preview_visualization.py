"""Phase 40 tests: wiring `timeline_summary` into the Preview Board (via
`factory.preview_board.gather_board_data()`, not
`factory.project_inspection.summarize_project()` - see the Aggregation
Layer Convention in docs/architecture.md) and rendering a compact
"Project Timeline" card in the Preview Board HTML. See
docs/project-timeline.md, docs/preview-board.md, docs/roadmap.md Phase 40.
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


def test_gather_board_data_includes_timeline_summary(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    project = board["projects"][0]
    assert "timeline_summary" in project
    assert project["timeline_summary"]["event_count"] >= 1


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


def test_gather_board_data_reflects_export_events(isolated_projects_dir, scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    board = gather_board_data(isolated_projects_dir)
    project = board["projects"][0]
    assert project["timeline_summary"]["dated_event_count"] >= 1


# ---- Preview Board HTML: Project Timeline card ----


def test_html_includes_project_timeline_section_heading(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    assert "Project Timeline" in html


def test_html_project_timeline_appears_after_slicer_intelligence_before_project_intake(
    isolated_projects_dir, scad_project
):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    intelligence_index = html.find("<h4>Slicer Intelligence</h4>")
    timeline_index = html.find("<h4>Project Timeline</h4>")
    intake_index = html.find("<h4>Project Intake</h4>")
    assert intelligence_index != -1
    assert timeline_index != -1
    assert intake_index != -1
    assert intelligence_index < timeline_index < intake_index


def test_html_project_timeline_shows_event_count(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    start = html.find("<h4>Project Timeline</h4>")
    end = html.find("<h4>Project Intake</h4>", start)
    section = html[start:end]
    assert "Events:" in section


def test_html_project_timeline_shows_latest_event_when_dated(isolated_projects_dir, scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    start = html.find("<h4>Project Timeline</h4>")
    end = html.find("<h4>Project Intake</h4>", start)
    section = html[start:end]
    assert "Latest:" in section


def test_html_project_timeline_shows_tracking_note_when_unavailable_events_exist(
    isolated_projects_dir, scad_project
):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    start = html.find("<h4>Project Timeline</h4>")
    end = html.find("<h4>Project Intake</h4>", start)
    section = html[start:end]
    assert "Tracking:" in section
    assert "predate history tracking" in section


def test_html_project_timeline_missing_summary_key_renders_cleanly():
    project = _full_project()
    assert "timeline_summary" not in project
    html = build_board_html(_minimal_board([project]))
    assert "No timeline data available for this project." in html


def test_html_project_timeline_zero_events_message():
    project = _full_project(timeline_summary={
        "event_count": 0, "dated_event_count": 0, "unavailable_event_count": 0, "latest_event": None,
    })
    html = build_board_html(_minimal_board([project]))
    assert "No timeline events recorded yet for this project." in html


def test_html_never_leaves_project_timeline_value_blank(isolated_projects_dir, scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    start = html.find("<h4>Project Timeline</h4>")
    end = html.find("<h4>Project Intake</h4>", start)
    section = html[start:end]
    assert 'di-value"></span>' not in section


# ---- existing detail cards preserved ----


def test_existing_detail_cards_still_present_alongside_project_timeline_card(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "Project Readiness" in html
    assert "Generation Gate" in html
    assert "Post-Generation Pipeline" in html
    assert "Slicer Review Readiness" in html
    assert "Manual Review Workspace" in html
    assert "Slicer Intelligence" in html
    assert "Health signals" in html
    assert "Suggested next steps" in html
    assert "Design Intent" in html
    assert "Reference Board" in html
    assert "Project Intake" in html


# ---- Escaping / no external assets ----


def test_html_project_timeline_section_escapes_values():
    project = _full_project(
        timeline_summary={
            "event_count": 1,
            "dated_event_count": 1,
            "unavailable_event_count": 0,
            "latest_event": {"label": "<img src=x onerror=alert(1)>", "date": "2026-01-01", "category": "export"},
        },
    )
    html = build_board_html(_minimal_board([project]))
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_html_project_timeline_section_has_no_external_assets_or_ai_calls():
    forbidden = ("http://", "<script", "cdn.", "fetch(", "openai", "anthropic")
    project = _full_project(
        timeline_summary={
            "event_count": 3,
            "dated_event_count": 2,
            "unavailable_event_count": 1,
            "latest_event": {"label": "STL exported", "date": "2026-01-01", "category": "export"},
        },
    )
    html = build_board_html(_minimal_board([project]))
    for term in forbidden:
        assert term not in html


# ---- regression: CLI/JSON compatibility, other pipelines unaffected ----


def test_cli_preview_board_html_includes_project_timeline_section(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout
    html = (isolated_projects_dir / "preview_board" / "index.html").read_text()
    assert "Project Timeline" in html


def test_preview_board_json_includes_additive_timeline_summary(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout
    board = json.loads((isolated_projects_dir / "preview_board" / "index.json").read_text())
    project = board["projects"][0]
    assert "timeline_summary" in project
    assert "slicer_intelligence_summary" in project
    assert "manual_review_summary" in project


def test_review_gate_cli_unaffected_by_timeline_summary(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["review-gate", "--json", str(scad_project)])
    payload = json.loads(result.stdout)
    assert "timeline_summary" not in payload


def test_slicer_readiness_cli_unaffected_by_timeline(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["slicer-readiness", str(scad_project), "--json"])
    payload = json.loads(result.stdout)
    assert "timeline_summary" not in payload


def test_slicer_inspect_cli_unaffected_by_timeline(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["slicer-inspect", str(scad_project), "--json"])
    payload = json.loads(result.stdout)
    assert "timeline_summary" not in payload

"""Phase 35 tests: wiring `export_pipeline_summary` into
`factory.project_inspection.summarize_project()` and rendering a compact
"Post-Generation Pipeline" card in the Preview Board HTML. See
docs/export-pipeline.md, docs/preview-board.md, docs/roadmap.md Phase 35.

This phase never exports, validates, renders, or invokes a subprocess from
project inspection or the preview board - these tests exist to prove both
stay entirely read-only even with export-pipeline state now flowing
through them, and that every existing detail card is preserved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory import export_pipeline, project_store
from factory.cli import app
from factory.export_pipeline import write_export_receipt
from factory.openscad.generate import generate_openscad
from factory.preview_board import VISUAL_READINESS_STATES, build_board_html, gather_board_data
from factory.project_inspection import summarize_project

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


def _fake_export(project_root):
    """Write a plausible receipt for `project_root` without ever invoking a
    real subprocess - used only to give summarize_export_pipeline() and
    the board something non-trivial to display."""
    plan = export_pipeline.plan_export(project_root)
    generation_result = {
        "source_file": "cad/sign.scad",
        "output_stl": "stl/sign.stl",
        "export_tool": "OpenSCAD CLI",
        "command": [FAKE_OPENSCAD, "-o", "stl/sign.stl", "cad/sign.scad"],
        "started_at": "2026-01-01T00:00:00+00:00",
        "completed_at": "2026-01-01T00:00:01+00:00",
        "duration_seconds": 1.0,
        "exit_code": 0,
        "stdout_summary": "",
        "stderr_summary": "",
        "success": True,
        "errors": [],
        "output_size_bytes": 1234,
        "output_fingerprint": "sha256:fake",
        "source_fingerprint": plan["source_fingerprints"]["cad/sign.scad"],
    }
    record = {
        "source_file": "cad/sign.scad",
        "output_stl": "stl/sign.stl",
        "export": generation_result,
        "validation": {"status": "passed_with_warnings", "report_path": "validation/sign_validation.json"},
        "render": {"status": "passed", "render_path": "renders/sign_preview.png"},
        "pipeline_state": "completed",
    }
    write_export_receipt(project_root, [record], "completed")


# ---- summarize_project() integration ----


def test_summarize_project_export_pipeline_summary_present(scad_project):
    summary = summarize_project(scad_project)
    export_summary = summary["export_pipeline_summary"]
    assert export_summary["source_engine"] == "OpenSCAD"
    assert export_summary["decision"] in export_pipeline.DECISIONS


def test_summarize_project_export_pipeline_summary_matches_module_function(scad_project):
    from factory.export_pipeline import summarize_export_pipeline

    summary = summarize_project(scad_project)
    expected = summarize_export_pipeline(scad_project)
    assert summary["export_pipeline_summary"] == expected


def test_summarize_project_never_exports_or_writes_anything(scad_project):
    before_cad = sorted(p.name for p in (scad_project / "cad").iterdir())
    before_stl = sorted(p.name for p in (scad_project / "stl").iterdir())
    summarize_project(scad_project)
    after_cad = sorted(p.name for p in (scad_project / "cad").iterdir())
    after_stl = sorted(p.name for p in (scad_project / "stl").iterdir())
    assert before_cad == after_cad
    assert before_stl == after_stl == []
    assert not (scad_project / "generated").exists()


def test_summarize_project_export_pipeline_summary_reflects_a_written_receipt(scad_project):
    _fake_export(scad_project)
    summary = summarize_project(scad_project)
    export_summary = summary["export_pipeline_summary"]
    assert export_summary["pipeline_complete"] is True
    assert export_summary["last_completed_stage"] == "completed"


# ---- Preview Board HTML: Post-Generation Pipeline card ----


def test_html_includes_post_generation_pipeline_section_heading(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    assert "Post-Generation Pipeline" in html


def test_html_post_generation_pipeline_appears_after_generation_gate_before_project_intake(
    isolated_projects_dir, scad_project
):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    gate_index = html.find("<h4>Generation Gate</h4>")
    pipeline_index = html.find("<h4>Post-Generation Pipeline</h4>")
    intake_index = html.find("<h4>Project Intake</h4>")
    assert gate_index != -1
    assert pipeline_index != -1
    assert intake_index != -1
    assert gate_index < pipeline_index < intake_index


def test_html_post_generation_pipeline_shows_cad_source_stl_validation_preview(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    assert "CAD source:" in html
    assert "STL:" in html
    assert "Validation:" in html
    assert "Preview:" in html


def test_html_post_generation_pipeline_shows_next_step_when_incomplete(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    start = html.find("<h4>Post-Generation Pipeline</h4>")
    end = html.find("<h4>Slicer Review Readiness</h4>", start)
    section = html[start:end]
    assert "Next step" in section
    assert "Review" not in section  # no "Pending human approval" until complete


def test_html_post_generation_pipeline_shows_review_pending_when_complete(isolated_projects_dir, scad_project):
    _fake_export(scad_project)
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    start = html.find("<h4>Post-Generation Pipeline</h4>")
    end = html.find("<h4>Slicer Review Readiness</h4>", start)
    section = html[start:end]
    assert "Pending human approval" in section
    assert "Current" in section  # CAD source + STL both current


def test_html_post_generation_pipeline_missing_summary_key_renders_cleanly():
    project = _full_project()
    assert "export_pipeline_summary" not in project
    html = build_board_html(_minimal_board([project]))
    assert "No export pipeline analysis available for this project." in html


def test_html_never_leaves_post_generation_pipeline_value_blank(isolated_projects_dir, scad_project):
    for do_export in (False, True):
        if do_export:
            _fake_export(scad_project)
        board = gather_board_data(isolated_projects_dir)
        html = build_board_html(board)
        assert 'di-value"></span>' not in html


# ---- existing detail cards preserved ----


def test_existing_detail_cards_still_present_alongside_post_generation_pipeline_card(
    isolated_projects_dir, scad_project
):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "Project Readiness" in html
    assert "Generation Gate" in html
    assert "Health signals" in html
    assert "Suggested next steps" in html
    assert "Design Intent" in html
    assert "Reference Board" in html
    assert "Project Intake" in html
    assert "Draft Brief" in html
    assert "Brief Update" in html


# ---- Board never exports, validates, renders, or writes anything ----


def test_gathering_board_data_never_exports_or_writes_anything(isolated_projects_dir, scad_project):
    before_stl = sorted(p.name for p in (scad_project / "stl").iterdir())
    gather_board_data(isolated_projects_dir)
    after_stl = sorted(p.name for p in (scad_project / "stl").iterdir())
    assert before_stl == after_stl == []
    assert not (scad_project / "generated").exists()


# ---- Escaping / no external assets ----


def test_html_post_generation_pipeline_section_escapes_values():
    project = _full_project(
        export_pipeline_summary={
            "decision": "<script>alert(1)</script>",
            "source_engine": "OpenSCAD",
            "source_count": 1,
            "exporter": "OpenSCAD CLI",
            "exporter_available": True,
            "expected_stl_count": 1,
            "current_stl_count": 0,
            "stale_stl_count": 0,
            "cad_source_status": "<b>current</b>",
            "stl_status": "missing",
            "validation_status": "not_run",
            "preview_status": "not_run",
            "last_completed_stage": None,
            "pipeline_complete": False,
            "next_step": "<img src=x onerror=alert(1)>",
            "blockers": [],
            "receipt_path": None,
        },
    )
    html = build_board_html(_minimal_board([project]))
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_html_post_generation_pipeline_section_has_no_external_assets_or_ai_calls():
    forbidden = ("http://", "<script", "cdn.", "fetch(", "openai", "anthropic")
    project = _full_project(
        export_pipeline_summary={
            "decision": "needs_confirmation",
            "source_engine": "OpenSCAD",
            "source_count": 1,
            "exporter": "OpenSCAD CLI",
            "exporter_available": True,
            "expected_stl_count": 1,
            "current_stl_count": 0,
            "stale_stl_count": 0,
            "cad_source_status": "current",
            "stl_status": "missing",
            "validation_status": "not_run",
            "preview_status": "not_run",
            "last_completed_stage": None,
            "pipeline_complete": False,
            "next_step": "Confirm STL export",
            "blockers": [],
            "receipt_path": None,
        },
    )
    html = build_board_html(_minimal_board([project]))
    for term in forbidden:
        assert term not in html


# ---- regression: JSON compatibility, review-gate unaffected ----


def test_cli_preview_board_html_includes_post_generation_pipeline_section(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout
    html = (isolated_projects_dir / "preview_board" / "index.html").read_text()
    assert "Post-Generation Pipeline" in html


def test_preview_board_json_includes_additive_export_pipeline_summary(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    board = json.loads((isolated_projects_dir / "preview_board" / "index.json").read_text())
    project = board["projects"][0]
    assert project["export_pipeline_summary"]["source_engine"] == "OpenSCAD"
    # Existing Phase 26-34 fields untouched by this phase.
    assert project["generation_gate_summary"]["recommended_engine"] in export_pipeline.SUPPORTED_SOURCE_ENGINES + ("Unknown",)
    assert "generation_execution_summary" in project
    assert "design_orchestrator_summary" in project


def test_review_gate_cli_unaffected_by_export_pipeline_summary(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["review-gate", "--json", str(scad_project)])
    payload = json.loads(result.stdout)
    assert "export_pipeline_summary" not in payload
    assert "generation_gate_summary" not in payload
    assert "generation_execution_summary" not in payload

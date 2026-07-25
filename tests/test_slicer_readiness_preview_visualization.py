"""Phase 36 tests: wiring `slicer_readiness_summary` into the Preview
Board (via `factory.preview_board.gather_board_data()`, not
`factory.project_inspection.summarize_project()` - see the architectural
note below) and rendering a compact "Slicer Review Readiness" card in the
Preview Board HTML. See docs/slicer-readiness.md, docs/preview-board.md,
docs/roadmap.md Phase 36.

**Architectural note:** every other Phase 26-35 additive board field lives
on `summarize_project()` itself. This phase's field does not, because
`factory.slicer_readiness` calls `factory.review_gate.evaluate_review_gate()`
directly, and `review_gate.py` already imports `summarize_project` -
adding the summary *inside* `project_inspection.py` would create a genuine
circular import (confirmed empirically while building this phase). Instead
`factory.preview_board.gather_board_data()` calls
`factory.slicer_readiness.summarize_slicer_readiness()` per project and
merges the result in at the aggregation point - the same visible effect,
from a layer above `project_inspection.py` rather than below it. These
tests exist to prove the board stays entirely read-only even with this
extra per-project call, and that every existing detail card is preserved.
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
from factory.slicer_readiness import SLICER_REVIEW_DIRNAME, record_approval

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
        "printer_id": "test-printer",
        "display_name": "Test Printer",
        "resolved": True,
        "resolved_from": "test",
        "capabilities": None,
    }
    project_store.save_json(project_dir / "build_plan.json", build_plan)
    return project_dir


# ---- gather_board_data() integration ----


def test_gather_board_data_includes_slicer_readiness_summary(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    project = board["projects"][0]
    assert "slicer_readiness_summary" in project
    assert project["slicer_readiness_summary"]["status"] == "blocked"


def test_gather_board_data_never_writes_anything(isolated_projects_dir, scad_project):
    before = sorted(str(p) for p in scad_project.rglob("*"))
    gather_board_data(isolated_projects_dir)
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after
    assert not (scad_project / SLICER_REVIEW_DIRNAME / "slicer_review_manifest.json").exists()


def test_gather_board_data_never_invokes_a_subprocess(isolated_projects_dir, scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("gather_board_data() must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    gather_board_data(isolated_projects_dir)


def test_gather_board_data_reflects_approval(isolated_projects_dir, scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    record_approval(scad_project, note="looks good")
    board = gather_board_data(isolated_projects_dir)
    project = board["projects"][0]
    assert project["slicer_readiness_summary"]["approval_status"] == "approved"
    assert project["slicer_readiness_summary"]["status"] == "ready_for_review_package"


# ---- Preview Board HTML: Slicer Review Readiness card ----


def test_html_includes_slicer_review_readiness_section_heading(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    assert "Slicer Review Readiness" in html


def test_html_slicer_review_readiness_appears_after_post_generation_pipeline_before_project_intake(
    isolated_projects_dir, scad_project
):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    pipeline_index = html.find("<h4>Post-Generation Pipeline</h4>")
    readiness_index = html.find("<h4>Slicer Review Readiness</h4>")
    intake_index = html.find("<h4>Project Intake</h4>")
    assert pipeline_index != -1
    assert readiness_index != -1
    assert intake_index != -1
    assert pipeline_index < readiness_index < intake_index


def test_html_slicer_review_readiness_shows_status_score_approval_package(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    start = html.find("<h4>Slicer Review Readiness</h4>")
    end = html.find("<h4>Project Intake</h4>", start)
    section = html[start:end]
    assert "Status:" in section
    assert "Score:" in section
    assert "Human approval:" in section
    assert "Review package:" in section
    assert "Blockers:" in section
    assert "Warnings:" in section
    assert "Next action:" in section


def test_html_slicer_review_readiness_shows_blocked_state(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    start = html.find("<h4>Slicer Review Readiness</h4>")
    end = html.find("<h4>Project Intake</h4>", start)
    section = html[start:end]
    assert "Blocked" in section


def test_html_slicer_review_readiness_shows_ready_state_after_approval(isolated_projects_dir, scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    record_approval(scad_project)
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    start = html.find("<h4>Slicer Review Readiness</h4>")
    end = html.find("<h4>Project Intake</h4>", start)
    section = html[start:end]
    assert "Ready for review package" in section
    assert "Approved" in section


def test_html_slicer_review_readiness_missing_summary_key_renders_cleanly():
    project = _full_project()
    assert "slicer_readiness_summary" not in project
    html = build_board_html(_minimal_board([project]))
    assert "No slicer readiness analysis available for this project." in html


def test_html_never_leaves_slicer_review_readiness_value_blank(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    start = html.find("<h4>Slicer Review Readiness</h4>")
    end = html.find("<h4>Project Intake</h4>", start)
    section = html[start:end]
    assert 'di-value"></span>' not in section


# ---- existing detail cards preserved ----


def test_existing_detail_cards_still_present_alongside_slicer_readiness_card(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "Project Readiness" in html
    assert "Generation Gate" in html
    assert "Post-Generation Pipeline" in html
    assert "Health signals" in html
    assert "Suggested next steps" in html
    assert "Design Intent" in html
    assert "Reference Board" in html
    assert "Project Intake" in html
    assert "Draft Brief" in html
    assert "Brief Update" in html


# ---- Board never assesses, approves, packages, or launches a slicer ----


def test_gather_board_data_never_creates_a_package(isolated_projects_dir, scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    record_approval(scad_project)
    gather_board_data(isolated_projects_dir)
    assert not (scad_project / SLICER_REVIEW_DIRNAME / "slicer_review_manifest.json").exists()


def test_gather_board_data_never_records_approval(isolated_projects_dir, scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    gather_board_data(isolated_projects_dir)
    from factory.slicer_readiness import read_slicer_readiness_receipt

    assert read_slicer_readiness_receipt(scad_project) is None


# ---- Escaping / no external assets ----


def test_html_slicer_review_readiness_section_escapes_values():
    project = _full_project(
        slicer_readiness_summary={
            "status": "<script>alert(1)</script>",
            "score": 42,
            "ready_for_package": False,
            "human_approval_required": True,
            "approval_status": "<b>not_approved</b>",
            "stl_status": "missing",
            "validation_status": "not_run",
            "preview_status": "not_run",
            "manifest_status": "incomplete",
            "package_status": "not_created",
            "blocker_count": 1,
            "warning_count": 0,
            "next_action": "<img src=x onerror=alert(1)>",
        },
    )
    html = build_board_html(_minimal_board([project]))
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_html_slicer_review_readiness_section_has_no_external_assets_or_ai_calls():
    forbidden = ("http://", "<script", "cdn.", "fetch(", "openai", "anthropic")
    project = _full_project(
        slicer_readiness_summary={
            "status": "needs_human_approval",
            "score": 88,
            "ready_for_package": False,
            "human_approval_required": True,
            "approval_status": "not_approved",
            "stl_status": "current",
            "validation_status": "passed",
            "preview_status": "current",
            "manifest_status": "complete",
            "package_status": "not_created",
            "blocker_count": 0,
            "warning_count": 1,
            "next_action": "Review the assessment, then approve.",
        },
    )
    html = build_board_html(_minimal_board([project]))
    for term in forbidden:
        assert term not in html


# ---- regression: CLI/JSON compatibility, review-gate/export-pipeline unaffected ----


def test_cli_preview_board_html_includes_slicer_review_readiness_section(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout
    html = (isolated_projects_dir / "preview_board" / "index.html").read_text()
    assert "Slicer Review Readiness" in html


def test_preview_board_json_includes_additive_slicer_readiness_summary(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    board = json.loads((isolated_projects_dir / "preview_board" / "index.json").read_text())
    project = board["projects"][0]
    assert project["slicer_readiness_summary"]["status"] == "blocked"
    # Existing Phase 26-35 fields untouched by this phase.
    assert "export_pipeline_summary" in project
    assert "generation_gate_summary" in project
    assert "generation_execution_summary" in project
    assert "design_orchestrator_summary" in project


def test_review_gate_cli_unaffected_by_slicer_readiness_summary(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["review-gate", "--json", str(scad_project)])
    payload = json.loads(result.stdout)
    assert "slicer_readiness_summary" not in payload


def test_export_pipeline_cli_unaffected_by_slicer_readiness_summary(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["export-from-cad", str(scad_project), "--json"])
    payload = json.loads(result.stdout)
    assert "slicer_readiness_summary" not in payload

"""Phase 33 tests: wiring `design_orchestrator_summary` into
`factory.project_inspection.summarize_project()` and rendering a compact
"Project Readiness" dashboard in the Preview Board HTML. See
docs/design-orchestrator.md, docs/preview-board.md, docs/roadmap.md
Phase 33.

This phase never generates CAD or invokes any engine - these tests exist
to prove the board stays entirely read-only even with a readiness/engine
recommendation now flowing through it, and that every existing detail card
is preserved (the dashboard summarizes them, it doesn't replace them).
"""

import pytest
from typer.testing import CliRunner

from factory import project_store
from factory.cli import app
from factory.design_orchestrator import READINESS_STATES, RECOMMENDED_ENGINES, evaluate_project_readiness
from factory.preview_board import VISUAL_READINESS_STATES, build_board_html, gather_board_data

runner = CliRunner()


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture()
def project_root(isolated_projects_dir):
    return project_store.init_project("Demo Project")


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


def _set_description(project_root, description):
    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["description"] = description
    project_store.save_json(brief_path, brief)


RICH_DESCRIPTION = (
    "A mechanical organizer for my desk, made from PLA on a Bambu printer, "
    "AMS compatible, multi-part."
)


# ---- summarize_project() integration ----


def test_summarize_project_design_orchestrator_summary_present(project_root):
    from factory.project_inspection import summarize_project

    summary = summarize_project(project_root)
    orchestrator = summary["design_orchestrator_summary"]
    assert orchestrator["readiness_state"] in READINESS_STATES
    assert orchestrator["recommended_engine"] in RECOMMENDED_ENGINES


def test_summarize_project_design_orchestrator_summary_matches_module_function(project_root):
    from factory.project_inspection import summarize_project

    _set_description(project_root, RICH_DESCRIPTION)
    summary = summarize_project(project_root)
    expected = evaluate_project_readiness(
        summary["intake_summary"],
        summary["draft_brief_summary"],
        summary["brief_update_summary"],
        summary["design_intent_summary"],
        summary["design_intent_detail"],
        summary["reference_board_summary"],
    )
    assert summary["design_orchestrator_summary"] == expected


def test_summarize_project_never_writes_or_invokes_anything(project_root):
    from factory.project_inspection import summarize_project

    before = project_store.load_json(project_root / "brief.json")
    _set_description(project_root, RICH_DESCRIPTION)
    summarize_project(project_root)
    after = project_store.load_json(project_root / "brief.json")
    assert after["description"] == RICH_DESCRIPTION
    assert "design_intent" not in after


# ---- Preview Board HTML: Project Readiness dashboard ----


def test_html_includes_project_readiness_section_heading(isolated_projects_dir, project_root):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    assert "Project Readiness" in html


def test_html_project_readiness_appears_first_before_project_intake(isolated_projects_dir, project_root):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    readiness_index = html.find("<h4>Project Readiness</h4>")
    intake_index = html.find("<h4>Project Intake</h4>")
    assert readiness_index != -1
    assert intake_index != -1
    assert readiness_index < intake_index


def test_html_project_readiness_shows_score_engine_status(isolated_projects_dir, project_root):
    _set_description(project_root, RICH_DESCRIPTION)
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "%" in html
    assert "OpenSCAD" in html
    assert "Needs Information" in html or "Ready For Mechanical CAD" in html


def test_html_project_readiness_missing_summary_key_renders_cleanly():
    project = _full_project()
    assert "design_orchestrator_summary" not in project
    html = build_board_html(_minimal_board([project]))
    assert "No readiness analysis available for this project." in html


def test_html_never_leaves_project_readiness_value_blank(isolated_projects_dir, project_root):
    for description in (None, RICH_DESCRIPTION):
        if description is not None:
            _set_description(project_root, description)
        board = gather_board_data(isolated_projects_dir)
        html = build_board_html(board)
        assert 'di-value"></span>' not in html


# ---- existing detail cards preserved (dashboard summarizes, doesn't replace) ----


def test_existing_detail_cards_still_present_alongside_readiness_dashboard(isolated_projects_dir, project_root):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "<table>" in html
    assert "Health signals" in html
    assert "Suggested next steps" in html
    assert "Design Intent" in html
    assert "Reference Board" in html
    assert "Project Intake" in html
    assert "Draft Brief" in html
    assert "Brief Update" in html


# ---- Board never writes/generates/invokes anything ----


def test_gathering_board_data_never_writes_or_invokes_an_engine(isolated_projects_dir, project_root):
    _set_description(project_root, RICH_DESCRIPTION)
    before = project_store.load_json(project_root / "brief.json")
    gather_board_data(isolated_projects_dir)
    after = project_store.load_json(project_root / "brief.json")
    assert before == after


# ---- Escaping / no external assets ----


def test_html_project_readiness_section_escapes_values():
    project = _full_project(
        design_orchestrator_summary={
            "readiness_state": "<script>alert(1)</script>",
            "recommended_engine": "<b>OpenSCAD</b>",
            "engine_rationale": "x",
            "score": {"overall": 50, "categories": {}},
            "advisories": ["<img src=x onerror=alert(1)>"],
        },
    )
    html = build_board_html(_minimal_board([project]))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>OpenSCAD</b>" not in html
    assert "&lt;b&gt;OpenSCAD&lt;/b&gt;" in html


def test_html_project_readiness_section_has_no_external_assets_or_ai_calls():
    forbidden = ("http://", "<script", "cdn.", "fetch(", "openai", "anthropic")
    project = _full_project(
        design_orchestrator_summary={
            "readiness_state": "Ready For Mechanical CAD",
            "recommended_engine": "OpenSCAD",
            "engine_rationale": "x",
            "score": {"overall": 80, "categories": {}},
            "advisories": ["Human approval required"],
        },
    )
    html = build_board_html(_minimal_board([project]))
    for term in forbidden:
        assert term not in html


# ---- regression: JSON compatibility, review-gate unaffected ----


def test_cli_preview_board_html_includes_project_readiness_section(isolated_projects_dir, project_root):
    _set_description(project_root, RICH_DESCRIPTION)
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    html = (isolated_projects_dir / "preview_board" / "index.html").read_text()
    assert "Project Readiness" in html


def test_preview_board_json_includes_additive_design_orchestrator_summary(isolated_projects_dir, project_root):
    _set_description(project_root, RICH_DESCRIPTION)
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    import json

    board = json.loads((isolated_projects_dir / "preview_board" / "index.json").read_text())
    project = board["projects"][0]
    assert project["design_orchestrator_summary"]["recommended_engine"] == "OpenSCAD"
    # Existing Phase 26-32 fields untouched by this phase.
    assert project["design_intent_summary"] is None
    assert project["design_intent_detail"] is None
    assert project["reference_board_summary"]["reference_count"] == 0
    assert project["intake_summary"]["category"]["value"] == "organizer"
    assert project["draft_brief_summary"]["readiness"]["status"] == "Ready"
    assert "brief_update_summary" in project


def test_review_gate_cli_unaffected_by_design_orchestrator_summary(isolated_projects_dir, project_root):
    result = runner.invoke(app, ["review-gate", "--json", str(project_root)])

    import json

    payload = json.loads(result.stdout)
    assert "design_orchestrator_summary" not in payload
    assert "brief_update_summary" not in payload
    assert "draft_brief_summary" not in payload
    assert "intake_summary" not in payload
    assert "reference_board_summary" not in payload
    assert "design_intent_summary" not in payload

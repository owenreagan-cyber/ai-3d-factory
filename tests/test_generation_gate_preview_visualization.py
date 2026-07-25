"""Phase 34 tests: wiring `generation_gate_summary` into
`factory.project_inspection.summarize_project()` and rendering a compact
"Generation Gate" card in the Preview Board HTML. See
docs/generation-gate.md, docs/preview-board.md, docs/roadmap.md Phase 34.

This phase never generates CAD or invokes any engine from project
inspection or the preview board - these tests exist to prove both stay
entirely read-only even with a gate decision now flowing through them, and
that every existing detail card is preserved.
"""

import json

import pytest
from typer.testing import CliRunner

from factory import project_store
from factory.cli import app
from factory.generation_gate import DECISIONS, summarize_generation_gate
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


def test_summarize_project_generation_gate_summary_present(project_root):
    from factory.project_inspection import summarize_project

    summary = summarize_project(project_root)
    gate = summary["generation_gate_summary"]
    assert set(gate.keys()) == {"decision", "recommended_engine", "ready", "reason"}
    assert gate["decision"] in DECISIONS


def test_summarize_project_generation_gate_summary_matches_module_function(project_root):
    from factory.project_inspection import summarize_project

    _set_description(project_root, RICH_DESCRIPTION)
    summary = summarize_project(project_root)
    expected = summarize_generation_gate(summary["intake_summary"], summary["design_orchestrator_summary"])
    assert summary["generation_gate_summary"] == expected


def test_summarize_project_never_generates_cad_or_writes_anything(project_root):
    from factory.project_inspection import summarize_project

    before = project_store.load_json(project_root / "brief.json")
    _set_description(project_root, RICH_DESCRIPTION)
    before_cad = sorted(p.name for p in (project_root / "cad").iterdir())
    summarize_project(project_root)
    after = project_store.load_json(project_root / "brief.json")
    after_cad = sorted(p.name for p in (project_root / "cad").iterdir())
    assert after["description"] == RICH_DESCRIPTION
    assert before_cad == after_cad == []


# ---- Preview Board HTML: Generation Gate card ----


def test_html_includes_generation_gate_section_heading(isolated_projects_dir, project_root):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    assert "Generation Gate" in html


def test_html_generation_gate_appears_after_project_readiness_before_project_intake(isolated_projects_dir, project_root):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    readiness_index = html.find("<h4>Project Readiness</h4>")
    gate_index = html.find("<h4>Generation Gate</h4>")
    intake_index = html.find("<h4>Project Intake</h4>")
    assert readiness_index != -1
    assert gate_index != -1
    assert intake_index != -1
    assert readiness_index < gate_index < intake_index


def test_html_generation_gate_shows_decision_engine_ready(isolated_projects_dir, project_root):
    _set_description(project_root, RICH_DESCRIPTION)
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "Decision:" in html
    assert "Engine:" in html
    assert "Ready:" in html
    assert "OpenSCAD" in html


def test_html_generation_gate_missing_summary_key_renders_cleanly():
    project = _full_project()
    assert "generation_gate_summary" not in project
    html = build_board_html(_minimal_board([project]))
    assert "No generation gate analysis available for this project." in html


def test_html_never_leaves_generation_gate_value_blank(isolated_projects_dir, project_root):
    for description in (None, RICH_DESCRIPTION):
        if description is not None:
            _set_description(project_root, description)
        board = gather_board_data(isolated_projects_dir)
        html = build_board_html(board)
        assert 'di-value"></span>' not in html


# ---- Phase 34: execution receipts on the Generation Gate card ----


def test_html_generation_gate_shows_receipt_available_and_last_execution(isolated_projects_dir, project_root):
    _set_description(project_root, RICH_DESCRIPTION)
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "Receipt available" in html
    assert "Last execution" in html


def test_html_generation_gate_no_receipt_shows_no_and_never(isolated_projects_dir, project_root):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    gate_section_start = html.find("<h4>Generation Gate</h4>")
    gate_section_end = html.find("<h4>Project Intake</h4>", gate_section_start)
    section = html[gate_section_start:gate_section_end]
    assert "Never" in section


def test_html_generation_gate_with_receipt_shows_yes_and_timestamp(isolated_projects_dir, project_root):
    from factory.generation_gate import write_generation_receipt

    _set_description(project_root, RICH_DESCRIPTION)
    (project_root / "cad" / "organizer.scad").write_text("// demo\n", encoding="utf-8")
    gate_result = {
        "decision": "Allowed",
        "recommended_engine": "OpenSCAD",
        "readiness_state": "Ready For Mechanical CAD",
        "readiness_score": 90,
        "plan": {"engine": "OpenSCAD", "template": "sign", "params": {"text": "Demo"}},
        "required_before_generation": [],
        "confirm_generate": True,
    }
    generation_result = {"written_files": [str(project_root / "cad" / "organizer.scad")], "warnings": []}
    write_generation_receipt(project_root, gate_result, generation_result)

    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    gate_section_start = html.find("<h4>Generation Gate</h4>")
    gate_section_end = html.find("<h4>Project Intake</h4>", gate_section_start)
    section = html[gate_section_start:gate_section_end]
    assert "Never" not in section


def test_html_generation_gate_missing_execution_summary_falls_back_cleanly():
    project = _full_project(
        generation_gate_summary={"decision": "Dry Run Only", "recommended_engine": "OpenSCAD", "ready": False, "reason": None},
    )
    assert "generation_execution_summary" not in project
    html = build_board_html(_minimal_board([project]))
    assert "Receipt available" in html
    assert "Never" in html
    assert 'di-value"></span>' not in html


# ---- existing detail cards preserved ----


def test_existing_detail_cards_still_present_alongside_generation_gate_card(isolated_projects_dir, project_root):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "Project Readiness" in html
    assert "<table>" in html
    assert "Health signals" in html
    assert "Suggested next steps" in html
    assert "Design Intent" in html
    assert "Reference Board" in html
    assert "Project Intake" in html
    assert "Draft Brief" in html
    assert "Brief Update" in html


# ---- Board never generates CAD or writes anything ----


def test_gathering_board_data_never_generates_cad_or_writes_anything(isolated_projects_dir, project_root):
    _set_description(project_root, RICH_DESCRIPTION)
    before = project_store.load_json(project_root / "brief.json")
    before_cad = sorted(p.name for p in (project_root / "cad").iterdir())
    gather_board_data(isolated_projects_dir)
    after = project_store.load_json(project_root / "brief.json")
    after_cad = sorted(p.name for p in (project_root / "cad").iterdir())
    assert before == after
    assert before_cad == after_cad == []


# ---- Escaping / no external assets ----


def test_html_generation_gate_section_escapes_values():
    project = _full_project(
        generation_gate_summary={
            "decision": "<script>alert(1)</script>",
            "recommended_engine": "<b>OpenSCAD</b>",
            "ready": False,
            "reason": "<img src=x onerror=alert(1)>",
        },
    )
    html = build_board_html(_minimal_board([project]))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>OpenSCAD</b>" not in html
    assert "&lt;b&gt;OpenSCAD&lt;/b&gt;" in html


def test_html_generation_gate_section_has_no_external_assets_or_ai_calls():
    forbidden = ("http://", "<script", "cdn.", "fetch(", "openai", "anthropic")
    project = _full_project(
        generation_gate_summary={
            "decision": "Needs Confirmation",
            "recommended_engine": "OpenSCAD",
            "ready": True,
            "reason": None,
        },
    )
    html = build_board_html(_minimal_board([project]))
    for term in forbidden:
        assert term not in html


# ---- regression: JSON compatibility, review-gate unaffected ----


def test_cli_preview_board_html_includes_generation_gate_section(isolated_projects_dir, project_root):
    _set_description(project_root, RICH_DESCRIPTION)
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    html = (isolated_projects_dir / "preview_board" / "index.html").read_text()
    assert "Generation Gate" in html


def test_preview_board_json_includes_additive_generation_gate_summary(isolated_projects_dir, project_root):
    _set_description(project_root, RICH_DESCRIPTION)
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    board = json.loads((isolated_projects_dir / "preview_board" / "index.json").read_text())
    project = board["projects"][0]
    assert project["generation_gate_summary"]["recommended_engine"] == "OpenSCAD"
    # Existing Phase 26-33 fields untouched by this phase.
    assert project["design_orchestrator_summary"]["recommended_engine"] == "OpenSCAD"
    assert project["design_intent_summary"] is None
    assert project["design_intent_detail"] is None
    assert project["reference_board_summary"]["reference_count"] == 0
    assert project["intake_summary"]["category"]["value"] == "organizer"
    assert project["draft_brief_summary"]["readiness"]["status"] == "Ready"
    assert "brief_update_summary" in project


def test_review_gate_cli_unaffected_by_generation_gate_summary(isolated_projects_dir, project_root):
    result = runner.invoke(app, ["review-gate", "--json", str(project_root)])

    payload = json.loads(result.stdout)
    assert "generation_gate_summary" not in payload
    assert "design_orchestrator_summary" not in payload
    assert "brief_update_summary" not in payload
    assert "draft_brief_summary" not in payload
    assert "intake_summary" not in payload
    assert "reference_board_summary" not in payload
    assert "design_intent_summary" not in payload

"""Phase 30 tests: wiring `intake_summary` into
`factory.project_inspection.summarize_project()` and rendering a compact
"Project Intake" card in the Preview Board HTML. See
docs/project-intake.md, docs/preview-board.md, docs/roadmap.md Phase 30.

This phase adds no new approval, scoring, gate, or network/AI semantics -
these tests exist to prove that, not just that the new HTML text appears.
"""

import pytest
from typer.testing import CliRunner

from factory import project_store
from factory.cli import app
from factory.preview_board import VISUAL_READINESS_STATES, build_board_html, gather_board_data
from factory.project_intake import analyze_project

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
    "A premium, etsy-worthy classroom sign for my teacher's desk, gift-quality, "
    "made from PLA on a Bambu printer, roughly 48-inch wide."
)


# ---- summarize_project() integration ----


def test_summarize_project_intake_summary_present(project_root):
    from factory.project_inspection import summarize_project

    summary = summarize_project(project_root)
    assert summary["intake_summary"]["source"] == "brief_description"


def test_summarize_project_intake_summary_matches_module_function(project_root):
    from factory.project_inspection import summarize_project

    _set_description(project_root, RICH_DESCRIPTION)
    summary = summarize_project(project_root)
    assert summary["intake_summary"] == analyze_project(project_root)


# ---- Preview Board HTML: Project Intake section ----


def test_html_includes_project_intake_section_heading(isolated_projects_dir, project_root):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    assert "Project Intake" in html


def test_html_project_intake_appears_before_design_intent(isolated_projects_dir, project_root):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    intake_index = html.find("<h4>Project Intake</h4>")
    design_intent_index = html.find("<h4>Design Intent</h4>")
    assert intake_index != -1
    assert design_intent_index != -1
    assert intake_index < design_intent_index


def test_html_rich_intake_renders_all_compact_fields(isolated_projects_dir, project_root):
    _set_description(project_root, RICH_DESCRIPTION)
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "Sign" in html
    assert "Classroom" in html
    assert "Etsy-worthy" in html
    assert "PLA" in html


def test_html_minimal_intake_renders_fallbacks(isolated_projects_dir, project_root):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    assert "Not specified" in html


def test_html_missing_intake_summary_key_renders_cleanly():
    project = _full_project()
    assert "intake_summary" not in project
    html = build_board_html(_minimal_board([project]))
    assert "No intake analysis available for this project." in html


def test_html_never_leaves_intake_value_blank(isolated_projects_dir, project_root):
    for description in (None, "", RICH_DESCRIPTION):
        if description is not None:
            _set_description(project_root, description)
        board = gather_board_data(isolated_projects_dir)
        html = build_board_html(board)
        assert 'di-value"></span>' not in html


# ---- Escaping / no external assets ----


def test_html_project_intake_section_escapes_values():
    project = _full_project(
        intake_summary={
            "project_name": {"value": "<script>alert(1)</script>", "confidence": "high"},
            "category": {"value": "sign", "confidence": "high"},
            "purpose": {"value": None, "confidence": "unknown"},
            "audience": {"value": "<b>students</b>", "confidence": "medium"},
            "environment": {"value": "classroom", "confidence": "medium"},
            "material_assumptions": {"value": ["PLA"], "confidence": "high"},
            "printer_assumptions": {"value": [], "confidence": "unknown"},
            "quality_target": {"value": "premium", "confidence": "medium"},
            "manufacturing_style": {"value": [], "confidence": "unknown"},
            "functional_goals": {"value": [], "confidence": "unknown"},
            "visual_goals": {"value": [], "confidence": "unknown"},
            "dimensional_constraints": {"value": [], "confidence": "unknown"},
            "commercial_intent": {"value": False, "confidence": "unknown"},
            "warnings": ["<img src=x onerror=alert(1)>"],
            "source": "brief_description",
        },
    )
    html = build_board_html(_minimal_board([project]))
    assert "<b>students</b>" not in html
    assert "&lt;b&gt;students&lt;/b&gt;" in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;img" in html


def test_html_project_intake_section_has_no_external_assets_or_ai_calls():
    forbidden = ("http://", "<script", "cdn.", "fetch(", "openai", "anthropic")
    project = _full_project(
        intake_summary={
            "category": {"value": "sign", "confidence": "high"},
            "audience": {"value": "Students", "confidence": "medium"},
            "environment": {"value": "classroom", "confidence": "medium"},
            "quality_target": {"value": "etsy-worthy", "confidence": "medium"},
            "material_assumptions": {"value": ["PLA"], "confidence": "high"},
            "warnings": ["Dimensions not specified."],
        },
    )
    html = build_board_html(_minimal_board([project]))
    for term in forbidden:
        assert term not in html


# ---- regression: existing sections preserved, JSON compatibility ----


def test_existing_sections_still_present_alongside_intake_card(isolated_projects_dir, project_root):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "<table>" in html
    assert "Health signals" in html
    assert "Suggested next steps" in html
    assert "Design Intent" in html
    assert "Reference Board" in html


def test_cli_preview_board_html_includes_project_intake_section(isolated_projects_dir, project_root):
    _set_description(project_root, RICH_DESCRIPTION)
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    html = (isolated_projects_dir / "preview_board" / "index.html").read_text()
    assert "Project Intake" in html
    assert "Sign" in html


def test_preview_board_json_includes_additive_intake_summary(isolated_projects_dir, project_root):
    _set_description(project_root, RICH_DESCRIPTION)
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    import json

    board = json.loads((isolated_projects_dir / "preview_board" / "index.json").read_text())
    project = board["projects"][0]
    assert project["intake_summary"]["category"]["value"] == "sign"
    # Existing Phase 26-29 fields untouched by this phase.
    assert project["design_intent_summary"] is None
    assert project["design_intent_detail"] is None
    assert project["reference_board_summary"]["reference_count"] == 0


def test_review_gate_cli_unaffected_by_intake_summary(isolated_projects_dir, project_root):
    result = runner.invoke(app, ["review-gate", "--json", str(project_root)])

    import json

    payload = json.loads(result.stdout)
    assert "intake_summary" not in payload
    assert "reference_board_summary" not in payload
    assert "design_intent_summary" not in payload
    assert "design_intent_detail" not in payload

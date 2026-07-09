"""Phase 32 tests: wiring `brief_update_summary` into
`factory.project_inspection.summarize_project()` and rendering a compact
"Brief Update" card in the Preview Board HTML. See docs/brief-generator.md,
docs/preview-board.md, docs/roadmap.md Phase 32.

This phase adds no new write path the board itself can trigger - these
tests exist to prove the board stays entirely read-only even with merge
data now flowing through it.
"""

import pytest
from typer.testing import CliRunner

from factory import project_store
from factory.brief_generator import summarize_brief_update
from factory.cli import app
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
    "A premium, etsy-worthy classroom sign for my teacher's desk, gift-quality, "
    "made from PLA on a Bambu printer, AMS compatible, multi-part."
)


# ---- summarize_project() integration ----


def test_summarize_project_brief_update_summary_present(project_root):
    from factory.project_inspection import summarize_project

    summary = summarize_project(project_root)
    assert set(summary["brief_update_summary"].keys()) == {
        "merge_available", "fields_to_add_count", "fields_preserved_count", "human_review_required",
    }


def test_summarize_project_brief_update_summary_matches_module_function(project_root):
    from factory.project_inspection import summarize_project

    _set_description(project_root, RICH_DESCRIPTION)
    summary = summarize_project(project_root)
    existing = project_store.load_json(project_root / "brief.json")
    assert summary["brief_update_summary"] == summarize_brief_update(existing, summary["intake_summary"])


def test_summarize_project_never_writes_a_merged_brief(project_root):
    from factory.project_inspection import summarize_project

    before = project_store.load_json(project_root / "brief.json")
    _set_description(project_root, RICH_DESCRIPTION)
    summarize_project(project_root)
    after = project_store.load_json(project_root / "brief.json")
    assert after["description"] == RICH_DESCRIPTION
    assert "design_intent" not in after  # never auto-merged by inspection alone


# ---- Preview Board HTML: Brief Update section ----


def test_html_includes_brief_update_section_heading(isolated_projects_dir, project_root):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    assert "Brief Update" in html


def test_html_brief_update_appears_after_draft_brief_before_design_intent(isolated_projects_dir, project_root):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    draft_index = html.find("<h4>Draft Brief</h4>")
    update_index = html.find("<h4>Brief Update</h4>")
    design_intent_index = html.find("<h4>Design Intent</h4>")
    assert draft_index != -1
    assert update_index != -1
    assert design_intent_index != -1
    assert draft_index < update_index < design_intent_index


def test_html_brief_update_compact_when_nothing_to_merge(isolated_projects_dir, project_root):
    # A freshly-init'd project's default_brief() has real project_name/
    # intended_printer already, and no design_intent/manufacturing_notes
    # signal exists in intake either -> nothing meaningful to merge.
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    assert "Up to date - nothing to merge." in html


def test_html_brief_update_shows_merge_available_when_meaningful(isolated_projects_dir, project_root):
    _set_description(project_root, RICH_DESCRIPTION)
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    assert "Merge available" in html
    assert "Human review required" in html


def test_html_brief_update_missing_summary_key_renders_cleanly():
    project = _full_project()
    assert "brief_update_summary" not in project
    html = build_board_html(_minimal_board([project]))
    assert "No brief update analysis available for this project." in html


def test_html_never_leaves_brief_update_value_blank(isolated_projects_dir, project_root):
    for description in (None, RICH_DESCRIPTION):
        if description is not None:
            _set_description(project_root, description)
        board = gather_board_data(isolated_projects_dir)
        html = build_board_html(board)
        assert 'di-value"></span>' not in html


# ---- Board never writes/merges anything ----


def test_gathering_board_data_never_merges_or_writes_brief(isolated_projects_dir, project_root):
    _set_description(project_root, RICH_DESCRIPTION)
    before = project_store.load_json(project_root / "brief.json")
    gather_board_data(isolated_projects_dir)
    after = project_store.load_json(project_root / "brief.json")
    assert before == after
    assert "design_intent" not in after


# ---- Escaping / no external assets ----


def test_html_brief_update_section_escapes_values():
    project = _full_project(
        brief_update_summary={
            "merge_available": True,
            "fields_to_add_count": "<script>alert(1)</script>",
            "fields_preserved_count": 2,
            "human_review_required": True,
        },
    )
    html = build_board_html(_minimal_board([project]))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_brief_update_section_has_no_external_assets_or_ai_calls():
    forbidden = ("http://", "<script", "cdn.", "fetch(", "openai", "anthropic")
    project = _full_project(
        brief_update_summary={
            "merge_available": True,
            "fields_to_add_count": 3,
            "fields_preserved_count": 2,
            "human_review_required": True,
        },
    )
    html = build_board_html(_minimal_board([project]))
    for term in forbidden:
        assert term not in html


# ---- regression: existing sections preserved, JSON compatibility ----


def test_existing_sections_still_present_alongside_brief_update_card(isolated_projects_dir, project_root):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "<table>" in html
    assert "Health signals" in html
    assert "Suggested next steps" in html
    assert "Design Intent" in html
    assert "Reference Board" in html
    assert "Project Intake" in html
    assert "Draft Brief" in html


def test_cli_preview_board_html_includes_brief_update_section(isolated_projects_dir, project_root):
    _set_description(project_root, RICH_DESCRIPTION)
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    html = (isolated_projects_dir / "preview_board" / "index.html").read_text()
    assert "Brief Update" in html


def test_preview_board_json_includes_additive_brief_update_summary(isolated_projects_dir, project_root):
    _set_description(project_root, RICH_DESCRIPTION)
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    import json

    board = json.loads((isolated_projects_dir / "preview_board" / "index.json").read_text())
    project = board["projects"][0]
    assert project["brief_update_summary"]["merge_available"] is True
    # Existing Phase 26-31 fields untouched by this phase.
    assert project["design_intent_summary"] is None
    assert project["design_intent_detail"] is None
    assert project["reference_board_summary"]["reference_count"] == 0
    assert project["intake_summary"]["category"]["value"] == "sign"
    assert project["draft_brief_summary"]["readiness"]["status"] == "Ready"


def test_review_gate_cli_unaffected_by_brief_update_summary(isolated_projects_dir, project_root):
    result = runner.invoke(app, ["review-gate", "--json", str(project_root)])

    import json

    payload = json.loads(result.stdout)
    assert "brief_update_summary" not in payload
    assert "draft_brief_summary" not in payload
    assert "intake_summary" not in payload
    assert "reference_board_summary" not in payload
    assert "design_intent_summary" not in payload

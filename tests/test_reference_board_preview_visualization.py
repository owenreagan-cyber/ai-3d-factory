"""Phase 28 tests: wiring `reference_board_summary` into
`factory.project_inspection.summarize_project()` and rendering a compact
"Reference Board" section in the Preview Board HTML. See
docs/reference-board.md, docs/preview-board.md, docs/roadmap.md Phase 28.

This phase adds no new approval, scoring, gate, or network/download
semantics - these tests exist to prove that, not just that the new HTML
text appears.
"""

import pytest
from typer.testing import CliRunner

from factory import project_store
from factory.cli import app
from factory.preview_board import VISUAL_READINESS_STATES, build_board_html, gather_board_data
from factory.reference_board import summarize_reference_board

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


def _init_project_with_reference_board(isolated_projects_dir, references):
    runner.invoke(app, ["init-project", "Demo Project"])
    project_dir = isolated_projects_dir / "demo-project"
    if references is not None:
        project_store.save_json(project_dir / "reference_board.json", {"references": references})
    return project_dir


FULL_REFERENCE = {
    "title": "Classroom storage inspiration",
    "source_url": "https://example.com/classroom-storage-reference",
    "source_type": "inspiration",
    "license": "cc_by",
    "usage_intent": "design_reference_only",
    "attached_to": "design_intent.reference_inputs",
    "notes": "Used only as a style and organization reference.",
}

PARTIAL_REFERENCE = {
    "title": "Untitled sketch",
    # source_url, license, usage_intent, attached_to all absent.
}


# ---- summarize_project() integration ----


def test_summarize_project_reference_board_summary_missing_file(project_root):
    from factory.project_inspection import summarize_project

    summary = summarize_project(project_root)
    assert summary["reference_board_summary"]["reference_count"] == 0


def test_summarize_project_reference_board_summary_matches_module_function(project_root):
    from factory.project_inspection import summarize_project

    project_store.save_json(project_root / "reference_board.json", {"references": [FULL_REFERENCE]})
    summary = summarize_project(project_root)
    assert summary["reference_board_summary"] == summarize_reference_board(project_root)


# ---- Preview Board HTML: Reference Board section ----


def test_html_includes_reference_board_section_heading(isolated_projects_dir):
    _init_project_with_reference_board(isolated_projects_dir, [FULL_REFERENCE])
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    assert "Reference Board" in html


def test_html_fully_populated_reference_board_renders_fields(isolated_projects_dir):
    _init_project_with_reference_board(isolated_projects_dir, [FULL_REFERENCE])
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert ">1<" in html  # reference count
    assert "CC BY" in html
    assert "design reference only" in html
    assert "None" in html  # no warnings for a fully-clean reference


def test_html_partial_reference_board_renders_fallback_and_warnings(isolated_projects_dir):
    _init_project_with_reference_board(isolated_projects_dir, [PARTIAL_REFERENCE])
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "unknown" in html  # license fell back to unknown
    assert "commercial use unclear" in html
    assert "no source_url recorded" in html


def test_html_empty_reference_board_renders_cleanly(isolated_projects_dir):
    _init_project_with_reference_board(isolated_projects_dir, [])
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    assert "No references recorded for this project." in html
    assert "Traceback" not in html


def test_html_missing_reference_board_file_renders_cleanly(isolated_projects_dir):
    _init_project_with_reference_board(isolated_projects_dir, None)
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    assert "No references recorded for this project." in html
    assert "Traceback" not in html


def test_html_reference_board_appears_near_design_intent(isolated_projects_dir):
    _init_project_with_reference_board(isolated_projects_dir, [FULL_REFERENCE])
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    design_intent_index = html.find("<h4>Design Intent</h4>")
    reference_board_index = html.find("<h4>Reference Board</h4>")
    manufacturing_index = html.find("<h4>Manufacturing Overview</h4>")
    assert design_intent_index != -1
    assert reference_board_index != -1
    assert design_intent_index < reference_board_index < manufacturing_index


def test_html_reference_board_never_leaves_value_blank(isolated_projects_dir):
    for references in (None, [], [PARTIAL_REFERENCE], [FULL_REFERENCE]):
        _init_project_with_reference_board(isolated_projects_dir, references)
        board = gather_board_data(isolated_projects_dir)
        html = build_board_html(board)
        assert 'di-value"></span>' not in html


def test_html_project_card_gracefully_handles_missing_reference_board_summary_key():
    project = _full_project()
    assert "reference_board_summary" not in project
    html = build_board_html(_minimal_board([project]))
    assert "No references recorded for this project." in html


# ---- Escaping / no external assets / no network in HTML output ----


def test_html_reference_board_section_escapes_values():
    project = _full_project(
        reference_board_summary={
            "reference_count": 1,
            "by_license": {"unknown": 1},
            "by_source_type": {"unknown": 1},
            "by_usage_intent": {},
            "attached_to_design_intent_count": 0,
            "warnings": ["<script>alert(1)</script> some warning"],
        },
    )
    html = build_board_html(_minimal_board([project]))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_reference_board_section_has_no_external_assets_or_network_calls():
    forbidden = ("http://", "<script", "cdn.", "fetch(", "XMLHttpRequest", "google-analytics")
    project = _full_project(
        reference_board_summary={
            "reference_count": 1,
            "by_license": {"cc_by": 1},
            "by_source_type": {"inspiration": 1},
            "by_usage_intent": {"design_reference_only": 1},
            "attached_to_design_intent_count": 1,
            "warnings": [],
        },
    )
    html = build_board_html(_minimal_board([project]))
    for term in forbidden:
        assert term not in html
    # A source_url may appear as inert https:// metadata text elsewhere on the
    # board (design intent, suggested actions), but this reference-board test
    # fixture doesn't include one, so https:// shouldn't appear from this card.


# ---- Regression: existing sections preserved, JSON compatibility ----


def test_existing_sections_still_present_alongside_reference_board_card(isolated_projects_dir):
    _init_project_with_reference_board(isolated_projects_dir, [FULL_REFERENCE])
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "<table>" in html
    assert "Health signals" in html
    assert "Suggested next steps" in html
    assert "Design Intent" in html


def test_cli_preview_board_html_includes_reference_board_section(isolated_projects_dir):
    _init_project_with_reference_board(isolated_projects_dir, [FULL_REFERENCE])
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    html = (isolated_projects_dir / "preview_board" / "index.html").read_text()
    assert "Reference Board" in html
    assert "Classroom storage inspiration" not in html  # titles aren't rendered individually (compact only)


def test_preview_board_json_includes_additive_reference_board_summary(isolated_projects_dir):
    _init_project_with_reference_board(isolated_projects_dir, [FULL_REFERENCE])
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    import json

    board = json.loads((isolated_projects_dir / "preview_board" / "index.json").read_text())
    project = board["projects"][0]
    assert project["reference_board_summary"]["reference_count"] == 1
    # Existing fields untouched by this phase.
    assert project["design_intent_summary"] is None
    assert project["design_intent_detail"] is None
    assert set(project.keys()) >= {
        "design_intent_summary", "design_intent_detail", "reference_board_summary",
    }


def test_review_gate_cli_unaffected_by_reference_board(isolated_projects_dir):
    _init_project_with_reference_board(isolated_projects_dir, [FULL_REFERENCE])
    project_dir = isolated_projects_dir / "demo-project"
    result = runner.invoke(app, ["review-gate", "--json", str(project_dir)])

    import json

    payload = json.loads(result.stdout)
    assert "reference_board_summary" not in payload
    assert "design_intent_summary" not in payload
    assert "design_intent_detail" not in payload

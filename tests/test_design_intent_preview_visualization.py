"""Phase 27 tests: visualizing existing `design_intent` data (Phase 24-26) as a
first-class "Design Intent" card in the Preview Board HTML - visualization
only, on top of Phase 26's `design_intent_summary`/`factory report` visibility
work. See docs/design-intent-brief.md, docs/preview-board.md, docs/roadmap.md
Phase 27.

This phase adds no new approval, scoring, gate, or schema-required semantics -
these tests exist to prove that, not just that the new HTML text appears.
"""

import inspect

import pytest
from typer.testing import CliRunner

from factory import design_intent_check, project_store
from factory.cli import app
from factory.design_intent_check import describe_design_intent_for_board
from factory.preview_board import VISUAL_READINESS_STATES, build_board_html, gather_board_data
from factory.project_inspection import summarize_project

runner = CliRunner()

PIGGY_BANK_BRIEF = (
    project_store.REPO_ROOT
    / "examples"
    / "future-organic-models"
    / "piggy-bank-design-study"
    / "concept_brief.json"
)

CHIP_CLIP_BRIEF = (
    project_store.REPO_ROOT
    / "examples"
    / "future-functional-designs"
    / "chip-bag-clip-study"
    / "concept_brief.json"
)


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
    """A hand-built project dict carrying every field the existing table-row
    renderer accesses directly (not just `.get()`-defensively), so tests that
    only care about the Phase 27 card sections don't have to restate all of
    them each time. Mirrors `tests/test_preview_board.py`'s `_minimal_board()`
    project fixtures."""
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


# ---- describe_design_intent_for_board() ----


def test_describe_design_intent_for_board_none_when_field_absent(tmp_path):
    path = tmp_path / "brief.json"
    path.write_text('{"project_name": "x"}', encoding="utf-8")
    assert describe_design_intent_for_board(path) is None


def test_describe_design_intent_for_board_none_when_not_a_dict(tmp_path):
    path = tmp_path / "brief.json"
    path.write_text('{"design_intent": "not a dict"}', encoding="utf-8")
    assert describe_design_intent_for_board(path) is None


def test_describe_design_intent_for_board_none_when_file_missing(tmp_path):
    assert describe_design_intent_for_board(tmp_path / "does-not-exist.json") is None


def test_describe_design_intent_for_board_none_when_invalid_json(tmp_path):
    path = tmp_path / "brief.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert describe_design_intent_for_board(path) is None


def test_describe_design_intent_for_board_full_shape_for_piggy_bank():
    detail = describe_design_intent_for_board(PIGGY_BANK_BRIEF)
    assert detail is not None
    assert set(detail.keys()) == {
        "quality_standard", "use_case", "style_direction", "manufacturability_result",
        "reference_input_count", "design_notes", "warnings",
    }
    assert detail["quality_standard"] == "Etsy-worthy"
    assert detail["use_case"] == "everyday coin storage that's also a display-worthy object"
    assert detail["style_direction"] == ["cute", "designer-toy", "ceramic-smooth"]
    assert detail["manufacturability_result"] == "fits_some_printers"
    assert detail["reference_input_count"] == 1
    assert detail["design_notes"] == (
        "polished and gift-worthy, not blobby - matches docs/design-quality-standard.md's piggy "
        "bank example in full"
    )
    assert isinstance(detail["warnings"], list)


def test_describe_design_intent_for_board_zero_reference_inputs_for_chip_clip():
    detail = describe_design_intent_for_board(CHIP_CLIP_BRIEF)
    assert detail is not None
    assert detail["reference_input_count"] == 0
    assert detail["design_notes"] is not None


def test_describe_design_intent_for_board_is_deterministic():
    assert describe_design_intent_for_board(PIGGY_BANK_BRIEF) == describe_design_intent_for_board(PIGGY_BANK_BRIEF)


@pytest.mark.parametrize(
    "design_intent,expected_count,expected_notes",
    [
        ({}, 0, None),
        ({"reference_inputs": "not a list"}, 0, None),
        ({"reference_inputs": [1, 2, 3]}, 3, None),
        ({"iteration_plan": "not a dict"}, 0, None),
        ({"iteration_plan": {"acceptance_notes": 123}}, 0, None),
        ({"iteration_plan": {"acceptance_notes": "   "}}, 0, None),
        ({"iteration_plan": {"acceptance_notes": "done means X"}}, 0, "done means X"),
    ],
)
def test_describe_design_intent_for_board_malformed_fields_handled_safely(
    tmp_path, design_intent, expected_count, expected_notes
):
    path = tmp_path / "brief.json"
    path.write_text(__import__("json").dumps({"design_intent": design_intent}), encoding="utf-8")
    detail = describe_design_intent_for_board(path)
    assert detail is not None
    assert detail["reference_input_count"] == expected_count
    assert detail["design_notes"] == expected_notes


def test_describe_design_intent_for_board_writes_no_files(tmp_path):
    before = sorted(p.name for p in tmp_path.iterdir())
    describe_design_intent_for_board(PIGGY_BANK_BRIEF)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after


def test_describe_design_intent_for_board_does_not_duplicate_manufacturability_parsing():
    source = inspect.getsource(design_intent_check.describe_design_intent_for_board)
    assert "check_design_intent_manufacturability(" in source
    assert "permutations" not in source
    assert "load_printers" not in source


def test_describe_design_intent_for_board_does_not_modify_committed_piggy_bank_concept_brief():
    import hashlib

    before = hashlib.sha256(PIGGY_BANK_BRIEF.read_bytes()).hexdigest()
    describe_design_intent_for_board(PIGGY_BANK_BRIEF)
    after = hashlib.sha256(PIGGY_BANK_BRIEF.read_bytes()).hexdigest()
    assert before == after


def test_design_intent_check_module_still_has_no_forbidden_calls_after_phase27():
    forbidden = (
        "import subprocess", "subprocess.run(", "subprocess.call(", "subprocess.Popen(",
        "os.system(", "os.popen(", "socket.", "import urllib", "import requests",
        "http.client", "write_text(", "write_bytes(", "save_json(",
    )
    source = inspect.getsource(design_intent_check)
    for forbidden_call in forbidden:
        assert forbidden_call not in source


# ---- Preview Board HTML: Design Intent section ----


def _init_project_with_design_intent(isolated_projects_dir, design_intent):
    runner.invoke(app, ["init-project", "Demo Project"])
    project_dir = isolated_projects_dir / "demo-project"
    brief_path = project_dir / "brief.json"
    brief = project_store.load_json(brief_path)
    if design_intent is not None:
        brief["design_intent"] = design_intent
    project_store.save_json(brief_path, brief)
    return project_dir


FULL_DESIGN_INTENT = {
    "quality_standard": "Etsy-worthy",
    "use_case": "classroom organization",
    "style_direction": ["minimal", "functional"],
    "reference_inputs": [{"type": "image", "description": "a reference photo", "local_only": True}],
    "manufacturability_constraints": {"max_size_mm": [120, 100, 100]},
    "iteration_plan": {"acceptance_notes": "matches the storage bin lid's existing footprint"},
}

PARTIAL_DESIGN_INTENT = {
    "quality_standard": "Etsy-worthy",
    # use_case, style_direction, reference_inputs, iteration_plan all absent.
}


def test_html_includes_design_intent_section_heading(isolated_projects_dir):
    _init_project_with_design_intent(isolated_projects_dir, FULL_DESIGN_INTENT)
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    assert "Design Intent" in html
    assert "Manufacturing Overview" in html
    assert "Artifacts" in html
    assert "Review Readiness" in html


def test_html_fully_populated_design_intent_renders_all_fields(isolated_projects_dir):
    _init_project_with_design_intent(isolated_projects_dir, FULL_DESIGN_INTENT)
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "Etsy-worthy" in html
    assert "classroom organization" in html
    assert "minimal / functional" in html
    assert "Fits configured printers" in html
    assert "matches the storage bin lid&#x27;s existing footprint" in html or (
        "matches the storage bin lid's existing footprint" in html
    )
    assert ">1<" in html  # reference input count rendered somewhere


def test_html_partial_design_intent_renders_fallbacks(isolated_projects_dir):
    _init_project_with_design_intent(isolated_projects_dir, PARTIAL_DESIGN_INTENT)
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "Etsy-worthy" in html
    assert "Not specified" in html
    assert ">None<" in html  # design notes fallback


def test_html_missing_design_intent_renders_cleanly(isolated_projects_dir):
    _init_project_with_design_intent(isolated_projects_dir, None)
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "No design intent declared for this project." in html
    assert "Traceback" not in html


def test_html_never_leaves_design_intent_value_blank(isolated_projects_dir):
    for design_intent in (None, PARTIAL_DESIGN_INTENT, FULL_DESIGN_INTENT):
        _init_project_with_design_intent(isolated_projects_dir, design_intent)
        board = gather_board_data(isolated_projects_dir)
        html = build_board_html(board)
        assert "di-value\"></span>" not in html
        assert "di-value\"> <" not in html


# ---- Status badges ----


def test_html_status_badges_present_when_artifacts_exist(project_root):
    (project_root / "cad").mkdir(exist_ok=True)
    (project_root / "cad" / "part.scad").write_text("// demo", encoding="utf-8")

    board_dir = project_root.parent
    board = gather_board_data(board_dir)
    html = build_board_html(board)

    assert "CAD Present" in html
    assert "STL Missing" in html
    assert "Render Missing" in html


def test_html_status_badges_missing_when_no_artifacts(project_root):
    board_dir = project_root.parent
    board = gather_board_data(board_dir)
    html = build_board_html(board)

    assert "CAD Missing" in html
    assert "STL Missing" in html
    assert "Render Missing" in html


def test_html_review_readiness_badge_not_ready_by_default(project_root):
    board_dir = project_root.parent
    board = gather_board_data(board_dir)
    html = build_board_html(board)

    assert "Review Not Ready" in html
    assert "badge-review-not-ready" in html


def test_html_review_readiness_badge_ready_when_slicer_review_ready():
    project = _full_project(
        visual_readiness_state="slicer_review_ready",
        cad_files=["cad/part.scad"],
        mesh_files=["stl/part.stl"],
        render_files=["renders/part.png"],
    )
    html = build_board_html(_minimal_board([project]))
    assert "Review Ready" in html
    assert "badge-review-ready" in html


# ---- Escaping / no external assets / no JS ----


def test_html_design_intent_section_escapes_values():
    project = _full_project(
        design_intent_detail={
            "quality_standard": "<script>alert(1)</script>",
            "use_case": "kitchen & dining",
            "style_direction": ["<b>bold</b>"],
            "manufacturability_result": "fits_some_printers",
            "reference_input_count": 0,
            "design_notes": "\"quoted\" notes",
            "warnings": ["<img src=x onerror=alert(1)>"],
        },
    )
    html = build_board_html(_minimal_board([project]))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;img" in html


def test_html_design_intent_section_has_no_external_assets_or_tracking():
    _forbidden = ("http://", "https://", "<script", "cdn.", "google-analytics", "fetch(", "XMLHttpRequest")
    project = _full_project(
        design_intent_detail={
            "quality_standard": "Etsy-worthy",
            "use_case": "gift",
            "style_direction": ["minimal"],
            "manufacturability_result": "fits_some_printers",
            "reference_input_count": 1,
            "design_notes": "some notes",
            "warnings": ["an advisory warning"],
        },
    )
    html = build_board_html(_minimal_board([project]))
    for term in _forbidden:
        assert term not in html


def test_html_project_card_gracefully_handles_missing_optional_keys():
    # A hand-built project dict, as tests elsewhere in this suite construct,
    # need not carry the card-only keys `summarize_project()` would compute -
    # the card must not raise even when design_intent_detail/health_signals/
    # suggested_actions are entirely absent (only the pre-existing table-row
    # fields, already required before Phase 27, are supplied here).
    project = _full_project(project_name="Bare", project_dir="bare", slug="bare")
    assert "design_intent_detail" not in project
    assert "health_signals" not in project
    assert "suggested_actions" not in project

    html = build_board_html(_minimal_board([project]))
    assert "Bare" in html
    assert "No design intent declared for this project." in html


# ---- Regression: existing preview board functionality preserved ----


def test_existing_sections_still_present_alongside_design_intent_cards(isolated_projects_dir):
    _init_project_with_design_intent(isolated_projects_dir, FULL_DESIGN_INTENT)
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "<table>" in html
    assert "Health signals" in html
    assert "Suggested next steps" in html
    assert "Local static preview only" in html


def test_cli_preview_board_html_includes_design_intent_section(isolated_projects_dir):
    _init_project_with_design_intent(isolated_projects_dir, FULL_DESIGN_INTENT)
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    html = (isolated_projects_dir / "preview_board" / "index.html").read_text()
    assert "Design Intent" in html
    assert "classroom organization" in html


def test_preview_board_json_output_unaffected_by_html_design_intent_section(isolated_projects_dir):
    _init_project_with_design_intent(isolated_projects_dir, FULL_DESIGN_INTENT)
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    import json

    board = json.loads((isolated_projects_dir / "preview_board" / "index.json").read_text())
    project = board["projects"][0]
    assert set(project["design_intent_summary"].keys()) == {
        "quality_standard", "use_case", "manufacturability_result",
    }
    assert set(project["design_intent_detail"].keys()) == {
        "quality_standard", "use_case", "style_direction", "manufacturability_result",
        "reference_input_count", "design_notes", "warnings",
    }


def test_regression_all_example_projects_still_summarize_and_render(project_root):
    # Not a real example project (examples/ aren't under a projects_root), but
    # exercises the same summarize_project -> build_board_html pipeline the
    # real preview-board CLI command runs, to guard against a regression in
    # the common no-design-intent path.
    summary = summarize_project(project_root)
    assert summary["design_intent_detail"] is None
    board_dir = project_root.parent
    board = gather_board_data(board_dir)
    html = build_board_html(board)
    assert "Traceback" not in html

"""Phase 26 tests: surfacing existing `design_intent` manufacturability
information inside `factory report` and the preview board - visibility
only. See docs/design-intent-brief.md, docs/roadmap.md Phase 26.

This phase adds no new approval, scoring, or gate semantics - these tests
exist to prove that, not just that the new text appears.
"""

import hashlib
import inspect

import pytest
from typer.testing import CliRunner

from factory import design_intent_check, project_store
from factory.cli import app
from factory.design_intent_check import summarize_design_intent

runner = CliRunner()

PIGGY_BANK_BRIEF = (
    project_store.REPO_ROOT
    / "examples"
    / "future-organic-models"
    / "piggy-bank-design-study"
    / "concept_brief.json"
)


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


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
    "use_case": "kitchen organization",
    "style_direction": ["minimalist", "functional"],
    "manufacturability_constraints": {"max_size_mm": [120, 100, 100]},
}


# ---- summarize_design_intent() ----


def test_summarize_design_intent_none_when_field_absent(tmp_path):
    path = tmp_path / "brief.json"
    path.write_text('{"project_name": "x"}', encoding="utf-8")
    assert summarize_design_intent(path) is None


def test_summarize_design_intent_none_when_not_a_dict(tmp_path):
    path = tmp_path / "brief.json"
    path.write_text('{"design_intent": "not a dict"}', encoding="utf-8")
    assert summarize_design_intent(path) is None


def test_summarize_design_intent_none_when_file_missing(tmp_path):
    assert summarize_design_intent(tmp_path / "does-not-exist.json") is None


def test_summarize_design_intent_none_when_invalid_json(tmp_path):
    path = tmp_path / "brief.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert summarize_design_intent(path) is None


def test_summarize_design_intent_full_shape_for_piggy_bank():
    summary = summarize_design_intent(PIGGY_BANK_BRIEF)
    assert summary is not None
    assert set(summary.keys()) == {
        "quality_standard", "use_case", "style_direction", "max_size_mm", "manufacturability_check",
    }
    assert summary["quality_standard"] == "Etsy-worthy"
    assert summary["use_case"] == "everyday coin storage that's also a display-worthy object"
    assert summary["style_direction"] == ["cute", "designer-toy", "ceramic-smooth"]
    assert summary["max_size_mm"] == [120.0, 100.0, 100.0]
    assert summary["manufacturability_check"]["result"] == "fits_some_printers"
    assert summary["manufacturability_check"]["fitting_printers"]
    assert all(isinstance(p, str) for p in summary["manufacturability_check"]["fitting_printers"])


def test_summarize_design_intent_is_deterministic():
    assert summarize_design_intent(PIGGY_BANK_BRIEF) == summarize_design_intent(PIGGY_BANK_BRIEF)


@pytest.mark.parametrize(
    "design_intent,expected_use_case,expected_style",
    [
        ({"use_case": 123}, None, None),
        ({"style_direction": "not a list"}, None, None),
        ({"style_direction": {"a": 1}}, None, None),
        ({"use_case": "valid", "style_direction": ["ok"]}, "valid", ["ok"]),
    ],
)
def test_summarize_design_intent_malformed_fields_handled_safely(tmp_path, design_intent, expected_use_case, expected_style):
    path = tmp_path / "brief.json"
    path.write_text(
        __import__("json").dumps({"design_intent": design_intent}),
        encoding="utf-8",
    )
    summary = summarize_design_intent(path)
    assert summary is not None
    assert summary["use_case"] == expected_use_case
    assert summary["style_direction"] == expected_style


def test_summarize_design_intent_writes_no_files(tmp_path):
    before = sorted(p.name for p in tmp_path.iterdir())
    summarize_design_intent(PIGGY_BANK_BRIEF)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after


def test_summarize_design_intent_does_not_duplicate_manufacturability_parsing():
    # summarize_design_intent must call check_design_intent_manufacturability
    # rather than re-deriving max_size_mm/fit logic itself.
    source = inspect.getsource(design_intent_check.summarize_design_intent)
    assert "check_design_intent_manufacturability(" in source
    assert "permutations" not in source
    assert "load_printers" not in source


# ---- design_intent_check module stays read-only/local (covers the new function too) ----


def test_design_intent_check_module_still_has_no_forbidden_calls():
    # Reuses the same forbidden-call vocabulary as test_design_intent_check.py;
    # inspect.getsource() covers the whole module, including the new
    # summarize_design_intent() added in this phase.
    forbidden = (
        "import subprocess", "subprocess.run(", "subprocess.call(", "subprocess.Popen(",
        "os.system(", "os.popen(", "socket.", "import urllib", "import requests",
        "http.client", "write_text(", "write_bytes(", "save_json(",
    )
    source = inspect.getsource(design_intent_check)
    for forbidden_call in forbidden:
        assert forbidden_call not in source


def test_design_intent_check_module_does_not_set_human_approved_or_print_ready():
    source = inspect.getsource(design_intent_check)
    assert '"human_approved": True' not in source
    assert '"print_ready": True' not in source
    assert "human_approved = True" not in source
    assert "print_ready = True" not in source


# ---- factory report: shows design intent when present ----


def test_report_shows_design_intent_when_present(isolated_projects_dir):
    project_dir = _init_project_with_design_intent(isolated_projects_dir, FULL_DESIGN_INTENT)
    result = runner.invoke(app, ["report", str(project_dir)])
    assert result.exit_code == 0
    assert "Design Intent:" in result.stdout
    assert "Etsy-worthy" in result.stdout
    assert "kitchen organization" in result.stdout
    assert "minimalist, functional" in result.stdout
    assert "fits configured printers" in result.stdout


def test_report_design_intent_section_is_advisory_only(isolated_projects_dir):
    project_dir = _init_project_with_design_intent(isolated_projects_dir, FULL_DESIGN_INTENT)
    result = runner.invoke(app, ["report", str(project_dir)])
    assert "advisory only" in result.stdout
    assert "does not judge creativity" in result.stdout
    assert "approve this design" in result.stdout


# ---- factory report: no design_intent -> no error, no section ----


def test_report_no_design_intent_no_error_no_section(isolated_projects_dir):
    project_dir = _init_project_with_design_intent(isolated_projects_dir, None)
    result = runner.invoke(app, ["report", str(project_dir)])
    assert result.exit_code == 0
    assert "Design Intent:" not in result.stdout


# ---- factory report: malformed design_intent handled safely ----


@pytest.mark.parametrize(
    "malformed_design_intent",
    [
        "not a dict",
        123,
        ["a", "list"],
        {"style_direction": "not a list", "use_case": 42},
    ],
)
def test_report_malformed_design_intent_handled_safely(isolated_projects_dir, malformed_design_intent):
    project_dir = _init_project_with_design_intent(isolated_projects_dir, malformed_design_intent)
    result = runner.invoke(app, ["report", str(project_dir)])
    assert result.exit_code == 0
    assert "Traceback" not in result.stdout


# ---- factory report: no writes, no approval/print-ready semantics ----


def test_report_does_not_modify_brief_json(isolated_projects_dir):
    project_dir = _init_project_with_design_intent(isolated_projects_dir, FULL_DESIGN_INTENT)
    brief_path = project_dir / "brief.json"
    before = hashlib.sha256(brief_path.read_bytes()).hexdigest()
    runner.invoke(app, ["report", str(project_dir)])
    after = hashlib.sha256(brief_path.read_bytes()).hexdigest()
    assert before == after


def test_report_does_not_set_human_approved_or_print_ready(isolated_projects_dir):
    project_dir = _init_project_with_design_intent(isolated_projects_dir, FULL_DESIGN_INTENT)
    runner.invoke(app, ["report", str(project_dir)])
    brief = project_store.load_json(project_dir / "brief.json")
    assert brief.get("human_approved") is not True
    assert brief.get("status") != "print_ready"
    build_plan_path = project_dir / "build_plan.json"
    if build_plan_path.is_file():
        build_plan = project_store.load_json(build_plan_path)
        assert build_plan.get("status") != "print_ready"


def test_report_writes_no_new_files(isolated_projects_dir):
    project_dir = _init_project_with_design_intent(isolated_projects_dir, FULL_DESIGN_INTENT)
    before = {p for p in project_dir.rglob("*") if p.is_file()}
    runner.invoke(app, ["report", str(project_dir)])
    after = {p for p in project_dir.rglob("*") if p.is_file()}
    assert before == after


def test_report_does_not_modify_committed_piggy_bank_concept_brief():
    before = hashlib.sha256(PIGGY_BANK_BRIEF.read_bytes()).hexdigest()
    summarize_design_intent(PIGGY_BANK_BRIEF)
    after = hashlib.sha256(PIGGY_BANK_BRIEF.read_bytes()).hexdigest()
    assert before == after


# ---- review-gate behavior unchanged by this phase ----


def test_review_gate_cli_still_behaves_the_same_after_phase26():
    result = runner.invoke(app, ["review-gate", "examples/simple-nameplate"])
    assert result.exit_code == 1
    assert "No STL files exist yet" in result.stdout


def test_review_gate_does_not_mention_design_intent(isolated_projects_dir):
    project_dir = _init_project_with_design_intent(isolated_projects_dir, FULL_DESIGN_INTENT)
    result = runner.invoke(app, ["review-gate", str(project_dir)])
    assert "design intent" not in result.stdout.lower()
    assert "design_intent" not in result.stdout.lower()


def test_review_gate_json_output_key_set_unaffected_by_design_intent(isolated_projects_dir):
    with_intent = _init_project_with_design_intent(isolated_projects_dir, FULL_DESIGN_INTENT)
    result = runner.invoke(app, ["review-gate", "--json", str(with_intent)])
    import json

    payload = json.loads(result.stdout)
    assert "design_intent_summary" not in payload
    assert set(payload.keys()) == {
        "project_dir", "gate", "result", "status_ceiling", "summary",
        "blocking_items", "warning_items", "ready_items", "suggested_actions", "notes",
    }


# ---- no network/subprocess/printer/slicer/cloud/Blender/Meshy behavior introduced ----


def test_no_forbidden_terms_in_new_report_helper():
    from factory import cli

    source = inspect.getsource(cli._print_design_intent_summary)
    forbidden = (
        "subprocess", "socket.", "urllib", "requests", "http.client",
        "meshy", "blender", "printer.connect", "slicer.send",
    )
    lowered = source.lower()
    for term in forbidden:
        assert term.lower() not in lowered


def test_no_stl_or_png_files_added_by_phase26():
    for directory in ("docs", "examples", "src"):
        root = project_store.REPO_ROOT / directory
        assert not any(root.rglob("*.stl"))
        assert not any(root.rglob("*.png"))

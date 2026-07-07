import pytest
from typer.testing import CliRunner

from factory import project_store
from factory.cli import app

runner = CliRunner()


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


def _init_and_plan(isolated_projects_dir, description, intended_printer="Bambu H2D"):
    runner.invoke(app, ["init-project", "Demo Project"])
    project_dir = isolated_projects_dir / "demo-project"
    brief_path = project_dir / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["description"] = description
    brief["intended_printer"] = intended_printer
    project_store.save_json(brief_path, brief)
    runner.invoke(app, ["plan", str(brief_path)])
    return project_dir


def test_report_shows_target_printer_and_accessories(isolated_projects_dir):
    project_dir = _init_and_plan(isolated_projects_dir, "a two-color raised-letter nameplate")

    result = runner.invoke(app, ["report", str(project_dir)])
    assert result.exit_code == 0
    assert "target printer: Bambu Lab H2D" in result.stdout
    assert "AMS 2 Pro" in result.stdout


def test_report_shows_manufacturing_options_and_recommendation(isolated_projects_dir):
    project_dir = _init_and_plan(isolated_projects_dir, "a two-color raised-letter nameplate")

    result = runner.invoke(app, ["report", str(project_dir)])
    assert result.exit_code == 0
    assert "manufacturing options (7 explained)" in result.stdout
    assert "recommended option: 'multipart_color'" in result.stdout
    assert "selected: None" in result.stdout


def test_report_lists_remaining_human_decisions(isolated_projects_dir):
    project_dir = _init_and_plan(isolated_projects_dir, "a simple test part")

    result = runner.invoke(app, ["report", str(project_dir)])
    build_plan = project_store.load_json(project_dir / "build_plan.json")
    assert f"remaining human decisions: {len(build_plan['unanswered_questions'])}" in result.stdout


def test_report_always_ends_with_fixed_safety_lines(isolated_projects_dir):
    project_dir = _init_and_plan(isolated_projects_dir, "a simple test part")

    result = runner.invoke(app, ["report", str(project_dir)])
    assert "Human slicer review required." in result.stdout
    assert "Project is NOT print-ready." in result.stdout


def test_report_without_a_plan_does_not_crash(isolated_projects_dir):
    runner.invoke(app, ["init-project", "Demo Project"])
    project_dir = isolated_projects_dir / "demo-project"

    result = runner.invoke(app, ["report", str(project_dir)])
    assert result.exit_code == 0
    assert "target printer: (not planned yet" in result.stdout
    assert "Project is NOT print-ready." in result.stdout


def test_report_never_reports_print_ready_status(isolated_projects_dir):
    project_dir = _init_and_plan(isolated_projects_dir, "a two-color raised-letter nameplate")

    brief_path = project_dir / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["status"] = "print_ready"
    project_store.save_json(brief_path, brief)

    result = runner.invoke(app, ["report", str(project_dir)])
    safe_status_line = result.stdout.split("current safe status:")[1].split("\n")[0]
    assert "print_ready" not in safe_status_line


def test_report_before_option_selection_shows_unresolved_decision(isolated_projects_dir):
    project_dir = _init_and_plan(isolated_projects_dir, "a two-color raised-letter nameplate")

    result = runner.invoke(app, ["report", str(project_dir)])
    assert "unresolved decision" in result.stdout.lower()
    assert "manifest readiness: no_option_selected" in result.stdout
    assert "CAD generation can proceed safely: False" in result.stdout


def test_report_after_option_selection_shows_selected_option(isolated_projects_dir):
    project_dir = _init_and_plan(isolated_projects_dir, "a two-color raised-letter nameplate")
    runner.invoke(app, ["choose-option", str(project_dir), "multipart_color"])

    result = runner.invoke(app, ["report", str(project_dir)])
    assert "selected manufacturing option: 'multipart_color'" in result.stdout
    assert "manifest readiness: multipart_incomplete" in result.stdout
    assert "multipart planning incomplete: True" in result.stdout
    assert "unresolved decision" not in result.stdout.lower()


def test_report_after_selection_status_never_exceeds_slicer_review_ready(isolated_projects_dir):
    project_dir = _init_and_plan(isolated_projects_dir, "a two-color raised-letter nameplate")
    runner.invoke(app, ["choose-option", str(project_dir), "multipart_color"])

    result = runner.invoke(app, ["report", str(project_dir)])
    assert "current safe status: manufacturing_option_selected" in result.stdout
    assert "human_approved" not in result.stdout
    assert "print_ready" not in result.stdout
    assert "Human slicer review required." in result.stdout
    assert "Project is NOT print-ready." in result.stdout


def test_report_drops_resolved_selection_question_after_choosing(isolated_projects_dir):
    project_dir = _init_and_plan(isolated_projects_dir, "a two-color raised-letter nameplate")
    before = runner.invoke(app, ["report", str(project_dir)])
    before_count = int(before.stdout.split("remaining human decisions: ")[1].split("\n")[0])

    runner.invoke(app, ["choose-option", str(project_dir), "multipart_color"])
    after = runner.invoke(app, ["report", str(project_dir)])
    after_count = int(after.stdout.split("remaining human decisions: ")[1].split("\n")[0])

    assert after_count == before_count - 1

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


@pytest.fixture()
def planned_project_dir(isolated_projects_dir):
    runner.invoke(app, ["init-project", "Demo Project"])
    project_dir = isolated_projects_dir / "demo-project"
    brief_path = project_dir / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["description"] = "a two-color raised-letter nameplate"
    brief["intended_printer"] = "Bambu H2D"
    project_store.save_json(brief_path, brief)
    runner.invoke(app, ["plan", str(brief_path)])
    return project_dir


def test_list_options_shows_all_seven_options(planned_project_dir):
    result = runner.invoke(app, ["list-options", str(planned_project_dir)])
    assert result.exit_code == 0
    assert "manufacturing options (7):" in result.stdout
    assert "RECOMMENDED" in result.stdout
    for option_id in (
        "single_piece",
        "multipart_build_volume",
        "multipart_color",
        "multipart_detail",
        "multipart_paint",
        "multipart_strength",
        "replaceable_components",
    ):
        assert option_id in result.stdout


def test_list_options_without_plan_errors_cleanly(isolated_projects_dir):
    runner.invoke(app, ["init-project", "No Plan Project"])
    project_dir = isolated_projects_dir / "no-plan-project"
    # init-project writes a build_plan.json stub, so list-options should run
    # but show zero options rather than crash.
    result = runner.invoke(app, ["list-options", str(project_dir)])
    assert result.exit_code == 0
    assert "manufacturing options (0):" in result.stdout


def test_list_options_missing_build_plan_file_errors(isolated_projects_dir):
    project_dir = isolated_projects_dir / "nonexistent"
    project_dir.mkdir()
    result = runner.invoke(app, ["list-options", str(project_dir)])
    assert result.exit_code == 1
    assert "error" in result.stdout.lower()


def test_choose_option_valid_id_succeeds(planned_project_dir):
    result = runner.invoke(app, ["choose-option", str(planned_project_dir), "multipart_color"])
    assert result.exit_code == 0
    assert "selected" in result.stdout.lower()
    assert "manufacturing_option_selected" in result.stdout

    build_plan = project_store.load_json(planned_project_dir / "build_plan.json")
    assert build_plan["selected_manufacturing_option"] == "multipart_color"


def test_choose_option_invalid_id_fails_cleanly(planned_project_dir):
    result = runner.invoke(app, ["choose-option", str(planned_project_dir), "bogus_option"])
    assert result.exit_code == 1
    assert "unknown manufacturing option" in result.stdout.lower()

    build_plan = project_store.load_json(planned_project_dir / "build_plan.json")
    assert build_plan["selected_manufacturing_option"] is None


def test_choose_option_does_not_claim_cad_or_export_action(planned_project_dir):
    result = runner.invoke(app, ["choose-option", str(planned_project_dir), "single_piece"])
    assert result.exit_code == 0
    normalized = " ".join(result.stdout.lower().split())
    assert "did not generate or modify cad" in normalized
    assert "export an stl" in normalized
    assert "invoke openscad" in normalized
    assert "printer/slicer/network" in normalized


def test_choose_option_never_sets_print_ready_or_human_approved(planned_project_dir):
    runner.invoke(app, ["choose-option", str(planned_project_dir), "multipart_color"])
    brief = project_store.load_json(planned_project_dir / "brief.json")
    assert brief["status"] not in ("print_ready", "human_approved")

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


def test_status_runs_and_reports_safety_posture():
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "repo path" in result.stdout
    assert "python version" in result.stdout
    assert "safety status" in result.stdout
    assert "no cloud/paid API calls" in result.stdout
    assert "no printer control" in result.stdout


def test_init_project_creates_structure_and_refuses_overwrite(isolated_projects_dir):
    result = runner.invoke(app, ["init-project", "Test Widget"])
    assert result.exit_code == 0

    root = isolated_projects_dir / "test-widget"
    assert root.is_dir()
    for sub in project_store.PROJECT_SUBDIRS:
        assert (root / sub).is_dir()

    result_again = runner.invoke(app, ["init-project", "Test Widget"])
    assert result_again.exit_code != 0


def test_plan_writes_build_plan(isolated_projects_dir):
    runner.invoke(app, ["init-project", "Test Widget"])
    brief_path = isolated_projects_dir / "test-widget" / "brief.json"

    result = runner.invoke(app, ["plan", str(brief_path)])
    assert result.exit_code == 0
    assert "plan_drafted" in result.stdout

    build_plan = project_store.load_json(isolated_projects_dir / "test-widget" / "build_plan.json")
    assert build_plan["status"] == "plan_drafted"
    assert build_plan["human_review_required"] is True


def test_inspect_slicer_is_read_only_and_runs(monkeypatch):
    result = runner.invoke(app, ["inspect-slicer"])
    assert result.exit_code == 0
    assert "never launches a slicer, slices, prints, or uploads" in result.stdout


def test_validate_and_render_on_generated_cube(isolated_projects_dir, tmp_path):
    trimesh = pytest.importorskip("trimesh")

    runner.invoke(app, ["init-project", "Test Widget"])
    project_root = isolated_projects_dir / "test-widget"
    mesh_path = project_root / "stl" / "cube.stl"
    trimesh.creation.box(extents=(20, 20, 20)).export(str(mesh_path))

    validate_result = runner.invoke(app, ["validate", str(mesh_path)])
    assert validate_result.exit_code == 0
    assert "overall:" in validate_result.stdout

    validation_report_path = project_root / "validation" / "cube_validation.json"
    assert validation_report_path.is_file()
    report = project_store.load_json(validation_report_path)
    assert report["overall_status"] in ("PASS", "WARN")
    assert "human slicer review required" in report["summary_message"]

    render_result = runner.invoke(app, ["render", str(mesh_path)])
    assert render_result.exit_code == 0

    preview_path = project_root / "renders" / "cube_preview.png"
    assert preview_path.is_file()


def test_report_reflects_project_state(isolated_projects_dir):
    trimesh = pytest.importorskip("trimesh")

    runner.invoke(app, ["init-project", "Test Widget"])
    project_root = isolated_projects_dir / "test-widget"

    result_before = runner.invoke(app, ["report", str(project_root)])
    assert result_before.exit_code == 0
    assert "current safe status" in result_before.stdout
    assert "print_ready" not in result_before.stdout.split("current safe status")[1].split("\n")[0]

    mesh_path = project_root / "stl" / "cube.stl"
    trimesh.creation.box(extents=(20, 20, 20)).export(str(mesh_path))
    runner.invoke(app, ["validate", str(mesh_path)])
    runner.invoke(app, ["render", str(mesh_path)])

    result_after = runner.invoke(app, ["report", str(project_root)])
    assert result_after.exit_code == 0
    assert "slicer_review_ready" in result_after.stdout
    assert "Human approval is required" in result_after.stdout

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
def project_dir(isolated_projects_dir):
    runner.invoke(app, ["init-project", "Demo Project"])
    return isolated_projects_dir / "demo-project"


def _files_snapshot(project_dir):
    return {p: p.read_bytes() for p in project_dir.rglob("*") if p.is_file()}


def test_preview_index_is_fully_read_only(project_dir):
    before = _files_snapshot(project_dir)
    result = runner.invoke(app, ["preview-index", str(project_dir)])
    after = _files_snapshot(project_dir)
    assert result.exit_code == 0
    assert before == after


def test_preview_index_on_empty_project(project_dir):
    result = runner.invoke(app, ["preview-index", str(project_dir)])
    assert result.exit_code == 0
    assert "CAD source files: 0" in result.stdout
    assert "mesh/STL files: 0" in result.stdout
    assert "render/preview images: 0" in result.stdout
    assert "missing visual artifacts" in result.stdout.lower()


def test_preview_index_with_cad_files_only(project_dir):
    (project_dir / "cad" / "part.scad").write_text("// scad\n", encoding="utf-8")
    result = runner.invoke(app, ["preview-index", str(project_dir)])
    assert result.exit_code == 0
    assert "CAD source files: 1" in result.stdout


def test_preview_index_with_stl_files_only(project_dir):
    (project_dir / "stl" / "part.stl").write_bytes(b"fake stl")
    result = runner.invoke(app, ["preview-index", str(project_dir)])
    assert result.exit_code == 0
    assert "mesh/STL files: 1" in result.stdout
    normalized = " ".join(result.stdout.lower().split())
    assert "missing visual artifacts (1)" in normalized


def test_preview_index_with_renders(project_dir):
    (project_dir / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_dir / "renders" / "part_preview.png").write_bytes(b"fake png")
    result = runner.invoke(app, ["preview-index", str(project_dir)])
    assert result.exit_code == 0
    assert "render/preview images: 1" in result.stdout
    assert "missing visual artifacts: none" in result.stdout


def test_preview_index_missing_project_dir_errors(isolated_projects_dir):
    result = runner.invoke(app, ["preview-index", str(isolated_projects_dir / "nope")])
    assert result.exit_code == 1


def test_preview_index_shows_required_safety_lines(project_dir):
    result = runner.invoke(app, ["preview-index", str(project_dir)])
    assert "Human visual inspection required." in result.stdout
    assert "Human slicer review required." in result.stdout
    assert "Project is NOT print-ready." in result.stdout


def test_preview_project_writes_index_json(project_dir):
    result = runner.invoke(app, ["preview-project", str(project_dir)])
    assert result.exit_code == 0
    assert (project_dir / "preview_package" / "index.json").is_file()


def test_preview_project_writes_preview_report_md(project_dir):
    runner.invoke(app, ["preview-project", str(project_dir)])
    report_path = project_dir / "preview_package" / "preview_report.md"
    assert report_path.is_file()
    content = report_path.read_text(encoding="utf-8")
    assert "Human visual inspection required." in content
    assert "Human slicer review required." in content
    assert "Project is NOT print-ready." in content


def test_preview_project_does_not_duplicate_render_images(project_dir):
    render_path = project_dir / "renders" / "part_preview.png"
    render_bytes = b"original bytes"
    (project_dir / "stl" / "part.stl").write_bytes(b"fake stl")
    render_path.write_bytes(render_bytes)

    runner.invoke(app, ["preview-project", str(project_dir)])

    package_dir = project_dir / "preview_package"
    assert list(package_dir.rglob("*.png")) == []
    assert render_path.read_bytes() == render_bytes


def test_preview_project_shows_required_safety_lines(project_dir):
    result = runner.invoke(app, ["preview-project", str(project_dir)])
    assert "Human visual inspection required." in result.stdout
    assert "Human slicer review required." in result.stdout
    assert "Project is NOT print-ready." in result.stdout


def test_preview_project_never_sets_print_ready_or_human_approved(project_dir):
    runner.invoke(app, ["preview-project", str(project_dir)])
    brief = project_store.load_json(project_dir / "brief.json")
    assert brief["status"] not in ("print_ready", "human_approved")


def test_report_shows_preview_package_missing_before_preview_project(project_dir):
    result = runner.invoke(app, ["report", str(project_dir)])
    assert "preview package: missing" in result.stdout


def test_report_shows_preview_package_summary_after_preview_project(project_dir):
    runner.invoke(app, ["preview-project", str(project_dir)])
    result = runner.invoke(app, ["report", str(project_dir)])
    # Absolute paths in a deep tmp_path can wrap mid-word under Rich's fixed
    # console width, so check the JSON content directly instead of stdout
    # for path substrings, and only check short, wrap-safe stdout snippets.
    index = project_store.load_json(project_dir / "preview_package" / "index.json")
    assert index is not None
    assert "missing preview items:" in result.stdout
    assert "preview package:" in result.stdout
    assert "preview report:" in result.stdout


def test_report_still_ends_with_fixed_safety_lines_with_preview_package(project_dir):
    runner.invoke(app, ["preview-project", str(project_dir)])
    result = runner.invoke(app, ["report", str(project_dir)])
    assert "Human slicer review required." in result.stdout
    assert "Project is NOT print-ready." in result.stdout


def test_old_project_without_preview_package_dir_still_works(project_dir):
    # Projects created before Phase 6 never had a preview_package/ subdir -
    # both commands must work fine without it existing in advance.
    assert not (project_dir / "preview_package").exists()
    index_result = runner.invoke(app, ["preview-index", str(project_dir)])
    assert index_result.exit_code == 0
    project_result = runner.invoke(app, ["preview-project", str(project_dir)])
    assert project_result.exit_code == 0
    assert (project_dir / "preview_package" / "index.json").is_file()


def test_preview_index_handles_malformed_manifest_without_crashing(project_dir):
    (project_dir / "part_manifest.json").write_text("{not valid json", encoding="utf-8")
    result = runner.invoke(app, ["preview-index", str(project_dir)])
    assert result.exit_code == 0


def test_preview_project_handles_missing_manifest_without_crashing(project_dir):
    (project_dir / "part_manifest.json").unlink()
    result = runner.invoke(app, ["preview-project", str(project_dir)])
    assert result.exit_code == 0

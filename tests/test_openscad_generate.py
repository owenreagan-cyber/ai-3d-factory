import ast
import inspect

import pytest
from typer.testing import CliRunner

from factory import project_store
from factory.cli import app
from factory.openscad import generate as generate_module
from factory.openscad import templates as templates_module
from factory.openscad.generate import GeneratedFileExistsError, ProjectNotInitializedError, generate_openscad
from factory.openscad.templates import ALLOWED_TEMPLATES, render_template

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


# ---- template rendering ----


def test_render_test_cube_contains_key_parameters():
    output = render_template("test-cube", None)
    assert len(output.files) == 1
    content = output.files[0].content
    assert "cube_size = 20" in content
    assert "module test_cube()" in content


def test_render_nameplate_contains_text_and_parameters():
    output = render_template("nameplate", "MR REAGAN")
    content = output.files[0].content
    assert 'text_string = "MR REAGAN"' in content
    assert "plate_width" in content
    assert "text_height" in content


def test_render_sign_contains_text_and_parameters():
    output = render_template("sign", "READ")
    content = output.files[0].content
    assert 'text_string = "READ"' in content
    assert "plate_width" in content


def test_templates_requiring_text_raise_without_it():
    for template in ("nameplate", "sign", "multipart-nameplate"):
        with pytest.raises(ValueError):
            render_template(template, None)


def test_unknown_template_raises():
    with pytest.raises(ValueError):
        render_template("not-a-real-template", None)


def test_text_is_escaped_for_scad_string_literal():
    output = render_template("nameplate", 'weird "quoted" text')
    content = output.files[0].content
    assert '\\"quoted\\"' in content


def test_multipart_nameplate_produces_two_files_and_parts():
    output = render_template("multipart-nameplate", "MR REAGAN")
    filenames = {f.filename for f in output.files}
    assert filenames == {"nameplate_base.scad", "nameplate_text.scad"}

    part_names = {p.part_name for p in output.parts}
    assert part_names == {"nameplate_base", "nameplate_text"}

    transform_notes = {p.transform_notes for p in output.parts}
    assert len(transform_notes) == 1  # both parts document the same shared origin
    assert "Shared origin" in next(iter(transform_notes))


# ---- generator / project integration ----


def test_generate_openscad_writes_expected_files(project_root):
    result = generate_openscad(project_root, "test-cube", None)
    assert (project_root / "cad" / "test_cube.scad").is_file()
    assert (project_root / "cad" / "README.md").is_file()
    assert (project_root / "slicer_review" / "openscad_export_instructions.md").is_file()
    assert result.written_files == (project_root / "cad" / "test_cube.scad",)


def test_generate_openscad_requires_initialized_project(tmp_path):
    not_a_project = tmp_path / "not-a-project"
    not_a_project.mkdir()
    with pytest.raises(ProjectNotInitializedError):
        generate_openscad(not_a_project, "test-cube", None)


def test_generate_openscad_refuses_overwrite_without_force(project_root):
    generate_openscad(project_root, "test-cube", None)
    with pytest.raises(GeneratedFileExistsError):
        generate_openscad(project_root, "test-cube", None)

    original = (project_root / "cad" / "test_cube.scad").read_text()
    assert "cube_size = 20" in original  # unchanged


def test_generate_openscad_overwrites_with_force(project_root):
    generate_openscad(project_root, "test-cube", None)
    result = generate_openscad(project_root, "test-cube", None, force=True)
    assert result.written_files[0].is_file()


def test_generate_openscad_export_instructions_scan_all_cad_files(project_root):
    generate_openscad(project_root, "test-cube", None)
    generate_openscad(project_root, "nameplate", "MR REAGAN")

    instructions = (project_root / "slicer_review" / "openscad_export_instructions.md").read_text()
    assert "openscad -o stl/test_cube.stl cad/test_cube.scad" in instructions
    assert "openscad -o stl/nameplate.stl cad/nameplate.scad" in instructions


def test_generate_openscad_updates_manifest_for_multipart(project_root):
    generate_openscad(project_root, "multipart-nameplate", "MR REAGAN")

    manifest = project_store.load_json(project_root / "part_manifest.json")
    parts_by_name = {p["part_name"]: p for p in manifest["parts"]}
    assert set(parts_by_name) == {"nameplate_base", "nameplate_text"}

    base = parts_by_name["nameplate_base"]
    text = parts_by_name["nameplate_text"]
    assert base["transform_notes"] == text["transform_notes"]
    assert "Shared origin" in base["transform_notes"]
    assert base["file_path"] == "stl/nameplate_base.stl"
    assert text["file_path"] == "stl/nameplate_text.stl"
    assert base["required_for_assembly"] is True
    assert base["license"] == "original"


def test_generate_openscad_does_not_duplicate_manifest_entries_on_rerun(project_root):
    generate_openscad(project_root, "test-cube", None)
    generate_openscad(project_root, "test-cube", None, force=True)

    manifest = project_store.load_json(project_root / "part_manifest.json")
    assert len(manifest["parts"]) == 1


def test_generate_openscad_advances_brief_status_forward_only(project_root):
    brief_path = project_root / "brief.json"
    assert project_store.load_json(brief_path)["status"] == "brief_created"

    generate_openscad(project_root, "test-cube", None)
    assert project_store.load_json(brief_path)["status"] == "cad_generated"

    # Manually push status further along; re-generating must not regress it.
    brief = project_store.load_json(brief_path)
    brief["status"] = "preview_rendered"
    project_store.save_json(brief_path, brief)

    generate_openscad(project_root, "sign", "READ")
    assert project_store.load_json(brief_path)["status"] == "preview_rendered"


# ---- CLI ----


def test_cli_generate_openscad_happy_path(isolated_projects_dir):
    runner.invoke(app, ["init-project", "Demo Project"])
    project_dir = isolated_projects_dir / "demo-project"

    result = runner.invoke(app, ["generate-openscad", str(project_dir), "--template", "test-cube"])
    assert result.exit_code == 0
    assert (project_dir / "cad" / "test_cube.scad").is_file()


def test_cli_generate_openscad_requires_text_for_nameplate(isolated_projects_dir):
    runner.invoke(app, ["init-project", "Demo Project"])
    project_dir = isolated_projects_dir / "demo-project"

    result = runner.invoke(app, ["generate-openscad", str(project_dir), "--template", "nameplate"])
    assert result.exit_code != 0


def test_cli_generate_openscad_refuses_overwrite_then_force_succeeds(isolated_projects_dir):
    runner.invoke(app, ["init-project", "Demo Project"])
    project_dir = isolated_projects_dir / "demo-project"

    first = runner.invoke(app, ["generate-openscad", str(project_dir), "--template", "test-cube"])
    assert first.exit_code == 0

    second = runner.invoke(app, ["generate-openscad", str(project_dir), "--template", "test-cube"])
    assert second.exit_code != 0

    forced = runner.invoke(app, ["generate-openscad", str(project_dir), "--template", "test-cube", "--force"])
    assert forced.exit_code == 0


def test_cli_generate_openscad_for_all_example_templates(isolated_projects_dir):
    runner.invoke(app, ["init-project", "Demo Project"])
    project_dir = isolated_projects_dir / "demo-project"

    for args in (
        ["--template", "test-cube"],
        ["--template", "nameplate", "--text", "MR REAGAN"],
        ["--template", "sign", "--text", "READ"],
        ["--template", "multipart-nameplate", "--text", "MR REAGAN"],
    ):
        result = runner.invoke(app, ["generate-openscad", str(project_dir), *args])
        assert result.exit_code == 0, result.stdout


# ---- safety: no network/subprocess/API behavior anywhere in this module ----


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    """Remove module/function/class docstrings so prose mentions (e.g. 'no subprocess'
    in a safety-comment docstring) don't trip up a source-scan safety check."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body.pop(0)
    return tree


def test_openscad_modules_have_no_network_or_process_calls():
    forbidden = [
        "import subprocess",
        "subprocess.",
        "os.system(",
        "os.popen(",
        "Popen(",
        "socket.",
        "import urllib",
        "import requests",
        "http.client",
    ]
    for module in (templates_module, generate_module):
        tree = _strip_docstrings(ast.parse(inspect.getsource(module)))
        code_only_source = ast.unparse(tree)
        for forbidden_term in forbidden:
            assert forbidden_term not in code_only_source, (
                f"{module.__name__} must stay local-only; found {forbidden_term!r}"
            )


def test_allowed_templates_match_cli_help_options():
    assert set(ALLOWED_TEMPLATES) == {"test-cube", "nameplate", "sign", "multipart-nameplate"}

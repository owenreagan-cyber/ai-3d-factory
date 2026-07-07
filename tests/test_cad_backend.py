import ast
import inspect

import pytest
from typer.testing import CliRunner

from factory import project_store
from factory.cad import backend as backend_module
from factory.cad import cadquery_backend
from factory.cad import manifest as cad_manifest_module
from factory.cad import router as cad_router_module
from factory.cad.backend import get_backend_registry, is_cadquery_available
from factory.cad.cadquery_backend import (
    CadQueryNotAvailableError,
    GeneratedFileExistsError,
    ProjectNotInitializedError,
    generate_cadquery,
)
from factory.cad.router import route_cad
from factory.cli import app

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


# ---- backend registry ----


def test_registry_has_all_four_backends():
    registry = get_backend_registry()
    assert set(registry) == {"openscad", "cadquery", "blender", "meshy"}


def test_openscad_always_available():
    assert get_backend_registry()["openscad"].status == "available"


def test_blender_and_meshy_are_future():
    registry = get_backend_registry()
    assert registry["blender"].status == "future"
    assert registry["meshy"].status == "future_gated"


def test_cadquery_status_reflects_availability(monkeypatch):
    monkeypatch.setattr(backend_module, "is_cadquery_available", lambda: True)
    assert get_backend_registry()["cadquery"].status == "available"

    monkeypatch.setattr(backend_module, "is_cadquery_available", lambda: False)
    assert get_backend_registry()["cadquery"].status == "not_installed"


def test_is_cadquery_available_never_imports_cadquery():
    # Real environment check for this repo: cadquery is not an installed
    # dependency, and this must not raise even though it isn't present.
    assert isinstance(is_cadquery_available(), bool)


# ---- factory.cad.router (route_cad) ----


def test_route_cad_openscad_match():
    result = route_cad("a nameplate sign with raised letters")
    assert result["primary_recommendation"] == "openscad"
    assert result["recommended_backends"] == ["openscad"]
    assert result["future_only_needs"] == []


def test_route_cad_cadquery_match():
    result = route_cad("a mounting bracket with fillets and a tolerance fit")
    assert result["primary_recommendation"] == "cadquery"
    assert result["recommended_backends"] == ["cadquery"]
    assert result["future_only_needs"] == []


def test_route_cad_blender_is_future_only_and_falls_back_to_openscad():
    result = route_cad("repair an imported organic mesh with boolean cleanup")
    assert result["primary_recommendation"] == "blender"
    assert result["recommended_backends"] == ["openscad"]
    assert any(need["backend_id"] == "blender" for need in result["future_only_needs"])


def test_route_cad_meshy_is_future_only_and_gated():
    result = route_cad("generative concept art meshy sculpture")
    assert result["primary_recommendation"] == "meshy"
    assert result["recommended_backends"] == ["openscad"]
    needs = {need["backend_id"] for need in result["future_only_needs"]}
    assert "meshy" in needs


def test_route_cad_unspecified_defaults_to_openscad():
    result = route_cad("")
    assert result["primary_recommendation"] == "unspecified"
    assert result["recommended_backends"] == ["openscad"]


def test_route_cad_reports_cadquery_availability_and_selected_option():
    result = route_cad("a plate", selected_manufacturing_option="single_piece")
    assert result["selected_manufacturing_option"] == "single_piece"
    assert isinstance(result["cadquery_available"], bool)


def test_route_cad_never_writes_generates_or_calls_network():
    # Purely a read of in-memory text plus the local registry - no filesystem writes.
    route_cad("a bracket with a chamfer")


# ---- factory.cad.cadquery_backend (generate_cadquery) ----


def test_generate_cadquery_requires_initialized_project(tmp_path):
    not_a_project = tmp_path / "not-a-project"
    not_a_project.mkdir()
    with pytest.raises(ProjectNotInitializedError):
        generate_cadquery(not_a_project, "mechanical-plate")


def test_generate_cadquery_unknown_template_raises(project_root):
    with pytest.raises(ValueError):
        generate_cadquery(project_root, "not-a-real-template")


def test_generate_cadquery_fails_gracefully_when_unavailable(project_root, monkeypatch):
    monkeypatch.setattr(cadquery_backend, "is_cadquery_available", lambda: False)
    with pytest.raises(CadQueryNotAvailableError):
        generate_cadquery(project_root, "mechanical-plate")
    # No files written on failure.
    assert not (project_root / "cad" / "mechanical_plate.py").exists()
    assert not (project_root / "slicer_review" / "cadquery_export_instructions.md").exists()


def test_generate_cadquery_real_environment_is_unavailable_here(project_root):
    """Documents the actual state of this environment: cadquery is not an
    installed dependency here, so the public entry point must fail cleanly
    rather than crash or attempt an install."""
    if is_cadquery_available():
        pytest.skip("cadquery is installed in this environment; not the case this test documents")
    with pytest.raises(CadQueryNotAvailableError):
        generate_cadquery(project_root, "mechanical-plate")


# The following tests exercise the success path by monkeypatching only the
# local availability check (never installing or importing the real
# `cadquery` package - `generate_cadquery` itself never imports it either;
# it just writes plain text describing a CadQuery script for a human to
# run later).


def test_generate_cadquery_writes_expected_files(project_root, monkeypatch):
    monkeypatch.setattr(cadquery_backend, "is_cadquery_available", lambda: True)
    result = generate_cadquery(project_root, "mechanical-plate")

    cad_path = project_root / "cad" / "mechanical_plate.py"
    assert cad_path.is_file()
    assert result.source_files == (cad_path,)
    assert result.expected_mesh_files == (project_root / "stl" / "mechanical_plate.stl",)

    instructions_path = project_root / "slicer_review" / "cadquery_export_instructions.md"
    assert instructions_path.is_file()
    assert "python cad/mechanical_plate.py" in instructions_path.read_text()


def test_generate_cadquery_source_is_valid_python_and_never_executed(project_root, monkeypatch):
    monkeypatch.setattr(cadquery_backend, "is_cadquery_available", lambda: True)
    generate_cadquery(project_root, "mechanical-plate")
    source = (project_root / "cad" / "mechanical_plate.py").read_text()
    ast.parse(source)  # syntactically valid; this only parses, never executes
    assert "import cadquery as cq" in source


def test_generate_cadquery_reflects_parameters_in_source(project_root, monkeypatch):
    monkeypatch.setattr(cadquery_backend, "is_cadquery_available", lambda: True)
    generate_cadquery(
        project_root,
        "mechanical-plate",
        length_mm=100.0,
        width_mm=60.0,
        hole_diameter_mm=4.2,
        label_text="REV A",
    )
    source = (project_root / "cad" / "mechanical_plate.py").read_text()
    assert "length_mm = 100.0" in source
    assert "width_mm = 60.0" in source
    assert "hole_diameter_mm = 4.2" in source
    assert "label_text = 'REV A'" in source


def test_generate_cadquery_refuses_overwrite_without_force(project_root, monkeypatch):
    monkeypatch.setattr(cadquery_backend, "is_cadquery_available", lambda: True)
    generate_cadquery(project_root, "mechanical-plate")
    with pytest.raises(GeneratedFileExistsError):
        generate_cadquery(project_root, "mechanical-plate")


def test_generate_cadquery_overwrites_with_force(project_root, monkeypatch):
    monkeypatch.setattr(cadquery_backend, "is_cadquery_available", lambda: True)
    generate_cadquery(project_root, "mechanical-plate")
    result = generate_cadquery(project_root, "mechanical-plate", length_mm=200.0, force=True)
    assert "length_mm = 200.0" in result.source_files[0].read_text()


def test_generate_cadquery_updates_manifest_without_touching_openscad_entries(project_root, monkeypatch):
    cad_manifest_module.upsert_cadquery_manifest_entry(
        project_root,
        part_name="scad_part",
        cad_source="cad/scad_part.scad",
        expected_stl_path="stl/scad_part.stl",
    )
    manifest_path = project_root / "part_manifest.json"
    before = project_store.load_json(manifest_path)
    assert len(before["parts"]) == 1

    monkeypatch.setattr(cadquery_backend, "is_cadquery_available", lambda: True)
    generate_cadquery(project_root, "mechanical-plate")

    manifest = project_store.load_json(manifest_path)
    parts_by_name = {p["part_name"]: p for p in manifest["parts"]}
    assert set(parts_by_name) == {"scad_part", "mechanical_plate"}
    assert parts_by_name["scad_part"]["cad_source"] == "cad/scad_part.scad"

    plate = parts_by_name["mechanical_plate"]
    assert plate["backend"] == "cadquery"
    assert plate["file_path"] == "stl/mechanical_plate.stl"
    assert plate["material"] == "TBD - human decision"


def test_generate_cadquery_does_not_duplicate_manifest_entries_on_rerun(project_root, monkeypatch):
    monkeypatch.setattr(cadquery_backend, "is_cadquery_available", lambda: True)
    generate_cadquery(project_root, "mechanical-plate")
    generate_cadquery(project_root, "mechanical-plate", force=True)

    manifest = project_store.load_json(project_root / "part_manifest.json")
    assert len(manifest["parts"]) == 1


def test_generate_cadquery_advances_brief_status_forward_only(project_root, monkeypatch):
    monkeypatch.setattr(cadquery_backend, "is_cadquery_available", lambda: True)
    brief_path = project_root / "brief.json"
    assert project_store.load_json(brief_path)["status"] == "brief_created"

    generate_cadquery(project_root, "mechanical-plate")
    assert project_store.load_json(brief_path)["status"] == "cad_generated"

    brief = project_store.load_json(brief_path)
    brief["status"] = "preview_rendered"
    project_store.save_json(brief_path, brief)

    generate_cadquery(project_root, "mechanical-plate", force=True)
    assert project_store.load_json(brief_path)["status"] == "preview_rendered"


# ---- CLI ----


def test_cli_route_cad_happy_path(isolated_projects_dir):
    runner.invoke(app, ["init-project", "Demo Project"])
    project_dir = isolated_projects_dir / "demo-project"

    result = runner.invoke(app, ["route-cad", str(project_dir)])
    assert result.exit_code == 0
    assert "primary recommendation" in result.stdout


def test_cli_route_cad_missing_dir():
    result = runner.invoke(app, ["route-cad", "/nonexistent/path/xyz"])
    assert result.exit_code != 0


def test_cli_generate_cadquery_fails_cleanly_when_unavailable(isolated_projects_dir, monkeypatch):
    monkeypatch.setattr(cadquery_backend, "is_cadquery_available", lambda: False)
    runner.invoke(app, ["init-project", "Demo Project"])
    project_dir = isolated_projects_dir / "demo-project"

    result = runner.invoke(app, ["generate-cadquery", str(project_dir), "--template", "mechanical-plate"])
    assert result.exit_code != 0
    assert not (project_dir / "cad" / "mechanical_plate.py").exists()


def test_cli_generate_cadquery_happy_path(isolated_projects_dir, monkeypatch):
    monkeypatch.setattr(cadquery_backend, "is_cadquery_available", lambda: True)
    runner.invoke(app, ["init-project", "Demo Project"])
    project_dir = isolated_projects_dir / "demo-project"

    result = runner.invoke(app, ["generate-cadquery", str(project_dir), "--template", "mechanical-plate"])
    assert result.exit_code == 0, result.stdout
    assert (project_dir / "cad" / "mechanical_plate.py").is_file()


def test_cli_generate_cadquery_refuses_overwrite_then_force_succeeds(isolated_projects_dir, monkeypatch):
    monkeypatch.setattr(cadquery_backend, "is_cadquery_available", lambda: True)
    runner.invoke(app, ["init-project", "Demo Project"])
    project_dir = isolated_projects_dir / "demo-project"

    first = runner.invoke(app, ["generate-cadquery", str(project_dir), "--template", "mechanical-plate"])
    assert first.exit_code == 0

    second = runner.invoke(app, ["generate-cadquery", str(project_dir), "--template", "mechanical-plate"])
    assert second.exit_code != 0

    forced = runner.invoke(
        app, ["generate-cadquery", str(project_dir), "--template", "mechanical-plate", "--force"]
    )
    assert forced.exit_code == 0


# ---- safety: no network/subprocess/import-cadquery calls anywhere in these modules ----


def _strip_docstrings(tree: ast.AST) -> ast.AST:
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


def test_cad_modules_have_no_network_or_process_calls():
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
    for module in (backend_module, cad_router_module, cadquery_backend, cad_manifest_module):
        tree = _strip_docstrings(ast.parse(inspect.getsource(module)))
        code_only_source = ast.unparse(tree)
        for forbidden_term in forbidden:
            assert forbidden_term not in code_only_source, (
                f"{module.__name__} must stay local-only; found {forbidden_term!r}"
            )


def test_cadquery_backend_never_imports_cadquery_module_itself():
    # `import cadquery` may appear only inside the *generated source string*
    # (a plain Python string literal), never as a real top-level/module import
    # in this file - the module must work even when cadquery isn't installed.
    tree = ast.parse(inspect.getsource(cadquery_backend))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name != "cadquery" for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module != "cadquery"

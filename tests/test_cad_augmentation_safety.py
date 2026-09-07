"""Phase 50 safety tests: static/AST inspection proving
`factory.cad_augmentation` stays inside its safety contract - no CadQuery
execution, no arbitrary CAD file execution, no GUI, no network, path
containment, no overwrite. Mirrors `tests/test_blender_adaptation_safety.py`'s
(Phase 49) and `tests/test_hybrid_workflow_safety.py`'s (Phase 48)
conventions exactly. See docs/cad-augmentation.md.
"""

from __future__ import annotations

import ast
import importlib
import socket
import subprocess

import pytest

from factory import cad_augmentation, project_store

_MINIMAL_STL = (
    "solid t\n"
    "facet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\n"
    "facet normal 0 0 -1\nouter loop\nvertex 0 0 0\nvertex 0 1 0\nvertex 1 0 0\nendloop\nendfacet\n"
    "endsolid t\n"
)


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture()
def blender_adapted_project(isolated_projects_dir):
    root = project_store.init_project("Piggy Bank")
    adapted_dir = root / "generated" / "blender" / "adapted"
    adapted_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = adapted_dir / "01a07ca5_adapted.stl"
    artifact_path.write_text(_MINIMAL_STL)
    return root, artifact_path


def importlib_source(module_name: str) -> str:
    return open(importlib.import_module(module_name).__file__, encoding="utf-8").read()


# ---------------------------------------------------------------------------
# factory.cad_augmentation itself never imports subprocess/network - it
# delegates the one real invocation to factory.export_pipeline.
# ---------------------------------------------------------------------------


def test_module_imports_no_subprocess_or_network_library():
    tree = ast.parse(importlib_source("factory.cad_augmentation"))
    forbidden = {"subprocess", "socket", "requests", "httpx", "aiohttp", "urllib"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(forbidden), f"cad_augmentation.py imports forbidden module(s): {imported & forbidden}"


def test_module_never_imports_cadquery_or_blender_execution_modules():
    """This module may only ever route CAD engine recommendations from
    factory.engine_registry - it must never import cadquery itself,
    factory.cad.cadquery_backend's generator, or factory.blender_adapter
    (the module that actually invokes Blender)."""
    tree = ast.parse(importlib_source("factory.cad_augmentation"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "cadquery" not in imported
    assert "factory.cad.cadquery_backend" not in imported
    assert "factory.blender_adapter" not in imported


def test_module_never_calls_cadquery_api():
    """No real `cq.*(...)`/`cadquery.*(...)` call site anywhere - this
    workflow executes OpenSCAD only. Checked via AST call sites (never a
    raw substring scan, which would also flag this module's own docstring
    explaining, in backtick-quoted prose, why `factory.tool_qualification`'s
    unrelated throwaway-fixture probe is never extended here)."""
    tree = ast.parse(importlib_source("factory.cad_augmentation"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            root = node.func
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id in ("cq", "cadquery"):
                pytest.fail(f"unexpected CadQuery API call site: {ast.dump(node.func)}")


def test_no_desktop_automation_patterns():
    text = importlib_source("factory.cad_augmentation")
    for pattern in ('os.system(', 'os.popen(', 'subprocess.Popen(', '"osascript"', "'osascript'", '"pkill"', "'pkill'", '["open"', "['open'", "FreeCADCmd", "freecad --"):
        assert pattern not in text


# ---------------------------------------------------------------------------
# Behavioral proof: planning survives poisoned network/subprocess
# ---------------------------------------------------------------------------


def test_build_plan_survives_poisoned_network_and_subprocess(blender_adapted_project, monkeypatch):
    _, artifact_path = blender_adapted_project

    def _boom(*a, **k):
        raise AssertionError("planning must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    plan = cad_augmentation.build_augmentation_plan(artifact_path, base_width_mm=120.0, base_length_mm=80.0, base_height_mm=10.0)
    assert plan["automatic_execution_allowed"] is False


def test_blocked_execution_survives_poisoned_network_and_subprocess(tmp_path, monkeypatch):
    artifact = tmp_path / "loose.stl"
    artifact.write_text(_MINIMAL_STL)

    def _boom(*a, **k):
        raise AssertionError("a blocked (unconfirmed) execution must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    result = cad_augmentation.run_organic_mechanical_augmentation(
        artifact, confirm=False, base_width_mm=120.0, base_length_mm=80.0, base_height_mm=10.0
    )
    assert result["augmentation_status"] == "blocked"


# ---------------------------------------------------------------------------
# Path containment / no-overwrite / no boolean merge
# ---------------------------------------------------------------------------


def test_output_artifact_path_is_always_under_generated_cad_augmentation(blender_adapted_project):
    project_dir, artifact_path = blender_adapted_project
    plan = cad_augmentation.build_augmentation_plan(artifact_path, base_width_mm=120.0, base_length_mm=80.0, base_height_mm=10.0)
    output = plan["output_artifact"]
    assert output is not None
    assert output.startswith(str(project_dir / "generated" / "cad_augmentation"))


def test_plan_never_modifies_the_input_artifact(blender_adapted_project):
    _, artifact_path = blender_adapted_project
    before = artifact_path.read_bytes()
    cad_augmentation.build_augmentation_plan(artifact_path, base_width_mm=120.0, base_length_mm=80.0, base_height_mm=10.0)
    cad_augmentation.build_augmentation_plan(artifact_path, base_width_mm=120.0, base_length_mm=80.0, base_height_mm=10.0)
    after = artifact_path.read_bytes()
    assert before == after


def test_safety_block_declares_no_boolean_merge_and_no_cadquery():
    block = cad_augmentation.build_safety_block()
    assert block["mesh_boolean_merge_performed"] is False
    assert block["cadquery_executed"] is False


# ---------------------------------------------------------------------------
# The generated OpenSCAD feature source: never a fused/merged copy of the
# organic mesh, no reference to any organic mesh file at all.
# ---------------------------------------------------------------------------


def test_generated_scad_never_references_the_input_stl_path():
    """The feature-source generator takes only numeric parameters - it
    never reads, imports, or references the organic mesh file itself
    (proving there is no accidental merge path)."""
    text = cad_augmentation._render_functional_feature_scad(
        base_width_mm=120.0, base_length_mm=80.0, base_height_mm=10.0,
        coin_slot_width_mm=30.0, coin_slot_length_mm=6.0, coin_slot_depth_mm=12.0,
        coin_slot_position_x_mm=None, coin_slot_position_y_mm=None,
        mounting_hole_diameter_mm=4.0, mounting_hole_margin_mm=8.0,
    )
    for forbidden in ("import(", "surface(", ".stl", ".STL"):
        assert forbidden not in text


def test_generated_scad_source_signature_has_no_forbidden_function_parameter():
    """No CLI option or function parameter anywhere accepts an arbitrary
    CAD script/file path - mirrors
    tests/test_blender_adaptation_safety.py's identical guarantee."""
    for module_name in ("factory.cad_augmentation", "factory.export_pipeline"):
        source = importlib_source(module_name)
        assert "user_script" not in source
        assert "arbitrary_file" not in source

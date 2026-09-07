"""Phase 48 safety tests: proves - not just asserts by inspection - that
`factory.hybrid_workflow` never launches Blender, never executes a CAD
backend, never invokes a slicer, never contacts a printer or network,
never overwrites an artifact, and never silently rescales or repairs a
mesh. Every plan/assessment function is pure planning: reading receipts
that already exist and computing a recommendation, nothing else.
"""

from __future__ import annotations

import ast
import importlib
import socket
import subprocess

import pytest

from factory import project_store
from factory.hybrid_workflow import assess_artifact_file, build_adaptation_plan

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
def meshy_project(isolated_projects_dir):
    root = project_store.init_project("Piggy Bank")
    artifact_dir = root / "generated" / "meshy" / "processed"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "01a07ca5.stl"
    artifact_path.write_text(_MINIMAL_STL)
    receipt = {
        "meshy_task_id": "01a07ca5-0c06-7459-b1f4-68f383774fae",
        "mock_execution": False, "live_api_used": True, "ai_model": "meshy-7",
        "validation_status": "WARN", "preview_status": "PASS",
        "output_artifact_paths": [str(artifact_path)],
    }
    project_store.save_json(root / "generated" / "meshy_receipt.json", receipt)
    return root, artifact_path


# ---------------------------------------------------------------------------
# Static AST scan: no subprocess/network-capable import anywhere in the module
# ---------------------------------------------------------------------------


def test_module_imports_no_subprocess_or_network_library():
    tree = ast.parse(open(importlib.import_module("factory.hybrid_workflow").__file__).read())
    forbidden = {"subprocess", "socket", "requests", "httpx", "aiohttp", "urllib"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(forbidden), f"hybrid_workflow.py imports forbidden module(s): {imported & forbidden}"


def test_module_never_imports_blender_or_cad_execution_modules():
    """This module may only ever *read* Blender's readiness gate
    (`factory.blender_gate.evaluate_blender_execution_gate`) - it must
    never import the module that actually invokes Blender via subprocess."""
    tree = ast.parse(open(importlib.import_module("factory.hybrid_workflow").__file__).read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "factory.blender_adapter" not in imported
    assert "factory.cad.backend" not in imported


# ---------------------------------------------------------------------------
# Behavioral proof: plan/assess still work with network/subprocess poisoned
# ---------------------------------------------------------------------------


def test_build_adaptation_plan_survives_poisoned_network_and_subprocess(meshy_project, monkeypatch):
    project_dir, _ = meshy_project

    def _boom(*a, **k):
        raise AssertionError("hybrid_workflow must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    plan = build_adaptation_plan(project_dir)
    assert plan["automatic_execution_allowed"] is False


def test_assess_artifact_file_survives_poisoned_network_and_subprocess(tmp_path, monkeypatch):
    stl_path = tmp_path / "sample.stl"
    stl_path.write_text(_MINIMAL_STL)

    def _boom(*a, **k):
        raise AssertionError("assess_artifact_file must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    result = assess_artifact_file(stl_path)
    assert result["error"] is None


# ---------------------------------------------------------------------------
# No artifact mutation
# ---------------------------------------------------------------------------


def test_build_adaptation_plan_never_modifies_the_artifact(meshy_project):
    project_dir, artifact_path = meshy_project
    before = artifact_path.read_bytes()
    build_adaptation_plan(project_dir)
    build_adaptation_plan(project_dir)  # twice, to also prove no accumulating side effect
    after = artifact_path.read_bytes()
    assert before == after


def test_build_adaptation_plan_never_writes_a_receipt_of_its_own(meshy_project):
    """Phase 48 is orchestration only - there is no hybrid_workflow_receipt
    writer yet, and none should appear on disk merely from planning."""
    project_dir, _ = meshy_project
    files_before = sorted(p.relative_to(project_dir) for p in project_dir.rglob("*") if p.is_file())
    build_adaptation_plan(project_dir)
    files_after = sorted(p.relative_to(project_dir) for p in project_dir.rglob("*") if p.is_file())
    assert files_before == files_after


def test_assess_artifact_file_never_modifies_the_file(tmp_path):
    stl_path = tmp_path / "sample.stl"
    stl_path.write_text(_MINIMAL_STL)
    before = stl_path.read_bytes()
    assess_artifact_file(stl_path)
    after = stl_path.read_bytes()
    assert before == after


# ---------------------------------------------------------------------------
# No silent scaling / no silent repair
# ---------------------------------------------------------------------------


def test_scale_assessment_always_requires_human_confirmation(meshy_project):
    project_dir, _ = meshy_project
    plan = build_adaptation_plan(project_dir)
    assert plan["scale_assessment"]["requires_human_confirmation"] is True
    # and no field anywhere in the plan claims a rescale actually happened
    assert "rescaled" not in str(plan).lower()
    assert "repaired" not in str(plan).lower()


def test_every_adaptation_step_is_marked_not_automatically_executable(meshy_project):
    project_dir, _ = meshy_project
    plan = build_adaptation_plan(project_dir)
    assert plan["automatic_execution_allowed"] is False
    for step in plan["adaptation_steps"]:
        assert step.get("automatic_execution_allowed") is False
        assert step.get("requires_human_confirmation") in (True, False)  # explicit field, never absent
        if step["step"] != "factory_validation":
            assert step["requires_human_confirmation"] is True


def test_no_automatic_print_flag_present(meshy_project):
    project_dir, _ = meshy_project
    plan = build_adaptation_plan(project_dir)
    assert plan["no_automatic_print"] is True

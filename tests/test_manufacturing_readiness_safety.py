"""Phase 52 safety tests: static/AST inspection proving
`factory.manufacturing_readiness` stays inside its safety contract -
aggregation only, never execution. No Meshy calls, no Blender launch, no
CAD execution, no slicer, no printer, no network, no geometry
modification. Mirrors `tests/test_design_review_safety.py`'s (Phase 51)
conventions exactly.
"""

from __future__ import annotations

import ast
import importlib
import socket
import subprocess

import pytest

from factory import manufacturing_readiness, project_store
from factory.design_review import _file_fingerprint

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
    meshy_dir = root / "generated" / "meshy" / "processed"
    meshy_dir.mkdir(parents=True, exist_ok=True)
    parent_path = meshy_dir / "abc.stl"
    parent_path.write_text(_MINIMAL_STL)

    adapted_dir = root / "generated" / "blender" / "adapted"
    adapted_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = adapted_dir / "abc_adapted.stl"
    artifact_path.write_text(_MINIMAL_STL)
    project_store.save_json(
        root / "generated" / "blender_adaptation_receipt.json",
        {
            "workflow": "organic_cleanup_workflow",
            "input_artifact": "generated/meshy/processed/abc.stl", "input_hash": _file_fingerprint(parent_path),
            "output_artifact": "generated/blender/adapted/abc_adapted.stl",
            "output_hash": _file_fingerprint(artifact_path),
            "single_shot_human_confirmation": True, "validation_status": "PASS",
        },
    )
    return root


def importlib_source(module_name: str) -> str:
    return open(importlib.import_module(module_name).__file__, encoding="utf-8").read()


# ---------------------------------------------------------------------------
# factory.manufacturing_readiness never imports subprocess/network or any
# of the real execution modules (blender_adapter, cad execution, meshy
# transport, slicer probes, cadquery).
# ---------------------------------------------------------------------------


def test_module_imports_no_subprocess_or_network_library():
    tree = ast.parse(importlib_source("factory.manufacturing_readiness"))
    forbidden = {"subprocess", "socket", "requests", "httpx", "aiohttp", "urllib"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(forbidden), f"manufacturing_readiness.py imports forbidden module(s): {imported & forbidden}"


def test_module_never_imports_real_execution_modules():
    """This module may only ever *read* the outputs of other aggregation
    modules - it must never import factory.blender_adapter (Blender
    execution), factory.export_pipeline/factory.cad_augmentation's own
    execution internals, cadquery, or any Meshy transport module."""
    tree = ast.parse(importlib_source("factory.manufacturing_readiness"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    forbidden_modules = {
        "factory.blender_adapter",
        "factory.export_pipeline",
        "factory.meshy_http_transport",
        "factory.meshy_live_adapter",
        "factory.meshy_mock_transport",
        "cadquery",
    }
    assert imported.isdisjoint(forbidden_modules), f"forbidden import(s): {imported & forbidden_modules}"


def test_no_desktop_or_slicer_automation_patterns():
    text = importlib_source("factory.manufacturing_readiness")
    for pattern in ('os.system(', 'subprocess.Popen(', '"osascript"', "'osascript'", "bpy", "cq.Workplane", "cadquery.Workplane"):
        assert pattern not in text


# ---------------------------------------------------------------------------
# Behavioral proof: evaluation survives poisoned network/subprocess
# ---------------------------------------------------------------------------


def test_evaluate_survives_poisoned_network_and_subprocess(blender_adapted_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("manufacturing readiness must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    report = manufacturing_readiness.evaluate_manufacturing_readiness(blender_adapted_project)
    assert report["automatic_print_allowed"] is False


# ---------------------------------------------------------------------------
# No geometry modification, no writes at all
# ---------------------------------------------------------------------------


def test_evaluate_never_modifies_any_receipt_or_artifact(blender_adapted_project):
    receipt_path = blender_adapted_project / "generated" / "blender_adaptation_receipt.json"
    files_before = {
        p: p.read_bytes() for p in blender_adapted_project.rglob("*") if p.is_file()
    }

    manufacturing_readiness.evaluate_manufacturing_readiness(blender_adapted_project)
    manufacturing_readiness.evaluate_manufacturing_readiness(blender_adapted_project)

    files_after = {p: p.read_bytes() for p in blender_adapted_project.rglob("*") if p.is_file()}
    assert files_before == files_after
    assert receipt_path in files_after


def test_evaluate_writes_no_new_files(blender_adapted_project):
    files_before = set(p for p in blender_adapted_project.rglob("*") if p.is_file())
    manufacturing_readiness.evaluate_manufacturing_readiness(blender_adapted_project)
    files_after = set(p for p in blender_adapted_project.rglob("*") if p.is_file())
    assert files_before == files_after


def test_build_safety_block_declares_no_execution():
    block = manufacturing_readiness.build_safety_block()
    assert block["blender_launched"] is False
    assert block["cad_executed"] is False
    assert block["meshy_contacted"] is False
    assert block["slicer_executed"] is False
    assert block["printer_contacted"] is False
    assert block["network_used"] is False
    assert block["geometry_modified"] is False
    assert block["gcode_generated"] is False
    assert block["automatic_print_allowed"] is False
    assert block["automatic_approval_granted"] is False


def test_readiness_states_respect_the_repo_wide_automation_ceiling():
    """Matches config/agent_policy.json's status_gates.max_automatic_status
    - no state in this ladder is ever at or beyond 'approved_for_print'."""
    forbidden = {"approved_for_print", "automatic_manufacture_ready", "print_ready", "human_approved", "slicer_review_ready"}
    assert forbidden.isdisjoint(set(manufacturing_readiness.READINESS_STATES))

"""Phase 51 safety tests: static/AST inspection proving
`factory.design_review` stays inside its safety contract - review only,
never execution. No Meshy calls, no Blender launch, no CAD execution, no
slicer, no printer, no network, no geometry modification. Mirrors
`tests/test_cad_augmentation_safety.py`'s (Phase 50) and
`tests/test_hybrid_workflow_safety.py`'s (Phase 48) conventions exactly.
See docs/design-review.md.
"""

from __future__ import annotations

import ast
import importlib
import socket
import subprocess

import pytest

from factory import design_review, project_store

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
    artifact_path = adapted_dir / "abc_adapted.stl"
    artifact_path.write_text(_MINIMAL_STL)
    project_store.save_json(
        root / "generated" / "blender_adaptation_receipt.json",
        {
            "workflow": "organic_cleanup_workflow",
            "input_artifact": "generated/meshy/processed/abc.stl", "input_hash": "sha256:x",
            "output_artifact": "generated/blender/adapted/abc_adapted.stl",
            "output_hash": design_review._file_fingerprint(artifact_path),
            "single_shot_human_confirmation": True, "validation_status": "PASS",
        },
    )
    return root, artifact_path


def importlib_source(module_name: str) -> str:
    return open(importlib.import_module(module_name).__file__, encoding="utf-8").read()


# ---------------------------------------------------------------------------
# factory.design_review never imports subprocess/network or any of the
# real execution modules (blender_adapter, cad execution, meshy transport,
# slicer probes).
# ---------------------------------------------------------------------------


def test_module_imports_no_subprocess_or_network_library():
    tree = ast.parse(importlib_source("factory.design_review"))
    forbidden = {"subprocess", "socket", "requests", "httpx", "aiohttp", "urllib"}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(forbidden), f"design_review.py imports forbidden module(s): {imported & forbidden}"


def test_module_never_imports_real_execution_modules():
    """This module may only ever *read* receipts/summaries - it must
    never import factory.blender_adapter (Blender execution),
    factory.export_pipeline (OpenSCAD execution), cadquery, or any Meshy
    transport module."""
    tree = ast.parse(importlib_source("factory.design_review"))
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
    text = importlib_source("factory.design_review")
    for pattern in ('os.system(', 'subprocess.Popen(', '"osascript"', "'osascript'", "bpy", "cq.Workplane", "cadquery.Workplane"):
        assert pattern not in text


# ---------------------------------------------------------------------------
# Behavioral proof: review survives poisoned network/subprocess
# ---------------------------------------------------------------------------


def test_evaluate_survives_poisoned_network_and_subprocess(blender_adapted_project, monkeypatch):
    project_dir, _ = blender_adapted_project

    def _boom(*a, **k):
        raise AssertionError("design review must never touch network or subprocess")

    monkeypatch.setattr(socket, "socket", _boom)
    monkeypatch.setattr(subprocess, "run", _boom)
    monkeypatch.setattr(subprocess, "Popen", _boom)

    review = design_review.evaluate_design_review(project_dir)
    assert review["automatic_print_allowed"] is False


# ---------------------------------------------------------------------------
# No geometry modification, no overwrite of an execution receipt
# ---------------------------------------------------------------------------


def test_evaluate_never_modifies_any_receipt_or_artifact(blender_adapted_project):
    project_dir, artifact_path = blender_adapted_project
    receipt_path = project_dir / "generated" / "blender_adaptation_receipt.json"
    artifact_before = artifact_path.read_bytes()
    receipt_before = receipt_path.read_bytes()

    design_review.evaluate_design_review(project_dir)
    design_review.evaluate_design_review(project_dir)

    assert artifact_path.read_bytes() == artifact_before
    assert receipt_path.read_bytes() == receipt_before


def test_save_report_never_overwrites_an_execution_receipt(blender_adapted_project):
    project_dir, _ = blender_adapted_project
    receipt_path = project_dir / "generated" / "blender_adaptation_receipt.json"
    receipt_before = receipt_path.read_bytes()

    report_path = design_review.save_design_review_report(project_dir)

    assert report_path.name == "design_review_report.json"
    assert report_path != receipt_path
    assert receipt_path.read_bytes() == receipt_before


def test_report_filename_is_distinct_from_every_execution_receipt():
    assert design_review.REPORT_FILENAME not in ("blender_adaptation_receipt.json", "cad_augmentation_receipt.json", "meshy_receipt.json", "export_receipt.json", "generation_receipt.json")


def test_build_safety_block_declares_no_execution():
    block = design_review.build_safety_block()
    assert block["blender_launched"] is False
    assert block["cad_executed"] is False
    assert block["meshy_contacted"] is False
    assert block["geometry_modified"] is False
    assert block["automatic_print_allowed"] is False
    assert block["automatic_approval_granted"] is False

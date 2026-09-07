"""Phase 48 tests: `factory.hybrid_workflow` - the planning layer between a
generative-AI/CAD artifact and manufacturing-ready Factory output. Every
plan/assessment function here is read-only - no test in this file ever
invokes Blender, a CAD backend, a slicer, or a printer, and none ever
rescales or repairs a mesh file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from factory import export_pipeline, project_store
from factory.openscad.generate import generate_openscad
from factory.hybrid_workflow import (
    ARTIFACT_TYPES,
    MANUFACTURING_READINESS_STATES,
    WORKFLOW_TYPES,
    assess_artifact_file,
    assess_manufacturing_intent,
    assess_scale,
    build_adaptation_plan,
    build_adaptation_plan_for_path,
    route_tools,
    summarize_hybrid_workflow,
)

FAKE_OPENSCAD = "/fake/bin/openscad"

# A minimal, genuinely valid watertight triangle-pair STL - the same
# fixture style `tests/test_meshy_live_adapter.py` already uses.
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
def scad_project(isolated_projects_dir):
    root = project_store.init_project("Demo Sign")
    generate_openscad(root, "sign", "Hi")
    return root


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _export_cad_project(project_dir, monkeypatch):
    monkeypatch.setattr(export_pipeline, "resolve_openscad_executable", lambda: FAKE_OPENSCAD)

    def _fake_run(command, capture_output, text, timeout):
        if "--version" in command:
            return _FakeCompleted(returncode=0, stdout="OpenSCAD version 2021.01 (fake)")
        output_path = Path(command[2])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_MINIMAL_STL)
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(export_pipeline.subprocess, "run", _fake_run)
    plan = export_pipeline.plan_export(project_dir, confirm_export=True)
    return export_pipeline.run_export_pipeline(project_dir, plan, all_steps=True)


def _write_meshy_receipt(project_dir: Path, *, stl_bytes: str = _MINIMAL_STL, **overrides) -> Path:
    artifact_dir = project_dir / "generated" / "meshy" / "processed"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "01a07ca5.stl"
    artifact_path.write_text(stl_bytes)

    receipt = {
        "meshy_task_id": "01a07ca5-0c06-7459-b1f4-68f383774fae",
        "mock_execution": False,
        "live_api_used": True,
        "ai_model": "meshy-7",
        "consumed_credits": 20,
        "validation_status": "WARN",
        "preview_status": "PASS",
        "output_artifact_paths": [str(artifact_path)],
    }
    receipt.update(overrides)
    generated_dir = project_dir / "generated"
    generated_dir.mkdir(parents=True, exist_ok=True)
    project_store.save_json(generated_dir / "meshy_receipt.json", receipt)
    return artifact_path


def _set_design_intent(project_dir: Path, *, use_case=None, max_size_mm=None):
    brief_path = project_dir / "brief.json"
    brief = project_store.load_json(brief_path)
    design_intent = {}
    if use_case is not None:
        design_intent["use_case"] = use_case
    if max_size_mm is not None:
        design_intent["manufacturability_constraints"] = {"max_size_mm": max_size_mm}
    brief["design_intent"] = design_intent
    project_store.save_json(brief_path, brief)


# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------


def test_workflow_types_include_minimum_useful_set():
    for expected in (
        "organic_concept_to_print", "mechanical_part_refinement", "hybrid_organic_mechanical",
        "replacement_part_reconstruction", "functional_product_design", "decorative_collectible", "unknown",
    ):
        assert expected in WORKFLOW_TYPES


def test_artifact_types_and_readiness_states_are_closed_vocabularies():
    assert "meshy_organic" in ARTIFACT_TYPES
    assert "cad_mechanical" in ARTIFACT_TYPES
    assert "ready" not in MANUFACTURING_READINESS_STATES  # never claims outright "ready" - human review always required


# ---------------------------------------------------------------------------
# No input artifact
# ---------------------------------------------------------------------------


def test_no_artifact_produces_unknown_workflow_and_no_steps(scad_project):
    plan = build_adaptation_plan(scad_project.parent / "nonexistent-project")
    assert plan["artifact_type"] == "none"
    assert plan["workflow_type"] == "unknown"
    assert plan["adaptation_steps"] == []
    assert plan["automatic_execution_allowed"] is False
    assert plan["manufacturing_readiness"] == "unknown"


# ---------------------------------------------------------------------------
# Meshy organic artifact (the piggy-bank motivating example)
# ---------------------------------------------------------------------------


def test_meshy_organic_artifact_recommends_blender(scad_project):
    """A real project with no brief.json is created by init_project(), so
    this exercises the missing-design-intent path too."""
    _write_meshy_receipt(scad_project)
    plan = build_adaptation_plan(scad_project)
    assert plan["artifact_type"] == "meshy_organic"
    assert plan["recommended_engine"] == "blender"
    assert any(step["tool"] == "blender" for step in plan["adaptation_steps"])
    assert plan["automatic_execution_allowed"] is False


def test_meshy_organic_artifact_with_no_design_intent_flags_missing_metadata(scad_project):
    _write_meshy_receipt(scad_project)
    plan = build_adaptation_plan(scad_project)
    assert any("No design_intent recorded" in issue for issue in plan["issues_found"])


def test_meshy_organic_artifact_scale_warning_when_bbox_implausible(scad_project):
    """The real piggy-bank artifact's ~1.9m bounding box against a 150mm
    figurine-scale expectation should be flagged implausible, never
    silently accepted or rescaled."""
    _write_meshy_receipt(scad_project)
    _set_design_intent(scad_project, use_case="figurine", max_size_mm=[150, 150, 150])
    plan = build_adaptation_plan(scad_project)
    scale = plan["scale_assessment"]
    assert scale["expected_dimensions_mm"] is not None
    assert scale["requires_human_confirmation"] is True
    # our minimal fixture STL is tiny (1mm-scale), so against a 150mm
    # expectation the ratio is far below 0.5 - also implausible, just in
    # the opposite direction from the real piggy bank. Either direction
    # must be flagged.
    assert scale["implausible"] is True
    assert any("scale_not_manufacturing_ready" in issue for issue in plan["issues_found"])


def test_scale_assessment_never_sets_a_scale_factor_without_evidence():
    result = assess_scale({"bounding_box_mm": {"x": 100, "y": 100, "z": 100}}, use_case=None, design_intent_max_size_mm=None)
    assert result["expected_dimensions_mm"] is None
    assert result["scale_factor"] is None
    assert result["confidence"] == "unknown"
    assert result["requires_human_confirmation"] is True


def test_scale_assessment_uses_declared_design_intent_as_high_confidence():
    result = assess_scale({"bounding_box_mm": {"x": 120, "y": 40, "z": 5}}, use_case=None, design_intent_max_size_mm=[120, 40, 5])
    assert result["confidence"] == "high"
    assert result["implausible"] is False


def test_scale_assessment_use_case_hint_is_low_confidence_and_never_universal():
    result = assess_scale({"bounding_box_mm": {"x": 150, "y": 150, "z": 150}}, use_case="a desk object for my office", design_intent_max_size_mm=None)
    assert result["confidence"] == "low"
    assert result["expected_dimensions_mm"] == {"min_mm": 50.0, "max_mm": 300.0}


# ---------------------------------------------------------------------------
# Mechanical (CAD-origin) artifact
# ---------------------------------------------------------------------------


def test_cad_mechanical_artifact_recommends_cad_not_blender(scad_project, monkeypatch):
    _export_cad_project(scad_project, monkeypatch)
    plan = build_adaptation_plan(scad_project)
    assert plan["artifact_type"] == "cad_mechanical"
    assert plan["recommended_engine"] == "cad"
    assert plan["workflow_type"] == "mechanical_part_refinement"
    assert not any(step.get("tool") == "blender" for step in plan["adaptation_steps"])


def test_cad_functional_intent_classifies_as_functional_product_design(scad_project, monkeypatch):
    _export_cad_project(scad_project, monkeypatch)
    _set_design_intent(scad_project, use_case="a functional mounting bracket")
    plan = build_adaptation_plan(scad_project)
    assert plan["workflow_type"] == "functional_product_design"


# ---------------------------------------------------------------------------
# Hybrid organic+mechanical artifact
# ---------------------------------------------------------------------------


def test_meshy_artifact_with_mechanical_intent_is_hybrid_workflow(scad_project):
    _write_meshy_receipt(scad_project)
    _set_design_intent(scad_project, use_case="a mechanical assembly with a hinge")
    plan = build_adaptation_plan(scad_project)
    assert plan["workflow_type"] == "hybrid_organic_mechanical"
    tools = [step.get("tool") for step in plan["adaptation_steps"]]
    assert "blender" in tools
    assert any(step["step"] == "cad_mechanical_augmentation" for step in plan["adaptation_steps"])


def test_replacement_part_intent_classifies_correctly(scad_project):
    _write_meshy_receipt(scad_project)
    _set_design_intent(scad_project, use_case="a replacement part for a broken handle")
    plan = build_adaptation_plan(scad_project)
    assert plan["workflow_type"] == "replacement_part_reconstruction"


# ---------------------------------------------------------------------------
# Manufacturing intent
# ---------------------------------------------------------------------------


def test_manufacturing_intent_always_requires_human_confirmation():
    result = assess_manufacturing_intent(use_case="a classroom teaching aid", artifact_type="cad_mechanical")
    assert result["requires_human_confirmation"] is True
    assert "educational" in result["candidate_intents"]


def test_manufacturing_intent_unknown_when_no_signal():
    result = assess_manufacturing_intent(use_case=None, artifact_type="cad_mechanical")
    assert result["candidate_intents"] == []
    assert result["confidence"] == "unknown"


# ---------------------------------------------------------------------------
# Tool routing (reuses engine_registry/blender_gate - never a second selector)
# ---------------------------------------------------------------------------


def test_route_tools_organic_uses_blender_gate_verbatim():
    routing = route_tools(workflow_type="organic_concept_to_print")
    step = next(s for s in routing["steps"] if s["step"] == "blender_organic_adaptation")
    assert "engine_gate_status" in step
    assert step["engine_project_execution_approved"] is False  # Blender project execution is not approved yet
    assert step["automatic_execution_allowed"] is False


def test_route_tools_mechanical_recommends_known_cad_tools_only():
    routing = route_tools(workflow_type="mechanical_part_refinement")
    step = next(s for s in routing["steps"] if s["step"] == "cad_mechanical_augmentation")
    for tool_id in step["candidate_tools"]:
        assert tool_id in ("cadquery", "openscad_stable", "freecad")


def test_route_tools_unknown_recommends_nothing_specific():
    routing = route_tools(workflow_type="unknown")
    assert routing["recommended_engine"] is None


# ---------------------------------------------------------------------------
# JSON-cleanliness and standalone artifact assessment
# ---------------------------------------------------------------------------


def test_plan_is_json_serializable(scad_project):
    import json

    _write_meshy_receipt(scad_project)
    plan = build_adaptation_plan(scad_project)
    json.dumps(plan)  # must not raise


def test_build_adaptation_plan_for_path_matches_build_adaptation_plan(scad_project):
    _write_meshy_receipt(scad_project)
    assert build_adaptation_plan_for_path(scad_project) == build_adaptation_plan(scad_project)


def test_assess_artifact_file_missing_file_reports_error(tmp_path):
    result = assess_artifact_file(tmp_path / "does_not_exist.stl")
    assert result["error"] == "file_not_found"
    assert result["scale_assessment"] is None


def test_assess_artifact_file_valid_mesh(tmp_path):
    stl_path = tmp_path / "sample.stl"
    stl_path.write_text(_MINIMAL_STL)
    result = assess_artifact_file(stl_path)
    assert result["error"] is None
    assert result["mesh_stats"]["is_watertight"] is True
    assert result["scale_assessment"]["requires_human_confirmation"] is True


# ---------------------------------------------------------------------------
# Preview board summary
# ---------------------------------------------------------------------------


def test_summarize_hybrid_workflow_no_artifact(scad_project):
    empty_project = scad_project.parent / "empty"
    empty_project.mkdir()
    summary = summarize_hybrid_workflow(empty_project)
    assert summary["plan_available"] is False
    assert summary["manufacturing_readiness"] == "unknown"


def test_summarize_hybrid_workflow_with_artifact(scad_project):
    _write_meshy_receipt(scad_project)
    summary = summarize_hybrid_workflow(scad_project)
    assert summary["plan_available"] is True
    assert summary["recommended_engine"] == "blender"
    assert summary["issue_count"] > 0

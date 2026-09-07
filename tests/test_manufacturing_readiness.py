"""Phase 52 tests: `factory.manufacturing_readiness.evaluate_manufacturing_readiness()`.
A pipeline-agnostic aggregation over `factory.design_review` (hybrid) and
`factory.project_health` (traditional) - never a second scoring/validation
system. Mirrors `tests/test_design_review.py`'s (Phase 51) conventions.
"""

from __future__ import annotations

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
    """A hybrid-pipeline project: Meshy->Blender chain present and
    lineage-consistent (the recorded parent artifact actually exists on
    disk with a matching fingerprint), but no brief.json/build_plan.json/
    part_manifest.json - a good fixture for 'missing printer'/'missing
    material'/'needs_information' cases without a lineage blocker
    interfering."""
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


@pytest.fixture()
def fresh_project(isolated_projects_dir):
    """No artifact chain, no brief, no CAD - the earliest possible state."""
    return project_store.init_project("Nothing Yet")


def test_fresh_project_is_not_ready(fresh_project):
    report = manufacturing_readiness.evaluate_manufacturing_readiness(fresh_project)
    assert report["readiness_state"] == "not_ready"
    assert report["artifact_status"] == "absent"
    assert report["pipeline"] == "traditional"
    assert report["automatic_print_allowed"] is False
    assert report["blockers"] == []


def test_hybrid_chain_reports_hybrid_pipeline_and_needs_information(blender_adapted_project):
    report = manufacturing_readiness.evaluate_manufacturing_readiness(blender_adapted_project)
    assert report["pipeline"] == "hybrid"
    assert report["artifact_status"] in ("present", "partial")
    # No brief.json, no build_plan.json, no part_manifest.json - core design
    # confirmations (design intent, manufacturing purpose) are missing.
    assert report["readiness_state"] == "needs_information"
    assert report["design_status"] == "needs_information"
    assert report["manufacturing_status"] == "needs_information"


def test_missing_printer_is_needs_information_not_a_blocker(blender_adapted_project):
    report = manufacturing_readiness.evaluate_manufacturing_readiness(blender_adapted_project)
    assert report["printer_status"] == "needs_information"
    assert "printer_selected" in report["missing_requirements"]
    assert not any("printer" in b["message"].lower() for b in report["blockers"])


def test_missing_material_reported_honestly(blender_adapted_project):
    """No part_manifest.json means zero parts - the same 'vacuously
    confirmed' rule factory.design_review already established (no parts
    means nothing is unresolved) is reused verbatim here, not re-derived."""
    report = manufacturing_readiness.evaluate_manufacturing_readiness(blender_adapted_project)
    assert report["material_status"] in ("confirmed", "needs_information")
    assert report["material_summary"]["part_count"] == 0


def test_failed_geometry_validation_is_a_blocker(isolated_projects_dir):
    """A Blender-adapted artifact that fails mesh validation (not a valid
    STL) must surface as a blocker via factory.design_review's own
    geometry blocker rule - reused, never re-validated here."""
    root = project_store.init_project("Broken Mesh")
    adapted_dir = root / "generated" / "blender" / "adapted"
    adapted_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = adapted_dir / "broken.stl"
    artifact_path.write_text("not a valid stl file")
    project_store.save_json(
        root / "generated" / "blender_adaptation_receipt.json",
        {
            "workflow": "organic_cleanup_workflow",
            "input_artifact": "generated/meshy/processed/abc.stl", "input_hash": "sha256:x",
            "output_artifact": "generated/blender/adapted/broken.stl",
            "output_hash": _file_fingerprint(artifact_path),
            "single_shot_human_confirmation": True, "validation_status": "FAIL",
        },
    )
    report = manufacturing_readiness.evaluate_manufacturing_readiness(root)
    assert report["readiness_state"] == "blocked"
    assert report["blockers"]
    assert report["geometry_status"] == "failed"


def test_missing_lineage_broken_link_is_a_blocker(isolated_projects_dir):
    """A blender_adaptation receipt whose recorded input artifact no
    longer exists is a broken-lineage blocker - reused directly from
    factory.design_review's own `_resolve_artifact_chain()` check."""
    root = project_store.init_project("Broken Lineage")
    adapted_dir = root / "generated" / "blender" / "adapted"
    adapted_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = adapted_dir / "abc_adapted.stl"
    artifact_path.write_text(_MINIMAL_STL)
    project_store.save_json(
        root / "generated" / "blender_adaptation_receipt.json",
        {
            "workflow": "organic_cleanup_workflow",
            "input_artifact": "generated/meshy/processed/does_not_exist.stl", "input_hash": "sha256:deadbeef",
            "output_artifact": "generated/blender/adapted/abc_adapted.stl",
            "output_hash": _file_fingerprint(artifact_path),
            "single_shot_human_confirmation": True, "validation_status": "PASS",
        },
    )
    report = manufacturing_readiness.evaluate_manufacturing_readiness(root)
    assert report["readiness_state"] == "blocked"
    assert any(b["source"] == "lineage" for b in report["blockers"])


def test_readiness_states_never_include_forbidden_names():
    forbidden = {"approved_for_print", "automatic_manufacture_ready", "print_ready", "human_approved"}
    assert forbidden.isdisjoint(set(manufacturing_readiness.READINESS_STATES))


def test_readiness_score_never_overrides_a_blocker(isolated_projects_dir):
    """A project with a hard blocker must report readiness_state ==
    'blocked' regardless of how high its readiness_score happens to be."""
    root = project_store.init_project("High Score Blocked")
    adapted_dir = root / "generated" / "blender" / "adapted"
    adapted_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = adapted_dir / "broken.stl"
    artifact_path.write_text("not a valid stl file")
    project_store.save_json(
        root / "generated" / "blender_adaptation_receipt.json",
        {
            "workflow": "organic_cleanup_workflow",
            "input_artifact": "generated/meshy/processed/abc.stl", "input_hash": "sha256:x",
            "output_artifact": "generated/blender/adapted/broken.stl",
            "output_hash": _file_fingerprint(artifact_path),
            "single_shot_human_confirmation": True, "validation_status": "FAIL",
        },
    )
    report = manufacturing_readiness.evaluate_manufacturing_readiness(root)
    assert report["blockers"]
    assert report["readiness_state"] == "blocked"


def test_blockers_and_warnings_are_tagged_by_pipeline(blender_adapted_project):
    report = manufacturing_readiness.evaluate_manufacturing_readiness(blender_adapted_project)
    for entry in report["blockers"] + report["warnings"]:
        assert entry["pipeline"] in ("hybrid", "traditional", "shared")
        assert "source" in entry and "message" in entry


def test_completed_and_missing_requirements_partition_the_checklist(blender_adapted_project):
    report = manufacturing_readiness.evaluate_manufacturing_readiness(blender_adapted_project)
    checklist_items = {c["item"] for c in report["human_confirmation_checklist"]}
    assert set(report["completed_requirements"]) | set(report["missing_requirements"]) == checklist_items
    assert set(report["completed_requirements"]).isdisjoint(set(report["missing_requirements"]))


def test_scoring_weights_documented_for_hybrid_pipeline(blender_adapted_project):
    report = manufacturing_readiness.evaluate_manufacturing_readiness(blender_adapted_project)
    assert report["readiness_score_source"] == "design_review"
    assert abs(sum(report["readiness_score_weights"].values()) - 1.0) < 1e-9


def test_automatic_print_allowed_is_always_false(blender_adapted_project, fresh_project):
    for project in (blender_adapted_project, fresh_project):
        report = manufacturing_readiness.evaluate_manufacturing_readiness(project)
        assert report["automatic_print_allowed"] is False
        assert report["no_geometry_modified"] is True


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


def test_summarize_manufacturing_readiness_is_compact(blender_adapted_project):
    summary = manufacturing_readiness.summarize_manufacturing_readiness(blender_adapted_project)
    assert summary["available"] is True
    assert summary["readiness_state"] in manufacturing_readiness.READINESS_STATES
    assert isinstance(summary["top_blockers"], list) and len(summary["top_blockers"]) <= 2
    assert isinstance(summary["top_warnings"], list) and len(summary["top_warnings"]) <= 2

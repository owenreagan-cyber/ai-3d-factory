"""Phase 51 tests: `factory.design_review` - artifact chain resolution,
per-category scoring, readiness-state determination, human checkpoints,
recommended actions, and the optional read-only snapshot. See
docs/design-review.md.
"""

from __future__ import annotations

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
def empty_project(isolated_projects_dir):
    return project_store.init_project("Empty Project")


@pytest.fixture()
def meshy_only_project(isolated_projects_dir):
    root = project_store.init_project("Meshy Only")
    artifact_dir = root / "generated" / "meshy" / "processed"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "abc123.stl"
    artifact_path.write_text(_MINIMAL_STL)
    project_store.save_json(
        root / "generated" / "meshy_receipt.json",
        {
            "meshy_task_id": "abc123",
            "mock_execution": False,
            "live_api_used": True,
            "output_artifact_paths": [str(artifact_path)],
            "validation_status": "WARN",
        },
    )
    return root, artifact_path


@pytest.fixture()
def blender_only_project(isolated_projects_dir):
    """blender_adaptation_receipt.json present with no real meshy_receipt.json."""
    root = project_store.init_project("Blender Only")
    adapted_dir = root / "generated" / "blender" / "adapted"
    adapted_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = adapted_dir / "abc123_adapted.stl"
    artifact_path.write_text(_MINIMAL_STL)
    fingerprint = design_review._file_fingerprint(artifact_path)
    project_store.save_json(
        root / "generated" / "blender_adaptation_receipt.json",
        {
            "workflow": "organic_cleanup_workflow",
            "input_artifact": "generated/meshy/processed/abc123.stl",
            "input_hash": "sha256:doesnotmatter",
            "output_artifact": "generated/blender/adapted/abc123_adapted.stl",
            "output_hash": fingerprint,
            "scale_factor_applied": 0.1,
            "target_max_dimension_mm": 100.0,
            "single_shot_human_confirmation": True,
            "validation_status": "PASS",
        },
    )
    return root, artifact_path


@pytest.fixture()
def cad_only_project(isolated_projects_dir):
    """cad_augmentation_receipt.json present with no meshy/blender receipts -
    e.g. a CAD feature generated directly against some other mesh."""
    root = project_store.init_project("CAD Only")
    input_dir = root / "stl"
    input_dir.mkdir(parents=True, exist_ok=True)
    input_path = input_dir / "some_mesh.stl"
    input_path.write_text(_MINIMAL_STL)
    input_hash = design_review._file_fingerprint(input_path)

    feature_dir = root / "generated" / "cad_augmentation"
    feature_dir.mkdir(parents=True, exist_ok=True)
    feature_path = feature_dir / "some_mesh_feature.stl"
    feature_path.write_text(_MINIMAL_STL)
    output_hash = design_review._file_fingerprint(feature_path)

    project_store.save_json(
        root / "generated" / "cad_augmentation_receipt.json",
        {
            "workflow": "organic_mechanical_augmentation",
            "input_artifact": "stl/some_mesh.stl",
            "input_hash": input_hash,
            "output_artifact": "generated/cad_augmentation/some_mesh_feature.stl",
            "output_hash": output_hash,
            "cad_engine": "openscad_stable",
            "parameters": {"base_width_mm": 100.0, "base_length_mm": 80.0, "base_height_mm": 10.0},
            "single_shot_human_confirmation": True,
            "validation_status": "PASS",
        },
    )
    return root, feature_path


@pytest.fixture()
def full_hybrid_project(isolated_projects_dir):
    """A complete Meshy -> Blender -> CAD chain, all fingerprints
    consistent."""
    root = project_store.init_project("Piggy Bank")

    meshy_dir = root / "generated" / "meshy" / "processed"
    meshy_dir.mkdir(parents=True, exist_ok=True)
    meshy_path = meshy_dir / "task1.stl"
    meshy_path.write_text(_MINIMAL_STL)
    meshy_hash = design_review._file_fingerprint(meshy_path)
    project_store.save_json(
        root / "generated" / "meshy_receipt.json",
        {
            "meshy_task_id": "task1", "mock_execution": False, "live_api_used": True,
            "output_artifact_paths": [str(meshy_path)], "artifact_fingerprint": meshy_hash,
            "validation_status": "WARN",
        },
    )

    adapted_dir = root / "generated" / "blender" / "adapted"
    adapted_dir.mkdir(parents=True, exist_ok=True)
    adapted_path = adapted_dir / "task1_adapted.stl"
    adapted_path.write_text(_MINIMAL_STL)
    adapted_hash = design_review._file_fingerprint(adapted_path)
    project_store.save_json(
        root / "generated" / "blender_adaptation_receipt.json",
        {
            "workflow": "organic_cleanup_workflow",
            "input_artifact": "generated/meshy/processed/task1.stl", "input_hash": meshy_hash,
            "output_artifact": "generated/blender/adapted/task1_adapted.stl", "output_hash": adapted_hash,
            "scale_factor_applied": 0.1, "target_max_dimension_mm": 150.0,
            "single_shot_human_confirmation": True, "validation_status": "PASS",
        },
    )

    feature_dir = root / "generated" / "cad_augmentation"
    feature_dir.mkdir(parents=True, exist_ok=True)
    feature_path = feature_dir / "task1_adapted_feature.stl"
    feature_path.write_text(_MINIMAL_STL)
    feature_hash = design_review._file_fingerprint(feature_path)
    project_store.save_json(
        root / "generated" / "cad_augmentation_receipt.json",
        {
            "workflow": "organic_mechanical_augmentation",
            "input_artifact": "generated/blender/adapted/task1_adapted.stl", "input_hash": adapted_hash,
            "output_artifact": "generated/cad_augmentation/task1_adapted_feature.stl", "output_hash": feature_hash,
            "cad_engine": "openscad_stable",
            "parameters": {"base_width_mm": 120.0, "base_length_mm": 80.0, "base_height_mm": 10.0, "coin_slot_width_mm": 30.0},
            "single_shot_human_confirmation": True, "validation_status": "PASS",
        },
    )
    return root


# ---------------------------------------------------------------------------
# Artifact chain resolution
# ---------------------------------------------------------------------------


def test_empty_project_has_no_artifact_chain(empty_project):
    chain = design_review._resolve_artifact_chain(empty_project)
    assert chain["any_stage_present"] is False
    assert chain["organic_artifact_path"] is None
    assert chain["mechanical_artifact_path"] is None


def test_meshy_only_chain(meshy_only_project):
    root, artifact_path = meshy_only_project
    chain = design_review._resolve_artifact_chain(root)
    assert chain["stages"][0]["present"] is True
    assert chain["stages"][1]["present"] is False
    assert chain["stages"][2]["present"] is False
    assert chain["organic_source"] == "meshy"
    assert chain["mechanical_artifact_path"] is None


def test_blender_only_chain(blender_only_project):
    root, artifact_path = blender_only_project
    chain = design_review._resolve_artifact_chain(root)
    assert chain["stages"][0]["present"] is False
    assert chain["stages"][1]["present"] is True
    assert chain["organic_source"] == "blender_adapted"
    assert chain["organic_artifact_path"] == str(artifact_path)


def test_cad_only_chain(cad_only_project):
    root, feature_path = cad_only_project
    chain = design_review._resolve_artifact_chain(root)
    assert chain["stages"][0]["present"] is False
    assert chain["stages"][1]["present"] is False
    assert chain["stages"][2]["present"] is True
    assert chain["organic_source"] == "unknown_origin"
    assert chain["mechanical_artifact_path"] == str(feature_path)


def test_full_hybrid_chain_is_consistent(full_hybrid_project):
    chain = design_review._resolve_artifact_chain(full_hybrid_project)
    assert all(s["present"] for s in chain["stages"])
    assert chain["chain_consistent"] is True
    assert chain["broken_links"] == []


def test_broken_lineage_detected_when_parent_file_changes(full_hybrid_project):
    # Mutate the meshy artifact after the chain was recorded - its
    # fingerprint no longer matches blender_adaptation_receipt's input_hash.
    meshy_path = full_hybrid_project / "generated" / "meshy" / "processed" / "task1.stl"
    meshy_path.write_text(_MINIMAL_STL + "\n// mutated\n")
    chain = design_review._resolve_artifact_chain(full_hybrid_project)
    assert chain["chain_consistent"] is False
    assert chain["broken_links"] != []


def test_broken_lineage_detected_when_parent_file_missing(full_hybrid_project):
    meshy_path = full_hybrid_project / "generated" / "meshy" / "processed" / "task1.stl"
    meshy_path.unlink()
    chain = design_review._resolve_artifact_chain(full_hybrid_project)
    assert chain["chain_consistent"] is False


# ---------------------------------------------------------------------------
# Full evaluate_design_review() - end to end per scenario
# ---------------------------------------------------------------------------


def test_empty_project_is_not_reviewed(empty_project):
    review = design_review.evaluate_design_review(empty_project)
    assert review["manufacturing_readiness"] == "not_reviewed"
    assert review["automatic_print_allowed"] is False


def test_full_hybrid_project_reaches_needs_information_without_printer(full_hybrid_project):
    review = design_review.evaluate_design_review(full_hybrid_project)
    assert review["manufacturing_readiness"] == "needs_information"
    assert review["chain_consistent"] is True
    assert review["workflow_type"] == "hybrid_organic_mechanical"
    assert 0 <= review["design_quality_score"] <= 100


def test_broken_lineage_produces_a_blocker(full_hybrid_project):
    meshy_path = full_hybrid_project / "generated" / "meshy" / "processed" / "task1.stl"
    meshy_path.unlink()
    review = design_review.evaluate_design_review(full_hybrid_project)
    assert review["manufacturing_readiness"] == "blocked"
    assert any(b["source"] == "lineage" for b in review["blockers"])


def test_invalid_geometry_scores_zero_and_blocks(isolated_projects_dir):
    root = project_store.init_project("Bad Geometry")
    adapted_dir = root / "generated" / "blender" / "adapted"
    adapted_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = adapted_dir / "broken.stl"
    artifact_path.write_text("not a valid stl file")
    project_store.save_json(
        root / "generated" / "blender_adaptation_receipt.json",
        {
            "workflow": "organic_cleanup_workflow",
            "input_artifact": "generated/meshy/processed/x.stl", "input_hash": "sha256:x",
            "output_artifact": "generated/blender/adapted/broken.stl", "output_hash": design_review._file_fingerprint(artifact_path),
            "single_shot_human_confirmation": True,
        },
    )
    review = design_review.evaluate_design_review(root)
    assert review["score_categories"]["geometry"]["score"] == 0
    assert review["manufacturing_readiness"] == "blocked"


def test_unknown_scale_scores_low_without_design_intent_or_blender(meshy_only_project):
    root, _ = meshy_only_project
    review = design_review.evaluate_design_review(root)
    assert review["score_categories"]["scale"]["score"] <= 40


def test_missing_printer_is_flagged(full_hybrid_project):
    review = design_review.evaluate_design_review(full_hybrid_project)
    confirmations = {c["item"]: c["confirmed"] for c in review["required_human_confirmations"]}
    assert confirmations["printer_confirmed"] is False
    assert any("printer" in a.lower() for a in review["recommended_actions"])


def test_missing_design_intent_is_flagged(full_hybrid_project):
    review = design_review.evaluate_design_review(full_hybrid_project)
    confirmations = {c["item"]: c["confirmed"] for c in review["required_human_confirmations"]}
    assert confirmations["design_intent_confirmed"] is False


def test_functional_completeness_flags_missing_cad_when_expected(isolated_projects_dir):
    """A project with a design_intent whose use_case implies mechanical
    features, but no cad_augmentation_receipt yet."""
    root = project_store.init_project("Coin Bank")
    brief_path = root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["design_intent"] = {"use_case": "a coin bank with a mechanical moving hinge mechanism"}
    project_store.save_json(brief_path, brief)

    meshy_dir = root / "generated" / "meshy" / "processed"
    meshy_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = meshy_dir / "x.stl"
    artifact_path.write_text(_MINIMAL_STL)
    project_store.save_json(
        root / "generated" / "meshy_receipt.json",
        {"meshy_task_id": "x", "mock_execution": False, "live_api_used": True, "output_artifact_paths": [str(artifact_path)]},
    )

    review = design_review.evaluate_design_review(root)
    assert review["functional_completeness"]["score"] == 0
    assert any(b["source"] == "functional_completeness" for b in review["blockers"])


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_quality_category_weights_sum_to_one():
    assert abs(sum(design_review.QUALITY_CATEGORY_WEIGHTS.values()) - 1.0) < 1e-9


def test_compute_quality_score_is_weighted_average():
    categories = {name: {"score": 100, "reasoning": "", "inputs": {}} for name in design_review.QUALITY_CATEGORY_WEIGHTS}
    result = design_review.compute_quality_score(categories)
    assert result["overall"] == 100
    categories_zero = {name: {"score": 0, "reasoning": "", "inputs": {}} for name in design_review.QUALITY_CATEGORY_WEIGHTS}
    assert design_review.compute_quality_score(categories_zero)["overall"] == 0


def test_readiness_states_never_include_approved_for_print():
    assert "approved_for_print" not in design_review.READINESS_STATES
    assert all("print" not in s or s == "not_reviewed" for s in design_review.READINESS_STATES)


# ---------------------------------------------------------------------------
# Never writes without --save / never executes anything
# ---------------------------------------------------------------------------


def test_evaluate_never_writes_anything(full_hybrid_project):
    files_before = sorted(p.relative_to(full_hybrid_project) for p in full_hybrid_project.rglob("*") if p.is_file())
    design_review.evaluate_design_review(full_hybrid_project)
    design_review.evaluate_design_review(full_hybrid_project)
    files_after = sorted(p.relative_to(full_hybrid_project) for p in full_hybrid_project.rglob("*") if p.is_file())
    assert files_before == files_after


def test_save_design_review_report_writes_a_snapshot(full_hybrid_project):
    report_path = design_review.save_design_review_report(full_hybrid_project)
    assert report_path.is_file()
    saved = project_store.load_json(report_path)
    assert saved["design_review_version"] == design_review.DESIGN_REVIEW_VERSION
    assert "review" in saved


def test_read_design_review_report_none_before_save(full_hybrid_project):
    assert design_review.read_design_review_report(full_hybrid_project) is None


def test_build_safety_block_is_all_false():
    block = design_review.build_safety_block()
    assert all(value is False for value in block.values())


def test_summarize_design_review_before_and_after(full_hybrid_project):
    summary = design_review.summarize_design_review(full_hybrid_project)
    assert summary["review_available"] is True
    assert isinstance(summary["design_quality_score"], int)

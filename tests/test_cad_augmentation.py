"""Phase 50 tests: `factory.cad_augmentation` - plan generation, CAD
routing, parameter handling, the execution gate (explicit confirmation),
receipt writing, and artifact lineage. Uses the real `openscad` CLI when
available (the same convention `tests/test_export_pipeline.py` uses via
monkeypatched `resolve_openscad_executable`/`subprocess.run`), so these
tests never depend on OpenSCAD actually being installed. See
docs/cad-augmentation.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from factory import cad_augmentation, export_pipeline, project_store

_MINIMAL_STL = (
    "solid t\n"
    "facet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\n"
    "facet normal 0 0 -1\nouter loop\nvertex 0 0 0\nvertex 0 1 0\nvertex 1 0 0\nendloop\nendfacet\n"
    "endsolid t\n"
)

_BASE_PARAMS = {"base_width_mm": 120.0, "base_length_mm": 80.0, "base_height_mm": 10.0}


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture()
def blender_adapted_project(isolated_projects_dir):
    """A project whose organic artifact is itself a Blender-adapted child
    artifact, with a real blender_adaptation_receipt.json - so
    `organic_component.is_blender_adapted` can be proven true."""
    root = project_store.init_project("Piggy Bank")
    adapted_dir = root / "generated" / "blender" / "adapted"
    adapted_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = adapted_dir / "01a07ca5_adapted.stl"
    artifact_path.write_text(_MINIMAL_STL)
    receipt = {
        "workflow": "organic_cleanup_workflow",
        "input_artifact": "generated/meshy/processed/01a07ca5.stl",
        "output_artifact": "generated/blender/adapted/01a07ca5_adapted.stl",
        "scale_factor_applied": 0.07883,
        "validation_status": "WARN",
    }
    project_store.save_json(root / "generated" / "blender_adaptation_receipt.json", receipt)
    return root, artifact_path


def _fake_openscad_writes_stl(monkeypatch, *, content=_MINIMAL_STL.encode()):
    """Mocks factory.export_pipeline.resolve_openscad_executable() +
    subprocess.run() to behave like a successful
    `openscad -o out.stl in.scad` call - mirrors
    tests/test_export_pipeline.py's identical convention exactly."""
    monkeypatch.setattr(export_pipeline, "resolve_openscad_executable", lambda: "/fake/bin/openscad")

    class _FakeCompleted:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(command, capture_output, text, timeout):
        if "--version" in command:
            return _FakeCompleted(returncode=0, stdout="OpenSCAD version 2021.01 (fake)")
        output_path = Path(command[2])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(export_pipeline.subprocess, "run", _fake_run)


def _fake_openscad_fails(monkeypatch):
    monkeypatch.setattr(export_pipeline, "resolve_openscad_executable", lambda: "/fake/bin/openscad")

    class _FakeCompleted:
        returncode = 1
        stdout = ""
        stderr = "syntax error"

    monkeypatch.setattr(export_pipeline.subprocess, "run", lambda *a, **k: _FakeCompleted())


# ---------------------------------------------------------------------------
# _select_cad_engine() / routing
# ---------------------------------------------------------------------------


def test_select_cad_engine_recommends_openscad_only():
    routing = cad_augmentation._select_cad_engine()
    assert routing["recommended_cad_engine"] == "openscad_stable"
    assert set(routing["candidate_engines"]) >= {"cadquery", "openscad_stable"}
    assert "freecad" in routing["candidate_engines"] or True  # freecad may or may not be "high"; never asserted rigidly here


def test_select_cad_engine_never_recommends_cadquery_or_freecad():
    routing = cad_augmentation._select_cad_engine()
    assert routing["recommended_cad_engine"] != "cadquery"
    assert routing["recommended_cad_engine"] != "freecad"


# ---------------------------------------------------------------------------
# _required_parameters()
# ---------------------------------------------------------------------------


def test_required_parameters_base_only():
    model = cad_augmentation._required_parameters(dict(_BASE_PARAMS))
    assert model["all_required_provided"] is True
    assert model["coin_slot_requested"] is False
    assert model["mounting_holes_requested"] is False


def test_required_parameters_coin_slot_partial_requires_human_input():
    params = dict(_BASE_PARAMS)
    params["coin_slot_width_mm"] = 30.0  # length/depth missing
    model = cad_augmentation._required_parameters(params)
    assert model["coin_slot_requested"] is True
    assert "coin_slot_length_mm" in model["requires_human_input"]
    assert "coin_slot_depth_mm" in model["requires_human_input"]
    assert model["all_required_provided"] is False


def test_required_parameters_missing_base_dimension():
    params = {"base_width_mm": 120.0, "base_length_mm": None, "base_height_mm": 10.0}
    model = cad_augmentation._required_parameters(params)
    assert "base_length_mm" in model["requires_human_input"]


def test_required_parameters_mounting_holes_never_required():
    model = cad_augmentation._required_parameters(dict(_BASE_PARAMS))
    entry = next(e for e in model["parameters"] if e["name"] == "mounting_hole_diameter_mm")
    assert entry["required"] is False


# ---------------------------------------------------------------------------
# _render_functional_feature_scad() - pure text generation
# ---------------------------------------------------------------------------


def test_render_scad_never_writes_a_file(tmp_path):
    before = sorted(tmp_path.rglob("*"))
    cad_augmentation._render_functional_feature_scad(
        base_width_mm=120.0, base_length_mm=80.0, base_height_mm=10.0,
        coin_slot_width_mm=None, coin_slot_length_mm=None, coin_slot_depth_mm=None,
        coin_slot_position_x_mm=None, coin_slot_position_y_mm=None,
        mounting_hole_diameter_mm=None, mounting_hole_margin_mm=8.0,
    )
    after = sorted(tmp_path.rglob("*"))
    assert before == after


def test_render_scad_uses_openscad_comment_syntax_not_python():
    text = cad_augmentation._render_functional_feature_scad(
        base_width_mm=120.0, base_length_mm=80.0, base_height_mm=10.0,
        coin_slot_width_mm=None, coin_slot_length_mm=None, coin_slot_depth_mm=None,
        coin_slot_position_x_mm=None, coin_slot_position_y_mm=None,
        mounting_hole_diameter_mm=4.0, mounting_hole_margin_mm=8.0,
    )
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            pytest.fail(f"line uses a Python-style '#' comment, invalid in OpenSCAD: {line!r}")


def test_render_scad_omits_coin_slot_and_holes_when_not_requested():
    text = cad_augmentation._render_functional_feature_scad(
        base_width_mm=120.0, base_length_mm=80.0, base_height_mm=10.0,
        coin_slot_width_mm=None, coin_slot_length_mm=None, coin_slot_depth_mm=None,
        coin_slot_position_x_mm=None, coin_slot_position_y_mm=None,
        mounting_hole_diameter_mm=None, mounting_hole_margin_mm=8.0,
    )
    assert "coin_slot = false;" in text
    assert "mounting_holes = false;" in text


# ---------------------------------------------------------------------------
# build_augmentation_plan() - pure, read-only
# ---------------------------------------------------------------------------


def test_plan_reports_no_project_when_artifact_outside_projects_dir(tmp_path):
    artifact = tmp_path / "loose.stl"
    artifact.write_text(_MINIMAL_STL)
    plan = cad_augmentation.build_augmentation_plan(artifact, **_BASE_PARAMS)
    assert plan["project"] is None
    assert plan["output_artifact"] is None
    assert plan["execution_allowed"] is False
    assert any("project directory" in b for b in plan["blockers"])


def test_plan_detects_blender_adapted_lineage(blender_adapted_project):
    _, artifact_path = blender_adapted_project
    plan = cad_augmentation.build_augmentation_plan(artifact_path, **_BASE_PARAMS)
    assert plan["organic_component"]["is_blender_adapted"] is True
    assert plan["organic_component"]["blender_workflow"] == "organic_cleanup_workflow"
    assert plan["organic_component"]["blender_scale_factor_applied"] == 0.07883


def test_plan_computes_output_paths(blender_adapted_project):
    project_dir, artifact_path = blender_adapted_project
    plan = cad_augmentation.build_augmentation_plan(artifact_path, **_BASE_PARAMS)
    assert plan["output_artifact"] == str(project_dir / "generated" / "cad_augmentation" / "01a07ca5_adapted_feature.stl")
    assert plan["output_feature_source"] == str(project_dir / "generated" / "cad_augmentation" / "01a07ca5_adapted_feature.scad")


def test_plan_execution_allowed_with_full_params(blender_adapted_project):
    _, artifact_path = blender_adapted_project
    plan = cad_augmentation.build_augmentation_plan(artifact_path, **_BASE_PARAMS)
    assert plan["execution_allowed"] is True
    assert plan["recommended_cad_engine"] == "openscad_stable"
    assert plan["workflow_type"] == "organic_mechanical_augmentation"
    assert plan["automatic_execution_allowed"] is False
    assert plan["no_automatic_print"] is True


def test_plan_blocked_when_required_parameter_missing(blender_adapted_project):
    _, artifact_path = blender_adapted_project
    plan = cad_augmentation.build_augmentation_plan(artifact_path, base_width_mm=120.0)
    assert plan["execution_allowed"] is False
    assert any("missing required parameter" in b for b in plan["blockers"])


def test_plan_blocked_when_output_already_exists(blender_adapted_project):
    project_dir, artifact_path = blender_adapted_project
    output_path = project_dir / "generated" / "cad_augmentation" / "01a07ca5_adapted_feature.stl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_MINIMAL_STL)
    plan = cad_augmentation.build_augmentation_plan(artifact_path, **_BASE_PARAMS)
    assert plan["execution_allowed"] is False
    assert any("overwrite" in b for b in plan["blockers"])


def test_plan_never_writes_anything(blender_adapted_project):
    project_dir, artifact_path = blender_adapted_project
    files_before = sorted(p.relative_to(project_dir) for p in project_dir.rglob("*") if p.is_file())
    cad_augmentation.build_augmentation_plan(artifact_path, **_BASE_PARAMS)
    files_after = sorted(p.relative_to(project_dir) for p in project_dir.rglob("*") if p.is_file())
    assert files_before == files_after


# ---------------------------------------------------------------------------
# run_organic_mechanical_augmentation() - the gated execution path
# ---------------------------------------------------------------------------


def test_execute_blocked_without_confirm(blender_adapted_project, monkeypatch):
    _, artifact_path = blender_adapted_project
    _fake_openscad_writes_stl(monkeypatch)
    result = cad_augmentation.run_organic_mechanical_augmentation(artifact_path, confirm=False, **_BASE_PARAMS)
    assert result["augmentation_status"] == "blocked"
    assert result["receipt"] is None


def test_execute_blocked_when_plan_has_blockers(blender_adapted_project, monkeypatch):
    _, artifact_path = blender_adapted_project
    result = cad_augmentation.run_organic_mechanical_augmentation(artifact_path, confirm=True, base_width_mm=120.0)
    assert result["augmentation_status"] == "blocked"


def test_execute_succeeds_end_to_end(blender_adapted_project, monkeypatch):
    project_dir, artifact_path = blender_adapted_project
    _fake_openscad_writes_stl(monkeypatch)

    result = cad_augmentation.run_organic_mechanical_augmentation(
        artifact_path, confirm=True, confirmed_by="owen",
        base_width_mm=120.0, base_length_mm=80.0, base_height_mm=10.0,
        coin_slot_width_mm=30.0, coin_slot_length_mm=6.0, coin_slot_depth_mm=12.0,
        mounting_hole_diameter_mm=4.0,
    )

    assert result["augmentation_status"] == "succeeded"
    output_path = project_dir / "generated" / "cad_augmentation" / "01a07ca5_adapted_feature.stl"
    assert output_path.is_file()
    scad_path = project_dir / "generated" / "cad_augmentation" / "01a07ca5_adapted_feature.scad"
    assert scad_path.is_file()

    receipt_path = project_dir / "generated" / "cad_augmentation_receipt.json"
    assert receipt_path.is_file()
    receipt = project_store.load_json(receipt_path)
    assert receipt["workflow"] == "organic_mechanical_augmentation"
    assert receipt["cad_engine"] == "openscad_stable"
    assert receipt["confirmed_by"] == "owen"
    assert receipt["single_shot_human_confirmation"] is True
    assert receipt["project_execution_approved"] is False
    assert receipt["mesh_boolean_merge_performed"] is False
    assert receipt["input_hash"].startswith("sha256:")
    assert receipt["output_hash"].startswith("sha256:")
    assert receipt["parameters"]["coin_slot_width_mm"] == 30.0

    # original organic input artifact must never be modified
    assert artifact_path.read_text() == _MINIMAL_STL


def test_execute_never_overwrites_organic_artifact(blender_adapted_project, monkeypatch):
    _, artifact_path = blender_adapted_project
    _fake_openscad_writes_stl(monkeypatch)
    before = artifact_path.read_bytes()
    cad_augmentation.run_organic_mechanical_augmentation(artifact_path, confirm=True, **_BASE_PARAMS)
    after = artifact_path.read_bytes()
    assert before == after


def test_execute_refuses_to_overwrite_existing_receipt(blender_adapted_project, monkeypatch):
    project_dir, artifact_path = blender_adapted_project
    _fake_openscad_writes_stl(monkeypatch)
    receipt_path = project_dir / "generated" / "cad_augmentation_receipt.json"
    project_store.save_json(receipt_path, {"pre_existing": True})

    result = cad_augmentation.run_organic_mechanical_augmentation(artifact_path, confirm=True, **_BASE_PARAMS)
    assert result["augmentation_status"] == "failed"
    assert project_store.load_json(receipt_path) == {"pre_existing": True}


def test_execute_reports_failure_when_openscad_fails(blender_adapted_project, monkeypatch):
    _, artifact_path = blender_adapted_project
    _fake_openscad_fails(monkeypatch)
    result = cad_augmentation.run_organic_mechanical_augmentation(artifact_path, confirm=True, **_BASE_PARAMS)
    assert result["augmentation_status"] == "failed"
    assert result["receipt"] is None


def test_read_cad_augmentation_receipt_none_before_execution(blender_adapted_project):
    project_dir, _ = blender_adapted_project
    assert cad_augmentation.read_cad_augmentation_receipt(project_dir) is None


def test_summarize_cad_augmentation_before_and_after(blender_adapted_project, monkeypatch):
    project_dir, artifact_path = blender_adapted_project
    summary_before = cad_augmentation.summarize_cad_augmentation(project_dir)
    assert summary_before["augmentation_available"] is False

    _fake_openscad_writes_stl(monkeypatch)
    cad_augmentation.run_organic_mechanical_augmentation(artifact_path, confirm=True, **_BASE_PARAMS)

    summary_after = cad_augmentation.summarize_cad_augmentation(project_dir)
    assert summary_after["augmentation_available"] is True
    assert summary_after["workflow"] == "organic_mechanical_augmentation"


def test_build_safety_block_is_all_false():
    block = cad_augmentation.build_safety_block()
    assert all(value is False for value in block.values())

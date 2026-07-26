"""Phase 39 Part 3/4 tests: `factory.slicer_history` - a lightweight,
local, append-only analysis history and change comparison.

History is observational - it never affects readiness, approval,
slicing, or printing. Persistence is explicit only:
`save_analysis_snapshot()` is the only function that writes anything, and
nothing else in this module (or `factory.slicer_intelligence`/
`factory.preview_board`) ever calls it automatically. See
docs/slicer-analysis-history.md, docs/roadmap.md Phase 39.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from factory import export_pipeline, project_store
from factory.openscad.generate import generate_openscad
from factory.slicer_history import (
    ANALYSIS_TYPE,
    CHANGE_CATEGORIES,
    HISTORY_FILENAME,
    compare_slicer_analysis,
    read_analysis_history,
    save_analysis_snapshot,
    summarize_slicer_history,
)
from factory.slicer_intelligence import evaluate_slicer_intelligence
from factory.generation_gate import GENERATED_DIRNAME

FAKE_OPENSCAD = "/fake/bin/openscad"


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


def _fake_openscad_available(monkeypatch, executable=FAKE_OPENSCAD):
    monkeypatch.setattr(export_pipeline, "resolve_openscad_executable", lambda: executable)


def _fake_subprocess_writes_stl(monkeypatch, *, content=b"solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid x\n"):
    def _fake_run(command, capture_output, text, timeout):
        if "--version" in command:
            return _FakeCompleted(returncode=0, stdout="OpenSCAD version 2021.01 (fake)")
        output_path = Path(command[2])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(export_pipeline.subprocess, "run", _fake_run)


_DEFAULT_STL = b"solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid x\n"
_DIFFERENT_STL = b"solid y\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 2 0 0\nvertex 0 2 0\nendloop\nendfacet\nendsolid y\n"


def _export_all(project_dir, monkeypatch, *, overwrite_stl=False, content=_DEFAULT_STL):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch, content=content)
    plan = export_pipeline.plan_export(project_dir, confirm_export=True, overwrite_stl=overwrite_stl)
    return export_pipeline.run_export_pipeline(project_dir, plan, all_steps=True)


def _resolve_manufacturing(project_dir, *, printer_id="bambu_h2d"):
    build_plan = project_store.load_json(project_dir / "build_plan.json")
    build_plan["selected_manufacturing_option"] = "single_piece"
    build_plan["target_printer"] = {
        "printer_id": printer_id,
        "display_name": printer_id,
        "resolved": True,
        "resolved_from": "test",
        "capabilities": None,
    }
    project_store.save_json(project_dir / "build_plan.json", build_plan)


def _resolve_materials(project_dir, *, material="PLA", color="white"):
    manifest = project_store.load_json(project_dir / "part_manifest.json")
    for part in manifest.get("parts", []):
        part["material"] = material
        part["color"] = color
    project_store.save_json(project_dir / "part_manifest.json", manifest)


# ---------------------------------------------------------------------------
# Vocabulary sanity
# ---------------------------------------------------------------------------


def test_change_categories_are_the_suggested_values():
    assert set(CHANGE_CATEGORIES) == {
        "STL changed", "CAD changed", "Printer changed", "Material changed",
        "Validation changed", "Risk changed", "Slicer environment changed", "Warnings changed",
    }


def test_analysis_type_constant():
    assert ANALYSIS_TYPE == "slicer_intelligence"


# ---------------------------------------------------------------------------
# save_analysis_snapshot() / read_analysis_history() - the only write path
# ---------------------------------------------------------------------------


def test_read_history_empty_when_no_file(scad_project):
    assert read_analysis_history(scad_project) == []


def test_save_snapshot_writes_the_history_file(scad_project):
    result = save_analysis_snapshot(scad_project)
    history_path = scad_project / GENERATED_DIRNAME / HISTORY_FILENAME
    assert history_path.is_file()
    assert result["history_path"] == str(history_path)
    assert result["snapshot_count"] == 1


def test_save_snapshot_appends_not_overwrites(scad_project):
    save_analysis_snapshot(scad_project)
    result = save_analysis_snapshot(scad_project)
    assert result["snapshot_count"] == 2
    history = read_analysis_history(scad_project)
    assert len(history) == 2


def test_saved_snapshot_has_expected_fields(scad_project):
    save_analysis_snapshot(scad_project)
    history = read_analysis_history(scad_project)
    snapshot = history[0]
    for field in (
        "timestamp", "project", "analysis_type", "artifact_fingerprints",
        "readiness_summary", "slicer_intelligence_summary", "printer_id",
        "printer_display_name", "materials", "detected_slicer_names",
        "slicer_profile_name", "risk_level", "confidence", "warnings",
    ):
        assert field in snapshot, f"missing field {field!r}"
    assert snapshot["analysis_type"] == "slicer_intelligence"


def test_save_snapshot_reuses_a_precomputed_analysis_without_recomputing(scad_project, monkeypatch):
    calls = {"count": 0}
    real_evaluate = evaluate_slicer_intelligence

    def _counting_evaluate(project_dir):
        calls["count"] += 1
        return real_evaluate(project_dir)

    monkeypatch.setattr("factory.slicer_history.evaluate_slicer_intelligence", _counting_evaluate)
    analysis = real_evaluate(scad_project)
    save_analysis_snapshot(scad_project, analysis=analysis)
    assert calls["count"] == 0


def test_save_snapshot_computes_fresh_when_analysis_not_given(scad_project, monkeypatch):
    calls = {"count": 0}
    real_evaluate = evaluate_slicer_intelligence

    def _counting_evaluate(project_dir):
        calls["count"] += 1
        return real_evaluate(project_dir)

    monkeypatch.setattr("factory.slicer_history.evaluate_slicer_intelligence", _counting_evaluate)
    save_analysis_snapshot(scad_project)
    assert calls["count"] == 1


def test_corrupted_history_file_degrades_to_empty_not_a_crash(scad_project):
    history_path = scad_project / GENERATED_DIRNAME / HISTORY_FILENAME
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text("{not valid json", encoding="utf-8")
    assert read_analysis_history(scad_project) == []


def test_corrupted_history_file_does_not_block_saving_a_new_one(scad_project):
    history_path = scad_project / GENERATED_DIRNAME / HISTORY_FILENAME
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text("{not valid json", encoding="utf-8")
    result = save_analysis_snapshot(scad_project)
    assert result["snapshot_count"] == 1
    history = read_analysis_history(scad_project)
    assert len(history) == 1


def test_history_with_wrong_shape_degrades_to_empty(scad_project):
    history_path = scad_project / GENERATED_DIRNAME / HISTORY_FILENAME
    project_store.save_json(history_path, {"project": "x", "snapshots": "not-a-list"})
    assert read_analysis_history(scad_project) == []


def test_save_analysis_never_writes_outside_generated_dir(scad_project):
    before = sorted(str(p) for p in scad_project.rglob("*") if GENERATED_DIRNAME not in p.parts)
    save_analysis_snapshot(scad_project)
    after = sorted(str(p) for p in scad_project.rglob("*") if GENERATED_DIRNAME not in p.parts)
    assert before == after


def test_save_analysis_never_invokes_a_subprocess(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("save_analysis_snapshot() must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    save_analysis_snapshot(scad_project)


# ---------------------------------------------------------------------------
# No automatic writes - reading/evaluating must never trigger a save
# ---------------------------------------------------------------------------


def test_read_analysis_history_never_writes(scad_project):
    read_analysis_history(scad_project)
    assert not (scad_project / GENERATED_DIRNAME).exists()


def test_evaluate_slicer_intelligence_never_writes_history(scad_project):
    evaluate_slicer_intelligence(scad_project)
    assert not (scad_project / GENERATED_DIRNAME / HISTORY_FILENAME).exists()


def test_compare_slicer_analysis_never_writes_history(scad_project):
    compare_slicer_analysis(scad_project)
    assert not (scad_project / GENERATED_DIRNAME / HISTORY_FILENAME).exists()


def test_summarize_slicer_history_never_writes(scad_project):
    summarize_slicer_history(scad_project)
    assert not (scad_project / GENERATED_DIRNAME).exists()


def test_preview_board_never_writes_history(isolated_projects_dir, scad_project):
    from factory.preview_board import gather_board_data

    gather_board_data(isolated_projects_dir)
    assert not (scad_project / GENERATED_DIRNAME / HISTORY_FILENAME).exists()


# ---------------------------------------------------------------------------
# compare_slicer_analysis() - live current vs. last saved snapshot
# ---------------------------------------------------------------------------


def test_compare_with_no_history_reports_unavailable(scad_project):
    comparison = compare_slicer_analysis(scad_project)
    assert comparison["history_available"] is False
    assert comparison["previous"] is None
    assert comparison["changes"] == []
    assert "No previous analysis snapshot" in comparison["recommendation"]


def test_compare_with_no_changes_reports_none(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    save_analysis_snapshot(scad_project)
    comparison = compare_slicer_analysis(scad_project)
    assert comparison["history_available"] is True
    assert comparison["changes"] == []
    assert comparison["recommendation"] == "No changes detected since the last saved analysis."


def test_compare_detects_stl_changed(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    save_analysis_snapshot(scad_project)
    _export_all(scad_project, monkeypatch, overwrite_stl=True, content=_DIFFERENT_STL)
    comparison = compare_slicer_analysis(scad_project)
    assert "STL changed" in comparison["changes"]


def test_compare_detects_cad_changed(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    save_analysis_snapshot(scad_project)
    scad_path = scad_project / "cad" / "sign.scad"
    scad_path.write_text(scad_path.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
    comparison = compare_slicer_analysis(scad_project)
    assert "CAD changed" in comparison["changes"]


def test_compare_detects_printer_changed(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    _resolve_manufacturing(scad_project, printer_id="bambu_h2d")
    save_analysis_snapshot(scad_project)
    _resolve_manufacturing(scad_project, printer_id="bambu_p1s_1")
    comparison = compare_slicer_analysis(scad_project)
    assert "Printer changed" in comparison["changes"]


def test_compare_detects_material_changed(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    _resolve_materials(scad_project, material="PLA")
    save_analysis_snapshot(scad_project)
    _resolve_materials(scad_project, material="PETG")
    comparison = compare_slicer_analysis(scad_project)
    assert "Material changed" in comparison["changes"]


def test_compare_detects_risk_changed(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    save_analysis_snapshot(scad_project)
    _resolve_manufacturing(scad_project)
    _resolve_materials(scad_project)
    comparison = compare_slicer_analysis(scad_project)
    assert "Risk changed" in comparison["changes"]


def test_compare_detects_warnings_changed(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    save_analysis_snapshot(scad_project)
    _resolve_manufacturing(scad_project)
    comparison = compare_slicer_analysis(scad_project)
    assert "Warnings changed" in comparison["changes"]


def test_compare_detects_slicer_environment_changed(scad_project, monkeypatch):
    monkeypatch.setattr(
        "factory.slicer_readiness.probe_slicers",
        lambda: [{"name": "Bambu Studio", "found": True, "method": "applications_folder", "path": "/Applications/BambuStudio.app"}],
    )
    save_analysis_snapshot(scad_project)
    monkeypatch.setattr(
        "factory.slicer_readiness.probe_slicers",
        lambda: [{"name": "Bambu Studio", "found": False, "method": None, "path": None}],
    )
    comparison = compare_slicer_analysis(scad_project)
    assert "Slicer environment changed" in comparison["changes"]


def test_compare_recommendation_reflects_changes(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    save_analysis_snapshot(scad_project)
    _export_all(scad_project, monkeypatch, overwrite_stl=True, content=_DIFFERENT_STL)
    comparison = compare_slicer_analysis(scad_project)
    assert "review" in comparison["recommendation"].lower()


def test_compare_never_writes_a_new_snapshot(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    save_analysis_snapshot(scad_project)
    before = len(read_analysis_history(scad_project))
    compare_slicer_analysis(scad_project)
    after = len(read_analysis_history(scad_project))
    assert before == after


def test_compare_accepts_a_precomputed_current_analysis(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    save_analysis_snapshot(scad_project)
    current = evaluate_slicer_intelligence(scad_project)
    comparison = compare_slicer_analysis(scad_project, current=current)
    assert comparison["current"]["risk_level"] == current["risk_level"]


# ---------------------------------------------------------------------------
# summarize_slicer_history() - pure history-to-history comparison, no live
# recompute, no write
# ---------------------------------------------------------------------------


def test_summarize_history_unavailable_with_no_snapshots(scad_project):
    summary = summarize_slicer_history(scad_project)
    assert summary["history_available"] is False
    assert summary["latest_analysis"] is None
    assert summary["previous_analysis"] is None
    assert summary["changes_detected"] is None
    assert summary["risk_change"] is None


def test_summarize_history_with_one_snapshot_has_no_previous(scad_project):
    save_analysis_snapshot(scad_project)
    summary = summarize_slicer_history(scad_project)
    assert summary["history_available"] is True
    assert summary["latest_analysis"] is not None
    assert summary["previous_analysis"] is None
    assert summary["changes_detected"] is None
    assert summary["risk_change"] is None


def test_summarize_history_with_two_snapshots_computes_changes(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    save_analysis_snapshot(scad_project)
    _resolve_manufacturing(scad_project)
    save_analysis_snapshot(scad_project)
    summary = summarize_slicer_history(scad_project)
    assert summary["history_available"] is True
    assert summary["previous_analysis"] is not None
    assert isinstance(summary["changes_detected"], int)
    assert summary["changes_detected"] >= 1


def test_summarize_history_risk_change_format(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    save_analysis_snapshot(scad_project)
    _resolve_manufacturing(scad_project)
    _resolve_materials(scad_project)
    save_analysis_snapshot(scad_project)
    summary = summarize_slicer_history(scad_project)
    if summary["risk_change"] is not None:
        assert "->" in summary["risk_change"]


# ---------------------------------------------------------------------------
# Safety: history is observational only
# ---------------------------------------------------------------------------


def test_saving_a_snapshot_does_not_affect_readiness(scad_project, monkeypatch):
    from factory.slicer_readiness import assess_slicer_readiness

    before = assess_slicer_readiness(scad_project)["readiness_status"]
    save_analysis_snapshot(scad_project)
    after = assess_slicer_readiness(scad_project)["readiness_status"]
    assert before == after


def test_saving_a_snapshot_does_not_affect_approval(scad_project, monkeypatch):
    from factory.slicer_readiness import read_slicer_readiness_receipt

    save_analysis_snapshot(scad_project)
    receipt = read_slicer_readiness_receipt(scad_project)
    assert receipt is None or "approval" not in receipt


def test_no_slicer_execution_no_gcode_no_network(scad_project, monkeypatch):
    def _boom_subprocess(*a, **k):
        raise AssertionError("must never invoke a subprocess")

    def _boom_socket(*a, **k):
        raise AssertionError("must never open a network socket")

    import socket

    monkeypatch.setattr(export_pipeline.subprocess, "Popen", _boom_subprocess, raising=False)
    monkeypatch.setattr(socket, "socket", _boom_socket)
    save_analysis_snapshot(scad_project)
    compare_slicer_analysis(scad_project)
    summarize_slicer_history(scad_project)

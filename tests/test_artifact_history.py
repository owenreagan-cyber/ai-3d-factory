"""Phase 41 tests: `factory.artifact_history` - safe artifact history and
diff planning built directly on Phase 40's unified timeline.

There is no write path anywhere in this module. Version numbers are
derived (the 1-based ordinal of each artifact-relevant timeline event),
never stored in a counter file. Artifact History is a VIEW over existing
evidence - it never becomes authoritative. See docs/artifact-history.md,
docs/roadmap.md Phase 41.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from factory import export_pipeline, project_store
from factory.manufacturing import knowledge
from factory.openscad.generate import generate_openscad
from factory.artifact_history import (
    ARTIFACT_CATEGORIES,
    VERSION_EVENT_CATEGORIES,
    UnknownVersionError,
    build_rollback_plan,
    diff_artifact_versions,
    get_artifact_history,
    get_artifact_history_for_path,
    get_artifact_snapshot,
    summarize_artifact_history,
)
from factory.slicer_history import save_analysis_snapshot
from factory.slicer_readiness import record_approval

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


def _flesh_out_brief_for_manufacturing_review(project_dir):
    brief_path = project_dir / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["design_intent"] = {
        "quality_standard": "premium",
        "use_case": "classroom nameplate sign",
        "style_direction": ["clean", "modern"],
        "reference_inputs": ["Classroom sign example"],
        "manufacturability_constraints": {"max_size_mm": [120, 40, 5]},
    }
    project_store.save_json(brief_path, brief)
    project_store.save_json(
        project_dir / "reference_board.json",
        {
            "references": [
                {
                    "title": "Classroom sign example",
                    "source_type": "image",
                    "license": "public_domain",
                    "attached_to": "design_intent.reference_inputs",
                    "source_url": "https://example.com/sign",
                }
            ]
        },
    )


def _resolve_manufacturing(project_dir, *, printer_id="bambu_h2d"):
    build_plan = project_store.load_json(project_dir / "build_plan.json")
    build_plan["selected_manufacturing_option"] = "single_piece"
    printer = knowledge.get_printer(printer_id)
    build_plan["target_printer"] = {
        "printer_id": printer_id,
        "display_name": printer["display_name"] if printer else printer_id,
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


def _fully_ready(project_dir, monkeypatch, **kwargs):
    _flesh_out_brief_for_manufacturing_review(project_dir)
    _export_all(project_dir, monkeypatch)
    _resolve_manufacturing(project_dir, **kwargs)
    _resolve_materials(project_dir)
    return project_dir


def _fully_approved(project_dir, monkeypatch, **kwargs):
    _fully_ready(project_dir, monkeypatch, **kwargs)
    record_approval(project_dir)
    return project_dir


# ---------------------------------------------------------------------------
# Vocabulary sanity
# ---------------------------------------------------------------------------


def test_version_event_categories_exclude_non_artifact_categories():
    assert set(VERSION_EVENT_CATEGORIES) == {
        "cad", "export", "validation", "preview", "approval", "package", "workspace",
    }
    # Pipeline-milestone and already-derived-change categories are never
    # versioned - they're reused for diffing instead (see below).
    assert "brief" not in VERSION_EVENT_CATEGORIES
    assert "manufacturing_plan" not in VERSION_EVENT_CATEGORIES
    assert "slicer_analysis" not in VERSION_EVENT_CATEGORIES
    assert "material_change" not in VERSION_EVENT_CATEGORIES


def test_artifact_categories_is_a_fixed_closed_set():
    assert isinstance(ARTIFACT_CATEGORIES, tuple)
    assert len(ARTIFACT_CATEGORIES) == len(set(ARTIFACT_CATEGORIES))


def test_module_reuses_timeline_not_independent_receipt_scanning():
    source = Path("src/factory/artifact_history.py").read_text(encoding="utf-8")
    assert "from factory.project_timeline import get_project_timeline" in source
    # Never re-implements receipt reading, fingerprinting, or change detection.
    assert "read_export_receipt" not in source
    assert "read_slicer_readiness_receipt" not in source
    assert "def file_fingerprint" not in source
    assert "def detect_changes" not in source
    assert "save_json" not in source


# ---------------------------------------------------------------------------
# get_artifact_history() - empty/missing/complete/multiple versions
# ---------------------------------------------------------------------------


def test_writes_nothing(scad_project):
    before = sorted(str(p) for p in scad_project.rglob("*"))
    get_artifact_history(scad_project)
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


def test_never_invokes_a_subprocess(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("get_artifact_history() must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    get_artifact_history(scad_project)


def test_empty_project_no_export_yet_has_at_least_the_cad_version(scad_project):
    # scad_project already jumped to "cad_generated" via generate_openscad -
    # its status_history-derived "CAD generated" event is a version-worthy
    # category, so history is non-empty even with no export yet.
    history = get_artifact_history(scad_project)
    assert len(history) == 1
    assert history[0]["source_event_category"] == "cad"
    assert history[0]["version_id"] == 1


def test_bare_project_no_cad_no_export_has_empty_history(isolated_projects_dir):
    root = project_store.init_project("Bare Project")
    history = get_artifact_history(root)
    assert history == []


def test_missing_receipts_degrade_gracefully(scad_project):
    (scad_project / "brief.json").write_text("{not valid json", encoding="utf-8")
    history = get_artifact_history(scad_project)
    assert isinstance(history, list)


def test_complete_project_has_multiple_versions(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    history = get_artifact_history(scad_project)
    assert len(history) >= 4  # cad, export, validation, preview, approval at minimum
    assert [v["version_id"] for v in history] == list(range(1, len(history) + 1))


def test_deterministic_version_numbering_across_calls(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    a = get_artifact_history(scad_project)
    b = get_artifact_history(scad_project)
    assert a == b


def test_versions_are_cumulative_carrying_forward_prior_fingerprints(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    history = get_artifact_history(scad_project)
    export_version = next(v for v in history if v["source_event_category"] == "export")
    latest_version = history[-1]
    # Every fingerprint known at the export version must still be present
    # (and unchanged) at the latest version - cumulative, never dropped.
    for path, fp in export_version["fingerprints"].items():
        assert latest_version["fingerprints"].get(path) == fp


def test_fingerprint_change_reflected_in_a_later_version(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    history_before = get_artifact_history(scad_project)
    export_v1 = next(v for v in history_before if v["source_event_category"] == "export")

    _export_all(scad_project, monkeypatch, overwrite_stl=True, content=_DIFFERENT_STL)
    history_after = get_artifact_history(scad_project)
    export_v2 = [v for v in history_after if v["source_event_category"] == "export"][-1]

    stl_paths = [p for p in export_v2["fingerprints"] if p.startswith("stl/")]
    assert stl_paths
    for p in stl_paths:
        assert export_v2["fingerprints"][p] != export_v1["fingerprints"].get(p)


def test_get_artifact_history_for_path_matches_direct_call(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    a = get_artifact_history(scad_project)
    b = get_artifact_history_for_path(scad_project)
    assert a == b


def test_get_artifact_snapshot_returns_none_for_unknown_version(scad_project):
    assert get_artifact_snapshot(scad_project, 999) is None


def test_get_artifact_snapshot_returns_the_matching_version(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    history = get_artifact_history(scad_project)
    snapshot = get_artifact_snapshot(scad_project, history[0]["version_id"])
    assert snapshot == history[0]


def test_artifacts_grouped_by_category(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    history = get_artifact_history(scad_project)
    latest = history[-1]
    assert "cad" in latest["artifacts"]
    assert "stl" in latest["artifacts"]
    assert set(latest["artifacts"]) <= set(ARTIFACT_CATEGORIES)


def test_validation_preview_review_state_progress_through_versions(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    history = get_artifact_history(scad_project)
    cad_version = history[0]
    assert cad_version["validation_state"] == "Not yet reached"
    assert cad_version["review_state"] == "Pending"
    latest = history[-1]
    assert latest["validation_state"] != "Not yet reached"
    assert latest["review_state"] != "Pending"


# ---------------------------------------------------------------------------
# diff_artifact_versions()
# ---------------------------------------------------------------------------


def test_diff_no_changes_between_adjacent_versions_of_same_export(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    history = get_artifact_history(scad_project)
    validation_v = next(v for v in history if v["source_event_category"] == "validation")
    preview_v = next(v for v in history if v["source_event_category"] == "preview")
    diff = diff_artifact_versions(scad_project, validation_v["version_id"], preview_v["version_id"])
    assert "STL file" not in diff["changed"]
    assert "CAD source" not in diff["changed"]


def test_diff_detects_cad_and_stl_changed(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    history_before = get_artifact_history(scad_project)
    v1 = history_before[0]["version_id"]

    scad_path = scad_project / "cad" / "sign.scad"
    scad_path.write_text(scad_path.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
    _export_all(scad_project, monkeypatch, overwrite_stl=True, content=_DIFFERENT_STL)

    history_after = get_artifact_history(scad_project)
    v_latest = history_after[-1]["version_id"]
    diff = diff_artifact_versions(scad_project, v1, v_latest)
    assert "CAD source" in diff["changed"]
    assert "STL file" in diff["changed"]
    assert diff["impact"] == "Requires slicer review."


def test_diff_detects_validation_changed_category(scad_project, monkeypatch):
    # validation/preview fingerprints are only ever backfilled once an
    # approval/package/workspace/analysis event captures them (export_receipt
    # itself never stores one - see docs/artifact-history.md). `approval`
    # is a single overwrite-in-place event (Phase 40): this test re-approves,
    # so anchoring `v1` there would resolve - at diff time - to the *second*
    # approval's own (later) timestamp, silently sliding past the change
    # being tested. `cad` (position 1, from the generation receipt) is the
    # one category never re-triggered by anything this test does, so it's
    # the only stable anchor - same choice `test_diff_detects_cad_and_stl_changed`
    # already makes.
    _fully_approved(scad_project, monkeypatch)
    v1 = get_artifact_history(scad_project)[0]["version_id"]

    scad_path = scad_project / "cad" / "sign.scad"
    scad_path.write_text(scad_path.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
    _export_all(scad_project, monkeypatch, overwrite_stl=True, content=_DIFFERENT_STL)
    record_approval(scad_project)

    v2 = get_artifact_history(scad_project)[-1]["version_id"]
    diff = diff_artifact_versions(scad_project, v1, v2)
    assert "Validation report" in diff["changed"]


def test_diff_detects_preview_changed_category(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    v1 = get_artifact_history(scad_project)[0]["version_id"]

    scad_path = scad_project / "cad" / "sign.scad"
    scad_path.write_text(scad_path.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
    _export_all(scad_project, monkeypatch, overwrite_stl=True, content=_DIFFERENT_STL)
    record_approval(scad_project)

    v2 = get_artifact_history(scad_project)[-1]["version_id"]
    diff = diff_artifact_versions(scad_project, v1, v2)
    assert "Preview render" in diff["changed"]


def test_diff_detects_material_changed_via_reused_timeline_event(scad_project, monkeypatch):
    # material_change/printer_change/risk_change/warning_change are never
    # version-worthy on their own (see VERSION_EVENT_CATEGORIES) - a
    # change occurring between two *saved analyses* is only visible in a
    # version-to-version diff once a version-worthy event exists on each
    # side of the change (its timestamp must fall inside the compared
    # range). `approval` is a single overwrite-in-place event: this test
    # re-approves after the material change, so anchoring `v1` on `approval`
    # would - at diff time - resolve to the *second* approval's own later
    # timestamp, pushing the range's lower bound past the very
    # `material_change` event it needs to bracket. `cad` (position 1) is
    # never re-triggered here, so it stays a stable, always-earliest anchor.
    _fully_approved(scad_project, monkeypatch)
    v1 = get_artifact_history(scad_project)[0]["version_id"]
    save_analysis_snapshot(scad_project)

    _resolve_materials(scad_project, material="PETG")
    save_analysis_snapshot(scad_project)
    record_approval(scad_project)

    v2 = get_artifact_history(scad_project)[-1]["version_id"]
    diff = diff_artifact_versions(scad_project, v1, v2)
    assert "Material changed" in diff["changed"]


def test_diff_detects_printer_changed_via_reused_timeline_event(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    v1 = get_artifact_history(scad_project)[0]["version_id"]
    save_analysis_snapshot(scad_project)

    _resolve_manufacturing(scad_project, printer_id="bambu_p1s_1")
    save_analysis_snapshot(scad_project)
    record_approval(scad_project)

    v2 = get_artifact_history(scad_project)[-1]["version_id"]
    diff = diff_artifact_versions(scad_project, v1, v2)
    assert "Printer changed" in diff["changed"]


def test_diff_detects_warnings_changed_via_reused_timeline_event(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    v1 = get_artifact_history(scad_project)[-1]["version_id"]
    save_analysis_snapshot(scad_project)

    _flesh_out_brief_for_manufacturing_review(scad_project)
    _resolve_manufacturing(scad_project)
    _resolve_materials(scad_project)
    save_analysis_snapshot(scad_project)
    record_approval(scad_project)

    v2 = get_artifact_history(scad_project)[-1]["version_id"]
    diff = diff_artifact_versions(scad_project, v1, v2)
    assert "Warnings changed" in diff["changed"]


def test_diff_never_tracked_categories_always_listed_unchanged(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    history = get_artifact_history(scad_project)
    diff = diff_artifact_versions(scad_project, history[0]["version_id"], history[-1]["version_id"])
    assert "Brief" in diff["unchanged"]
    assert "Design Intent" in diff["unchanged"]
    assert "Reference Board" in diff["unchanged"]


def test_diff_unknown_version_raises(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    history = get_artifact_history(scad_project)
    with pytest.raises(UnknownVersionError):
        diff_artifact_versions(scad_project, history[0]["version_id"], 9999)
    with pytest.raises(UnknownVersionError):
        diff_artifact_versions(scad_project, 9999, history[0]["version_id"])


def test_diff_never_writes_anything(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    history = get_artifact_history(scad_project)
    before = sorted(str(p) for p in scad_project.rglob("*"))
    diff_artifact_versions(scad_project, history[0]["version_id"], history[-1]["version_id"])
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


# ---------------------------------------------------------------------------
# build_rollback_plan() - report only, never destructive
# ---------------------------------------------------------------------------


def test_rollback_plan_correctly_identifies_affected_files(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    history_before = get_artifact_history(scad_project)
    v1 = history_before[0]["version_id"]
    scad_path = scad_project / "cad" / "sign.scad"
    scad_path.write_text(scad_path.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
    _export_all(scad_project, monkeypatch, overwrite_stl=True, content=_DIFFERENT_STL)

    plan = build_rollback_plan(scad_project, v1)
    assert "CAD source" in plan["would_affect"]
    assert "STL file" in plan["would_affect"]


def test_rollback_plan_correctly_identifies_unaffected_files(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    history = get_artifact_history(scad_project)
    plan = build_rollback_plan(scad_project, history[0]["version_id"])
    assert "Brief" in plan["would_not_affect"]
    assert "Design Intent" in plan["would_not_affect"]
    assert "Reference Board" in plan["would_not_affect"]


def test_rollback_plan_reports_current_and_target_version(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    history = get_artifact_history(scad_project)
    plan = build_rollback_plan(scad_project, history[0]["version_id"])
    assert plan["current_version"] == history[-1]["version_id"]
    assert plan["target_version"] == history[0]["version_id"]


def test_rollback_plan_never_writes_anything(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    history = get_artifact_history(scad_project)
    before = sorted(str(p) for p in scad_project.rglob("*"))
    build_rollback_plan(scad_project, history[0]["version_id"])
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


def test_rollback_plan_never_restores_copies_or_deletes():
    # Structural guard: the module source must never call a file-mutation
    # primitive at all - this is a report-only phase by design.
    source = Path("src/factory/artifact_history.py").read_text(encoding="utf-8")
    for forbidden in ("shutil.copy", "shutil.move", "os.remove", "unlink(", "rmtree", "write_text", "write_bytes", "save_json"):
        assert forbidden not in source, f"artifact_history.py must never mutate files; found {forbidden!r}"


def test_rollback_plan_flags_are_all_true(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    history = get_artifact_history(scad_project)
    plan = build_rollback_plan(scad_project, history[0]["version_id"])
    assert plan["no_files_restored"] is True
    assert plan["no_files_copied"] is True
    assert plan["no_files_deleted"] is True
    assert plan["no_manifest_modified"] is True
    assert plan["dry_run"] is True


def test_rollback_plan_unknown_version_raises(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    with pytest.raises(UnknownVersionError):
        build_rollback_plan(scad_project, 9999)


def test_rollback_plan_on_project_with_no_history_raises(isolated_projects_dir):
    root = project_store.init_project("Bare Project")
    with pytest.raises(UnknownVersionError):
        build_rollback_plan(root, 1)


# ---------------------------------------------------------------------------
# summarize_artifact_history() - the compact Preview Board summary
# ---------------------------------------------------------------------------


def test_summarize_is_read_only(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    before = sorted(str(p) for p in scad_project.rglob("*"))
    summarize_artifact_history(scad_project)
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


def test_summarize_shape_with_no_history(isolated_projects_dir):
    root = project_store.init_project("Bare Project")
    summary = summarize_artifact_history(root)
    assert summary == {
        "history_available": False,
        "version_count": 0,
        "latest_version": None,
        "changed_since_previous": None,
        "current_artifact_state": None,
    }


def test_summarize_shape_with_history(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    summary = summarize_artifact_history(scad_project)
    assert summary["history_available"] is True
    assert summary["version_count"] >= 4
    assert summary["latest_version"] == summary["version_count"]
    assert isinstance(summary["changed_since_previous"], list)
    assert set(summary["current_artifact_state"].keys()) == {"validation", "preview", "review"}


def test_summarize_changed_since_previous_none_with_only_one_version(scad_project):
    summary = summarize_artifact_history(scad_project)
    assert summary["version_count"] == 1
    assert summary["changed_since_previous"] is None


# ---------------------------------------------------------------------------
# Integration: Phase 40 timeline / slicer history / export / generation
# receipt compatibility
# ---------------------------------------------------------------------------


def test_integration_with_phase_40_timeline_never_reimplemented(scad_project, monkeypatch):
    from factory.project_timeline import get_project_timeline

    _fully_approved(scad_project, monkeypatch)
    timeline_events = get_project_timeline(scad_project)
    history = get_artifact_history(scad_project)
    version_worthy = [e for e in timeline_events if e["category"] in VERSION_EVENT_CATEGORIES]
    assert len(history) == len(version_worthy)
    assert [v["source_event_id"] for v in history] == [e["event_id"] for e in version_worthy]


def test_phase_40_timeline_unaffected_by_this_phase(scad_project, monkeypatch):
    from factory.project_timeline import get_project_timeline

    _fully_approved(scad_project, monkeypatch)
    before = get_project_timeline(scad_project)
    get_artifact_history(scad_project)
    diff_artifact_versions(scad_project, 1, 1) if len(get_artifact_history(scad_project)) >= 1 else None
    after = get_project_timeline(scad_project)
    assert before == after


# ---------------------------------------------------------------------------
# Safety: no subprocess, no network, no artifact modification
# ---------------------------------------------------------------------------


def test_no_slicer_execution_no_gcode_no_network(scad_project, monkeypatch):
    import socket

    def _boom_subprocess(*a, **k):
        raise AssertionError("must never invoke a subprocess")

    def _boom_socket(*a, **k):
        raise AssertionError("must never open a network socket")

    monkeypatch.setattr(export_pipeline.subprocess, "Popen", _boom_subprocess, raising=False)
    monkeypatch.setattr(socket, "socket", _boom_socket)
    get_artifact_history(scad_project)
    summarize_artifact_history(scad_project)


def test_no_artifact_files_ever_modified_by_any_public_function(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    history = get_artifact_history(scad_project)
    stl_dir_before = sorted(p.read_bytes() for p in (scad_project / "stl").glob("*.stl"))
    diff_artifact_versions(scad_project, history[0]["version_id"], history[-1]["version_id"])
    build_rollback_plan(scad_project, history[0]["version_id"])
    stl_dir_after = sorted(p.read_bytes() for p in (scad_project / "stl").glob("*.stl"))
    assert stl_dir_before == stl_dir_after

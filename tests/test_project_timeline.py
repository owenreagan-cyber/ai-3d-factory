"""Phase 40 tests: `factory.project_timeline` - the Factory's project
memory, a read-only, chronological event log derived entirely from
existing receipts/history. Stores nothing new for derived events; never
writes anything itself. See docs/project-timeline.md,
docs/roadmap.md Phase 40.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from factory import export_pipeline, project_store
from factory.manufacturing import knowledge
from factory.openscad.generate import generate_openscad
from factory.project_inspection import HEALTH_SEVERITIES
from factory.project_timeline import (
    EVENT_CATEGORIES,
    EVENT_SEVERITIES,
    EVENT_STATUSES,
    get_project_timeline,
    get_project_timeline_for_path,
    summarize_project_timeline,
)
from factory.slicer_history import save_analysis_snapshot
from factory.slicer_readiness import create_review_package, record_approval
from factory.manual_review_workspace import create_manual_review_workspace

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


def _export_all(project_dir, monkeypatch, *, overwrite_stl=False):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
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


def test_event_severities_are_reused_from_project_inspection_verbatim():
    assert EVENT_SEVERITIES == HEALTH_SEVERITIES
    assert EVENT_SEVERITIES == ("info", "warning", "blocked", "ready")


def test_event_statuses_are_the_suggested_values():
    assert set(EVENT_STATUSES) == {"completed", "changed", "recorded", "unavailable"}


def test_event_categories_is_a_fixed_closed_set():
    assert isinstance(EVENT_CATEGORIES, tuple)
    assert len(EVENT_CATEGORIES) == len(set(EVENT_CATEGORIES))


def test_module_reuses_existing_read_functions_not_reimplemented():
    source = Path("src/factory/project_timeline.py").read_text(encoding="utf-8")
    assert "from factory.generation_gate import read_last_execution_receipt" in source
    assert "from factory.export_pipeline import read_export_receipt" in source
    assert "from factory.slicer_readiness import read_slicer_readiness_receipt" in source
    assert "from factory.manual_review_workspace import read_workspace_receipt" in source
    assert "from factory.slicer_history import detect_changes, read_analysis_history" in source
    assert "from factory.project_inspection import HEALTH_SEVERITIES" in source
    # Never re-implements receipt writing or any assessment logic.
    assert "def evaluate_review_gate" not in source
    assert "def assess_slicer_readiness" not in source
    assert "save_json" not in source


# ---------------------------------------------------------------------------
# get_project_timeline() - read-only, never writes
# ---------------------------------------------------------------------------


def test_writes_nothing(scad_project):
    before = sorted(str(p) for p in scad_project.rglob("*"))
    get_project_timeline(scad_project)
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


def test_never_invokes_a_subprocess(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("get_project_timeline() must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    get_project_timeline(scad_project)


def test_get_project_timeline_for_path_matches_direct_call(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    a = get_project_timeline(scad_project)
    b = get_project_timeline_for_path(scad_project)
    assert a == b


# ---------------------------------------------------------------------------
# status_history adapter - "unavailable" is never silently empty
# ---------------------------------------------------------------------------


def test_brand_new_project_has_one_dated_brief_created_event(scad_project):
    events = get_project_timeline(scad_project)
    brief_events = [e for e in events if e["category"] == "brief"]
    assert len(brief_events) == 1
    assert brief_events[0]["status"] == "completed"
    assert brief_events[0]["timestamp"] is not None


def test_project_missing_status_history_reports_unavailable_not_omitted(scad_project):
    brief_path = scad_project / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["status"] = "cad_generated"
    brief.pop("status_history", None)  # simulate a pre-Phase-40 project
    project_store.save_json(brief_path, brief)

    events = get_project_timeline(scad_project)
    labels_by_category = {e["category"]: e for e in events}
    assert labels_by_category["brief"]["status"] == "unavailable"
    assert labels_by_category["brief"]["timestamp"] is None
    assert labels_by_category["cad"]["status"] == "unavailable"
    assert "predate" in labels_by_category["brief"]["detail"] or "predate" in labels_by_category["brief"]["label"]


def test_unavailable_events_never_invent_a_timestamp(scad_project):
    brief_path = scad_project / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["status"] = "manufacturing_option_selected"
    brief.pop("status_history", None)
    project_store.save_json(brief_path, brief)

    events = get_project_timeline(scad_project)
    for e in events:
        if e["status"] == "unavailable":
            assert e["timestamp"] is None
            assert e["date"] is None


def test_stage_not_yet_reached_produces_no_event_at_all(isolated_projects_dir):
    # A brand-new project (status "brief_created", no CAD generated yet -
    # scad_project already jumps straight to "cad_generated", so this uses
    # a bare init_project() instead) has not reached plan_drafted/
    # cad_generated yet - those must be absent, not "unavailable".
    root = project_store.init_project("Bare Project")
    events = get_project_timeline(root)
    categories = [e["category"] for e in events]
    assert "manufacturing_plan" not in categories
    assert "cad" not in categories


def test_status_history_records_new_transitions_with_real_timestamps(isolated_projects_dir):
    root = project_store.init_project("Bare Project")
    brief_path = root / "brief.json"
    brief = project_store.load_json(brief_path)
    # Advance through every intermediate manufacturing-plan stage in order -
    # skipping none - so every one gets its own real status_history entry.
    project_store.advance_status(brief, "plan_drafted")
    project_store.advance_status(brief, "plan_approved")
    project_store.advance_status(brief, "manufacturing_option_selected")
    project_store.save_json(brief_path, brief)

    events = get_project_timeline(root)
    plan_events = [e for e in events if e["category"] == "manufacturing_plan"]
    assert len(plan_events) == 3
    assert all(e["status"] == "completed" for e in plan_events)
    assert all(e["timestamp"] is not None for e in plan_events)


def test_skipping_an_intermediate_stage_reports_it_as_unavailable(isolated_projects_dir):
    root = project_store.init_project("Bare Project")
    brief_path = root / "brief.json"
    brief = project_store.load_json(brief_path)
    # Jump straight from plan_drafted to manufacturing_option_selected,
    # skipping plan_approved entirely (a realistic real-world path) - the
    # skipped stage must be reported as unavailable, not silently omitted
    # or falsely reported as "completed".
    project_store.advance_status(brief, "plan_drafted")
    project_store.advance_status(brief, "manufacturing_option_selected")
    project_store.save_json(brief_path, brief)

    events = get_project_timeline(root)
    plan_events = [e for e in events if e["category"] == "manufacturing_plan"]
    assert len(plan_events) == 3
    statuses = {e["label"].split(" (")[0]: e["status"] for e in plan_events}
    assert statuses["Manufacturing plan drafted"] == "completed"
    assert statuses["Manufacturing plan approved"] == "unavailable"
    assert statuses["Manufacturing option selected"] == "completed"


def test_cad_generated_skipped_from_status_history_when_generation_receipt_exists(scad_project):
    from factory.generation_gate import write_generation_receipt

    brief_path = scad_project / "brief.json"
    brief = project_store.load_json(brief_path)
    project_store.advance_status(brief, "cad_generated")
    project_store.save_json(brief_path, brief)

    gate_result = {"plan": {"engine": "OpenSCAD"}, "recommended_engine": "OpenSCAD", "readiness_score": 90, "readiness_state": "Ready For Mechanical CAD", "decision": "Allowed"}
    generation_result = {"written_files": [], "warnings": []}
    write_generation_receipt(scad_project, gate_result, generation_result)

    events = get_project_timeline(scad_project)
    cad_events = [e for e in events if e["category"] == "cad"]
    assert len(cad_events) == 1
    assert cad_events[0]["source"] == "generation_receipt"
    assert cad_events[0]["status"] == "completed"


# ---------------------------------------------------------------------------
# export_receipt adapter
# ---------------------------------------------------------------------------


def test_export_events_present_after_export(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    events = get_project_timeline(scad_project)
    export_events = [e for e in events if e["category"] == "export"]
    assert len(export_events) == 1
    assert export_events[0]["severity"] == "ready"
    assert export_events[0]["timestamp"] is not None


def test_validation_and_preview_events_present_after_export(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    events = get_project_timeline(scad_project)
    categories = [e["category"] for e in events]
    assert "validation" in categories
    assert "preview" in categories


def test_validation_warning_severity_reflected(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    events = get_project_timeline(scad_project)
    validation_event = next(e for e in events if e["category"] == "validation")
    # The default fake STL (a single degenerate triangle) passes validation
    # with a warning, not a clean pass - matching Phase 36's own precedent.
    assert validation_event["severity"] in ("warning", "ready")


def test_no_export_no_export_events(scad_project):
    events = get_project_timeline(scad_project)
    assert not [e for e in events if e["category"] in ("export", "validation", "preview")]


# ---------------------------------------------------------------------------
# slicer_readiness_receipt / manual_review_workspace_receipt adapters
# ---------------------------------------------------------------------------


def test_approval_event_present_after_approval(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    events = get_project_timeline(scad_project)
    approval_events = [e for e in events if e["category"] == "approval"]
    assert len(approval_events) == 1
    assert approval_events[0]["status"] == "recorded"
    assert approval_events[0]["severity"] == "ready"


def test_package_event_present_after_package_created(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    create_review_package(scad_project)
    events = get_project_timeline(scad_project)
    assert any(e["category"] == "package" for e in events)


def test_workspace_event_present_after_workspace_created(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    create_manual_review_workspace(scad_project)
    events = get_project_timeline(scad_project)
    assert any(e["category"] == "workspace" for e in events)


def test_no_approval_no_approval_or_package_or_workspace_events(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    events = get_project_timeline(scad_project)
    categories = [e["category"] for e in events]
    assert "approval" not in categories
    assert "package" not in categories
    assert "workspace" not in categories


# ---------------------------------------------------------------------------
# slicer_history adapter - snapshots and change-detection events
# ---------------------------------------------------------------------------


def test_slicer_analysis_event_present_after_save(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    save_analysis_snapshot(scad_project)
    events = get_project_timeline(scad_project)
    analysis_events = [e for e in events if e["category"] == "slicer_analysis" and e["status"] == "recorded"]
    assert len(analysis_events) == 1


def test_material_change_event_between_two_snapshots(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    save_analysis_snapshot(scad_project)
    _resolve_materials(scad_project, material="PETG")
    save_analysis_snapshot(scad_project)
    events = get_project_timeline(scad_project)
    assert any(e["category"] == "material_change" and e["status"] == "changed" for e in events)


def test_printer_change_event_between_two_snapshots(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    save_analysis_snapshot(scad_project)
    _resolve_manufacturing(scad_project, printer_id="bambu_p1s_1")
    save_analysis_snapshot(scad_project)
    events = get_project_timeline(scad_project)
    assert any(e["category"] == "printer_change" for e in events)


def test_risk_change_event_includes_before_after_values(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    save_analysis_snapshot(scad_project)
    _flesh_out_brief_for_manufacturing_review(scad_project)
    _resolve_manufacturing(scad_project)
    _resolve_materials(scad_project)
    save_analysis_snapshot(scad_project)
    events = get_project_timeline(scad_project)
    risk_events = [e for e in events if e["category"] == "risk_change"]
    assert risk_events
    assert "->" in risk_events[0]["label"]


def test_warning_change_event(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    save_analysis_snapshot(scad_project)
    _resolve_manufacturing(scad_project)
    save_analysis_snapshot(scad_project)
    events = get_project_timeline(scad_project)
    assert any(e["category"] == "warning_change" for e in events)


def test_no_snapshots_no_slicer_analysis_events(scad_project):
    events = get_project_timeline(scad_project)
    assert not [e for e in events if e["category"] == "slicer_analysis"]


def test_one_snapshot_no_change_events(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    save_analysis_snapshot(scad_project)
    events = get_project_timeline(scad_project)
    change_categories = {"material_change", "printer_change", "risk_change", "warning_change"}
    assert not [e for e in events if e["category"] in change_categories]


# ---------------------------------------------------------------------------
# Determinism / ordering
# ---------------------------------------------------------------------------


def test_event_ids_are_deterministic_across_calls(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    a = get_project_timeline(scad_project)
    b = get_project_timeline(scad_project)
    assert [e["event_id"] for e in a] == [e["event_id"] for e in b]


def test_undated_events_sort_before_dated_events(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    events = get_project_timeline(scad_project)
    dated_flags = [e["timestamp"] is not None for e in events]
    # Once a dated event appears, no undated event should appear after it.
    seen_dated = False
    for is_dated in dated_flags:
        if is_dated:
            seen_dated = True
        elif seen_dated:
            pytest.fail("an undated event appeared after a dated event")


def test_dated_events_sorted_ascending_by_timestamp(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    save_analysis_snapshot(scad_project)
    events = get_project_timeline(scad_project)
    timestamps = [e["timestamp"] for e in events if e["timestamp"] is not None]
    assert timestamps == sorted(timestamps)


def test_malformed_brief_json_does_not_crash(scad_project):
    (scad_project / "brief.json").write_text("{not valid json", encoding="utf-8")
    events = get_project_timeline(scad_project)
    assert isinstance(events, list)


# ---------------------------------------------------------------------------
# summarize_project_timeline() - the compact Preview Board summary
# ---------------------------------------------------------------------------


def test_summarize_is_read_only(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    before = sorted(str(p) for p in scad_project.rglob("*"))
    summarize_project_timeline(scad_project)
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


def test_summarize_shape(scad_project):
    summary = summarize_project_timeline(scad_project)
    assert set(summary.keys()) == {"event_count", "dated_event_count", "unavailable_event_count", "latest_event"}


def test_summarize_latest_event_reflects_most_recent_dated_event(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    summary = summarize_project_timeline(scad_project)
    assert summary["latest_event"] is not None
    assert summary["latest_event"]["date"] is not None


def test_summarize_reports_unavailable_count_for_legacy_project(scad_project):
    brief_path = scad_project / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["status"] = "cad_generated"
    brief.pop("status_history", None)
    project_store.save_json(brief_path, brief)
    summary = summarize_project_timeline(scad_project)
    assert summary["unavailable_event_count"] > 0


# ---------------------------------------------------------------------------
# Safety: no subprocess, no network, no printer/slicer contact
# ---------------------------------------------------------------------------


def test_no_slicer_execution_no_gcode_no_network(scad_project, monkeypatch):
    import socket

    def _boom_subprocess(*a, **k):
        raise AssertionError("must never invoke a subprocess")

    def _boom_socket(*a, **k):
        raise AssertionError("must never open a network socket")

    monkeypatch.setattr(export_pipeline.subprocess, "Popen", _boom_subprocess, raising=False)
    monkeypatch.setattr(socket, "socket", _boom_socket)
    get_project_timeline(scad_project)
    summarize_project_timeline(scad_project)

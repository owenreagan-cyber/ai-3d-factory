"""Phase 42 tests: `factory.project_health` - a safe, read-only, unified
Project Health Dashboard aggregating existing Factory intelligence
(Phases 13, 26-41). This module never recalculates readiness, never
duplicates risk/validation/artifact logic, never creates new approval
rules, and never overrides an existing blocker. See docs/project-health.md,
docs/roadmap.md Phase 42.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from factory import export_pipeline, project_store
from factory.manufacturing import knowledge
from factory.openscad.generate import generate_openscad
from factory.project_health import (
    HEALTH_CATEGORY_WEIGHTS,
    HEALTH_LEVELS,
    LIFECYCLE_STAGES,
    compute_health_score,
    evaluate_project_health,
    evaluate_project_health_for_path,
    summarize_project_health,
)
from factory.slicer_history import save_analysis_snapshot
from factory.slicer_readiness import create_review_package, record_approval

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
    build_plan_path = project_dir / "build_plan.json"
    build_plan = project_store.load_json(build_plan_path)
    build_plan["selected_manufacturing_option"] = "single_piece"
    printer = knowledge.get_printer(printer_id)
    build_plan["target_printer"] = {
        "printer_id": printer_id,
        "display_name": printer["display_name"] if printer else printer_id,
        "resolved": True,
        "resolved_from": "test",
        "capabilities": None,
    }
    project_store.save_json(build_plan_path, build_plan)


def _resolve_materials(project_dir, *, material="PLA", color="white"):
    manifest_path = project_dir / "part_manifest.json"
    manifest = project_store.load_json(manifest_path)
    for part in manifest.get("parts", []):
        part["material"] = material
        part["color"] = color
    project_store.save_json(manifest_path, manifest)


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


def _force_validation_failure(project_dir):
    """Directly corrupt a validation report/receipt to simulate a real
    failed geometry validation - never runs the real validator."""
    receipt_path = project_dir / "generated" / "export_receipt.json"
    receipt = project_store.load_json(receipt_path)
    receipt["exports"][0]["validation"]["status"] = "failed"
    project_store.save_json(receipt_path, receipt)
    validation_path = project_dir / "validation" / "sign_validation.json"
    validation = project_store.load_json(validation_path)
    validation["overall_status"] = "FAIL"
    project_store.save_json(validation_path, validation)


def _force_manufacturability_block(project_dir):
    brief_path = project_dir / "brief.json"
    brief = project_store.load_json(brief_path)
    brief.setdefault("design_intent", {})["manufacturability_constraints"] = {
        "max_size_mm": [99999, 99999, 99999]
    }
    project_store.save_json(brief_path, brief)


# ---------------------------------------------------------------------------
# Vocabulary sanity
# ---------------------------------------------------------------------------


def test_health_category_weights_sum_to_one():
    assert abs(sum(HEALTH_CATEGORY_WEIGHTS.values()) - 1.0) < 1e-9


def test_lifecycle_stages_include_blocked_and_complete():
    assert "blocked" in LIFECYCLE_STAGES
    assert "complete" in LIFECYCLE_STAGES
    assert "idea" in LIFECYCLE_STAGES


def test_health_levels_vocabulary():
    assert set(HEALTH_LEVELS) == {"excellent", "good", "fair", "poor", "unknown"}


# ---------------------------------------------------------------------------
# Health calculation - complete / incomplete / blocked / missing / unknown
# ---------------------------------------------------------------------------


def test_bare_project_is_low_score_not_blocked(isolated_projects_dir):
    root = project_store.init_project("Bare Project")
    health = evaluate_project_health(root)
    assert health["overall_status"] != "Blocked"
    assert health["lifecycle_stage"] == "briefing"
    assert health["health_score"] < 30
    assert health["blockers"] == []


def test_fully_approved_project_is_ready_for_slicer_review(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    health = evaluate_project_health(scad_project)
    assert health["overall_status"] == "Ready for Slicer Review"
    assert health["lifecycle_stage"] == "slicer_review"
    assert health["blockers"] == []
    assert health["health_score"] > 50


def test_manufacturability_block_sets_blocked_status(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    _force_manufacturability_block(scad_project)
    health = evaluate_project_health(scad_project)
    assert health["overall_status"] == "Blocked"
    assert health["lifecycle_stage"] == "blocked"


def test_validation_failure_sets_blocked_status_and_blocker_message(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    _force_validation_failure(scad_project)
    health = evaluate_project_health(scad_project)
    assert health["overall_status"] == "Blocked"
    assert health["lifecycle_stage"] == "blocked"
    assert any("failed validation" in b["message"] for b in health["blockers"])


def test_score_never_bypasses_blockers(scad_project, monkeypatch):
    """A blocked project can still score numerically high on unrelated
    categories (e.g. good design intent) - `overall_status` must still say
    'Blocked' regardless of what `health_score` is."""
    _fully_approved(scad_project, monkeypatch)
    _force_manufacturability_block(scad_project)
    health = evaluate_project_health(scad_project)
    assert health["overall_status"] == "Blocked"
    assert health["health_score"] > 0  # score is not artificially zeroed


def test_no_stl_yet_is_not_a_blocker(scad_project, monkeypatch):
    """Not having exported an STL yet is a normal in-progress state, not a
    genuine obstruction - must not appear in `blockers`."""
    health = evaluate_project_health(scad_project)
    assert health["lifecycle_stage"] == "cad_generation"
    assert health["overall_status"] != "Blocked"
    assert health["blockers"] == []


def test_missing_brief_lowers_confidence(isolated_projects_dir):
    root = isolated_projects_dir / "no-brief-project"
    root.mkdir()
    for sub in project_store.PROJECT_SUBDIRS:
        (root / sub).mkdir()
    health = evaluate_project_health(root)
    assert health["confidence"] == "low"
    assert health["lifecycle_stage"] in ("idea", "intake")


def test_fully_approved_project_has_high_confidence(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    health = evaluate_project_health(scad_project)
    assert health["confidence"] == "high"


def test_unknown_validation_status_stays_unknown_not_invented(scad_project, monkeypatch):
    health = evaluate_project_health(scad_project)
    assert health["readiness_summary"]["status"] in (
        "blocked", "not_ready", "unsupported_project_state",
    )
    # No validation has run yet - the validation category score reflects
    # that honestly (0), it is never invented as "passed".
    assert health["health_score_categories"]["validation"] == 0


def test_score_changes_when_summaries_change(scad_project, monkeypatch):
    before = evaluate_project_health(scad_project)
    _export_all(scad_project, monkeypatch)
    after = evaluate_project_health(scad_project)
    assert after["health_score"] > before["health_score"]
    assert after["health_score_categories"]["artifact_completeness"] > before["health_score_categories"]["artifact_completeness"]


def test_compute_health_score_is_deterministic_and_reuses_inputs():
    readiness_assessment = {"readiness_score": 80, "validation_failure_count": 0}
    design_orchestrator_summary = {
        "score": {
            "overall": 70,
            "categories": {"intake": 80, "brief": 60, "design_intent": 50, "reference_board": 40, "manufacturing": 90},
        }
    }
    result_a = compute_health_score(
        design_orchestrator_summary=design_orchestrator_summary,
        generation_gate_summary={"decision": "Allowed"},
        generation_execution_summary={"receipt_available": True},
        export_pipeline_summary={"expected_stl_count": 2, "current_stl_count": 2, "validation_status": "passed"},
        readiness_assessment=readiness_assessment,
        selected_manufacturing_option="single_piece",
        cad_files=["cad/sign.scad"],
    )
    result_b = compute_health_score(
        design_orchestrator_summary=design_orchestrator_summary,
        generation_gate_summary={"decision": "Allowed"},
        generation_execution_summary={"receipt_available": True},
        export_pipeline_summary={"expected_stl_count": 2, "current_stl_count": 2, "validation_status": "passed"},
        readiness_assessment=readiness_assessment,
        selected_manufacturing_option="single_piece",
        cad_files=["cad/sign.scad"],
    )
    assert result_a == result_b
    assert result_a["overall"] == round(
        sum(result_a["categories"][name] * weight for name, weight in HEALTH_CATEGORY_WEIGHTS.items())
    )
    assert result_a["categories"]["cad_generation"] == 100  # receipt_available
    assert result_a["categories"]["artifact_completeness"] == 100  # 2/2
    assert result_a["categories"]["validation"] == 100  # passed
    assert result_a["categories"]["manufacturing_planning"] == 100  # selected


# ---------------------------------------------------------------------------
# Lifecycle stages
# ---------------------------------------------------------------------------


def test_lifecycle_idea_stage_no_brief(isolated_projects_dir):
    root = isolated_projects_dir / "no-brief-project"
    root.mkdir()
    for sub in project_store.PROJECT_SUBDIRS:
        (root / sub).mkdir()
    health = evaluate_project_health(root)
    assert health["lifecycle_stage"] == "idea"


def test_lifecycle_briefing_stage(isolated_projects_dir):
    root = project_store.init_project("Fresh Brief")
    health = evaluate_project_health(root)
    assert health["lifecycle_stage"] == "briefing"


def test_lifecycle_design_stage_with_design_intent(isolated_projects_dir):
    root = project_store.init_project("Design Stage")
    _flesh_out_brief_for_manufacturing_review(root)
    health = evaluate_project_health(root)
    assert health["lifecycle_stage"] == "design"


def test_lifecycle_planning_stage(isolated_projects_dir):
    root = project_store.init_project("Planning Stage")
    brief_path = root / "brief.json"
    brief = project_store.load_json(brief_path)
    project_store.advance_status(brief, "plan_drafted")
    project_store.save_json(brief_path, brief)
    health = evaluate_project_health(root)
    assert health["lifecycle_stage"] == "planning"


def test_lifecycle_cad_generation_stage(scad_project):
    health = evaluate_project_health(scad_project)
    assert health["lifecycle_stage"] == "cad_generation"


def test_lifecycle_export_stage_stale_artifacts(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    scad_path = scad_project / "cad" / "sign.scad"
    scad_path.write_text(scad_path.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
    health = evaluate_project_health(scad_project)
    assert health["lifecycle_stage"] == "export"


def test_lifecycle_validation_stage(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    # Export without validate/render - a current STL exists but hasn't
    # been validated or previewed yet.
    plan = export_pipeline.plan_export(scad_project, confirm_export=True)
    export_pipeline.run_export_pipeline(scad_project, plan)
    health = evaluate_project_health(scad_project)
    assert health["lifecycle_stage"] == "validation"


def test_lifecycle_review_preparation_stage(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    health = evaluate_project_health(scad_project)
    assert health["lifecycle_stage"] == "review_preparation"


def test_lifecycle_slicer_review_stage(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    health = evaluate_project_health(scad_project)
    assert health["lifecycle_stage"] == "slicer_review"


def test_lifecycle_complete_stage(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    brief_path = scad_project / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["status"] = "human_approved"
    project_store.save_json(brief_path, brief)
    health = evaluate_project_health(scad_project)
    assert health["lifecycle_stage"] == "complete"
    assert health["overall_status"] == "Complete"


def test_lifecycle_never_mutates_brief_status(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    brief_path = scad_project / "brief.json"
    before = project_store.load_json(brief_path)
    evaluate_project_health(scad_project)
    after = project_store.load_json(brief_path)
    assert before == after


# ---------------------------------------------------------------------------
# Aggregation - each existing layer is genuinely consumed
# ---------------------------------------------------------------------------


def test_timeline_is_consumed_via_recent_activity_and_summary(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    health = evaluate_project_health(scad_project)
    assert health["timeline_summary"]["event_count"] >= 1
    assert len(health["recent_activity"]) >= 1
    assert health["recent_activity"][0]["label"]


def test_artifact_history_is_consumed(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    health = evaluate_project_health(scad_project)
    assert health["artifact_summary"]["history_available"] is True
    assert health["artifact_summary"]["version_count"] >= 1


def test_readiness_is_consumed(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    health = evaluate_project_health(scad_project)
    assert health["readiness_summary"]["approval_status"] == "approved"
    assert health["readiness_summary"]["score"] > 0


def test_review_workspace_is_consumed(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    health = evaluate_project_health(scad_project)
    assert health["review_summary"]["workspace_status"] in (
        "ready_to_create", "workspace_created", "stale_workspace",
    )


def test_slicer_intelligence_is_consumed(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    health = evaluate_project_health(scad_project)
    assert health["slicer_summary"]["risk_level"] in ("Unknown", "Low", "Moderate", "High")
    assert isinstance(health["risks"], list)


def test_manufacturing_summary_reflects_selection(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    health = evaluate_project_health(scad_project)
    assert health["manufacturing_summary"]["selected_manufacturing_option"] == "single_piece"
    assert health["manufacturing_summary"]["printer_display_name"] != "Unknown"


def test_engine_summary_reflects_design_orchestrator(scad_project):
    health = evaluate_project_health(scad_project)
    assert health["engine_summary"]["recommended_engine"] is not None


def test_strengths_reflect_approval_and_design_intent(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    health = evaluate_project_health(scad_project)
    assert any("approval" in s.lower() for s in health["strengths"])
    assert any("design intent" in s.lower() for s in health["strengths"])


def test_material_change_reflected_via_reused_timeline_event(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    save_analysis_snapshot(scad_project)
    _resolve_materials(scad_project, material="PETG")
    save_analysis_snapshot(scad_project)
    health = evaluate_project_health(scad_project)
    assert health["timeline_summary"]["event_count"] >= 1


def test_evaluate_project_health_for_path_matches_direct_call(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    a = evaluate_project_health(scad_project)
    b = evaluate_project_health_for_path(scad_project)
    assert a["health_score"] == b["health_score"]
    assert a["lifecycle_stage"] == b["lifecycle_stage"]


def test_summarize_project_health_compact_shape(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    summary = summarize_project_health(scad_project)
    assert set(summary.keys()) == {
        "status", "score", "health_level", "lifecycle_stage", "blocker_count", "warning_count", "next_action",
    }
    assert summary["status"] == "Ready for Slicer Review"


# ---------------------------------------------------------------------------
# Safety: no writes, no mutation, no receipts changed, no subprocess/network
# ---------------------------------------------------------------------------


def test_dashboard_does_not_write_anything(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    before = sorted(str(p) for p in scad_project.rglob("*"))
    evaluate_project_health(scad_project)
    evaluate_project_health(scad_project)
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


def test_dashboard_does_not_mutate_receipts(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    receipt_path = scad_project / "generated" / "export_receipt.json"
    before = project_store.load_json(receipt_path)
    evaluate_project_health(scad_project)
    after = project_store.load_json(receipt_path)
    assert before == after


def test_dashboard_does_not_change_readiness_receipt(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    readiness_receipt_path = scad_project / "generated" / "slicer_readiness_receipt.json"
    before = project_store.load_json(readiness_receipt_path)
    evaluate_project_health(scad_project)
    after = project_store.load_json(readiness_receipt_path)
    assert before == after


def test_dashboard_does_not_approve_projects(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    evaluate_project_health(scad_project)
    receipt_path = scad_project / "generated" / "slicer_readiness_receipt.json"
    assert not receipt_path.is_file()


def test_dashboard_does_not_create_review_package(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    evaluate_project_health(scad_project)
    assert not (scad_project / "slicer_review" / "slicer_review_manifest.json").is_file()


def test_dashboard_never_invokes_a_subprocess(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)

    def _boom(*a, **k):
        raise AssertionError("read-only project health must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    evaluate_project_health(scad_project)


def test_dashboard_never_makes_a_network_call(scad_project, monkeypatch):
    import socket

    _fully_approved(scad_project, monkeypatch)

    def _boom(*a, **k):
        raise AssertionError("project health must never open a network socket")

    monkeypatch.setattr(socket, "socket", _boom)
    evaluate_project_health(scad_project)


def test_dashboard_never_modifies_committed_examples():
    example_dir = project_store.REPO_ROOT / "examples" / "storage-bin-lid"
    before = sorted(str(p) for p in example_dir.rglob("*"))
    evaluate_project_health(example_dir)
    after = sorted(str(p) for p in example_dir.rglob("*"))
    assert before == after


def test_no_automatic_print_flag_always_present(scad_project):
    health = evaluate_project_health(scad_project)
    assert health["no_automatic_print"] is True

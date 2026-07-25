"""Phase 36 tests: `factory.slicer_readiness` - the Slicer Review Readiness
Promotion and Review Package bridge.

Thin assessment/promotion layer over already-computed state - reuses
`factory.project_inspection.summarize_project()`, `factory.review_gate.
evaluate_review_gate()`, `factory.slicer.local_slicer_probe.probe_slicers()`,
and `factory.manufacturing.manifest.compute_assembly_intent()` rather than
re-implementing any of them. `assess_slicer_readiness()` is read-only;
`record_approval()` and `create_review_package()` are the only two writes,
and only ever run when explicitly called. No AI, no LLM, no network, no
Blender, no Meshy, no slicer, no printer, no automatic print submission.
See docs/slicer-readiness.md, docs/roadmap.md Phase 36.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from factory import export_pipeline, project_store, slicer_readiness
from factory.openscad.generate import generate_openscad
from factory.slicer import local_slicer_probe
from factory.slicer_readiness import (
    ApprovalNotAllowedError,
    CATEGORY_WEIGHTS,
    PackageCollisionError,
    PackageNotAllowedError,
    READINESS_RECEIPT_FILENAME,
    READINESS_STATES,
    REVIEW_PACKAGE_FILENAME,
    REVIEW_PACKAGE_README_FILENAME,
    SLICER_REVIEW_DIRNAME,
    assess_slicer_readiness,
    build_review_checklist,
    create_review_package,
    evaluate_slicer_readiness_for_path,
    read_slicer_readiness_receipt,
    record_approval,
    summarize_slicer_readiness,
)
from factory.generation_gate import GENERATED_DIRNAME

FAKE_OPENSCAD = "/fake/bin/openscad"
REPO_ROOT = project_store.REPO_ROOT


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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


def _export_all(project_dir, monkeypatch, *, confirm=True, all_steps=True):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = export_pipeline.plan_export(project_dir, confirm_export=confirm)
    return export_pipeline.run_export_pipeline(project_dir, plan, all_steps=all_steps)


def _flesh_out_brief_for_manufacturing_review(project_dir):
    """Populate design_intent + reference_board so the Design Orchestrator
    (Phase 33) readiness_state clears the "Not Ready" floor (overall score
    >= 25) - the minimum needed for slicer_readiness to ever reach
    needs_human_approval/ready_for_review_package. Mirrors the exact fixture
    shape `tests/test_generation_gate.py` already uses for the same purpose.
    """
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


def _resolve_manufacturing(project_dir, *, option="single_piece"):
    build_plan = project_store.load_json(project_dir / "build_plan.json")
    build_plan["selected_manufacturing_option"] = option
    build_plan["target_printer"] = {
        "printer_id": "test-printer",
        "display_name": "Test Printer",
        "resolved": True,
        "resolved_from": "test",
        "capabilities": None,
    }
    project_store.save_json(project_dir / "build_plan.json", build_plan)


def _fully_exported_and_ready(project_dir, monkeypatch):
    """Get `project_dir` all the way to `needs_human_approval` - every
    technical signal satisfied, only the separate human-approval step
    outstanding."""
    _flesh_out_brief_for_manufacturing_review(project_dir)
    _export_all(project_dir, monkeypatch)
    _resolve_manufacturing(project_dir)
    return project_dir


def _fully_approved(project_dir, monkeypatch, **kwargs):
    _fully_exported_and_ready(project_dir, monkeypatch)
    record_approval(project_dir, **kwargs)
    return project_dir


# ---------------------------------------------------------------------------
# Vocabulary sanity
# ---------------------------------------------------------------------------


def test_readiness_states_are_the_suggested_values():
    assert set(READINESS_STATES) == {
        "unsupported_project_state", "blocked", "not_ready", "stale_artifacts",
        "needs_validation", "needs_preview", "needs_manifest_completion",
        "needs_information", "needs_human_approval", "ready_for_review_package",
        "review_package_created",
    }


def test_category_weights_sum_to_one():
    assert sum(CATEGORY_WEIGHTS.values()) == pytest.approx(1.0)


def test_module_reuses_existing_logic_not_reimplemented():
    source = Path("src/factory/slicer_readiness.py").read_text(encoding="utf-8")
    assert "from factory.project_inspection import summarize_project" in source
    assert "from factory.review_gate import evaluate_review_gate" in source
    assert "from factory.manufacturing.manifest import compute_assembly_intent" in source
    assert "from factory.slicer.local_slicer_probe import probe_slicers" in source
    # Never re-implements mesh validation or rendering directly.
    assert "def validate_mesh" not in source
    assert "def render_preview" not in source


# ---------------------------------------------------------------------------
# _evaluate_readiness_status() - the priority-ordered decision ladder,
# unit-tested directly with synthetic inputs (same white-box style already
# used for `evaluate_generation_gate()` in test_generation_gate.py). Several
# of these branches (not_ready-from-partial-STL, needs_preview,
# needs_manifest_completion-from-unreadable-manifest) are shadowed in the
# *real* pipeline by factory.review_gate's own stricter blocking checks
# (`render_missing`/`manifest_unreadable` are hard blockers there even
# though this ladder also independently handles them) - see the "_via_
# review_gate" realistic tests above for that interaction. Testing the
# ladder directly still matters: it is the one place this repo's own
# documented decision order is pinned, and it must stay correct in
# isolation even if review_gate's current policy makes some branches
# unreachable through the CLI today.
# ---------------------------------------------------------------------------

_PASSING_REVIEW_GATE = {"result": "pass", "blocking_items": [], "warning_items": []}
_READY_ORCHESTRATOR = {"readiness_state": "Ready For Manufacturing Review"}
_CLEAN_MANIFEST = {
    "manifest_readable": True,
    "assembly_intent": None,
    "unresolved_material_parts": [],
    "unresolved_color_parts": [],
    "printer_resolved": True,
}


def _evaluate(*, stl, validation, preview, manifest, review_gate_result=None, approval_status="not_approved", package_status="not_created"):
    return slicer_readiness._evaluate_readiness_status(
        review_gate_result=review_gate_result or _PASSING_REVIEW_GATE,
        design_orchestrator_summary=_READY_ORCHESTRATOR,
        stl=stl,
        validation=validation,
        preview=preview,
        manifest=manifest,
        approval_status=approval_status,
        package_status=package_status,
        blocking_reasons=[],
        warnings=[],
    )


def test_evaluate_readiness_status_not_ready_branch():
    status = _evaluate(
        stl={"expected": 1, "current": 0, "stale": 0, "missing": 1},
        validation={"statuses": [], "pass_count": 0, "warning_count": 0, "failure_count": 0, "not_run_count": 0},
        preview={"current": 0, "stale": 0, "missing": 0, "statuses": []},
        manifest=_CLEAN_MANIFEST,
    )
    assert status == "not_ready"


def test_evaluate_readiness_status_needs_preview_branch():
    status = _evaluate(
        stl={"expected": 1, "current": 1, "stale": 0, "missing": 0},
        validation={"statuses": ["passed"], "pass_count": 1, "warning_count": 0, "failure_count": 0, "not_run_count": 0},
        preview={"current": 0, "stale": 0, "missing": 1, "statuses": []},
        manifest=_CLEAN_MANIFEST,
    )
    assert status == "needs_preview"


def test_evaluate_readiness_status_needs_manifest_completion_branch():
    status = _evaluate(
        stl={"expected": 1, "current": 1, "stale": 0, "missing": 0},
        validation={"statuses": ["passed"], "pass_count": 1, "warning_count": 0, "failure_count": 0, "not_run_count": 0},
        preview={"current": 1, "stale": 0, "missing": 0, "statuses": ["passed"]},
        manifest={**_CLEAN_MANIFEST, "manifest_readable": False},
    )
    assert status == "needs_manifest_completion"


def test_evaluate_readiness_status_review_gate_warn_is_not_blocking():
    warn_result = {
        "result": "warn",
        "blocking_items": [],
        "warning_items": [{"message": "No manufacturing option has been selected yet."}],
    }
    status = _evaluate(
        stl={"expected": 1, "current": 1, "stale": 0, "missing": 0},
        validation={"statuses": ["passed"], "pass_count": 1, "warning_count": 0, "failure_count": 0, "not_run_count": 0},
        preview={"current": 1, "stale": 0, "missing": 0, "statuses": ["passed"]},
        manifest=_CLEAN_MANIFEST,
        review_gate_result=warn_result,
    )
    assert status == "needs_human_approval"


def test_evaluate_readiness_status_fully_ready_reaches_ready_for_package():
    status = _evaluate(
        stl={"expected": 1, "current": 1, "stale": 0, "missing": 0},
        validation={"statuses": ["passed"], "pass_count": 1, "warning_count": 0, "failure_count": 0, "not_run_count": 0},
        preview={"current": 1, "stale": 0, "missing": 0, "statuses": ["passed"]},
        manifest=_CLEAN_MANIFEST,
        approval_status="approved",
        package_status="not_created",
    )
    assert status == "ready_for_review_package"


# ---------------------------------------------------------------------------
# assess_slicer_readiness() - read-only, never writes
# ---------------------------------------------------------------------------


def test_assess_writes_nothing(scad_project):
    before = sorted(str(p) for p in scad_project.rglob("*"))
    assess_slicer_readiness(scad_project)
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after
    assert not (scad_project / GENERATED_DIRNAME / READINESS_RECEIPT_FILENAME).exists()
    assert not (scad_project / SLICER_REVIEW_DIRNAME / REVIEW_PACKAGE_FILENAME).exists()


def test_assess_dry_run_flags_always_true(scad_project):
    assessment = assess_slicer_readiness(scad_project)
    assert assessment["dry_run"] is True
    assert assessment["no_automatic_print"] is True


def test_assess_never_invokes_a_subprocess(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("assess_slicer_readiness() must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    assess_slicer_readiness(scad_project)


def test_no_stl_at_all_is_blocked_via_review_gate(scad_project):
    """`factory.review_gate` already treats a project with zero STL files as
    a hard blocker (`no_stl_files`) - `_evaluate_readiness_status()` checks
    `review_gate_result["result"] == "fail"` first and inherits that,
    reporting `"blocked"` rather than re-deriving its own answer. See
    `test_evaluate_readiness_status_not_ready_branch` below for the
    `"not_ready"` branch itself, unit-tested directly with a passing
    review-gate result (the scenario it actually guards: some STL exist but
    not the full expected set).
    """
    assessment = assess_slicer_readiness(scad_project)
    assert assessment["readiness_status"] == "blocked"
    assert assessment["ready_for_slicer_review"] is False
    assert assessment["review_gate_status"] == "fail"


def test_stale_stl_detected(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    # Touch the CAD source so the exported STL is now stale relative to it.
    scad_path = scad_project / "cad" / "sign.scad"
    scad_path.write_text(scad_path.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
    assessment = assess_slicer_readiness(scad_project)
    assert assessment["readiness_status"] == "stale_artifacts"
    assert assessment["stale_stl_count"] > 0


def test_missing_validation_needs_validation(scad_project, monkeypatch):
    # review_gate treats missing render as a hard blocker but missing
    # validation as only a warning (docs/review-gate.md) - so a render
    # without validation is the one realistic way to reach
    # needs_validation via the real pipeline, rather than being shadowed by
    # review_gate's own stricter "fail".
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = export_pipeline.plan_export(scad_project, confirm_export=True)
    export_pipeline.run_export_pipeline(scad_project, plan, validate=False, render=True)
    assessment = assess_slicer_readiness(scad_project)
    assert assessment["readiness_status"] == "needs_validation"
    assert assessment["ready_for_slicer_review"] is False


def test_validation_failure_blocks(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch, content=b"not an stl at all")
    plan = export_pipeline.plan_export(scad_project, confirm_export=True)
    export_pipeline.run_export_pipeline(scad_project, plan, all_steps=True)
    assessment = assess_slicer_readiness(scad_project)
    assert assessment["readiness_status"] == "blocked"
    assert assessment["ready_for_slicer_review"] is False


def test_validation_warning_is_visible_but_not_blocking(scad_project, monkeypatch):
    # The default fake STL content (a single triangle) passes validation with
    # a warning (e.g. non-manifold/too-simple geometry) rather than failing
    # outright or passing cleanly - exactly the "visible warning" case.
    _export_all(scad_project, monkeypatch)
    _flesh_out_brief_for_manufacturing_review(scad_project)
    _resolve_manufacturing(scad_project)
    assessment = assess_slicer_readiness(scad_project)
    assert assessment["readiness_status"] != "blocked"
    if assessment["validation_warning_count"]:
        assert any("warning" in w.lower() for w in assessment["warnings"])


def test_technically_ready_reaches_needs_human_approval(scad_project, monkeypatch):
    _fully_exported_and_ready(scad_project, monkeypatch)
    assessment = assess_slicer_readiness(scad_project)
    assert assessment["readiness_status"] == "needs_human_approval"
    assert assessment["human_approval_required"] is True
    assert assessment["ready_for_slicer_review"] is False


def test_missing_preview_is_blocked_via_review_gate(scad_project, monkeypatch):
    """review_gate treats a missing render as a hard blocker
    (`render_missing`) regardless of validation state - so in the real
    pipeline, missing-preview is shadowed by "blocked" rather than ever
    surfacing slicer_readiness's own `"needs_preview"` state. See
    `test_evaluate_readiness_status_needs_preview_branch` for that branch
    unit-tested directly."""
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = export_pipeline.plan_export(scad_project, confirm_export=True)
    export_pipeline.run_export_pipeline(scad_project, plan, validate=True, render=False)
    assessment = assess_slicer_readiness(scad_project)
    assert assessment["readiness_status"] == "blocked"
    assert assessment["ready_for_slicer_review"] is False


def test_malformed_manifest_after_export_is_blocked_via_review_gate(scad_project, monkeypatch):
    """review_gate treats `manifest_unreadable` as a hard blocker too - so a
    manifest corrupted after an otherwise-complete export is shadowed by
    "blocked", not slicer_readiness's own `"needs_manifest_completion"`. See
    `test_evaluate_readiness_status_needs_manifest_completion_branch` for
    that branch unit-tested directly."""
    _export_all(scad_project, monkeypatch)
    (scad_project / "part_manifest.json").write_text("{not valid json", encoding="utf-8")
    assessment = assess_slicer_readiness(scad_project)
    assert assessment["readiness_status"] == "blocked"
    assert assessment["manifest_status"] == "missing_or_unreadable"


def test_multipart_incomplete_blocks(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    build_plan = project_store.load_json(scad_project / "build_plan.json")
    build_plan["selected_manufacturing_option"] = "multipart_color"
    project_store.save_json(scad_project / "build_plan.json", build_plan)
    assessment = assess_slicer_readiness(scad_project)
    assert assessment["readiness_status"] == "blocked"
    assert assessment["multipart_status"] == "multipart_incomplete"


def test_multipart_ready_is_not_blocked_by_multipart_status(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    build_plan = project_store.load_json(scad_project / "build_plan.json")
    build_plan["selected_manufacturing_option"] = "single_piece"
    project_store.save_json(scad_project / "build_plan.json", build_plan)
    assessment = assess_slicer_readiness(scad_project)
    assert assessment["multipart_status"] == "single_piece_ready"
    assert assessment["readiness_status"] != "blocked"


def test_material_missing_is_warning_in_needs_manifest_completion(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    manifest = project_store.load_json(scad_project / "part_manifest.json")
    for part in manifest.get("parts", []):
        part["material"] = "TBD - human decision"
    project_store.save_json(scad_project / "part_manifest.json", manifest)
    _resolve_manufacturing(scad_project)
    assessment = assess_slicer_readiness(scad_project)
    assert assessment["readiness_status"] == "needs_manifest_completion"
    assert assessment["material_status"] == "unresolved"
    assert any("Material unconfirmed" in w for w in assessment["warnings"])


def test_printer_missing_is_needs_manifest_completion(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    assessment = assess_slicer_readiness(scad_project)
    assert assessment["readiness_status"] == "needs_manifest_completion"
    assert assessment["printer_status"] == "unresolved"
    assert any("printer" in w.lower() for w in assessment["warnings"])


def test_missing_receipts_reported_honestly(scad_project):
    assessment = assess_slicer_readiness(scad_project)
    assert assessment["export_receipt_status"] == "missing"
    assert assessment["generation_receipt_status"] == "missing"


def test_malformed_readiness_receipt_does_not_crash(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    receipt_path = scad_project / GENERATED_DIRNAME / READINESS_RECEIPT_FILENAME
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text("{not valid json", encoding="utf-8")
    assessment = assess_slicer_readiness(scad_project)
    assert assessment["approval_status"] == "not_approved"
    assert assessment["package_status"] == "not_created"


def test_score_is_deterministic(scad_project, monkeypatch):
    _fully_exported_and_ready(scad_project, monkeypatch)
    a = assess_slicer_readiness(scad_project)
    b = assess_slicer_readiness(scad_project)
    assert a["readiness_score"] == b["readiness_score"]
    assert a["readiness_sub_scores"] == b["readiness_sub_scores"]


def test_score_cannot_bypass_a_hard_blocker(scad_project, monkeypatch):
    # A validation failure blocks regardless of how high other sub-scores are.
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch, content=b"not an stl at all")
    plan = export_pipeline.plan_export(scad_project, confirm_export=True)
    export_pipeline.run_export_pipeline(scad_project, plan, all_steps=True)
    _flesh_out_brief_for_manufacturing_review(scad_project)
    _resolve_manufacturing(scad_project)
    assessment = assess_slicer_readiness(scad_project)
    assert assessment["readiness_status"] == "blocked"
    assert assessment["ready_for_slicer_review"] is False
    # Even if the score happens to be high, status (not score) gates review.
    assert assessment["readiness_status"] not in ("ready_for_review_package", "review_package_created")


def test_readiness_score_never_exceeds_100(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    assessment = assess_slicer_readiness(scad_project)
    assert 0 <= assessment["readiness_score"] <= 100


def test_evaluate_slicer_readiness_for_path_matches_assess(scad_project, monkeypatch):
    _fully_exported_and_ready(scad_project, monkeypatch)
    a = assess_slicer_readiness(scad_project)
    b = evaluate_slicer_readiness_for_path(scad_project)
    assert a == b


# ---------------------------------------------------------------------------
# Human approval - separate, explicit, never automatic
# ---------------------------------------------------------------------------


def test_approval_required_before_package(scad_project, monkeypatch):
    _fully_exported_and_ready(scad_project, monkeypatch)
    with pytest.raises(PackageNotAllowedError):
        create_review_package(scad_project)


def test_approval_not_allowed_before_technically_ready(scad_project):
    with pytest.raises(ApprovalNotAllowedError):
        record_approval(scad_project)


def test_approval_not_allowed_when_blocked(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch, content=b"not an stl at all")
    plan = export_pipeline.plan_export(scad_project, confirm_export=True)
    export_pipeline.run_export_pipeline(scad_project, plan, all_steps=True)
    with pytest.raises(ApprovalNotAllowedError):
        record_approval(scad_project)


def test_approval_records_artifact_fingerprints(scad_project, monkeypatch):
    _fully_exported_and_ready(scad_project, monkeypatch)
    result = record_approval(scad_project, note="ship it")
    assert result["artifact_fingerprints"]
    assert all(fp.startswith("sha256:") for fp in result["artifact_fingerprints"].values())
    receipt = read_slicer_readiness_receipt(scad_project)
    assert receipt["approval"]["approved"] is True
    assert receipt["approval"]["note"] == "ship it"


def test_approval_invalidated_when_source_changes(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    assert assess_slicer_readiness(scad_project)["approval_status"] == "approved"

    scad_path = scad_project / "cad" / "sign.scad"
    scad_path.write_text(scad_path.read_text(encoding="utf-8") + "\n// changed after approval\n", encoding="utf-8")

    assessment = assess_slicer_readiness(scad_project)
    assert assessment["approval_status"] == "invalidated"
    assert assessment["human_approval_required"] is True


def test_approval_never_invokes_a_subprocess(scad_project, monkeypatch):
    _fully_exported_and_ready(scad_project, monkeypatch)

    def _boom(*a, **k):
        raise AssertionError("record_approval() must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    record_approval(scad_project)


def test_approval_never_creates_a_package(scad_project, monkeypatch):
    _fully_exported_and_ready(scad_project, monkeypatch)
    record_approval(scad_project)
    assert not (scad_project / SLICER_REVIEW_DIRNAME / REVIEW_PACKAGE_FILENAME).exists()


def test_approval_preserves_prior_receipt_fields(scad_project, monkeypatch):
    _fully_exported_and_ready(scad_project, monkeypatch)
    scad_project_receipt_path = scad_project / GENERATED_DIRNAME / READINESS_RECEIPT_FILENAME
    scad_project_receipt_path.parent.mkdir(parents=True, exist_ok=True)
    project_store.save_json(scad_project_receipt_path, {"project": str(scad_project), "custom_marker": "keep-me"})
    record_approval(scad_project, note="ok")
    receipt = read_slicer_readiness_receipt(scad_project)
    assert receipt["custom_marker"] == "keep-me"
    assert receipt["approval"]["approved"] is True


# ---------------------------------------------------------------------------
# Review package creation - the second write path
# ---------------------------------------------------------------------------


def test_package_requires_confirmation_semantics_via_error(scad_project, monkeypatch):
    """`create_review_package()` itself has no dry-run flag - the CLI is
    responsible for gating it behind `--create-package --confirm-package`.
    Directly calling it while not yet approved is the module-level
    equivalent of "did not confirm" and must raise, not silently write."""
    _fully_exported_and_ready(scad_project, monkeypatch)
    with pytest.raises(PackageNotAllowedError):
        create_review_package(scad_project)
    assert not (scad_project / SLICER_REVIEW_DIRNAME / REVIEW_PACKAGE_FILENAME).exists()


def test_blocked_project_creates_no_package(scad_project):
    with pytest.raises(PackageNotAllowedError):
        create_review_package(scad_project)
    assert not (scad_project / SLICER_REVIEW_DIRNAME / REVIEW_PACKAGE_FILENAME).exists()


def test_package_references_current_stl_not_copies(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    result = create_review_package(scad_project)
    manifest = result["manifest"]
    for ref in manifest["source_cad_references"]:
        assert ref is not None
    package_dir = scad_project / SLICER_REVIEW_DIRNAME
    assert not any(p.suffix == ".stl" for p in package_dir.rglob("*"))


def test_package_contains_validation_and_preview_references(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    result = create_review_package(scad_project)
    manifest = result["manifest"]
    assert manifest["export_receipt_path"] == f"{GENERATED_DIRNAME}/{export_pipeline.EXPORT_RECEIPT_FILENAME}"
    assert (scad_project / manifest["export_receipt_path"]).is_file()


def test_package_contains_checklist(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    result = create_review_package(scad_project)
    checklist = result["manifest"]["human_checklist"]
    assert checklist
    assert any("Material" in item for item in checklist)
    assert any("Approval" in item for item in checklist)


def test_package_declares_no_automatic_print(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    result = create_review_package(scad_project)
    assert result["manifest"]["auto_print_allowed"] is False
    readme = Path(result["readme_path"]).read_text(encoding="utf-8")
    assert "No automatic print" in readme


def test_package_conforms_to_existing_schema(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    result = create_review_package(scad_project)
    schema = json.loads((REPO_ROOT / "schemas" / "slicer_review.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(result["manifest"], schema)


def test_package_collision_protection(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    create_review_package(scad_project)
    with pytest.raises(PackageCollisionError):
        create_review_package(scad_project)


def test_package_overwrite_true_allows_recreation(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    create_review_package(scad_project)
    result = create_review_package(scad_project, overwrite=True)
    assert Path(result["package_path"]).is_file()


def test_prior_package_preserved_when_recreation_not_confirmed(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    first = create_review_package(scad_project)
    first_bytes = Path(first["package_path"]).read_bytes()
    with pytest.raises(PackageCollisionError):
        create_review_package(scad_project)
    assert Path(first["package_path"]).read_bytes() == first_bytes


def test_stale_package_detected_after_source_change(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    create_review_package(scad_project)
    assert assess_slicer_readiness(scad_project)["package_status"] == "current"

    scad_path = scad_project / "cad" / "sign.scad"
    scad_path.write_text(scad_path.read_text(encoding="utf-8") + "\n// changed after package\n", encoding="utf-8")

    assert assess_slicer_readiness(scad_project)["package_status"] == "stale"


def test_package_creation_writes_receipt_package_block(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    create_review_package(scad_project)
    receipt = read_slicer_readiness_receipt(scad_project)
    assert "package" in receipt
    assert receipt["package"]["package_path"] == f"{SLICER_REVIEW_DIRNAME}/{REVIEW_PACKAGE_FILENAME}"
    # The approval block from the earlier write must survive the merge.
    assert receipt["approval"]["approved"] is True


def test_package_never_invokes_a_subprocess(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)

    def _boom(*a, **k):
        raise AssertionError("create_review_package() must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    create_review_package(scad_project)


def test_build_review_checklist_includes_multipart_items_only_when_relevant(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    assessment = assess_slicer_readiness(scad_project)
    from factory.slicer_readiness import _manifest_assessment

    manifest = _manifest_assessment(scad_project)
    checklist = build_review_checklist(scad_project, assessment, manifest)
    assert not any("AMS slot mapping" in item for item in checklist)


def test_readme_rendered_with_warnings_section(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    result = create_review_package(scad_project)
    readme = Path(result["readme_path"]).read_text(encoding="utf-8")
    assert "## Warnings to review" in readme
    assert "## Human checklist" in readme


# ---------------------------------------------------------------------------
# Local slicer detection - read-only, advisory only
# ---------------------------------------------------------------------------


def test_slicer_probe_reused_not_reimplemented(scad_project):
    assessment = assess_slicer_readiness(scad_project)
    assert assessment["detected_slicers"] == local_slicer_probe.probe_slicers()


def test_absent_slicer_is_advisory_not_blocking(scad_project, monkeypatch):
    monkeypatch.setattr(slicer_readiness, "probe_slicers", lambda: [{"name": "Bambu Studio", "found": False}])
    _fully_exported_and_ready(scad_project, monkeypatch)
    assessment = assess_slicer_readiness(scad_project)
    assert assessment["local_slicer_status"] == "not_detected"
    assert assessment["readiness_status"] != "blocked"
    assert any("No local slicer detected" in a for a in assessment["advisories"])


def test_readiness_never_launches_a_slicer(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must never launch a slicer binary")

    monkeypatch.setattr(export_pipeline.subprocess, "Popen", _boom, raising=False)
    _fully_approved(scad_project, monkeypatch)
    create_review_package(scad_project)


# ---------------------------------------------------------------------------
# summarize_slicer_readiness() - the compact Preview Board summary
# ---------------------------------------------------------------------------


def test_summarize_slicer_readiness_is_read_only(scad_project, monkeypatch):
    _fully_exported_and_ready(scad_project, monkeypatch)
    before = sorted(str(p) for p in scad_project.rglob("*"))
    summarize_slicer_readiness(scad_project)
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


def test_summarize_slicer_readiness_shape(scad_project, monkeypatch):
    _fully_exported_and_ready(scad_project, monkeypatch)
    summary = summarize_slicer_readiness(scad_project)
    assert set(summary.keys()) == {
        "status", "score", "ready_for_package", "human_approval_required",
        "approval_status", "stl_status", "validation_status", "preview_status",
        "manifest_status", "package_status", "blocker_count", "warning_count",
        "next_action",
    }
    assert summary["status"] == "needs_human_approval"


def test_summarize_slicer_readiness_reflects_approval(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    summary = summarize_slicer_readiness(scad_project)
    assert summary["approval_status"] == "approved"
    assert summary["ready_for_package"] is True

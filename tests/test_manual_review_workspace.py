"""Phase 37 tests: `factory.manual_review_workspace` - the Manual Review
Workspace, the Factory's first true pre-slicer review workspace.

Thin organizing layer over already-computed state - reuses
`factory.slicer_readiness.assess_slicer_readiness()` for every technical/
approval/package signal, and `factory.manufacturing.knowledge` for local
printer/material reference data, rather than re-implementing either.
`assess_manual_review_workspace()` is read-only;
`create_manual_review_workspace()` is the only write, and only ever runs
when explicitly called. No AI, no LLM, no network, no slicer launch, no
G-code generation, no automatic printing. See
docs/manual-review-workspace.md, docs/roadmap.md Phase 37.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from factory import export_pipeline, project_store
from factory.manufacturing import knowledge
from factory.openscad.generate import generate_openscad
from factory.slicer import local_slicer_probe
from factory.slicer_readiness import create_review_package, record_approval
from factory.manual_review_workspace import (
    WORKSPACE_DIRNAME,
    WORKSPACE_MANIFEST_FILENAME,
    WORKSPACE_RECEIPT_FILENAME,
    WORKSPACE_STATES,
    WorkspaceCollisionError,
    WorkspaceNotAllowedError,
    assess_manual_review_workspace,
    create_manual_review_workspace,
    evaluate_manual_review_workspace_for_path,
    read_workspace_receipt,
    summarize_manual_review_workspace,
)
from factory.generation_gate import GENERATED_DIRNAME

FAKE_OPENSCAD = "/fake/bin/openscad"


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


@pytest.fixture()
def multipart_scad_project(isolated_projects_dir):
    root = project_store.init_project("Demo Multipart")
    generate_openscad(root, "multipart-nameplate", "Hi")
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


def _export_all(project_dir, monkeypatch, *, confirm=True, all_steps=True, validate=False, render=False, overwrite_stl=False):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = export_pipeline.plan_export(project_dir, confirm_export=confirm, overwrite_stl=overwrite_stl)
    return export_pipeline.run_export_pipeline(project_dir, plan, all_steps=all_steps, validate=validate, render=render)


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


def _resolve_manufacturing(project_dir, *, option="single_piece", printer_id="bambu_h2d"):
    build_plan = project_store.load_json(project_dir / "build_plan.json")
    build_plan["selected_manufacturing_option"] = option
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


def _fully_ready(project_dir, monkeypatch, **resolve_kwargs):
    """Get `project_dir` all the way to `needs_approval` - every technical
    signal satisfied, only the separate approval step outstanding."""
    _flesh_out_brief_for_manufacturing_review(project_dir)
    _export_all(project_dir, monkeypatch)
    _resolve_manufacturing(project_dir, **resolve_kwargs)
    _resolve_materials(project_dir)
    return project_dir


def _fully_approved(project_dir, monkeypatch, **kwargs):
    _fully_ready(project_dir, monkeypatch)
    record_approval(project_dir, **kwargs)
    return project_dir


def _fully_packaged(project_dir, monkeypatch, **kwargs):
    _fully_approved(project_dir, monkeypatch, **kwargs)
    create_review_package(project_dir)
    return project_dir


# ---------------------------------------------------------------------------
# Vocabulary sanity
# ---------------------------------------------------------------------------


def test_workspace_states_are_the_suggested_values():
    assert set(WORKSPACE_STATES) == {
        "not_ready", "needs_approval", "ready_to_create", "stale_workspace", "workspace_created",
    }


def test_module_reuses_existing_logic_not_reimplemented():
    source = Path("src/factory/manual_review_workspace.py").read_text(encoding="utf-8")
    assert "from factory.slicer_readiness import" in source
    assert "assess_slicer_readiness" in source
    assert "from factory.manufacturing import knowledge" in source
    # Never re-implements mesh validation, rendering, or slicer probing directly.
    assert "def validate_mesh" not in source
    assert "def render_preview" not in source
    assert "def probe_slicers" not in source
    assert "def evaluate_review_gate" not in source


# ---------------------------------------------------------------------------
# assess_manual_review_workspace() - read-only, never writes
# ---------------------------------------------------------------------------


def test_assess_writes_nothing(scad_project):
    before = sorted(str(p) for p in scad_project.rglob("*"))
    assess_manual_review_workspace(scad_project)
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after
    assert not (scad_project / GENERATED_DIRNAME / WORKSPACE_RECEIPT_FILENAME).exists()
    assert not (scad_project / WORKSPACE_DIRNAME / WORKSPACE_MANIFEST_FILENAME).exists()


def test_assess_dry_run_flags_always_true(scad_project):
    workspace = assess_manual_review_workspace(scad_project)
    assert workspace["dry_run"] is True
    assert workspace["no_automatic_print"] is True


def test_assess_never_invokes_a_subprocess(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("assess_manual_review_workspace() must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    assess_manual_review_workspace(scad_project)


def test_no_stl_is_not_ready(scad_project):
    workspace = assess_manual_review_workspace(scad_project)
    assert workspace["workspace_status"] == "not_ready"
    assert workspace["technical_readiness"] == "blocked"


def test_technically_ready_reaches_needs_approval(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    workspace = assess_manual_review_workspace(scad_project)
    assert workspace["workspace_status"] == "needs_approval"
    assert workspace["technical_readiness"] == "needs_human_approval"


def test_approved_reaches_ready_to_create(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    workspace = assess_manual_review_workspace(scad_project)
    assert workspace["workspace_status"] == "ready_to_create"
    assert workspace["approval_status"] == "approved"


def test_evaluate_manual_review_workspace_for_path_matches_assess(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    a = assess_manual_review_workspace(scad_project)
    b = evaluate_manual_review_workspace_for_path(scad_project)
    assert a == b


# ---------------------------------------------------------------------------
# Printer profile inspection
# ---------------------------------------------------------------------------


def test_printer_resolved_reports_known_profile_fields(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch, printer_id="bambu_h2d")
    workspace = assess_manual_review_workspace(scad_project)
    printer = workspace["printer_summary"]
    assert printer["resolved"] is True
    assert printer["display_name"] == "Bambu Lab H2D"
    assert printer["nozzle_mm"] == 0.4
    assert printer["ams_available"] is True
    assert isinstance(printer["build_volume_mm"], dict)
    # Layer height is never present in this repo's printer knowledge base -
    # always honestly "Unknown", never invented.
    assert printer["layer_height_mm"] == "Unknown"


def test_missing_printer_reports_unknown_never_invented(scad_project):
    workspace = assess_manual_review_workspace(scad_project)
    printer = workspace["printer_summary"]
    assert printer["resolved"] is False
    assert printer["display_name"] == "Unknown"
    assert printer["nozzle_mm"] == "Unknown"
    assert printer["layer_height_mm"] == "Unknown"
    assert printer["build_volume_mm"] == "Unknown"
    assert printer["ams_available"] == "Unknown"


def test_resolved_but_unknown_printer_id_reports_unknown_profile(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    build_plan = project_store.load_json(scad_project / "build_plan.json")
    build_plan["target_printer"] = {
        "printer_id": "totally_unknown_printer",
        "display_name": "Some Printer",
        "resolved": True,
        "resolved_from": "test",
        "capabilities": None,
    }
    project_store.save_json(scad_project / "build_plan.json", build_plan)
    workspace = assess_manual_review_workspace(scad_project)
    printer = workspace["printer_summary"]
    assert printer["resolved"] is True
    assert printer["display_name"] == "Some Printer"
    assert printer["nozzle_mm"] == "Unknown"
    assert printer["ams_available"] == "Unknown"


def test_printer_inspection_never_installs_or_launches_a_slicer(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must never launch a slicer or install anything")

    monkeypatch.setattr(export_pipeline.subprocess, "Popen", _boom, raising=False)
    _fully_ready(scad_project, monkeypatch, printer_id="bambu_h2d")
    assess_manual_review_workspace(scad_project)


# ---------------------------------------------------------------------------
# Material profile inspection
# ---------------------------------------------------------------------------


def test_missing_material_reports_unresolved(scad_project, monkeypatch):
    _flesh_out_brief_for_manufacturing_review(scad_project)
    _export_all(scad_project, monkeypatch)
    _resolve_manufacturing(scad_project)
    _resolve_materials(scad_project, material="TBD - human decision", color="TBD - human decision")
    workspace = assess_manual_review_workspace(scad_project)
    material = workspace["material_summary"]
    assert material["unresolved_material_parts"]
    assert material["unresolved_color_parts"]
    assert any("Material unconfirmed" in w for w in workspace["warnings"])
    assert any("Color unconfirmed" in w for w in workspace["warnings"])


def test_resolved_material_matches_knowledge_base_profile(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    workspace = assess_manual_review_workspace(scad_project)
    part = workspace["material_summary"]["parts"][0]
    assert part["material"] == "PLA"
    assert part["material_profile"] is not None
    assert part["material_profile"]["material_id"] == "pla"


def test_unmatched_material_string_reports_no_invented_profile(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch, )
    _resolve_materials(scad_project, material="Some Exotic Filament Nobody Has Heard Of")
    workspace = assess_manual_review_workspace(scad_project)
    part = workspace["material_summary"]["parts"][0]
    assert part["material_profile"] is None


def test_multi_material_detected_across_parts(multipart_scad_project, monkeypatch):
    _flesh_out_brief_for_manufacturing_review(multipart_scad_project)
    _export_all(multipart_scad_project, monkeypatch)
    _resolve_manufacturing(multipart_scad_project, option="multipart_color")
    manifest = project_store.load_json(multipart_scad_project / "part_manifest.json")
    materials = ["PLA", "PETG"]
    for i, part in enumerate(manifest.get("parts", [])):
        part["material"] = materials[i % len(materials)]
        part["color"] = "white"
    project_store.save_json(multipart_scad_project / "part_manifest.json", manifest)
    workspace = assess_manual_review_workspace(multipart_scad_project)
    assert workspace["material_summary"]["multi_material"] is True


# ---------------------------------------------------------------------------
# Multipart / AMS checklist categories - only included when supported by data
# ---------------------------------------------------------------------------


def test_multipart_project_includes_multipart_assembly_category(multipart_scad_project, monkeypatch):
    _fully_ready(multipart_scad_project, monkeypatch)
    workspace = assess_manual_review_workspace(multipart_scad_project)
    categories = [c["category"] for c in workspace["review_checklist"]]
    assert "Multipart Assembly" in categories


def test_single_part_project_excludes_multipart_assembly_category(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    workspace = assess_manual_review_workspace(scad_project)
    categories = [c["category"] for c in workspace["review_checklist"]]
    assert "Multipart Assembly" not in categories


def test_ams_supported_printer_includes_ams_category(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch, printer_id="bambu_h2d")
    workspace = assess_manual_review_workspace(scad_project)
    categories = [c["category"] for c in workspace["review_checklist"]]
    assert "AMS" in categories


def test_non_ams_printer_single_material_excludes_ams_category(scad_project, monkeypatch):
    printers = knowledge.load_printers()
    non_ams_id = next(
        (pid for pid, p in printers.items() if not p.get("ams_supported")), None
    )
    if non_ams_id is None:
        pytest.skip("no non-AMS printer available in the local knowledge base")
    _fully_ready(scad_project, monkeypatch, printer_id=non_ams_id)
    workspace = assess_manual_review_workspace(scad_project)
    categories = [c["category"] for c in workspace["review_checklist"]]
    assert "AMS" not in categories


def test_checklist_never_invents_a_category_without_supporting_data(scad_project):
    workspace = assess_manual_review_workspace(scad_project)
    categories = [c["category"] for c in workspace["review_checklist"]]
    assert "Multipart Assembly" not in categories
    assert "AMS" not in categories
    assert "Build Volume" not in categories


def test_checklist_always_includes_human_approval_category(scad_project):
    workspace = assess_manual_review_workspace(scad_project)
    categories = [c["category"] for c in workspace["review_checklist"]]
    assert "Human Approval" in categories


# ---------------------------------------------------------------------------
# Review confidence / remaining risk - deterministic
# ---------------------------------------------------------------------------


def test_review_confidence_and_risk_are_deterministic(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    a = assess_manual_review_workspace(scad_project)
    b = assess_manual_review_workspace(scad_project)
    assert a["review_confidence"] == b["review_confidence"]
    assert a["remaining_risk"] == b["remaining_risk"]


def test_review_confidence_and_risk_unknown_for_unsupported_project_state():
    """`"unsupported_project_state"` is declared in `slicer_readiness.
    READINESS_STATES` but is never actually produced by
    `assess_slicer_readiness()` today (confirmed - it appears nowhere in
    `_evaluate_readiness_status()`'s own return statements). It exists for
    forward-compatibility/robustness, same as several of Phase 36's own
    ladder branches. Unit-test `_review_confidence()`/`_remaining_risk()`
    directly with a synthetic assessment dict for that state - the same
    white-box style `test_slicer_readiness.py` already uses for
    `_evaluate_readiness_status()`."""
    from factory.manual_review_workspace import _remaining_risk, _review_confidence

    assessment = {
        "readiness_status": "unsupported_project_state",
        "readiness_score": 0,
        "validation_warning_count": 0,
        "warnings": [],
    }
    printer_profile = {"resolved": False}
    material_summary = {"unresolved_material_parts": [], "unresolved_color_parts": []}
    assert _review_confidence(assessment, printer_profile, material_summary) == "Unknown"
    assert _remaining_risk(assessment, printer_profile, material_summary) == "Unknown"


def test_review_confidence_low_when_blocked(scad_project):
    workspace = assess_manual_review_workspace(scad_project)
    assert workspace["review_confidence"] == "Low"


def test_review_confidence_high_only_when_everything_resolved(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    workspace = assess_manual_review_workspace(scad_project)
    if not workspace["warnings"] and workspace["validation_summary"]["passed_with_warnings"] == 0:
        assert workspace["review_confidence"] == "High"
    else:
        assert workspace["review_confidence"] == "Medium"


def test_remaining_risk_high_when_blocked(scad_project):
    workspace = assess_manual_review_workspace(scad_project)
    assert workspace["remaining_risk"] == "High"


# ---------------------------------------------------------------------------
# Compact summaries - thin extracts, never re-derived
# ---------------------------------------------------------------------------


def test_stl_validation_preview_receipt_summaries_reflect_assessment(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    workspace = assess_manual_review_workspace(scad_project)
    assert workspace["stl_summary"]["current"] == 1
    assert workspace["stl_summary"]["expected"] == 1
    assert workspace["validation_summary"]["passed"] + workspace["validation_summary"]["passed_with_warnings"] == 1
    assert workspace["preview_summary"]["current"] == 1
    assert workspace["receipt_summary"]["export_receipt_status"] == "present"


# ---------------------------------------------------------------------------
# Workspace creation - the one write path
# ---------------------------------------------------------------------------


def test_workspace_not_allowed_before_approval(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    with pytest.raises(WorkspaceNotAllowedError):
        create_manual_review_workspace(scad_project)
    assert not (scad_project / WORKSPACE_DIRNAME / WORKSPACE_MANIFEST_FILENAME).exists()


def test_workspace_not_allowed_when_blocked(scad_project):
    with pytest.raises(WorkspaceNotAllowedError):
        create_manual_review_workspace(scad_project)
    assert not (scad_project / WORKSPACE_DIRNAME / WORKSPACE_MANIFEST_FILENAME).exists()


def test_workspace_created_after_approval(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    result = create_manual_review_workspace(scad_project)
    assert Path(result["workspace_path"]).is_file()
    assert Path(result["readme_path"]).is_file()


def test_workspace_created_without_requiring_prior_package(scad_project, monkeypatch):
    """A review package (Phase 36) is referenced if present, but the
    workspace does not strictly require one to already exist - approval +
    technical readiness are the only hard requirements."""
    _fully_approved(scad_project, monkeypatch)
    assert not (scad_project / "slicer_review" / "slicer_review_manifest.json").exists()
    result = create_manual_review_workspace(scad_project)
    assert Path(result["workspace_path"]).is_file()


def test_workspace_references_package_when_present(scad_project, monkeypatch):
    _fully_packaged(scad_project, monkeypatch)
    result = create_manual_review_workspace(scad_project)
    assert result["manifest"]["review_package_path"] == "slicer_review/slicer_review_manifest.json"


def test_workspace_references_stl_not_copies(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    create_manual_review_workspace(scad_project)
    workspace_dir = scad_project / WORKSPACE_DIRNAME
    assert not any(p.suffix == ".stl" for p in workspace_dir.rglob("*"))


def test_workspace_contains_validation_and_receipt_references(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    result = create_manual_review_workspace(scad_project)
    manifest = result["manifest"]
    assert manifest["receipt_summary"]["export_receipt_status"] == "present"
    assert manifest["validation_summary"]["passed"] + manifest["validation_summary"]["passed_with_warnings"] == 1


def test_workspace_declares_no_automatic_print(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    result = create_manual_review_workspace(scad_project)
    assert result["manifest"]["auto_print_allowed"] is False
    readme = Path(result["readme_path"]).read_text(encoding="utf-8")
    assert "No automatic print" in readme
    assert "Human sign-off" in readme


def test_workspace_collision_protection(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    create_manual_review_workspace(scad_project)
    with pytest.raises(WorkspaceCollisionError):
        create_manual_review_workspace(scad_project)


def test_workspace_overwrite_true_allows_recreation(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    create_manual_review_workspace(scad_project)
    result = create_manual_review_workspace(scad_project, overwrite=True)
    assert Path(result["workspace_path"]).is_file()


def test_workspace_prior_version_preserved_on_collision(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    first = create_manual_review_workspace(scad_project)
    first_bytes = Path(first["workspace_path"]).read_bytes()
    with pytest.raises(WorkspaceCollisionError):
        create_manual_review_workspace(scad_project)
    assert Path(first["workspace_path"]).read_bytes() == first_bytes


def test_workspace_stale_detection_after_source_change(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    create_manual_review_workspace(scad_project)
    assert assess_manual_review_workspace(scad_project)["workspace_status"] == "workspace_created"

    scad_path = scad_project / "cad" / "sign.scad"
    scad_path.write_text(scad_path.read_text(encoding="utf-8") + "\n// changed after workspace\n", encoding="utf-8")

    workspace = assess_manual_review_workspace(scad_project)
    assert workspace["workspace_status"] == "not_ready"
    assert workspace["technical_readiness"] == "stale_artifacts"


def test_workspace_stale_when_package_recreated(scad_project, monkeypatch):
    """The workspace fingerprints the Phase 36 package file itself, so
    recreating the package (even with unchanged STL/validation/render)
    invalidates a previously-created workspace."""
    _fully_packaged(scad_project, monkeypatch)
    create_manual_review_workspace(scad_project)
    assert assess_manual_review_workspace(scad_project)["workspace_status"] == "workspace_created"

    create_review_package(scad_project, overwrite=True)
    workspace = assess_manual_review_workspace(scad_project)
    assert workspace["workspace_status"] == "stale_workspace"


def test_workspace_refresh_after_stale_recreates_current(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    create_manual_review_workspace(scad_project)
    scad_path = scad_project / "cad" / "sign.scad"
    scad_path.write_text(scad_path.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
    assert assess_manual_review_workspace(scad_project)["workspace_status"] == "not_ready"

    # Refresh: re-export/validate/render, re-approve, then re-create.
    _export_all(scad_project, monkeypatch, overwrite_stl=True)
    record_approval(scad_project)
    result = create_manual_review_workspace(scad_project, overwrite=True)
    assert Path(result["workspace_path"]).is_file()
    assert assess_manual_review_workspace(scad_project)["workspace_status"] == "workspace_created"


def test_workspace_never_invokes_a_subprocess(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)

    def _boom(*a, **k):
        raise AssertionError("create_manual_review_workspace() must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    create_manual_review_workspace(scad_project)


def test_workspace_writes_receipt(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    create_manual_review_workspace(scad_project)
    receipt = read_workspace_receipt(scad_project)
    assert receipt is not None
    assert receipt["workspace"]["workspace_path"] == f"{WORKSPACE_DIRNAME}/{WORKSPACE_MANIFEST_FILENAME}"


def test_malformed_workspace_receipt_does_not_crash(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    receipt_path = scad_project / GENERATED_DIRNAME / WORKSPACE_RECEIPT_FILENAME
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text("{not valid json", encoding="utf-8")
    workspace = assess_manual_review_workspace(scad_project)
    assert workspace["workspace_status"] == "ready_to_create"


# ---------------------------------------------------------------------------
# Local slicer detection - read-only, advisory only, reused from Phase 36
# ---------------------------------------------------------------------------


def test_slicer_probe_reused_not_reimplemented(scad_project):
    workspace = assess_manual_review_workspace(scad_project)
    assert workspace["detected_slicers"] == local_slicer_probe.probe_slicers()


def test_workspace_never_launches_a_slicer(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must never launch a slicer binary")

    monkeypatch.setattr(export_pipeline.subprocess, "Popen", _boom, raising=False)
    _fully_approved(scad_project, monkeypatch)
    create_manual_review_workspace(scad_project)


# ---------------------------------------------------------------------------
# summarize_manual_review_workspace() - the compact Preview Board summary
# ---------------------------------------------------------------------------


def test_summarize_is_read_only(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    before = sorted(str(p) for p in scad_project.rglob("*"))
    summarize_manual_review_workspace(scad_project)
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


def test_summarize_shape(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    summary = summarize_manual_review_workspace(scad_project)
    assert set(summary.keys()) == {
        "workspace_status", "printer_display_name", "material_multi", "material_unresolved",
        "review_confidence", "remaining_risk", "package_available", "warning_count", "next_action",
    }
    assert summary["workspace_status"] == "needs_approval"


def test_summarize_reflects_workspace_creation(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    create_manual_review_workspace(scad_project)
    summary = summarize_manual_review_workspace(scad_project)
    assert summary["workspace_status"] == "workspace_created"

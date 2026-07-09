"""Phase 13 refactor tests: the shared factory.project_inspection layer,
the import graph between it/preview_board/review_gate, and backward
compatibility of both public JSON shapes after the extraction.
"""

import ast
import inspect
import time
from pathlib import Path

import pytest

from factory import project_store
from factory import project_inspection as project_inspection_module
from factory import preview_board as preview_board_module
from factory import review_gate as review_gate_module
from factory.project_inspection import (
    ACTION_SAFETY,
    HEALTH_SEVERITIES,
    VISUAL_READINESS_STATES,
    build_health_signals,
    build_suggested_actions,
    classify_visual_readiness,
    summarize_project,
)
from factory.preview_board import gather_board_data, summarize_project as board_summarize_project
from factory.review_gate import evaluate_review_gate


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture()
def project_root(isolated_projects_dir):
    return project_store.init_project("Demo Project")


def _module_import_targets(module) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            targets.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                targets.add(alias.name)
    return targets


# ---- import graph ----


def test_review_gate_does_not_import_preview_board():
    targets = _module_import_targets(review_gate_module)
    assert "factory.preview_board" not in targets
    # Prose in the docstring is allowed to mention preview_board by name
    # (comparing behavior) - only real import statements are forbidden.
    for line in inspect.getsource(review_gate_module).splitlines():
        stripped = line.strip()
        assert not stripped.startswith("import factory.preview_board")
        assert not stripped.startswith("from factory.preview_board")


def test_review_gate_imports_project_inspection():
    targets = _module_import_targets(review_gate_module)
    assert "factory.project_inspection" in targets


def test_preview_board_imports_project_inspection():
    targets = _module_import_targets(preview_board_module)
    assert "factory.project_inspection" in targets


def test_project_inspection_does_not_import_preview_board_or_review_gate():
    targets = _module_import_targets(project_inspection_module)
    assert "factory.preview_board" not in targets
    assert "factory.review_gate" not in targets


def test_no_circular_imports_among_the_three_modules():
    # Run in a fresh subprocess (not importlib.reload() in-process, which
    # would rebind names in already-imported modules and corrupt `is`
    # identity for the rest of this test session) - proves each import
    # order succeeds with a clean module cache, regardless of order.
    import subprocess
    import sys

    orders = [
        "import factory.review_gate; import factory.preview_board; import factory.project_inspection",
        "import factory.preview_board; import factory.review_gate; import factory.project_inspection",
        "import factory.project_inspection; import factory.preview_board; import factory.review_gate",
    ]
    for order in orders:
        result = subprocess.run(
            [sys.executable, "-c", order],
            cwd=str(Path(__file__).resolve().parents[1]),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"import order {order!r} failed:\n{result.stderr}"


def test_preview_board_and_review_gate_use_the_same_summarize_project():
    # Not just "both import project_inspection" - they must be the literal
    # same function, so the two surfaces can never silently diverge.
    from factory.preview_board import summarize_project as pb_summarize_project

    assert pb_summarize_project is summarize_project


# ---- project_inspection used directly (not via preview_board's re-export) ----


def test_summarize_project_importable_and_usable_directly(project_root):
    summary = summarize_project(project_root)
    assert summary["visual_readiness_state"] == "cad_source_ready"
    assert "health_signals" in summary
    assert "suggested_actions" in summary


def test_classify_visual_readiness_importable_directly():
    state = classify_visual_readiness(
        brief_status="missing", manifest_status="missing", cad_files=[], mesh_files=[],
        missing_renders=[], stale_renders=[], missing_visual_artifacts=[], stale_previews=[],
    )
    assert state == "needs_brief"


def test_constants_importable_directly():
    assert VISUAL_READINESS_STATES == (
        "needs_brief", "cad_source_ready", "needs_stl_export", "needs_render",
        "slicer_review_ready", "blocked_or_incomplete",
    )
    assert HEALTH_SEVERITIES == ("info", "warning", "blocked", "ready")
    assert ACTION_SAFETY == "manual_only"


def test_build_suggested_actions_and_build_health_signals_importable_directly():
    assert callable(build_suggested_actions)
    assert callable(build_health_signals)


# ---- backward compatibility: preview-board JSON shape ----


def test_preview_board_json_shape_unchanged_after_refactor(isolated_projects_dir):
    project_store.init_project("Demo")
    board = gather_board_data(isolated_projects_dir)
    assert set(board.keys()) == {
        "generated_at", "projects_root", "project_count", "state_counts", "projects", "notes",
    }
    project = board["projects"][0]
    expected_keys = {
        "project_name", "project_dir", "slug", "brief_exists", "brief_status",
        "manufacturing_status", "selected_manufacturing_option", "manifest_exists",
        "render_coverage", "preview_package_exists", "cad_files", "mesh_files",
        "render_files", "visual_readiness_state", "warnings", "suggested_actions",
        "health_signals", "design_intent_summary", "design_intent_detail",
        "reference_board_summary", "intake_summary", "draft_brief_summary",
    }
    assert set(project.keys()) == expected_keys


def test_preview_board_suggested_actions_and_health_signals_still_present(project_root):
    summary = board_summarize_project(project_root)
    assert summary["suggested_actions"]
    assert summary["health_signals"]["summary"] in ("ok", "attention_needed", "blocked")


# ---- Phase 26: design_intent_summary field ----


def test_design_intent_summary_is_none_when_brief_has_no_design_intent(project_root):
    summary = summarize_project(project_root)
    assert summary["design_intent_summary"] is None


def test_design_intent_summary_is_none_when_brief_missing(isolated_projects_dir):
    empty_dir = isolated_projects_dir / "no-brief-here"
    empty_dir.mkdir()
    summary = summarize_project(empty_dir)
    assert summary["design_intent_summary"] is None


def test_design_intent_summary_populated_when_brief_has_design_intent(project_root):
    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["design_intent"] = {
        "quality_standard": "Etsy-worthy",
        "use_case": "kitchen organization",
        "style_direction": ["minimalist", "functional"],
        "manufacturability_constraints": {"max_size_mm": [50, 50, 50]},
    }
    project_store.save_json(brief_path, brief)

    summary = summarize_project(project_root)
    design_intent_summary = summary["design_intent_summary"]
    assert design_intent_summary is not None
    assert set(design_intent_summary.keys()) == {"quality_standard", "use_case", "manufacturability_result"}
    assert design_intent_summary["quality_standard"] == "Etsy-worthy"
    assert design_intent_summary["use_case"] == "kitchen organization"
    assert design_intent_summary["manufacturability_result"] == "fits_some_printers"


def test_design_intent_summary_malformed_design_intent_handled_safely(project_root):
    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["design_intent"] = "not a dict"
    project_store.save_json(brief_path, brief)

    summary = summarize_project(project_root)
    assert summary["design_intent_summary"] is None


def test_design_intent_summary_never_affects_visual_readiness_or_health(project_root):
    without_intent = summarize_project(project_root)

    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["design_intent"] = {"quality_standard": "Etsy-worthy"}
    project_store.save_json(brief_path, brief)
    with_intent = summarize_project(project_root)

    assert with_intent["visual_readiness_state"] == without_intent["visual_readiness_state"]
    assert with_intent["health_signals"] == without_intent["health_signals"]
    assert with_intent["suggested_actions"] == without_intent["suggested_actions"]


def test_review_gate_json_excludes_design_intent_summary(project_root):
    gate = evaluate_review_gate(project_root)
    assert "design_intent_summary" not in gate


# ---- Phase 27: design_intent_detail field (Preview Board HTML visualization) ----


def test_design_intent_detail_is_none_when_brief_has_no_design_intent(project_root):
    summary = summarize_project(project_root)
    assert summary["design_intent_detail"] is None


def test_design_intent_detail_is_none_when_brief_missing(isolated_projects_dir):
    empty_dir = isolated_projects_dir / "no-brief-here"
    empty_dir.mkdir()
    summary = summarize_project(empty_dir)
    assert summary["design_intent_detail"] is None


def test_design_intent_detail_populated_when_brief_has_design_intent(project_root):
    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["design_intent"] = {
        "quality_standard": "Etsy-worthy",
        "use_case": "kitchen organization",
        "style_direction": ["minimalist", "functional"],
        "reference_inputs": [{"type": "image", "description": "a photo", "local_only": True}],
        "manufacturability_constraints": {"max_size_mm": [50, 50, 50]},
        "iteration_plan": {"acceptance_notes": "matches the reference photo's silhouette"},
    }
    project_store.save_json(brief_path, brief)

    summary = summarize_project(project_root)
    detail = summary["design_intent_detail"]
    assert detail is not None
    assert set(detail.keys()) == {
        "quality_standard", "use_case", "style_direction", "manufacturability_result",
        "reference_input_count", "design_notes", "warnings",
    }
    assert detail["quality_standard"] == "Etsy-worthy"
    assert detail["use_case"] == "kitchen organization"
    assert detail["style_direction"] == ["minimalist", "functional"]
    assert detail["manufacturability_result"] == "fits_some_printers"
    assert detail["reference_input_count"] == 1
    assert detail["design_notes"] == "matches the reference photo's silhouette"
    assert isinstance(detail["warnings"], list)


def test_design_intent_detail_reference_input_count_zero_when_absent(project_root):
    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["design_intent"] = {"quality_standard": "Etsy-worthy"}
    project_store.save_json(brief_path, brief)

    detail = summarize_project(project_root)["design_intent_detail"]
    assert detail["reference_input_count"] == 0
    assert detail["design_notes"] is None


def test_design_intent_detail_malformed_design_intent_handled_safely(project_root):
    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["design_intent"] = "not a dict"
    project_store.save_json(brief_path, brief)

    summary = summarize_project(project_root)
    assert summary["design_intent_detail"] is None


def test_design_intent_detail_never_affects_visual_readiness_or_health(project_root):
    without_intent = summarize_project(project_root)

    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["design_intent"] = {"quality_standard": "Etsy-worthy"}
    project_store.save_json(brief_path, brief)
    with_intent = summarize_project(project_root)

    assert with_intent["visual_readiness_state"] == without_intent["visual_readiness_state"]
    assert with_intent["health_signals"] == without_intent["health_signals"]
    assert with_intent["suggested_actions"] == without_intent["suggested_actions"]


def test_review_gate_json_excludes_design_intent_detail(project_root):
    gate = evaluate_review_gate(project_root)
    assert "design_intent_detail" not in gate


# ---- Phase 28: reference_board_summary field (Reference Board planning) ----


def test_reference_board_summary_is_clean_empty_result_when_file_missing(project_root):
    summary = summarize_project(project_root)
    assert summary["reference_board_summary"] == {
        "reference_count": 0,
        "by_license": {},
        "by_source_type": {},
        "by_usage_intent": {},
        "attached_to_design_intent_count": 0,
        "warnings": [],
    }


def test_reference_board_summary_populated_when_file_present(project_root):
    board_path = project_root / "reference_board.json"
    project_store.save_json(
        board_path,
        {
            "references": [
                {
                    "title": "Classroom storage inspiration",
                    "source_url": "https://example.com/classroom-storage-reference",
                    "source_type": "inspiration",
                    "license": "unknown",
                    "usage_intent": "design_reference_only",
                    "attached_to": "design_intent.reference_inputs",
                    "notes": "Used only as a style and organization reference.",
                }
            ]
        },
    )

    summary = summarize_project(project_root)
    reference_board_summary = summary["reference_board_summary"]
    assert reference_board_summary["reference_count"] == 1
    assert reference_board_summary["by_license"] == {"unknown": 1}
    assert reference_board_summary["by_source_type"] == {"inspiration": 1}
    assert reference_board_summary["by_usage_intent"] == {"design_reference_only": 1}
    assert reference_board_summary["attached_to_design_intent_count"] == 1
    assert any("commercial use unclear" in w for w in reference_board_summary["warnings"])


def test_reference_board_summary_malformed_file_handled_safely(project_root):
    (project_root / "reference_board.json").write_text("{not valid json", encoding="utf-8")
    summary = summarize_project(project_root)
    assert summary["reference_board_summary"]["reference_count"] == 0


def test_reference_board_summary_never_affects_visual_readiness_or_health(project_root):
    without_board = summarize_project(project_root)

    project_store.save_json(
        project_root / "reference_board.json",
        {"references": [{"title": "x", "source_type": "unknown", "license": "unknown"}]},
    )
    with_board = summarize_project(project_root)

    assert with_board["visual_readiness_state"] == without_board["visual_readiness_state"]
    assert with_board["health_signals"] == without_board["health_signals"]
    assert with_board["suggested_actions"] == without_board["suggested_actions"]


def test_reference_board_summary_independent_of_brief_status(isolated_projects_dir):
    # A project with no brief.json at all can still have a reference board -
    # reference_board_summary must not be gated on brief_status like
    # design_intent_summary/design_intent_detail are.
    empty_dir = isolated_projects_dir / "no-brief-here"
    empty_dir.mkdir()
    project_store.save_json(
        empty_dir / "reference_board.json",
        {"references": [{"title": "x", "source_type": "sketch", "license": "public_domain"}]},
    )
    summary = summarize_project(empty_dir)
    assert summary["brief_exists"] is False
    assert summary["reference_board_summary"]["reference_count"] == 1


def test_review_gate_json_excludes_reference_board_summary(project_root):
    gate = evaluate_review_gate(project_root)
    assert "reference_board_summary" not in gate


# ---- Phase 30: intake_summary field (Project Intake Engine) ----


def test_intake_summary_present_and_shaped_for_minimal_project(project_root):
    summary = summarize_project(project_root)
    intake = summary["intake_summary"]
    assert intake is not None
    assert set(intake.keys()) == {
        "project_name", "category", "purpose", "audience", "environment",
        "material_assumptions", "printer_assumptions", "quality_target",
        "manufacturing_style", "functional_goals", "visual_goals",
        "dimensional_constraints", "commercial_intent", "warnings", "source",
    }
    assert intake["source"] == "brief_description"


def test_intake_summary_is_clean_result_when_brief_missing(isolated_projects_dir):
    empty_dir = isolated_projects_dir / "no-brief-here"
    empty_dir.mkdir()
    summary = summarize_project(empty_dir)
    intake = summary["intake_summary"]
    assert intake["source"] == "none"
    assert intake["category"]["value"] == "unknown"


def test_intake_summary_reflects_brief_description(project_root):
    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["description"] = "A premium classroom sign for my teacher's desk, made from PLA on a Bambu printer."
    project_store.save_json(brief_path, brief)

    summary = summarize_project(project_root)
    intake = summary["intake_summary"]
    assert intake["category"]["value"] == "sign"
    assert intake["material_assumptions"]["value"] == ["PLA"]
    assert intake["printer_assumptions"]["value"] == ["Bambu"]


def test_intake_summary_malformed_brief_handled_safely(project_root):
    (project_root / "brief.json").write_text("{not valid json", encoding="utf-8")
    summary = summarize_project(project_root)
    assert summary["intake_summary"]["source"] == "none"


def test_intake_summary_never_affects_visual_readiness_or_health(project_root):
    without_intake = summarize_project(project_root)

    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["description"] = "A premium etsy-worthy gift for the classroom, made with PLA."
    project_store.save_json(brief_path, brief)
    with_intake = summarize_project(project_root)

    assert with_intake["visual_readiness_state"] == without_intake["visual_readiness_state"]
    assert with_intake["health_signals"] == without_intake["health_signals"]
    assert with_intake["suggested_actions"] == without_intake["suggested_actions"]


def test_intake_summary_does_not_affect_design_intent_or_reference_board_fields(project_root):
    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["description"] = "A premium etsy-worthy gift for the classroom."
    project_store.save_json(brief_path, brief)

    summary = summarize_project(project_root)
    assert summary["design_intent_summary"] is None
    assert summary["design_intent_detail"] is None
    assert summary["reference_board_summary"]["reference_count"] == 0


def test_review_gate_json_excludes_intake_summary(project_root):
    gate = evaluate_review_gate(project_root)
    assert "intake_summary" not in gate


# ---- Phase 31: draft_brief_summary field (Intake-to-Brief Draft Generation) ----


def test_draft_brief_summary_present_and_shaped(project_root):
    summary = summarize_project(project_root)
    draft = summary["draft_brief_summary"]
    assert set(draft.keys()) == {"readiness", "advisories"}
    assert draft["readiness"]["status"] == "Ready"
    assert draft["readiness"]["human_review_required"] is True
    assert "Human approval required before save." in draft["advisories"]


def test_draft_brief_summary_derived_from_intake_summary(project_root):
    from factory.brief_generator import summarize_draft_brief

    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["description"] = "A premium etsy-worthy classroom sign made of PLA on a Bambu printer."
    project_store.save_json(brief_path, brief)

    summary = summarize_project(project_root)
    assert summary["draft_brief_summary"] == summarize_draft_brief(summary["intake_summary"])


def test_draft_brief_summary_never_affects_visual_readiness_or_health(project_root):
    without_draft = summarize_project(project_root)

    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["description"] = "A premium etsy-worthy gift for the classroom, made with PLA."
    project_store.save_json(brief_path, brief)
    with_draft = summarize_project(project_root)

    assert with_draft["visual_readiness_state"] == without_draft["visual_readiness_state"]
    assert with_draft["health_signals"] == without_draft["health_signals"]
    assert with_draft["suggested_actions"] == without_draft["suggested_actions"]


def test_draft_brief_summary_does_not_affect_other_summary_fields(project_root):
    summary = summarize_project(project_root)
    assert summary["design_intent_summary"] is None
    assert summary["design_intent_detail"] is None
    assert summary["reference_board_summary"]["reference_count"] == 0


def test_review_gate_json_excludes_draft_brief_summary(project_root):
    gate = evaluate_review_gate(project_root)
    assert "draft_brief_summary" not in gate


# ---- backward compatibility: review-gate JSON shape ----


def test_review_gate_json_shape_unchanged_after_refactor(project_root):
    gate = evaluate_review_gate(project_root)
    assert set(gate.keys()) == {
        "project_dir", "gate", "result", "status_ceiling", "summary",
        "blocking_items", "warning_items", "ready_items", "suggested_actions", "notes",
    }
    assert gate["gate"] == "human_slicer_review"
    assert gate["status_ceiling"] == "slicer_review_ready"


def test_review_gate_fail_behavior_preserved(project_root):
    gate = evaluate_review_gate(project_root)
    assert gate["result"] == "fail"
    assert any(i["kind"] == "no_stl_files" for i in gate["blocking_items"])


def test_review_gate_warn_behavior_preserved(project_root):
    build_plan = project_store.load_json(project_root / "build_plan.json")
    build_plan["selected_manufacturing_option"] = "single_piece"
    project_store.save_json(project_root / "build_plan.json", build_plan)
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png")

    gate = evaluate_review_gate(project_root)
    assert gate["result"] == "warn"
    assert gate["blocking_items"] == []


def test_review_gate_pass_behavior_preserved(project_root):
    from factory.preview_package import write_preview_package

    build_plan = project_store.load_json(project_root / "build_plan.json")
    build_plan["selected_manufacturing_option"] = "single_piece"
    project_store.save_json(project_root / "build_plan.json", build_plan)
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png")
    (project_root / "validation" / "part_validation.json").write_text('{"overall_status": "PASS"}', encoding="utf-8")
    write_preview_package(project_root)

    gate = evaluate_review_gate(project_root)
    assert gate["result"] == "pass"
    assert gate["blocking_items"] == []
    assert gate["warning_items"] == []


def test_review_gate_stale_render_still_fails(project_root):
    import os

    stl_path = project_root / "stl" / "part.stl"
    render_path = project_root / "renders" / "part_preview.png"
    stl_path.write_bytes(b"fake stl")
    render_path.write_bytes(b"fake png")
    future = time.time() + 10
    os.utime(stl_path, (future, future))

    gate = evaluate_review_gate(project_root)
    assert gate["result"] == "fail"
    assert any(i["kind"] == "render_stale" for i in gate["blocking_items"])


# ---- safety: no approval, no network/subprocess, project_inspection specifically ----


def _strip_docstrings(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body.pop(0)
    return tree


def test_project_inspection_module_has_no_network_or_process_calls():
    forbidden = [
        "import subprocess",
        "subprocess.",
        "os.system(",
        "os.popen(",
        "Popen(",
        "socket.",
        "import urllib",
        "import requests",
        "http.client",
    ]
    tree = _strip_docstrings(ast.parse(inspect.getsource(project_inspection_module)))
    code_only_source = ast.unparse(tree)
    for forbidden_term in forbidden:
        assert forbidden_term not in code_only_source, f"factory.project_inspection must stay local-only; found {forbidden_term!r}"


def test_project_inspection_module_never_writes_files():
    source = inspect.getsource(project_inspection_module)
    for write_call in ("write_text(", "write_bytes(", "save_json(", ".mkdir("):
        assert write_call not in source, f"factory.project_inspection must not write files; found {write_call!r}"


def test_project_inspection_module_never_references_approval_statuses():
    tree = _strip_docstrings(ast.parse(inspect.getsource(project_inspection_module)))
    code_only_source = ast.unparse(tree)
    assert "human_approved" not in code_only_source
    assert "print_ready" not in code_only_source


def test_project_inspection_module_never_calls_advance_status():
    source = inspect.getsource(project_inspection_module)
    assert "advance_status" not in source


def test_evaluate_review_gate_never_writes_any_file(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    before = {p for p in project_root.rglob("*") if p.is_file()}
    evaluate_review_gate(project_root)
    after = {p for p in project_root.rglob("*") if p.is_file()}
    assert before == after


def test_gather_board_data_never_writes_project_files(isolated_projects_dir):
    project_root_dir = project_store.init_project("Untouched")
    before = {p: p.read_bytes() for p in project_root_dir.rglob("*") if p.is_file()}
    gather_board_data(isolated_projects_dir)
    after = {p: p.read_bytes() for p in project_root_dir.rglob("*") if p.is_file()}
    assert before == after

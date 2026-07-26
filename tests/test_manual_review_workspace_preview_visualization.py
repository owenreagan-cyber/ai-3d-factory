"""Phase 37 tests: wiring `manual_review_summary` into the Preview Board
(via `factory.preview_board.gather_board_data()`, not
`factory.project_inspection.summarize_project()` - see the architectural
note below) and rendering a compact "Manual Review Workspace" card in the
Preview Board HTML. See docs/manual-review-workspace.md,
docs/preview-board.md, docs/roadmap.md Phase 37.

**Architectural note:** this field lives outside `project_inspection.py`
for the same reason Phase 36's `slicer_readiness_summary` does -
`factory.manual_review_workspace` calls
`factory.slicer_readiness.assess_slicer_readiness()`, which itself calls
`factory.review_gate.evaluate_review_gate()`, which already imports
`summarize_project()`. Adding the field inside `project_inspection.py`
would recreate the exact circular import Phase 36 already discovered.
These tests exist to prove the board stays entirely read-only even with
this extra per-project call, and that every existing detail card is
preserved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory import export_pipeline, project_store
from factory.cli import app
from factory.openscad.generate import generate_openscad
from factory.preview_board import VISUAL_READINESS_STATES, build_board_html, gather_board_data
from factory.manual_review_workspace import WORKSPACE_DIRNAME, WORKSPACE_MANIFEST_FILENAME, create_manual_review_workspace
from factory.slicer_readiness import record_approval

runner = CliRunner()

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


def _minimal_board(projects=None):
    return {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "projects_root": "/tmp/projects",
        "project_count": len(projects or []),
        "state_counts": {state: 0 for state in VISUAL_READINESS_STATES},
        "projects": projects or [],
        "notes": ["Local static preview only.", "Human slicer review required."],
    }


def _empty_render_coverage() -> dict:
    return {
        "project_dir": "/tmp/projects/demo",
        "mesh_files": [],
        "render_files": [],
        "covered": [],
        "missing_renders": [],
        "orphan_renders": [],
        "stale_renders": [],
        "total_meshes": 0,
        "total_renders": 0,
        "covered_count": 0,
        "all_meshes_have_renders": False,
        "visually_complete_for_slicer_review": False,
        "notes": [],
    }


def _full_project(**overrides) -> dict:
    project = {
        "project_name": "Demo",
        "project_dir": "demo",
        "slug": "demo",
        "brief_exists": True,
        "brief_status": "cad_generated",
        "manufacturing_status": None,
        "selected_manufacturing_option": None,
        "manifest_exists": True,
        "preview_package_exists": True,
        "cad_files": [],
        "mesh_files": [],
        "render_files": [],
        "render_coverage": _empty_render_coverage(),
        "visual_readiness_state": "needs_brief",
        "warnings": [],
    }
    project.update(overrides)
    return project


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


def _fully_approved(project_dir, monkeypatch):
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
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = export_pipeline.plan_export(project_dir, confirm_export=True)
    export_pipeline.run_export_pipeline(project_dir, plan, all_steps=True)

    build_plan = project_store.load_json(project_dir / "build_plan.json")
    build_plan["selected_manufacturing_option"] = "single_piece"
    build_plan["target_printer"] = {
        "printer_id": "bambu_h2d",
        "display_name": "Bambu Lab H2D",
        "resolved": True,
        "resolved_from": "test",
        "capabilities": None,
    }
    project_store.save_json(project_dir / "build_plan.json", build_plan)

    manifest = project_store.load_json(project_dir / "part_manifest.json")
    for part in manifest.get("parts", []):
        part["material"] = "PLA"
        part["color"] = "white"
    project_store.save_json(project_dir / "part_manifest.json", manifest)

    record_approval(project_dir)
    return project_dir


# ---- gather_board_data() integration ----


def test_gather_board_data_includes_manual_review_summary(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    project = board["projects"][0]
    assert "manual_review_summary" in project
    assert project["manual_review_summary"]["workspace_status"] == "not_ready"


def test_gather_board_data_never_writes_anything(isolated_projects_dir, scad_project):
    before = sorted(str(p) for p in scad_project.rglob("*"))
    gather_board_data(isolated_projects_dir)
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after
    assert not (scad_project / WORKSPACE_DIRNAME / WORKSPACE_MANIFEST_FILENAME).exists()


def test_gather_board_data_never_invokes_a_subprocess(isolated_projects_dir, scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("gather_board_data() must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    gather_board_data(isolated_projects_dir)


def test_gather_board_data_reflects_approval(isolated_projects_dir, scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    board = gather_board_data(isolated_projects_dir)
    project = board["projects"][0]
    assert project["manual_review_summary"]["workspace_status"] == "ready_to_create"


def test_gather_board_data_reflects_workspace_creation(isolated_projects_dir, scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    create_manual_review_workspace(scad_project)
    board = gather_board_data(isolated_projects_dir)
    project = board["projects"][0]
    assert project["manual_review_summary"]["workspace_status"] == "workspace_created"


# ---- Preview Board HTML: Manual Review Workspace card ----


def test_html_includes_manual_review_workspace_section_heading(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    assert "Manual Review Workspace" in html


def test_html_manual_review_workspace_appears_after_slicer_review_readiness_before_project_intake(
    isolated_projects_dir, scad_project
):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    readiness_index = html.find("<h4>Slicer Review Readiness</h4>")
    workspace_index = html.find("<h4>Manual Review Workspace</h4>")
    intake_index = html.find("<h4>Project Intake</h4>")
    assert readiness_index != -1
    assert workspace_index != -1
    assert intake_index != -1
    assert readiness_index < workspace_index < intake_index


def test_html_manual_review_workspace_shows_workspace_printer_material_confidence_risk_package(
    isolated_projects_dir, scad_project
):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    start = html.find("<h4>Manual Review Workspace</h4>")
    end = html.find("<h4>Project Intake</h4>", start)
    section = html[start:end]
    assert "Workspace:" in section
    assert "Printer:" in section
    assert "Material:" in section
    assert "Review confidence:" in section
    assert "Remaining risk:" in section
    assert "Package:" in section
    assert "Next action:" in section
    assert "Human review required" in section


def test_html_manual_review_workspace_shows_not_ready_state(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    start = html.find("<h4>Manual Review Workspace</h4>")
    end = html.find("<h4>Project Intake</h4>", start)
    section = html[start:end]
    assert "Not ready" in section


def test_html_manual_review_workspace_shows_ready_state_after_workspace_creation(
    isolated_projects_dir, scad_project, monkeypatch
):
    _fully_approved(scad_project, monkeypatch)
    create_manual_review_workspace(scad_project)
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    start = html.find("<h4>Manual Review Workspace</h4>")
    end = html.find("<h4>Project Intake</h4>", start)
    section = html[start:end]
    assert ">Ready<" in section


def test_html_manual_review_workspace_missing_summary_key_renders_cleanly():
    project = _full_project()
    assert "manual_review_summary" not in project
    html = build_board_html(_minimal_board([project]))
    assert "No manual review workspace analysis available for this project." in html


def test_html_never_leaves_manual_review_workspace_value_blank(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)
    start = html.find("<h4>Manual Review Workspace</h4>")
    end = html.find("<h4>Project Intake</h4>", start)
    section = html[start:end]
    assert 'di-value"></span>' not in section


# ---- existing detail cards preserved ----


def test_existing_detail_cards_still_present_alongside_manual_review_workspace_card(isolated_projects_dir, scad_project):
    board = gather_board_data(isolated_projects_dir)
    html = build_board_html(board)

    assert "Project Readiness" in html
    assert "Generation Gate" in html
    assert "Post-Generation Pipeline" in html
    assert "Slicer Review Readiness" in html
    assert "Health signals" in html
    assert "Suggested next steps" in html
    assert "Design Intent" in html
    assert "Reference Board" in html
    assert "Project Intake" in html
    assert "Draft Brief" in html
    assert "Brief Update" in html


# ---- Board never assesses, inspects a printer profile, or creates a workspace ----


def test_gather_board_data_never_creates_a_workspace(isolated_projects_dir, scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    gather_board_data(isolated_projects_dir)
    assert not (scad_project / WORKSPACE_DIRNAME / WORKSPACE_MANIFEST_FILENAME).exists()


# ---- Escaping / no external assets ----


def test_html_manual_review_workspace_section_escapes_values():
    project = _full_project(
        manual_review_summary={
            "workspace_status": "<script>alert(1)</script>",
            "printer_display_name": "<b>Bambu</b>",
            "material_multi": False,
            "material_unresolved": True,
            "review_confidence": "Unknown",
            "remaining_risk": "Unknown",
            "package_available": False,
            "warning_count": 1,
            "next_action": "<img src=x onerror=alert(1)>",
        },
    )
    html = build_board_html(_minimal_board([project]))
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_html_manual_review_workspace_section_has_no_external_assets_or_ai_calls():
    forbidden = ("http://", "<script", "cdn.", "fetch(", "openai", "anthropic")
    project = _full_project(
        manual_review_summary={
            "workspace_status": "needs_approval",
            "printer_display_name": "Bambu Lab H2D",
            "material_multi": False,
            "material_unresolved": False,
            "review_confidence": "Medium",
            "remaining_risk": "Moderate",
            "package_available": False,
            "warning_count": 0,
            "next_action": "Record human approval.",
        },
    )
    html = build_board_html(_minimal_board([project]))
    for term in forbidden:
        assert term not in html


# ---- regression: CLI/JSON compatibility, other pipelines unaffected ----


def test_cli_preview_board_html_includes_manual_review_workspace_section(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout
    html = (isolated_projects_dir / "preview_board" / "index.html").read_text()
    assert "Manual Review Workspace" in html


def test_preview_board_json_includes_additive_manual_review_summary(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    board = json.loads((isolated_projects_dir / "preview_board" / "index.json").read_text())
    project = board["projects"][0]
    assert project["manual_review_summary"]["workspace_status"] == "not_ready"
    # Existing Phase 26-36 fields untouched by this phase.
    assert "slicer_readiness_summary" in project
    assert "export_pipeline_summary" in project
    assert "generation_gate_summary" in project
    assert "design_orchestrator_summary" in project


def test_review_gate_cli_unaffected_by_manual_review_summary(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["review-gate", "--json", str(scad_project)])
    payload = json.loads(result.stdout)
    assert "manual_review_summary" not in payload


def test_slicer_readiness_cli_unaffected_by_manual_review_workspace(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["slicer-readiness", str(scad_project), "--json"])
    payload = json.loads(result.stdout)
    assert "manual_review_summary" not in payload

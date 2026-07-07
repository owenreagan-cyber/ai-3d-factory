import ast
import inspect
import os
import time

import pytest
from typer.testing import CliRunner

from factory import preview_board as preview_board_module
from factory import project_store
from factory.cli import app
from factory.preview_board import (
    ACTION_SAFETY,
    HEALTH_SEVERITIES,
    VISUAL_READINESS_STATES,
    build_board_html,
    build_health_signals,
    build_suggested_actions,
    classify_visual_readiness,
    discover_projects,
    gather_board_data,
    preview_board_paths,
    summarize_project,
    write_preview_board,
)
from factory.render_coverage import compute_render_coverage
from factory.preview_package import write_preview_package

runner = CliRunner()


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture()
def project_root(isolated_projects_dir):
    return project_store.init_project("Demo Project")


# ---- discover_projects ----


def test_discover_projects_on_empty_root(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    assert discover_projects(root) == []


def test_discover_projects_on_nonexistent_root(tmp_path):
    assert discover_projects(tmp_path / "does-not-exist") == []


def test_discover_projects_skips_hidden_and_board_dir(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "real-project").mkdir()
    (root / ".hidden").mkdir()
    (root / "preview_board").mkdir()
    (root / "a_file.txt").write_text("not a dir")
    assert discover_projects(root) == [root / "real-project"]


def test_discover_projects_sorted_by_name(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    for name in ("zeta", "alpha", "mid"):
        (root / name).mkdir()
    assert [p.name for p in discover_projects(root)] == ["alpha", "mid", "zeta"]


# ---- classify_visual_readiness ----


def test_classify_needs_brief_when_missing():
    state = classify_visual_readiness(
        brief_status="missing",
        manifest_status="missing",
        cad_files=[],
        mesh_files=[],
        missing_renders=[],
        stale_renders=[],
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert state == "needs_brief"


def test_classify_blocked_when_brief_unreadable():
    state = classify_visual_readiness(
        brief_status="unreadable",
        manifest_status="ok",
        cad_files=["cad/a.scad"],
        mesh_files=[],
        missing_renders=[],
        stale_renders=[],
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert state == "blocked_or_incomplete"


def test_classify_blocked_when_manifest_unreadable():
    state = classify_visual_readiness(
        brief_status="ok",
        manifest_status="unreadable",
        cad_files=[],
        mesh_files=[],
        missing_renders=[],
        stale_renders=[],
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert state == "blocked_or_incomplete"


def test_classify_cad_source_ready_when_no_cad_yet():
    state = classify_visual_readiness(
        brief_status="ok",
        manifest_status="ok",
        cad_files=[],
        mesh_files=[],
        missing_renders=[],
        stale_renders=[],
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert state == "cad_source_ready"


def test_classify_needs_stl_export_when_cad_but_no_mesh():
    state = classify_visual_readiness(
        brief_status="ok",
        manifest_status="ok",
        cad_files=["cad/part.scad"],
        mesh_files=[],
        missing_renders=[],
        stale_renders=[],
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert state == "needs_stl_export"


def test_classify_needs_render_when_mesh_present_without_local_cad_source():
    # e.g. an imported/scanned STL with no local .scad/.py - should still
    # progress past "cad_source_ready" rather than falsely regressing there.
    state = classify_visual_readiness(
        brief_status="ok",
        manifest_status="ok",
        cad_files=[],
        mesh_files=["stl/imported.stl"],
        missing_renders=["stl/imported.stl"],
        stale_renders=[],
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert state == "needs_render"


def test_classify_needs_render_when_mesh_but_no_render():
    state = classify_visual_readiness(
        brief_status="ok",
        manifest_status="ok",
        cad_files=["cad/part.scad"],
        mesh_files=["stl/part.stl"],
        missing_renders=["stl/part.stl"],
        stale_renders=[],
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert state == "needs_render"


def test_classify_needs_render_when_only_some_meshes_are_missing_a_render():
    # Partial coverage - one of two meshes still has no render - must stay
    # the simple "needs_render" fix, not escalate to blocked_or_incomplete.
    state = classify_visual_readiness(
        brief_status="ok",
        manifest_status="ok",
        cad_files=["cad/a.scad", "cad/b.scad"],
        mesh_files=["stl/a.stl", "stl/b.stl"],
        missing_renders=["stl/b.stl"],
        stale_renders=[],
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert state == "needs_render"


def test_classify_slicer_review_ready_when_everything_present_and_clean():
    state = classify_visual_readiness(
        brief_status="ok",
        manifest_status="ok",
        cad_files=["cad/part.scad"],
        mesh_files=["stl/part.stl"],
        missing_renders=[],
        stale_renders=[],
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert state == "slicer_review_ready"


def test_classify_blocked_when_render_is_stale():
    state = classify_visual_readiness(
        brief_status="ok",
        manifest_status="ok",
        cad_files=["cad/part.scad"],
        mesh_files=["stl/part.stl"],
        missing_renders=[],
        stale_renders=["renders/part_preview.png"],
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert state == "blocked_or_incomplete"


def test_classify_blocked_when_stale_preview_despite_all_files_present():
    state = classify_visual_readiness(
        brief_status="ok",
        manifest_status="ok",
        cad_files=["cad/part.scad"],
        mesh_files=["stl/part.stl"],
        missing_renders=[],
        stale_renders=[],
        missing_visual_artifacts=[],
        stale_previews=["renders/part_preview.png is older than stl/part.stl"],
    )
    assert state == "blocked_or_incomplete"


def test_classify_not_blocked_by_orphan_renders_alone():
    # Orphan renders are advisory-only (see docs/render-coverage.md) - they
    # must never by themselves prevent slicer_review_ready.
    state = classify_visual_readiness(
        brief_status="ok",
        manifest_status="ok",
        cad_files=["cad/part.scad"],
        mesh_files=["stl/part.stl"],
        missing_renders=[],
        stale_renders=[],
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert state == "slicer_review_ready"


def test_all_documented_states_are_reachable():
    # Every VISUAL_READINESS_STATES entry must be producible by some input.
    reachable = {
        classify_visual_readiness(
            brief_status="missing", manifest_status="missing",
            cad_files=[], mesh_files=[], missing_renders=[], stale_renders=[],
            missing_visual_artifacts=[], stale_previews=[],
        ),
        classify_visual_readiness(
            brief_status="unreadable", manifest_status="ok",
            cad_files=[], mesh_files=[], missing_renders=[], stale_renders=[],
            missing_visual_artifacts=[], stale_previews=[],
        ),
        classify_visual_readiness(
            brief_status="ok", manifest_status="ok",
            cad_files=[], mesh_files=[], missing_renders=[], stale_renders=[],
            missing_visual_artifacts=[], stale_previews=[],
        ),
        classify_visual_readiness(
            brief_status="ok", manifest_status="ok",
            cad_files=["x"], mesh_files=[], missing_renders=[], stale_renders=[],
            missing_visual_artifacts=[], stale_previews=[],
        ),
        classify_visual_readiness(
            brief_status="ok", manifest_status="ok",
            cad_files=["x"], mesh_files=["y"], missing_renders=["y"], stale_renders=[],
            missing_visual_artifacts=[], stale_previews=[],
        ),
        classify_visual_readiness(
            brief_status="ok", manifest_status="ok",
            cad_files=["x"], mesh_files=["y"], missing_renders=[], stale_renders=[],
            missing_visual_artifacts=[], stale_previews=[],
        ),
    }
    assert reachable == set(VISUAL_READINESS_STATES)


# ---- summarize_project ----


def test_summarize_bare_directory_needs_brief(tmp_path):
    bare = tmp_path / "bare-dir"
    bare.mkdir()
    summary = summarize_project(bare)
    assert summary["visual_readiness_state"] == "needs_brief"
    assert summary["brief_exists"] is False
    assert summary["manifest_exists"] is False
    assert "brief.json is missing." in summary["warnings"]


def test_summarize_fresh_project_is_cad_source_ready(project_root):
    summary = summarize_project(project_root)
    assert summary["visual_readiness_state"] == "cad_source_ready"
    assert summary["brief_exists"] is True
    assert summary["manifest_exists"] is True
    assert summary["cad_files"] == []
    assert summary["brief_status"] == "brief_created"


def test_summarize_project_with_openscad_source_needs_stl_export(project_root):
    (project_root / "cad" / "part.scad").write_text("// scad\n", encoding="utf-8")
    summary = summarize_project(project_root)
    assert summary["visual_readiness_state"] == "needs_stl_export"
    assert summary["cad_files"] == ["cad/part.scad"]


def test_summarize_project_with_cadquery_source_needs_stl_export(project_root):
    (project_root / "cad" / "mechanical_plate.py").write_text("# cadquery source\n", encoding="utf-8")
    summary = summarize_project(project_root)
    assert summary["visual_readiness_state"] == "needs_stl_export"
    assert summary["cad_files"] == ["cad/mechanical_plate.py"]


def test_summarize_project_counts_mixed_openscad_and_cadquery_sources(project_root):
    (project_root / "cad" / "a_part.scad").write_text("// scad\n", encoding="utf-8")
    (project_root / "cad" / "b_part.py").write_text("# cadquery\n", encoding="utf-8")
    summary = summarize_project(project_root)
    assert summary["cad_files"] == ["cad/a_part.scad", "cad/b_part.py"]


def test_summarize_project_with_stl_needs_render(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    summary = summarize_project(project_root)
    assert summary["visual_readiness_state"] == "needs_render"
    assert summary["mesh_files"] == ["stl/part.stl"]


def test_summarize_project_slicer_review_ready_when_render_present(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png")
    summary = summarize_project(project_root)
    assert summary["visual_readiness_state"] == "slicer_review_ready"
    assert summary["warnings"] == [
        "No preview_package/index.json found - this summary was computed on the fly "
        "(read-only). Run `factory preview-project` to persist it."
    ]


def test_summarize_project_blocked_when_render_is_stale(project_root):
    stl_path = project_root / "stl" / "part.stl"
    render_path = project_root / "renders" / "part_preview.png"
    stl_path.write_bytes(b"fake stl")
    render_path.write_bytes(b"fake png")
    # Force the render to look older than the mesh it's supposed to preview.
    now = time.time()
    os.utime(render_path, (now - 1000, now - 1000))
    os.utime(stl_path, (now, now))

    summary = summarize_project(project_root)
    assert summary["visual_readiness_state"] == "blocked_or_incomplete"
    assert any("older than" in w for w in summary["warnings"])


def test_summarize_project_blocked_when_manifest_unreadable(project_root):
    (project_root / "part_manifest.json").write_text("{not valid json", encoding="utf-8")
    summary = summarize_project(project_root)
    assert summary["visual_readiness_state"] == "blocked_or_incomplete"
    assert summary["manifest_exists"] is True
    assert "part_manifest.json exists but could not be parsed as JSON." in summary["warnings"]


def test_summarize_project_blocked_when_brief_unreadable(project_root):
    (project_root / "brief.json").write_text("{not valid json", encoding="utf-8")
    summary = summarize_project(project_root)
    assert summary["visual_readiness_state"] == "blocked_or_incomplete"
    assert summary["brief_exists"] is True
    assert "brief.json exists but could not be parsed as JSON." in summary["warnings"]


def test_summarize_project_reuses_existing_preview_package(project_root):
    (project_root / "cad" / "part.scad").write_text("// scad\n", encoding="utf-8")
    write_preview_package(project_root)  # persists preview_package/index.json

    summary = summarize_project(project_root)
    assert summary["preview_package_exists"] is True
    assert not any("computed on the fly" in w for w in summary["warnings"])


def test_summarize_project_computes_lightweight_summary_when_package_missing(project_root):
    summary = summarize_project(project_root)
    assert summary["preview_package_exists"] is False
    assert any("computed on the fly" in w for w in summary["warnings"])


def test_summarize_project_reports_selected_manufacturing_option(project_root):
    build_plan = project_store.load_json(project_root / "build_plan.json")
    build_plan["selected_manufacturing_option"] = "single_piece"
    build_plan["status"] = "manufacturing_option_selected"
    project_store.save_json(project_root / "build_plan.json", build_plan)

    summary = summarize_project(project_root)
    assert summary["selected_manufacturing_option"] == "single_piece"
    assert summary["manufacturing_status"] == "manufacturing_option_selected"


def test_summarize_project_never_sets_human_approved_or_print_ready(project_root):
    summary = summarize_project(project_root)
    assert "human_approved" not in summary
    assert "print_ready" not in summary
    for value in summary.values():
        assert value != "human_approved"
        assert value != "print_ready"


# ---- gather_board_data ----


def test_gather_board_data_empty_root(tmp_path):
    root = tmp_path / "empty-root"
    root.mkdir()
    board = gather_board_data(root)
    assert board["project_count"] == 0
    assert board["projects"] == []
    assert board["state_counts"] == {state: 0 for state in VISUAL_READINESS_STATES}


def test_gather_board_data_nonexistent_root(tmp_path):
    board = gather_board_data(tmp_path / "nope")
    assert board["project_count"] == 0
    assert board["projects"] == []


def test_gather_board_data_multiple_projects(isolated_projects_dir):
    a = project_store.init_project("Alpha")
    b = project_store.init_project("Beta")
    (b / "cad" / "part.scad").write_text("// scad\n", encoding="utf-8")

    board = gather_board_data(isolated_projects_dir)
    assert board["project_count"] == 2
    names = {p["project_name"] for p in board["projects"]}
    assert names == {"Alpha", "Beta"}
    assert board["state_counts"]["cad_source_ready"] == 1
    assert board["state_counts"]["needs_stl_export"] == 1


def test_gather_board_data_never_writes_project_files(isolated_projects_dir):
    project_root_dir = project_store.init_project("Untouched")
    brief_before = (project_root_dir / "brief.json").read_text()
    manifest_before = (project_root_dir / "part_manifest.json").read_text()
    build_plan_before = (project_root_dir / "build_plan.json").read_text()

    gather_board_data(isolated_projects_dir)

    assert (project_root_dir / "brief.json").read_text() == brief_before
    assert (project_root_dir / "part_manifest.json").read_text() == manifest_before
    assert (project_root_dir / "build_plan.json").read_text() == build_plan_before


# ---- build_board_html ----


def _minimal_board(projects=None):
    return {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "projects_root": "/tmp/projects",
        "project_count": len(projects or []),
        "state_counts": {state: 0 for state in VISUAL_READINESS_STATES},
        "projects": projects or [],
        "notes": ["Local static preview only.", "Human slicer review required."],
    }


def _empty_render_coverage(project_dir: str = "/tmp/projects/demo") -> dict:
    return {
        "project_dir": project_dir,
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


def test_build_board_html_empty_projects_message():
    html = build_board_html(_minimal_board())
    assert "No projects found under this projects_root." in html


def test_build_board_html_renders_project_row():
    project = {
        "project_name": "Demo",
        "project_dir": "demo",
        "slug": "demo",
        "brief_exists": True,
        "brief_status": "cad_generated",
        "manufacturing_status": "plan_drafted",
        "selected_manufacturing_option": None,
        "manifest_exists": True,
        "preview_package_exists": True,
        "cad_files": ["cad/part.scad"],
        "mesh_files": [],
        "render_files": [],
        "render_coverage": _empty_render_coverage(),
        "visual_readiness_state": "needs_stl_export",
        "warnings": ["some warning"],
    }
    html = build_board_html(_minimal_board([project]))
    assert "Demo" in html
    assert "state-needs_stl_export" in html
    assert "some warning" in html
    assert "cad_generated" in html


def test_build_board_html_escapes_project_name():
    project = {
        "project_name": "<script>alert(1)</script>",
        "project_dir": "evil",
        "slug": "evil",
        "brief_exists": True,
        "brief_status": "idea",
        "manufacturing_status": None,
        "selected_manufacturing_option": None,
        "manifest_exists": True,
        "preview_package_exists": False,
        "cad_files": [],
        "mesh_files": [],
        "render_files": [],
        "render_coverage": _empty_render_coverage(),
        "visual_readiness_state": "cad_source_ready",
        "warnings": [],
    }
    html = build_board_html(_minimal_board([project]))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_build_board_html_has_no_external_assets_or_tracking():
    html = build_board_html(_minimal_board())
    forbidden = ["http://", "https://", "<script src", "cdn.", "google-analytics", "gtag(", "fetch(", "XMLHttpRequest"]
    for term in forbidden:
        assert term not in html


def test_build_board_html_includes_safety_notes():
    html = build_board_html(_minimal_board())
    assert "Human slicer review required." in html


# ---- write_preview_board ----


def test_write_preview_board_default_location(isolated_projects_dir):
    project_store.init_project("Demo")
    result = write_preview_board(isolated_projects_dir)

    index_path, html_path = preview_board_paths(isolated_projects_dir / "preview_board")
    assert result["index_path"] == index_path
    assert result["html_path"] == html_path
    assert index_path.is_file()
    assert html_path.is_file()


def test_write_preview_board_custom_output_dir(isolated_projects_dir, tmp_path):
    project_store.init_project("Demo")
    custom_output = tmp_path / "custom-board"
    result = write_preview_board(isolated_projects_dir, output_dir=custom_output)

    assert result["index_path"] == custom_output / "index.json"
    assert result["html_path"] == custom_output / "index.html"
    assert (custom_output / "index.json").is_file()
    assert (custom_output / "index.html").is_file()


def test_write_preview_board_format_json_only(isolated_projects_dir):
    project_store.init_project("Demo")
    result = write_preview_board(isolated_projects_dir, fmt="json")

    assert result["index_path"] is not None
    assert result["html_path"] is None
    index_path, html_path = preview_board_paths(isolated_projects_dir / "preview_board")
    assert index_path.is_file()
    assert not html_path.exists()


def test_write_preview_board_format_html_only(isolated_projects_dir):
    project_store.init_project("Demo")
    result = write_preview_board(isolated_projects_dir, fmt="html")

    assert result["html_path"] is not None
    assert result["index_path"] is None
    index_path, html_path = preview_board_paths(isolated_projects_dir / "preview_board")
    assert html_path.is_file()
    assert not index_path.exists()


def test_write_preview_board_rejects_invalid_format(isolated_projects_dir):
    with pytest.raises(ValueError):
        write_preview_board(isolated_projects_dir, fmt="xml")


def test_write_preview_board_never_touches_project_state_files(isolated_projects_dir):
    project_root_dir = project_store.init_project("Demo")
    brief_before = (project_root_dir / "brief.json").read_text()
    manifest_before = (project_root_dir / "part_manifest.json").read_text()
    build_plan_before = (project_root_dir / "build_plan.json").read_text()

    write_preview_board(isolated_projects_dir)

    assert (project_root_dir / "brief.json").read_text() == brief_before
    assert (project_root_dir / "part_manifest.json").read_text() == manifest_before
    assert (project_root_dir / "build_plan.json").read_text() == build_plan_before
    assert "human_approved" not in brief_before
    assert "print_ready" not in brief_before


def test_write_preview_board_does_not_advance_brief_status(isolated_projects_dir):
    project_root_dir = project_store.init_project("Demo")
    assert project_store.load_json(project_root_dir / "brief.json")["status"] == "brief_created"

    write_preview_board(isolated_projects_dir)

    assert project_store.load_json(project_root_dir / "brief.json")["status"] == "brief_created"


# ---- CLI ----


def test_cli_preview_board_happy_path(isolated_projects_dir):
    runner.invoke(app, ["init-project", "Demo Project"])
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout
    assert (isolated_projects_dir / "preview_board" / "index.json").is_file()
    assert (isolated_projects_dir / "preview_board" / "index.html").is_file()


def test_cli_preview_board_missing_root():
    result = runner.invoke(app, ["preview-board", "/nonexistent/path/xyz"])
    assert result.exit_code != 0


def test_cli_preview_board_invalid_format(isolated_projects_dir):
    runner.invoke(app, ["init-project", "Demo Project"])
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir), "--format", "xml"])
    assert result.exit_code != 0


def test_cli_preview_board_custom_output(isolated_projects_dir, tmp_path):
    runner.invoke(app, ["init-project", "Demo Project"])
    custom_output = tmp_path / "custom-out"
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir), "--output", str(custom_output)])
    assert result.exit_code == 0, result.stdout
    assert (custom_output / "index.json").is_file()
    assert (custom_output / "index.html").is_file()


def test_cli_preview_board_empty_root_still_succeeds(tmp_path):
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    result = runner.invoke(app, ["preview-board", str(empty_root)])
    assert result.exit_code == 0, result.stdout
    assert (empty_root / "preview_board" / "index.json").is_file()


# ---- safety: no network/subprocess/printer/slicer behavior anywhere in this module ----


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


def test_preview_board_module_has_no_network_or_process_calls():
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
    tree = _strip_docstrings(ast.parse(inspect.getsource(preview_board_module)))
    code_only_source = ast.unparse(tree)
    for forbidden_term in forbidden:
        assert forbidden_term not in code_only_source, (
            f"factory.preview_board must stay local-only; found {forbidden_term!r}"
        )


def test_preview_board_module_never_writes_project_state_paths():
    source = inspect.getsource(preview_board_module)
    # The module reads brief.json/build_plan.json/part_manifest.json but must
    # never call save_json or advance_status on any project's state files -
    # only board output files (index.json/index.html) are ever written.
    assert "save_json(index_path" in source
    assert "advance_status" not in source

    # human_approved/print_ready may be named in prose (docstrings/comments)
    # explaining that this module never computes them - only the code itself
    # must never reference them as values or statuses.
    tree = _strip_docstrings(ast.parse(source))
    code_only_source = ast.unparse(tree)
    assert "human_approved" not in code_only_source
    assert "print_ready" not in code_only_source


# ---- build_suggested_actions (Phase 10) ----


# Directive/action phrases that would mean this suggestion tells the human to
# actually print, send, upload, or call an external service - not merely
# mentioning "print" defensively (e.g. "do not print yet" is fine and expected).
_FORBIDDEN_ACTION_LANGUAGE = (
    "send to printer", "start print", "begin printing", "print now", "click print",
    "print this", "send this", "upload", "meshy", "blender", "bambu cloud",
    "api key", "api call", "cloud api",
)


def _assert_actions_are_safe(actions: list[dict]) -> None:
    for action in actions:
        assert set(action.keys()) == {"kind", "label", "command", "safety", "reason"}
        assert action["safety"] == ACTION_SAFETY
        haystack = " ".join([action["label"], action["command"], action["reason"]]).lower()
        for forbidden in _FORBIDDEN_ACTION_LANGUAGE:
            assert forbidden not in haystack, f"found forbidden language {forbidden!r} in action {action!r}"


def test_suggested_actions_for_needs_brief():
    actions = build_suggested_actions(
        visual_readiness_state="needs_brief",
        project_path="projects/demo",
        brief_status="missing",
        manifest_status="missing",
        render_coverage=_empty_render_coverage(),
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert len(actions) == 1
    assert actions[0]["kind"] == "create_brief_missing"
    assert "projects/demo/brief.json" in actions[0]["command"]
    _assert_actions_are_safe(actions)


def test_suggested_actions_for_cad_source_ready():
    actions = build_suggested_actions(
        visual_readiness_state="cad_source_ready",
        project_path="projects/demo",
        brief_status="ok",
        manifest_status="ok",
        render_coverage=_empty_render_coverage(),
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert len(actions) == 1
    assert actions[0]["kind"] == "generate_cad_source"
    assert actions[0]["command"] == "factory route-cad projects/demo"
    _assert_actions_are_safe(actions)


def test_suggested_actions_for_needs_stl_export():
    actions = build_suggested_actions(
        visual_readiness_state="needs_stl_export",
        project_path="projects/demo",
        brief_status="ok",
        manifest_status="ok",
        render_coverage=_empty_render_coverage(),
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert len(actions) == 1
    assert actions[0]["kind"] == "export_stl_manual"
    assert "projects/demo/stl" in actions[0]["command"]
    _assert_actions_are_safe(actions)


def test_suggested_actions_for_needs_render_single_missing():
    coverage = _empty_render_coverage()
    coverage["missing_renders"] = ["stl/part_a.stl"]
    actions = build_suggested_actions(
        visual_readiness_state="needs_render",
        project_path="projects/demo",
        brief_status="ok",
        manifest_status="ok",
        render_coverage=coverage,
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert len(actions) == 1
    assert actions[0]["kind"] == "render_missing_mesh"
    assert actions[0]["command"] == "factory render projects/demo/stl/part_a.stl"
    assert "missing" in actions[0]["reason"].lower()
    _assert_actions_are_safe(actions)


def test_suggested_actions_for_needs_render_multiple_missing():
    coverage = _empty_render_coverage()
    coverage["missing_renders"] = ["stl/a.stl", "stl/b.stl"]
    actions = build_suggested_actions(
        visual_readiness_state="needs_render",
        project_path="projects/demo",
        brief_status="ok",
        manifest_status="ok",
        render_coverage=coverage,
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    commands = {a["command"] for a in actions}
    assert commands == {"factory render projects/demo/stl/a.stl", "factory render projects/demo/stl/b.stl"}
    _assert_actions_are_safe(actions)


def test_suggested_actions_for_needs_render_stale():
    coverage = _empty_render_coverage()
    coverage["stale_renders"] = ["renders/part_a_preview.png"]
    actions = build_suggested_actions(
        visual_readiness_state="needs_render",
        project_path="projects/demo",
        brief_status="ok",
        manifest_status="ok",
        render_coverage=coverage,
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert len(actions) == 1
    assert actions[0]["command"] == "factory render projects/demo/stl/part_a.stl"
    assert "stale" in actions[0]["reason"].lower() or "older" in actions[0]["reason"].lower()
    _assert_actions_are_safe(actions)


def test_suggested_actions_for_slicer_review_ready_is_manual_review_only():
    actions = build_suggested_actions(
        visual_readiness_state="slicer_review_ready",
        project_path="projects/demo",
        brief_status="ok",
        manifest_status="ok",
        render_coverage=_empty_render_coverage(),
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert len(actions) == 1
    assert actions[0]["kind"] == "review_slicer_manually"
    assert "do not print" in actions[0]["reason"].lower() or "not for printing" in actions[0]["reason"].lower()
    _assert_actions_are_safe(actions)


def test_suggested_actions_for_blocked_or_incomplete_is_inspection_only():
    actions = build_suggested_actions(
        visual_readiness_state="blocked_or_incomplete",
        project_path="projects/demo",
        brief_status="unreadable",
        manifest_status="ok",
        render_coverage=_empty_render_coverage(),
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert len(actions) == 1
    assert actions[0]["kind"] == "inspect_blocked_project"
    assert "factory report projects/demo" in actions[0]["command"]
    assert "approve" not in actions[0]["reason"].lower()
    assert "print" not in actions[0]["reason"].lower()
    _assert_actions_are_safe(actions)


def test_suggested_actions_for_blocked_reflects_actual_cause():
    coverage = _empty_render_coverage()
    coverage["stale_renders"] = ["renders/x_preview.png"]
    actions = build_suggested_actions(
        visual_readiness_state="blocked_or_incomplete",
        project_path="projects/demo",
        brief_status="ok",
        manifest_status="ok",
        render_coverage=coverage,
        missing_visual_artifacts=["Missing STL for part 'x'."],
        stale_previews=["renders/y_preview.png is older than stl/y.stl"],
    )
    reason = actions[0]["reason"]
    assert "older than their stl" in reason.lower()
    assert "missing visual artifact" in reason.lower()
    assert "stale preview" in reason.lower()


def test_suggested_actions_are_deterministic():
    coverage = _empty_render_coverage()
    coverage["missing_renders"] = ["stl/a.stl", "stl/b.stl"]
    kwargs = dict(
        visual_readiness_state="needs_render",
        project_path="projects/demo",
        brief_status="ok",
        manifest_status="ok",
        render_coverage=coverage,
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert build_suggested_actions(**kwargs) == build_suggested_actions(**kwargs)


def test_no_suggested_action_kind_contains_forbidden_execution_behavior():
    # Exercise every state at least once and check none slip in forbidden wording.
    coverage_with_gaps = _empty_render_coverage()
    coverage_with_gaps["missing_renders"] = ["stl/a.stl"]
    scenarios = [
        dict(visual_readiness_state="needs_brief", brief_status="missing", manifest_status="missing", render_coverage=_empty_render_coverage()),
        dict(visual_readiness_state="cad_source_ready", brief_status="ok", manifest_status="ok", render_coverage=_empty_render_coverage()),
        dict(visual_readiness_state="needs_stl_export", brief_status="ok", manifest_status="ok", render_coverage=_empty_render_coverage()),
        dict(visual_readiness_state="needs_render", brief_status="ok", manifest_status="ok", render_coverage=coverage_with_gaps),
        dict(visual_readiness_state="slicer_review_ready", brief_status="ok", manifest_status="ok", render_coverage=_empty_render_coverage()),
        dict(visual_readiness_state="blocked_or_incomplete", brief_status="unreadable", manifest_status="ok", render_coverage=_empty_render_coverage()),
    ]
    for scenario in scenarios:
        actions = build_suggested_actions(
            project_path="projects/demo",
            missing_visual_artifacts=[],
            stale_previews=[],
            **scenario,
        )
        assert len(actions) >= 1
        _assert_actions_are_safe(actions)


# ---- summarize_project integration: suggested_actions ----


def test_summarize_project_includes_suggested_actions_field(project_root):
    summary = summarize_project(project_root)
    assert "suggested_actions" in summary
    assert isinstance(summary["suggested_actions"], list)


def test_summarize_bare_directory_suggests_creating_brief(tmp_path):
    bare = tmp_path / "bare-dir"
    bare.mkdir()
    summary = summarize_project(bare)
    assert summary["suggested_actions"][0]["kind"] == "create_brief_missing"
    _assert_actions_are_safe(summary["suggested_actions"])


def test_summarize_project_with_missing_render_suggests_factory_render(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    summary = summarize_project(project_root)
    assert summary["visual_readiness_state"] == "needs_render"
    actions = summary["suggested_actions"]
    render_actions = [a for a in actions if a["kind"] == "render_missing_mesh"]
    assert len(render_actions) == 1
    assert str(project_root) in render_actions[0]["command"]
    assert "stl/part.stl" in render_actions[0]["command"]
    _assert_actions_are_safe(actions)


def test_summarize_project_fully_covered_suggests_manual_review_only(project_root):
    # "Fully covered" means STL + render + validation report all present -
    # only then should the only suggestion be the manual slicer review.
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png")
    (project_root / "validation" / "part_validation.json").write_text('{"overall_status": "PASS"}', encoding="utf-8")
    summary = summarize_project(project_root)
    assert summary["visual_readiness_state"] == "slicer_review_ready"
    actions = summary["suggested_actions"]
    assert len(actions) == 1
    assert actions[0]["kind"] == "review_slicer_manually"
    _assert_actions_are_safe(actions)


def test_summarize_project_blocked_suggests_inspection_not_approval(project_root):
    (project_root / "part_manifest.json").write_text("{not valid json", encoding="utf-8")
    summary = summarize_project(project_root)
    assert summary["visual_readiness_state"] == "blocked_or_incomplete"
    actions = summary["suggested_actions"]
    assert len(actions) == 1
    assert actions[0]["kind"] == "inspect_blocked_project"
    _assert_actions_are_safe(actions)


def test_summarize_project_action_command_matches_plan_render_commands(project_root):
    (project_root / "stl" / "a.stl").write_bytes(b"a")
    (project_root / "stl" / "b.stl").write_bytes(b"b")
    (project_root / "renders" / "a_preview.png").write_bytes(b"a-png")
    summary = summarize_project(project_root)
    coverage = compute_render_coverage(project_root)
    from factory.render_coverage import plan_render_commands

    expected_suffixes = {cmd.removeprefix("factory render ") for cmd in plan_render_commands(coverage)}
    render_actions = [a for a in summary["suggested_actions"] if a["kind"] == "render_missing_mesh"]
    actual_suffixes = {a["command"].removeprefix(f"factory render {project_root}/") for a in render_actions}
    assert actual_suffixes == expected_suffixes


# ---- HTML: Suggested next steps section ----


def test_build_board_html_includes_suggestions_section():
    html = build_board_html(_minimal_board())
    assert "Suggested next steps" in html


def test_build_board_html_renders_action_command_and_reason():
    project = {
        "project_name": "Demo",
        "project_dir": "demo",
        "slug": "demo",
        "brief_exists": True,
        "brief_status": "cad_generated",
        "manufacturing_status": "plan_drafted",
        "selected_manufacturing_option": None,
        "manifest_exists": True,
        "preview_package_exists": True,
        "cad_files": ["cad/part.scad"],
        "mesh_files": ["stl/part.stl"],
        "render_files": [],
        "render_coverage": _empty_render_coverage(),
        "visual_readiness_state": "needs_render",
        "warnings": [],
        "suggested_actions": [
            {
                "kind": "render_missing_mesh",
                "label": "Render missing STL preview",
                "command": "factory render projects/demo/stl/part.stl",
                "safety": "manual_only",
                "reason": "STL exists but the matching render PNG is missing.",
            }
        ],
    }
    html = build_board_html(_minimal_board([project]))
    assert "factory render projects/demo/stl/part.stl" in html
    assert "STL exists but the matching render PNG is missing." in html
    assert "manual_only" in html


def test_build_board_html_suggestions_escape_html():
    project = {
        "project_name": "Demo",
        "project_dir": "demo",
        "slug": "demo",
        "brief_exists": True,
        "brief_status": "idea",
        "manufacturing_status": None,
        "selected_manufacturing_option": None,
        "manifest_exists": True,
        "preview_package_exists": False,
        "cad_files": [],
        "mesh_files": [],
        "render_files": [],
        "render_coverage": _empty_render_coverage(),
        "visual_readiness_state": "cad_source_ready",
        "warnings": [],
        "suggested_actions": [
            {
                "kind": "generate_cad_source",
                "label": "<script>alert(1)</script>",
                "command": "<img onerror=alert(1)>",
                "safety": "manual_only",
                "reason": "<b>reason</b>",
            }
        ],
    }
    html = build_board_html(_minimal_board([project]))
    assert "<script>alert(1)</script>" not in html
    assert "<img onerror=alert(1)>" not in html
    assert "&lt;script&gt;" in html


def test_build_board_html_no_suggestions_when_no_projects():
    html = build_board_html(_minimal_board())
    assert "No suggested actions" in html


def test_build_board_html_suggestions_have_no_external_assets_or_copy_js():
    html = build_board_html(_minimal_board())
    forbidden = ["http://", "https://", "<script", "cdn.", "clipboard", "navigator.clipboard", "onclick="]
    for term in forbidden:
        assert term not in html


def test_cli_preview_board_json_includes_suggested_actions(isolated_projects_dir):
    runner.invoke(app, ["init-project", "Demo Project"])
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    import json

    board = json.loads((isolated_projects_dir / "preview_board" / "index.json").read_text())
    assert board["projects"][0]["suggested_actions"]


def test_cli_preview_board_html_includes_suggested_next_steps(isolated_projects_dir):
    runner.invoke(app, ["init-project", "Demo Project"])
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    html = (isolated_projects_dir / "preview_board" / "index.html").read_text()
    assert "Suggested next steps" in html
    assert "factory route-cad" in html


# ---- build_health_signals (Phase 11) ----


_FORBIDDEN_SIGNAL_LANGUAGE = _FORBIDDEN_ACTION_LANGUAGE


def _assert_health_signals_are_safe(health: dict) -> None:
    assert set(health.keys()) == {"summary", "items"}
    assert health["summary"] in ("ok", "attention_needed", "blocked")
    for item in health["items"]:
        assert set(item.keys()) == {"kind", "severity", "message", "suggested_action_kind"}
        assert item["severity"] in HEALTH_SEVERITIES
        haystack = item["message"].lower()
        for forbidden in _FORBIDDEN_SIGNAL_LANGUAGE:
            assert forbidden not in haystack, f"found forbidden language {forbidden!r} in signal {item!r}"
        assert "human_approved" not in haystack
        assert "print_ready" not in haystack


def _base_health_kwargs(**overrides) -> dict:
    kwargs = dict(
        visual_readiness_state="cad_source_ready",
        brief_status="ok",
        manifest_status="ok",
        preview_package_status="ok",
        selected_manufacturing_option="single_piece",
        mesh_files=[],
        render_coverage=_empty_render_coverage(),
        missing_visual_artifacts=[],
        stale_previews=[],
        validation_missing=[],
        validation_present_count=0,
    )
    kwargs.update(overrides)
    return kwargs


def test_health_signals_ok_when_nothing_to_flag():
    health = build_health_signals(**_base_health_kwargs())
    assert health["summary"] == "ok"
    assert health["items"] == []


def test_health_signals_missing_brief_is_warning():
    health = build_health_signals(**_base_health_kwargs(visual_readiness_state="needs_brief", brief_status="missing"))
    assert health["summary"] == "attention_needed"
    item = next(i for i in health["items"] if i["kind"] == "brief_missing")
    assert item["severity"] == "warning"
    assert item["suggested_action_kind"] == "create_brief_missing"
    _assert_health_signals_are_safe(health)


def test_health_signals_unreadable_brief_is_blocked():
    health = build_health_signals(**_base_health_kwargs(visual_readiness_state="blocked_or_incomplete", brief_status="unreadable"))
    assert health["summary"] == "blocked"
    item = next(i for i in health["items"] if i["kind"] == "brief_unreadable")
    assert item["severity"] == "blocked"
    _assert_health_signals_are_safe(health)


def test_health_signals_missing_manifest_is_warning():
    health = build_health_signals(**_base_health_kwargs(manifest_status="missing"))
    item = next(i for i in health["items"] if i["kind"] == "manifest_missing")
    assert item["severity"] == "warning"
    assert item["suggested_action_kind"] == "inspect_blocked_project"
    assert health["summary"] == "attention_needed"
    _assert_health_signals_are_safe(health)


def test_health_signals_unreadable_manifest_is_blocked():
    health = build_health_signals(
        **_base_health_kwargs(visual_readiness_state="blocked_or_incomplete", manifest_status="unreadable")
    )
    item = next(i for i in health["items"] if i["kind"] == "manifest_unreadable")
    assert item["severity"] == "blocked"
    assert health["summary"] == "blocked"
    _assert_health_signals_are_safe(health)


def test_health_signals_manufacturing_option_not_selected_only_when_brief_ok():
    health = build_health_signals(**_base_health_kwargs(selected_manufacturing_option=None))
    kinds = {i["kind"] for i in health["items"]}
    assert "manufacturing_option_not_selected" in kinds

    # Not shown when there's no brief to plan from yet - avoids redundant noise.
    health_no_brief = build_health_signals(
        **_base_health_kwargs(visual_readiness_state="needs_brief", brief_status="missing", selected_manufacturing_option=None)
    )
    kinds_no_brief = {i["kind"] for i in health_no_brief["items"]}
    assert "manufacturing_option_not_selected" not in kinds_no_brief


def test_health_signals_preview_package_missing_is_info():
    health = build_health_signals(**_base_health_kwargs(preview_package_status="missing"))
    item = next(i for i in health["items"] if i["kind"] == "preview_package_missing")
    assert item["severity"] == "info"
    _assert_health_signals_are_safe(health)


def test_health_signals_preview_package_unreadable_is_warning():
    health = build_health_signals(**_base_health_kwargs(preview_package_status="unreadable"))
    item = next(i for i in health["items"] if i["kind"] == "preview_package_unreadable")
    assert item["severity"] == "warning"
    _assert_health_signals_are_safe(health)


def test_health_signals_render_missing_is_warning():
    coverage = _empty_render_coverage()
    coverage["missing_renders"] = ["stl/a.stl"]
    health = build_health_signals(
        **_base_health_kwargs(visual_readiness_state="needs_render", mesh_files=["stl/a.stl"], render_coverage=coverage)
    )
    item = next(i for i in health["items"] if i["kind"] == "render_missing")
    assert item["severity"] == "warning"
    assert item["suggested_action_kind"] == "render_missing_mesh"
    _assert_health_signals_are_safe(health)


def test_health_signals_render_stale_is_blocked_consistent_with_classification():
    # Stale-only (no missing) always resolves classify_visual_readiness to
    # blocked_or_incomplete - the health signal severity must agree.
    coverage = _empty_render_coverage()
    coverage["stale_renders"] = ["renders/a_preview.png"]
    state = classify_visual_readiness(
        brief_status="ok", manifest_status="ok", cad_files=["cad/a.scad"], mesh_files=["stl/a.stl"],
        missing_renders=[], stale_renders=["renders/a_preview.png"],
        missing_visual_artifacts=[], stale_previews=[],
    )
    assert state == "blocked_or_incomplete"
    health = build_health_signals(
        **_base_health_kwargs(visual_readiness_state=state, mesh_files=["stl/a.stl"], render_coverage=coverage)
    )
    item = next(i for i in health["items"] if i["kind"] == "render_stale")
    assert item["severity"] == "blocked"
    assert health["summary"] == "blocked"
    _assert_health_signals_are_safe(health)


def test_health_signals_render_orphan_is_advisory_info_only():
    coverage = _empty_render_coverage()
    coverage["orphan_renders"] = ["renders/leftover_preview.png"]
    health = build_health_signals(**_base_health_kwargs(render_coverage=coverage))
    item = next(i for i in health["items"] if i["kind"] == "render_orphan")
    assert item["severity"] == "info"
    # An orphan alone must never push the overall summary to blocked/attention_needed.
    assert health["summary"] == "ok"
    _assert_health_signals_are_safe(health)


def test_health_signals_validation_missing_is_warning():
    health = build_health_signals(
        **_base_health_kwargs(mesh_files=["stl/a.stl"], validation_missing=["stl/a.stl"])
    )
    item = next(i for i in health["items"] if i["kind"] == "validation_missing")
    assert item["severity"] == "warning"
    assert item["suggested_action_kind"] == "validate_mesh_manual"
    assert health["summary"] == "attention_needed"
    _assert_health_signals_are_safe(health)


def test_health_signals_validation_present_is_info():
    health = build_health_signals(
        **_base_health_kwargs(mesh_files=["stl/a.stl"], validation_present_count=1)
    )
    item = next(i for i in health["items"] if i["kind"] == "validation_present")
    assert item["severity"] == "info"
    _assert_health_signals_are_safe(health)


def test_health_signals_validation_missing_and_present_can_coexist():
    health = build_health_signals(
        **_base_health_kwargs(
            mesh_files=["stl/a.stl", "stl/b.stl"], validation_missing=["stl/b.stl"], validation_present_count=1
        )
    )
    kinds = {i["kind"] for i in health["items"]}
    assert {"validation_missing", "validation_present"} <= kinds


def test_health_signals_slicer_review_ready_is_ready_not_approval():
    health = build_health_signals(**_base_health_kwargs(visual_readiness_state="slicer_review_ready"))
    item = next(i for i in health["items"] if i["kind"] == "slicer_review_ready")
    assert item["severity"] == "ready"
    assert item["suggested_action_kind"] == "review_slicer_manually"
    assert "print_ready" not in item["message"].lower()
    assert "human_approved" not in item["message"].lower()
    _assert_health_signals_are_safe(health)


def test_health_signals_summary_rolls_up_to_blocked_over_warning():
    coverage = _empty_render_coverage()
    coverage["stale_renders"] = ["renders/a_preview.png"]
    health = build_health_signals(
        **_base_health_kwargs(
            visual_readiness_state="blocked_or_incomplete",
            manifest_status="missing",  # warning-level
            mesh_files=["stl/a.stl"],
            render_coverage=coverage,  # blocked-level
        )
    )
    assert health["summary"] == "blocked"


def test_health_signals_are_deterministic():
    kwargs = _base_health_kwargs(manifest_status="missing")
    assert build_health_signals(**kwargs) == build_health_signals(**kwargs)


def test_health_signals_never_produce_approval_or_print_readiness_kind():
    # Exercise a broad mix of inputs and confirm no kind/severity implies approval.
    coverage = _empty_render_coverage()
    coverage["missing_renders"] = ["stl/a.stl"]
    coverage["stale_renders"] = []
    coverage["orphan_renders"] = ["renders/orphan_preview.png"]
    health = build_health_signals(
        **_base_health_kwargs(
            visual_readiness_state="needs_render",
            mesh_files=["stl/a.stl"],
            render_coverage=coverage,
            validation_missing=["stl/a.stl"],
        )
    )
    for item in health["items"]:
        assert item["kind"] not in ("human_approved", "print_ready", "approved", "print_ready_signal")
    _assert_health_signals_are_safe(health)


# ---- summarize_project integration: health_signals + validation coverage ----


def test_summarize_project_includes_health_signals_field(project_root):
    summary = summarize_project(project_root)
    assert "health_signals" in summary
    assert summary["health_signals"]["summary"] in ("ok", "attention_needed", "blocked")


def test_summarize_project_missing_manifest_creates_warning_health_signal(project_root):
    (project_root / "part_manifest.json").unlink()
    summary = summarize_project(project_root)
    kinds = {i["kind"]: i["severity"] for i in summary["health_signals"]["items"]}
    assert kinds["manifest_missing"] == "warning"


def test_summarize_project_unreadable_manifest_creates_blocked_health_signal(project_root):
    (project_root / "part_manifest.json").write_text("{not valid json", encoding="utf-8")
    summary = summarize_project(project_root)
    kinds = {i["kind"]: i["severity"] for i in summary["health_signals"]["items"]}
    assert kinds["manifest_unreadable"] == "blocked"
    assert summary["health_signals"]["summary"] == "blocked"


def test_summarize_project_stl_without_validation_report_creates_warning_and_suggestion(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    summary = summarize_project(project_root)

    kinds = {i["kind"]: i for i in summary["health_signals"]["items"]}
    assert kinds["validation_missing"]["severity"] == "warning"

    validate_actions = [a for a in summary["suggested_actions"] if a["kind"] == "validate_mesh_manual"]
    assert len(validate_actions) == 1
    assert validate_actions[0]["command"] == f"factory validate {project_root}/stl/part.stl"
    _assert_actions_are_safe(validate_actions)


def test_summarize_project_validation_report_present_creates_info_signal(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "validation" / "part_validation.json").write_text('{"overall_status": "PASS"}', encoding="utf-8")
    summary = summarize_project(project_root)

    kinds = {i["kind"]: i for i in summary["health_signals"]["items"]}
    assert kinds["validation_present"]["severity"] == "info"
    assert "validation_missing" not in kinds
    assert not any(a["kind"] == "validate_mesh_manual" for a in summary["suggested_actions"])


def test_summarize_project_validation_folder_missing_when_stl_exists_counts_as_missing(project_root):
    import shutil

    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    shutil.rmtree(project_root / "validation")
    summary = summarize_project(project_root)
    kinds = {i["kind"]: i for i in summary["health_signals"]["items"]}
    assert kinds["validation_missing"]["severity"] == "warning"


def test_summarize_project_fully_covered_shows_ready_health_signal(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png")
    (project_root / "validation" / "part_validation.json").write_text('{"overall_status": "PASS"}', encoding="utf-8")
    summary = summarize_project(project_root)

    assert summary["visual_readiness_state"] == "slicer_review_ready"
    kinds = {i["kind"]: i for i in summary["health_signals"]["items"]}
    assert kinds["slicer_review_ready"]["severity"] == "ready"
    assert "human_approved" not in str(summary)
    assert "print_ready" not in str(summary)


def test_summarize_project_never_writes_validation_reports(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    summarize_project(project_root)
    assert not (project_root / "validation" / "part_validation.json").exists()


# ---- HTML: Health signals section ----


def test_build_board_html_includes_health_signals_section():
    html = build_board_html(_minimal_board())
    assert "Health signals" in html


def test_build_board_html_renders_health_items():
    project = {
        "project_name": "Demo",
        "project_dir": "demo",
        "slug": "demo",
        "brief_exists": True,
        "brief_status": "cad_generated",
        "manufacturing_status": "plan_drafted",
        "selected_manufacturing_option": None,
        "manifest_exists": True,
        "preview_package_exists": True,
        "cad_files": ["cad/part.scad"],
        "mesh_files": ["stl/part.stl"],
        "render_files": [],
        "render_coverage": _empty_render_coverage(),
        "visual_readiness_state": "needs_render",
        "warnings": [],
        "suggested_actions": [],
        "health_signals": {
            "summary": "attention_needed",
            "items": [
                {
                    "kind": "render_missing",
                    "severity": "warning",
                    "message": "1 STL file(s) have no matching render yet.",
                    "suggested_action_kind": "render_missing_mesh",
                }
            ],
        },
    }
    html = build_board_html(_minimal_board([project]))
    assert "1 STL file(s) have no matching render yet." in html
    assert "health-warning" in html
    assert "health-summary-attention_needed" in html


def test_build_board_html_health_signals_escape_html():
    project = {
        "project_name": "Demo",
        "project_dir": "demo",
        "slug": "demo",
        "brief_exists": True,
        "brief_status": "idea",
        "manufacturing_status": None,
        "selected_manufacturing_option": None,
        "manifest_exists": True,
        "preview_package_exists": False,
        "cad_files": [],
        "mesh_files": [],
        "render_files": [],
        "render_coverage": _empty_render_coverage(),
        "visual_readiness_state": "cad_source_ready",
        "warnings": [],
        "suggested_actions": [],
        "health_signals": {
            "summary": "attention_needed",
            "items": [
                {
                    "kind": "manifest_missing",
                    "severity": "warning",
                    "message": "<script>alert(1)</script>",
                    "suggested_action_kind": None,
                }
            ],
        },
    }
    html = build_board_html(_minimal_board([project]))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_build_board_html_no_health_signals_message_when_no_projects():
    html = build_board_html(_minimal_board())
    assert "No health signals" in html


def test_build_board_html_health_signals_no_external_assets_or_js():
    html = build_board_html(_minimal_board())
    forbidden = ["http://", "https://", "<script", "cdn.", "onclick=", "navigator.clipboard"]
    for term in forbidden:
        assert term not in html


def test_cli_preview_board_json_includes_health_signals(isolated_projects_dir):
    runner.invoke(app, ["init-project", "Demo Project"])
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    import json

    board = json.loads((isolated_projects_dir / "preview_board" / "index.json").read_text())
    assert "health_signals" in board["projects"][0]


def test_cli_preview_board_html_includes_health_signals_section(isolated_projects_dir):
    runner.invoke(app, ["init-project", "Demo Project"])
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

    html = (isolated_projects_dir / "preview_board" / "index.html").read_text()
    assert "Health signals" in html


# ---- safety: health signals never contain unsafe execution language ----


def test_no_health_signal_kind_contains_forbidden_execution_behavior():
    coverage_with_gaps = _empty_render_coverage()
    coverage_with_gaps["missing_renders"] = ["stl/a.stl"]
    coverage_with_stale = _empty_render_coverage()
    coverage_with_stale["stale_renders"] = ["renders/a_preview.png"]
    scenarios = [
        _base_health_kwargs(visual_readiness_state="needs_brief", brief_status="missing"),
        _base_health_kwargs(manifest_status="missing"),
        _base_health_kwargs(visual_readiness_state="blocked_or_incomplete", manifest_status="unreadable"),
        _base_health_kwargs(mesh_files=["stl/a.stl"], render_coverage=coverage_with_gaps, visual_readiness_state="needs_render"),
        _base_health_kwargs(mesh_files=["stl/a.stl"], render_coverage=coverage_with_stale, visual_readiness_state="blocked_or_incomplete"),
        _base_health_kwargs(mesh_files=["stl/a.stl"], validation_missing=["stl/a.stl"]),
        _base_health_kwargs(visual_readiness_state="slicer_review_ready"),
    ]
    for kwargs in scenarios:
        health = build_health_signals(**kwargs)
        _assert_health_signals_are_safe(health)

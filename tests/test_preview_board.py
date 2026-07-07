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
    VISUAL_READINESS_STATES,
    build_board_html,
    classify_visual_readiness,
    discover_projects,
    gather_board_data,
    preview_board_paths,
    summarize_project,
    write_preview_board,
)
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
        render_files=[],
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
        render_files=[],
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
        render_files=[],
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
        render_files=[],
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
        render_files=[],
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
        render_files=[],
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
        render_files=[],
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
        render_files=["renders/part_preview.png"],
        missing_visual_artifacts=[],
        stale_previews=[],
    )
    assert state == "slicer_review_ready"


def test_classify_blocked_when_stale_preview_despite_all_files_present():
    state = classify_visual_readiness(
        brief_status="ok",
        manifest_status="ok",
        cad_files=["cad/part.scad"],
        mesh_files=["stl/part.stl"],
        render_files=["renders/part_preview.png"],
        missing_visual_artifacts=[],
        stale_previews=["renders/part_preview.png is older than stl/part.stl"],
    )
    assert state == "blocked_or_incomplete"


def test_all_documented_states_are_reachable():
    # Every VISUAL_READINESS_STATES entry must be producible by some input.
    reachable = {
        classify_visual_readiness(
            brief_status="missing", manifest_status="missing",
            cad_files=[], mesh_files=[], render_files=[], missing_visual_artifacts=[], stale_previews=[],
        ),
        classify_visual_readiness(
            brief_status="unreadable", manifest_status="ok",
            cad_files=[], mesh_files=[], render_files=[], missing_visual_artifacts=[], stale_previews=[],
        ),
        classify_visual_readiness(
            brief_status="ok", manifest_status="ok",
            cad_files=[], mesh_files=[], render_files=[], missing_visual_artifacts=[], stale_previews=[],
        ),
        classify_visual_readiness(
            brief_status="ok", manifest_status="ok",
            cad_files=["x"], mesh_files=[], render_files=[], missing_visual_artifacts=[], stale_previews=[],
        ),
        classify_visual_readiness(
            brief_status="ok", manifest_status="ok",
            cad_files=["x"], mesh_files=["y"], render_files=[], missing_visual_artifacts=[], stale_previews=[],
        ),
        classify_visual_readiness(
            brief_status="ok", manifest_status="ok",
            cad_files=["x"], mesh_files=["y"], render_files=["z"], missing_visual_artifacts=[], stale_previews=[],
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

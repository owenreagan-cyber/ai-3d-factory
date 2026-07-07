import ast
import inspect
import os
import time

import pytest
from typer.testing import CliRunner

from factory import project_store
from factory import render_coverage as render_coverage_module
from factory.cli import app
from factory.render_coverage import (
    build_text_report,
    compute_render_coverage,
    plan_render_commands,
)

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


# ---- compute_render_coverage ----


def test_no_stl_files(project_root):
    coverage = compute_render_coverage(project_root)
    assert coverage["total_meshes"] == 0
    assert coverage["total_renders"] == 0
    assert coverage["mesh_files"] == []
    assert coverage["render_files"] == []
    assert coverage["covered"] == []
    assert coverage["missing_renders"] == []
    assert coverage["orphan_renders"] == []
    assert coverage["stale_renders"] == []
    assert coverage["all_meshes_have_renders"] is False  # vacuous: nothing to review yet
    assert coverage["visually_complete_for_slicer_review"] is False


def test_missing_stl_and_renders_dirs_entirely(tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    coverage = compute_render_coverage(bare)  # must not raise
    assert coverage["total_meshes"] == 0
    assert coverage["total_renders"] == 0


def test_one_stl_with_matching_render(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png")

    coverage = compute_render_coverage(project_root)
    assert coverage["total_meshes"] == 1
    assert coverage["covered_count"] == 1
    assert coverage["missing_renders"] == []
    assert coverage["orphan_renders"] == []
    assert coverage["stale_renders"] == []
    assert coverage["all_meshes_have_renders"] is True
    assert coverage["visually_complete_for_slicer_review"] is True
    assert coverage["covered"] == [
        {"mesh": "stl/part.stl", "render": "renders/part_preview.png", "stale": False}
    ]


def test_one_stl_missing_render(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")

    coverage = compute_render_coverage(project_root)
    assert coverage["total_meshes"] == 1
    assert coverage["covered_count"] == 0
    assert coverage["missing_renders"] == ["stl/part.stl"]
    assert coverage["all_meshes_have_renders"] is False
    assert coverage["visually_complete_for_slicer_review"] is False


def test_multiple_stl_with_partial_render_coverage(project_root):
    (project_root / "stl" / "a.stl").write_bytes(b"a")
    (project_root / "stl" / "b.stl").write_bytes(b"b")
    (project_root / "stl" / "c.stl").write_bytes(b"c")
    (project_root / "renders" / "a_preview.png").write_bytes(b"a-png")
    (project_root / "renders" / "c_preview.png").write_bytes(b"c-png")

    coverage = compute_render_coverage(project_root)
    assert coverage["total_meshes"] == 3
    assert coverage["covered_count"] == 2
    assert coverage["missing_renders"] == ["stl/b.stl"]
    assert coverage["all_meshes_have_renders"] is False
    assert coverage["visually_complete_for_slicer_review"] is False
    assert {c["mesh"] for c in coverage["covered"]} == {"stl/a.stl", "stl/c.stl"}


def test_orphan_render_files(project_root):
    (project_root / "stl" / "a.stl").write_bytes(b"a")
    (project_root / "renders" / "a_preview.png").write_bytes(b"a-png")
    (project_root / "renders" / "leftover_preview.png").write_bytes(b"leftover")

    coverage = compute_render_coverage(project_root)
    assert coverage["orphan_renders"] == ["renders/leftover_preview.png"]
    # An orphan alone doesn't block completeness - the one real mesh is fully covered.
    assert coverage["all_meshes_have_renders"] is True
    assert coverage["visually_complete_for_slicer_review"] is True


def test_stale_render_detected_and_blocks_completeness(project_root):
    stl_path = project_root / "stl" / "part.stl"
    render_path = project_root / "renders" / "part_preview.png"
    stl_path.write_bytes(b"fake stl")
    render_path.write_bytes(b"fake png")
    future = time.time() + 10
    os.utime(stl_path, (future, future))

    coverage = compute_render_coverage(project_root)
    assert coverage["stale_renders"] == ["renders/part_preview.png"]
    assert coverage["missing_renders"] == []
    assert coverage["all_meshes_have_renders"] is True  # present, just stale
    assert coverage["visually_complete_for_slicer_review"] is False
    # A stale render is still "covered" (it exists), just flagged stale.
    assert coverage["covered"][0]["stale"] is True


def test_render_coverage_is_deterministic_given_unchanged_files(project_root):
    (project_root / "stl" / "a.stl").write_bytes(b"a")
    (project_root / "stl" / "b.stl").write_bytes(b"b")
    (project_root / "renders" / "a_preview.png").write_bytes(b"a-png")

    first = compute_render_coverage(project_root)
    second = compute_render_coverage(project_root)
    assert first == second


def test_render_coverage_never_writes_anything(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    before = {p for p in project_root.rglob("*") if p.is_file()}
    compute_render_coverage(project_root)
    after = {p for p in project_root.rglob("*") if p.is_file()}
    assert before == after


# ---- build_text_report ----


def test_build_text_report_no_meshes(project_root):
    coverage = compute_render_coverage(project_root)
    lines = build_text_report(coverage)
    text = "\n".join(lines)
    assert "STL files: 0" in text
    assert "Human slicer review required." in text
    assert "Project is NOT print-ready." in text


def test_build_text_report_lists_missing_and_stale_and_orphan(project_root):
    (project_root / "stl" / "a.stl").write_bytes(b"a")
    (project_root / "stl" / "b.stl").write_bytes(b"b")
    (project_root / "renders" / "leftover_preview.png").write_bytes(b"x")
    coverage = compute_render_coverage(project_root)
    text = "\n".join(build_text_report(coverage))
    assert "stl/a.stl" in text
    assert "stl/b.stl" in text
    assert "renders/leftover_preview.png" in text
    assert "advisory only" in text


# ---- plan_render_commands ----


def test_plan_render_commands_empty_when_nothing_missing(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png")
    coverage = compute_render_coverage(project_root)
    assert plan_render_commands(coverage) == []


def test_plan_render_commands_for_missing_renders(project_root):
    (project_root / "stl" / "a.stl").write_bytes(b"a")
    (project_root / "stl" / "b.stl").write_bytes(b"b")
    coverage = compute_render_coverage(project_root)
    commands = plan_render_commands(coverage)
    assert commands == ["factory render stl/a.stl", "factory render stl/b.stl"]


def test_plan_render_commands_for_stale_renders(project_root):
    stl_path = project_root / "stl" / "part.stl"
    render_path = project_root / "renders" / "part_preview.png"
    stl_path.write_bytes(b"fake stl")
    render_path.write_bytes(b"fake png")
    future = time.time() + 10
    os.utime(stl_path, (future, future))

    coverage = compute_render_coverage(project_root)
    commands = plan_render_commands(coverage)
    assert commands == ["factory render stl/part.stl"]


def test_plan_render_commands_never_duplicates(project_root):
    # A mesh that's both missing (no render at all) can't also be stale, but
    # verify de-duplication logic doesn't produce repeats across the two lists.
    (project_root / "stl" / "a.stl").write_bytes(b"a")
    coverage = compute_render_coverage(project_root)
    commands = plan_render_commands(coverage)
    assert len(commands) == len(set(commands))


def test_plan_render_commands_never_executes_anything():
    source = inspect.getsource(render_coverage_module.plan_render_commands)
    for forbidden in ("subprocess", "os.system", "Popen", "eval(", "exec("):
        assert forbidden not in source


# ---- CLI: render-coverage ----


def test_cli_render_coverage_missing_dir():
    result = runner.invoke(app, ["render-coverage", "/nonexistent/path/xyz"])
    assert result.exit_code != 0


def test_cli_render_coverage_human_readable(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    result = runner.invoke(app, ["render-coverage", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "STL files: 1" in result.stdout
    assert "missing renders" in result.stdout
    assert "did not render" in " ".join(result.stdout.split())


def test_cli_render_coverage_json_output(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png")
    result = runner.invoke(app, ["render-coverage", str(project_root), "--json"])
    assert result.exit_code == 0, result.stdout

    import json

    payload = json.loads(result.stdout)
    assert payload["total_meshes"] == 1
    assert payload["all_meshes_have_renders"] is True
    assert payload["visually_complete_for_slicer_review"] is True


def test_cli_render_coverage_json_is_valid_and_parseable_with_no_meshes(project_root):
    result = runner.invoke(app, ["render-coverage", str(project_root), "--json"])
    assert result.exit_code == 0

    import json

    payload = json.loads(result.stdout)
    assert payload["total_meshes"] == 0


# ---- CLI: plan-renders ----


def test_cli_plan_renders_missing_dir():
    result = runner.invoke(app, ["plan-renders", "/nonexistent/path/xyz"])
    assert result.exit_code != 0


def test_cli_plan_renders_nothing_to_do(project_root):
    result = runner.invoke(app, ["plan-renders", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "nothing to plan" in " ".join(result.stdout.split()).lower()


def test_cli_plan_renders_lists_suggested_commands(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    result = runner.invoke(app, ["plan-renders", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "factory render stl/part.stl" in result.stdout
    assert "none of these are run automatically" in " ".join(result.stdout.split())


def test_cli_plan_renders_never_actually_renders(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    runner.invoke(app, ["plan-renders", str(project_root)])
    # No render file should have been produced by merely planning.
    assert not (project_root / "renders" / "part_preview.png").exists()


# ---- safety: no network/subprocess/printer/slicer behavior; no human_approved/print_ready ----


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


def test_render_coverage_module_has_no_network_or_process_calls():
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
    tree = _strip_docstrings(ast.parse(inspect.getsource(render_coverage_module)))
    code_only_source = ast.unparse(tree)
    for forbidden_term in forbidden:
        assert forbidden_term not in code_only_source, (
            f"factory.render_coverage must stay local-only; found {forbidden_term!r}"
        )


def test_render_coverage_module_never_writes_files():
    tree = ast.parse(inspect.getsource(render_coverage_module))
    source = ast.unparse(tree)
    for write_call in ("write_text(", "write_bytes(", "save_json(", ".mkdir("):
        assert write_call not in source, f"factory.render_coverage must not write files; found {write_call!r}"


def test_render_coverage_module_never_references_approval_statuses():
    tree = _strip_docstrings(ast.parse(inspect.getsource(render_coverage_module)))
    code_only_source = ast.unparse(tree)
    assert "human_approved" not in code_only_source
    assert "print_ready" not in code_only_source

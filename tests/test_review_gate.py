import ast
import inspect
import os
import time

import pytest
from typer.testing import CliRunner

from factory import project_store
from factory import review_gate as review_gate_module
from factory.cli import app
from factory.review_gate import GATE_NAME, STATUS_CEILING, evaluate_review_gate

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


def _kinds(items):
    return {i["kind"] for i in items}


# ---- basic shape ----


def test_gate_name_and_ceiling_constants():
    assert GATE_NAME == "human_slicer_review"
    assert STATUS_CEILING == "slicer_review_ready"


def test_gate_result_shape(project_root):
    gate = evaluate_review_gate(project_root)
    assert set(gate.keys()) == {
        "project_dir", "gate", "result", "status_ceiling", "summary",
        "blocking_items", "warning_items", "ready_items", "suggested_actions", "notes",
    }
    assert gate["gate"] == GATE_NAME
    assert gate["status_ceiling"] == STATUS_CEILING
    assert gate["result"] in ("pass", "warn", "fail")


# ---- fail scenarios ----


def test_missing_brief_fails(tmp_path):
    bare = tmp_path / "bare-dir"
    bare.mkdir()
    gate = evaluate_review_gate(bare)
    assert gate["result"] == "fail"
    assert "brief_missing" in _kinds(gate["blocking_items"])


def test_unreadable_brief_fails(project_root):
    (project_root / "brief.json").write_text("{not valid json", encoding="utf-8")
    gate = evaluate_review_gate(project_root)
    assert gate["result"] == "fail"
    assert "brief_unreadable" in _kinds(gate["blocking_items"])


def test_no_stl_files_fails(project_root):
    gate = evaluate_review_gate(project_root)
    assert gate["result"] == "fail"
    assert "no_stl_files" in _kinds(gate["blocking_items"])


def test_stl_with_missing_render_fails(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    gate = evaluate_review_gate(project_root)
    assert gate["result"] == "fail"
    assert "render_missing" in _kinds(gate["blocking_items"])
    assert "no_stl_files" not in _kinds(gate["blocking_items"])


def test_stale_render_fails(project_root):
    stl_path = project_root / "stl" / "part.stl"
    render_path = project_root / "renders" / "part_preview.png"
    stl_path.write_bytes(b"fake stl")
    render_path.write_bytes(b"fake png")
    future = time.time() + 10
    os.utime(stl_path, (future, future))

    gate = evaluate_review_gate(project_root)
    assert gate["result"] == "fail"
    assert "render_stale" in _kinds(gate["blocking_items"])


def test_unreadable_manifest_fails(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png")
    (project_root / "part_manifest.json").write_text("{not valid json", encoding="utf-8")
    gate = evaluate_review_gate(project_root)
    assert gate["result"] == "fail"
    assert "manifest_unreadable" in _kinds(gate["blocking_items"])


def test_unreadable_preview_package_fails(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png")
    package_dir = project_root / "preview_package"
    package_dir.mkdir()
    (package_dir / "index.json").write_text("{not valid json", encoding="utf-8")

    gate = evaluate_review_gate(project_root)
    assert gate["result"] == "fail"
    assert "preview_package_unreadable" in _kinds(gate["blocking_items"])


# ---- warn scenarios ----


def test_complete_stl_render_missing_validation_warns(project_root):
    build_plan = project_store.load_json(project_root / "build_plan.json")
    build_plan["selected_manufacturing_option"] = "single_piece"
    project_store.save_json(project_root / "build_plan.json", build_plan)

    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png")

    gate = evaluate_review_gate(project_root)
    assert gate["result"] == "warn"
    assert gate["blocking_items"] == []
    assert "validation_missing" in _kinds(gate["warning_items"])


def test_manifest_missing_warns_not_fails(project_root):
    build_plan = project_store.load_json(project_root / "build_plan.json")
    build_plan["selected_manufacturing_option"] = "single_piece"
    project_store.save_json(project_root / "build_plan.json", build_plan)

    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png")
    (project_root / "validation" / "part_validation.json").write_text('{"overall_status": "PASS"}', encoding="utf-8")
    (project_root / "part_manifest.json").unlink()

    gate = evaluate_review_gate(project_root)
    assert gate["result"] == "warn"
    assert gate["blocking_items"] == []
    assert "manifest_missing" in _kinds(gate["warning_items"])


def test_manufacturing_option_not_selected_warns(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png")
    (project_root / "validation" / "part_validation.json").write_text('{"overall_status": "PASS"}', encoding="utf-8")

    gate = evaluate_review_gate(project_root)
    assert gate["result"] == "warn"
    assert "manufacturing_option_not_selected" in _kinds(gate["warning_items"])


def test_orphan_render_is_warning_not_blocking(project_root):
    build_plan = project_store.load_json(project_root / "build_plan.json")
    build_plan["selected_manufacturing_option"] = "single_piece"
    project_store.save_json(project_root / "build_plan.json", build_plan)

    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png")
    (project_root / "validation" / "part_validation.json").write_text('{"overall_status": "PASS"}', encoding="utf-8")
    (project_root / "renders" / "leftover_preview.png").write_bytes(b"leftover")

    gate = evaluate_review_gate(project_root)
    assert gate["result"] == "warn"
    assert gate["blocking_items"] == []
    assert "render_orphan" in _kinds(gate["warning_items"])


def test_preview_package_missing_is_warning(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png")
    gate = evaluate_review_gate(project_root)
    assert "preview_package_unreadable" not in _kinds(gate["blocking_items"])
    assert "preview_package_missing" in _kinds(gate["warning_items"])


# ---- pass scenario ----


def test_fully_complete_project_passes(project_root):
    build_plan = project_store.load_json(project_root / "build_plan.json")
    build_plan["selected_manufacturing_option"] = "single_piece"
    project_store.save_json(project_root / "build_plan.json", build_plan)

    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png")
    (project_root / "validation" / "part_validation.json").write_text('{"overall_status": "PASS"}', encoding="utf-8")

    # Persist the preview package so preview_package_missing doesn't fire.
    from factory.preview_package import write_preview_package

    write_preview_package(project_root)

    gate = evaluate_review_gate(project_root)
    assert gate["result"] == "pass"
    assert gate["blocking_items"] == []
    assert gate["warning_items"] == []
    assert "slicer_review_ready" in _kinds(gate["ready_items"])
    assert "validation_present" in _kinds(gate["ready_items"])
    assert "stl_files_present" in _kinds(gate["ready_items"])
    assert "all_renders_fresh" in _kinds(gate["ready_items"])


def test_pass_result_never_mentions_approval_or_print_ready(project_root):
    build_plan = project_store.load_json(project_root / "build_plan.json")
    build_plan["selected_manufacturing_option"] = "single_piece"
    project_store.save_json(project_root / "build_plan.json", build_plan)
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png")
    (project_root / "validation" / "part_validation.json").write_text('{"overall_status": "PASS"}', encoding="utf-8")

    from factory.preview_package import write_preview_package

    write_preview_package(project_root)

    gate = evaluate_review_gate(project_root)
    assert gate["result"] == "pass"
    text = gate["summary"].lower()
    assert "approved" not in text
    assert "human_approved" not in text
    assert "print_ready" not in text
    assert "not an approval" in text or "not print-ready" in text or "not a print-readiness" in text


# ---- determinism ----


def test_gate_result_is_deterministic(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    first = evaluate_review_gate(project_root)
    second = evaluate_review_gate(project_root)
    assert first == second


def test_gate_never_writes_any_file(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    before = {p for p in project_root.rglob("*") if p.is_file()}
    evaluate_review_gate(project_root)
    after = {p for p in project_root.rglob("*") if p.is_file()}
    assert before == after


# ---- suggested_actions ----


def test_suggested_actions_included_and_safe(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    gate = evaluate_review_gate(project_root)
    assert gate["suggested_actions"]
    for action in gate["suggested_actions"]:
        assert action["safety"] == "manual_only"
        haystack = " ".join([action["label"], action["command"], action["reason"]]).lower()
        for forbidden in ("send to printer", "start print", "begin printing", "print now", "upload", "meshy", "blender", "bambu cloud", "api key", "api call"):
            assert forbidden not in haystack


# ---- CLI ----


def test_cli_review_gate_missing_dir():
    result = runner.invoke(app, ["review-gate", "/nonexistent/path/xyz"])
    assert result.exit_code != 0


def test_cli_review_gate_human_readable_fail_exits_nonzero(project_root):
    result = runner.invoke(app, ["review-gate", str(project_root)])
    assert result.exit_code == 1
    assert "FAIL" in result.stdout
    assert "human slicer review" in result.stdout.lower() or "Human slicer review" in result.stdout


def test_cli_review_gate_human_readable_pass_exits_zero(project_root):
    build_plan = project_store.load_json(project_root / "build_plan.json")
    build_plan["selected_manufacturing_option"] = "single_piece"
    project_store.save_json(project_root / "build_plan.json", build_plan)
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png")
    (project_root / "validation" / "part_validation.json").write_text('{"overall_status": "PASS"}', encoding="utf-8")

    from factory.preview_package import write_preview_package

    write_preview_package(project_root)

    result = runner.invoke(app, ["review-gate", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "PASS" in result.stdout


def test_cli_review_gate_json_output(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    result = runner.invoke(app, ["review-gate", str(project_root), "--json"])
    assert result.exit_code == 1

    import json

    payload = json.loads(result.stdout)
    assert payload["result"] == "fail"
    assert payload["gate"] == "human_slicer_review"


def test_cli_review_gate_never_modifies_project_files(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    before = {p: p.read_bytes() for p in project_root.rglob("*") if p.is_file()}
    runner.invoke(app, ["review-gate", str(project_root)])
    runner.invoke(app, ["review-gate", str(project_root), "--json"])
    after = {p: p.read_bytes() for p in project_root.rglob("*") if p.is_file()}
    assert before == after


# ---- safety ----


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


def test_review_gate_module_has_no_network_or_process_calls():
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
    tree = _strip_docstrings(ast.parse(inspect.getsource(review_gate_module)))
    code_only_source = ast.unparse(tree)
    for forbidden_term in forbidden:
        assert forbidden_term not in code_only_source, f"factory.review_gate must stay local-only; found {forbidden_term!r}"


def test_review_gate_module_never_writes_files():
    source = inspect.getsource(review_gate_module)
    for write_call in ("write_text(", "write_bytes(", "save_json(", ".mkdir("):
        assert write_call not in source, f"factory.review_gate must not write files; found {write_call!r}"


def test_review_gate_module_never_references_approval_statuses():
    tree = _strip_docstrings(ast.parse(inspect.getsource(review_gate_module)))
    code_only_source = ast.unparse(tree)
    assert "human_approved" not in code_only_source
    assert "print_ready" not in code_only_source

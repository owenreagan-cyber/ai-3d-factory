"""Phase 43 tests: the Preview Board's board-wide "Tool Environment"
section - a compact rendering of `factory.engine_registry.summarize_tool_environment()`.
One section for the whole board, never one card per tool, never one per
project. See docs/engine-registry.md, docs/preview-board.md.
"""

from __future__ import annotations

from factory import engine_registry, project_store
from factory.preview_board import _build_tool_environment_html, build_board_html, gather_board_data


def test_tool_environment_section_renders_compact_summary():
    summary = {
        "core_local_tools_available": "1/2",
        "slicers_detected": 1,
        "near_term_engines_unqualified": 2,
        "cloud_engines_gated": 2,
    }
    html = _build_tool_environment_html(summary)
    assert "1/2" in html
    assert "Core local tools available" in html
    assert "Slicers detected" in html


def test_tool_environment_section_handles_missing_data():
    html = _build_tool_environment_html(None)
    assert "No tool environment data" in html
    assert "<script" not in html


def test_tool_environment_section_escapes_html(monkeypatch):
    monkeypatch.setattr(
        engine_registry,
        "summarize_tool_environment",
        lambda **kwargs: {
            "core_local_tools_available": "<script>alert(1)</script>",
            "slicers_detected": 0,
            "near_term_engines_unqualified": 0,
            "cloud_engines_gated": 0,
        },
    )
    html = _build_tool_environment_html(engine_registry.summarize_tool_environment())
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_gather_board_data_includes_tool_environment_summary(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    project_store.init_project("Demo")
    board = gather_board_data(projects_dir)
    assert "tool_environment_summary" in board
    summary = board["tool_environment_summary"]
    assert set(summary.keys()) == {
        "core_local_tools_available", "slicers_detected", "near_term_engines_unqualified", "cloud_engines_gated",
    }


def test_build_board_html_contains_tool_environment_section(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    project_store.init_project("Demo")
    board = gather_board_data(projects_dir)
    html = build_board_html(board)
    assert "Tool Environment" in html
    # Exactly one board-wide section, not one per project/tool.
    assert html.count('<div class="tool-environment">') == 1


def test_board_generation_never_launches_gui_or_calls_network(tmp_path, monkeypatch):
    """A guard against a regression that would make board generation spawn a
    subprocess for tool detection - board generation must stay a pure
    filesystem/PATH/package-metadata read."""

    def _boom(*args, **kwargs):
        raise AssertionError("preview-board generation must never call subprocess")

    import subprocess

    monkeypatch.setattr(subprocess, "run", _boom)
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    project_store.init_project("Demo")
    board = gather_board_data(projects_dir)
    assert board["tool_environment_summary"] is not None


def test_board_generation_writes_no_project_files(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    root = project_store.init_project("Demo")
    before = sorted(p.name for p in root.rglob("*") if p.is_file())
    gather_board_data(projects_dir)
    after = sorted(p.name for p in root.rglob("*") if p.is_file())
    assert before == after


def test_tool_environment_does_not_add_a_card_per_tool(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    project_store.init_project("Demo")
    board = gather_board_data(projects_dir)
    html = build_board_html(board)
    # Existing detail cards remain - the project card count is unaffected
    # by the new board-wide section.
    assert html.count('<div class="project-card">') == 1

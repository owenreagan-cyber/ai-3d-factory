"""Phase 40 tests: the `factory timeline` CLI - a thin, entirely
read-only wrapper around `factory.project_timeline`. No AI, no LLM, no
network, no slicer, no G-code generation, no printer communication. See
docs/project-timeline.md, docs/roadmap.md Phase 40.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory import export_pipeline, project_store
from factory.cli import app
from factory.openscad.generate import generate_openscad

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


def _export_all(project_dir, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = export_pipeline.plan_export(project_dir, confirm_export=True)
    export_pipeline.run_export_pipeline(project_dir, plan, all_steps=True)


# ---- human-readable output ----


def test_timeline_human_readable(scad_project):
    result = runner.invoke(app, ["timeline", str(scad_project)])
    assert result.exit_code == 0, result.stdout
    assert "Project Timeline" in result.stdout
    assert "This is a read-only view of existing receipts" in result.stdout


def test_timeline_shows_date_unavailable_section_for_undated_events(isolated_projects_dir):
    root = project_store.init_project("Bare Project")
    brief_path = root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["status"] = "cad_generated"
    brief.pop("status_history", None)
    project_store.save_json(brief_path, brief)

    result = runner.invoke(app, ["timeline", str(root)])
    assert result.exit_code == 0, result.stdout
    assert "Date unavailable" in result.stdout
    assert "?" in result.stdout


def test_timeline_shows_day_heading_for_dated_events(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    result = runner.invoke(app, ["timeline", str(scad_project)])
    assert result.exit_code == 0, result.stdout
    assert "✓" in result.stdout
    assert "STL exported" in result.stdout


def test_timeline_no_events_message(isolated_projects_dir):
    root = project_store.init_project("Bare Project")
    result = runner.invoke(app, ["timeline", str(root)])
    # Brand-new project reaches only "brief_created" - one event exists,
    # so the "no events" message should not appear here.
    assert result.exit_code == 0, result.stdout
    assert "Brief created" in result.stdout


def test_timeline_has_no_history_flag():
    # Per the approved adjustment: --history is redundant on this command
    # (the whole command is historical) and must not exist.
    result = runner.invoke(app, ["timeline", "--help"])
    assert result.exit_code == 0, result.stdout
    assert "--history" not in result.stdout


# ---- JSON contract: never mixed with plain text ----


def test_timeline_json_is_the_only_output(scad_project):
    result = runner.invoke(app, ["timeline", str(scad_project), "--json"])
    json.loads(result.stdout)


def test_timeline_json_missing_project_is_clean_json():
    result = runner.invoke(app, ["timeline", "/no/such/project", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["errors"]
    assert payload["no_automatic_print"] is True


def test_timeline_json_shape(scad_project):
    result = runner.invoke(app, ["timeline", str(scad_project), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert "events" in payload
    assert isinstance(payload["events"], list)
    assert payload["errors"] == []
    assert payload["no_automatic_print"] is True


def test_timeline_help_never_touches_a_project():
    result = runner.invoke(app, ["timeline", "--help"])
    assert result.exit_code == 0, result.stdout
    assert "timeline" in result.stdout.lower()


def test_timeline_never_modifies_committed_examples():
    example_dir = project_store.REPO_ROOT / "examples" / "storage-bin-lid"
    before = sorted(str(p) for p in example_dir.rglob("*"))
    runner.invoke(app, ["timeline", str(example_dir)])
    runner.invoke(app, ["timeline", str(example_dir), "--json"])
    after = sorted(str(p) for p in example_dir.rglob("*"))
    assert before == after


def test_timeline_never_invokes_a_subprocess(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("read-only timeline must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    result = runner.invoke(app, ["timeline", str(scad_project)])
    assert result.exit_code == 0, result.stdout


def test_timeline_never_makes_a_network_call(scad_project, monkeypatch):
    import socket

    def _boom(*a, **k):
        raise AssertionError("timeline must never open a network socket")

    monkeypatch.setattr(socket, "socket", _boom)
    result = runner.invoke(app, ["timeline", str(scad_project)])
    assert result.exit_code == 0, result.stdout


def test_timeline_never_writes_anything(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    before = sorted(str(p) for p in scad_project.rglob("*"))
    runner.invoke(app, ["timeline", str(scad_project)])
    runner.invoke(app, ["timeline", str(scad_project), "--json"])
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after

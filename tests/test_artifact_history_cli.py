"""Phase 41 tests: the `factory artifact-history` / `factory artifact-diff`
/ `factory artifact-rollback-plan` CLI commands - thin, entirely read-only
wrappers around `factory.artifact_history`. No AI, no LLM, no network, no
slicer, no G-code generation, no printer communication, no file restored,
copied, or deleted. See docs/artifact-history.md, docs/roadmap.md Phase 41.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory import export_pipeline, project_store
from factory.cli import app
from factory.openscad.generate import generate_openscad
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
    _export_all(project_dir, monkeypatch)

    build_plan_path = project_dir / "build_plan.json"
    build_plan = project_store.load_json(build_plan_path)
    build_plan["selected_manufacturing_option"] = "single_piece"
    build_plan["target_printer"] = {
        "printer_id": "bambu_h2d",
        "display_name": "Bambu Lab H2D",
        "resolved": True,
        "resolved_from": "test",
        "capabilities": None,
    }
    project_store.save_json(build_plan_path, build_plan)

    manifest_path = project_dir / "part_manifest.json"
    manifest = project_store.load_json(manifest_path)
    for part in manifest.get("parts", []):
        part["material"] = "PLA"
        part["color"] = "white"
    project_store.save_json(manifest_path, manifest)

    record_approval(project_dir)
    return project_dir


# ---------------------------------------------------------------------------
# factory artifact-history - human-readable output
# ---------------------------------------------------------------------------


def test_artifact_history_human_readable(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    result = runner.invoke(app, ["artifact-history", str(scad_project)])
    assert result.exit_code == 0, result.stdout
    assert "Artifact History" in result.stdout
    assert "Version 1" in result.stdout
    assert "This is a read-only view" in result.stdout
    assert "never writes, restores, copies, or deletes a file" in result.stdout


def test_artifact_history_no_versions_message(isolated_projects_dir):
    root = project_store.init_project("Bare Project")
    result = runner.invoke(app, ["artifact-history", str(root)])
    assert result.exit_code == 0, result.stdout
    assert "No artifact versions recorded yet" in result.stdout


def test_artifact_history_missing_project_dir():
    result = runner.invoke(app, ["artifact-history", "/no/such/project"])
    assert result.exit_code == 1
    assert "error" in result.stdout.lower()


# ---------------------------------------------------------------------------
# factory artifact-history - JSON contract
# ---------------------------------------------------------------------------


def test_artifact_history_json_is_the_only_output(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    result = runner.invoke(app, ["artifact-history", str(scad_project), "--json"])
    json.loads(result.stdout)


def test_artifact_history_json_missing_project_is_clean_json():
    result = runner.invoke(app, ["artifact-history", "/no/such/project", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["errors"]
    assert payload["no_automatic_print"] is True


def test_artifact_history_json_shape(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    result = runner.invoke(app, ["artifact-history", str(scad_project), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert "versions" in payload
    assert isinstance(payload["versions"], list)
    assert payload["versions"][0]["version_id"] == 1
    assert payload["errors"] == []
    assert payload["no_automatic_print"] is True


# ---------------------------------------------------------------------------
# factory artifact-diff
# ---------------------------------------------------------------------------


def test_artifact_diff_human_readable(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    result = runner.invoke(app, ["artifact-diff", str(scad_project), "--from", "1", "--to", "1"])
    assert result.exit_code == 0, result.stdout
    assert "Artifact Difference" in result.stdout
    assert "Changed:" in result.stdout
    assert "Unchanged:" in result.stdout
    assert "Impact:" in result.stdout
    assert "never invokes a slicer or contacts a printer/network" in result.stdout


def test_artifact_diff_unknown_version_exits_nonzero(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    result = runner.invoke(app, ["artifact-diff", str(scad_project), "--from", "1", "--to", "9999"])
    assert result.exit_code == 1
    assert "error" in result.stdout.lower()


def test_artifact_diff_unknown_version_json_is_clean(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    result = runner.invoke(app, ["artifact-diff", str(scad_project), "--from", "1", "--to", "9999", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["errors"]
    assert payload["no_automatic_print"] is True


def test_artifact_diff_missing_project_dir():
    result = runner.invoke(app, ["artifact-diff", "/no/such/project", "--from", "1", "--to", "1"])
    assert result.exit_code == 1


def test_artifact_diff_json_shape(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    result = runner.invoke(app, ["artifact-diff", str(scad_project), "--from", "1", "--to", "1", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["from_version"] == 1
    assert payload["to_version"] == 1
    assert payload["dry_run"] is True
    assert payload["no_automatic_print"] is True
    assert payload["errors"] == []


def test_artifact_diff_requires_from_and_to(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    result = runner.invoke(app, ["artifact-diff", str(scad_project)])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# factory artifact-rollback-plan
# ---------------------------------------------------------------------------


def test_artifact_rollback_plan_human_readable(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    result = runner.invoke(app, ["artifact-rollback-plan", str(scad_project), "--to", "1"])
    assert result.exit_code == 0, result.stdout
    assert "Rollback Plan" in result.stdout
    assert "Would affect:" in result.stdout
    assert "Would not affect:" in result.stdout
    assert "Manual review required. No files changed." in result.stdout
    assert "No files were restored. No files were copied. No files were deleted." in result.stdout
    assert "No manifest was modified. No slicer was opened. No print was started." in result.stdout


def test_artifact_rollback_plan_unknown_version_exits_nonzero(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    result = runner.invoke(app, ["artifact-rollback-plan", str(scad_project), "--to", "9999"])
    assert result.exit_code == 1
    assert "error" in result.stdout.lower()


def test_artifact_rollback_plan_missing_project_no_versions(isolated_projects_dir):
    root = project_store.init_project("Bare Project")
    result = runner.invoke(app, ["artifact-rollback-plan", str(root), "--to", "1"])
    assert result.exit_code == 1


def test_artifact_rollback_plan_json_shape(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    result = runner.invoke(app, ["artifact-rollback-plan", str(scad_project), "--to", "1", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["current_version"] == 4
    assert payload["target_version"] == 1
    assert payload["no_files_restored"] is True
    assert payload["no_files_copied"] is True
    assert payload["no_files_deleted"] is True
    assert payload["no_manifest_modified"] is True
    assert payload["no_automatic_print"] is True
    assert payload["errors"] == []


def test_artifact_rollback_plan_missing_project_dir():
    result = runner.invoke(app, ["artifact-rollback-plan", "/no/such/project", "--to", "1"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Help text - never touches a project
# ---------------------------------------------------------------------------


def test_artifact_history_help_never_touches_a_project():
    result = runner.invoke(app, ["artifact-history", "--help"])
    assert result.exit_code == 0, result.stdout
    assert "artifact" in result.stdout.lower()


def test_artifact_diff_help_never_touches_a_project():
    result = runner.invoke(app, ["artifact-diff", "--help"])
    assert result.exit_code == 0, result.stdout
    assert "--from" in result.stdout
    assert "--to" in result.stdout


def test_artifact_rollback_plan_help_never_touches_a_project():
    result = runner.invoke(app, ["artifact-rollback-plan", "--help"])
    assert result.exit_code == 0, result.stdout
    assert "--to" in result.stdout


def test_artifact_commands_listed_in_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.stdout
    assert "artifact-history" in result.stdout
    assert "artifact-diff" in result.stdout
    assert "artifact-rollback-plan" in result.stdout


# ---------------------------------------------------------------------------
# Safety: no writes, no subprocess, no network
# ---------------------------------------------------------------------------


def test_artifact_history_never_modifies_committed_examples():
    example_dir = project_store.REPO_ROOT / "examples" / "storage-bin-lid"
    before = sorted(str(p) for p in example_dir.rglob("*"))
    runner.invoke(app, ["artifact-history", str(example_dir)])
    runner.invoke(app, ["artifact-history", str(example_dir), "--json"])
    after = sorted(str(p) for p in example_dir.rglob("*"))
    assert before == after


def test_artifact_diff_never_modifies_committed_examples():
    example_dir = project_store.REPO_ROOT / "examples" / "storage-bin-lid"
    before = sorted(str(p) for p in example_dir.rglob("*"))
    runner.invoke(app, ["artifact-diff", str(example_dir), "--from", "1", "--to", "1"])
    after = sorted(str(p) for p in example_dir.rglob("*"))
    assert before == after


def test_artifact_rollback_plan_never_modifies_committed_examples():
    example_dir = project_store.REPO_ROOT / "examples" / "storage-bin-lid"
    before = sorted(str(p) for p in example_dir.rglob("*"))
    runner.invoke(app, ["artifact-rollback-plan", str(example_dir), "--to", "1"])
    after = sorted(str(p) for p in example_dir.rglob("*"))
    assert before == after


def test_artifact_history_never_writes_anything(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    before = sorted(str(p) for p in scad_project.rglob("*"))
    runner.invoke(app, ["artifact-history", str(scad_project)])
    runner.invoke(app, ["artifact-history", str(scad_project), "--json"])
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


def test_artifact_diff_never_writes_anything(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    before = sorted(str(p) for p in scad_project.rglob("*"))
    runner.invoke(app, ["artifact-diff", str(scad_project), "--from", "1", "--to", "1"])
    runner.invoke(app, ["artifact-diff", str(scad_project), "--from", "1", "--to", "1", "--json"])
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


def test_artifact_rollback_plan_never_writes_anything(scad_project, monkeypatch):
    _fully_approved(scad_project, monkeypatch)
    before = sorted(str(p) for p in scad_project.rglob("*"))
    runner.invoke(app, ["artifact-rollback-plan", str(scad_project), "--to", "1"])
    runner.invoke(app, ["artifact-rollback-plan", str(scad_project), "--to", "1", "--json"])
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


def test_artifact_history_never_invokes_a_subprocess(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("read-only artifact-history must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    result = runner.invoke(app, ["artifact-history", str(scad_project)])
    assert result.exit_code == 0, result.stdout


def test_artifact_diff_never_invokes_a_subprocess(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("read-only artifact-diff must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    result = runner.invoke(app, ["artifact-diff", str(scad_project), "--from", "1", "--to", "1"])
    assert result.exit_code == 0, result.stdout


def test_artifact_rollback_plan_never_invokes_a_subprocess(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("read-only artifact-rollback-plan must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    result = runner.invoke(app, ["artifact-rollback-plan", str(scad_project), "--to", "1"])
    assert result.exit_code == 0, result.stdout


def test_artifact_history_never_makes_a_network_call(scad_project, monkeypatch):
    import socket

    def _boom(*a, **k):
        raise AssertionError("artifact-history must never open a network socket")

    monkeypatch.setattr(socket, "socket", _boom)
    result = runner.invoke(app, ["artifact-history", str(scad_project)])
    assert result.exit_code == 0, result.stdout


def test_artifact_diff_never_makes_a_network_call(scad_project, monkeypatch):
    import socket

    def _boom(*a, **k):
        raise AssertionError("artifact-diff must never open a network socket")

    monkeypatch.setattr(socket, "socket", _boom)
    result = runner.invoke(app, ["artifact-diff", str(scad_project), "--from", "1", "--to", "1"])
    assert result.exit_code == 0, result.stdout


def test_artifact_rollback_plan_never_makes_a_network_call(scad_project, monkeypatch):
    import socket

    def _boom(*a, **k):
        raise AssertionError("artifact-rollback-plan must never open a network socket")

    monkeypatch.setattr(socket, "socket", _boom)
    result = runner.invoke(app, ["artifact-rollback-plan", str(scad_project), "--to", "1"])
    assert result.exit_code == 0, result.stdout

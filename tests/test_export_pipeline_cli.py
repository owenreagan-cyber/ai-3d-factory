"""Phase 35 tests: the `factory export-from-cad` CLI - a thin wrapper around
`factory.export_pipeline`. Dry run by default; no subprocess is ever
invoked without an explicit `--confirm-export`, and even then only if the
plan allows it. No AI, no LLM, no network, no Blender, no Meshy, no
slicer, no printer. See docs/export-pipeline.md, docs/roadmap.md Phase 35.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory import export_pipeline, project_store
from factory.cad import cadquery_backend
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


def _fake_subprocess_writes_stl(monkeypatch, *, returncode=0, content=b"solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid x\n"):
    def _fake_run(command, capture_output, text, timeout):
        if "--version" in command:
            return _FakeCompleted(returncode=0, stdout="fake version")
        output_path = Path(command[2])
        if returncode == 0:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(content)
        return _FakeCompleted(returncode=returncode)

    monkeypatch.setattr(export_pipeline.subprocess, "run", _fake_run)


# ---- help ----


def test_export_from_cad_help():
    result = runner.invoke(app, ["export-from-cad", "--help"])
    assert result.exit_code == 0
    for flag in ("--confirm-export", "--json", "--source", "--output-dir", "--overwrite-stl", "--validate", "--render", "--all", "--resume"):
        assert flag in result.stdout


def test_top_level_help_lists_export_from_cad_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "export-from-cad" in result.stdout


def test_status_command_lists_export_from_cad():
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "export-from-cad" in result.stdout


def test_export_from_cad_requires_a_path_argument():
    result = runner.invoke(app, ["export-from-cad"])
    assert result.exit_code != 0


# ---- dry run (default) ----


def test_export_from_cad_dry_run_human_readable(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    result = runner.invoke(app, ["export-from-cad", str(scad_project)])
    assert result.exit_code == 0, result.stdout
    assert "Guided Export Plan" in result.stdout
    assert "Project:" in result.stdout
    assert "Source engine:" in result.stdout
    assert "CAD source:" in result.stdout
    assert "Exporter:" in result.stdout
    assert "Exporter available:" in result.stdout
    assert "Expected output:" in result.stdout
    assert "Decision:" in result.stdout
    assert "No files written." in result.stdout
    assert "Re-run with --confirm-export" in result.stdout
    assert "OpenSCAD" in result.stdout


def test_export_from_cad_dry_run_json(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    result = runner.invoke(app, ["export-from-cad", str(scad_project), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["decision"] == "needs_confirmation"
    assert payload["no_automatic_print"] is True
    assert payload["execution"] is None


def test_export_from_cad_dry_run_writes_nothing(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    before = sorted(str(p) for p in scad_project.rglob("*"))
    runner.invoke(app, ["export-from-cad", str(scad_project)])
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


def test_export_from_cad_dry_run_invokes_no_subprocess(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("dry run must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    result = runner.invoke(app, ["export-from-cad", str(scad_project)])
    assert result.exit_code == 0, result.stdout


def test_export_from_cad_never_modifies_committed_examples():
    example_dir = project_store.REPO_ROOT / "examples" / "storage-bin-lid"
    before = sorted(str(p) for p in example_dir.rglob("*"))
    runner.invoke(app, ["export-from-cad", str(example_dir)])
    after = sorted(str(p) for p in example_dir.rglob("*"))
    assert before == after


# ---- JSON contract: no plain-text contamination ----


def test_export_from_cad_json_is_the_only_output(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    result = runner.invoke(app, ["export-from-cad", str(scad_project), "--json"])
    # json.loads() on the full stdout succeeds only if nothing else was
    # printed before or after the JSON payload.
    json.loads(result.stdout)


def test_export_from_cad_json_missing_project_is_clean_json():
    result = runner.invoke(app, ["export-from-cad", "/no/such/project", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["errors"]
    assert payload["no_automatic_print"] is True


def test_export_from_cad_json_confirmed_run_is_clean_json(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    result = runner.invoke(app, ["export-from-cad", str(scad_project), "--confirm-export", "--all", "--json"])
    payload = json.loads(result.stdout)
    assert payload["decision"] == "allowed"


# ---- missing project (non-JSON) ----


def test_export_from_cad_missing_project_human_readable():
    result = runner.invoke(app, ["export-from-cad", "/no/such/project"])
    assert result.exit_code == 1
    assert "error" in result.stdout.lower()


# ---- confirmed export ----


def test_export_from_cad_confirm_export_requires_flag(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    result = runner.invoke(app, ["export-from-cad", str(scad_project)])
    assert result.exit_code == 0, result.stdout
    assert "needs_confirmation" in result.stdout or "Needs" not in result.stdout  # decision printed as raw value
    assert not (scad_project / "stl" / "sign.stl").exists()


def test_export_from_cad_confirmed_export_writes_stl(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    result = runner.invoke(app, ["export-from-cad", str(scad_project), "--confirm-export"])
    assert result.exit_code == 0, result.stdout
    assert "exported" in result.stdout
    assert (scad_project / "stl" / "sign.stl").is_file()


def test_export_from_cad_confirmed_blocked_run_writes_nothing(isolated_projects_dir):
    root = project_store.init_project("Empty")
    result = runner.invoke(app, ["export-from-cad", str(root), "--confirm-export"])
    assert result.exit_code == 0, result.stdout
    assert not (root / "generated").exists()


def test_export_from_cad_writes_receipt_and_json_includes_path(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    result = runner.invoke(app, ["export-from-cad", str(scad_project), "--confirm-export", "--json"])
    payload = json.loads(result.stdout)
    assert payload["receipt"]["path"] == str(scad_project / "generated" / "export_receipt.json")
    assert (scad_project / "generated" / "export_receipt.json").is_file()


def test_export_from_cad_dry_run_never_writes_a_receipt(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    runner.invoke(app, ["export-from-cad", str(scad_project)])
    assert not (scad_project / "generated").exists()


def test_export_from_cad_human_readable_no_automatic_receipt_confirmation(scad_project, monkeypatch):
    # "Update execution receipt" legitimately appears as a line in the
    # static "Post-export checks" checklist (shown in every run, dry or
    # confirmed) - what must NOT appear is a write-confirmation banner
    # naming the receipt's path, the way `factory validate` prints
    # "wrote <path>" for its own report.
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    result = runner.invoke(app, ["export-from-cad", str(scad_project), "--confirm-export"])
    assert "generated/export_receipt.json" not in result.stdout
    assert "wrote" not in result.stdout.lower()


# ---- --overwrite-stl ----


def test_export_from_cad_collision_without_overwrite_blocks(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    runner.invoke(app, ["export-from-cad", str(scad_project), "--confirm-export"])

    result = runner.invoke(app, ["export-from-cad", str(scad_project), "--confirm-export", "--json"])
    payload = json.loads(result.stdout)
    assert payload["decision"] == "output_collision"


def test_export_from_cad_overwrite_stl_flag_unblocks(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    runner.invoke(app, ["export-from-cad", str(scad_project), "--confirm-export"])

    result = runner.invoke(
        app, ["export-from-cad", str(scad_project), "--confirm-export", "--overwrite-stl", "--json"]
    )
    payload = json.loads(result.stdout)
    assert payload["decision"] == "allowed"


# ---- CadQuery manual-export-required ----


def test_export_from_cad_cadquery_source_never_invokes_a_subprocess(isolated_projects_dir, monkeypatch):
    monkeypatch.setattr(cadquery_backend, "is_cadquery_available", lambda: True)
    root = project_store.init_project("Demo Bracket")
    cadquery_backend.generate_cadquery(root, "mechanical-plate")

    def _boom(*a, **k):
        raise AssertionError("CadQuery source must never be executed automatically")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    result = runner.invoke(app, ["export-from-cad", str(root), "--confirm-export", "--json"])
    payload = json.loads(result.stdout)
    assert payload["decision"] == "manual_export_required"


# ---- --validate / --render / --all ----


def test_export_from_cad_all_runs_validate_and_render(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    result = runner.invoke(app, ["export-from-cad", str(scad_project), "--confirm-export", "--all", "--json"])
    payload = json.loads(result.stdout)
    assert payload["validation"][0]["status"] in export_pipeline.VALIDATION_STATUSES
    assert payload["preview"][0]["status"] in export_pipeline.RENDER_STATUSES
    assert (scad_project / "validation" / "sign_validation.json").is_file()
    assert (scad_project / "renders" / "sign_preview.png").is_file()


def test_export_from_cad_validate_flag_alone(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    result = runner.invoke(app, ["export-from-cad", str(scad_project), "--confirm-export", "--validate", "--json"])
    payload = json.loads(result.stdout)
    assert payload["validation"][0]["status"] != "not_run"
    assert payload["preview"][0]["status"] == "not_run"


# ---- --resume ----


def test_export_from_cad_resume_skips_already_current_stages(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    runner.invoke(app, ["export-from-cad", str(scad_project), "--confirm-export", "--validate"])
    receipt_before = json.loads((scad_project / "generated" / "export_receipt.json").read_text())
    started_before = receipt_before["exports"][0]["export"]["started_at"]

    result = runner.invoke(
        app, ["export-from-cad", str(scad_project), "--confirm-export", "--all", "--resume", "--json"]
    )
    assert result.exit_code == 0, result.stdout
    receipt_after = json.loads((scad_project / "generated" / "export_receipt.json").read_text())
    assert receipt_after["exports"][0]["export"]["started_at"] == started_before
    assert receipt_after["exports"][0]["render"]["status"] != "not_run"


# ---- artifact registry in JSON ----


def test_export_from_cad_json_includes_artifact_registry(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    result = runner.invoke(app, ["export-from-cad", str(scad_project), "--json"])
    payload = json.loads(result.stdout)
    assert "artifact_registry" in payload
    assert set(payload["artifact_registry"].keys()) == {"cad_source", "stl", "validation", "preview", "review", "receipts"}


# ---- CLI is thin: no re-implemented planning logic ----


def test_cli_export_from_cad_command_does_not_reimplement_planning_logic():
    from factory import cli

    source = inspect.getsource(cli.export_from_cad_cmd)
    assert "_discover_cad_sources" not in source
    assert "_stl_freshness" not in source
    assert "resolve_openscad_executable(" not in source


def test_cli_module_export_pipeline_wiring_has_no_forbidden_calls():
    from factory import cli

    forbidden = ("requests.get(", "requests.post(", "urlopen(", "socket.", "openai", "anthropic")
    source = inspect.getsource(cli.export_from_cad_cmd)
    for term in forbidden:
        assert term not in source


# ---- regression: existing commands unaffected ----


def test_generate_openscad_cli_unaffected_by_export_from_cad_command(isolated_projects_dir):
    root = project_store.init_project("Regression Project")
    result = runner.invoke(app, ["generate-openscad", str(root), "--template", "test-cube"])
    assert result.exit_code == 0, result.stdout
    assert (root / "cad").exists()


def test_validate_cli_unaffected_by_export_from_cad_command(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    runner.invoke(app, ["export-from-cad", str(scad_project), "--confirm-export"])
    result = runner.invoke(app, ["validate", str(scad_project / "stl" / "sign.stl")])
    assert result.exit_code == 0, result.stdout


def test_render_cli_unaffected_by_export_from_cad_command(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    runner.invoke(app, ["export-from-cad", str(scad_project), "--confirm-export"])
    result = runner.invoke(app, ["render", str(scad_project / "stl" / "sign.stl")])
    assert result.exit_code == 0, result.stdout


def test_review_gate_cli_remains_read_only_and_unaffected(scad_project, monkeypatch):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    runner.invoke(app, ["export-from-cad", str(scad_project), "--confirm-export"])
    result = runner.invoke(app, ["review-gate", "--json", str(scad_project)])
    payload = json.loads(result.stdout)
    assert "export_pipeline_summary" not in payload


def test_preview_board_cli_unaffected_by_export_from_cad_command(isolated_projects_dir, scad_project):
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout


def test_generate_from_readiness_cli_unaffected_by_export_from_cad_command():
    result = runner.invoke(app, ["generate-from-readiness", "examples/storage-bin-lid", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert "recommended_engine" in payload


def test_report_command_unaffected_by_export_from_cad_command(scad_project):
    result = runner.invoke(app, ["report", str(scad_project)])
    assert result.exit_code == 0, result.stdout

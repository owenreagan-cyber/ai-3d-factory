"""Phase 33 tests: the `factory readiness` CLI - a thin wrapper around
`factory.design_orchestrator`. Still completely local: no AI, no LLM, no
network, no CAD generation, no engine invocation. See
docs/design-orchestrator.md, docs/roadmap.md Phase 33.
"""

import json

import pytest
from typer.testing import CliRunner

from factory import project_store
from factory.cli import app

runner = CliRunner()

BENCHMARK_PATH = "examples/intake-benchmarks/teacher-nameplate.md"
STORAGE_BIN_LID_PATH = "examples/storage-bin-lid"


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture()
def project_root(isolated_projects_dir):
    return project_store.init_project("Demo Project")


# ---- help ----


def test_readiness_help():
    result = runner.invoke(app, ["readiness", "--help"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_top_level_help_lists_readiness_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "readiness" in result.stdout


def test_status_command_lists_readiness():
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "readiness" in result.stdout


# ---- single project directory ----


def test_readiness_storage_bin_lid_human_readable():
    result = runner.invoke(app, ["readiness", STORAGE_BIN_LID_PATH])
    assert result.exit_code == 0, result.stdout
    assert "Overall:" in result.stdout
    assert "Ready for:" in result.stdout
    assert "Status:" in result.stdout
    assert "Score breakdown:" in result.stdout
    assert "Remaining:" in result.stdout
    assert "OpenSCAD" in result.stdout


def test_readiness_storage_bin_lid_json():
    result = runner.invoke(app, ["readiness", STORAGE_BIN_LID_PATH, "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {"readiness_state", "recommended_engine", "engine_rationale", "score", "advisories"}
    assert payload["recommended_engine"] == "OpenSCAD"


def test_readiness_json_matches_summarize_project():
    from factory.project_inspection import summarize_project

    result = runner.invoke(app, ["readiness", STORAGE_BIN_LID_PATH, "--json"])
    payload = json.loads(result.stdout)
    from pathlib import Path

    expected = summarize_project(Path(STORAGE_BIN_LID_PATH))["design_orchestrator_summary"]
    assert payload == expected


# ---- markdown/text file ----


def test_readiness_markdown_benchmark_human_readable():
    result = runner.invoke(app, ["readiness", BENCHMARK_PATH])
    assert result.exit_code == 0, result.stdout
    assert "OpenSCAD" in result.stdout
    assert "deterministic, local-only recommendation" in result.stdout


def test_readiness_markdown_benchmark_json():
    result = runner.invoke(app, ["readiness", BENCHMARK_PATH, "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["recommended_engine"] == "OpenSCAD"


def test_readiness_plain_text_file(tmp_path):
    path = tmp_path / "idea.txt"
    path.write_text("A replacement bracket for my broken shelf mount.", encoding="utf-8")
    result = runner.invoke(app, ["readiness", str(path)])
    assert result.exit_code == 0, result.stdout
    assert "CadQuery" in result.stdout


# ---- projects root (multi-project) ----


def test_readiness_examples_root_human_readable():
    result = runner.invoke(app, ["readiness", "examples/"])
    assert result.exit_code == 0, result.stdout
    assert "Project Readiness" in result.stdout
    assert "project(s) under" in result.stdout
    assert "storage-bin-lid" in result.stdout


def test_readiness_examples_root_json():
    result = runner.invoke(app, ["readiness", "examples/", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {"projects_root", "project_count", "projects"}
    assert "storage-bin-lid" in payload["projects"]
    assert payload["projects"]["storage-bin-lid"]["recommended_engine"] == "OpenSCAD"


def test_readiness_projects_root_with_multiple_projects(isolated_projects_dir, monkeypatch):
    project_store.init_project("Project One")
    project_store.init_project("Project Two")
    result = runner.invoke(app, ["readiness", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout
    assert "2 project(s)" in result.stdout
    assert "project-one" in result.stdout
    assert "project-two" in result.stdout


def test_readiness_projects_root_never_writes_anything(isolated_projects_dir, project_root):
    before = project_store.load_json(project_root / "brief.json")
    runner.invoke(app, ["readiness", str(isolated_projects_dir)])
    after = project_store.load_json(project_root / "brief.json")
    assert before == after


# ---- missing / empty input ----


def test_readiness_missing_path_returns_clean_result(isolated_projects_dir):
    result = runner.invoke(app, ["readiness", str(isolated_projects_dir / "does-not-exist")])
    assert result.exit_code == 0, result.stdout
    assert "Traceback" not in result.stdout
    assert "Not Ready" in result.stdout


def test_readiness_empty_file_returns_clean_result(tmp_path):
    path = tmp_path / "empty.md"
    path.write_text("", encoding="utf-8")
    result = runner.invoke(app, ["readiness", str(path)])
    assert result.exit_code == 0, result.stdout
    assert "Not Ready" in result.stdout


def test_readiness_requires_a_path_argument():
    result = runner.invoke(app, ["readiness"])
    assert result.exit_code != 0


def test_readiness_never_writes_any_file(tmp_path):
    before = sorted(p.name for p in tmp_path.iterdir())
    runner.invoke(app, ["readiness", BENCHMARK_PATH])
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after


# ---- CLI is thin: no re-implemented orchestrator logic ----


def test_cli_readiness_command_does_not_reimplement_orchestrator_logic():
    import inspect

    from factory import cli

    source = inspect.getsource(cli.readiness_cmd)
    assert "CATEGORY_WEIGHTS" not in source
    assert "_score_intake" not in source
    assert "_ORGANIC_VISUAL_KEYWORDS" not in source


def test_cli_module_has_no_forbidden_network_or_ai_calls():
    import inspect

    from factory import cli

    forbidden = ("requests.get(", "requests.post(", "urlopen(", "socket.", "openai", "anthropic")
    source = inspect.getsource(cli)
    for term in forbidden:
        assert term not in source


# ---- regression: existing commands unaffected ----


def test_preview_board_cli_unaffected_by_readiness_command(isolated_projects_dir, project_root):
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout


def test_intake_suggest_brief_cli_unaffected_by_readiness_command():
    result = runner.invoke(app, ["intake", "suggest-brief", BENCHMARK_PATH])
    assert result.exit_code == 0, result.stdout


def test_reference_board_cli_unaffected_by_readiness_command(project_root):
    result = runner.invoke(app, ["reference-board", "show", str(project_root)])
    assert result.exit_code == 0, result.stdout


def test_review_gate_cli_unaffected_by_readiness_command(project_root):
    result = runner.invoke(app, ["review-gate", "--json", str(project_root)])
    payload = json.loads(result.stdout)
    assert "design_orchestrator_summary" not in payload


def test_report_command_unaffected_by_readiness_command(project_root):
    result = runner.invoke(app, ["report", str(project_root)])
    assert result.exit_code == 0, result.stdout

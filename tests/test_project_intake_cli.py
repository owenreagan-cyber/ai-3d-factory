"""Phase 30 tests: the `factory intake analyze` CLI - a thin wrapper around
`factory.project_intake`. Still completely local: no AI, no LLM, no
network, no search. See docs/project-intake.md, docs/roadmap.md Phase 30.
"""

import json

import pytest
from typer.testing import CliRunner

from factory import project_store
from factory.cli import app

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


BENCHMARK_PATH = "examples/intake-benchmarks/teacher-nameplate.md"


# ---- help / CLI wiring ----


def test_intake_help():
    result = runner.invoke(app, ["intake", "--help"])
    assert result.exit_code == 0
    assert "analyze" in result.stdout


def test_intake_analyze_help():
    result = runner.invoke(app, ["intake", "analyze", "--help"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_top_level_help_lists_intake_group():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "intake" in result.stdout


def test_status_command_lists_intake_analyze():
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "intake analyze" in result.stdout


# ---- analyze against a markdown file ----


def test_analyze_markdown_file_human_readable():
    result = runner.invoke(app, ["intake", "analyze", BENCHMARK_PATH])
    assert result.exit_code == 0, result.stdout
    assert "Project Intake Analysis" in result.stdout
    assert "markdown_file" in result.stdout
    assert "Sign" in result.stdout
    assert "Classroom" in result.stdout
    assert "Etsy-worthy" in result.stdout
    assert "PLA" in result.stdout
    assert "Bambu" in result.stdout


def test_analyze_markdown_file_json():
    result = runner.invoke(app, ["intake", "analyze", BENCHMARK_PATH, "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["source"] == "markdown_file"
    assert payload["category"]["value"] == "sign"
    assert payload["material_assumptions"]["value"] == ["PLA"]
    assert payload["printer_assumptions"]["value"] == ["Bambu"]
    assert payload["dimensional_constraints"]["value"] == ["48-inch"]
    assert "anime" in payload["visual_goals"]["value"]


def test_analyze_json_matches_module_function():
    from factory.project_intake import analyze

    result = runner.invoke(app, ["intake", "analyze", BENCHMARK_PATH, "--json"])
    payload = json.loads(result.stdout)
    from pathlib import Path

    assert payload == analyze(Path(BENCHMARK_PATH))


# ---- analyze against a plain text file ----


def test_analyze_plain_text_file(tmp_path):
    path = tmp_path / "idea.txt"
    path.write_text("A premium nameplate made of PLA on a Bambu printer.", encoding="utf-8")
    result = runner.invoke(app, ["intake", "analyze", str(path)])
    assert result.exit_code == 0, result.stdout
    assert "text_file" in result.stdout
    assert "Sign" in result.stdout


# ---- analyze against a project directory ----


def test_analyze_project_directory(project_root):
    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["description"] = "A premium etsy-worthy classroom sign, made of PLA."
    project_store.save_json(brief_path, brief)

    result = runner.invoke(app, ["intake", "analyze", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "brief_description" in result.stdout
    assert "Demo Project" in result.stdout  # the brief's literal project_name


def test_analyze_project_directory_with_no_description(project_root):
    result = runner.invoke(app, ["intake", "analyze", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "Unknown" in result.stdout


# ---- missing / empty / malformed input ----


def test_analyze_missing_path_returns_clean_result(isolated_projects_dir):
    result = runner.invoke(app, ["intake", "analyze", str(isolated_projects_dir / "does-not-exist")])
    assert result.exit_code == 0, result.stdout
    assert "Traceback" not in result.stdout
    assert "none" in result.stdout


def test_analyze_empty_file_returns_clean_result(tmp_path):
    path = tmp_path / "empty.md"
    path.write_text("", encoding="utf-8")
    result = runner.invoke(app, ["intake", "analyze", str(path)])
    assert result.exit_code == 0, result.stdout
    assert "No project description text found to analyze" in result.stdout


def test_analyze_malformed_brief_json_does_not_crash(project_root):
    (project_root / "brief.json").write_text("{not valid json", encoding="utf-8")
    result = runner.invoke(app, ["intake", "analyze", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "Traceback" not in result.stdout


def test_analyze_binary_file_does_not_crash(tmp_path):
    path = tmp_path / "binary.txt"
    path.write_bytes(b"\xff\xfe\x00\x01garbage\x80\x81")
    result = runner.invoke(app, ["intake", "analyze", str(path)])
    assert result.exit_code == 0, result.stdout
    assert "Traceback" not in result.stdout


def test_analyze_unicode_file(tmp_path):
    path = tmp_path / "idea.md"
    path.write_text("# Décor pour salon\n\nUn décor élégant pour la maison. 你好", encoding="utf-8")
    result = runner.invoke(app, ["intake", "analyze", str(path)])
    assert result.exit_code == 0, result.stdout
    assert "Traceback" not in result.stdout
    assert "Décor pour salon" in result.stdout


def test_analyze_requires_a_path_argument():
    result = runner.invoke(app, ["intake", "analyze"])
    assert result.exit_code != 0


# ---- CLI is thin: no re-implemented heuristics, no forbidden calls ----


def test_cli_intake_command_does_not_reimplement_keyword_tables():
    import inspect

    from factory import cli

    source = inspect.getsource(cli.intake_analyze_cmd)
    assert "_CATEGORY_KEYWORDS" not in source
    assert "_contains_keyword" not in source
    assert "re.search(" not in source
    assert "re.compile(" not in source


def test_cli_intake_module_has_no_forbidden_network_or_ai_calls():
    import inspect

    from factory import cli

    forbidden = ("requests.get(", "requests.post(", "urlopen(", "socket.", "openai", "anthropic")
    source = inspect.getsource(cli)
    for term in forbidden:
        assert term not in source


# ---- regression: existing commands unaffected ----


def test_report_command_still_works_after_intake_cli_added(project_root):
    result = runner.invoke(app, ["report", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "Traceback" not in result.stdout


def test_reference_board_cli_still_works_after_intake_cli_added(project_root):
    result = runner.invoke(app, ["reference-board", "show", str(project_root)])
    assert result.exit_code == 0, result.stdout


def test_preview_board_cli_still_works_after_intake_cli_added(isolated_projects_dir, project_root):
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout

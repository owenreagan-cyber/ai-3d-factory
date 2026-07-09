"""Phase 31 tests: the `factory intake suggest-brief` CLI - a thin wrapper
around `factory.brief_generator`. Still completely local: no AI, no LLM,
no network, no automatic writes without an explicit --write. See
docs/brief-generator.md, docs/roadmap.md Phase 31.
"""

import json

import pytest
from typer.testing import CliRunner

from factory import project_store
from factory.cli import app

runner = CliRunner()

BENCHMARK_PATH = "examples/intake-benchmarks/teacher-nameplate.md"


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture()
def project_root(isolated_projects_dir):
    return project_store.init_project("Demo Project")


# ---- help / CLI wiring ----


def test_suggest_brief_help():
    result = runner.invoke(app, ["intake", "suggest-brief", "--help"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_intake_help_lists_suggest_brief():
    result = runner.invoke(app, ["intake", "--help"])
    assert result.exit_code == 0
    assert "suggest-brief" in result.stdout


def test_status_command_lists_suggest_brief():
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "intake suggest-brief" in result.stdout


# ---- human-readable output against the benchmark ----


def test_suggest_brief_human_readable_benchmark():
    result = runner.invoke(app, ["intake", "suggest-brief", BENCHMARK_PATH])
    assert result.exit_code == 0, result.stdout
    out = result.stdout

    assert "Draft Brief Suggestion" in out
    assert "nameplate" in out.lower()
    assert "Sign" in out
    assert "Classroom" in out
    assert "Etsy-worthy" in out
    assert "PLA" in out
    assert "Bambu" in out
    assert "AMS" in out
    assert "Multi-part" in out
    assert "unknown" in out.lower()  # commercial intent
    assert "Human approval required before save." in out
    assert "DRAFT only" in out


def test_suggest_brief_never_writes_without_write_flag(tmp_path):
    result = runner.invoke(app, ["intake", "suggest-brief", BENCHMARK_PATH])
    assert result.exit_code == 0, result.stdout
    assert not (tmp_path / "brief.json").exists()


def test_suggest_brief_readiness_header_matches_benchmark():
    result = runner.invoke(app, ["intake", "suggest-brief", BENCHMARK_PATH])
    assert "Status: Ready" in result.stdout
    assert "Populated: 85%" in result.stdout
    assert "Unknown fields: 2" in result.stdout


# ---- JSON output ----


def test_suggest_brief_json_shape():
    result = runner.invoke(app, ["intake", "suggest-brief", BENCHMARK_PATH, "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {"readiness", "brief", "design_intent", "manufacturing_notes", "advisories"}


def test_suggest_brief_json_matches_module_function():
    from pathlib import Path

    from factory.brief_generator import generate_draft, load_intake_summary_from_path

    result = runner.invoke(app, ["intake", "suggest-brief", BENCHMARK_PATH, "--json"])
    payload = json.loads(result.stdout)
    expected = generate_draft(load_intake_summary_from_path(Path(BENCHMARK_PATH)))
    assert payload == expected


def test_suggest_brief_json_never_writes(tmp_path):
    runner.invoke(app, ["intake", "suggest-brief", BENCHMARK_PATH, "--json"])
    assert not (tmp_path / "brief.json").exists()


# ---- --write ----


def test_suggest_brief_write_creates_brief_in_bare_project_dir(tmp_path):
    # A bare directory (not scaffolded via `factory init-project`, which
    # always creates its own starter brief.json) - the realistic "nothing
    # here yet" case --write is meant for.
    bare_project = tmp_path / "bare-project"
    bare_project.mkdir()

    result = runner.invoke(app, ["intake", "suggest-brief", str(bare_project), "--write"])
    assert result.exit_code == 0, result.stdout
    assert "wrote" in result.stdout
    assert (bare_project / "brief.json").is_file()


def test_suggest_brief_write_output_validates_against_schema(tmp_path):
    import jsonschema

    bare_project = tmp_path / "bare-project"
    bare_project.mkdir()
    project_store.save_json(
        bare_project / "brief.json",
        {"project_name": "x", "description": "A premium etsy-worthy classroom sign made of PLA on a Bambu printer, AMS, multi-part."},
    )
    # Overwrite via --force so --write actually regenerates the file from
    # the draft (rather than leaving the hand-seeded stub in place).
    result = runner.invoke(app, ["intake", "suggest-brief", str(bare_project), "--write", "--force"])
    assert result.exit_code == 0, result.stdout

    written = project_store.load_json(bare_project / "brief.json")
    schema = project_store.load_json(project_store.SCHEMAS_DIR / "project_brief.schema.json")
    jsonschema.validate(instance=written, schema=schema)
    assert written["intended_printer"] == "Bambu"
    assert "design_intent" in written


def test_suggest_brief_write_refuses_existing_brief(project_root):
    result = runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--write"])
    assert result.exit_code == 1
    assert "Brief already exists" in result.stdout
    assert "--force" in result.stdout


def test_suggest_brief_write_does_not_modify_existing_brief_without_force(project_root):
    before = project_store.load_json(project_root / "brief.json")
    runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--write"])
    after = project_store.load_json(project_root / "brief.json")
    assert before == after


def test_suggest_brief_write_force_replaces_existing_brief(project_root):
    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["description"] = "A premium etsy-worthy classroom sign made of PLA on a Bambu printer."
    project_store.save_json(brief_path, brief)

    result = runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--write", "--force"])
    assert result.exit_code == 0, result.stdout
    assert "wrote" in result.stdout

    written = project_store.load_json(brief_path)
    assert written["status"] == "brief_created"
    assert written["required_human_approval"] is True


def test_suggest_brief_write_missing_project_directory_errors_cleanly(isolated_projects_dir):
    missing = isolated_projects_dir / "does-not-exist"
    result = runner.invoke(app, ["intake", "suggest-brief", str(missing), "--write"])
    assert result.exit_code == 1
    assert "error" in result.stdout.lower()


def test_suggest_brief_write_with_markdown_file_path_fails_cleanly():
    # --write requires a project directory as the destination - a markdown
    # file path can't double as one.
    result = runner.invoke(app, ["intake", "suggest-brief", BENCHMARK_PATH, "--write"])
    assert result.exit_code == 1
    assert "Traceback" not in result.stdout


# ---- loading a saved intake_summary JSON ----


def test_suggest_brief_from_saved_intake_json(tmp_path):
    analyze_result = runner.invoke(app, ["intake", "analyze", BENCHMARK_PATH, "--json"])
    saved = tmp_path / "saved_intake.json"
    saved.write_text(analyze_result.stdout, encoding="utf-8")

    result = runner.invoke(app, ["intake", "suggest-brief", str(saved), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["readiness"]["percent_populated"] == 85


def test_suggest_brief_malformed_json_file_errors_cleanly(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    result = runner.invoke(app, ["intake", "suggest-brief", str(bad)])
    assert result.exit_code == 1
    assert "error" in result.stdout.lower()
    assert "Traceback" not in result.stdout


def test_suggest_brief_json_file_not_shaped_like_intake_summary_errors_cleanly(tmp_path):
    bad = tmp_path / "not_intake.json"
    project_store.save_json(bad, {"hello": "world"})
    result = runner.invoke(app, ["intake", "suggest-brief", str(bad)])
    assert result.exit_code == 1
    assert "error" in result.stdout.lower()


# ---- empty / missing / minimal input ----


def test_suggest_brief_missing_path_returns_clean_result(isolated_projects_dir):
    result = runner.invoke(app, ["intake", "suggest-brief", str(isolated_projects_dir / "does-not-exist")])
    assert result.exit_code == 0, result.stdout
    assert "Traceback" not in result.stdout
    assert "Populated: 0%" in result.stdout


def test_suggest_brief_empty_file_returns_clean_result(tmp_path):
    path = tmp_path / "empty.md"
    path.write_text("", encoding="utf-8")
    result = runner.invoke(app, ["intake", "suggest-brief", str(path)])
    assert result.exit_code == 0, result.stdout
    assert "Populated: 0%" in result.stdout


def test_suggest_brief_requires_a_path_argument():
    result = runner.invoke(app, ["intake", "suggest-brief"])
    assert result.exit_code != 0


# ---- CLI is thin: no re-implemented generator logic ----


def test_cli_suggest_brief_command_does_not_reimplement_generator_logic():
    import inspect

    from factory import cli

    source = inspect.getsource(cli.intake_suggest_brief_cmd)
    assert "_TRACKED_FIELDS" not in source
    assert "_confident_value" not in source
    assert "save_json(" not in source


def test_cli_module_has_no_forbidden_network_or_ai_calls():
    import inspect

    from factory import cli

    forbidden = ("requests.get(", "requests.post(", "urlopen(", "socket.", "openai", "anthropic")
    source = inspect.getsource(cli)
    for term in forbidden:
        assert term not in source


# ---- regression: existing commands unaffected ----


def test_intake_analyze_still_works_after_suggest_brief_added():
    result = runner.invoke(app, ["intake", "analyze", BENCHMARK_PATH])
    assert result.exit_code == 0, result.stdout


def test_reference_board_cli_still_works_after_suggest_brief_added(project_root):
    result = runner.invoke(app, ["reference-board", "show", str(project_root)])
    assert result.exit_code == 0, result.stdout


def test_preview_board_cli_still_works_after_suggest_brief_added(isolated_projects_dir, project_root):
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout


def test_report_command_still_works_after_suggest_brief_added(project_root):
    result = runner.invoke(app, ["report", str(project_root)])
    assert result.exit_code == 0, result.stdout

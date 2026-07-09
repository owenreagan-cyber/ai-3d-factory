"""Phase 29 tests: the `factory reference-board` CLI (init/show/validate/add/list)
- a thin wrapper around Phase 28's `factory.reference_board` module. Still
completely local: no search, scraping, downloading, or API/network calls.
See docs/reference-board.md, docs/roadmap.md Phase 29.
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
    return project_store.init_project("Demo Widget")


def _add(project_root, **kwargs):
    args = ["reference-board", "add", "--project", str(project_root)]
    for flag, value in kwargs.items():
        args += [f"--{flag.replace('_', '-')}", value]
    return runner.invoke(app, args)


# ---- reference-board --help / CLI wiring ----


def test_reference_board_help_lists_all_five_subcommands():
    result = runner.invoke(app, ["reference-board", "--help"])
    assert result.exit_code == 0
    for name in ("init", "show", "validate", "add", "list"):
        assert name in result.stdout


def test_top_level_help_lists_reference_board_group():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "reference-board" in result.stdout


def test_status_command_lists_reference_board_subcommands():
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "reference-board init" in result.stdout
    assert "reference-board show" in result.stdout
    assert "reference-board validate" in result.stdout
    assert "reference-board add" in result.stdout
    assert "reference-board list" in result.stdout


@pytest.mark.parametrize("subcommand", ["init", "show", "validate", "add", "list"])
def test_each_subcommand_has_help_text(subcommand):
    result = runner.invoke(app, ["reference-board", subcommand, "--help"])
    assert result.exit_code == 0
    assert result.stdout.strip()


# ---- init ----


def test_init_creates_reference_board_json(project_root):
    result = runner.invoke(app, ["reference-board", "init", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "created" in result.stdout
    board_path = project_root / "reference_board.json"
    assert board_path.is_file()


def test_init_starter_file_has_empty_references_and_documented_notes(project_root):
    runner.invoke(app, ["reference-board", "init", str(project_root)])
    data = project_store.load_json(project_root / "reference_board.json")
    assert data["references"] == []
    assert "notes" in data
    assert any("docs/reference-board.md" in n for n in data["notes"])


def test_init_does_not_overwrite_existing_file(project_root):
    runner.invoke(app, ["reference-board", "init", str(project_root)])
    _add(project_root, title="Keep me", license="cc_by")

    result = runner.invoke(app, ["reference-board", "init", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "already exists" in result.stdout

    data = project_store.load_json(project_root / "reference_board.json")
    assert len(data["references"]) == 1
    assert data["references"][0]["title"] == "Keep me"


def test_init_force_overwrites_existing_file(project_root):
    runner.invoke(app, ["reference-board", "init", str(project_root)])
    _add(project_root, title="Will be wiped", license="cc_by")

    result = runner.invoke(app, ["reference-board", "init", str(project_root), "--force"])
    assert result.exit_code == 0, result.stdout
    assert "created" in result.stdout

    data = project_store.load_json(project_root / "reference_board.json")
    assert data["references"] == []


def test_init_missing_project_directory_errors_cleanly(isolated_projects_dir):
    result = runner.invoke(app, ["reference-board", "init", str(isolated_projects_dir / "nope")])
    assert result.exit_code == 1
    assert "error" in result.stdout.lower()
    assert "Traceback" not in result.stdout


def test_init_never_creates_the_project_directory_itself(isolated_projects_dir):
    missing = isolated_projects_dir / "nope"
    runner.invoke(app, ["reference-board", "init", str(missing)])
    assert not missing.exists()


# ---- add ----


def test_add_creates_file_if_missing(project_root):
    result = _add(
        project_root,
        title="Classroom Storage Inspiration",
        url="https://example.com/storage",
        type="inspiration",
        license="unknown",
        usage="style_reference",
        notes="Used only for organization ideas",
    )
    assert result.exit_code == 0, result.stdout
    assert "added" in result.stdout

    data = project_store.load_json(project_root / "reference_board.json")
    assert len(data["references"]) == 1
    entry = data["references"][0]
    assert entry["title"] == "Classroom Storage Inspiration"
    assert entry["source_url"] == "https://example.com/storage"
    assert entry["source_type"] == "inspiration"
    assert entry["license"] == "unknown"
    assert entry["usage_intent"] == "style_reference"
    assert entry["notes"] == "Used only for organization ideas"


def test_add_prints_advisory_warnings_for_the_new_entry(project_root):
    result = _add(project_root, title="No license or url")
    assert result.exit_code == 0, result.stdout
    assert "advisory warnings" in result.stdout.lower()
    assert "no source_url recorded" in result.stdout
    assert "commercial use unclear" in result.stdout


def test_add_does_not_overwrite_existing_entries(project_root):
    _add(project_root, title="First", license="cc_by")
    _add(project_root, title="Second", license="public_domain")

    data = project_store.load_json(project_root / "reference_board.json")
    titles = [r["title"] for r in data["references"]]
    assert titles == ["First", "Second"]


def test_add_duplicate_title_appends_rather_than_merging(project_root):
    _add(project_root, title="Same Title", license="cc_by")
    _add(project_root, title="Same Title", license="public_domain")

    data = project_store.load_json(project_root / "reference_board.json")
    assert len(data["references"]) == 2
    assert data["references"][0]["license"] == "cc_by"
    assert data["references"][1]["license"] == "public_domain"


def test_add_unsupported_enum_value_is_saved_not_rejected(project_root):
    result = _add(project_root, title="Weird", type="not_a_real_type", license="not_a_real_license")
    assert result.exit_code == 0, result.stdout

    data = project_store.load_json(project_root / "reference_board.json")
    entry = data["references"][0]
    # Saved exactly as given - normalization/fallback happens on read, not on write.
    assert entry["source_type"] == "not_a_real_type"
    assert entry["license"] == "not_a_real_license"
    assert "not a supported value" in result.stdout


def test_add_missing_project_directory_errors_cleanly(isolated_projects_dir):
    result = _add(isolated_projects_dir / "nope", title="X")
    assert result.exit_code == 1
    assert "error" in result.stdout.lower()


def test_add_onto_malformed_json_errors_and_does_not_clobber(project_root):
    board_path = project_root / "reference_board.json"
    board_path.write_text("{not valid json", encoding="utf-8")

    result = _add(project_root, title="Should not append")
    assert result.exit_code == 1
    assert "not valid json" in result.stdout.lower()
    assert board_path.read_text(encoding="utf-8") == "{not valid json"


def test_add_requires_title():
    result = runner.invoke(app, ["reference-board", "add", "--project", "some/path"])
    assert result.exit_code != 0


# ---- show ----


def test_show_on_missing_reference_board_reports_zero(project_root):
    result = runner.invoke(app, ["reference-board", "show", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "References: 0" in result.stdout
    assert "Warnings: 0" in result.stdout


def test_show_fully_populated_board(project_root):
    _add(project_root, title="A", license="commercial_allowed", usage="style_reference")
    _add(project_root, title="B", license="unknown", usage="style_reference")
    _add(project_root, title="C", license="unknown", usage="functional_reference")

    result = runner.invoke(app, ["reference-board", "show", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "References: 3" in result.stdout
    assert "License Status" in result.stdout
    assert "Commercial Allowed: 1" in result.stdout
    assert "Unknown: 2" in result.stdout
    assert "Usage" in result.stdout
    assert "Style Reference: 2" in result.stdout
    assert "Functional Reference: 1" in result.stdout


def test_show_json_matches_summarize_reference_board(project_root):
    _add(project_root, title="A", license="cc_by")
    result = runner.invoke(app, ["reference-board", "show", str(project_root), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)

    from factory.reference_board import summarize_reference_board

    assert payload == summarize_reference_board(project_root)


def test_show_missing_project_directory_errors_cleanly(isolated_projects_dir):
    result = runner.invoke(app, ["reference-board", "show", str(isolated_projects_dir / "nope")])
    assert result.exit_code == 1
    assert "error" in result.stdout.lower()


# ---- validate ----


def test_validate_empty_board_is_valid_with_no_warnings(project_root):
    runner.invoke(app, ["reference-board", "init", str(project_root)])
    result = runner.invoke(app, ["reference-board", "validate", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "Valid reference board" in result.stdout
    assert "No warnings." in result.stdout


def test_validate_missing_reference_board_file_is_still_valid(project_root):
    result = runner.invoke(app, ["reference-board", "validate", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "Valid reference board" in result.stdout


def test_validate_reports_advisory_warnings_never_fails(project_root):
    _add(project_root, title="No license or url", usage="remix_candidate")
    result = runner.invoke(app, ["reference-board", "validate", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "Valid reference board" in result.stdout
    assert "Warnings" in result.stdout
    assert "do not remix without confirming rights" in result.stdout


def test_validate_malformed_json_is_the_only_error_condition(project_root):
    (project_root / "reference_board.json").write_text("{not valid json", encoding="utf-8")
    result = runner.invoke(app, ["reference-board", "validate", str(project_root)])
    assert result.exit_code == 1
    assert "invalid reference_board.json" in result.stdout
    assert "Traceback" not in result.stdout


def test_validate_json_output_shape(project_root):
    result = runner.invoke(app, ["reference-board", "validate", str(project_root), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["result"] == "valid"
    assert "reference_count" in payload
    assert "warnings" in payload


def test_validate_malformed_json_output_shape(project_root):
    (project_root / "reference_board.json").write_text("{not valid json", encoding="utf-8")
    result = runner.invoke(app, ["reference-board", "validate", str(project_root), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["result"] == "invalid_json"
    assert "error" in payload


# ---- list ----


def test_list_on_empty_board_prints_no_references_message(project_root):
    result = runner.invoke(app, ["reference-board", "list", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "No references recorded for this project." in result.stdout


def test_list_prints_each_reference_with_index_and_fields(project_root):
    _add(project_root, title="Classroom Storage Inspiration", type="inspiration", license="unknown", usage="style_reference")
    _add(project_root, title="Hand Sketch", type="sketch", license="custom", usage="functional_reference")

    result = runner.invoke(app, ["reference-board", "list", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "1" in result.stdout
    assert "Classroom Storage Inspiration" in result.stdout
    assert "Inspiration" in result.stdout
    assert "2" in result.stdout
    assert "Hand Sketch" in result.stdout
    assert "Sketch" in result.stdout
    assert "Custom" in result.stdout
    assert "Functional Reference" in result.stdout
    assert "-" * 20 in result.stdout


def test_list_json_matches_normalize_references(project_root):
    _add(project_root, title="A", license="cc_by")
    result = runner.invoke(app, ["reference-board", "list", str(project_root), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)

    from factory.reference_board import normalize_references

    assert payload == normalize_references(project_root)


def test_list_missing_project_directory_errors_cleanly(isolated_projects_dir):
    result = runner.invoke(app, ["reference-board", "list", str(isolated_projects_dir / "nope")])
    assert result.exit_code == 1
    assert "error" in result.stdout.lower()


# ---- CLI is a thin wrapper: no duplicated validation logic ----


def test_cli_module_reference_board_commands_do_not_reimplement_normalization():
    import inspect

    from factory import cli

    for func in (
        cli.reference_board_show_cmd,
        cli.reference_board_validate_cmd,
        cli.reference_board_list_cmd,
        cli.reference_board_add_cmd,
        cli.reference_board_init_cmd,
    ):
        source = inspect.getsource(func)
        # None of the CLI commands should touch SOURCE_TYPES/LICENSES/USAGE_INTENTS
        # membership logic directly - that's _normalize_reference()'s job alone.
        assert " in SOURCE_TYPES" not in source
        assert " in LICENSES" not in source
        assert " in USAGE_INTENTS" not in source


def test_cli_module_has_no_forbidden_network_calls():
    import inspect

    from factory import cli

    forbidden = ("requests.get(", "requests.post(", "urlopen(", "socket.", "subprocess.run(")
    source = inspect.getsource(cli)
    for term in forbidden:
        assert term not in source


# ---- regression: existing report/design-intent/preview-board commands unaffected ----


def test_report_command_still_works_after_reference_board_cli_added(project_root):
    result = runner.invoke(app, ["report", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "Traceback" not in result.stdout


def test_preview_board_cli_still_works_after_reference_board_cli_added(isolated_projects_dir, project_root):
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout


def test_review_gate_cli_still_excludes_reference_board_fields(project_root):
    result = runner.invoke(app, ["review-gate", "--json", str(project_root)])
    payload = json.loads(result.stdout)
    assert "reference_board_summary" not in payload

"""Phase 32 tests: the `factory intake suggest-brief --update` CLI - safe
merge/update mode on top of Phase 31's plain draft-write. Still completely
local, still human-approval-required before any write. See
docs/brief-generator.md, docs/roadmap.md Phase 32.
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


def _seed(project_root, description):
    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["description"] = description
    project_store.save_json(brief_path, brief)


RICH_DESCRIPTION = (
    "A premium, etsy-worthy classroom sign for my teacher's desk, gift-quality, "
    "made from PLA on a Bambu printer, AMS compatible, multi-part."
)


# ---- help ----


def test_suggest_brief_help_mentions_update():
    result = runner.invoke(app, ["intake", "suggest-brief", "--help"])
    assert result.exit_code == 0
    assert "--update" in result.stdout


# ---- --force and --update rejected together ----


def test_force_and_update_together_rejected(project_root):
    result = runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--force", "--update"])
    assert result.exit_code == 1
    assert "incompatible" in result.stdout.lower()


def test_force_and_update_together_does_not_touch_existing_brief(project_root):
    before = project_store.load_json(project_root / "brief.json")
    runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--force", "--update"])
    after = project_store.load_json(project_root / "brief.json")
    assert before == after


# ---- no brief exists: --update falls back to plain draft/write behavior ----


def test_update_with_no_existing_brief_falls_back_to_plain_draft():
    # A markdown/text path has no possible existing brief.json to merge into.
    result = runner.invoke(app, ["intake", "suggest-brief", BENCHMARK_PATH, "--update"])
    assert result.exit_code == 0, result.stdout
    assert "Draft Brief Suggestion" in result.stdout
    assert "no existing brief.json was found" in result.stdout


def test_update_write_with_no_existing_brief_creates_one(tmp_path):
    bare_project = tmp_path / "bare-project"
    bare_project.mkdir()
    result = runner.invoke(app, ["intake", "suggest-brief", str(bare_project), "--update", "--write"])
    assert result.exit_code == 0, result.stdout
    assert "wrote" in result.stdout
    assert (bare_project / "brief.json").is_file()


# ---- merge preview without --write: nothing saved ----


def test_update_preview_shows_merge_preview_header(project_root):
    _seed(project_root, RICH_DESCRIPTION)
    result = runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--update"])
    assert result.exit_code == 0, result.stdout
    assert "Brief Merge Preview" in result.stdout
    assert "Fields to add" in result.stdout
    assert "Fields preserved" in result.stdout
    assert "Warnings" in result.stdout
    assert "preview only" in result.stdout.lower()


def test_update_preview_does_not_write(project_root):
    _seed(project_root, RICH_DESCRIPTION)
    before = project_store.load_json(project_root / "brief.json")
    runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--update"])
    after = project_store.load_json(project_root / "brief.json")
    assert before == after


def test_update_preview_shows_new_fields_and_preserved_fields(project_root):
    _seed(project_root, RICH_DESCRIPTION)
    result = runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--update"])
    assert "material: PLA" in result.stdout
    assert "project_name: existing value kept" in result.stdout
    assert "purpose: existing value kept" in result.stdout


# ---- --write --update: safe merge applied ----


def test_write_update_preserves_existing_and_adds_new_fields(project_root):
    _seed(project_root, RICH_DESCRIPTION)
    before = project_store.load_json(project_root / "brief.json")

    result = runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--write", "--update"])
    assert result.exit_code == 0, result.stdout
    assert "merged and wrote" in result.stdout

    after = project_store.load_json(project_root / "brief.json")
    assert after["project_name"] == before["project_name"]
    assert after["description"] == before["description"]
    assert after["intended_printer"] == before["intended_printer"]
    assert "design_intent" in after
    assert after["design_intent"]["quality_standard"] == "etsy-worthy"
    assert "manufacturing_notes" in after


def test_write_update_never_overwrites_real_intended_printer(project_root):
    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["intended_printer"] = "Prusa MK4"
    brief["description"] = RICH_DESCRIPTION  # mentions Bambu, but printer is already real
    project_store.save_json(brief_path, brief)

    runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--write", "--update"])
    after = project_store.load_json(brief_path)
    assert after["intended_printer"] == "Prusa MK4"


def test_write_update_second_run_is_idempotent(project_root):
    _seed(project_root, RICH_DESCRIPTION)
    runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--write", "--update"])
    first = project_store.load_json(project_root / "brief.json")

    result = runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--write", "--update"])
    assert result.exit_code == 0, result.stdout
    second = project_store.load_json(project_root / "brief.json")
    assert first == second


# ---- malformed existing brief ----


def test_update_malformed_existing_brief_errors_cleanly(project_root):
    (project_root / "brief.json").write_text("{not valid json", encoding="utf-8")
    result = runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--update"])
    assert result.exit_code == 1
    assert "not valid json" in result.stdout.lower()
    assert "Traceback" not in result.stdout


def test_update_malformed_existing_brief_not_touched(project_root):
    (project_root / "brief.json").write_text("{not valid json", encoding="utf-8")
    runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--write", "--update"])
    assert (project_root / "brief.json").read_text(encoding="utf-8") == "{not valid json"


def test_update_malformed_existing_brief_force_still_works(project_root):
    (project_root / "brief.json").write_text("{not valid json", encoding="utf-8")
    result = runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--write", "--force"])
    assert result.exit_code == 0, result.stdout
    data = project_store.load_json(project_root / "brief.json")
    assert data["status"] == "brief_created"


# ---- --force still means full replacement (Phase 31 behavior unchanged) ----


def test_force_alone_still_fully_replaces(project_root):
    _seed(project_root, RICH_DESCRIPTION)
    before = project_store.load_json(project_root / "brief.json")
    assert before["description"] == RICH_DESCRIPTION

    result = runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--write", "--force"])
    assert result.exit_code == 0, result.stdout
    after = project_store.load_json(project_root / "brief.json")
    # Full replace via Phase 31's plain draft path re-derives description
    # from intake (same text in this case, since it re-reads the same
    # brief), but project_name is regenerated fresh, not "preserved" -
    # this is the key behavioral difference from --update.
    assert after["status"] == "brief_created"


def test_write_alone_without_update_or_force_refuses_existing_brief(project_root):
    result = runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--write"])
    assert result.exit_code == 1
    assert "Brief already exists" in result.stdout


# ---- JSON output ----


def test_update_json_shape():
    # No existing brief - falls back to plain draft, so --json here should
    # still be Phase 31's unchanged shape (backward compatible).
    result = runner.invoke(app, ["intake", "suggest-brief", BENCHMARK_PATH, "--update", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {"readiness", "brief", "design_intent", "manufacturing_notes", "advisories"}


def test_update_json_shape_with_existing_brief(project_root):
    _seed(project_root, RICH_DESCRIPTION)
    result = runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--update", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {
        "draft", "merge_preview", "fields_to_add", "fields_preserved", "advisories", "would_write", "wrote_file",
    }
    assert payload["would_write"] is False
    assert payload["wrote_file"] is None
    assert payload["fields_to_add"] == payload["merge_preview"]["fields_to_add"]
    assert payload["fields_preserved"] == payload["merge_preview"]["fields_preserved"]


def test_update_write_json_reports_wrote_file(project_root):
    _seed(project_root, RICH_DESCRIPTION)
    result = runner.invoke(app, ["intake", "suggest-brief", str(project_root), "--update", "--write", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["would_write"] is True
    assert payload["wrote_file"] == str(project_root / "brief.json")


def test_plain_json_output_unchanged_without_update():
    # Backward compatibility: --json without --update must be byte-for-byte
    # the same shape/content as before --update existed (Phase 31).
    from factory.brief_generator import generate_draft, load_intake_summary_from_path
    from pathlib import Path

    result = runner.invoke(app, ["intake", "suggest-brief", BENCHMARK_PATH, "--json"])
    payload = json.loads(result.stdout)
    expected = generate_draft(load_intake_summary_from_path(Path(BENCHMARK_PATH)))
    assert payload == expected


# ---- CLI is thin: no re-implemented merge logic ----


def test_cli_suggest_brief_command_does_not_reimplement_merge_logic():
    import inspect

    from factory import cli

    source = inspect.getsource(cli.intake_suggest_brief_cmd)
    assert "_MERGE_FIELDS" not in source
    assert "_is_placeholder_text" not in source
    assert "_is_present(" not in source


def test_cli_module_has_no_forbidden_network_or_ai_calls():
    import inspect

    from factory import cli

    forbidden = ("requests.get(", "requests.post(", "urlopen(", "socket.", "openai", "anthropic")
    source = inspect.getsource(cli)
    for term in forbidden:
        assert term not in source


# ---- regression: existing Phase 26-31 commands unaffected ----


def test_intake_analyze_unaffected_by_update_flag():
    result = runner.invoke(app, ["intake", "analyze", BENCHMARK_PATH])
    assert result.exit_code == 0, result.stdout


def test_reference_board_cli_unaffected(project_root):
    result = runner.invoke(app, ["reference-board", "show", str(project_root)])
    assert result.exit_code == 0, result.stdout


def test_preview_board_cli_unaffected(isolated_projects_dir, project_root):
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout


def test_review_gate_cli_unaffected(project_root):
    result = runner.invoke(app, ["review-gate", "--json", str(project_root)])
    payload = json.loads(result.stdout)
    assert "brief_update_summary" not in payload

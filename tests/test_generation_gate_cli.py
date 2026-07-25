"""Phase 34 tests: the `factory generate-from-readiness` CLI - a thin
wrapper around `factory.generation_gate`. Dry run by default; nothing is
ever written without an explicit `--confirm-generate` flag, and even then
only if the gate allows it. No AI, no LLM, no network, no Blender, no
Meshy. See docs/generation-gate.md, docs/roadmap.md Phase 34.
"""

import json

import pytest
from typer.testing import CliRunner

from factory import project_store
from factory.cli import app

runner = CliRunner()

STORAGE_BIN_LID_PATH = "examples/storage-bin-lid"

RICH_DESCRIPTION = (
    "A premium etsy-worthy classroom nameplate sign made of PLA on a Bambu H2D printer, "
    "120mm wide by 40mm tall by 5mm thick, single color."
)


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture()
def project_root(isolated_projects_dir):
    return project_store.init_project("Demo Project")


def _ready_project(project_root):
    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["description"] = RICH_DESCRIPTION
    brief["intended_printer"] = "Bambu H2D"
    brief["constraints"] = ["120mm wide, 40mm tall, 5mm thick", "PLA filament only"]
    brief["design_intent"] = {
        "quality_standard": "premium",
        "use_case": "classroom nameplate sign",
        "style_direction": ["clean", "modern"],
        "reference_inputs": ["Classroom sign example"],
        "manufacturability_constraints": {"max_size_mm": [120, 40, 5]},
    }
    project_store.save_json(brief_path, brief)
    project_store.save_json(
        project_root / "reference_board.json",
        {
            "references": [
                {
                    "title": "Classroom sign example",
                    "source_type": "image",
                    "license": "public_domain",
                    "usage_intent": "design_reference_only",
                    "attached_to": "design_intent.reference_inputs",
                    "source_url": "https://example.com/sign",
                }
            ]
        },
    )
    return project_root


# ---- help ----


def test_generate_from_readiness_help():
    result = runner.invoke(app, ["generate-from-readiness", "--help"])
    assert result.exit_code == 0
    assert result.stdout.strip()
    assert "--confirm-generate" in result.stdout
    assert "--json" in result.stdout


def test_top_level_help_lists_generate_from_readiness_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "generate-from-readiness" in result.stdout


def test_status_command_lists_generate_from_readiness():
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "generate-from-readiness" in result.stdout


# ---- dry run (default): storage-bin-lid worked example from the spec ----


def test_generate_from_readiness_storage_bin_lid_dry_run_human_readable():
    result = runner.invoke(app, ["generate-from-readiness", STORAGE_BIN_LID_PATH])
    assert result.exit_code == 0, result.stdout
    assert "Generation Plan" in result.stdout
    assert "Project:" in result.stdout
    assert "Readiness:" in result.stdout
    assert "Status:" in result.stdout
    assert "Recommended Engine:" in result.stdout
    assert "Decision:" in result.stdout
    assert "Would Generate:" in result.stdout
    assert "No files written." in result.stdout
    assert "OpenSCAD" in result.stdout
    assert "Dry Run Only" in result.stdout


def test_generate_from_readiness_storage_bin_lid_json():
    result = runner.invoke(app, ["generate-from-readiness", STORAGE_BIN_LID_PATH, "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["decision"] == "Dry Run Only"
    assert payload["recommended_engine"] == "OpenSCAD"
    assert payload["confirm_generate"] is False
    assert "generation_result" not in payload


def test_generate_from_readiness_never_writes_any_file_by_default(tmp_path):
    before = sorted(p.name for p in tmp_path.iterdir())
    runner.invoke(app, ["generate-from-readiness", STORAGE_BIN_LID_PATH])
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after


def test_generate_from_readiness_never_modifies_the_example_project():
    from pathlib import Path

    example_dir = Path(STORAGE_BIN_LID_PATH)
    before = sorted(str(p) for p in example_dir.rglob("*"))
    runner.invoke(app, ["generate-from-readiness", STORAGE_BIN_LID_PATH])
    after = sorted(str(p) for p in example_dir.rglob("*"))
    assert before == after


def test_generate_from_readiness_json_matches_summarize_project_derived_gate():
    from factory.generation_gate import evaluate_generation_gate_for_path

    result = runner.invoke(app, ["generate-from-readiness", STORAGE_BIN_LID_PATH, "--json"])
    payload = json.loads(result.stdout)
    expected = evaluate_generation_gate_for_path(STORAGE_BIN_LID_PATH)
    for key in expected:
        assert payload[key] == expected[key]


# ---- confirm-generate required, and only honored when the gate allows it ----


def test_confirm_generate_flag_required_for_a_fully_ready_project_and_writes_nothing_without_it(project_root):
    _ready_project(project_root)
    result = runner.invoke(app, ["generate-from-readiness", str(project_root)])
    assert result.exit_code == 0, result.stdout
    assert "Needs Confirmation" in result.stdout
    assert "No files written." in result.stdout
    assert list((project_root / "cad").iterdir()) == []


def test_confirm_generate_on_dry_run_only_project_still_writes_nothing(project_root):
    # project_root here has no rich description/design_intent set - it stays
    # a low-readiness "Dry Run Only" project even with --confirm-generate.
    result = runner.invoke(app, ["generate-from-readiness", str(project_root), "--confirm-generate"])
    assert result.exit_code == 0, result.stdout
    assert "No files written." in result.stdout
    assert list((project_root / "cad").iterdir()) == []


def test_confirm_generate_on_ready_project_actually_generates(project_root):
    _ready_project(project_root)
    result = runner.invoke(app, ["generate-from-readiness", str(project_root), "--confirm-generate"])
    assert result.exit_code == 0, result.stdout
    assert "Allowed" in result.stdout
    assert "generated" in result.stdout
    assert (project_root / "cad" / "sign.scad").is_file()


def test_confirm_generate_json_includes_generation_result_when_allowed(project_root):
    _ready_project(project_root)
    result = runner.invoke(app, ["generate-from-readiness", str(project_root), "--confirm-generate", "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["decision"] == "Allowed"
    assert "generation_result" in payload
    assert payload["generation_result"]["written_files"]


def test_confirm_generate_json_excludes_generation_result_when_not_allowed(project_root):
    result = runner.invoke(app, ["generate-from-readiness", str(project_root), "--confirm-generate", "--json"])
    payload = json.loads(result.stdout)
    assert payload["decision"] != "Allowed"
    assert "generation_result" not in payload


# ---- execution receipts (Phase 34) ----


def test_confirm_generate_writes_an_execution_receipt(project_root):
    _ready_project(project_root)
    result = runner.invoke(app, ["generate-from-readiness", str(project_root), "--confirm-generate"])
    assert result.exit_code == 0, result.stdout
    receipt_path = project_root / "generated" / "generation_receipt.json"
    assert receipt_path.is_file()


def test_confirm_generate_json_includes_receipt_path_when_allowed(project_root):
    _ready_project(project_root)
    result = runner.invoke(app, ["generate-from-readiness", str(project_root), "--confirm-generate", "--json"])
    payload = json.loads(result.stdout)
    assert payload["decision"] == "Allowed"
    assert payload["receipt_path"] == str(project_root / "generated" / "generation_receipt.json")


def test_confirm_generate_receipt_content_matches_the_gate_and_generation_result(project_root):
    _ready_project(project_root)
    result = runner.invoke(app, ["generate-from-readiness", str(project_root), "--confirm-generate", "--json"])
    payload = json.loads(result.stdout)
    receipt = json.loads((project_root / "generated" / "generation_receipt.json").read_text())
    assert receipt["engine"] == payload["recommended_engine"]
    assert receipt["readiness_score"] == payload["readiness_score"]
    assert receipt["files_generated"] == ["cad/sign.scad"]
    assert receipt["success"] is True


def test_dry_run_never_writes_an_execution_receipt(project_root):
    _ready_project(project_root)
    runner.invoke(app, ["generate-from-readiness", str(project_root)])  # no --confirm-generate
    assert not (project_root / "generated").exists()


def test_needs_confirmation_never_writes_an_execution_receipt(project_root):
    _ready_project(project_root)
    result = runner.invoke(app, ["generate-from-readiness", str(project_root)])
    assert "Needs Confirmation" in result.stdout
    assert not (project_root / "generated").exists()


def test_confirm_generate_on_dry_run_only_project_never_writes_a_receipt(project_root):
    result = runner.invoke(app, ["generate-from-readiness", str(project_root), "--confirm-generate"])
    assert "No files written." in result.stdout
    assert not (project_root / "generated").exists()


def test_human_readable_output_never_prints_an_automatic_receipt_confirmation(project_root):
    _ready_project(project_root)
    result = runner.invoke(app, ["generate-from-readiness", str(project_root), "--confirm-generate"])
    assert "receipt" not in result.stdout.lower()


def test_second_confirmed_run_on_same_project_does_not_crash_and_reports_a_clear_error(project_root):
    _ready_project(project_root)
    first = runner.invoke(app, ["generate-from-readiness", str(project_root), "--confirm-generate", "--json"])
    assert first.exit_code == 0, first.stdout

    second = runner.invoke(app, ["generate-from-readiness", str(project_root), "--confirm-generate", "--json"])
    # A clean typer.Exit(code=1) - not an unhandled exception surfacing as a
    # raw traceback (a real crash would show up here as some other
    # exception type, e.g. GeneratedFileExistsError, and CliRunner would
    # still capture it - the JSON payload below is what actually proves
    # this was handled gracefully rather than merely caught).
    assert isinstance(second.exception, SystemExit)
    payload = json.loads(second.stdout)
    assert second.exit_code == 1
    assert "generation_error" in payload
    assert "sign.scad" in payload["generation_error"]
    assert "generation_result" not in payload
    assert "receipt_path" not in payload


def test_second_confirmed_run_on_same_project_human_readable_does_not_crash(project_root):
    _ready_project(project_root)
    runner.invoke(app, ["generate-from-readiness", str(project_root), "--confirm-generate"])
    second = runner.invoke(app, ["generate-from-readiness", str(project_root), "--confirm-generate"])
    assert isinstance(second.exception, SystemExit)
    assert second.exit_code == 1
    assert "error" in second.stdout.lower()
    assert "Traceback" not in second.stdout


# ---- blocked project ----


def test_blocked_project_never_generates_even_with_confirm_generate(project_root):
    brief_path = project_root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["design_intent"] = {
        "quality_standard": "premium",
        "manufacturability_constraints": {"max_size_mm": [10000, 10000, 10000]},
    }
    project_store.save_json(brief_path, brief)

    result = runner.invoke(app, ["generate-from-readiness", str(project_root), "--confirm-generate", "--json"])
    payload = json.loads(result.stdout)
    assert payload["decision"] == "Blocked"
    assert list((project_root / "cad").iterdir()) == []


# ---- unsupported engine ----


def test_unsupported_engine_organic_idea_never_generates(tmp_path):
    path = tmp_path / "idea.txt"
    path.write_text("An anime-inspired figure for display.", encoding="utf-8")
    result = runner.invoke(app, ["generate-from-readiness", str(path), "--confirm-generate", "--json"])
    payload = json.loads(result.stdout)
    assert payload["decision"] == "Unsupported Engine"
    assert payload["recommended_engine"] in ("Blender", "Meshy (Concept Only)")


# ---- missing path argument ----


def test_generate_from_readiness_requires_a_path_argument():
    result = runner.invoke(app, ["generate-from-readiness"])
    assert result.exit_code != 0


# ---- CLI is thin: no re-implemented gate logic ----


def test_cli_generate_from_readiness_command_does_not_reimplement_gate_logic():
    import inspect

    from factory import cli

    source = inspect.getsource(cli.generate_from_readiness_cmd)
    assert "MINIMUM_READINESS_SCORE" not in source
    assert "_select_openscad_plan" not in source
    assert "_CRITICAL_ADVISORIES" not in source


def test_cli_module_has_no_forbidden_network_or_ai_calls():
    import inspect

    from factory import cli

    forbidden = ("requests.get(", "requests.post(", "urlopen(", "socket.", "openai", "anthropic")
    source = inspect.getsource(cli)
    for term in forbidden:
        assert term not in source


# ---- regression: existing commands unaffected ----


def test_readiness_cli_unaffected_by_generate_from_readiness_command():
    result = runner.invoke(app, ["readiness", STORAGE_BIN_LID_PATH, "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert "recommended_engine" in payload


def test_generate_openscad_cli_unaffected_by_generate_from_readiness_command(project_root):
    result = runner.invoke(app, ["generate-openscad", str(project_root), "--template", "test-cube"])
    assert result.exit_code == 0, result.stdout
    assert (project_root / "cad").exists()


def test_preview_board_cli_unaffected_by_generate_from_readiness_command(isolated_projects_dir, project_root):
    result = runner.invoke(app, ["preview-board", str(isolated_projects_dir)])
    assert result.exit_code == 0, result.stdout


def test_review_gate_cli_unaffected_by_generate_from_readiness_command(project_root):
    result = runner.invoke(app, ["review-gate", "--json", str(project_root)])
    payload = json.loads(result.stdout)
    assert "generation_gate_summary" not in payload


def test_report_command_unaffected_by_generate_from_readiness_command(project_root):
    result = runner.invoke(app, ["report", str(project_root)])
    assert result.exit_code == 0, result.stdout

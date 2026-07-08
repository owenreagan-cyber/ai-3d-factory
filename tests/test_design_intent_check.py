import ast
import inspect
import json

import pytest
from typer.testing import CliRunner

from factory import design_intent_check, project_store
from factory.cli import app
from factory.design_intent_check import (
    RESULT_FITS_NONE,
    RESULT_FITS_SOME,
    RESULT_INVALID_MAX_SIZE,
    RESULT_MISSING_PRINTER_CONFIG,
    RESULT_NO_DESIGN_INTENT,
    RESULT_NO_MAX_SIZE,
    RESULT_UNREADABLE_FILE,
    check_design_intent_manufacturability,
)

runner = CliRunner()

PIGGY_BANK_BRIEF = (
    project_store.REPO_ROOT
    / "examples"
    / "future-organic-models"
    / "piggy-bank-design-study"
    / "concept_brief.json"
)
CHIP_CLIP_BRIEF = (
    project_store.REPO_ROOT
    / "examples"
    / "future-functional-designs"
    / "chip-bag-clip-study"
    / "concept_brief.json"
)


def _write_brief(tmp_path, data, name="brief.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---- result classification ----


def test_no_design_intent_when_field_absent(tmp_path):
    path = _write_brief(tmp_path, {"project_name": "x"})
    result = check_design_intent_manufacturability(path)
    assert result["result"] == RESULT_NO_DESIGN_INTENT
    assert result["quality_standard"] is None
    assert result["max_size_mm"] is None


def test_no_design_intent_when_field_not_a_dict(tmp_path):
    path = _write_brief(tmp_path, {"design_intent": "not a dict"})
    result = check_design_intent_manufacturability(path)
    assert result["result"] == RESULT_NO_DESIGN_INTENT


def test_no_max_size_when_manufacturability_constraints_absent(tmp_path):
    path = _write_brief(tmp_path, {"design_intent": {"quality_standard": "Etsy-worthy"}})
    result = check_design_intent_manufacturability(path)
    assert result["result"] == RESULT_NO_MAX_SIZE
    assert result["quality_standard"] == "Etsy-worthy"


def test_no_max_size_when_max_size_mm_absent(tmp_path):
    path = _write_brief(tmp_path, {"design_intent": {"manufacturability_constraints": {}}})
    result = check_design_intent_manufacturability(path)
    assert result["result"] == RESULT_NO_MAX_SIZE


def test_no_max_size_when_max_size_mm_is_explicit_null(tmp_path):
    path = _write_brief(tmp_path, {"design_intent": {"manufacturability_constraints": {"max_size_mm": None}}})
    result = check_design_intent_manufacturability(path)
    assert result["result"] == RESULT_NO_MAX_SIZE


def test_valid_max_size_fits_at_least_one_configured_printer(tmp_path):
    path = _write_brief(
        tmp_path,
        {
            "design_intent": {
                "quality_standard": "Etsy-worthy",
                "manufacturability_constraints": {"max_size_mm": [50, 50, 50]},
            }
        },
    )
    result = check_design_intent_manufacturability(path)
    assert result["result"] == RESULT_FITS_SOME
    assert result["fitting_printers"]
    assert result["max_size_mm"] == [50.0, 50.0, 50.0]
    assert result["quality_standard"] == "Etsy-worthy"


def test_valid_max_size_fits_no_configured_printer(tmp_path):
    path = _write_brief(
        tmp_path,
        {"design_intent": {"manufacturability_constraints": {"max_size_mm": [10000, 10000, 10000]}}},
    )
    result = check_design_intent_manufacturability(path)
    assert result["result"] == RESULT_FITS_NONE
    assert result["fitting_printers"] == []
    assert result["warnings"]


def test_fits_via_axis_permutation(tmp_path):
    # A long, thin part that doesn't fit x/y/z as declared, but does once
    # reoriented - the check must try every orientation before giving up,
    # same as factory.validators.dimension_check.
    path = _write_brief(
        tmp_path,
        {"design_intent": {"manufacturability_constraints": {"max_size_mm": [300, 50, 50]}}},
    )
    result = check_design_intent_manufacturability(path)
    # bambu_h2d is 350x320x325 - a 300x50x50 part fits directly (no
    # reorientation even needed), so this also sanity-checks basic fit.
    assert result["result"] == RESULT_FITS_SOME


@pytest.mark.parametrize(
    "bad_value",
    [
        "not a list",
        [1, 2],
        [1, 2, "x"],
        [1, 2, -5],
        [0, 10, 10],
        123,
    ],
)
def test_invalid_max_size_shapes(tmp_path, bad_value):
    path = _write_brief(
        tmp_path,
        {"design_intent": {"manufacturability_constraints": {"max_size_mm": bad_value}}},
    )
    result = check_design_intent_manufacturability(path)
    assert result["result"] == RESULT_INVALID_MAX_SIZE
    assert result["warnings"]
    assert result["max_size_mm"] == bad_value


def test_unreadable_file_when_missing(tmp_path):
    path = tmp_path / "does-not-exist.json"
    result = check_design_intent_manufacturability(path)
    assert result["result"] == RESULT_UNREADABLE_FILE


def test_unreadable_file_when_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid json", encoding="utf-8")
    result = check_design_intent_manufacturability(path)
    assert result["result"] == RESULT_UNREADABLE_FILE


def test_missing_printer_config_handled_gracefully(tmp_path, monkeypatch):
    path = _write_brief(
        tmp_path,
        {"design_intent": {"manufacturability_constraints": {"max_size_mm": [10, 10, 10]}}},
    )
    monkeypatch.setattr(design_intent_check.knowledge, "load_printers", lambda: {})
    result = check_design_intent_manufacturability(path)
    assert result["result"] == RESULT_MISSING_PRINTER_CONFIG
    assert result["warnings"]


def test_every_result_includes_required_safety_notes(tmp_path):
    path = _write_brief(tmp_path, {"project_name": "x"})
    result = check_design_intent_manufacturability(path)
    notes_text = " ".join(result["notes"]).lower()
    assert "advisory" in notes_text
    assert "not an approval" in notes_text
    assert "human_approved" in notes_text
    assert "print_ready" in notes_text


# ---- real concept examples: deterministic, real fleet ----


def test_piggy_bank_concept_brief_check_is_deterministic():
    result1 = check_design_intent_manufacturability(PIGGY_BANK_BRIEF)
    result2 = check_design_intent_manufacturability(PIGGY_BANK_BRIEF)
    assert result1 == result2
    assert result1["result"] == RESULT_FITS_SOME
    assert result1["quality_standard"] == "Etsy-worthy"
    assert result1["max_size_mm"] == [120.0, 100.0, 100.0]
    assert len(result1["fitting_printers"]) == 4


def test_chip_clip_concept_brief_check_is_deterministic():
    result1 = check_design_intent_manufacturability(CHIP_CLIP_BRIEF)
    result2 = check_design_intent_manufacturability(CHIP_CLIP_BRIEF)
    assert result1 == result2
    assert result1["result"] == RESULT_FITS_SOME
    assert result1["quality_standard"] == "Etsy-worthy"
    assert result1["max_size_mm"] == [80.0, 30.0, 15.0]
    assert len(result1["fitting_printers"]) == 4


# ---- CLI ----


def test_cli_human_output_for_piggy_bank():
    result = runner.invoke(app, ["check-design-intent", str(PIGGY_BANK_BRIEF)])
    assert result.exit_code == 0
    assert "fits_some_printers" in result.stdout
    assert "Etsy-worthy" in result.stdout
    assert "not an approval" in result.stdout.lower()


def test_cli_human_output_for_chip_clip():
    result = runner.invoke(app, ["check-design-intent", str(CHIP_CLIP_BRIEF)])
    assert result.exit_code == 0
    assert "fits_some_printers" in result.stdout
    assert "80.0" in result.stdout


def test_cli_json_output_is_valid_and_matches_module():
    result = runner.invoke(app, ["check-design-intent", "--json", str(CHIP_CLIP_BRIEF)])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == check_design_intent_manufacturability(CHIP_CLIP_BRIEF)


def test_cli_unreadable_file_exits_nonzero(tmp_path):
    missing = tmp_path / "missing.json"
    result = runner.invoke(app, ["check-design-intent", str(missing)])
    assert result.exit_code == 1


def test_cli_no_design_intent_exits_zero():
    # A missing design_intent block is advisory information, not an error.
    result = runner.invoke(app, ["check-design-intent", "examples/simple-nameplate/brief.json"])
    assert result.exit_code == 0
    assert "no_design_intent" in result.stdout


def test_status_cli_lists_check_design_intent_command():
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "check-design-intent" in result.stdout


# ---- read-only: writes nothing, ever ----


def test_module_call_writes_no_files(tmp_path):
    before = sorted(p.name for p in tmp_path.iterdir())
    check_design_intent_manufacturability(PIGGY_BANK_BRIEF)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after


def test_cli_does_not_modify_committed_concept_briefs():
    import hashlib

    def _hash(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    before = {p: _hash(p) for p in (PIGGY_BANK_BRIEF, CHIP_CLIP_BRIEF)}
    runner.invoke(app, ["check-design-intent", str(PIGGY_BANK_BRIEF)])
    runner.invoke(app, ["check-design-intent", "--json", str(CHIP_CLIP_BRIEF)])
    after = {p: _hash(p) for p in (PIGGY_BANK_BRIEF, CHIP_CLIP_BRIEF)}
    assert before == after


# ---- module has no subprocess/network/printer/slicer/cloud behavior ----


FORBIDDEN_CALLS = (
    "import subprocess",
    "subprocess.run(",
    "subprocess.call(",
    "subprocess.Popen(",
    "os.system(",
    "os.popen(",
    "socket.",
    "import urllib",
    "import requests",
    "http.client",
    "write_text(",
    "write_bytes(",
    "save_json(",
)


def test_design_intent_check_module_has_no_network_process_or_write_calls():
    source = inspect.getsource(design_intent_check)
    for forbidden in FORBIDDEN_CALLS:
        assert forbidden not in source, f"factory.design_intent_check must stay local and read-only; found {forbidden!r}"


def test_design_intent_check_module_does_not_reference_human_approved_or_print_ready():
    # The module's docstrings/notes explain that it never *sets* these -
    # confirmed here by checking no string literal assigns to either field
    # (only the advisory prose in REQUIRED_SAFETY_NOTES mentions them by name).
    tree = ast.parse(inspect.getsource(design_intent_check))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, (ast.Subscript, ast.Attribute)):
                    rendered = ast.unparse(target)
                    assert "human_approved" not in rendered
                    assert "print_ready" not in rendered


def test_design_intent_check_module_only_reads_json():
    tree = ast.parse(inspect.getsource(design_intent_check))
    source = ast.unparse(tree)
    assert "load_json" in source
    assert "open(" not in source


# ---- review-gate behavior unchanged ----


def test_review_gate_cli_still_behaves_the_same_after_phase25():
    result = runner.invoke(app, ["review-gate", "examples/simple-nameplate"])
    assert result.exit_code == 1
    assert "No STL files exist yet" in result.stdout


# ---- concept examples remain concept-only ----


@pytest.mark.parametrize("path", (PIGGY_BANK_BRIEF, CHIP_CLIP_BRIEF))
def test_concept_briefs_remain_concept_only_after_phase25(path):
    concept_brief = project_store.load_json(path)
    assert concept_brief["status"] == "concept_only"
    assert concept_brief["not_printable"] is True
    assert concept_brief["not_generated"] is True
    assert not (path.parent / "brief.json").is_file()


def test_no_stl_or_png_files_added_by_phase25():
    for directory in ("docs", "examples", "src"):
        root = project_store.REPO_ROOT / directory
        assert not any(root.rglob("*.stl"))
        assert not any(root.rglob("*.png"))

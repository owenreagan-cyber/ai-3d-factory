import hashlib
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from factory import project_inspection, project_store
from factory.cli import app
from factory.examples_library import EXAMPLES_DIR, UnknownExampleError, get_example, list_examples
from factory.preview_board import discover_projects, gather_board_data
from factory.preview_package import gather_preview_data
from factory.review_gate import evaluate_review_gate

runner = CliRunner()

WORKING_EXAMPLES = ("simple-nameplate", "mechanical-plate")
MULTIPART_EXAMPLE = "multipart-classroom-sign"
LID_EXAMPLE = "storage-bin-lid"
MULTIPART_EXAMPLES = (MULTIPART_EXAMPLE, LID_EXAMPLE)
ALL_WORKING_EXAMPLES = WORKING_EXAMPLES + MULTIPART_EXAMPLES
CONCEPT_EXAMPLES = (
    "future-organic-models/car-concept",
    "future-organic-models/animal-concept",
    "future-organic-models/human-figure-study",
)

FORBIDDEN_JSON_KEYS = ("human_approved", "print_ready")


def _iter_example_files():
    return sorted(p for p in EXAMPLES_DIR.rglob("*") if p.is_file())


def _copy_example_to(name: str, tmp_path: Path) -> Path:
    """Copy a committed example into tmp_path so a test can safely run write commands against it.

    Tests must never point a write command (e.g. `factory preview-project`)
    directly at `examples/<name>` - that mutates a committed file's
    `generated_at` timestamp and leaves the working tree dirty after every
    test run. Always copy into `tmp_path` first and point commands there.
    """
    source = EXAMPLES_DIR / name
    dest = tmp_path / name
    shutil.copytree(source, dest)
    return dest


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_preview_files(name: str) -> dict:
    root = EXAMPLES_DIR / name / "preview_package"
    return {p.name: _hash_file(p) for p in sorted(root.glob("*"))}


def _assert_no_forbidden_keys(data, path):
    if isinstance(data, dict):
        for key in FORBIDDEN_JSON_KEYS:
            assert key not in data, f"{path} must not set {key!r}"
        for value in data.values():
            _assert_no_forbidden_keys(value, path)
    elif isinstance(data, list):
        for item in data:
            _assert_no_forbidden_keys(item, path)


# ---- structure ----


def test_examples_readme_exists():
    assert (EXAMPLES_DIR / "README.md").is_file()


def test_future_organic_models_readme_exists():
    assert (EXAMPLES_DIR / "future-organic-models" / "README.md").is_file()


@pytest.mark.parametrize("name", ALL_WORKING_EXAMPLES)
def test_working_example_has_required_local_files(name):
    root = EXAMPLES_DIR / name
    assert (root / "README.md").is_file()
    assert (root / "brief.json").is_file()
    assert (root / "part_manifest.json").is_file()
    cad_dir = root / "cad"
    cad_files = list(cad_dir.glob("*.scad")) + list(cad_dir.glob("*.py"))
    assert cad_files, f"{name} has no CAD source under cad/"
    assert (root / "preview_package" / "index.json").is_file()
    assert (root / "preview_package" / "preview_report.md").is_file()


def test_simple_nameplate_cad_source_is_the_named_file():
    assert (EXAMPLES_DIR / "simple-nameplate" / "cad" / "nameplate.scad").is_file()


def test_mechanical_plate_cad_source_is_the_named_file():
    assert (EXAMPLES_DIR / "mechanical-plate" / "cad" / "mechanical_plate.scad").is_file()


@pytest.mark.parametrize("name", ALL_WORKING_EXAMPLES)
def test_working_example_brief_is_valid_json_with_non_final_status(name):
    brief = project_store.load_json(EXAMPLES_DIR / name / "brief.json")
    assert brief["status"] not in ("human_approved", "print_ready")
    assert brief["required_human_approval"] is True


@pytest.mark.parametrize("name", ALL_WORKING_EXAMPLES)
def test_working_example_manifest_part_has_no_stl_on_disk(name):
    root = EXAMPLES_DIR / name
    manifest = project_store.load_json(root / "part_manifest.json")
    assert manifest["parts"], f"{name} part_manifest.json should list at least one part"
    for part in manifest["parts"]:
        mesh_path = root / part["file_path"]
        assert not mesh_path.exists(), (
            f"{name} should not ship a committed STL ({mesh_path}) - working examples stop at the CAD-source stage"
        )


# ---- multipart-classroom-sign specifics ----


def test_multipart_example_cad_files_are_named_as_expected():
    cad_dir = EXAMPLES_DIR / MULTIPART_EXAMPLE / "cad"
    for filename in ("base.scad", "text_layer.scad", "badge.scad"):
        assert (cad_dir / filename).is_file(), f"missing {filename}"


def test_multipart_example_cad_files_are_plain_text_source_only():
    cad_dir = EXAMPLES_DIR / MULTIPART_EXAMPLE / "cad"
    scad_files = list(cad_dir.glob("*.scad"))
    assert len(scad_files) == 3
    for path in scad_files:
        # Must decode cleanly as UTF-8 text (no binary CAD/mesh payload) and
        # contain no null bytes (a reliable indicator of a binary blob).
        raw = path.read_bytes()
        assert b"\x00" not in raw, f"{path} looks like a binary file, not OpenSCAD text source"
        text = raw.decode("utf-8")
        assert text.strip(), f"{path} is empty"
        assert "module" in text or "cube" in text or "cylinder" in text, f"{path} doesn't look like OpenSCAD source"


def test_multipart_example_manifest_has_multiple_parts_with_shared_origin():
    manifest = project_store.load_json(EXAMPLES_DIR / MULTIPART_EXAMPLE / "part_manifest.json")
    parts = manifest["parts"]
    assert len(parts) >= 3
    part_names = {p["part_name"] for p in parts}
    assert {"base_plate", "sign_text", "accent_badge"}.issubset(part_names)
    for part in parts:
        assert part["shared_origin"] is True, f"{part['part_name']} must declare shared_origin: true"
        assert part["transform_notes"], f"{part['part_name']} must document transform_notes"


def test_multipart_example_badge_is_optional():
    manifest = project_store.load_json(EXAMPLES_DIR / MULTIPART_EXAMPLE / "part_manifest.json")
    badge = next(p for p in manifest["parts"] if p["part_name"] == "accent_badge")
    assert badge["required_for_assembly"] is False


def test_multipart_example_preview_data_reports_multi_part_true():
    index = gather_preview_data(EXAMPLES_DIR / MULTIPART_EXAMPLE)
    assert index["multipart_state"]["multi_part"] is True
    assert index["multipart_state"]["part_count"] == 3
    assert len(index["cad_files"]) == 3
    assert index["mesh_files"] == []


# ---- storage-bin-lid specifics ----


def test_lid_example_cad_files_are_named_as_expected():
    cad_dir = EXAMPLES_DIR / LID_EXAMPLE / "cad"
    for filename in ("lid_panel.scad", "raised_label.scad", "pull_tab.scad"):
        assert (cad_dir / filename).is_file(), f"missing {filename}"


def test_lid_example_cad_files_are_plain_text_source_only():
    cad_dir = EXAMPLES_DIR / LID_EXAMPLE / "cad"
    scad_files = list(cad_dir.glob("*.scad"))
    assert len(scad_files) == 3
    for path in scad_files:
        # Must decode cleanly as UTF-8 text (no binary CAD/mesh payload) and
        # contain no null bytes (a reliable indicator of a binary blob).
        raw = path.read_bytes()
        assert b"\x00" not in raw, f"{path} looks like a binary file, not OpenSCAD text source"
        text = raw.decode("utf-8")
        assert text.strip(), f"{path} is empty"
        assert "module" in text or "cube" in text or "cylinder" in text, f"{path} doesn't look like OpenSCAD source"


def test_lid_example_manifest_has_multiple_parts_with_shared_origin():
    manifest = project_store.load_json(EXAMPLES_DIR / LID_EXAMPLE / "part_manifest.json")
    parts = manifest["parts"]
    assert len(parts) >= 3
    part_names = {p["part_name"] for p in parts}
    assert {"lid_panel", "raised_label_text", "pull_tab"}.issubset(part_names)
    for part in parts:
        assert part["shared_origin"] is True, f"{part['part_name']} must declare shared_origin: true"
        assert part["transform_notes"], f"{part['part_name']} must document transform_notes"


def test_lid_example_panel_is_required_but_label_and_tab_are_optional():
    manifest = project_store.load_json(EXAMPLES_DIR / LID_EXAMPLE / "part_manifest.json")
    parts_by_name = {p["part_name"]: p for p in manifest["parts"]}
    assert parts_by_name["lid_panel"]["required_for_assembly"] is True
    assert parts_by_name["raised_label_text"]["required_for_assembly"] is False
    assert parts_by_name["pull_tab"]["required_for_assembly"] is False


def test_lid_example_preview_data_reports_multi_part_true():
    index = gather_preview_data(EXAMPLES_DIR / LID_EXAMPLE)
    assert index["multipart_state"]["multi_part"] is True
    assert index["multipart_state"]["part_count"] == 3
    assert len(index["cad_files"]) == 3
    assert index["mesh_files"] == []


# ---- future concepts ----


@pytest.mark.parametrize("relative", CONCEPT_EXAMPLES)
def test_concept_example_is_marked_concept_only(relative):
    root = EXAMPLES_DIR / relative
    assert (root / "README.md").is_file()
    concept_brief_path = root / "concept_brief.json"
    assert concept_brief_path.is_file()
    concept_brief = project_store.load_json(concept_brief_path)
    assert concept_brief["status"] == "concept_only"
    assert concept_brief["not_printable"] is True
    assert concept_brief["not_generated"] is True


@pytest.mark.parametrize("relative", CONCEPT_EXAMPLES)
def test_concept_example_has_no_brief_json(relative):
    # Deliberate: a real brief.json would make preview-index/preview-project/
    # review-gate/preview-board treat this concept placeholder as a real,
    # in-progress project instead of a roadmap-only placeholder.
    assert not (EXAMPLES_DIR / relative / "brief.json").is_file()


@pytest.mark.parametrize("relative", CONCEPT_EXAMPLES)
def test_concept_example_has_no_generated_assets(relative):
    root = EXAMPLES_DIR / relative
    assert not any(root.rglob("*.stl"))
    assert not any(root.rglob("*.png"))
    assert not (root / "cad").exists()
    assert not (root / "part_manifest.json").exists()
    assert not (root / "preview_package").exists()


# ---- safety ----


def test_no_example_file_sets_human_approved_or_print_ready():
    for path in _iter_example_files():
        if path.suffix != ".json":
            continue
        data = project_store.load_json(path)
        _assert_no_forbidden_keys(data, path)


def test_no_example_contains_dotenv_files():
    for path in _iter_example_files():
        assert path.name != ".env", f"{path} looks like a real .env file - not allowed under examples/"
        assert path.suffix != ".env"


def test_no_example_file_contains_api_key_like_secrets():
    suspicious_markers = (
        "sk-ant-", "sk-proj-", "sk-live-", "AIzaSy",
        "MESHY_API_KEY=", "OPENAI_API_KEY=", "GEMINI_API_KEY=", "ANTHROPIC_API_KEY=",
    )
    for path in _iter_example_files():
        if path.suffix not in (".json", ".md", ".scad", ".py"):
            continue
        text = path.read_text(encoding="utf-8")
        for marker in suspicious_markers:
            assert marker not in text, f"{path} contains a suspicious secret-like marker: {marker!r}"


def test_no_example_claims_automatic_printing():
    forbidden_phrases = ("auto-print", "prints automatically", "automatically prints", "sends this to the printer")
    for path in _iter_example_files():
        if path.suffix not in (".json", ".md"):
            continue
        text = path.read_text(encoding="utf-8").lower()
        for phrase in forbidden_phrases:
            assert phrase not in text, f"{path} appears to claim automatic printing ({phrase!r})"


def test_no_example_ships_stl_or_png_files():
    # Working examples intentionally stop at the CAD-source stage; concept
    # examples never have generated assets at all (see above).
    assert not any(EXAMPLES_DIR.rglob("*.stl"))
    assert not any(EXAMPLES_DIR.rglob("*.png"))


# ---- integration with preview_package / project_inspection / review_gate ----


@pytest.mark.parametrize("name", ALL_WORKING_EXAMPLES)
def test_working_example_preview_data_reflects_cad_only_state(name):
    root = EXAMPLES_DIR / name
    index = gather_preview_data(root)
    assert index["cad_files"], f"{name} should have at least one CAD source file"
    assert index["mesh_files"] == []
    assert index["missing_visual_artifacts"]


@pytest.mark.parametrize("name", ALL_WORKING_EXAMPLES)
def test_working_example_summarize_project_needs_stl_export(name):
    summary = project_inspection.summarize_project(EXAMPLES_DIR / name)
    assert summary["brief_exists"] is True
    assert summary["visual_readiness_state"] == "needs_stl_export"


@pytest.mark.parametrize("name", ALL_WORKING_EXAMPLES)
def test_working_example_review_gate_fails_cleanly_without_stl(name):
    gate = evaluate_review_gate(EXAMPLES_DIR / name)
    assert gate["result"] == "fail"
    assert any(item["kind"] == "no_stl_files" for item in gate["blocking_items"])
    assert gate["status_ceiling"] == "slicer_review_ready"


@pytest.mark.parametrize("relative", CONCEPT_EXAMPLES)
def test_concept_example_summarize_project_reports_missing_brief(relative):
    summary = project_inspection.summarize_project(EXAMPLES_DIR / relative)
    assert summary["brief_exists"] is False
    assert summary["visual_readiness_state"] == "needs_brief"


@pytest.mark.parametrize("relative", CONCEPT_EXAMPLES)
def test_concept_example_review_gate_fails_and_is_not_printable_or_approved(relative):
    gate = evaluate_review_gate(EXAMPLES_DIR / relative)
    assert gate["result"] == "fail"
    assert gate["status_ceiling"] == "slicer_review_ready"


# ---- factory.examples_library ----


def test_list_examples_returns_every_registered_example_and_all_exist_on_disk():
    examples = list_examples()
    names = {e["name"] for e in examples}
    assert names == set(ALL_WORKING_EXAMPLES) | set(CONCEPT_EXAMPLES)
    for example in examples:
        assert example["exists"] is True, f"{example['name']} registry entry points at a missing path"


@pytest.mark.parametrize("name", WORKING_EXAMPLES)
def test_working_example_registry_entry_shape(name):
    example = get_example(name)
    assert example["type"] == "working"
    assert example["backend"] == "openscad"
    assert example["status"] == "slicer_review_ready_possible"
    assert example["safety_notes"]


@pytest.mark.parametrize("name", MULTIPART_EXAMPLES)
def test_multipart_example_registry_entry_shape(name):
    example = get_example(name)
    assert example["type"] == "working"
    assert example["backend"] == "openscad"
    assert example["status"] == "cad_generated"
    assert example["safety_notes"]
    assert any("multi-part" in note.lower() for note in example["safety_notes"])


@pytest.mark.parametrize("relative", CONCEPT_EXAMPLES)
def test_concept_example_registry_entry_shape(relative):
    example = get_example(relative)
    assert example["type"] == "future-concept"
    assert example["backend"] == "mixed"
    assert example["status"] == "concept_only"
    assert example["safety_notes"]


def test_get_example_unknown_name_raises():
    with pytest.raises(UnknownExampleError):
        get_example("does-not-exist")


# ---- CLI ----


def test_list_examples_cli_lists_every_registered_example():
    result = runner.invoke(app, ["list-examples"])
    assert result.exit_code == 0
    for name in ALL_WORKING_EXAMPLES + CONCEPT_EXAMPLES:
        assert name in result.stdout


def test_show_example_cli_working_example():
    result = runner.invoke(app, ["show-example", "simple-nameplate"])
    assert result.exit_code == 0
    assert "type: working" in result.stdout
    assert "backend: openscad" in result.stdout
    assert "review-gate examples/simple-nameplate" in result.stdout


@pytest.mark.parametrize("name", MULTIPART_EXAMPLES)
def test_show_example_cli_multipart_example(name):
    result = runner.invoke(app, ["show-example", name])
    assert result.exit_code == 0
    assert "type: working" in result.stdout
    assert "backend: openscad" in result.stdout
    assert "cad_generated" in result.stdout
    assert f"review-gate examples/{name}" in result.stdout


def test_show_example_cli_concept_example():
    result = runner.invoke(app, ["show-example", "future-organic-models/car-concept"])
    assert result.exit_code == 0
    assert "type: future-concept" in result.stdout
    assert "concept_only" in result.stdout
    # Concept examples don't get "try it" suggestions - they aren't working examples.
    assert "try it" not in result.stdout


def test_show_example_cli_unknown_name_fails_cleanly():
    result = runner.invoke(app, ["show-example", "does-not-exist"])
    assert result.exit_code == 1
    assert "error" in result.stdout.lower()


def test_status_cli_lists_examples_commands():
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "list-examples" in result.stdout
    assert "show-example" in result.stdout


@pytest.mark.parametrize("name", MULTIPART_EXAMPLES)
def test_review_gate_cli_fails_safely_for_multipart_example(name):
    result = runner.invoke(app, ["review-gate", f"examples/{name}"])
    assert result.exit_code == 1
    assert "No STL files exist yet" in result.stdout
    assert "NOT print-ready" in result.stdout


@pytest.mark.parametrize("name", MULTIPART_EXAMPLES)
def test_preview_project_cli_reports_multipart_state(name, tmp_path):
    # `preview-project` writes preview_package/{index.json,preview_report.md} -
    # run it against a tmp_path copy, never against the committed examples/
    # path directly, so this test can't leave the working tree dirty.
    example_copy = _copy_example_to(name, tmp_path)
    result = runner.invoke(app, ["preview-project", str(example_copy)])
    assert result.exit_code == 0
    assert "multi-part: True" in result.stdout


@pytest.mark.parametrize("name", MULTIPART_EXAMPLES)
def test_preview_project_cli_does_not_modify_committed_example_preview_files(name, tmp_path):
    before = _snapshot_preview_files(name)

    example_copy = _copy_example_to(name, tmp_path)
    result = runner.invoke(app, ["preview-project", str(example_copy)])
    assert result.exit_code == 0

    after = _snapshot_preview_files(name)
    assert before == after, (
        "factory preview-project must never write to the committed examples/ directory - "
        "run it against a tmp_path copy instead (see _copy_example_to())"
    )


# ---- preview-board across examples/ ----


def test_preview_board_discovers_multipart_examples_under_examples_root():
    project_dirs = discover_projects(EXAMPLES_DIR)
    names = {p.name for p in project_dirs}
    for name in MULTIPART_EXAMPLES:
        assert name in names


@pytest.mark.parametrize("name", MULTIPART_EXAMPLES)
def test_preview_board_gathers_multipart_example_without_crashing(name):
    board = gather_board_data(EXAMPLES_DIR)
    project = next(p for p in board["projects"] if p["slug"] == name)
    assert project["visual_readiness_state"] == "needs_stl_export"
    assert project["manifest_exists"] is True

import ast
import inspect
import re

import pytest
from typer.testing import CliRunner

from factory import future_cloud_tools, future_local_tools, project_store
from factory.cli import app
from factory.future_cloud_tools import get_future_cloud_tool
from factory.future_local_tools import (
    UnknownFutureLocalToolError,
    get_future_local_tool,
    list_future_local_tools,
    load_future_local_tools,
)

runner = CliRunner()

FORBIDDEN_JSON_KEYS = ("human_approved", "print_ready")

SUSPICIOUS_SECRET_MARKERS = (
    "sk-ant-", "sk-proj-", "sk-live-", "AIzaSy",
    "MESHY_API_KEY=", "OPENAI_API_KEY=", "GEMINI_API_KEY=", "ANTHROPIC_API_KEY=",
)

DISALLOWED_DEPENDENCY_MARKERS = ("bpy", "blender", "mcp", "meshy", "openai", "anthropic")

NEW_PHASE21_FILES = (
    "config/future_local_tools.json",
    "docs/blender-local-track.md",
    "src/factory/future_local_tools.py",
)


# ---- config exists and has the expected shape ----


def test_future_local_tools_config_exists():
    assert future_local_tools.FUTURE_LOCAL_TOOLS_PATH.is_file()


def test_future_local_tools_config_is_valid_json_with_blender_entry():
    config = load_future_local_tools()
    assert config["version"] == 1
    assert "blender" in config["tools"]


def test_blender_is_disabled_by_default():
    blender = get_future_local_tool("blender")
    assert blender["enabled"] is False
    assert blender["status"] == "future_track_required"


def test_blender_requires_explicit_human_approval():
    blender = get_future_local_tool("blender")
    assert blender["requires_explicit_human_approval"] is True


def test_blender_requires_local_path_review():
    blender = get_future_local_tool("blender")
    assert blender["requires_local_path_review"] is True


def test_blender_local_path_is_not_committed():
    blender = get_future_local_tool("blender")
    assert blender["local_blender_path"] is None


def test_blender_does_not_allow_automation_addons_or_mcp():
    blender = get_future_local_tool("blender")
    assert blender["allows_automation"] is False
    assert blender["allows_addons"] is False
    assert blender["allows_mcp"] is False


def test_blender_does_not_allow_printer_or_slicer_calls():
    blender = get_future_local_tool("blender")
    assert blender["allows_printer_or_slicer_calls"] is False


def test_blender_does_not_allow_background_execution_or_overwriting_meshes():
    blender = get_future_local_tool("blender")
    assert blender["allows_background_execution"] is False
    assert blender["allows_overwriting_original_meshes"] is False


def test_blender_does_not_allow_automatic_repair_acceptance_or_render_trust():
    blender = get_future_local_tool("blender")
    assert blender["allows_automatic_repair_acceptance"] is False
    assert blender["allows_automatic_render_trust"] is False


def test_blender_does_not_allow_automatic_print_readiness_or_approval():
    blender = get_future_local_tool("blender")
    assert blender["allows_automatic_print_readiness"] is False
    assert blender["allows_automatic_human_approved"] is False


def test_blender_requires_dry_run_and_provenance_and_before_after_checks():
    blender = get_future_local_tool("blender")
    assert blender["requires_dry_run_mode"] is True
    assert blender["requires_output_directory_isolation"] is True
    assert blender["requires_provenance_metadata"] is True
    assert blender["requires_before_after_validation"] is True
    assert blender["requires_before_after_render"] is True


def test_blender_notes_reference_the_track_doc():
    blender = get_future_local_tool("blender")
    assert any("blender-local-track.md" in note for note in blender["notes"])


def test_list_future_local_tools_includes_blender():
    tools = list_future_local_tools()
    tool_ids = {t["tool_id"] for t in tools}
    assert "blender" in tool_ids


def test_get_unknown_future_local_tool_raises():
    with pytest.raises(UnknownFutureLocalToolError):
        get_future_local_tool("does-not-exist")


def test_future_local_tools_config_has_no_path_shaped_or_key_shaped_fields():
    config = load_future_local_tools()
    blender = config["tools"]["blender"]
    for forbidden_field in ("api_key", "apiKey", "url", "endpoint", "secret", "token"):
        assert forbidden_field not in blender, f"config must not carry a {forbidden_field!r} field"
    # local_blender_path is the one path-shaped field, and it must be null.
    assert blender["local_blender_path"] is None


# ---- no forbidden keys / no secrets ----


def _assert_no_forbidden_keys(data, path):
    if isinstance(data, dict):
        for key in FORBIDDEN_JSON_KEYS:
            assert key not in data, f"{path} must not set {key!r}"
        for value in data.values():
            _assert_no_forbidden_keys(value, path)
    elif isinstance(data, list):
        for item in data:
            _assert_no_forbidden_keys(item, path)


def test_future_local_tools_config_sets_no_human_approved_or_print_ready():
    config = load_future_local_tools()
    _assert_no_forbidden_keys(config, future_local_tools.FUTURE_LOCAL_TOOLS_PATH)


@pytest.mark.parametrize("relative_path", NEW_PHASE21_FILES)
def test_phase21_files_contain_no_secret_like_markers(relative_path):
    path = project_store.REPO_ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    for marker in SUSPICIOUS_SECRET_MARKERS:
        assert marker not in text, f"{path} contains a suspicious secret-like marker: {marker!r}"


def test_no_real_env_file_exists():
    assert not (project_store.REPO_ROOT / ".env").is_file()


# ---- docs say not implemented / future-only ----


def test_blender_doc_exists():
    path = project_store.REPO_ROOT / "docs" / "blender-local-track.md"
    assert path.is_file()


def test_blender_doc_says_not_implemented_and_future_only():
    # Markdown source line-wraps prose, so normalize whitespace before
    # searching for a multi-word phrase that may span a line break.
    raw = (project_store.REPO_ROOT / "docs" / "blender-local-track.md").read_text(encoding="utf-8").lower()
    content = " ".join(raw.split())
    assert "does not implement blender automation" in content
    assert "no code in this repo launches blender" in content
    assert "future-only" in content


def test_no_doc_claims_blender_automation_is_implemented():
    forbidden_phrases = (
        "blender automation is implemented",
        "blender integration is complete",
        "blender is now automated",
        "blender is enabled",
    )
    doc_paths = (
        project_store.REPO_ROOT / "docs" / "roadmap.md",
        project_store.REPO_ROOT / "docs" / "blender-local-track.md",
        project_store.REPO_ROOT / "docs" / "cad-backends.md",
    )
    for path in doc_paths:
        content = path.read_text(encoding="utf-8").lower()
        for phrase in forbidden_phrases:
            assert phrase not in content, f"{path} appears to claim Blender automation is implemented ({phrase!r})"


# ---- future concept examples remain concept-only and reference the Blender track ----


CONCEPT_EXAMPLES = (
    "future-organic-models/car-concept",
    "future-organic-models/animal-concept",
    "future-organic-models/human-figure-study",
)


@pytest.mark.parametrize("relative", CONCEPT_EXAMPLES)
def test_concept_example_still_has_no_brief_json_or_generated_assets(relative):
    root = project_store.REPO_ROOT / "examples" / relative
    assert not (root / "brief.json").is_file()
    assert not any(root.rglob("*.stl"))
    assert not any(root.rglob("*.png"))
    assert not (root / "cad").exists()


@pytest.mark.parametrize("relative", CONCEPT_EXAMPLES)
def test_concept_example_still_marked_concept_only(relative):
    concept_brief = project_store.load_json(
        project_store.REPO_ROOT / "examples" / relative / "concept_brief.json"
    )
    assert concept_brief["status"] == "concept_only"
    assert concept_brief["not_printable"] is True
    assert concept_brief["not_generated"] is True


@pytest.mark.parametrize("relative", CONCEPT_EXAMPLES)
def test_concept_example_references_blender_local_track(relative):
    concept_brief = project_store.load_json(
        project_store.REPO_ROOT / "examples" / relative / "concept_brief.json"
    )
    assert concept_brief["blender_local_track_doc"] == "docs/blender-local-track.md"
    assert concept_brief["blender_gate_config"] == "config/future_local_tools.json"
    readme_text = (project_store.REPO_ROOT / "examples" / relative / "README.md").read_text(encoding="utf-8")
    assert "blender-local-track.md" in readme_text


# ---- no STL/PNG/binary assets added anywhere under examples/ ----


def test_examples_dir_still_has_no_stl_or_png_files():
    examples_dir = project_store.REPO_ROOT / "examples"
    assert not any(examples_dir.rglob("*.stl"))
    assert not any(examples_dir.rglob("*.png"))


# ---- no dependency/SDK added ----


def test_pyproject_has_no_blender_or_mcp_dependency():
    pyproject_text = (project_store.REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lowered = pyproject_text.lower()
    for marker in DISALLOWED_DEPENDENCY_MARKERS:
        assert marker not in lowered, f"pyproject.toml must not depend on {marker!r}"


# ---- factory.future_local_tools never touches subprocess/filesystem discovery/writes ----


FORBIDDEN_CALLS = (
    "import subprocess",
    "subprocess.run(",
    "subprocess.call(",
    "subprocess.Popen(",
    "subprocess.check_",
    "os.system(",
    "os.popen(",
    "Popen(",
    "socket.",
    "import urllib",
    "import requests",
    "http.client",
    "write_text(",
    "write_bytes(",
    "save_json(",
    "shutil.which(",
    "os.walk(",
)


def test_future_local_tools_module_has_no_subprocess_or_filesystem_discovery():
    source = inspect.getsource(future_local_tools)
    for forbidden_term in FORBIDDEN_CALLS:
        assert forbidden_term not in source, (
            f"factory.future_local_tools must stay local and read-only; found {forbidden_term!r}"
        )


def test_future_local_tools_module_only_reads_json():
    tree = ast.parse(inspect.getsource(future_local_tools))
    source = ast.unparse(tree)
    assert "load_json" in source
    assert "open(" not in source  # delegates to project_store.load_json; no raw file I/O of its own
    assert "requests" not in source
    assert "urllib" not in source


def test_no_blender_execution_code_anywhere_in_src():
    # Repo-wide scan (not just future_local_tools.py): no module may import
    # bpy (Blender's Python API), shell out to a "blender" binary, or
    # reference MCP configuration.
    src_dir = project_store.REPO_ROOT / "src"
    forbidden_patterns = ("import bpy", "from bpy", "subprocess.run([\"blender", "subprocess.Popen([\"blender", "mcp.json", "mcp_config")
    for path in src_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in forbidden_patterns:
            assert pattern not in text, f"{path} contains forbidden Blender/MCP execution pattern: {pattern!r}"


# ---- CLI ----


def test_check_local_tools_cli_reports_blender_disabled():
    result = runner.invoke(app, ["check-local-tools"])
    assert result.exit_code == 0
    assert "blender" in result.stdout
    assert "disabled" in result.stdout.lower()
    assert "future_track_required" in result.stdout


def test_check_local_tools_cli_never_claims_to_launch_or_search():
    result = runner.invoke(app, ["check-local-tools"])
    assert result.exit_code == 0
    assert "did not launch a" in result.stdout
    assert "tool" in result.stdout


def test_status_cli_lists_check_local_tools_command():
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "check-local-tools" in result.stdout


# ---- cross-checks: Meshy gate still disabled/future-only ----


def test_meshy_gate_still_disabled_after_blender_track_added():
    meshy = get_future_cloud_tool("meshy")
    assert meshy["enabled"] is False
    assert meshy["status"] == "future_gate_required"


def test_future_cloud_tools_config_unaffected_by_local_tools_addition():
    assert future_cloud_tools.FUTURE_CLOUD_TOOLS_PATH.is_file()
    config = future_cloud_tools.load_future_cloud_tools()
    assert "meshy" in config["tools"]


# ---- cross-check: phase registry remains sequential/gap-free ----


def test_phase_registry_still_sequential_with_no_gaps():
    content = (project_store.REPO_ROOT / "docs" / "phase-registry.md").read_text(encoding="utf-8")
    numbers = [int(n) for n in re.findall(r"^\|\s*(\d+)\s*\|", content, re.MULTILINE)]
    assert numbers, "expected at least one purely-numeric phase row"
    assert numbers == list(range(numbers[0], numbers[0] + len(numbers))), (
        f"phase-registry.md numbered rows have a gap or duplicate: {numbers}"
    )


def test_phase_registry_includes_phase_21():
    content = (project_store.REPO_ROOT / "docs" / "phase-registry.md").read_text(encoding="utf-8")
    assert re.search(r"^\|\s*21\s*\|", content, re.MULTILINE)

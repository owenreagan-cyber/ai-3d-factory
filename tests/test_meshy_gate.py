import ast
import inspect

import pytest
from typer.testing import CliRunner

from factory import future_cloud_tools, project_store
from factory.cli import app
from factory.future_cloud_tools import (
    UnknownFutureCloudToolError,
    get_future_cloud_tool,
    list_future_cloud_tools,
    load_future_cloud_tools,
)

runner = CliRunner()

FORBIDDEN_JSON_KEYS = ("human_approved", "print_ready")

SUSPICIOUS_SECRET_MARKERS = (
    "sk-ant-", "sk-proj-", "sk-live-", "AIzaSy",
    "MESHY_API_KEY=", "OPENAI_API_KEY=", "GEMINI_API_KEY=", "ANTHROPIC_API_KEY=",
)

DISALLOWED_DEPENDENCY_MARKERS = ("meshy", "openai", "anthropic", "google-generativeai", "google-genai")

NEW_PHASE16_FILES = (
    "config/future_cloud_tools.json",
    "docs/meshy-approval-gate.md",
    "src/factory/future_cloud_tools.py",
)


# ---- config exists and has the expected shape ----


def test_future_cloud_tools_config_exists():
    assert future_cloud_tools.FUTURE_CLOUD_TOOLS_PATH.is_file()


def test_future_cloud_tools_config_is_valid_json_with_meshy_entry():
    config = load_future_cloud_tools()
    assert config["version"] == 1
    assert "meshy" in config["tools"]


def test_meshy_is_disabled_by_default():
    meshy = get_future_cloud_tool("meshy")
    assert meshy["enabled"] is False
    assert meshy["status"] == "future_gate_required"


def test_meshy_requires_explicit_human_approval():
    meshy = get_future_cloud_tool("meshy")
    assert meshy["requires_explicit_human_approval"] is True


def test_meshy_requires_cost_cap():
    meshy = get_future_cloud_tool("meshy")
    assert meshy["requires_cost_cap"] is True


def test_meshy_requires_per_run_confirmation():
    meshy = get_future_cloud_tool("meshy")
    assert meshy["requires_per_run_confirmation"] is True


def test_meshy_requires_input_and_output_review():
    meshy = get_future_cloud_tool("meshy")
    assert meshy["requires_input_review_before_upload"] is True
    assert meshy["requires_output_review_after_generation"] is True


def test_meshy_does_not_allow_uploads_or_api_calls():
    meshy = get_future_cloud_tool("meshy")
    assert meshy["allows_uploads"] is False
    assert meshy["allows_api_calls"] is False


def test_meshy_does_not_allow_automatic_generation_or_acceptance():
    meshy = get_future_cloud_tool("meshy")
    assert meshy["allows_automatic_generation"] is False
    assert meshy["allows_automatic_mesh_acceptance"] is False


def test_meshy_does_not_allow_automatic_print_readiness_or_approval():
    meshy = get_future_cloud_tool("meshy")
    assert meshy["allows_automatic_print_readiness"] is False
    assert meshy["allows_automatic_human_approved"] is False


def test_meshy_has_a_local_only_fallback():
    meshy = get_future_cloud_tool("meshy")
    assert meshy["fallback_if_unavailable_or_over_budget"]
    assert "local" in meshy["fallback_if_unavailable_or_over_budget"].lower()


def test_meshy_notes_reference_the_gate_doc():
    meshy = get_future_cloud_tool("meshy")
    assert any("meshy-approval-gate.md" in note for note in meshy["notes"])


def test_list_future_cloud_tools_includes_meshy():
    tools = list_future_cloud_tools()
    tool_ids = {t["tool_id"] for t in tools}
    assert "meshy" in tool_ids


def test_get_unknown_future_cloud_tool_raises():
    with pytest.raises(UnknownFutureCloudToolError):
        get_future_cloud_tool("does-not-exist")


def test_future_cloud_tools_config_has_no_urls_or_key_shaped_fields():
    config = load_future_cloud_tools()
    meshy = config["tools"]["meshy"]
    for forbidden_field in ("api_key", "apiKey", "url", "endpoint", "secret", "token"):
        assert forbidden_field not in meshy, f"config must not carry a {forbidden_field!r} field"


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


def test_future_cloud_tools_config_sets_no_human_approved_or_print_ready():
    config = load_future_cloud_tools()
    _assert_no_forbidden_keys(config, future_cloud_tools.FUTURE_CLOUD_TOOLS_PATH)


@pytest.mark.parametrize("relative_path", NEW_PHASE16_FILES)
def test_phase16_files_contain_no_secret_like_markers(relative_path):
    path = project_store.REPO_ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    for marker in SUSPICIOUS_SECRET_MARKERS:
        assert marker not in text, f"{path} contains a suspicious secret-like marker: {marker!r}"


def test_no_real_env_file_exists():
    assert not (project_store.REPO_ROOT / ".env").is_file()


# ---- future concept examples remain concept-only and reference the gate ----


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
def test_concept_example_references_meshy_approval_gate(relative):
    concept_brief = project_store.load_json(
        project_store.REPO_ROOT / "examples" / relative / "concept_brief.json"
    )
    assert concept_brief["meshy_approval_gate_doc"] == "docs/meshy-approval-gate.md"
    assert concept_brief["meshy_gate_config"] == "config/future_cloud_tools.json"
    readme_text = (project_store.REPO_ROOT / "examples" / relative / "README.md").read_text(encoding="utf-8")
    assert "meshy-approval-gate.md" in readme_text


# ---- no STL/PNG/binary assets added anywhere under examples/ ----


def test_examples_dir_still_has_no_stl_or_png_files():
    examples_dir = project_store.REPO_ROOT / "examples"
    assert not any(examples_dir.rglob("*.stl"))
    assert not any(examples_dir.rglob("*.png"))


# ---- no dependency/SDK added ----


def test_pyproject_has_no_meshy_or_llm_api_dependency():
    pyproject_text = (project_store.REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lowered = pyproject_text.lower()
    for marker in DISALLOWED_DEPENDENCY_MARKERS:
        assert marker not in lowered, f"pyproject.toml must not depend on {marker!r}"


# ---- factory.future_cloud_tools never touches network/subprocess/filesystem writes ----


FORBIDDEN_CALLS = (
    "import subprocess",
    "subprocess.",
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
)


def test_future_cloud_tools_module_has_no_network_or_process_access():
    source = inspect.getsource(future_cloud_tools)
    for forbidden_term in FORBIDDEN_CALLS:
        assert forbidden_term not in source, (
            f"factory.future_cloud_tools must stay local and read-only; found {forbidden_term!r}"
        )


def test_future_cloud_tools_module_has_no_actual_dotenv_file_access():
    # Distinct from the forbidden-call scan above: this checks for real file
    # access to a .env path (os.environ, getenv, an open/Path call on
    # ".env"), not just the substring ".env" - which also appears
    # legitimately in this module's own docstring explaining that it never
    # reads .env.
    source = inspect.getsource(future_cloud_tools)
    for forbidden_term in ("os.environ", "getenv(", 'open(".env"', "Path(\".env\")", "load_dotenv"):
        assert forbidden_term not in source, f"factory.future_cloud_tools must never access .env; found {forbidden_term!r}"


def test_future_cloud_tools_module_only_reads_json():
    tree = ast.parse(inspect.getsource(future_cloud_tools))
    source = ast.unparse(tree)
    assert "load_json" in source
    assert "open(" not in source  # delegates to project_store.load_json; no raw file I/O of its own
    assert "requests" not in source
    assert "urllib" not in source


# ---- CLI ----


def test_check_future_tools_cli_reports_meshy_disabled():
    result = runner.invoke(app, ["check-future-tools"])
    assert result.exit_code == 0
    assert "meshy" in result.stdout
    assert "disabled" in result.stdout.lower()
    assert "future_gate_required" in result.stdout


def test_check_future_tools_cli_never_claims_network_contact():
    result = runner.invoke(app, ["check-future-tools"])
    assert result.exit_code == 0
    # Checked as two substrings (not one long phrase) because rich word-wraps
    # console output at the terminal width, which can split a long sentence
    # across a line boundary between "any" and "network".
    assert "did not contact any" in result.stdout
    assert "network" in result.stdout


def test_status_cli_lists_check_future_tools_command():
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "check-future-tools" in result.stdout

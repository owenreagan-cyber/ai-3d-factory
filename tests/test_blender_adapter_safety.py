"""Phase 45 safety tests: static/AST inspection proving the Blender
execution gate + adapter stay inside their safety contract.

Covers: no GUI-driving mechanism anywhere in the new modules, no network
import anywhere (including the fixture script), the fixture script's own
import/write-surface constraints, bounded-subprocess argument shape (list,
`shell=False`, timeout), and that exactly one Factory-owned script is ever
passed to `--python`. See docs/blender-adapter.md.
"""

from __future__ import annotations

import ast
import inspect

from factory import blender_adapter, blender_gate, project_store

_NEW_MODULE_SOURCE_PATHS = (
    project_store.REPO_ROOT / "src" / "factory" / "blender_gate.py",
    project_store.REPO_ROOT / "src" / "factory" / "blender_adapter.py",
)


# Actual call shapes, never bare words - the modules' own docstrings
# legitimately *name* osascript/AppleScript/pkill/open in backtick-quoted
# markdown prose to explain why none of them is ever used (mirrors
# tests/test_blender_gate.py's precise-call-shape convention, e.g.
# `subprocess.run(["blender` rather than the bare word "blender").
_FORBIDDEN_DESKTOP_AUTOMATION_PATTERNS = (
    "os.system(",
    "os.popen(",
    "subprocess.Popen(",
    '"osascript"',
    "'osascript'",
    '"pkill"',
    "'pkill'",
    '["open"',
    "['open'",
)

_FORBIDDEN_NETWORK_PATTERNS = (
    "import socket",
    "import requests",
    "import urllib",
    "http.client",
)


# ---------------------------------------------------------------------------
# No GUI-driving mechanism, no network import, anywhere in the new modules
# ---------------------------------------------------------------------------


def test_no_desktop_automation_in_new_modules():
    for path in _NEW_MODULE_SOURCE_PATHS:
        text = path.read_text(encoding="utf-8")
        for pattern in _FORBIDDEN_DESKTOP_AUTOMATION_PATTERNS:
            assert pattern not in text, f"{path} contains forbidden desktop-automation pattern: {pattern!r}"


def test_no_network_import_in_new_modules():
    for path in _NEW_MODULE_SOURCE_PATHS:
        text = path.read_text(encoding="utf-8")
        for pattern in _FORBIDDEN_NETWORK_PATTERNS:
            assert pattern not in text, f"{path} contains forbidden network pattern: {pattern!r}"


def test_no_addon_install_or_homebrew_mutation():
    for path in _NEW_MODULE_SOURCE_PATHS:
        text = path.read_text(encoding="utf-8")
        for pattern in ("--addons", "brew install", "brew upgrade", "brew update", "pip install"):
            assert pattern not in text, f"{path} contains forbidden install/mutation pattern: {pattern!r}"


def test_offline_mode_flag_present_in_adapter():
    text = (project_store.REPO_ROOT / "src" / "factory" / "blender_adapter.py").read_text(encoding="utf-8")
    assert "--offline-mode" in text


def test_factory_startup_flag_present_in_adapter():
    text = (project_store.REPO_ROOT / "src" / "factory" / "blender_adapter.py").read_text(encoding="utf-8")
    assert "--factory-startup" in text


def test_background_flag_present_in_adapter():
    text = (project_store.REPO_ROOT / "src" / "factory" / "blender_adapter.py").read_text(encoding="utf-8")
    assert "--background" in text


# ---------------------------------------------------------------------------
# Bounded-subprocess shape: real invocations always shell=False, always a
# hard timeout, always an argument list (dynamic - proven via monkeypatch,
# not just a source-text guess).
# ---------------------------------------------------------------------------


def test_every_real_subprocess_call_is_shell_false_with_timeout(monkeypatch):
    calls = []

    def _fake_run(command, **kwargs):
        calls.append((command, kwargs))

        class _Result:
            returncode = 0
            stdout = "Blender 5.2.0 LTS"
            stderr = ""

        return _Result()

    monkeypatch.setattr(blender_adapter.subprocess, "run", _fake_run)
    blender_adapter.verify_headless_runtime("/fake/blender")
    blender_adapter.run_fixture_qualification("/fake/blender")

    assert calls, "expected at least one subprocess.run call"
    for command, kwargs in calls:
        assert isinstance(command, list), "command must be an argument list, never a shell string"
        assert all(isinstance(arg, str) for arg in command)
        assert kwargs.get("shell", False) is False
        assert "timeout" in kwargs and kwargs["timeout"] is not None


def test_no_command_is_ever_a_shell_string():
    for func_source in (inspect.getsource(blender_adapter.verify_headless_runtime), inspect.getsource(blender_adapter.run_fixture_qualification)):
        assert "shell=True" not in func_source


# ---------------------------------------------------------------------------
# Exactly one Factory-owned script is ever passed to --python - no command
# in this repo accepts a user/project-supplied script path.
# ---------------------------------------------------------------------------


def test_only_the_factory_owned_fixture_script_is_ever_passed_to_python_flag():
    adapter_source = (project_store.REPO_ROOT / "src" / "factory" / "blender_adapter.py").read_text(encoding="utf-8")
    # The only literal path ever built for --python is blender_gate.FIXTURE_SCRIPT_PATH.
    assert "blender_gate.FIXTURE_SCRIPT_PATH" in adapter_source
    # No CLI option or function parameter anywhere accepts an arbitrary script path.
    for module in (blender_adapter, blender_gate):
        source = inspect.getsource(module)
        assert "script_path" not in source
        assert "user_script" not in source


def test_fixture_script_path_is_a_fixed_module_constant():
    assert blender_gate.FIXTURE_SCRIPT_PATH.is_file()
    assert blender_gate.FIXTURE_SCRIPT_PATH.name == "factory_qualification_fixture.py"


# ---------------------------------------------------------------------------
# The fixture script itself: statically parsed (AST, not just a substring
# scan) for forbidden imports/calls and confirmed to write only to its
# single given output path.
# ---------------------------------------------------------------------------

_FORBIDDEN_FIXTURE_IMPORT_MODULES = {"subprocess", "socket", "requests", "urllib", "os"}


def test_fixture_script_imports_only_bpy_and_sys():
    tree = ast.parse(blender_gate.FIXTURE_SCRIPT_PATH.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])
    assert imported_modules == {"bpy", "sys"}, f"unexpected imports: {imported_modules}"
    assert imported_modules.isdisjoint(_FORBIDDEN_FIXTURE_IMPORT_MODULES)


def test_fixture_script_never_calls_os_system_or_shell_commands():
    text = blender_gate.FIXTURE_SCRIPT_PATH.read_text(encoding="utf-8")
    for forbidden in ("os.system(", "subprocess.", "socket.", "urlopen(", "shell=True"):
        assert forbidden not in text


def test_fixture_script_has_exactly_one_output_write_call():
    text = blender_gate.FIXTURE_SCRIPT_PATH.read_text(encoding="utf-8")
    assert text.count("bpy.ops.wm.stl_export(") == 1
    assert "output_path" in text


def test_fixture_script_never_reads_any_hardcoded_external_path():
    tree = ast.parse(blender_gate.FIXTURE_SCRIPT_PATH.read_text(encoding="utf-8"))
    string_constants = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    suspicious_paths = [s for s in string_constants if s.startswith("/") or s.startswith("~")]
    assert suspicious_paths == [], f"fixture script contains a hardcoded absolute/home path: {suspicious_paths}"

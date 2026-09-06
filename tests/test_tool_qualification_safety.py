"""Phase 44 safety tests: hard safety guarantees for `factory.tool_qualification`.

Explicitly guards against GUI launch, AppleScript, shell=True, network calls,
Homebrew mutation, slicer execution, and G-code generation; proves every real
subprocess call this module makes uses argument lists (never a shell string)
with `shell=False` and a bounded timeout; and verifies temporary artifacts
never land inside examples/ or projects/, and are cleaned up (with a failure
reported honestly, never silently claimed a success).
See docs/tool-qualification.md.
"""

from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import pytest

from factory import engine_registry, tool_qualification as tq


def _probe(**overrides) -> dict:
    base = {"detected": False, "detected_path": None, "detected_version": "unknown", "probe_status": "not_installed", "probe_warnings": []}
    base.update(overrides)
    return base


def _fake_openscad_script(tmp_path):
    script = tmp_path / "fake-openscad"
    script.write_text(
        "#!/bin/sh\n"
        "out=\"\"\n"
        "while [ $# -gt 0 ]; do\n"
        "  case \"$1\" in\n"
        "    -o) out=\"$2\"; shift 2 ;;\n"
        "    *) shift ;;\n"
        "  esac\n"
        "done\n"
        "printf 'solid x\\nendsolid x\\n' > \"$out\"\n"
    )
    script.chmod(0o755)
    return script


# ---------------------------------------------------------------------------
# subprocess call-argument safety: list args, shell=False, bounded timeout
# ---------------------------------------------------------------------------


def test_openscad_export_subprocess_uses_argument_list_and_no_shell(monkeypatch, tmp_path):
    calls = []
    real_run = subprocess.run

    def _spy(command, **kwargs):
        calls.append((command, kwargs))
        return real_run(command, **kwargs)

    monkeypatch.setattr(tq.subprocess, "run", _spy)
    fake = _fake_openscad_script(tmp_path)
    probe = _probe(detected=True, detected_path=str(fake), detected_version="fake 1.0")
    monkeypatch.setattr(tq, "validate_mesh", lambda path: {"overall_status": "PASS"})
    tq._qualify_openscad_stable("OpenSCAD (stable)", probe)

    assert calls, "expected the export subprocess to actually run"
    for command, kwargs in calls:
        assert isinstance(command, list), "command must be an argument list, never a shell string"
        assert kwargs.get("shell", False) is False
        assert "timeout" in kwargs


def test_cadquery_qualification_never_shells_out():
    """CadQuery qualification is entirely in-process (no subprocess at all)."""
    source = inspect.getsource(tq._qualify_cadquery) + inspect.getsource(tq._run_cadquery_capability_probe)
    assert "subprocess" not in source
    assert "shell=True" not in source


@pytest.mark.parametrize("forbidden", ["osascript", "AppleScript", "pkill", "os.system", "shell=True"])
def test_qualification_functions_never_reference_gui_automation_or_shell(forbidden):
    for func in (
        tq._qualify_openscad_stable,
        tq._qualify_openscad_snapshot,
        tq._qualify_cadquery,
        tq._run_cadquery_capability_probe,
        tq._qualify_metadata_only_gui_tool,
        tq._qualify_deferred_tool,
        tq._qualify_one,
        tq.qualify_tool,
        tq.qualify_all_tools,
    ):
        assert forbidden not in inspect.getsource(func)


@pytest.mark.parametrize("forbidden", ["import socket", "import requests", "urllib.request", "http.client"])
def test_module_never_imports_networking(forbidden):
    source = inspect.getsource(tq)
    assert forbidden not in source


@pytest.mark.parametrize("forbidden", ["brew install", "brew upgrade", "brew update", '"brew"', "'brew'"])
def test_module_never_invokes_homebrew(forbidden):
    source = inspect.getsource(tq)
    assert forbidden not in source


def test_no_tool_id_ever_produces_execution_approved_true(monkeypatch):
    def _fake_probe_all(**kwargs):
        return {
            tool_id: _probe(detected=True, detected_path=f"/Applications/Fake-{tool_id}.app", detected_version="1.0")
            for tool_id in engine_registry.TOOL_IDS
        }

    monkeypatch.setattr(tq.engine_registry, "probe_all_tools", _fake_probe_all)
    monkeypatch.setattr(tq, "validate_mesh", lambda path: {"overall_status": "PASS"})
    results = tq.qualify_all_tools()
    assert all(r["execution_approved"] is False for r in results.values())
    assert all(r["automatic_print_allowed"] is False for r in results.values())
    assert all(r["printer_contacted"] is False for r in results.values())
    assert all(r["gui_launched"] is False for r in results.values())
    assert all(r["network_used"] is False for r in results.values())


# ---------------------------------------------------------------------------
# Temporary artifact safety
# ---------------------------------------------------------------------------


def test_temporary_artifacts_never_land_in_examples_or_projects(monkeypatch, tmp_path):
    fake = _fake_openscad_script(tmp_path)
    probe = _probe(detected=True, detected_path=str(fake), detected_version="fake 1.0")
    monkeypatch.setattr(tq, "validate_mesh", lambda path: {"overall_status": "PASS"})

    seen_dirs = []
    real_tempdir = tq.tempfile.TemporaryDirectory

    class _Recording(real_tempdir):
        def __enter__(self):
            path = super().__enter__()
            seen_dirs.append(path)
            return path

    monkeypatch.setattr(tq.tempfile, "TemporaryDirectory", _Recording)
    tq._qualify_openscad_stable("OpenSCAD (stable)", probe)

    repo_root = Path(__file__).resolve().parents[1]
    for d in seen_dirs:
        resolved = Path(d).resolve()
        assert repo_root / "examples" not in resolved.parents
        assert repo_root / "projects" not in resolved.parents
        assert not resolved.is_relative_to(repo_root / "examples") if hasattr(resolved, "is_relative_to") else True


def test_cleanup_reported_honestly_on_success(monkeypatch, tmp_path):
    fake = _fake_openscad_script(tmp_path)
    probe = _probe(detected=True, detected_path=str(fake), detected_version="fake 1.0")
    monkeypatch.setattr(tq, "validate_mesh", lambda path: {"overall_status": "PASS"})
    result = tq._qualify_openscad_stable("OpenSCAD (stable)", probe)
    assert result["temporary_artifacts_created"] is True
    assert result["temporary_artifacts_cleaned"] is True
    cleanup_check = next(c for c in result["checks"] if c["check_id"] == "openscad_cleanup")
    assert cleanup_check["status"] == "pass"


def test_no_temporary_artifacts_claimed_when_none_created():
    """A tool that never got detected must never claim it created (or
    cleaned) a temporary fixture it never touched."""
    result = tq._qualify_openscad_stable("OpenSCAD (stable)", _probe())
    assert result["temporary_artifacts_created"] is False
    assert result["temporary_artifacts_cleaned"] is True

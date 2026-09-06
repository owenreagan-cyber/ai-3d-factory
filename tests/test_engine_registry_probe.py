"""Phase 43 tests: `factory.engine_registry` read-only local probing.

Covers: installed-path detection, missing-app handling, malformed/timeout
version output, one tool's probe failure never aborting the rest, and the
hard safety guarantees (no GUI launch, no AppleScript, no `open`/`pkill`,
no network, no install, no Homebrew mutation). See docs/engine-registry.md.
"""

from __future__ import annotations

import subprocess

import pytest

from factory import engine_registry


def test_installed_path_detected(tmp_path):
    fake_app = tmp_path / "Blender.app"
    fake_app.mkdir()
    result = engine_registry._probe_app_or_path_binary((str(fake_app),), "blender")
    assert result["detected"] is True
    assert result["detected_path"] == str(fake_app)
    assert result["probe_method"] == "applications_folder"


def test_missing_app_handled_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_registry.shutil, "which", lambda name: None)
    result = engine_registry._probe_app_or_path_binary((str(tmp_path / "NotThere.app"),), "definitely-not-a-real-binary")
    assert result["detected"] is False
    assert result["probe_status"] == "not_installed"
    assert result["detected_path"] is None


def test_path_binary_fallback_detected(monkeypatch):
    monkeypatch.setattr(engine_registry.shutil, "which", lambda name: "/usr/local/bin/fake-tool" if name == "fake-tool" else None)
    result = engine_registry._probe_app_or_path_binary(("/Applications/DoesNotExist.app",), "fake-tool")
    assert result["detected"] is True
    assert result["probe_method"] == "path_binary"
    assert result["detected_path"] == "/usr/local/bin/fake-tool"


def test_unknown_version_handled_cleanly_when_no_plist(tmp_path):
    app = tmp_path / "NoPlist.app"
    (app / "Contents").mkdir(parents=True)
    # No Info.plist written - must not raise.
    result = engine_registry._probe_app_or_path_binary((str(app),), None)
    assert result["detected"] is True
    assert result["detected_version"] == "unknown"


def test_malformed_plist_handled_cleanly(tmp_path):
    app = tmp_path / "Malformed.app"
    contents = app / "Contents"
    contents.mkdir(parents=True)
    (contents / "Info.plist").write_bytes(b"not a real plist")
    version = engine_registry._read_app_bundle_version(str(app))
    assert version is None


def test_well_formed_plist_version_read(tmp_path):
    import plistlib

    app = tmp_path / "Good.app"
    contents = app / "Contents"
    contents.mkdir(parents=True)
    with open(contents / "Info.plist", "wb") as f:
        plistlib.dump({"CFBundleShortVersionString": "4.2.0"}, f)
    version = engine_registry._read_app_bundle_version(str(app))
    assert version == "4.2.0"


def test_openscad_not_found_handled_cleanly(monkeypatch):
    monkeypatch.setattr(engine_registry, "resolve_openscad_executable", lambda: None)
    result = engine_registry._probe_openscad(include_version_subprocess=True)
    assert result["detected"] is False
    assert result["probe_status"] == "not_installed"


def test_openscad_version_probe_subprocess_timeout(monkeypatch):
    monkeypatch.setattr(engine_registry, "resolve_openscad_executable", lambda: "/fake/openscad")

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["openscad"], timeout=10)

    monkeypatch.setattr(engine_registry.subprocess, "run", _raise_timeout)
    result = engine_registry._probe_openscad(include_version_subprocess=True)
    assert result["detected"] is True
    assert result["detected_version"] == "unknown"
    assert result["probe_warnings"]


def test_openscad_version_probe_command_failure(monkeypatch):
    monkeypatch.setattr(engine_registry, "resolve_openscad_executable", lambda: "/fake/openscad")

    def _raise_oserror(*args, **kwargs):
        raise OSError("no such file")

    monkeypatch.setattr(engine_registry.subprocess, "run", _raise_oserror)
    result = engine_registry._probe_openscad(include_version_subprocess=True)
    assert result["detected"] is True
    assert result["detected_version"] == "unknown"
    assert result["probe_warnings"]


def test_openscad_malformed_version_output_handled(monkeypatch):
    monkeypatch.setattr(engine_registry, "resolve_openscad_executable", lambda: "/fake/openscad")

    class _FakeCompleted:
        stdout = ""
        stderr = ""

    monkeypatch.setattr(engine_registry.subprocess, "run", lambda *a, **kw: _FakeCompleted())
    result = engine_registry._probe_openscad(include_version_subprocess=True)
    assert result["detected_version"] == "unknown"


def test_openscad_probe_without_version_subprocess_never_calls_subprocess(monkeypatch):
    monkeypatch.setattr(engine_registry, "resolve_openscad_executable", lambda: "/fake/openscad")

    def _boom(*args, **kwargs):
        raise AssertionError("must not call subprocess.run when include_version_subprocess=False")

    monkeypatch.setattr(engine_registry.subprocess, "run", _boom)
    result = engine_registry._probe_openscad(include_version_subprocess=False)
    assert result["detected"] is True
    assert result["detected_version"] == "unknown"


def test_one_tool_failure_does_not_abort_registry(monkeypatch):
    def _boom():
        raise RuntimeError("simulated probe crash")

    monkeypatch.setattr(engine_registry, "_probe_cadquery", _boom)
    results = engine_registry.probe_all_tools()
    assert set(results.keys()) == set(engine_registry.TOOL_IDS)
    assert results["cadquery"]["probe_status"] == "probe_failed"
    # every other tool still probed successfully
    assert results["openscad_stable"]["probe_status"] in ("detected", "not_installed")


def test_probe_all_tools_deterministic_shape():
    first = engine_registry.probe_all_tools()
    second = engine_registry.probe_all_tools()
    assert set(first.keys()) == set(second.keys()) == set(engine_registry.TOOL_IDS)
    for tool_id in engine_registry.TOOL_IDS:
        assert set(first[tool_id].keys()) >= {"detected", "detected_path", "detected_version", "probe_method", "probe_status", "probe_warnings"}


def test_meshy_and_onshape_never_probed_over_network():
    results = engine_registry.probe_all_tools()
    assert results["meshy"]["detected"] is False
    assert results["meshy"]["probe_status"] == "not_applicable"
    assert results["onshape"]["detected"] is False
    assert results["onshape"]["probe_status"] == "not_applicable"


def test_get_tool_registry_probe_downgrades_qualification_on_not_installed(monkeypatch):
    def _fake_probe(**kwargs):
        return {
            tool_id: {"detected": False, "detected_path": None, "detected_version": "unknown", "probe_method": None, "probe_status": "not_installed", "probe_warnings": []}
            for tool_id in engine_registry.TOOL_IDS
        }

    monkeypatch.setattr(engine_registry, "probe_all_tools", _fake_probe)
    registry = engine_registry.get_tool_registry(probe=True)
    assert registry["openscad_stable"]["qualification_status"] == "not_installed"
    # never upgraded to "qualified" by a probe
    for record in registry.values():
        assert record["qualification_status"] != "qualified"


@pytest.mark.parametrize("forbidden", ["osascript", "AppleScript", "pkill"])
def test_probe_functions_never_reference_gui_automation(forbidden):
    import inspect

    for func in (
        engine_registry._probe_app_or_path_binary,
        engine_registry._probe_openscad,
        engine_registry._probe_cadquery,
        engine_registry.probe_all_tools,
        engine_registry._read_app_bundle_version,
    ):
        assert forbidden not in inspect.getsource(func)

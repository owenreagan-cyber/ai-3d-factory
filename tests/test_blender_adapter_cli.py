"""Phase 45 CLI tests: `factory blender inspect` / `factory blender qualify
[--confirm-fixture] [--json] [--verbose]`.

Monkeypatches `factory.engine_registry.probe_all_tools()` so these tests
are deterministic regardless of whether Blender happens to be installed
on the machine running them - mirroring how `tests/test_tool_qualification_cli.py`
already isolates Phase 44's CLI tests from the local environment.
See docs/blender-adapter.md.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from factory import blender_gate
from factory.cli import app

runner = CliRunner()


def _probe_not_detected(**kw):
    return {"blender": {"detected": False, "detected_path": None, "detected_version": "unknown", "probe_warnings": []}}


def _probe_detected_no_binary(tmp_path):
    bundle = tmp_path / "Blender.app"
    bundle.mkdir()

    def _probe(**kw):
        return {"blender": {"detected": True, "detected_path": str(bundle), "detected_version": "5.2.0", "probe_warnings": []}}

    return _probe


def _probe_detected_with_binary(tmp_path, *, exit_code=0, output="Blender 5.2.0 LTS"):
    bundle = tmp_path / "Blender.app"
    binary_dir = bundle / "Contents" / "MacOS"
    binary_dir.mkdir(parents=True)
    binary = binary_dir / "Blender"
    binary.write_text(f"#!/bin/sh\necho '{output}'\nexit {exit_code}\n")
    binary.chmod(0o755)

    def _probe(**kw):
        return {"blender": {"detected": True, "detected_path": str(bundle), "detected_version": "5.2.0", "probe_warnings": []}}

    return _probe


# ---------------------------------------------------------------------------
# factory blender inspect
# ---------------------------------------------------------------------------


def test_inspect_reports_not_detected(monkeypatch):
    monkeypatch.setattr(blender_gate.engine_registry, "probe_all_tools", _probe_not_detected)
    result = runner.invoke(app, ["blender", "inspect"])
    assert result.exit_code == 0
    assert "Detected: No" in result.stdout
    assert "did not" not in result.stdout  # this command has its own trailer, not the generic one


def test_inspect_json_parses_cleanly(monkeypatch):
    monkeypatch.setattr(blender_gate.engine_registry, "probe_all_tools", _probe_not_detected)
    result = runner.invoke(app, ["blender", "inspect", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["project_execution_approved"] is False
    assert len(data["gate_checklist"]) == 15


def test_inspect_never_calls_subprocess(monkeypatch, tmp_path):
    calls = []

    def _fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("factory blender inspect must never call subprocess")

    monkeypatch.setattr(blender_gate.engine_registry, "probe_all_tools", _probe_detected_with_binary(tmp_path))
    import factory.blender_adapter as ba

    monkeypatch.setattr(ba.subprocess, "run", _fake_run)
    result = runner.invoke(app, ["blender", "inspect"])
    assert result.exit_code == 0
    assert calls == []


# ---------------------------------------------------------------------------
# factory blender qualify (default - no --confirm-fixture)
# ---------------------------------------------------------------------------


def test_qualify_default_shows_expected_human_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(blender_gate.engine_registry, "probe_all_tools", _probe_detected_with_binary(tmp_path))
    result = runner.invoke(app, ["blender", "qualify"])
    assert result.exit_code == 0
    assert "BLENDER EXECUTION GATE" in result.stdout
    assert "Headless runtime:" in result.stdout
    assert "Fixture execution:" in result.stdout
    assert "Not Run" in result.stdout
    assert "Execution approval:" in result.stdout
    assert "No" in result.stdout


def test_qualify_default_never_touches_temp_fixture(monkeypatch, tmp_path):
    monkeypatch.setattr(blender_gate.engine_registry, "probe_all_tools", _probe_detected_with_binary(tmp_path))
    result = runner.invoke(app, ["blender", "qualify", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["qualification"]["fixture_execution_status"] == "not_run"
    assert data["qualification"]["temporary_artifacts_created"] is False


def test_qualify_json_is_clean_and_deterministic_shape(monkeypatch, tmp_path):
    monkeypatch.setattr(blender_gate.engine_registry, "probe_all_tools", _probe_detected_with_binary(tmp_path))
    result = runner.invoke(app, ["blender", "qualify", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert set(data.keys()) == {"blender_adapter_version", "gate", "qualification", "project_execution_approved", "safety"}
    assert data["project_execution_approved"] is False
    assert data["safety"]["automatic_print_allowed"] is False


def test_qualify_not_detected(monkeypatch):
    monkeypatch.setattr(blender_gate.engine_registry, "probe_all_tools", _probe_not_detected)
    result = runner.invoke(app, ["blender", "qualify"])
    assert result.exit_code == 0
    assert "Detected:" in result.stdout
    assert "No" in result.stdout


def test_qualify_verbose_shows_checks_and_checklist(monkeypatch, tmp_path):
    monkeypatch.setattr(blender_gate.engine_registry, "probe_all_tools", _probe_detected_with_binary(tmp_path))
    result = runner.invoke(app, ["blender", "qualify", "--verbose"])
    assert result.exit_code == 0
    assert "Checks:" in result.stdout
    assert "Gate checklist:" in result.stdout


# ---------------------------------------------------------------------------
# factory blender qualify --confirm-fixture
# ---------------------------------------------------------------------------


def _fake_binary_with_fixture_support(tmp_path):
    """A fake Blender binary that answers both `--version` and the fixture
    `--python <script> -- <out>` invocation, writing a minimal STL."""
    bundle = tmp_path / "Blender.app"
    binary_dir = bundle / "Contents" / "MacOS"
    binary_dir.mkdir(parents=True)
    binary = binary_dir / "Blender"
    binary.write_text(
        "#!/bin/sh\n"
        "if echo \"$@\" | grep -q -- '--version'; then echo 'Blender 5.2.0 LTS'; exit 0; fi\n"
        "out=\"\"\nfound=0\n"
        "for arg in \"$@\"; do\n"
        "  if [ \"$found\" = \"1\" ]; then out=\"$arg\"; break; fi\n"
        "  if [ \"$arg\" = \"--\" ]; then found=1; fi\n"
        "done\n"
        "printf 'solid x\\nfacet normal 0 0 1\\nouter loop\\nvertex 0 0 0\\nvertex 1 0 0\\nvertex 0 1 0\\nendloop\\nendfacet\\nendsolid x\\n' > \"$out\"\n"
        "exit 0\n"
    )
    binary.chmod(0o755)

    def _probe(**kw):
        return {"blender": {"detected": True, "detected_path": str(bundle), "detected_version": "5.2.0", "probe_warnings": []}}

    return _probe


def test_confirm_fixture_runs_full_pipeline(monkeypatch, tmp_path):
    monkeypatch.setattr(blender_gate.engine_registry, "probe_all_tools", _fake_binary_with_fixture_support(tmp_path))
    result = runner.invoke(app, ["blender", "qualify", "--confirm-fixture", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["qualification"]["fixture_execution_status"] == "succeeded"
    assert data["qualification"]["adapter_qualification_status"] == "qualified"
    assert data["project_execution_approved"] is False


def test_confirm_fixture_human_output_never_claims_approval(monkeypatch, tmp_path):
    monkeypatch.setattr(blender_gate.engine_registry, "probe_all_tools", _fake_binary_with_fixture_support(tmp_path))
    result = runner.invoke(app, ["blender", "qualify", "--confirm-fixture"])
    assert result.exit_code == 0
    # rich wraps long lines, so normalize whitespace before searching for a
    # multi-word phrase that may span a line break (same convention as
    # tests/test_blender_gate.py's doc-content checks).
    normalized = " ".join(result.stdout.split())
    assert "Execution approval:" in normalized
    assert "No slicer was contacted" in normalized
    assert "No print was started" in normalized


def test_help_text_available_for_blender_group():
    result = runner.invoke(app, ["blender", "--help"])
    assert result.exit_code == 0
    assert "inspect" in result.stdout
    assert "qualify" in result.stdout


def test_status_cli_lists_blender_commands():
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "blender inspect" in result.stdout
    assert "blender qualify" in result.stdout

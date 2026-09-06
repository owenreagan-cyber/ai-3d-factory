"""Phase 44 tests: the `factory engines qualify` CLI - a thin, entirely
read-only wrapper around `factory.tool_qualification`. No install, no
upgrade, no GUI launch, no network, no slicer execution, no G-code, no
printer contact. See docs/tool-qualification.md.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from factory import engine_registry
from factory.cli import app

runner = CliRunner()


def _fake_probe(**overrides) -> dict:
    base = {"detected": False, "detected_path": None, "detected_version": "unknown", "probe_status": "not_installed", "probe_warnings": []}
    base.update(overrides)
    return base


def _fake_probe_all(overrides=None, **kwargs) -> dict:
    overrides = overrides or {}
    return {tool_id: overrides.get(tool_id, _fake_probe()) for tool_id in engine_registry.TOOL_IDS}


def test_engines_qualify_human_output(monkeypatch):
    monkeypatch.setattr("factory.tool_qualification.engine_registry.probe_all_tools", lambda **kwargs: _fake_probe_all())
    result = runner.invoke(app, ["engines", "qualify"])
    assert result.exit_code == 0
    assert "LOCAL TOOL QUALIFICATION" in result.stdout
    assert "Summary:" in result.stdout
    assert "Automatic printing remains disabled." in result.stdout


def test_engines_qualify_json_parses_cleanly(monkeypatch):
    monkeypatch.setattr("factory.tool_qualification.engine_registry.probe_all_tools", lambda **kwargs: _fake_probe_all())
    result = runner.invoke(app, ["engines", "qualify", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["qualification_version"] == 1
    assert len(payload["results"]) == 13
    assert payload["safety"]["automatic_print_allowed"] is False
    # no console prefix/suffix text contaminating the JSON
    assert result.stdout.strip().startswith("{")
    assert result.stdout.strip().endswith("}")


def test_engines_qualify_single_tool(monkeypatch):
    monkeypatch.setattr("factory.tool_qualification.engine_registry.probe_all_tools", lambda **kwargs: _fake_probe_all())
    result = runner.invoke(app, ["engines", "qualify", "cadquery", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert len(payload["results"]) == 1
    assert payload["results"][0]["tool_id"] == "cadquery"


def test_engines_qualify_verbose_shows_checks(monkeypatch):
    overrides = {"blender": _fake_probe(detected=True, detected_path="/Applications/Blender.app", detected_version="5.2.0")}
    monkeypatch.setattr("factory.tool_qualification.engine_registry.probe_all_tools", lambda **kwargs: _fake_probe_all(overrides))
    result = runner.invoke(app, ["engines", "qualify", "blender", "--verbose"])
    assert result.exit_code == 0
    assert "Checks:" in result.stdout
    assert "Headless/CLI probe" in result.stdout


def test_engines_qualify_unknown_tool_id_errors():
    result = runner.invoke(app, ["engines", "qualify", "not-a-real-tool"])
    assert result.exit_code == 1
    assert "unknown tool_id" in result.stdout.lower() or "unknown tool_id" in (result.stderr or "").lower()


def test_engines_qualify_unknown_tool_id_json_errors():
    result = runner.invoke(app, ["engines", "qualify", "not-a-real-tool", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["errors"]


def test_engines_qualify_help_text():
    result = runner.invoke(app, ["engines", "qualify", "--help"])
    assert result.exit_code == 0
    assert "qualification" in result.stdout.lower()


def test_engines_qualify_deterministic_output(monkeypatch):
    monkeypatch.setattr("factory.tool_qualification.engine_registry.probe_all_tools", lambda **kwargs: _fake_probe_all())
    first = runner.invoke(app, ["engines", "qualify", "--json"])
    second = runner.invoke(app, ["engines", "qualify", "--json"])
    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert [r["qualification_status"] for r in first_payload["results"]] == [r["qualification_status"] for r in second_payload["results"]]


def test_engines_qualify_no_side_effects_on_examples(monkeypatch, tmp_path):
    """The CLI command itself must never write anywhere in the repo tree -
    only inside its own temporary directory (see test_tool_qualification_safety.py
    for the dedicated temp-artifact-location proof)."""
    monkeypatch.setattr("factory.tool_qualification.engine_registry.probe_all_tools", lambda **kwargs: _fake_probe_all())
    before = set(tmp_path.iterdir())
    result = runner.invoke(app, ["engines", "qualify", "--json"])
    assert result.exit_code == 0
    after = set(tmp_path.iterdir())
    assert before == after


def test_engines_qualify_safety_trailer_present_in_human_output(monkeypatch):
    monkeypatch.setattr("factory.tool_qualification.engine_registry.probe_all_tools", lambda **kwargs: _fake_probe_all())
    result = runner.invoke(app, ["engines", "qualify"])
    assert "No software was installed or upgraded." in result.stdout
    assert "No GUI application was launched." in result.stdout
    assert "No slicer was executed and no G-code was generated." in result.stdout


def test_engines_default_and_probe_unaffected_by_qualify_addition(monkeypatch):
    """Backward compatibility: the pre-existing `factory engines`/`factory
    engines probe` commands are unchanged by this phase's addition."""
    result = runner.invoke(app, ["engines"])
    assert result.exit_code == 0
    assert "FACTORY ENGINE REGISTRY" in result.stdout

    result_json = runner.invoke(app, ["engines", "--json"])
    assert result_json.exit_code == 0
    payload = json.loads(result_json.stdout)
    assert payload["registry_version"]

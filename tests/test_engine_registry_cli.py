"""Phase 43 tests: the `factory engines`/`factory engines probe` CLI - a
thin, read-only wrapper around `factory.engine_registry`. See
docs/engine-registry.md, docs/roadmap.md Phase 43.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from factory.cli import app

runner = CliRunner()


def test_engines_default_human_output():
    result = runner.invoke(app, ["engines"])
    assert result.exit_code == 0
    assert "FACTORY ENGINE REGISTRY" in result.stdout
    assert "OpenSCAD (stable)" in result.stdout
    assert "Meshy" in result.stdout
    assert "Bambu Studio" in result.stdout
    assert "No tools were installed, upgraded, launched, or executed." in result.stdout
    assert "Automatic printing remains disabled." in result.stdout


def test_engines_default_does_not_show_detected_field():
    """The default (unprobed) view must not claim a detection result it
    never computed."""
    result = runner.invoke(app, ["engines"])
    assert result.exit_code == 0
    assert "Detected:" not in result.stdout


def test_engines_json_clean_and_parses():
    result = runner.invoke(app, ["engines", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert set(data.keys()) == {"registry_version", "categories", "tools", "summary", "safety"}
    assert len(data["tools"]) == 13
    assert data["safety"]["automatic_print_allowed"] is False


def test_engines_json_has_no_console_prefix_or_suffix_text():
    result = runner.invoke(app, ["engines", "--json"])
    assert result.exit_code == 0
    # The entire stdout must be exactly one JSON document - no banner text
    # before or after it.
    json.loads(result.stdout)


def test_engines_json_never_probed_by_default():
    result = runner.invoke(app, ["engines", "--json"])
    data = json.loads(result.stdout)
    for record in data["tools"].values():
        assert record["detected"] is False
        assert record["probe_status"] == "not_probed"


def test_engines_probe_human_output():
    result = runner.invoke(app, ["engines", "probe"])
    assert result.exit_code == 0
    assert "FACTORY ENGINE REGISTRY" in result.stdout
    assert "Detected:" in result.stdout
    assert "No tools were installed, upgraded, launched, or executed." in result.stdout


def test_engines_probe_json_clean_and_parses():
    result = runner.invoke(app, ["engines", "probe", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert len(data["tools"]) == 13
    assert "summary" in data
    for record in data["tools"].values():
        assert isinstance(record["detected"], bool)


def test_engines_help_text():
    result = runner.invoke(app, ["engines", "--help"])
    assert result.exit_code == 0
    assert "Engine Registry" in result.stdout
    assert "Never installs" in result.stdout or "never installs" in result.stdout.lower()


def test_engines_probe_help_text():
    result = runner.invoke(app, ["engines", "probe", "--help"])
    assert result.exit_code == 0
    assert "read-only" in result.stdout.lower()


def test_engines_unknown_subcommand_handled_cleanly():
    result = runner.invoke(app, ["engines", "not-a-real-subcommand"])
    assert result.exit_code != 0


def test_engines_deterministic_registry_output_across_calls():
    first = runner.invoke(app, ["engines", "--json"])
    second = runner.invoke(app, ["engines", "--json"])
    assert first.exit_code == second.exit_code == 0
    data_first = json.loads(first.stdout)
    data_second = json.loads(second.stdout)
    assert data_first == data_second


def test_engines_appears_in_available_commands_list():
    from factory.cli import AVAILABLE_COMMANDS

    assert any(cmd.startswith("engines ") or cmd == "engines" for cmd in AVAILABLE_COMMANDS)


def test_engines_safety_trailer_present_in_probe_mode_too():
    result = runner.invoke(app, ["engines", "probe"])
    assert "No slicer was run." in result.stdout
    assert "No G-code was created." in result.stdout
    assert "No printer was contacted." in result.stdout

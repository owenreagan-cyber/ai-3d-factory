"""Phase 49 CLI tests: `factory blender-adapt plan` / `factory
blender-adapt execute`. Kept as its own Typer group, separate from
`factory workflow` (which stays planning-only per Phase 48's own
documented invariant).
"""

from __future__ import annotations

import json
import textwrap

import pytest
from typer.testing import CliRunner

from factory import blender_gate, project_store
from factory.cli import app, blender_adapt_app

runner = CliRunner()

_MINIMAL_STL = (
    "solid t\n"
    "facet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\n"
    "facet normal 0 0 -1\nouter loop\nvertex 0 0 0\nvertex 0 1 0\nvertex 1 0 0\nendloop\nendfacet\n"
    "endsolid t\n"
)


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture()
def meshy_project(isolated_projects_dir):
    root = project_store.init_project("Piggy Bank")
    artifact_dir = root / "generated" / "meshy" / "processed"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / "01a07ca5.stl"
    artifact_path.write_text(_MINIMAL_STL)
    return root, artifact_path


def _resolved_binary(path):
    return {"detected": True, "app_bundle_path": str(path), "binary_path": str(path), "detected_version": "5.2.0 LTS", "warnings": []}


def _fake_blender_full_success(tmp_path):
    script = tmp_path / "fake-blender"
    script.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            case " $* " in
              *" --version "*)
                if ! echo "$*" | grep -q -- "--python"; then
                  echo 'Blender 5.2.0 LTS'
                  exit 0
                fi
                ;;
            esac
            python_script=""
            prev=""
            after_sep=0
            args_after=""
            for arg in "$@"; do
              if [ "$prev" = "--python" ]; then
                python_script="$arg"
              fi
              if [ "$after_sep" = "1" ]; then
                args_after="$args_after|$arg"
              fi
              if [ "$arg" = "--" ]; then
                after_sep=1
              fi
              prev="$arg"
            done
            stl_body='solid x
            facet normal 0 0 1
            outer loop
            vertex 0 0 0
            vertex 1 0 0
            vertex 0 1 0
            endloop
            endfacet
            endsolid x'
            case "$python_script" in
              *factory_qualification_fixture.py)
                out=$(echo "$args_after" | cut -d'|' -f2)
                printf '%s\\n' "$stl_body" > "$out"
                exit 0
                ;;
              *factory_organic_cleanup_workflow.py)
                out=$(echo "$args_after" | cut -d'|' -f3)
                printf '%s\\n' "$stl_body" > "$out"
                exit 0
                ;;
            esac
            exit 1
            """
        )
    )
    script.chmod(0o755)
    return script


def test_blender_adapt_plan_json(meshy_project):
    _, artifact_path = meshy_project
    result = runner.invoke(app, ["blender-adapt", "plan", str(artifact_path), "--target-max-mm", "150", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["plan"]["workflow_type"] == "organic_cleanup_workflow"
    assert payload["plan"]["automatic_execution_allowed"] is False
    assert all(v is False for v in payload["safety"].values())


def test_blender_adapt_plan_human_readable(meshy_project):
    _, artifact_path = meshy_project
    result = runner.invoke(app, ["blender-adapt", "plan", str(artifact_path)])
    assert result.exit_code == 0
    assert "BLENDER ADAPTATION PLAN" in result.stdout
    assert "Automatic printing remains impossible" in result.stdout


def test_blender_adapt_execute_blocked_without_confirm(meshy_project):
    _, artifact_path = meshy_project
    result = runner.invoke(app, ["blender-adapt", "execute", str(artifact_path), "--target-max-mm", "150", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["result"]["organic_cleanup_status"] == "blocked"


def test_blender_adapt_execute_succeeds_with_confirm(meshy_project, monkeypatch, tmp_path):
    project_dir, artifact_path = meshy_project
    monkeypatch.setattr(blender_gate, "resolve_blender_binary", lambda: _resolved_binary(_fake_blender_full_success(tmp_path)))

    result = runner.invoke(
        app, ["blender-adapt", "execute", str(artifact_path), "--target-max-mm", "150", "--confirm", "--json"]
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["result"]["organic_cleanup_status"] == "succeeded"
    assert (project_dir / "generated" / "blender_adaptation_receipt.json").is_file()


def test_blender_adapt_execute_human_readable_succeeds(meshy_project, monkeypatch, tmp_path):
    _, artifact_path = meshy_project
    monkeypatch.setattr(blender_gate, "resolve_blender_binary", lambda: _resolved_binary(_fake_blender_full_success(tmp_path)))

    result = runner.invoke(app, ["blender-adapt", "execute", str(artifact_path), "--target-max-mm", "150", "--confirm"])
    assert result.exit_code == 0
    assert "BLENDER ADAPTATION EXECUTION" in result.stdout
    assert "Automatic printing remains impossible" in result.stdout


def test_blender_adapt_execute_requires_target_max_mm():
    result = runner.invoke(app, ["blender-adapt", "execute", "some.stl", "--confirm"])
    assert result.exit_code != 0


def test_no_run_script_style_command_exists():
    """No arbitrary-execution interface - every command name is a fixed,
    narrow verb."""
    registered = {c.name for c in blender_adapt_app.registered_commands}
    assert registered == {"plan", "execute"}


def test_top_level_help_lists_blender_adapt_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "blender-adapt" in result.stdout

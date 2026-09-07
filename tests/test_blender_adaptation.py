"""Phase 49 tests: `factory.blender_adaptation` - plan generation, scale-
factor computation, the execution gate (fresh fixture-qualification
proof + explicit confirmation), receipt writing, and artifact lineage.
Uses the same "fake shell script standing in for the real Blender binary"
convention `tests/test_blender_adapter.py`/`tests/test_tool_qualification_openscad.py`
already established - never depends on Blender actually being installed.
See docs/blender-adaptation.md.
"""

from __future__ import annotations

import textwrap

import pytest

from factory import blender_adaptation, blender_gate, project_store

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
    receipt = {
        "meshy_task_id": "01a07ca5-0c06-7459-b1f4-68f383774fae",
        "mock_execution": False, "live_api_used": True, "ai_model": "meshy-7",
        "validation_status": "WARN", "preview_status": "PASS",
        "output_artifact_paths": [str(artifact_path)],
    }
    project_store.save_json(root / "generated" / "meshy_receipt.json", receipt)
    return root, artifact_path


def _fake_blender_no_binary_functionality(tmp_path):
    """Never used to actually run - only its path matters for
    resolve_blender_binary() to report `detected: True`."""
    script = tmp_path / "fake-blender"
    script.write_text("#!/bin/sh\nexit 1\n")
    script.chmod(0o755)
    return script


def _resolved_binary(path):
    return {"detected": True, "app_bundle_path": str(path), "binary_path": str(path), "detected_version": "5.2.0 LTS", "warnings": []}


def _not_detected():
    return {"detected": False, "app_bundle_path": None, "binary_path": None, "detected_version": "unknown", "warnings": []}


def _fake_blender_full_success(tmp_path):
    """Handles all three real invocation shapes this repo ever makes:
    `--version`, `--python .../factory_qualification_fixture.py -- <out>`,
    and `--python .../factory_organic_cleanup_workflow.py -- <in> <out> <factor>`.
    """
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
            echo 'unrecognized invocation' 1>&2
            exit 1
            """
        )
    )
    script.chmod(0o755)
    return script


# ---------------------------------------------------------------------------
# build_adaptation_execution_plan() - pure, read-only
# ---------------------------------------------------------------------------


def test_plan_reports_no_project_when_artifact_outside_projects_dir(tmp_path):
    artifact = tmp_path / "loose.stl"
    artifact.write_text(_MINIMAL_STL)
    plan = blender_adaptation.build_adaptation_execution_plan(artifact)
    assert plan["project"] is None
    assert plan["output_artifact"] is None
    assert plan["execution_allowed"] is False
    assert any("project directory" in issue for issue in plan["issues_found"])


def test_plan_computes_output_artifact_path(meshy_project):
    project_dir, artifact_path = meshy_project
    plan = blender_adaptation.build_adaptation_execution_plan(artifact_path, target_max_dimension_mm=150.0)
    assert plan["project"] == str(project_dir)
    assert plan["output_artifact"] == str(project_dir / "generated" / "blender" / "adapted" / "01a07ca5_adapted.stl")
    assert plan["source_engine"] == "meshy"
    assert plan["workflow_type"] == "organic_cleanup_workflow"
    assert plan["adaptation_operations"] == ["import_stl", "apply_scale_factor", "export_stl"]
    assert plan["requires_human_confirmation"] is True
    assert plan["automatic_execution_allowed"] is False
    assert plan["no_automatic_print"] is True


def test_plan_computes_proposed_scale_factor(meshy_project):
    project_dir, artifact_path = meshy_project
    plan = blender_adaptation.build_adaptation_execution_plan(artifact_path, target_max_dimension_mm=150.0)
    current = plan["current_dimensions_mm"]
    if current:
        largest = max(current.values())
        assert plan["proposed_scale_factor"] == round(150.0 / largest, 6)


def test_plan_without_target_dimension_has_no_scale_factor(meshy_project):
    _, artifact_path = meshy_project
    plan = blender_adaptation.build_adaptation_execution_plan(artifact_path)
    assert plan["proposed_scale_factor"] is None
    assert plan["target_dimensions"]["target_max_dimension_mm"] is None


def test_plan_blocked_when_output_already_exists(meshy_project, monkeypatch, tmp_path):
    project_dir, artifact_path = meshy_project
    monkeypatch.setattr(blender_gate, "resolve_blender_binary", lambda: _resolved_binary(_fake_blender_no_binary_functionality(tmp_path)))
    output_path = project_dir / "generated" / "blender" / "adapted" / "01a07ca5_adapted.stl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_MINIMAL_STL)
    plan = blender_adaptation.build_adaptation_execution_plan(artifact_path, target_max_dimension_mm=150.0)
    assert plan["execution_allowed"] is False
    assert any("overwrite" in b for b in plan["blockers"])


def test_plan_reports_blender_not_detected(meshy_project, monkeypatch):
    _, artifact_path = meshy_project
    monkeypatch.setattr(blender_gate, "resolve_blender_binary", _not_detected)
    plan = blender_adaptation.build_adaptation_execution_plan(artifact_path, target_max_dimension_mm=150.0)
    assert plan["blender_gate_status"] == "not_detected"
    assert plan["execution_allowed"] is False


def test_plan_never_writes_anything(meshy_project):
    project_dir, artifact_path = meshy_project
    files_before = sorted(p.relative_to(project_dir) for p in project_dir.rglob("*") if p.is_file())
    blender_adaptation.build_adaptation_execution_plan(artifact_path, target_max_dimension_mm=150.0)
    files_after = sorted(p.relative_to(project_dir) for p in project_dir.rglob("*") if p.is_file())
    assert files_before == files_after


# ---------------------------------------------------------------------------
# run_organic_cleanup_workflow() - the gated execution path
# ---------------------------------------------------------------------------


def test_execute_blocked_without_confirm(meshy_project, monkeypatch, tmp_path):
    _, artifact_path = meshy_project
    monkeypatch.setattr(blender_gate, "resolve_blender_binary", lambda: _resolved_binary(_fake_blender_full_success(tmp_path)))
    result = blender_adaptation.run_organic_cleanup_workflow(artifact_path, target_max_dimension_mm=150.0, confirm=False)
    assert result["organic_cleanup_status"] == "blocked"
    assert result["receipt"] is None
    assert result["human_confirmed"] is False


def test_execute_blocked_when_plan_has_issues(meshy_project, monkeypatch, tmp_path):
    _, artifact_path = meshy_project
    monkeypatch.setattr(blender_gate, "resolve_blender_binary", _not_detected)
    result = blender_adaptation.run_organic_cleanup_workflow(artifact_path, target_max_dimension_mm=150.0, confirm=True)
    assert result["organic_cleanup_status"] == "blocked"


def test_execute_succeeds_end_to_end(meshy_project, monkeypatch, tmp_path):
    project_dir, artifact_path = meshy_project
    monkeypatch.setattr(blender_gate, "resolve_blender_binary", lambda: _resolved_binary(_fake_blender_full_success(tmp_path)))

    result = blender_adaptation.run_organic_cleanup_workflow(
        artifact_path, target_max_dimension_mm=150.0, confirm=True, confirmed_by="owen"
    )

    assert result["organic_cleanup_status"] == "succeeded"
    assert result["output_artifact"] is not None
    output_path = project_dir / "generated" / "blender" / "adapted" / "01a07ca5_adapted.stl"
    assert output_path.is_file()

    receipt_path = project_dir / "generated" / "blender_adaptation_receipt.json"
    assert receipt_path.is_file()
    receipt = project_store.load_json(receipt_path)
    assert receipt["workflow"] == "organic_cleanup_workflow"
    assert receipt["confirmed_by"] == "owen"
    assert receipt["single_shot_human_confirmation"] is True
    assert receipt["project_execution_approved"] is False
    assert receipt["automatic_print_allowed"] is False
    assert receipt["no_automatic_print"] is True
    assert receipt["input_hash"].startswith("sha256:")
    assert receipt["output_hash"].startswith("sha256:")

    # original input artifact must never be modified
    assert artifact_path.read_text() == _MINIMAL_STL


def test_execute_never_overwrites_original_artifact(meshy_project, monkeypatch, tmp_path):
    project_dir, artifact_path = meshy_project
    monkeypatch.setattr(blender_gate, "resolve_blender_binary", lambda: _resolved_binary(_fake_blender_full_success(tmp_path)))
    before = artifact_path.read_bytes()
    blender_adaptation.run_organic_cleanup_workflow(artifact_path, target_max_dimension_mm=150.0, confirm=True)
    after = artifact_path.read_bytes()
    assert before == after


def test_execute_refuses_to_overwrite_existing_receipt(meshy_project, monkeypatch, tmp_path):
    project_dir, artifact_path = meshy_project
    monkeypatch.setattr(blender_gate, "resolve_blender_binary", lambda: _resolved_binary(_fake_blender_full_success(tmp_path)))
    receipt_path = project_dir / "generated" / "blender_adaptation_receipt.json"
    project_store.save_json(receipt_path, {"pre_existing": True})

    result = blender_adaptation.run_organic_cleanup_workflow(artifact_path, target_max_dimension_mm=150.0, confirm=True)
    assert result["organic_cleanup_status"] == "failed"
    # the pre-existing receipt content must be untouched
    assert project_store.load_json(receipt_path) == {"pre_existing": True}


def test_execute_blocked_when_fixture_qualification_fails(meshy_project, monkeypatch, tmp_path):
    _, artifact_path = meshy_project

    def _fake_broken_binary(tmp_path):
        script = tmp_path / "fake-blender"
        script.write_text("#!/bin/sh\necho 'boom' 1>&2\nexit 1\n")
        script.chmod(0o755)
        return script

    monkeypatch.setattr(blender_gate, "resolve_blender_binary", lambda: _resolved_binary(_fake_broken_binary(tmp_path)))
    result = blender_adaptation.run_organic_cleanup_workflow(artifact_path, target_max_dimension_mm=150.0, confirm=True)
    assert result["organic_cleanup_status"] == "blocked"
    assert result["fixture_qualification"] is not None
    assert result["fixture_qualification"]["adapter_qualification_status"] != "qualified"


def test_read_blender_adaptation_receipt_none_before_execution(meshy_project):
    project_dir, _ = meshy_project
    assert blender_adaptation.read_blender_adaptation_receipt(project_dir) is None


def test_summarize_blender_adaptation_before_and_after(meshy_project, monkeypatch, tmp_path):
    project_dir, artifact_path = meshy_project
    summary_before = blender_adaptation.summarize_blender_adaptation(project_dir)
    assert summary_before["adaptation_available"] is False

    monkeypatch.setattr(blender_gate, "resolve_blender_binary", lambda: _resolved_binary(_fake_blender_full_success(tmp_path)))
    blender_adaptation.run_organic_cleanup_workflow(artifact_path, target_max_dimension_mm=150.0, confirm=True)

    summary_after = blender_adaptation.summarize_blender_adaptation(project_dir)
    assert summary_after["adaptation_available"] is True
    assert summary_after["workflow"] == "organic_cleanup_workflow"


def test_build_safety_block_is_all_false():
    block = blender_adaptation.build_safety_block()
    assert all(value is False for value in block.values())

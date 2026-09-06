"""Phase 45 tests: `factory.blender_adapter` - the only module in this
repo that ever passes Blender to `subprocess`.

Uses a small fake shell-script standing in for the real Blender binary
(the same convention `tests/test_tool_qualification_openscad.py` already
established for OpenSCAD) so these tests never depend on Blender actually
being installed. Covers: headless runtime verification (success/timeout/
nonzero-exit), the full fixture pipeline (success, failure at each stage,
unexpected-file detection, cleanup verification), and that
`project_execution_approved`/`execution_approved`-shaped fields stay
`False` regardless of outcome. See docs/blender-adapter.md.
"""

from __future__ import annotations

import textwrap

from factory import blender_adapter


def _fake_blender_version_ok(tmp_path):
    script = tmp_path / "fake-blender"
    script.write_text("#!/bin/sh\necho 'Blender 5.2.0 LTS'\nexit 0\n")
    script.chmod(0o755)
    return script


def _fake_blender_version_fails(tmp_path):
    script = tmp_path / "fake-blender"
    script.write_text("#!/bin/sh\necho 'boom' 1>&2\nexit 1\n")
    script.chmod(0o755)
    return script


def _fake_blender_hangs(tmp_path):
    script = tmp_path / "fake-blender"
    script.write_text("#!/bin/sh\nsleep 5\n")
    script.chmod(0o755)
    return script


def _fake_blender_fixture_success(tmp_path, *, extra_file: str | None = None):
    """Mimics a real `--version` call and a real `--python <script> -- <out>`
    fixture call: writes a minimal valid ASCII STL to the path given after
    `--`. Optionally also drops an extra file to exercise unexpected-file
    detection."""
    extra_write = f'touch "$(dirname "$out")/{extra_file}"\n' if extra_file else ""
    script = tmp_path / "fake-blender"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            if [ "$1" = "--background" ] && echo "$@" | grep -q -- "--version"; then
              echo 'Blender 5.2.0 LTS'
              exit 0
            fi
            out=""
            found_sep=0
            for arg in "$@"; do
              if [ "$found_sep" = "1" ]; then
                out="$arg"
                break
              fi
              if [ "$arg" = "--" ]; then
                found_sep=1
              fi
            done
            printf 'solid x\\nfacet normal 0 0 1\\nouter loop\\nvertex 0 0 0\\nvertex 1 0 0\\nvertex 0 1 0\\nendloop\\nendfacet\\nendsolid x\\n' > "$out"
            {extra_write}
            exit 0
            """
        )
    )
    script.chmod(0o755)
    return script


def _fake_blender_fixture_nonzero_exit(tmp_path):
    script = tmp_path / "fake-blender"
    script.write_text("#!/bin/sh\nif echo \"$@\" | grep -q -- '--version'; then echo 'Blender 5.2.0'; exit 0; fi\necho 'bad script' 1>&2\nexit 1\n")
    script.chmod(0o755)
    return script


def _fake_blender_fixture_no_output(tmp_path):
    script = tmp_path / "fake-blender"
    script.write_text("#!/bin/sh\nif echo \"$@\" | grep -q -- '--version'; then echo 'Blender 5.2.0'; exit 0; fi\nexit 0\n")
    script.chmod(0o755)
    return script


# ---------------------------------------------------------------------------
# verify_headless_runtime()
# ---------------------------------------------------------------------------


def test_headless_runtime_success(tmp_path):
    fake = _fake_blender_version_ok(tmp_path)
    check = blender_adapter.verify_headless_runtime(str(fake))
    assert check["status"] == "pass"
    assert "5.2.0" in check["evidence"]


def test_headless_runtime_nonzero_exit(tmp_path):
    fake = _fake_blender_version_fails(tmp_path)
    check = blender_adapter.verify_headless_runtime(str(fake))
    assert check["status"] == "fail"


def test_headless_runtime_timeout(monkeypatch, tmp_path):
    fake = _fake_blender_hangs(tmp_path)
    monkeypatch.setattr(blender_adapter, "_HEADLESS_PROBE_TIMEOUT_SECONDS", 0.05)
    check = blender_adapter.verify_headless_runtime(str(fake))
    assert check["status"] == "fail"
    assert "timed out" in check["evidence"]


def test_headless_runtime_missing_binary(tmp_path):
    check = blender_adapter.verify_headless_runtime(str(tmp_path / "does-not-exist"))
    assert check["status"] == "fail"
    assert "failed to launch" in check["evidence"]


def test_headless_runtime_uses_bounded_flags(tmp_path, monkeypatch):
    captured = {}

    def _fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs

        class _Result:
            returncode = 0
            stdout = "Blender 5.2.0 LTS"
            stderr = ""

        return _Result()

    monkeypatch.setattr(blender_adapter.subprocess, "run", _fake_run)
    blender_adapter.verify_headless_runtime("/fake/path/to/Blender")
    assert isinstance(captured["command"], list)
    assert captured["command"][0] == "/fake/path/to/Blender"
    assert "--background" in captured["command"]
    assert "--factory-startup" in captured["command"]
    assert "--offline-mode" in captured["command"]
    assert "-P" not in captured["command"]
    assert "--python" not in captured["command"]
    assert captured["kwargs"]["shell"] is False
    assert "timeout" in captured["kwargs"]


# ---------------------------------------------------------------------------
# run_fixture_qualification() - the full bounded pipeline
# ---------------------------------------------------------------------------


def test_fixture_qualification_succeeds(tmp_path):
    fake = _fake_blender_fixture_success(tmp_path)
    result = blender_adapter.run_fixture_qualification(str(fake))
    assert result["fixture_execution_status"] == "succeeded"
    checks_by_id = {c["check_id"]: c for c in result["checks"]}
    assert checks_by_id["blender_fixture_exported"]["status"] == "pass"
    assert checks_by_id["blender_stl_output_valid"]["status"] == "pass"
    assert checks_by_id["blender_factory_validation"]["status"] in ("pass", "warn")
    assert checks_by_id["blender_factory_preview"]["status"] in ("pass", "warn")
    assert result["temporary_artifacts_created"] is True
    assert result["temporary_artifacts_cleaned"] is True
    assert result["unexpected_files"] == []


def test_fixture_qualification_skipped_when_headless_check_fails(tmp_path):
    fake = _fake_blender_version_fails(tmp_path)
    result = blender_adapter.run_fixture_qualification(str(fake))
    assert result["fixture_execution_status"] == "skipped"
    assert any("Headless runtime check failed" in e for e in result["errors"])


def test_fixture_qualification_nonzero_exit_handled(tmp_path):
    fake = _fake_blender_fixture_nonzero_exit(tmp_path)
    result = blender_adapter.run_fixture_qualification(str(fake))
    assert result["fixture_execution_status"] == "failed"
    checks_by_id = {c["check_id"]: c for c in result["checks"]}
    assert checks_by_id["blender_fixture_exported"]["status"] == "fail"


def test_fixture_qualification_missing_output_rejected(tmp_path):
    fake = _fake_blender_fixture_no_output(tmp_path)
    result = blender_adapter.run_fixture_qualification(str(fake))
    assert result["fixture_execution_status"] == "failed"
    checks_by_id = {c["check_id"]: c for c in result["checks"]}
    assert checks_by_id["blender_stl_output_valid"]["status"] == "fail"
    assert "missing" in checks_by_id["blender_stl_output_valid"]["evidence"]


def test_fixture_qualification_detects_unexpected_files(tmp_path):
    fake = _fake_blender_fixture_success(tmp_path, extra_file="unexpected.tmp")
    result = blender_adapter.run_fixture_qualification(str(fake))
    assert result["unexpected_files"] == ["unexpected.tmp"]
    assert any("unexpected" in w.lower() for w in result["warnings"])


def test_fixture_qualification_always_cleans_up_temp_dir(tmp_path):
    fake = _fake_blender_fixture_success(tmp_path)
    result = blender_adapter.run_fixture_qualification(str(fake))
    assert result["temporary_artifacts_cleaned"] is True


def test_fixture_command_uses_bounded_flags_and_factory_owned_script_only(monkeypatch):
    captured = []

    def _fake_run(command, **kwargs):
        captured.append((command, kwargs))

        class _Result:
            returncode = 0
            stdout = "Blender 5.2.0 LTS"
            stderr = ""

        return _Result()

    monkeypatch.setattr(blender_adapter.subprocess, "run", _fake_run)
    blender_adapter.run_fixture_qualification("/fake/path/to/Blender")
    assert len(captured) == 2  # one --version probe, one fixture invocation
    fixture_command, fixture_kwargs = captured[1]
    assert isinstance(fixture_command, list)
    assert fixture_kwargs["shell"] is False
    assert "timeout" in fixture_kwargs
    assert "--python" in fixture_command
    script_index = fixture_command.index("--python") + 1
    assert fixture_command[script_index] == str(blender_adapter.blender_gate.FIXTURE_SCRIPT_PATH)
    assert "--" in fixture_command
    assert "--python-exit-code" in fixture_command


# ---------------------------------------------------------------------------
# qualify_blender_adapter() - public entry point
# ---------------------------------------------------------------------------


def test_qualify_not_detected(monkeypatch):
    monkeypatch.setattr(blender_adapter.blender_gate, "resolve_blender_binary", lambda: {"detected": False, "binary_path": None, "detected_version": "unknown", "warnings": []})
    result = blender_adapter.qualify_blender_adapter()
    assert result["detected"] is False
    assert result["adapter_qualification_status"] == "not_detected"
    assert result["project_execution_approved"] is False


def test_qualify_default_does_not_run_fixture(monkeypatch, tmp_path):
    fake = _fake_blender_version_ok(tmp_path)
    monkeypatch.setattr(
        blender_adapter.blender_gate,
        "resolve_blender_binary",
        lambda: {"detected": True, "binary_path": str(fake), "detected_version": "5.2.0", "warnings": []},
    )
    result = blender_adapter.qualify_blender_adapter(confirm_fixture=False)
    assert result["fixture_execution_status"] == "not_run"
    assert result["adapter_qualification_status"] == "not_qualified"
    assert result["headless_runtime_status"] == "verified"
    assert result["temporary_artifacts_created"] is False
    assert result["project_execution_approved"] is False


def test_qualify_with_confirm_fixture_runs_full_pipeline(monkeypatch, tmp_path):
    fake = _fake_blender_fixture_success(tmp_path)
    monkeypatch.setattr(
        blender_adapter.blender_gate,
        "resolve_blender_binary",
        lambda: {"detected": True, "binary_path": str(fake), "detected_version": "5.2.0", "warnings": []},
    )
    result = blender_adapter.qualify_blender_adapter(confirm_fixture=True)
    assert result["fixture_execution_status"] == "succeeded"
    assert result["adapter_qualification_status"] == "qualified"
    assert result["project_execution_approved"] is False
    assert result["automatic_print_allowed"] is False
    assert result["printer_contacted"] is False
    assert result["network_used"] is False
    assert result["gui_launched"] is False


def test_qualify_execution_approved_never_true_even_when_qualified(monkeypatch, tmp_path):
    fake = _fake_blender_fixture_success(tmp_path)
    monkeypatch.setattr(
        blender_adapter.blender_gate,
        "resolve_blender_binary",
        lambda: {"detected": True, "binary_path": str(fake), "detected_version": "5.2.0", "warnings": []},
    )
    result = blender_adapter.qualify_blender_adapter(confirm_fixture=True)
    assert result["adapter_qualification_status"] == "qualified"
    assert result["project_execution_approved"] is False


def test_build_blender_report_shape(monkeypatch, tmp_path):
    fake = _fake_blender_version_ok(tmp_path)
    monkeypatch.setattr(
        blender_adapter.blender_gate,
        "resolve_blender_binary",
        lambda: {"detected": True, "binary_path": str(fake), "detected_version": "5.2.0", "warnings": []},
    )
    monkeypatch.setattr(
        blender_adapter.blender_gate.engine_registry,
        "probe_all_tools",
        lambda **kw: {"blender": {"detected": True, "detected_path": "/Applications/Blender.app", "detected_version": "5.2.0", "probe_warnings": []}},
    )
    report = blender_adapter.build_blender_report(confirm_fixture=False)
    assert set(report.keys()) == {"blender_adapter_version", "gate", "qualification", "project_execution_approved", "safety"}
    assert report["project_execution_approved"] is False
    assert report["safety"]["automatic_print_allowed"] is False

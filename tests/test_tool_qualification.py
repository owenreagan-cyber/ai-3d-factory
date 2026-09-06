"""Phase 44 tests: `factory.tool_qualification` core model.

Covers: every in-scope/deferred tool gets a result, detection != qualification
!= execution approval, one tool's failure never aborts the rest, deterministic
summary counts, and unknown-tool handling. See docs/tool-qualification.md.
"""

from __future__ import annotations

import pytest

from factory import engine_registry, tool_qualification as tq


def _fake_probe(tool_id: str, **overrides) -> dict:
    base = {
        "detected": False,
        "detected_path": None,
        "detected_version": "unknown",
        "probe_status": "not_installed",
        "probe_warnings": [],
    }
    base.update(overrides)
    return base


def _fake_probe_all(overrides: dict[str, dict] | None = None) -> dict[str, dict]:
    overrides = overrides or {}
    return {tool_id: overrides.get(tool_id, _fake_probe(tool_id)) for tool_id in engine_registry.TOOL_IDS}


# ---------------------------------------------------------------------------
# Core coverage
# ---------------------------------------------------------------------------


def test_every_tool_id_gets_a_result(monkeypatch):
    monkeypatch.setattr(tq.engine_registry, "probe_all_tools", lambda **kwargs: _fake_probe_all())
    results = tq.qualify_all_tools()
    assert set(results.keys()) == set(engine_registry.TOOL_IDS)
    for tool_id, result in results.items():
        assert result["tool_id"] == tool_id
        assert result["display_name"]


def test_in_scope_tools_get_real_qualification_statuses(monkeypatch):
    monkeypatch.setattr(tq.engine_registry, "probe_all_tools", lambda **kwargs: _fake_probe_all())
    results = tq.qualify_all_tools()
    for tool_id in tq.QUALIFICATION_SCOPE_TOOL_IDS:
        assert results[tool_id]["qualification_status"] != "unsupported"


def test_deferred_tools_get_unsupported_status_regardless_of_detection(monkeypatch):
    overrides = {tool_id: _fake_probe(tool_id, detected=True, detected_path="/Applications/Fake.app") for tool_id in tq.DEFERRED_TOOL_IDS}
    monkeypatch.setattr(tq.engine_registry, "probe_all_tools", lambda **kwargs: _fake_probe_all(overrides))
    results = tq.qualify_all_tools()
    for tool_id in tq.DEFERRED_TOOL_IDS:
        result = results[tool_id]
        assert result["qualification_status"] == "unsupported"
        assert result["qualification_level"] == "manual_required"
        # "detected merely because installed" never qualifies it - but the fact is still surfaced.
        assert result["detected"] is True


def test_scope_and_deferred_partition_every_tool_exactly_once():
    assert set(tq.QUALIFICATION_SCOPE_TOOL_IDS) | set(tq.DEFERRED_TOOL_IDS) == set(engine_registry.TOOL_IDS)
    assert not (set(tq.QUALIFICATION_SCOPE_TOOL_IDS) & set(tq.DEFERRED_TOOL_IDS))


def test_detected_does_not_imply_qualified(monkeypatch):
    """Blender: detected=True, but qualification_status is never "qualified" in this phase."""
    overrides = {"blender": _fake_probe("blender", detected=True, detected_path="/Applications/Blender.app", detected_version="5.2.0")}
    monkeypatch.setattr(tq.engine_registry, "probe_all_tools", lambda **kwargs: _fake_probe_all(overrides))
    result = tq.qualify_tool("blender")
    assert result["detected"] is True
    assert result["qualification_status"] != "qualified"
    assert result["qualification_status"] == "requires_manual_qualification"


def test_qualified_never_implies_execution_approved(monkeypatch, tmp_path):
    executable = _make_fake_openscad(tmp_path)
    overrides = {"openscad_stable": _fake_probe("openscad_stable", detected=True, detected_path=str(executable), detected_version="fake 1.0", probe_status="detected")}
    monkeypatch.setattr(tq.engine_registry, "probe_all_tools", lambda **kwargs: _fake_probe_all(overrides))
    monkeypatch.setattr(tq, "validate_mesh", lambda path: {"overall_status": "PASS"})
    result = tq.qualify_tool("openscad_stable")
    assert result["qualification_status"] == "qualified"
    assert result["execution_approved"] is False


def _make_fake_openscad(tmp_path):
    """A fake `openscad` executable script that writes a minimal non-empty STL,
    for monkeypatched probe-result tests that need the real (bounded, argument-
    list) subprocess call path to actually run against something."""
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


def test_one_tool_failure_never_aborts_the_rest(monkeypatch):
    def _boom(**kwargs):
        raise RuntimeError("probe exploded")

    # Only openscad_stable's dedicated qualifier is forced to explode; every other
    # tool must still get a real result back.
    monkeypatch.setattr(tq, "_qualify_openscad_stable", _boom)
    monkeypatch.setattr(tq.engine_registry, "probe_all_tools", lambda **kwargs: _fake_probe_all())
    results = tq.qualify_all_tools()
    assert results["openscad_stable"]["qualification_status"] == "probe_failed"
    assert results["cadquery"]["qualification_status"] == "not_installed"
    assert set(results.keys()) == set(engine_registry.TOOL_IDS)


def test_unknown_tool_id_raises():
    with pytest.raises(tq.UnknownToolError):
        tq.qualify_tool("not-a-real-tool")


def test_unknown_fields_stay_unknown(monkeypatch):
    monkeypatch.setattr(tq.engine_registry, "probe_all_tools", lambda **kwargs: _fake_probe_all())
    result = tq.qualify_tool("onshape")
    assert result["detected_version"] == "unknown"


def test_deterministic_given_same_probe_evidence(monkeypatch):
    monkeypatch.setattr(tq.engine_registry, "probe_all_tools", lambda **kwargs: _fake_probe_all())
    first = tq.qualify_all_tools()
    second = tq.qualify_all_tools()
    for tool_id in engine_registry.TOOL_IDS:
        assert first[tool_id]["qualification_status"] == second[tool_id]["qualification_status"]
        assert first[tool_id]["qualification_level"] == second[tool_id]["qualification_level"]
        assert first[tool_id]["checks"] == second[tool_id]["checks"]


# ---------------------------------------------------------------------------
# Summary counts
# ---------------------------------------------------------------------------


def test_summary_counts_correct(monkeypatch):
    monkeypatch.setattr(tq.engine_registry, "probe_all_tools", lambda **kwargs: _fake_probe_all())
    results = tq.qualify_all_tools()
    summary = tq.summarize_qualification(results)
    assert summary["total_tools"] == 13
    assert summary["qualification_scope"] == 8
    assert summary["not_installed"] == sum(1 for r in results.values() if r["qualification_status"] == "not_installed")
    assert summary["unsupported"] == sum(1 for r in results.values() if r["qualification_status"] == "unsupported")
    assert summary["cloud_gated"] == 2  # meshy, onshape
    assert summary["execution_approved"] == 0


def test_execution_approved_always_zero_in_summary(monkeypatch):
    monkeypatch.setattr(tq.engine_registry, "probe_all_tools", lambda **kwargs: _fake_probe_all())
    results = tq.qualify_all_tools()
    assert all(r["execution_approved"] is False for r in results.values())
    assert tq.summarize_qualification(results)["execution_approved"] == 0


def test_build_qualification_report_shape(monkeypatch):
    monkeypatch.setattr(tq.engine_registry, "probe_all_tools", lambda **kwargs: _fake_probe_all())
    report = tq.build_qualification_report()
    assert report["qualification_version"] == 1
    assert isinstance(report["results"], list)
    assert len(report["results"]) == 13
    assert report["safety"]["automatic_print_allowed"] is False
    assert report["safety"]["software_installed"] is False


def test_build_qualification_report_single_tool_shape(monkeypatch):
    monkeypatch.setattr(tq.engine_registry, "probe_all_tools", lambda **kwargs: _fake_probe_all())
    report = tq.build_qualification_report(tool_id="cadquery")
    assert len(report["results"]) == 1
    assert report["results"][0]["tool_id"] == "cadquery"


def test_qualification_scope_matches_documented_eight_tools():
    assert tq.QUALIFICATION_SCOPE_TOOL_IDS == (
        "openscad_stable",
        "openscad_snapshot",
        "cadquery",
        "blender",
        "freecad",
        "bambu_studio",
        "orcaslicer",
        "prusaslicer",
    )

"""Phase 45 tests: `factory.blender_gate` - the read-only, zero-subprocess
permission/readiness/dry-run planning layer that gates
`factory.blender_adapter`'s bounded execution.

Covers: Blender binary resolution (joined from Phase 43's `.app` bundle
detection, never a fresh PATH scan), the gate-checklist reconciliation
table, the dry-run fixture-execution plan, and that this module never
calls `subprocess`. See docs/blender-adapter.md.
"""

from __future__ import annotations

import inspect

from factory import blender_gate


def _probe(**overrides) -> dict:
    base = {"detected": False, "detected_path": None, "detected_version": "unknown", "probe_status": "not_installed", "probe_warnings": []}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# resolve_blender_binary()
# ---------------------------------------------------------------------------


def test_resolve_blender_binary_not_detected(monkeypatch):
    monkeypatch.setattr(blender_gate.engine_registry, "probe_all_tools", lambda **kw: {"blender": _probe()})
    resolved = blender_gate.resolve_blender_binary()
    assert resolved["detected"] is False
    assert resolved["binary_path"] is None


def test_resolve_blender_binary_detected_bundle_without_executable(monkeypatch, tmp_path):
    bundle = tmp_path / "Blender.app"
    bundle.mkdir()  # no Contents/MacOS/Blender inside
    monkeypatch.setattr(
        blender_gate.engine_registry,
        "probe_all_tools",
        lambda **kw: {"blender": _probe(detected=True, detected_path=str(bundle), detected_version="5.2.0")},
    )
    resolved = blender_gate.resolve_blender_binary()
    assert resolved["detected"] is False
    assert resolved["binary_path"] is None
    assert any("no Contents/MacOS/Blender executable" in w for w in resolved["warnings"])


def test_resolve_blender_binary_detected_with_executable(monkeypatch, tmp_path):
    bundle = tmp_path / "Blender.app"
    binary_dir = bundle / "Contents" / "MacOS"
    binary_dir.mkdir(parents=True)
    binary = binary_dir / "Blender"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    monkeypatch.setattr(
        blender_gate.engine_registry,
        "probe_all_tools",
        lambda **kw: {"blender": _probe(detected=True, detected_path=str(bundle), detected_version="5.2.0")},
    )
    resolved = blender_gate.resolve_blender_binary()
    assert resolved["detected"] is True
    assert resolved["binary_path"] == str(binary)
    assert resolved["detected_version"] == "5.2.0"


# ---------------------------------------------------------------------------
# reconcile_gate_checklist()
# ---------------------------------------------------------------------------


def test_gate_checklist_has_fifteen_items():
    checklist = blender_gate.reconcile_gate_checklist()
    assert len(checklist) == 15


def test_gate_checklist_every_item_has_required_fields():
    for item in blender_gate.reconcile_gate_checklist():
        assert set(item.keys()) == {"item", "maps_to_original", "status", "note"}
        assert item["status"] in ("satisfied", "partially_satisfied", "deferred", "unsatisfied")
        assert item["item"]
        assert item["note"]


def test_gate_checklist_explicit_human_approval_item_is_only_partially_satisfied():
    checklist = blender_gate.reconcile_gate_checklist()
    item = next(i for i in checklist if i["item"].startswith("Explicit human approval"))
    assert item["status"] == "partially_satisfied"
    assert "config/future_local_tools.json" in item["note"]


def test_gate_checklist_is_a_fresh_list_each_call():
    a = blender_gate.reconcile_gate_checklist()
    b = blender_gate.reconcile_gate_checklist()
    assert a == b
    assert a is not b


# ---------------------------------------------------------------------------
# plan_blender_fixture_execution() / evaluate_blender_execution_gate()
# ---------------------------------------------------------------------------


def test_plan_when_not_detected(monkeypatch):
    monkeypatch.setattr(blender_gate.engine_registry, "probe_all_tools", lambda **kw: {"blender": _probe()})
    plan = blender_gate.plan_blender_fixture_execution()
    assert plan["gate_status"] == "not_detected"
    assert plan["execution_allowed"] is False
    assert plan["blockers"]
    assert plan["dry_run"] is True
    assert plan["project_execution_approved"] is False


def test_plan_when_detected_is_ready_for_fixture_qualification(monkeypatch, tmp_path):
    bundle = tmp_path / "Blender.app"
    binary_dir = bundle / "Contents" / "MacOS"
    binary_dir.mkdir(parents=True)
    (binary_dir / "Blender").write_text("#!/bin/sh\n")
    (binary_dir / "Blender").chmod(0o755)
    monkeypatch.setattr(
        blender_gate.engine_registry,
        "probe_all_tools",
        lambda **kw: {"blender": _probe(detected=True, detected_path=str(bundle), detected_version="5.2.0")},
    )
    plan = blender_gate.plan_blender_fixture_execution()
    assert plan["gate_status"] == "ready_for_fixture_qualification"
    assert plan["execution_allowed"] is True
    assert plan["blockers"] == []
    assert plan["workflow"] == "fixture_organic_model"
    assert plan["project_execution_approved"] is False
    assert plan["no_automatic_print"] is True


def test_plan_never_launches_blender_or_calls_subprocess():
    # Looks for the actual call shape, not the word "subprocess" - the
    # module's own docstrings/kwarg names (e.g.
    # `include_version_subprocess=False`) legitimately mention it to
    # explain why this module never calls it itself.
    source = inspect.getsource(blender_gate)
    for forbidden in ("subprocess.run(", "subprocess.Popen(", "subprocess.call(", "import subprocess"):
        assert forbidden not in source, f"{forbidden!r} found in factory.blender_gate"


def test_evaluate_blender_execution_gate_shape(monkeypatch):
    monkeypatch.setattr(blender_gate.engine_registry, "probe_all_tools", lambda **kw: {"blender": _probe()})
    gate = blender_gate.evaluate_blender_execution_gate()
    assert gate["project_execution_approved"] is False
    assert gate["no_automatic_print"] is True
    assert gate["supported_workflows"] == ["fixture_organic_model"]
    assert isinstance(gate["gate_checklist"], list) and len(gate["gate_checklist"]) == 15
    assert isinstance(gate["unsatisfied_or_partial_gate_items"], list)


def test_supported_workflow_ids_is_narrow():
    assert blender_gate.SUPPORTED_WORKFLOW_IDS == ("fixture_organic_model",)


def test_fixture_script_path_points_outside_src():
    # The Factory-owned fixture script deliberately lives outside src/ so
    # its `import bpy` never trips the pre-existing repo-wide
    # test_no_blender_execution_code_anywhere_in_src() scan in
    # tests/test_blender_gate.py (Phase 21). See docs/blender-adapter.md
    # "Python execution policy".
    assert "src" not in blender_gate.FIXTURE_SCRIPT_PATH.parts
    assert blender_gate.FIXTURE_SCRIPT_PATH.name == "factory_qualification_fixture.py"

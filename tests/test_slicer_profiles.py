"""Phase 39 Part 1/2 tests: `factory.slicer_profiles` - slicer-aware
review profiles. Customizes review guidance based on the detected local
slicer environment; never requires any slicer to actually be installed,
never invents an installed profile, and never edits/launches/configures
any slicer. Reuses `factory.slicer.local_slicer_probe.probe_slicers()`
for detection rather than a second registry. See docs/slicer-profiles.md,
docs/roadmap.md Phase 39.
"""

from __future__ import annotations

import inspect

from factory.slicer import local_slicer_probe
from factory.slicer_profiles import (
    CONFIDENCE_LEVELS,
    PROFILE_STATUSES,
    SUPPORTED_SLICER_NAMES,
    build_slicer_specific_checks,
    detect_slicer_profile,
    get_slicer_review_profile,
)


def test_supported_slicer_names_are_the_suggested_values():
    assert set(SUPPORTED_SLICER_NAMES) == {"Bambu Studio", "OrcaSlicer", "PrusaSlicer"}


def test_profile_statuses_are_the_suggested_values():
    assert set(PROFILE_STATUSES) == {"detected", "not_detected"}


def test_confidence_levels_are_the_suggested_values():
    assert set(CONFIDENCE_LEVELS) == {"High", "Medium", "Low", "Unknown"}


def test_module_reuses_slicer_probe_not_a_second_registry():
    source = inspect.getsource(__import__("factory.slicer_profiles", fromlist=["_x"]))
    assert "from factory.slicer.local_slicer_probe import probe_slicers" in source
    # Never invents its own app-path/binary detection logic.
    assert "/Applications/" not in source
    assert "shutil.which" not in source


# ---------------------------------------------------------------------------
# detect_slicer_profile() - reuses probe_slicers(), never launches anything
# ---------------------------------------------------------------------------


def test_detect_slicer_profile_returns_unknown_when_nothing_found(monkeypatch):
    monkeypatch.setattr(
        "factory.slicer_profiles.probe_slicers",
        lambda: [{"name": "Bambu Studio", "found": False}, {"name": "OrcaSlicer", "found": False}, {"name": "PrusaSlicer", "found": False}],
    )
    assert detect_slicer_profile() == "Unknown"


def test_detect_slicer_profile_returns_bambu_studio_when_found(monkeypatch):
    monkeypatch.setattr(
        "factory.slicer_profiles.probe_slicers",
        lambda: [{"name": "Bambu Studio", "found": True}, {"name": "OrcaSlicer", "found": False}],
    )
    assert detect_slicer_profile() == "Bambu Studio"


def test_detect_slicer_profile_returns_orcaslicer_when_found(monkeypatch):
    monkeypatch.setattr(
        "factory.slicer_profiles.probe_slicers",
        lambda: [{"name": "Bambu Studio", "found": False}, {"name": "OrcaSlicer", "found": True}, {"name": "PrusaSlicer", "found": False}],
    )
    assert detect_slicer_profile() == "OrcaSlicer"


def test_detect_slicer_profile_returns_prusaslicer_when_found(monkeypatch):
    monkeypatch.setattr(
        "factory.slicer_profiles.probe_slicers",
        lambda: [{"name": "Bambu Studio", "found": False}, {"name": "OrcaSlicer", "found": False}, {"name": "PrusaSlicer", "found": True}],
    )
    assert detect_slicer_profile() == "PrusaSlicer"


def test_detect_slicer_profile_priority_order_when_multiple_found(monkeypatch):
    monkeypatch.setattr(
        "factory.slicer_profiles.probe_slicers",
        lambda: [{"name": "PrusaSlicer", "found": True}, {"name": "Bambu Studio", "found": True}],
    )
    # Priority order is SUPPORTED_SLICER_NAMES, not detection-list order.
    assert detect_slicer_profile() == "Bambu Studio"


def test_detect_slicer_profile_never_launches_a_slicer(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must never launch a slicer binary")

    import subprocess

    monkeypatch.setattr(subprocess, "Popen", _boom, raising=False)
    detect_slicer_profile()


# ---------------------------------------------------------------------------
# get_slicer_review_profile() - never invents an installed profile
# ---------------------------------------------------------------------------


def test_bambu_studio_profile_content(monkeypatch):
    monkeypatch.setattr("factory.slicer_profiles.detect_slicer_profile", lambda: "Bambu Studio")
    profile = get_slicer_review_profile()
    assert profile["slicer_name"] == "Bambu Studio"
    assert profile["profile_status"] == "detected"
    assert profile["confidence"] == "High"
    assert "AMS assignments" in profile["review_categories"]
    assert any("AMS" in q or "plate" in q.lower() for q in profile["printer_questions"])


def test_orcaslicer_profile_content():
    profile = get_slicer_review_profile("OrcaSlicer")
    assert profile["slicer_name"] == "OrcaSlicer"
    assert profile["profile_status"] == "detected"
    assert "Pressure advance awareness" in profile["review_categories"]


def test_prusaslicer_profile_content():
    profile = get_slicer_review_profile("PrusaSlicer")
    assert profile["slicer_name"] == "PrusaSlicer"
    assert profile["profile_status"] == "detected"
    assert "Layer settings" in profile["review_categories"]


def test_unknown_slicer_falls_back_to_generic_checklist():
    profile = get_slicer_review_profile("Unknown")
    assert profile["slicer_name"] == "Unknown"
    assert profile["profile_status"] == "not_detected"
    assert profile["confidence"] == "Unknown"
    assert profile["known_capabilities"] == []
    assert "Filament profile" in profile["review_categories"]


def test_unrecognized_slicer_name_also_falls_back_to_generic():
    profile = get_slicer_review_profile("SomeOtherSlicer")
    assert profile["profile_status"] == "not_detected"
    assert any("not a slicer" in w for w in profile["warnings"])


def test_never_invents_an_installed_profile_when_nothing_detected(monkeypatch):
    monkeypatch.setattr(
        "factory.slicer_profiles.probe_slicers",
        lambda: [{"name": n, "found": False} for n in SUPPORTED_SLICER_NAMES],
    )
    profile = get_slicer_review_profile()
    assert profile["slicer_name"] == "Unknown"
    assert profile["profile_status"] == "not_detected"


def test_multi_material_questions_only_present_when_requested():
    without = get_slicer_review_profile("Bambu Studio", multi_material=False)
    with_mm = get_slicer_review_profile("Bambu Studio", multi_material=True)
    assert without["multi_material_questions"] == []
    assert with_mm["multi_material_questions"]


def test_multi_material_questions_never_calculate_purge_or_modify_assignments():
    profile = get_slicer_review_profile("Bambu Studio", multi_material=True)
    for item in profile["multi_material_questions"]:
        assert item.lower().startswith("confirm")


def test_profile_never_reads_actual_slicer_settings():
    profile = get_slicer_review_profile("Bambu Studio")
    assert any("never reads" in limitation for limitation in profile["limitations"])


def test_multiple_detected_slicers_produces_a_warning(monkeypatch):
    monkeypatch.setattr(
        "factory.slicer_profiles.probe_slicers",
        lambda: [{"name": "Bambu Studio", "found": True}, {"name": "OrcaSlicer", "found": True}],
    )
    profile = get_slicer_review_profile()
    assert profile["slicer_name"] == "Bambu Studio"
    assert any("More than one" in w for w in profile["warnings"])


# ---------------------------------------------------------------------------
# build_slicer_specific_checks() - additive, never a replacement
# ---------------------------------------------------------------------------


def test_build_slicer_specific_checks_flattens_all_question_categories():
    profile = get_slicer_review_profile("Bambu Studio", multi_material=True)
    checks = build_slicer_specific_checks(profile)
    assert set(profile["printer_questions"]) <= set(checks)
    assert set(profile["material_questions"]) <= set(checks)
    assert set(profile["multi_material_questions"]) <= set(checks)


def test_build_slicer_specific_checks_generic_when_no_slicer_detected():
    profile = get_slicer_review_profile("Unknown")
    checks = build_slicer_specific_checks(profile)
    assert checks
    assert all(isinstance(c, str) for c in checks)


# ---------------------------------------------------------------------------
# Safety: no slicer execution, no G-code, no network
# ---------------------------------------------------------------------------


def test_module_never_launches_installs_or_edits_a_slicer():
    import factory.slicer_profiles as module

    source = inspect.getsource(module)
    for forbidden in ("subprocess", "os.system", "os.popen", "Popen", "urllib", "requests", "socket"):
        assert forbidden not in source, f"slicer_profiles.py must stay read-only; found {forbidden!r}"

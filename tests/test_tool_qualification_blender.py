"""Phase 44 tests: `factory.tool_qualification`'s Blender/FreeCAD (and, for the
same reasoning, the three slicers) metadata-only qualification path.

Covers: not installed, metadata-only detection, no subprocess is ever
attempted for Blender/FreeCAD, `execution_approved` stays false, and Phase 45
remains the owner of any future Blender execution decision.
See docs/tool-qualification.md.
"""

from __future__ import annotations

import inspect

from factory import tool_qualification as tq


def _probe(**overrides) -> dict:
    base = {"detected": False, "detected_path": None, "detected_version": "unknown", "probe_status": "not_installed", "probe_warnings": []}
    base.update(overrides)
    return base


def test_blender_not_installed():
    result = tq._qualify_metadata_only_gui_tool("blender", "Blender", _probe())
    assert result["detected"] is False
    assert result["qualification_status"] == "not_installed"
    assert result["qualification_level"] == "metadata_only"


def test_blender_metadata_only_detection():
    probe = _probe(detected=True, detected_path="/Applications/Blender.app", detected_version="5.2.0")
    result = tq._qualify_metadata_only_gui_tool("blender", "Blender", probe)
    assert result["detected"] is True
    assert result["detected_version"] == "5.2.0"
    assert result["qualification_status"] == "requires_manual_qualification"
    assert result["qualification_level"] == "metadata_only"


def test_blender_headless_probe_check_is_recorded_as_skipped_by_policy():
    probe = _probe(detected=True, detected_path="/Applications/Blender.app", detected_version="5.2.0")
    result = tq._qualify_metadata_only_gui_tool("blender", "Blender", probe)
    checks_by_id = {c["check_id"]: c for c in result["checks"]}
    assert checks_by_id["blender_headless_probe"]["status"] == "skip"
    assert "no subprocess" in checks_by_id["blender_headless_probe"]["evidence"].lower()


def test_blender_execution_approved_always_false():
    probe = _probe(detected=True, detected_path="/Applications/Blender.app", detected_version="5.2.0")
    result = tq._qualify_metadata_only_gui_tool("blender", "Blender", probe)
    assert result["execution_approved"] is False


def test_freecad_not_installed():
    result = tq._qualify_metadata_only_gui_tool("freecad", "FreeCAD", _probe())
    assert result["qualification_status"] == "not_installed"


def test_freecad_detected_stops_at_metadata_only():
    probe = _probe(detected=True, detected_path="/Applications/FreeCAD.app", detected_version="1.0")
    result = tq._qualify_metadata_only_gui_tool("freecad", "FreeCAD", probe)
    assert result["qualification_status"] == "requires_manual_qualification"
    assert result["qualification_level"] == "metadata_only"


def test_blender_and_freecad_never_call_subprocess():
    """Source inspection: neither the shared metadata-only qualifier nor its
    policy-note table ever references `subprocess` for Blender/FreeCAD."""
    source = inspect.getsource(tq._qualify_metadata_only_gui_tool)
    assert "subprocess" not in source


def test_no_gui_launch_helper_referenced_in_qualification_functions():
    """Source inspection of the actual qualification functions (never the
    module's own prose docstring, which legitimately *names* these tools to
    say they're never used) - mirrors `tests/test_engine_registry_probe.py`'s
    function-scoped source-inspection pattern."""
    for func in (
        tq._qualify_openscad_stable,
        tq._qualify_openscad_snapshot,
        tq._qualify_cadquery,
        tq._qualify_metadata_only_gui_tool,
        tq._qualify_deferred_tool,
        tq._run_cadquery_capability_probe,
    ):
        source = inspect.getsource(func)
        for forbidden in ("os.system", "AppleScript", "osascript", "pkill", "subprocess.Popen"):
            assert forbidden not in source, f"{forbidden!r} found in {func.__name__}"


# ---------------------------------------------------------------------------
# Slicers: Bambu Studio, OrcaSlicer, PrusaSlicer - same metadata-only path.
# ---------------------------------------------------------------------------


def test_slicer_missing():
    for tool_id, display_name in (("bambu_studio", "Bambu Studio"), ("orcaslicer", "OrcaSlicer"), ("prusaslicer", "PrusaSlicer")):
        result = tq._qualify_metadata_only_gui_tool(tool_id, display_name, _probe())
        assert result["qualification_status"] == "not_installed"


def test_slicer_detected_version_unknown_handled():
    probe = _probe(detected=True, detected_path="/Applications/BambuStudio.app", detected_version="unknown")
    result = tq._qualify_metadata_only_gui_tool("bambu_studio", "Bambu Studio", probe)
    assert result["qualification_status"] == "requires_manual_qualification"
    checks_by_id = {c["check_id"]: c for c in result["checks"]}
    assert checks_by_id["bambu_studio_version_metadata"]["status"] == "warn"


def test_slicer_never_slices_or_generates_gcode_or_contacts_printer():
    probe = _probe(detected=True, detected_path="/Applications/BambuStudio.app", detected_version="2.0")
    result = tq._qualify_metadata_only_gui_tool("bambu_studio", "Bambu Studio", probe)
    assert result["gui_launched"] is False
    assert result["printer_contacted"] is False
    assert result["automatic_print_allowed"] is False
    assert result["network_used"] is False

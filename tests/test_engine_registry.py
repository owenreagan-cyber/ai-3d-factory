"""Phase 43 tests: `factory.engine_registry` - the canonical, read-only
tool/engine registry. No installs, no upgrades, no GUI launches, no
Blender/FreeCAD/slicer execution, no Meshy/Onshape network contact, no
Homebrew mutation. See docs/engine-registry.md, docs/roadmap.md Phase 43.
"""

from __future__ import annotations

import inspect

from factory import engine_registry


def test_every_required_tool_exists_exactly_once():
    registry = engine_registry.get_tool_registry()
    assert set(registry.keys()) == set(engine_registry.TOOL_IDS)
    assert len(registry) == 13
    for tool_id, record in registry.items():
        assert record["tool_id"] == tool_id


def test_stable_unique_ids():
    assert len(engine_registry.TOOL_IDS) == len(set(engine_registry.TOOL_IDS))
    expected = {
        "openscad_stable", "openscad_snapshot", "cadquery", "blender", "freecad",
        "meshy", "plasticity", "autodesk_fusion", "onshape",
        "bambu_studio", "orcaslicer", "prusaslicer", "bambu_connect",
    }
    assert set(engine_registry.TOOL_IDS) == expected


_REQUIRED_FIELDS = (
    "tool_id", "display_name", "category", "subcategory", "vendor", "status",
    "roadmap_status", "execution_status", "qualification_status", "local_or_cloud",
    "install_method", "homebrew_token", "package_name", "detected", "detected_path",
    "detected_version", "detected_channel", "detected_architecture", "cli_available",
    "headless_capable", "gui_only", "automation_suitability", "network_required",
    "account_required", "possible_monetary_cost", "capabilities", "strengths",
    "limitations", "input_types", "output_types", "mechanical_design_suitability",
    "organic_modeling_suitability", "parametric_design_suitability",
    "dimensional_precision_suitability", "mesh_cleanup_suitability",
    "assembly_suitability", "slicer_suitability", "validation_requirements",
    "review_requirements", "licensing_or_provenance_concerns", "cloud_gate_required",
    "human_approval_required", "automatic_print_permission", "notes",
)

# Fields explicitly allowed to be None/False/"unknown" as a real, deliberate
# answer rather than a missing value - see docs/engine-registry.md.
_NULLABLE_FIELDS = {"homebrew_token", "package_name", "detected_path"}


def test_required_fields_present_and_no_blank_required_values():
    registry = engine_registry.get_tool_registry()
    for tool_id, record in registry.items():
        for field in _REQUIRED_FIELDS:
            assert field in record, f"{tool_id} missing field {field!r}"
            if field in _NULLABLE_FIELDS:
                continue
            value = record[field]
            assert value != "", f"{tool_id}.{field} is blank"
            assert value is not None, f"{tool_id}.{field} is None"


def test_automatic_print_permission_always_false():
    registry = engine_registry.get_tool_registry()
    for tool_id, record in registry.items():
        assert record["automatic_print_permission"] is False, tool_id
    probed = engine_registry.get_tool_registry(probe=True)
    for tool_id, record in probed.items():
        assert record["automatic_print_permission"] is False, tool_id


def test_meshy_cloud_gate_and_monetary_cost():
    meshy = engine_registry.get_tool_registry()["meshy"]
    assert meshy["cloud_gate_required"] is True
    assert meshy["possible_monetary_cost"] is True
    assert meshy["network_required"] is True
    assert meshy["local_or_cloud"] == "cloud"
    assert meshy["roadmap_status"] == "cloud_gated"
    assert meshy["human_approval_required"] is True


def test_blender_near_term_status():
    blender = engine_registry.get_tool_registry()["blender"]
    assert blender["roadmap_status"] == "near_term"
    assert blender["execution_status"] == "planned"
    assert blender["category"] == "organic_mesh_modeling"


def test_freecad_near_term_status():
    freecad = engine_registry.get_tool_registry()["freecad"]
    assert freecad["roadmap_status"] == "near_term"
    assert freecad["execution_status"] == "unsupported"


def test_plasticity_fusion_onshape_bambu_connect_preserved():
    registry = engine_registry.get_tool_registry()
    assert registry["plasticity"]["roadmap_status"] == "future"
    assert registry["autodesk_fusion"]["roadmap_status"] == "future"
    assert registry["onshape"]["roadmap_status"] == "future"
    assert registry["bambu_connect"]["roadmap_status"] == "printing_adjacent_disabled"
    assert registry["bambu_connect"]["category"] == "printing_adjacent"
    assert registry["bambu_connect"]["execution_status"] == "disabled"


def test_slicer_tools_correctly_categorized():
    registry = engine_registry.get_tool_registry()
    for tool_id in ("bambu_studio", "orcaslicer", "prusaslicer"):
        record = registry[tool_id]
        assert record["category"] == "slicer_review"
        assert record["display_group"] == "slicers"
        assert record["roadmap_status"] == "human_only"
        assert record["execution_status"] == "manual_only"
        assert record["automatic_print_permission"] is False


def test_openscad_stable_snapshot_distinction_exists():
    registry = engine_registry.get_tool_registry()
    stable = registry["openscad_stable"]
    snapshot = registry["openscad_snapshot"]
    assert stable["tool_id"] != snapshot["tool_id"]
    assert stable["roadmap_status"] == "core_supported"
    assert snapshot["roadmap_status"] != "core_supported"
    assert snapshot["qualification_status"] == "not_applicable"


def test_cadquery_correct_category():
    cadquery = engine_registry.get_tool_registry()["cadquery"]
    assert cadquery["category"] == "design_cad"
    assert cadquery["install_method"] == "python_package"
    assert cadquery["package_name"] == "cadquery"


def test_future_tools_cannot_accidentally_appear_as_implemented():
    registry = engine_registry.get_tool_registry()
    for tool_id in ("plasticity", "autodesk_fusion", "onshape", "bambu_connect"):
        assert registry[tool_id]["execution_status"] in ("future", "disabled")
        assert registry[tool_id]["execution_status"] != "implemented"


def test_vocabularies_are_closed_and_every_record_uses_them():
    registry = engine_registry.get_tool_registry()
    for record in registry.values():
        assert record["roadmap_status"] in engine_registry.ROADMAP_STATUSES
        assert record["execution_status"] in engine_registry.EXECUTION_STATUSES
        assert record["qualification_status"] in engine_registry.QUALIFICATION_STATUSES
        assert record["local_or_cloud"] in engine_registry.LOCAL_OR_CLOUD_VALUES
        assert record["display_group"] in engine_registry.DISPLAY_GROUPS


def test_qualification_never_qualified_in_this_phase():
    """Phase 43 is architecture + discovery only - qualification testing is
    Phase 44's job. No tool may already claim `qualified`."""
    registry = engine_registry.get_tool_registry(probe=True)
    for tool_id, record in registry.items():
        assert record["qualification_status"] != "qualified", tool_id


def test_get_tool_registry_recomputed_each_call_reflects_cadquery_availability(monkeypatch):
    from factory.cad import backend as cad_backend

    monkeypatch.setattr(cad_backend, "is_cadquery_available", lambda: True)
    registry = engine_registry.get_tool_registry()
    assert registry["cadquery"]["execution_status"] == "implemented"


def test_summarize_engine_registry_shape():
    data = engine_registry.summarize_engine_registry()
    assert set(data.keys()) == {"registry_version", "categories", "tools", "summary", "safety"}
    assert data["registry_version"] == engine_registry.REGISTRY_VERSION
    assert set(data["categories"]) == set(engine_registry.DISPLAY_GROUPS)
    assert len(data["tools"]) == 13
    safety = data["safety"]
    assert safety == {
        "installed_or_modified_tools": False,
        "launched_gui_apps": False,
        "network_used": False,
        "printer_contacted": False,
        "automatic_print_allowed": False,
    }


def test_summarize_tool_environment_shape():
    summary = engine_registry.summarize_tool_environment()
    assert set(summary.keys()) == {
        "core_local_tools_available", "slicers_detected", "near_term_engines_unqualified", "cloud_engines_gated",
    }


# ---- safety: source-level guards, mirroring tests/test_slicer_probe.py ----


def test_module_never_calls_forbidden_apis():
    """Guard actual call sites, not this module's own prose explaining what
    it deliberately never does (its docstrings *name* `osascript`/`open`/
    `pkill` precisely to disclaim them)."""
    source = inspect.getsource(engine_registry)
    forbidden_calls = [
        "os.system(", "os.popen(", "subprocess.Popen(", "shell=True",
        'subprocess.run(["osascript"', "subprocess.run(['osascript'",
        'subprocess.run(["open"', "subprocess.run(['open'",
        'subprocess.run(["pkill"', "subprocess.run(['pkill'",
        "brew install", "brew upgrade", "brew update",
    ]
    for token in forbidden_calls:
        assert token not in source, f"engine_registry.py must never contain {token!r}"


def test_module_only_subprocess_call_targets_openscad_version():
    """The single `subprocess.run(` call site in this module must target
    the local `openscad` executable's `--version` flag - never any other
    tool, never a shell string."""
    source = inspect.getsource(engine_registry._probe_openscad)
    assert "subprocess.run(" in source
    assert '"--version"' in source
    assert "shell=True" not in source
    other_functions = [
        engine_registry._probe_cadquery,
        engine_registry._probe_app_or_path_binary,
    ]
    for func in other_functions:
        assert "subprocess" not in inspect.getsource(func)
    # `probe_all_tools()` only ever forwards its `include_version_subprocess`
    # flag to `_probe_openscad()` - it never calls `subprocess` itself.
    assert "subprocess.run(" not in inspect.getsource(engine_registry.probe_all_tools)


def test_module_never_imports_network_libraries():
    source = inspect.getsource(engine_registry)
    for token in ("import requests", "import urllib", "import socket", "import http.client"):
        assert token not in source, f"engine_registry.py must never contain {token!r}"

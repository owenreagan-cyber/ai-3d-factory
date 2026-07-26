"""Phase 38 tests: `factory.slicer_intelligence` - Slicer Review
Intelligence & Print Risk Analysis.

A deterministic, read-only analysis layer that identifies potential
slicer-review concerns before a human opens a slicer. Reuses
`factory.manual_review_workspace.assess_manual_review_workspace()` for
every printer/material/technical-readiness signal, and each STL's
already-written validation report (`mesh_stats`) for build-volume-fit and
geometry-risk analysis - never re-implements mesh validation or dimension
checks. Only reports risks supported by existing measurable data; never
slices, generates G-code, contacts a printer, or makes a network call.
See docs/slicer-intelligence.md, docs/roadmap.md Phase 38.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from factory import export_pipeline, project_store
from factory.manufacturing import knowledge
from factory.openscad.generate import generate_openscad
from factory.slicer import local_slicer_probe
from factory.slicer_intelligence import (
    ANALYSIS_STATES,
    BUILD_VOLUME_FIT_STATES,
    CONFIDENCE_LEVELS,
    RISK_LEVELS,
    _best_fit_margin,
    _build_volume_analysis,
    _geometry_risks_for_part,
    evaluate_slicer_intelligence,
    evaluate_slicer_intelligence_for_path,
    summarize_slicer_intelligence,
)

FAKE_OPENSCAD = "/fake/bin/openscad"

_DEGENERATE_TRIANGLE_STL = (
    b"solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid x\n"
)


def _box_stl(dx: float, dy: float, dz: float) -> bytes:
    """A minimal, valid, watertight ASCII STL box from (0,0,0) to
    (dx,dy,dz) - 12 triangles, used wherever a test needs a real
    measurable bounding box/volume rather than the default degenerate
    single-triangle fixture."""
    v = [
        (0, 0, 0), (dx, 0, 0), (dx, dy, 0), (0, dy, 0),
        (0, 0, dz), (dx, 0, dz), (dx, dy, dz), (0, dy, dz),
    ]
    faces = [
        (0, 1, 2), (0, 2, 3),  # bottom
        (4, 6, 5), (4, 7, 6),  # top
        (0, 5, 1), (0, 4, 5),  # front
        (1, 6, 2), (1, 5, 6),  # right
        (2, 7, 3), (2, 6, 7),  # back
        (3, 4, 0), (3, 7, 4),  # left
    ]
    lines = ["solid box"]
    for a, b, c in faces:
        lines.append("facet normal 0 0 0")
        lines.append("outer loop")
        for idx in (a, b, c):
            lines.append(f"vertex {v[idx][0]} {v[idx][1]} {v[idx][2]}")
        lines.append("endloop")
        lines.append("endfacet")
    lines.append("endsolid box")
    return ("\n".join(lines) + "\n").encode("ascii")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture()
def scad_project(isolated_projects_dir):
    root = project_store.init_project("Demo Sign")
    generate_openscad(root, "sign", "Hi")
    return root


@pytest.fixture()
def multipart_scad_project(isolated_projects_dir):
    root = project_store.init_project("Demo Multipart")
    generate_openscad(root, "multipart-nameplate", "Hi")
    return root


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_openscad_available(monkeypatch, executable=FAKE_OPENSCAD):
    monkeypatch.setattr(export_pipeline, "resolve_openscad_executable", lambda: executable)


def _fake_subprocess_writes_stl(monkeypatch, *, content=_DEGENERATE_TRIANGLE_STL):
    def _fake_run(command, capture_output, text, timeout):
        if "--version" in command:
            return _FakeCompleted(returncode=0, stdout="OpenSCAD version 2021.01 (fake)")
        output_path = Path(command[2])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(content)
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(export_pipeline.subprocess, "run", _fake_run)


def _export_all(project_dir, monkeypatch, *, content=_DEGENERATE_TRIANGLE_STL):
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch, content=content)
    plan = export_pipeline.plan_export(project_dir, confirm_export=True)
    return export_pipeline.run_export_pipeline(project_dir, plan, all_steps=True)


def _flesh_out_brief_for_manufacturing_review(project_dir):
    brief_path = project_dir / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["design_intent"] = {
        "quality_standard": "premium",
        "use_case": "classroom nameplate sign",
        "style_direction": ["clean", "modern"],
        "reference_inputs": ["Classroom sign example"],
        "manufacturability_constraints": {"max_size_mm": [120, 40, 5]},
    }
    project_store.save_json(brief_path, brief)
    project_store.save_json(
        project_dir / "reference_board.json",
        {
            "references": [
                {
                    "title": "Classroom sign example",
                    "source_type": "image",
                    "license": "public_domain",
                    "attached_to": "design_intent.reference_inputs",
                    "source_url": "https://example.com/sign",
                }
            ]
        },
    )


def _resolve_manufacturing(project_dir, *, option="single_piece", printer_id="bambu_h2d"):
    build_plan = project_store.load_json(project_dir / "build_plan.json")
    build_plan["selected_manufacturing_option"] = option
    printer = knowledge.get_printer(printer_id)
    build_plan["target_printer"] = {
        "printer_id": printer_id,
        "display_name": printer["display_name"] if printer else printer_id,
        "resolved": True,
        "resolved_from": "test",
        "capabilities": None,
    }
    project_store.save_json(project_dir / "build_plan.json", build_plan)


def _resolve_materials(project_dir, *, material="PLA", color="white"):
    manifest = project_store.load_json(project_dir / "part_manifest.json")
    for part in manifest.get("parts", []):
        part["material"] = material
        part["color"] = color
    project_store.save_json(project_dir / "part_manifest.json", manifest)


def _fully_ready(project_dir, monkeypatch, *, content=_DEGENERATE_TRIANGLE_STL, **resolve_kwargs):
    _flesh_out_brief_for_manufacturing_review(project_dir)
    _export_all(project_dir, monkeypatch, content=content)
    _resolve_manufacturing(project_dir, **resolve_kwargs)
    _resolve_materials(project_dir)
    return project_dir


# ---------------------------------------------------------------------------
# Vocabulary sanity
# ---------------------------------------------------------------------------


def test_analysis_states_are_the_suggested_values():
    assert set(ANALYSIS_STATES) == {"no_geometry_data", "partial_geometry_data", "full_geometry_data"}


def test_build_volume_fit_states_are_the_suggested_values():
    assert set(BUILD_VOLUME_FIT_STATES) == {"fits", "does_not_fit", "unknown"}


def test_confidence_and_risk_levels_are_the_suggested_values():
    assert set(CONFIDENCE_LEVELS) == {"High", "Medium", "Low", "Unknown"}
    assert set(RISK_LEVELS) == {"Low", "Moderate", "High", "Unknown"}


def test_module_reuses_existing_logic_not_reimplemented():
    source = Path("src/factory/slicer_intelligence.py").read_text(encoding="utf-8")
    assert "from factory.manual_review_workspace import assess_manual_review_workspace" in source
    assert "from factory.validators.dimension_check import check_build_volume_fit" in source
    assert "from factory.export_pipeline import read_export_receipt" in source
    # Never re-implements mesh validation or dimension checking directly.
    assert "def validate_mesh" not in source
    assert "def check_build_volume_fit" not in source
    assert "import trimesh" not in source


# ---------------------------------------------------------------------------
# evaluate_slicer_intelligence() - read-only, never writes
# ---------------------------------------------------------------------------


def test_writes_nothing(scad_project):
    before = sorted(str(p) for p in scad_project.rglob("*"))
    evaluate_slicer_intelligence(scad_project)
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


def test_dry_run_flags_always_true(scad_project):
    analysis = evaluate_slicer_intelligence(scad_project)
    assert analysis["dry_run"] is True
    assert analysis["no_automatic_print"] is True


def test_never_invokes_a_subprocess(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("evaluate_slicer_intelligence() must never invoke a subprocess")

    monkeypatch.setattr(export_pipeline.subprocess, "run", _boom)
    evaluate_slicer_intelligence(scad_project)


def test_never_launches_a_slicer(scad_project, monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("must never launch a slicer binary")

    monkeypatch.setattr(export_pipeline.subprocess, "Popen", _boom, raising=False)
    _fully_ready(scad_project, monkeypatch)
    evaluate_slicer_intelligence(scad_project)


def test_no_stl_is_no_geometry_data(scad_project):
    analysis = evaluate_slicer_intelligence(scad_project)
    assert analysis["analysis_status"] == "no_geometry_data"
    assert analysis["confidence"] == "Unknown"


def test_evaluate_for_path_matches_direct_call(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    a = evaluate_slicer_intelligence(scad_project)
    b = evaluate_slicer_intelligence_for_path(scad_project)
    assert a == b


# ---------------------------------------------------------------------------
# Build volume analysis
# ---------------------------------------------------------------------------


def test_build_volume_fit_with_resolved_printer(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch, content=_box_stl(100, 60, 10), printer_id="bambu_h2d")
    analysis = evaluate_slicer_intelligence(scad_project)
    bva = analysis["build_volume_analysis"]
    assert bva["fit_status"] == "fits"
    assert bva["printer_display_name"] == "Bambu Lab H2D"
    assert bva["remaining_margin_mm"] is not None
    # H2D build volume is 350x320x325mm; a 100x60x10 box fits comfortably.
    assert bva["remaining_margin_mm"]["x"] > 0
    assert bva["remaining_margin_mm"]["y"] > 0
    assert bva["remaining_margin_mm"]["z"] > 0


def test_build_volume_unknown_without_resolved_printer(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch, content=_box_stl(100, 60, 10))
    analysis = evaluate_slicer_intelligence(scad_project)
    bva = analysis["build_volume_analysis"]
    assert bva["fit_status"] == "unknown"
    assert bva["remaining_margin_mm"] is None
    assert bva["parts"][0]["detail"] == "No resolved printer with a known build volume"


def test_build_volume_unknown_when_bbox_missing(scad_project, monkeypatch):
    _flesh_out_brief_for_manufacturing_review(scad_project)
    _export_all(scad_project, monkeypatch)
    _resolve_manufacturing(scad_project)
    # Corrupt the validation report so mesh_stats/bounding_box_mm is unreadable.
    validation_files = list((scad_project / "validation").glob("*.json"))
    assert validation_files
    validation_files[0].write_text("{not valid json", encoding="utf-8")
    analysis = evaluate_slicer_intelligence(scad_project)
    assert analysis["build_volume_analysis"]["parts"][0]["fit_status"] == "unknown"


def test_build_volume_does_not_fit_is_never_invented_but_computed_from_real_bbox(scad_project, monkeypatch):
    # A part far larger than any printer's build volume in every axis.
    _fully_ready(scad_project, monkeypatch, content=_box_stl(1000, 1000, 1000), printer_id="bambu_h2d")
    analysis = evaluate_slicer_intelligence(scad_project)
    bva = analysis["build_volume_analysis"]
    assert bva["fit_status"] == "does_not_fit"
    assert bva["parts"][0]["remaining_margin_mm"] is None
    assert analysis["risk_level"] == "High"


def test_build_volume_analysis_reports_printer_verified_flag(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch, content=_box_stl(100, 60, 10), printer_id="bambu_h2d")
    analysis = evaluate_slicer_intelligence(scad_project)
    # Every printer in this repo's local knowledge base is currently
    # "verified": false (placeholder specs) - see config/manufacturing/printers.json.
    assert analysis["build_volume_analysis"]["printer_verified"] is False
    assert any("unverified" in a for a in analysis["advisories"])


def test_best_fit_margin_picks_the_orientation_with_largest_minimum_margin():
    bbox = {"x": 10, "y": 300, "z": 50}
    build_volume = {"x": 350, "y": 320, "z": 325}
    margin = _best_fit_margin(bbox, build_volume)
    assert margin is not None
    assert min(margin.values()) >= 0


def test_best_fit_margin_returns_none_when_nothing_fits():
    bbox = {"x": 1000, "y": 1000, "z": 1000}
    build_volume = {"x": 350, "y": 320, "z": 325}
    assert _best_fit_margin(bbox, build_volume) is None


def test_build_volume_analysis_never_invents_a_dimension_directly():
    printer_summary = {"resolved": False, "printer_id": None, "display_name": "Unknown", "build_volume_mm": "Unknown"}
    result = _build_volume_analysis(printer_summary, [{"part_file": "stl/part.stl", "mesh_stats": None}])
    assert result["fit_status"] == "unknown"
    assert result["remaining_margin_mm"] is None


# ---------------------------------------------------------------------------
# Geometry risk analysis - direct unit tests (white-box, matching the
# established precedent for testing deterministic helper functions with
# synthetic inputs) plus real end-to-end coverage for Large Flat Areas.
# ---------------------------------------------------------------------------


def test_large_flat_area_detected_end_to_end(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch, content=_box_stl(160, 100, 5))
    analysis = evaluate_slicer_intelligence(scad_project)
    categories = [r["category"] for r in analysis["geometry_risks"]]
    assert "Large Flat Areas" in categories


def test_tall_narrow_geometry_detected_directly():
    mesh_stats = {"bounding_box_mm": {"x": 10, "y": 10, "z": 60}, "volume_mm3": None, "is_watertight": None}
    risks = _geometry_risks_for_part("stl/part.stl", mesh_stats)
    assert any(r["category"] == "Tall Narrow Geometry" for r in risks)


def test_small_part_tall_aspect_ratio_not_flagged():
    # Below the minimum-height threshold - a tiny tall/narrow boss should
    # not be flagged just because its aspect ratio looks dramatic.
    mesh_stats = {"bounding_box_mm": {"x": 2, "y": 2, "z": 10}, "volume_mm3": None, "is_watertight": None}
    risks = _geometry_risks_for_part("stl/part.stl", mesh_stats)
    assert not any(r["category"] == "Tall Narrow Geometry" for r in risks)


def test_thin_feature_low_fill_ratio_detected_directly():
    mesh_stats = {
        "bounding_box_mm": {"x": 100, "y": 100, "z": 100},
        "volume_mm3": 50_000,  # 5% of the 1,000,000 mm^3 bounding box
        "is_watertight": True,
    }
    risks = _geometry_risks_for_part("stl/part.stl", mesh_stats)
    assert any(r["category"] == "Thin Features" for r in risks)


def test_high_fill_ratio_solid_box_not_flagged_thin():
    mesh_stats = {
        "bounding_box_mm": {"x": 100, "y": 60, "z": 10},
        "volume_mm3": 100 * 60 * 10 * 0.95,
        "is_watertight": True,
    }
    risks = _geometry_risks_for_part("stl/part.stl", mesh_stats)
    assert not any(r["category"] == "Thin Features" for r in risks)


def test_non_watertight_mesh_flags_fragile_features_directly():
    mesh_stats = {"bounding_box_mm": {"x": 50, "y": 50, "z": 50}, "volume_mm3": None, "is_watertight": False}
    risks = _geometry_risks_for_part("stl/part.stl", mesh_stats)
    assert any(r["category"] == "Fragile Features" for r in risks)


def test_geometry_risks_never_claims_print_failure():
    mesh_stats = {"bounding_box_mm": {"x": 10, "y": 10, "z": 60}, "volume_mm3": None, "is_watertight": False}
    risks = _geometry_risks_for_part("stl/part.stl", mesh_stats)
    assert risks
    for risk in risks:
        assert "will fail" not in risk["message"].lower()
        assert "possible risk" in risk["message"].lower()


def test_multipart_alignment_flagged_end_to_end(multipart_scad_project, monkeypatch):
    _fully_ready(multipart_scad_project, monkeypatch)
    analysis = evaluate_slicer_intelligence(multipart_scad_project)
    categories = [r["category"] for r in analysis["geometry_risks"]]
    assert "Multi-part Alignment" in categories


def test_single_part_excludes_multipart_alignment(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    analysis = evaluate_slicer_intelligence(scad_project)
    categories = [r["category"] for r in analysis["geometry_risks"]]
    assert "Multi-part Alignment" not in categories


# ---------------------------------------------------------------------------
# Manufacturing risks / material analysis
# ---------------------------------------------------------------------------


def test_unknown_printer_reports_manufacturing_risk(scad_project, monkeypatch):
    _flesh_out_brief_for_manufacturing_review(scad_project)
    _export_all(scad_project, monkeypatch)
    analysis = evaluate_slicer_intelligence(scad_project)
    categories = [r["category"] for r in analysis["manufacturing_risks"]]
    assert "Printer" in categories


def test_unresolved_material_reports_unresolved_status(scad_project, monkeypatch):
    _flesh_out_brief_for_manufacturing_review(scad_project)
    _export_all(scad_project, monkeypatch)
    _resolve_manufacturing(scad_project)
    _resolve_materials(scad_project, material="TBD - human decision", color="TBD - human decision")
    analysis = evaluate_slicer_intelligence(scad_project)
    statuses = {entry["status"] for entry in analysis["material"]}
    assert "unresolved" in statuses
    categories = [r["category"] for r in analysis["manufacturing_risks"]]
    assert "Material" in categories


def test_known_material_reports_known_status(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    analysis = evaluate_slicer_intelligence(scad_project)
    assert all(entry["status"] == "known" for entry in analysis["material"])


def test_unrecognized_material_string_reports_unknown_material_status(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    _resolve_materials(scad_project, material="Some Exotic Filament Nobody Has Heard Of")
    analysis = evaluate_slicer_intelligence(scad_project)
    assert any(entry["status"] == "unknown_material" for entry in analysis["material"])
    assert any("not recognized" in w for w in analysis["warnings"])


def test_material_analysis_never_invents_settings(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    analysis = evaluate_slicer_intelligence(scad_project)
    for entry in analysis["material"]:
        assert set(entry.keys()) == {"part_name", "material", "status"}


# ---------------------------------------------------------------------------
# Multi-material considerations - reviewed, never calculated/optimized
# ---------------------------------------------------------------------------


def test_multi_material_considerations_present_for_ams_printer(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch, printer_id="bambu_h2d")
    analysis = evaluate_slicer_intelligence(scad_project)
    assert analysis["multi_material_considerations"]


def test_multi_material_considerations_absent_for_non_ams_single_material(scad_project, monkeypatch):
    non_ams_id = next(
        (pid for pid, p in knowledge.load_printers().items() if not p.get("ams_supported")), None
    )
    if non_ams_id is None:
        pytest.skip("no non-AMS printer available in the local knowledge base")
    _fully_ready(scad_project, monkeypatch, printer_id=non_ams_id)
    analysis = evaluate_slicer_intelligence(scad_project)
    assert analysis["multi_material_considerations"] == []


def test_multi_material_considerations_never_calculate_purge_or_modify_assignments():
    from factory.slicer_intelligence import _multi_material_considerations

    considerations = _multi_material_considerations(
        {"ams_available": True}, {"multi_material": True, "unresolved_material_parts": [], "unresolved_color_parts": []}
    )
    joined = " ".join(considerations).lower()
    assert "purge" not in joined or "calculate" not in joined
    for item in considerations:
        assert "assign" not in item.lower() or item.lower().startswith("review")


# ---------------------------------------------------------------------------
# Orientation / support / adhesion considerations - review prompts only,
# never a prescribed single orientation, never a computed support plan.
# ---------------------------------------------------------------------------


def test_orientation_considerations_are_generic_prompts_not_a_prescribed_orientation(scad_project):
    analysis = evaluate_slicer_intelligence(scad_project)
    for item in analysis["orientation_considerations"]:
        assert item.lower().startswith("review")


def test_support_considerations_absent_without_geometry_data(scad_project):
    analysis = evaluate_slicer_intelligence(scad_project)
    assert analysis["support_considerations"] == []


def test_support_considerations_present_with_geometry_data(scad_project, monkeypatch):
    _export_all(scad_project, monkeypatch)
    analysis = evaluate_slicer_intelligence(scad_project)
    assert analysis["support_considerations"]
    for item in analysis["support_considerations"]:
        assert "calculate" not in item.lower()


def test_adhesion_considerations_present_only_when_large_flat_area_found(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch, content=_box_stl(160, 100, 5))
    analysis = evaluate_slicer_intelligence(scad_project)
    assert analysis["adhesion_considerations"]


def test_adhesion_considerations_absent_without_large_flat_area(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch, content=_box_stl(20, 20, 20))
    analysis = evaluate_slicer_intelligence(scad_project)
    assert analysis["adhesion_considerations"] == []


# ---------------------------------------------------------------------------
# Confidence / risk scoring - deterministic, informational only
# ---------------------------------------------------------------------------


def test_confidence_high_with_full_geometry_data(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch, content=_box_stl(100, 60, 10))
    analysis = evaluate_slicer_intelligence(scad_project)
    assert analysis["analysis_status"] == "full_geometry_data"
    assert analysis["confidence"] == "High"


def test_confidence_low_with_partial_geometry_data(multipart_scad_project, monkeypatch):
    _flesh_out_brief_for_manufacturing_review(multipart_scad_project)
    _fake_openscad_available(monkeypatch)
    _fake_subprocess_writes_stl(monkeypatch)
    plan = export_pipeline.plan_export(multipart_scad_project, confirm_export=True)
    export_pipeline.run_export_pipeline(multipart_scad_project, plan, all_steps=True)
    # Corrupt exactly one of the (multiple) validation reports.
    validation_files = sorted((multipart_scad_project / "validation").glob("*.json"))
    assert len(validation_files) > 1
    validation_files[0].write_text("{not valid json", encoding="utf-8")
    analysis = evaluate_slicer_intelligence(multipart_scad_project)
    assert analysis["analysis_status"] == "partial_geometry_data"
    assert analysis["confidence"] == "Low"


def test_risk_level_is_deterministic(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    a = evaluate_slicer_intelligence(scad_project)
    b = evaluate_slicer_intelligence(scad_project)
    assert a["risk_level"] == b["risk_level"]
    assert a["review_priority"] == b["review_priority"]


def test_risk_level_never_blocks_readiness_or_review_gate(scad_project, monkeypatch):
    """risk_level is purely informational - factory.slicer_readiness's own
    readiness_status must be entirely unaffected by anything this module
    computes."""
    from factory.slicer_readiness import assess_slicer_readiness

    _fully_ready(scad_project, monkeypatch, content=_box_stl(1000, 1000, 1000))  # would report does_not_fit / High risk
    analysis = evaluate_slicer_intelligence(scad_project)
    assert analysis["risk_level"] == "High"
    readiness = assess_slicer_readiness(scad_project)
    # Readiness only cares about Review Gate/validation/manifest state -
    # never about slicer_intelligence's own build-volume-fit finding.
    assert readiness["readiness_status"] != "blocked" or "does_not_fit" not in str(readiness.get("blockers"))


def test_review_priority_lists_manufacturing_risks_before_geometry_risks(scad_project, monkeypatch):
    _flesh_out_brief_for_manufacturing_review(scad_project)
    _export_all(scad_project, monkeypatch, content=_box_stl(160, 100, 5))
    analysis = evaluate_slicer_intelligence(scad_project)
    priorities = analysis["review_priority"]
    manufacturing_messages = {r["message"] for r in analysis["manufacturing_risks"]}
    geometry_messages = {r["message"] for r in analysis["geometry_risks"]}
    if manufacturing_messages and geometry_messages:
        last_manufacturing_index = max(priorities.index(m) for m in manufacturing_messages if m in priorities)
        first_geometry_index = min(priorities.index(g) for g in geometry_messages if g in priorities)
        assert last_manufacturing_index < first_geometry_index


# ---------------------------------------------------------------------------
# Local slicer detection - reused from Phase 36/37, never re-implemented
# ---------------------------------------------------------------------------


def test_slicer_probe_reused_not_reimplemented(scad_project):
    analysis = evaluate_slicer_intelligence(scad_project)
    assert analysis["detected_slicers"] == local_slicer_probe.probe_slicers()


# ---------------------------------------------------------------------------
# summarize_slicer_intelligence() - the compact Preview Board summary
# ---------------------------------------------------------------------------


def test_summarize_is_read_only(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    before = sorted(str(p) for p in scad_project.rglob("*"))
    summarize_slicer_intelligence(scad_project)
    after = sorted(str(p) for p in scad_project.rglob("*"))
    assert before == after


def test_summarize_shape(scad_project, monkeypatch):
    _fully_ready(scad_project, monkeypatch)
    summary = summarize_slicer_intelligence(scad_project)
    assert set(summary.keys()) == {
        "risk_level", "build_volume_fit", "review_item_count", "top_priority", "confidence", "warning_count",
    }

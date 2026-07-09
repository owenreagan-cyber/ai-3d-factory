"""Phase 33 tests: `factory.design_orchestrator` - the local, fully
deterministic Design Orchestrator. No AI, no LLM, no network, no CAD
generation - it only evaluates whether a project is sufficiently defined
to proceed and recommends a downstream engine. See
docs/design-orchestrator.md, docs/roadmap.md Phase 33.
"""

import inspect
import tempfile
from pathlib import Path

import pytest

from factory import design_orchestrator, project_store
from factory.design_orchestrator import (
    CATEGORY_WEIGHTS,
    READINESS_STATES,
    RECOMMENDED_ENGINES,
    compute_design_signals,
    compute_readiness_score,
    determine_readiness_state,
    evaluate_project_readiness,
    evaluate_readiness_for_path,
    generate_readiness_advisories,
    recommend_engine,
)

BENCHMARK_PATH = project_store.REPO_ROOT / "examples" / "intake-benchmarks" / "teacher-nameplate.md"


def _analyze_text(text: str) -> Path:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False)
    f.write(text)
    f.close()
    return Path(f.name)


def _readiness_for_text(text: str) -> dict:
    path = _analyze_text(text)
    try:
        return evaluate_readiness_for_path(path)
    finally:
        path.unlink()


# ---- vocabulary sanity ----


def test_readiness_states_are_the_seven_required_values():
    assert set(READINESS_STATES) == {
        "Not Ready", "Needs Information", "Ready For Mechanical CAD",
        "Ready For Organic Modeling", "Ready For Mixed Workflow",
        "Ready For Manufacturing Review", "Blocked",
    }


def test_recommended_engines_include_all_required_values():
    assert set(RECOMMENDED_ENGINES) == {
        "OpenSCAD", "Blender", "Meshy (Concept Only)", "CadQuery", "FreeCAD",
        "Hybrid Workflow", "Manual Design", "Unknown",
    }


def test_category_weights_sum_to_one():
    assert abs(sum(CATEGORY_WEIGHTS.values()) - 1.0) < 1e-9


def test_category_weights_cover_all_five_categories():
    assert set(CATEGORY_WEIGHTS.keys()) == {"intake", "brief", "design_intent", "reference_board", "manufacturing"}


# ---- worked examples: engine recommendation ----


def test_mechanical_organizer_recommends_openscad():
    result = _readiness_for_text("A mechanical organizer for my desk, made of PLA on a Bambu printer.")
    assert result["recommended_engine"] == "OpenSCAD"


def test_teacher_nameplate_recommends_openscad():
    result = _readiness_for_text("A teacher desk nameplate for my classroom, made of PLA.")
    assert result["recommended_engine"] == "OpenSCAD"


def test_committed_teacher_nameplate_benchmark_recommends_openscad():
    # The real, committed Phase 30 benchmark - contains "anime"-inspired
    # lettering style keywords alongside a strong "sign" category; a single
    # incidental style word must not override a confident category match.
    result = evaluate_readiness_for_path(BENCHMARK_PATH)
    assert result["recommended_engine"] == "OpenSCAD"
    assert result["readiness_state"] != "Ready For Mixed Workflow"


def test_storage_bin_recommends_openscad():
    result = _readiness_for_text("A storage bin for the garage.")
    assert result["recommended_engine"] == "OpenSCAD"


def test_replacement_bracket_recommends_cadquery():
    result = _readiness_for_text("A replacement bracket for my broken shelf mount.")
    assert result["recommended_engine"] == "CadQuery"


def test_anime_figure_recommends_organic_engine():
    result = _readiness_for_text("An anime-inspired figure for display.")
    assert result["recommended_engine"] in ("Blender", "Meshy (Concept Only)")


def test_organic_collectible_recommends_organic_engine():
    result = _readiness_for_text("A cute, ornate organic collectible sculpture.")
    assert result["recommended_engine"] in ("Blender", "Meshy (Concept Only)")


def test_mechanical_with_strong_decorative_organic_section_recommends_hybrid():
    result = _readiness_for_text("A mechanical mount with an ornate, decorative organic section.")
    assert result["recommended_engine"] == "Hybrid Workflow"
    assert result["readiness_state"] == "Ready For Mixed Workflow" or result["score"]["overall"] < 60


def test_organic_project_with_real_definition_recommends_blender_not_meshy(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    project_dir = project_store.init_project("Piggy Bank")
    brief_path = project_dir / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["description"] = (
        "A cute piggy bank coin bank, designer-toy style, ceramic-smooth finish, gift-quality, "
        "printed in PLA on a Bambu printer, roughly 120mm tall."
    )
    brief["design_intent"] = {
        "quality_standard": "Etsy-worthy",
        "use_case": "everyday coin storage that is also a display-worthy object",
        "style_direction": ["cute", "designer-toy", "ceramic-smooth"],
        "manufacturability_constraints": {"max_size_mm": [120, 100, 100]},
    }
    project_store.save_json(brief_path, brief)
    project_store.save_json(
        project_dir / "reference_board.json",
        {
            "references": [
                {
                    "title": "Pig photo",
                    "source_type": "inspiration",
                    "license": "personal_use",
                    "usage_intent": "style_reference",
                    "attached_to": "design_intent.reference_inputs",
                    "source_url": "https://example.com/pig",
                }
            ]
        },
    )

    result = evaluate_readiness_for_path(project_dir)
    assert result["recommended_engine"] == "Blender"
    assert result["readiness_state"] == "Ready For Organic Modeling"


def test_sparse_organic_idea_recommends_meshy_concept_only():
    result = _readiness_for_text("A cute piggy bank coin bank, designer-toy style.")
    assert result["recommended_engine"] == "Meshy (Concept Only)"


# ---- blocked / manufacturability ----


def test_blocked_when_manufacturability_fits_no_known_printers(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    project_dir = project_store.init_project("Huge Sign")
    brief_path = project_dir / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["design_intent"] = {
        "quality_standard": "Etsy-worthy",
        "manufacturability_constraints": {"max_size_mm": [10000, 10000, 10000]},
    }
    project_store.save_json(brief_path, brief)

    result = evaluate_readiness_for_path(project_dir)
    assert result["readiness_state"] == "Blocked"
    assert result["recommended_engine"] == "Manual Design"


# ---- missing information ----


def test_empty_input_is_not_ready_and_unknown_engine():
    result = _readiness_for_text("")
    assert result["readiness_state"] == "Not Ready"
    assert result["recommended_engine"] == "Unknown"
    assert result["score"]["overall"] == 0


def test_missing_information_advisories_present_for_sparse_input():
    result = _readiness_for_text("A small box.")
    assert "Human approval required" in result["advisories"]


# ---- readiness score ----


def test_score_shape():
    result = _readiness_for_text("A sign for my desk.")
    assert set(result["score"].keys()) == {"overall", "categories"}
    assert set(result["score"]["categories"].keys()) == {
        "intake", "brief", "design_intent", "reference_board", "manufacturing",
    }
    for value in result["score"]["categories"].values():
        assert 0 <= value <= 100
    assert 0 <= result["score"]["overall"] <= 100


def test_compute_readiness_score_all_none_is_zero():
    score = compute_readiness_score(None, None, None, None, None)
    assert score["overall"] == 0
    assert all(v == 0 for v in score["categories"].values())


def test_compute_readiness_score_full_intake_gives_full_intake_category():
    draft_brief_summary = {"readiness": {"percent_populated": 100}}
    score = compute_readiness_score(None, draft_brief_summary, None, None, None)
    assert score["categories"]["intake"] == 100


def test_compute_readiness_score_brief_category_from_fields_preserved():
    brief_update_summary = {"fields_preserved_count": 4, "fields_to_add_count": 4}
    score = compute_readiness_score(None, None, brief_update_summary, None, None)
    assert score["categories"]["brief"] == 50  # 4/8


def test_compute_readiness_score_design_intent_category():
    design_intent_detail = {
        "quality_standard": "Etsy-worthy",
        "use_case": "a gift",
        "style_direction": ["cute"],
        "manufacturability_result": "fits_some_printers",
    }
    score = compute_readiness_score(None, None, None, design_intent_detail, None)
    assert score["categories"]["design_intent"] == 100


def test_compute_readiness_score_reference_board_category():
    reference_board_summary = {
        "reference_count": 1,
        "attached_to_design_intent_count": 1,
        "warnings": [],
    }
    score = compute_readiness_score(None, None, None, None, reference_board_summary)
    assert score["categories"]["reference_board"] == 100


def test_compute_readiness_score_manufacturing_category():
    intake_summary = {
        "printer_assumptions": {"value": ["Bambu"], "confidence": "high"},
        "material_assumptions": {"value": ["PLA"], "confidence": "high"},
        "manufacturing_style": {"value": [], "confidence": "unknown"},
        "dimensional_constraints": {"value": [], "confidence": "unknown"},
    }
    score = compute_readiness_score(intake_summary, None, None, None, None)
    assert score["categories"]["manufacturing"] == 50  # 2/4


def test_readiness_score_never_raises_on_malformed_inputs():
    compute_readiness_score("not a dict", 123, [], "x", None)  # must not raise


# ---- readiness state gating ----


def test_not_ready_below_25_percent():
    score = {"overall": 10, "categories": {"design_intent": 0, "reference_board": 0}}
    signals = {"has_organic_signal": False, "has_mechanical_signal": False, "is_mixed": False, "organic_strength": 0, "mechanical_strength": 0}
    state = determine_readiness_state(score, blocked=False, signals=signals, design_intent_detail=None, reference_board_summary=None)
    assert state == "Not Ready"


def test_needs_information_between_25_and_60():
    score = {"overall": 40, "categories": {"design_intent": 0, "reference_board": 0}}
    signals = {"has_organic_signal": False, "has_mechanical_signal": False, "is_mixed": False, "organic_strength": 0, "mechanical_strength": 0}
    state = determine_readiness_state(score, blocked=False, signals=signals, design_intent_detail=None, reference_board_summary=None)
    assert state == "Needs Information"


def test_ready_for_mechanical_cad_above_60_with_mechanical_signal():
    score = {"overall": 65, "categories": {"design_intent": 0, "reference_board": 0}}
    signals = {"has_organic_signal": False, "has_mechanical_signal": True, "is_mixed": False, "organic_strength": 0, "mechanical_strength": 2}
    state = determine_readiness_state(score, blocked=False, signals=signals, design_intent_detail=None, reference_board_summary=None)
    assert state == "Ready For Mechanical CAD"


def test_ready_for_organic_modeling_above_60_with_organic_signal():
    score = {"overall": 65, "categories": {"design_intent": 0, "reference_board": 0}}
    signals = {"has_organic_signal": True, "has_mechanical_signal": False, "is_mixed": False, "organic_strength": 2, "mechanical_strength": 0}
    state = determine_readiness_state(score, blocked=False, signals=signals, design_intent_detail=None, reference_board_summary=None)
    assert state == "Ready For Organic Modeling"


def test_ready_for_mixed_workflow_when_mixed():
    score = {"overall": 65, "categories": {"design_intent": 0, "reference_board": 0}}
    signals = {"has_organic_signal": True, "has_mechanical_signal": True, "is_mixed": True, "organic_strength": 2, "mechanical_strength": 2}
    state = determine_readiness_state(score, blocked=False, signals=signals, design_intent_detail=None, reference_board_summary=None)
    assert state == "Ready For Mixed Workflow"


def test_ready_for_manufacturing_review_when_near_complete():
    score = {"overall": 95, "categories": {"design_intent": 100, "reference_board": 100}}
    signals = {"has_organic_signal": False, "has_mechanical_signal": True, "is_mixed": False, "organic_strength": 0, "mechanical_strength": 2}
    state = determine_readiness_state(score, blocked=False, signals=signals, design_intent_detail=None, reference_board_summary=None)
    assert state == "Ready For Manufacturing Review"


def test_blocked_overrides_everything():
    score = {"overall": 95, "categories": {"design_intent": 100, "reference_board": 100}}
    signals = {"has_organic_signal": True, "has_mechanical_signal": True, "is_mixed": True, "organic_strength": 2, "mechanical_strength": 2}
    state = determine_readiness_state(score, blocked=True, signals=signals, design_intent_detail=None, reference_board_summary=None)
    assert state == "Blocked"


def test_needs_information_fallback_when_no_signal_but_score_passes_gate():
    score = {"overall": 65, "categories": {"design_intent": 0, "reference_board": 0}}
    signals = {"has_organic_signal": False, "has_mechanical_signal": False, "is_mixed": False, "organic_strength": 0, "mechanical_strength": 0}
    state = determine_readiness_state(score, blocked=False, signals=signals, design_intent_detail=None, reference_board_summary=None)
    assert state == "Needs Information"


# ---- compute_design_signals() ----


def test_compute_design_signals_single_style_word_does_not_trigger_mixed():
    intake_summary = {"category": {"value": "sign", "confidence": "high"}, "visual_goals": {"value": ["anime"], "confidence": "medium"}}
    signals = compute_design_signals(intake_summary, None)
    assert signals["has_mechanical_signal"] is True
    assert signals["is_mixed"] is False


def test_compute_design_signals_two_organic_words_against_category_triggers_mixed():
    intake_summary = {
        "category": {"value": "fixture", "confidence": "high"},
        "visual_goals": {"value": ["ornate", "decorative"], "confidence": "high"},
    }
    signals = compute_design_signals(intake_summary, None)
    assert signals["is_mixed"] is True


def test_compute_design_signals_unknown_category_no_keywords_is_neither():
    signals = compute_design_signals({}, None)
    assert signals["has_organic_signal"] is False
    assert signals["has_mechanical_signal"] is False
    assert signals["is_mixed"] is False


# ---- advisories ----


def test_advisories_always_end_with_human_approval_required():
    advisories = generate_readiness_advisories(None, None, None, {"categories": {"design_intent": 0, "manufacturing": 0}})
    assert advisories[-1] == "Human approval required"


def test_advisories_dimensions_material_printer_missing():
    intake_summary = {
        "dimensional_constraints": {"confidence": "unknown"},
        "material_assumptions": {"confidence": "unknown"},
        "printer_assumptions": {"confidence": "unknown"},
    }
    advisories = generate_readiness_advisories(intake_summary, None, None, {"categories": {"design_intent": 0, "manufacturing": 0}})
    assert "Dimensions missing" in advisories
    assert "Material unspecified" in advisories
    assert "Printer unspecified" in advisories


def test_advisories_commercial_review_recommended():
    intake_summary = {"commercial_intent": {"value": True, "confidence": "high"}}
    advisories = generate_readiness_advisories(intake_summary, None, None, {"categories": {"design_intent": 100, "manufacturing": 100}})
    assert "Commercial review recommended" in advisories


def test_advisories_reference_images_recommended_for_high_quality_bar():
    intake_summary = {"quality_target": {"value": "etsy-worthy", "confidence": "high"}}
    advisories = generate_readiness_advisories(intake_summary, None, {"reference_count": 0}, {"categories": {"design_intent": 100, "manufacturing": 100}})
    assert "Reference images recommended" in advisories


def test_advisories_never_raises_on_missing_inputs():
    generate_readiness_advisories(None, None, None, {"categories": {"design_intent": 0, "manufacturing": 0}})


# ---- evaluate_project_readiness(): shape / determinism ----


def test_evaluate_project_readiness_shape():
    result = evaluate_project_readiness(None, None, None, None, None, None)
    assert set(result.keys()) == {"readiness_state", "recommended_engine", "engine_rationale", "score", "advisories"}
    assert result["readiness_state"] in READINESS_STATES
    assert result["recommended_engine"] in RECOMMENDED_ENGINES


def test_evaluate_project_readiness_is_deterministic():
    from factory.project_intake import analyze

    intake = analyze(BENCHMARK_PATH)
    from factory.brief_generator import summarize_draft_brief

    draft_brief_summary = summarize_draft_brief(intake)
    a = evaluate_project_readiness(intake, draft_brief_summary, None, None, None, None)
    b = evaluate_project_readiness(intake, draft_brief_summary, None, None, None, None)
    assert a == b


def test_evaluate_project_readiness_never_raises_on_all_none():
    evaluate_project_readiness(None, None, None, None, None, None)


# ---- evaluate_readiness_for_path(): real repo examples ----


def test_evaluate_readiness_for_storage_bin_lid():
    result = evaluate_readiness_for_path(project_store.REPO_ROOT / "examples" / "storage-bin-lid")
    assert result["readiness_state"] in READINESS_STATES
    assert result["recommended_engine"] in RECOMMENDED_ENGINES


def test_evaluate_readiness_for_nonexistent_path_does_not_crash(tmp_path):
    result = evaluate_readiness_for_path(tmp_path / "does-not-exist")
    assert result["readiness_state"] == "Not Ready"


def test_evaluate_readiness_for_path_writes_no_files(tmp_path):
    before = sorted(p.name for p in tmp_path.iterdir())
    evaluate_readiness_for_path(tmp_path)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after


# ---- module hygiene: reuses factory.router, never duplicates parsing ----


def test_module_reuses_router_recommend_tool_not_a_second_keyword_table():
    source = inspect.getsource(design_orchestrator)
    assert "from factory.router import" in source
    assert "recommend_tool(" in source


def test_module_never_calls_extract_intake_fields_or_summarize_project():
    # design_orchestrator.py must never import factory.project_inspection
    # (that would be circular - project_inspection imports this module, not
    # the other way around) or re-run Phase 30's text extraction. Doc
    # comments referencing "factory.project_inspection.summarize_project()"
    # by name are fine (and expected); an actual import/call is not.
    source = inspect.getsource(design_orchestrator)
    assert "extract_intake_fields(" not in source
    assert "import factory.project_inspection" not in source
    assert "from factory.project_inspection" not in source
    assert "from factory import project_inspection" not in source


def test_module_has_no_forbidden_network_or_ai_or_cad_execution_calls():
    # "cadquery"/"FreeCAD" as plain words are expected (they're entries in
    # RECOMMENDED_ENGINES and rationale text) - only an actual
    # import/invocation would be forbidden.
    forbidden = (
        "import subprocess", "subprocess.run(", "subprocess.call(", "subprocess.Popen(",
        "os.system(", "os.popen(", "socket.", "import urllib", "import requests",
        "http.client", "urlopen(", "requests.get(", "requests.post(",
        "openai", "anthropic", "import cadquery", "import FreeCAD", "import bpy", "openscad_exec",
    )
    source = inspect.getsource(design_orchestrator)
    for forbidden_call in forbidden:
        assert forbidden_call not in source, f"found forbidden call {forbidden_call!r}"


def test_module_writes_no_files_ever():
    source = inspect.getsource(design_orchestrator)
    assert "save_json(" not in source
    assert "write_text(" not in source
    assert "write_bytes(" not in source


def test_module_does_not_set_human_approved_or_print_ready():
    source = inspect.getsource(design_orchestrator)
    assert '"human_approved"' not in source
    assert '"print_ready"' not in source

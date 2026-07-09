"""Phase 31 tests: `factory.brief_generator` - the local, fully deterministic
Intake-to-Brief Draft Generation engine. No AI, no LLM, no network - shapes
an already-computed `intake_summary` (Phase 30) into a human-reviewable
draft, never re-parsing free text itself. See docs/brief-generator.md,
docs/roadmap.md Phase 31.
"""

import inspect

import jsonschema
import pytest

from factory import brief_generator, project_intake, project_store
from factory.brief_generator import (
    BriefAlreadyExistsError,
    MalformedIntakeSummaryError,
    ProjectDirectoryNotFoundError,
    build_brief_json,
    compute_readiness,
    generate_advisories,
    generate_draft,
    generate_draft_brief,
    generate_draft_design_intent,
    generate_manufacturing_notes,
    load_intake_summary_from_path,
    summarize_draft_brief,
    write_draft_brief,
)
from factory.project_intake import analyze, extract_intake_fields

BENCHMARK_PATH = project_store.REPO_ROOT / "examples" / "intake-benchmarks" / "teacher-nameplate.md"


def _field(value, confidence):
    return {"value": value, "confidence": confidence}


def _empty_intake():
    return extract_intake_fields("")


# ---- compute_readiness() ----


def test_readiness_all_unknown_intake():
    readiness = compute_readiness(_empty_intake())
    assert readiness["status"] == "Ready"
    assert readiness["percent_populated"] == 0
    assert readiness["unknown_count"] == 13
    assert readiness["total_fields"] == 13
    assert readiness["human_review_required"] is True


def test_readiness_benchmark_matches_expected_85_percent():
    intake = analyze(BENCHMARK_PATH)
    readiness = compute_readiness(intake)
    assert readiness["percent_populated"] == 85
    assert readiness["unknown_count"] == 2
    assert readiness["populated_count"] == 11


def test_readiness_fully_populated_intake_is_100_percent():
    intake = {name: _field("x" if name != "commercial_intent" else True, "high") for name in brief_generator._TRACKED_FIELDS}
    readiness = compute_readiness(intake)
    assert readiness["percent_populated"] == 100
    assert readiness["unknown_count"] == 0


def test_readiness_medium_confidence_counts_as_populated():
    intake = {"category": _field("sign", "medium")}
    readiness = compute_readiness(intake)
    assert readiness["populated_count"] == 1


def test_readiness_low_confidence_does_not_count_as_populated():
    intake = {"category": _field("sign", "low")}
    readiness = compute_readiness(intake)
    assert readiness["populated_count"] == 0


# ---- generate_draft_brief(): confidence filtering, never invents ----


def test_draft_brief_empty_intake_all_unknown():
    draft = generate_draft_brief(_empty_intake())
    assert draft["project_name"] is None
    assert draft["category"] is None
    assert draft["purpose"] is None
    assert draft["audience"] is None
    assert draft["environment"] is None
    assert draft["printer"] == []
    assert draft["material"] == []
    assert draft["quality_target"] is None
    assert draft["manufacturing_style"] == []
    assert draft["dimensional_constraints"] == []
    assert draft["visual_goals"] == []
    assert draft["functional_goals"] == []
    assert draft["commercial_intent"] is None
    assert draft["review_notes"] == []


def test_draft_brief_populates_only_high_or_medium_confidence_fields():
    intake = {
        "project_name": _field("Widget", "high"),
        "category": _field("sign", "medium"),
        "environment": _field("classroom", "low"),  # excluded
        "quality_target": _field("premium", "unknown"),  # excluded
    }
    draft = generate_draft_brief(intake)
    assert draft["project_name"] == "Widget"
    assert draft["category"] == "sign"
    assert draft["environment"] is None
    assert draft["quality_target"] is None


def test_draft_brief_never_invents_a_value_for_missing_field():
    # A field simply absent from intake_summary (not even a dict) must not
    # crash or produce a fabricated value.
    draft = generate_draft_brief({})
    assert draft["project_name"] is None
    assert draft["material"] == []


def test_draft_brief_commercial_intent_low_confidence_false_stays_unknown_not_false():
    intake = {"commercial_intent": _field(False, "unknown")}
    draft = generate_draft_brief(intake)
    # Never silently promote an unconfirmed False into the draft - stays None.
    assert draft["commercial_intent"] is None


def test_draft_brief_commercial_intent_high_confidence_true_is_populated():
    intake = {"commercial_intent": _field(True, "high")}
    draft = generate_draft_brief(intake)
    assert draft["commercial_intent"] is True


def test_draft_brief_benchmark_fields():
    intake = analyze(BENCHMARK_PATH)
    draft = generate_draft_brief(intake)
    assert "nameplate" in draft["project_name"].lower()
    assert draft["category"] == "sign"
    assert draft["environment"] == "classroom"
    assert draft["quality_target"] == "etsy-worthy"
    assert draft["material"] == ["PLA"]
    assert draft["printer"] == ["Bambu"]
    assert "AMS" in draft["manufacturing_style"]
    assert "multi-part" in draft["manufacturing_style"]
    assert draft["commercial_intent"] is None  # unknown, correctly never invented


# ---- generate_draft_design_intent() ----


def test_draft_design_intent_empty_intake():
    design_intent = generate_draft_design_intent(_empty_intake())
    assert design_intent["purpose"] is None
    assert design_intent["quality_target"] is None
    assert design_intent["style"] == []
    assert design_intent["manufacturing_notes"] == []
    assert design_intent["reference_inputs"] == []
    assert design_intent["design_notes"] == []
    assert design_intent["review_required"] is True


def test_draft_design_intent_never_invents_reference_inputs():
    intake = analyze(BENCHMARK_PATH)
    design_intent = generate_draft_design_intent(intake)
    assert design_intent["reference_inputs"] == []


def test_draft_design_intent_never_invents_max_size_from_dimensional_constraints():
    intake = analyze(BENCHMARK_PATH)
    design_intent = generate_draft_design_intent(intake)
    assert "manufacturability_constraints" not in design_intent
    assert "max_size_mm" not in design_intent


def test_draft_design_intent_confidence_summary_matches_intake():
    intake = analyze(BENCHMARK_PATH)
    design_intent = generate_draft_design_intent(intake)
    assert design_intent["confidence_summary"]["category"] == intake["category"]["confidence"]
    assert design_intent["confidence_summary"]["commercial_intent"] == intake["commercial_intent"]["confidence"]
    assert set(design_intent["confidence_summary"].keys()) == set(brief_generator._TRACKED_FIELDS)


def test_draft_design_intent_carries_forward_intake_warnings():
    intake = analyze(BENCHMARK_PATH)
    design_intent = generate_draft_design_intent(intake)
    assert design_intent["warnings"] == intake["warnings"]


# ---- generate_manufacturing_notes() ----


def test_manufacturing_notes_empty_intake():
    notes = generate_manufacturing_notes(_empty_intake())
    assert notes == {"printer": [], "material": [], "manufacturing_style": [], "dimensional_constraints": []}


def test_manufacturing_notes_benchmark():
    intake = analyze(BENCHMARK_PATH)
    notes = generate_manufacturing_notes(intake)
    assert notes["printer"] == ["Bambu"]
    assert notes["material"] == ["PLA"]
    assert "AMS" in notes["manufacturing_style"]
    assert notes["dimensional_constraints"] == ["48-inch"]


# ---- generate_advisories() ----


def test_advisories_always_include_human_approval_required():
    advisories = generate_advisories(generate_draft_brief(_empty_intake()))
    assert advisories[-1] == "Human approval required before save."


def test_advisories_material_and_printer_and_dimensions():
    draft_brief = generate_draft_brief(_empty_intake())
    advisories = generate_advisories(draft_brief)
    assert "Material not specified." in advisories
    assert "Printer not specified." in advisories
    assert "Dimensions incomplete." in advisories


def test_advisories_reference_board_recommended_for_high_quality_target():
    intake = {"quality_target": _field("etsy-worthy", "high")}
    draft_brief = generate_draft_brief(intake)
    advisories = generate_advisories(draft_brief)
    assert "Reference board recommended - see `factory reference-board add`." in advisories


def test_advisories_commercial_review_recommended():
    intake = {"commercial_intent": _field(True, "high")}
    draft_brief = generate_draft_brief(intake)
    advisories = generate_advisories(draft_brief)
    assert "Commercial review recommended - see docs/licensing-policy.md." in advisories


def test_advisories_mechanical_review_recommended():
    intake = {"functional_goals": _field(["hold", "hinge"], "high")}
    draft_brief = generate_draft_brief(intake)
    advisories = generate_advisories(draft_brief)
    assert "Mechanical review recommended - functional/moving parts detected." in advisories


def test_advisories_never_raises():
    generate_advisories({})  # missing keys entirely - must not raise


# ---- generate_draft(): top-level orchestration ----


def test_generate_draft_is_deterministic():
    intake = analyze(BENCHMARK_PATH)
    assert generate_draft(intake) == generate_draft(intake)


def test_generate_draft_shape():
    draft = generate_draft(_empty_intake())
    assert set(draft.keys()) == {"readiness", "brief", "design_intent", "manufacturing_notes", "advisories"}


def test_generate_draft_brief_review_notes_matches_advisories():
    draft = generate_draft(analyze(BENCHMARK_PATH))
    assert draft["brief"]["review_notes"] == draft["advisories"]


def test_generate_draft_never_raises_on_missing_intake():
    generate_draft(None)  # must not raise
    generate_draft({})  # must not raise


# ---- summarize_draft_brief() ----


def test_summarize_draft_brief_shape():
    summary = summarize_draft_brief(_empty_intake())
    assert set(summary.keys()) == {"readiness", "advisories"}


def test_summarize_draft_brief_matches_full_draft():
    intake = analyze(BENCHMARK_PATH)
    summary = summarize_draft_brief(intake)
    full = generate_draft(intake)
    assert summary["readiness"] == full["readiness"]
    assert summary["advisories"] == full["advisories"]


# ---- build_brief_json(): schema validity ----


def test_build_brief_json_validates_against_schema_fully_populated():
    intake = analyze(BENCHMARK_PATH)
    draft = generate_draft(intake)
    brief_json = build_brief_json(draft)

    schema = project_store.load_json(project_store.SCHEMAS_DIR / "project_brief.schema.json")
    jsonschema.validate(instance=brief_json, schema=schema)


def test_build_brief_json_validates_against_schema_empty_draft():
    draft = generate_draft(_empty_intake())
    brief_json = build_brief_json(draft)

    schema = project_store.load_json(project_store.SCHEMAS_DIR / "project_brief.schema.json")
    jsonschema.validate(instance=brief_json, schema=schema)


def test_build_brief_json_unknown_fields_are_literal_unknown_string():
    draft = generate_draft(_empty_intake())
    brief_json = build_brief_json(draft)
    assert brief_json["project_name"] == "unknown"
    assert brief_json["owner"] == "unknown"
    assert brief_json["intended_printer"] == "unknown"
    assert brief_json["description"] == "unknown"
    assert brief_json["constraints"] == []


def test_build_brief_json_status_is_brief_created():
    brief_json = build_brief_json(generate_draft(_empty_intake()))
    assert brief_json["status"] == "brief_created"


def test_build_brief_json_required_human_approval_always_true():
    brief_json = build_brief_json(generate_draft(_empty_intake()))
    assert brief_json["required_human_approval"] is True


def test_build_brief_json_omits_design_intent_when_no_signal():
    brief_json = build_brief_json(generate_draft(_empty_intake()))
    assert "design_intent" not in brief_json


def test_build_brief_json_omits_manufacturing_notes_when_no_signal():
    brief_json = build_brief_json(generate_draft(_empty_intake()))
    assert "manufacturing_notes" not in brief_json


def test_build_brief_json_includes_design_intent_when_signal_present():
    intake = analyze(BENCHMARK_PATH)
    brief_json = build_brief_json(generate_draft(intake))
    assert "design_intent" in brief_json
    assert brief_json["design_intent"]["quality_standard"] == "etsy-worthy"
    assert "style_direction" in brief_json["design_intent"]


def test_build_brief_json_never_sets_manufacturability_constraints():
    intake = analyze(BENCHMARK_PATH)
    brief_json = build_brief_json(generate_draft(intake))
    assert "manufacturability_constraints" not in brief_json.get("design_intent", {})


# ---- write_draft_brief() ----


def test_write_draft_brief_creates_file(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    draft = generate_draft(analyze(BENCHMARK_PATH))
    written = write_draft_brief(tmp_path, draft)
    assert written == tmp_path / "brief.json"
    assert written.is_file()


def test_write_draft_brief_missing_project_dir_raises(tmp_path):
    with pytest.raises(ProjectDirectoryNotFoundError):
        write_draft_brief(tmp_path / "does-not-exist", generate_draft(_empty_intake()))


def test_write_draft_brief_refuses_to_overwrite_existing_brief(tmp_path):
    project_store.save_json(tmp_path / "brief.json", {"existing": True})
    draft = generate_draft(analyze(BENCHMARK_PATH))
    with pytest.raises(BriefAlreadyExistsError):
        write_draft_brief(tmp_path, draft)
    # Must not have been touched.
    assert project_store.load_json(tmp_path / "brief.json") == {"existing": True}


def test_write_draft_brief_force_overwrites_existing_brief(tmp_path):
    project_store.save_json(tmp_path / "brief.json", {"existing": True})
    draft = generate_draft(analyze(BENCHMARK_PATH))
    written = write_draft_brief(tmp_path, draft, force=True)
    data = project_store.load_json(written)
    assert data.get("existing") is None
    assert "nameplate" in data["project_name"].lower()


def test_write_draft_brief_writes_only_brief_json(tmp_path):
    before = sorted(p.name for p in tmp_path.iterdir())
    draft = generate_draft(analyze(BENCHMARK_PATH))
    write_draft_brief(tmp_path, draft)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert set(after) - set(before) == {"brief.json"}


# ---- load_intake_summary_from_path() ----


def test_load_intake_summary_from_project_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(project_store, "PROJECTS_DIR", tmp_path)
    project_dir = project_store.init_project("Demo")
    brief = project_store.load_json(project_dir / "brief.json")
    brief["description"] = "A premium etsy-worthy sign made of PLA."
    project_store.save_json(project_dir / "brief.json", brief)

    intake = load_intake_summary_from_path(project_dir)
    assert intake["source"] == "brief_description"
    assert intake["category"]["value"] == "sign"


def test_load_intake_summary_from_markdown_file():
    intake = load_intake_summary_from_path(BENCHMARK_PATH)
    assert intake["source"] == "markdown_file"


def test_load_intake_summary_from_saved_json(tmp_path):
    saved = tmp_path / "saved_intake.json"
    original = analyze(BENCHMARK_PATH)
    project_store.save_json(saved, original)

    loaded = load_intake_summary_from_path(saved)
    assert loaded == original


def test_load_intake_summary_from_malformed_json_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(MalformedIntakeSummaryError):
        load_intake_summary_from_path(bad)


def test_load_intake_summary_from_json_missing_expected_shape_raises(tmp_path):
    bad = tmp_path / "not_intake.json"
    project_store.save_json(bad, {"hello": "world"})
    with pytest.raises(MalformedIntakeSummaryError):
        load_intake_summary_from_path(bad)


def test_load_intake_summary_nonexistent_path_returns_clean_result(tmp_path):
    intake = load_intake_summary_from_path(tmp_path / "does-not-exist")
    assert intake["source"] == "none"


# ---- module never re-parses free text, never writes anything but brief.json ----


def test_generator_functions_never_call_extract_intake_fields():
    # The core shaping functions must never re-run the Phase 30 heuristics
    # themselves - only load_intake_summary_from_path() (a thin CLI-facing
    # convenience wrapper) is allowed to invoke the Phase 30 analyzer.
    for func in (
        generate_draft_brief,
        generate_draft_design_intent,
        generate_manufacturing_notes,
        generate_advisories,
        compute_readiness,
        generate_draft,
        summarize_draft_brief,
        build_brief_json,
    ):
        source = inspect.getsource(func)
        assert "extract_intake_fields(" not in source
        assert "project_intake.analyze" not in source


def test_module_has_no_forbidden_network_or_ai_calls():
    forbidden = (
        "import subprocess", "subprocess.run(", "subprocess.call(", "subprocess.Popen(",
        "os.system(", "os.popen(", "socket.", "import urllib", "import requests",
        "http.client", "urlopen(", "requests.get(", "requests.post(",
        "openai", "anthropic", "import torch", "import tensorflow", "import sklearn",
    )
    source = inspect.getsource(brief_generator)
    for forbidden_call in forbidden:
        assert forbidden_call not in source


def test_module_write_path_is_only_save_json_to_brief_json():
    # write_draft_brief() must be the only place this module calls save_json().
    source = inspect.getsource(brief_generator)
    assert source.count("save_json(") == 1


def test_module_does_not_set_human_approved_or_print_ready():
    source = inspect.getsource(brief_generator)
    assert '"human_approved": True' not in source
    assert '"print_ready": True' not in source
    assert '"human_approved"' not in source
    assert '"print_ready"' not in source

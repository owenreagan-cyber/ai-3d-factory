"""Phase 32 tests: `factory.brief_generator`'s safe merge/update logic
(`merge_draft_brief()`, `apply_merge()`, `load_existing_brief()`,
`write_merged_brief()`, `build_merge_preview()`, `summarize_brief_update()`).
No AI, no LLM, no network - a purely deterministic, "never overwrite
human-authored content" merge over an already-generated draft. See
docs/brief-generator.md, docs/roadmap.md Phase 32.
"""

import inspect

import jsonschema
import pytest

from factory import brief_generator, project_store
from factory.brief_generator import (
    MalformedExistingBriefError,
    ProjectDirectoryNotFoundError,
    apply_merge,
    build_merge_preview,
    generate_draft,
    generate_draft_brief,
    load_existing_brief,
    merge_draft_brief,
    summarize_brief_update,
    write_merged_brief,
)
from factory.project_intake import analyze, extract_intake_fields

BENCHMARK_PATH = project_store.REPO_ROOT / "examples" / "intake-benchmarks" / "teacher-nameplate.md"


def _field(value, confidence):
    return {"value": value, "confidence": confidence}


def _empty_intake():
    return extract_intake_fields("")


def _benchmark_draft_brief():
    return generate_draft_brief(analyze(BENCHMARK_PATH))


# ---- merge fills missing/unknown fields ----


def test_merge_fills_completely_absent_fields():
    result = merge_draft_brief({}, _benchmark_draft_brief())
    assert result["fields_to_add"]["material"] == ["PLA"]
    assert result["fields_to_add"]["printer"] == ["Bambu"]
    assert result["fields_to_add"]["quality_target"] == "etsy-worthy"
    assert result["fields_preserved"] == []


def test_merge_fills_placeholder_unknown_fields():
    existing = {"intended_printer": "unknown", "description": "unknown"}
    result = merge_draft_brief(existing, _benchmark_draft_brief())
    assert "printer" in result["fields_to_add"]
    assert "purpose" in result["fields_to_add"]


def test_merge_fills_default_brief_todo_placeholders():
    existing = project_store.default_brief("Demo")
    result = merge_draft_brief(existing, _benchmark_draft_brief())
    # description is a "TODO: ..." string -> fillable
    assert "purpose" in result["fields_to_add"]
    # constraints is a single-item "TODO: ..." list -> fillable
    assert "dimensional_constraints" in result["fields_to_add"]
    # project_name ("Demo") and intended_printer ("Bambu H2D") are real,
    # non-placeholder content from default_brief() -> preserved
    assert "project_name" in result["fields_preserved"]
    assert "printer" in result["fields_preserved"]


# ---- merge preserves existing known/human-authored values ----


def test_merge_preserves_real_existing_values():
    existing = {
        "project_name": "Real Project",
        "description": "A real human-written description.",
        "intended_printer": "Prusa MK4",
        "constraints": ["Must fit in a 100mm cube."],
    }
    result = merge_draft_brief(existing, _benchmark_draft_brief())
    assert set(result["fields_preserved"]) >= {"project_name", "purpose", "printer", "dimensional_constraints"}
    assert "project_name" not in result["fields_to_add"]
    assert "purpose" not in result["fields_to_add"]
    assert "printer" not in result["fields_to_add"]
    assert "dimensional_constraints" not in result["fields_to_add"]


def test_merge_preserves_real_design_intent_and_manufacturing_notes():
    existing = {
        "design_intent": {"quality_standard": "hand-picked premium", "style_direction": ["rustic"]},
        "manufacturing_notes": {"material": ["ABS"], "manufacturing_style": ["single-part"]},
    }
    result = merge_draft_brief(existing, _benchmark_draft_brief())
    assert "quality_target" in result["fields_preserved"]
    assert "visual_goals" in result["fields_preserved"]
    assert "material" in result["fields_preserved"]
    assert "manufacturing_style" in result["fields_preserved"]
    # None of the preserved fields should also appear as additions.
    assert "quality_target" not in result["fields_to_add"]
    assert "visual_goals" not in result["fields_to_add"]
    assert "material" not in result["fields_to_add"]
    assert "manufacturing_style" not in result["fields_to_add"]


def test_real_committed_example_brief_is_mostly_preserved():
    # examples/mr_reagan_nameplate/brief.json is a real, fully human-authored
    # brief - merging any draft into it should preserve every base field.
    existing = project_store.load_json(
        project_store.REPO_ROOT / "examples" / "mr_reagan_nameplate" / "brief.json"
    )
    result = merge_draft_brief(existing, _benchmark_draft_brief())
    assert set(result["fields_preserved"]) >= {"project_name", "purpose", "printer", "dimensional_constraints"}


# ---- merge never overwrites existing with unknown ----


def test_merge_never_proposes_replacing_present_value_even_if_draft_has_nothing():
    existing = {"project_name": "Keep Me"}
    result = merge_draft_brief(existing, generate_draft_brief(_empty_intake()))
    assert "project_name" in result["fields_preserved"]
    assert "project_name" not in result["fields_to_add"]


def test_merge_adds_nothing_when_draft_has_no_confident_value_and_existing_is_empty():
    result = merge_draft_brief({}, generate_draft_brief(_empty_intake()))
    assert result["fields_to_add"] == {}
    assert result["fields_preserved"] == []
    assert "No merge candidates found" in result["advisories"][0]


def test_apply_merge_never_touches_preserved_fields():
    existing = {
        "project_name": "Untouched Name",
        "description": "Untouched description.",
        "intended_printer": "Voron 2.4",
        "constraints": ["Untouched constraint."],
        "owner": "Someone Specific",
        "status": "plan_approved",
    }
    result = merge_draft_brief(existing, _benchmark_draft_brief())
    merged = apply_merge(existing, result)
    assert merged["project_name"] == "Untouched Name"
    assert merged["description"] == "Untouched description."
    assert merged["intended_printer"] == "Voron 2.4"
    assert merged["constraints"] == ["Untouched constraint."]
    assert merged["owner"] == "Someone Specific"
    assert merged["status"] == "plan_approved"  # never touched by merge, ever


def test_apply_merge_does_not_mutate_input_existing_brief():
    existing = {"project_name": "Original"}
    result = merge_draft_brief(existing, _benchmark_draft_brief())
    apply_merge(existing, result)
    assert existing == {"project_name": "Original"}  # deep-copied, not mutated in place


# ---- fields_to_add / fields_preserved reporting ----


def test_fields_to_add_and_preserved_are_disjoint():
    intake = analyze(BENCHMARK_PATH)
    existing = {"project_name": "Kept", "intended_printer": "Prusa"}
    result = merge_draft_brief(existing, generate_draft_brief(intake))
    assert set(result["fields_to_add"]) & set(result["fields_preserved"]) == set()


def test_category_audience_environment_never_appear_in_merge_output():
    # These have no home in a real brief.json (build_brief_json() never
    # writes them), so merge_draft_brief() must never mention them.
    result = merge_draft_brief({}, _benchmark_draft_brief())
    all_field_names = set(result["fields_to_add"]) | set(result["fields_preserved"])
    assert "category" not in all_field_names
    assert "audience" not in all_field_names
    assert "environment" not in all_field_names
    assert "functional_goals" not in all_field_names
    assert "commercial_intent" not in all_field_names


def test_merge_records_advisories():
    result = merge_draft_brief({}, _benchmark_draft_brief())
    assert "Human approval required before save." in result["advisories"]


def test_merge_never_raises_on_malformed_existing_brief_dict():
    merge_draft_brief("not a dict", _benchmark_draft_brief())  # must not raise
    merge_draft_brief(None, _benchmark_draft_brief())  # must not raise
    merge_draft_brief([], _benchmark_draft_brief())  # must not raise


def test_merge_never_raises_on_malformed_draft_brief():
    merge_draft_brief({}, "not a dict")  # must not raise
    merge_draft_brief({}, None)  # must not raise


# ---- build_merge_preview() ----


def test_build_merge_preview_shape():
    preview = build_merge_preview({}, analyze(BENCHMARK_PATH))
    assert set(preview.keys()) == {"draft", "merge_preview"}
    assert set(preview["merge_preview"].keys()) == {"fields_to_add", "fields_preserved", "advisories"}


def test_build_merge_preview_is_deterministic():
    intake = analyze(BENCHMARK_PATH)
    existing = {"project_name": "Fixed"}
    assert build_merge_preview(existing, intake) == build_merge_preview(existing, intake)


def test_build_merge_preview_never_writes_anything(tmp_path):
    before = sorted(p.name for p in tmp_path.iterdir())
    build_merge_preview({}, analyze(BENCHMARK_PATH))
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after


# ---- apply_merge(): schema validity ----


def test_apply_merge_output_validates_against_schema_fresh():
    merged = apply_merge({}, merge_draft_brief({}, _benchmark_draft_brief()))
    schema = project_store.load_json(project_store.SCHEMAS_DIR / "project_brief.schema.json")
    jsonschema.validate(instance=merged, schema=schema)


def test_apply_merge_output_validates_against_schema_partial_existing():
    existing = project_store.default_brief("Demo")
    merged = apply_merge(existing, merge_draft_brief(existing, _benchmark_draft_brief()))
    schema = project_store.load_json(project_store.SCHEMAS_DIR / "project_brief.schema.json")
    jsonschema.validate(instance=merged, schema=schema)


def test_apply_merge_always_sets_required_human_approval_true():
    merged = apply_merge({}, merge_draft_brief({}, _benchmark_draft_brief()))
    assert merged["required_human_approval"] is True


# ---- load_existing_brief() ----


def test_load_existing_brief_none_when_missing(tmp_path):
    assert load_existing_brief(tmp_path) is None


def test_load_existing_brief_reads_real_file(tmp_path):
    project_store.save_json(tmp_path / "brief.json", {"project_name": "X"})
    assert load_existing_brief(tmp_path) == {"project_name": "X"}


def test_load_existing_brief_malformed_json_raises(tmp_path):
    (tmp_path / "brief.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(MalformedExistingBriefError):
        load_existing_brief(tmp_path)


def test_load_existing_brief_writes_no_files(tmp_path):
    project_store.save_json(tmp_path / "brief.json", {"project_name": "X"})
    before = sorted(p.name for p in tmp_path.iterdir())
    load_existing_brief(tmp_path)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert before == after


# ---- write_merged_brief() ----


def test_write_merged_brief_creates_file_and_preserves_existing(tmp_path):
    existing = {
        "project_name": "Keep",
        "description": "Keep this too.",
        "intended_printer": "Prusa",
        "constraints": ["Keep constraint."],
        "owner": "Someone",
        "status": "plan_approved",
        "required_human_approval": True,
    }
    project_store.save_json(tmp_path / "brief.json", existing)

    merge_result = merge_draft_brief(existing, _benchmark_draft_brief())
    written = write_merged_brief(tmp_path, existing, merge_result)

    data = project_store.load_json(written)
    assert data["project_name"] == "Keep"
    assert data["description"] == "Keep this too."
    assert data["intended_printer"] == "Prusa"
    assert data["constraints"] == ["Keep constraint."]
    assert data["status"] == "plan_approved"
    # New fields added from the confident draft (design_intent/manufacturing_notes
    # didn't exist before).
    assert "design_intent" in data
    assert "manufacturing_notes" in data


def test_write_merged_brief_missing_project_dir_raises(tmp_path):
    with pytest.raises(ProjectDirectoryNotFoundError):
        write_merged_brief(tmp_path / "does-not-exist", {}, {"fields_to_add": {}, "fields_preserved": []})


def test_write_merged_brief_writes_only_brief_json(tmp_path):
    before = sorted(p.name for p in tmp_path.iterdir())
    merge_result = merge_draft_brief({}, _benchmark_draft_brief())
    write_merged_brief(tmp_path, {}, merge_result)
    after = sorted(p.name for p in tmp_path.iterdir())
    assert set(after) - set(before) == {"brief.json"}


# ---- summarize_brief_update() ----


def test_summarize_brief_update_shape():
    summary = summarize_brief_update({}, _empty_intake())
    assert set(summary.keys()) == {
        "merge_available", "fields_to_add_count", "fields_preserved_count", "human_review_required",
    }


def test_summarize_brief_update_merge_available_true_when_fields_to_add():
    summary = summarize_brief_update({}, analyze(BENCHMARK_PATH))
    assert summary["merge_available"] is True
    assert summary["fields_to_add_count"] > 0


def test_summarize_brief_update_merge_available_false_when_nothing_to_add():
    summary = summarize_brief_update({}, _empty_intake())
    assert summary["merge_available"] is False
    assert summary["fields_to_add_count"] == 0


def test_summarize_brief_update_merge_available_false_when_fully_preserved():
    existing = project_store.load_json(
        project_store.REPO_ROOT / "examples" / "mr_reagan_nameplate" / "brief.json"
    )
    summary = summarize_brief_update(existing, _empty_intake())
    assert summary["merge_available"] is False
    assert summary["fields_preserved_count"] >= 4


def test_summarize_brief_update_human_review_required_always_true():
    assert summarize_brief_update({}, _empty_intake())["human_review_required"] is True
    assert summarize_brief_update(None, analyze(BENCHMARK_PATH))["human_review_required"] is True


# ---- module hygiene: no re-parsing, no forbidden calls, no invented data ----


def test_merge_functions_never_call_extract_intake_fields():
    for func in (merge_draft_brief, apply_merge, load_existing_brief, write_merged_brief, summarize_brief_update):
        source = inspect.getsource(func)
        assert "extract_intake_fields(" not in source
        assert "project_intake.analyze" not in source


def test_merge_module_has_no_forbidden_network_or_ai_calls():
    forbidden = (
        "import subprocess", "subprocess.run(", "subprocess.call(", "subprocess.Popen(",
        "os.system(", "os.popen(", "socket.", "import urllib", "import requests",
        "http.client", "urlopen(", "requests.get(", "requests.post(",
        "openai", "anthropic",
    )
    source = inspect.getsource(brief_generator)
    for forbidden_call in forbidden:
        assert forbidden_call not in source


def test_merge_module_does_not_set_human_approved_true_literal():
    source = inspect.getsource(brief_generator)
    assert '"human_approved": True' not in source
    assert '"print_ready": True' not in source

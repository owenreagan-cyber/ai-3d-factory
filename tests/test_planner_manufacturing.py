import jsonschema
import pytest

from factory import planner, project_store


def _brief(**overrides):
    base = {
        "project_name": "test-part",
        "status": "brief_created",
        "owner": "Owen",
        "intended_printer": "Bambu H2D",
        "description": "A two-color raised-letter nameplate.",
        "constraints": [],
        "required_human_approval": True,
    }
    base.update(overrides)
    return base


def test_draft_build_plan_resolves_known_target_printer():
    plan = planner.draft_build_plan(_brief(intended_printer="Bambu H2D"))
    assert plan["target_printer"]["resolved"] is True
    assert plan["target_printer"]["printer_id"] == "bambu_h2d"
    assert plan["target_printer"]["capabilities"]["multicolor_supported"] is True


def test_draft_build_plan_leaves_unresolved_printer_as_open_question():
    plan = planner.draft_build_plan(_brief(intended_printer="Prusa MK4"))
    assert plan["target_printer"]["resolved"] is False
    assert plan["target_printer"]["printer_id"] is None
    assert any("intended printer" in q.lower() for q in plan["unanswered_questions"])


def test_draft_build_plan_includes_manufacturing_options_and_never_selects_one():
    plan = planner.draft_build_plan(_brief())
    assert len(plan["manufacturing_options"]["options"]) == 7
    assert plan["manufacturing_options"]["recommended_option"]
    assert plan["manufacturing_options"]["selected_manufacturing_option"] is None
    assert plan["selected_manufacturing_option"] is None


def test_draft_build_plan_recommends_multipart_color_for_two_color_description():
    plan = planner.draft_build_plan(_brief(description="a two-color raised-letter sign"))
    assert plan["manufacturing_options"]["recommended_option"] == "multipart_color"


def test_draft_build_plan_never_advances_status_beyond_plan_drafted():
    plan = planner.draft_build_plan(_brief())
    assert plan["status"] == "plan_drafted"
    assert plan["status"] not in ("human_approved", "print_ready")


def test_draft_build_plan_has_non_empty_unanswered_questions():
    plan = planner.draft_build_plan(_brief())
    assert len(plan["unanswered_questions"]) >= 1


def test_draft_build_plan_materials_are_advisory_only():
    plan = planner.draft_build_plan(_brief(description="an outdoor UV-resistant automotive part"))
    assert "asa" in plan["materials"]["candidates"]
    assert plan["colors"] == []


def test_draft_build_plan_validates_against_build_plan_schema():
    plan = planner.draft_build_plan(_brief())
    schema = project_store.load_json(project_store.SCHEMAS_DIR / "build_plan.schema.json")
    jsonschema.validate(instance=plan, schema=schema)


def test_plan_from_brief_path_seeds_part_manifest(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)

    root = project_store.init_project("Demo Project")
    brief_path = root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["description"] = "a two-color raised-letter nameplate"
    brief["intended_printer"] = "Bambu H2D"
    project_store.save_json(brief_path, brief)

    planner.plan_from_brief_path(brief_path)

    manifest = project_store.load_json(root / "part_manifest.json")
    assert len(manifest["parts"]) == 1
    part = manifest["parts"][0]
    assert part["quantity"] == 1
    assert "intended_material" in part

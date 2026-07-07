import pytest

from factory import planner, project_store
from factory.manufacturing.selection import (
    BuildPlanNotFoundError,
    UnknownManufacturingOptionError,
    choose_manufacturing_option,
    list_manufacturing_options,
)


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture()
def planned_project(isolated_projects_dir):
    root = project_store.init_project("Demo Project")
    brief_path = root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["description"] = "a two-color raised-letter nameplate"
    brief["intended_printer"] = "Bambu H2D"
    project_store.save_json(brief_path, brief)
    planner.plan_from_brief_path(brief_path)
    return root


def test_list_manufacturing_options_requires_a_plan(isolated_projects_dir):
    root = project_store.init_project("Unplanned Project")
    # init-project writes a non-schema-conformant build_plan.json stub without
    # manufacturing_options; list_manufacturing_options must still degrade gracefully.
    result = list_manufacturing_options(root)
    assert result["options"] == []
    assert result["selected_manufacturing_option"] is None


def test_list_manufacturing_options_raises_without_build_plan(tmp_path):
    not_a_project = tmp_path / "no-build-plan"
    not_a_project.mkdir()
    with pytest.raises(BuildPlanNotFoundError):
        list_manufacturing_options(not_a_project)


def test_list_manufacturing_options_returns_seven_options(planned_project):
    result = list_manufacturing_options(planned_project)
    assert len(result["options"]) == 7
    assert result["recommended_option"] == "multipart_color"
    assert result["selected_manufacturing_option"] is None


def test_choose_manufacturing_option_records_selection(planned_project):
    result = choose_manufacturing_option(planned_project, "multipart_color")
    assert result["option"]["option_id"] == "multipart_color"

    build_plan = project_store.load_json(planned_project / "build_plan.json")
    assert build_plan["selected_manufacturing_option"] == "multipart_color"
    assert build_plan["manufacturing_options"]["selected_manufacturing_option"] == "multipart_color"


def test_choose_manufacturing_option_rejects_unknown_id(planned_project):
    with pytest.raises(UnknownManufacturingOptionError):
        choose_manufacturing_option(planned_project, "not_a_real_option")

    # A rejected choice must not have mutated build_plan.json.
    build_plan = project_store.load_json(planned_project / "build_plan.json")
    assert build_plan["selected_manufacturing_option"] is None


def test_choose_manufacturing_option_preserves_all_other_fields(planned_project):
    before = project_store.load_json(planned_project / "build_plan.json")
    choose_manufacturing_option(planned_project, "multipart_color")
    after = project_store.load_json(planned_project / "build_plan.json")

    for key in before:
        if key in ("selected_manufacturing_option", "manufacturing_options"):
            continue
        assert after[key] == before[key], f"field {key!r} was unexpectedly modified"

    # manufacturing_options is preserved apart from the one selection field.
    for key in before["manufacturing_options"]:
        if key == "selected_manufacturing_option":
            continue
        assert after["manufacturing_options"][key] == before["manufacturing_options"][key]


def test_choose_manufacturing_option_advances_status_forward_only(planned_project):
    brief_before = project_store.load_json(planned_project / "brief.json")
    assert brief_before["status"] == "brief_created"

    choose_manufacturing_option(planned_project, "multipart_color")
    brief_after = project_store.load_json(planned_project / "brief.json")
    assert brief_after["status"] == "manufacturing_option_selected"

    # Manually push status further along; choosing an option again must not regress it.
    brief_after["status"] = "preview_rendered"
    project_store.save_json(planned_project / "brief.json", brief_after)

    choose_manufacturing_option(planned_project, "single_piece")
    brief_final = project_store.load_json(planned_project / "brief.json")
    assert brief_final["status"] == "preview_rendered"


def test_choose_manufacturing_option_never_sets_human_approved_or_print_ready(planned_project):
    choose_manufacturing_option(planned_project, "multipart_color")
    brief = project_store.load_json(planned_project / "brief.json")
    assert brief["status"] not in ("human_approved", "print_ready")


def test_choose_manufacturing_option_does_not_touch_cad_or_stl_dirs(planned_project):
    cad_files_before = list((planned_project / "cad").iterdir())
    stl_files_before = list((planned_project / "stl").iterdir())

    choose_manufacturing_option(planned_project, "multipart_color")

    assert list((planned_project / "cad").iterdir()) == cad_files_before
    assert list((planned_project / "stl").iterdir()) == stl_files_before


def test_choose_manufacturing_option_warns_but_allows_unavailable_choice(planned_project):
    # multipart_color is available (H2D has multicolor); pick an always-available
    # option and confirm the availability info round-trips regardless of value.
    result = choose_manufacturing_option(planned_project, "single_piece")
    assert result["available"] is True
    assert result["availability_note"] is None


def test_choose_manufacturing_option_allows_unavailable_option_with_warning(isolated_projects_dir):
    root = project_store.init_project("No Multicolor Project")
    brief_path = root / "brief.json"
    brief = project_store.load_json(brief_path)
    brief["description"] = "a two-color raised-letter nameplate"
    brief["intended_printer"] = "Elegoo Centauri Carbon"
    project_store.save_json(brief_path, brief)
    planner.plan_from_brief_path(brief_path)

    # multipart_color is unavailable for this printer, but an explicit human
    # choice is still recorded, not blocked.
    result = choose_manufacturing_option(root, "multipart_color")
    assert result["available"] is False
    assert result["availability_note"]

    build_plan = project_store.load_json(root / "build_plan.json")
    assert build_plan["selected_manufacturing_option"] == "multipart_color"

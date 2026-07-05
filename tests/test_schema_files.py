import json

import jsonschema
import pytest

from factory import planner, project_store

SCHEMA_NAMES = [
    "project_brief.schema.json",
    "build_plan.schema.json",
    "part_manifest.schema.json",
    "validation_report.schema.json",
    "slicer_review.schema.json",
]


@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
def test_schema_file_is_valid_json_and_valid_schema(schema_name):
    path = project_store.SCHEMAS_DIR / schema_name
    assert path.is_file(), f"missing schema file {schema_name}"

    with open(path, encoding="utf-8") as f:
        schema = json.load(f)

    jsonschema.Draft7Validator.check_schema(schema)


EXAMPLE_BRIEFS = [
    "simple_test_cube/brief.json",
    "mr_reagan_nameplate/brief.json",
    "gv60_plate_frame/brief.json",
]


@pytest.mark.parametrize("relative_path", EXAMPLE_BRIEFS)
def test_example_briefs_validate_against_schema(relative_path):
    brief_path = project_store.REPO_ROOT / "examples" / relative_path
    schema_path = project_store.SCHEMAS_DIR / "project_brief.schema.json"

    brief = project_store.load_json(brief_path)
    schema = project_store.load_json(schema_path)

    jsonschema.validate(instance=brief, schema=schema)


def test_planner_output_validates_against_build_plan_schema():
    brief = project_store.load_json(
        project_store.REPO_ROOT / "examples" / "simple_test_cube" / "brief.json"
    )
    build_plan = planner.draft_build_plan(brief)

    schema = project_store.load_json(project_store.SCHEMAS_DIR / "build_plan.schema.json")
    jsonschema.validate(instance=build_plan, schema=schema)


def test_empty_part_manifest_validates_against_schema():
    schema = project_store.load_json(project_store.SCHEMAS_DIR / "part_manifest.schema.json")
    jsonschema.validate(instance={"parts": []}, schema=schema)

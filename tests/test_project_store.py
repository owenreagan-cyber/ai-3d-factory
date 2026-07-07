from pathlib import Path

import pytest

from factory import project_store


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


def test_slugify_basic():
    assert project_store.slugify("Mr Reagan Nameplate") == "mr-reagan-nameplate"
    assert project_store.slugify("  Weird__Name!! ") == "weird-name"


def test_slugify_empty_raises():
    with pytest.raises(ValueError):
        project_store.slugify("!!!")


def test_init_project_creates_expected_structure(isolated_projects_dir):
    root = project_store.init_project("Demo Project")

    assert root == isolated_projects_dir / "demo-project"
    assert root.is_dir()

    for sub in project_store.PROJECT_SUBDIRS:
        assert (root / sub).is_dir(), f"missing subdir {sub}"

    for fname in ("brief.json", "build_plan.json", "part_manifest.json"):
        assert (root / fname).is_file(), f"missing file {fname}"

    brief = project_store.load_json(root / "brief.json")
    assert brief["project_name"] == "Demo Project"
    assert brief["status"] == "brief_created"
    assert brief["owner"] == "Owen"
    assert brief["intended_printer"] == "Bambu H2D"
    assert brief["required_human_approval"] is True

    manifest = project_store.load_json(root / "part_manifest.json")
    assert manifest == {"parts": []}


def test_init_project_never_overwrites(isolated_projects_dir):
    project_store.init_project("Demo Project")
    with pytest.raises(FileExistsError):
        project_store.init_project("Demo Project")


def test_find_project_root(isolated_projects_dir):
    root = project_store.init_project("Demo Project")
    mesh_path = root / "stl" / "part.stl"
    assert project_store.find_project_root(mesh_path) == root

    outside_path = Path(isolated_projects_dir).parent / "not_a_project" / "file.stl"
    assert project_store.find_project_root(outside_path) is None


def test_save_and_load_json_roundtrip(tmp_path):
    path = tmp_path / "nested" / "data.json"
    data = {"a": 1, "b": [1, 2, 3]}
    project_store.save_json(path, data)
    assert path.is_file()
    assert project_store.load_json(path) == data


def test_manufacturing_option_selected_is_between_plan_approved_and_cad_generated():
    statuses = project_store.PROJECT_STATUSES
    assert "manufacturing_option_selected" in statuses
    assert statuses.index("plan_approved") < statuses.index("manufacturing_option_selected") < statuses.index(
        "cad_generated"
    )


def test_advance_status_allows_manufacturing_option_selected():
    brief = {"status": "plan_drafted"}
    changed = project_store.advance_status(brief, "manufacturing_option_selected")
    assert changed is True
    assert brief["status"] == "manufacturing_option_selected"


def test_advance_status_still_blocks_print_ready_and_human_approved():
    brief = {"status": "manufacturing_option_selected"}
    with pytest.raises(ValueError):
        project_store.advance_status(brief, "print_ready")
    with pytest.raises(ValueError):
        project_store.advance_status(brief, "human_approved")
    # Neither attempt should have mutated the status.
    assert brief["status"] == "manufacturing_option_selected"

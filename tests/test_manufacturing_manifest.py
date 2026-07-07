import pytest

from factory import project_store
from factory.manufacturing.manifest import seed_manifest_from_plan


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture()
def project_root(isolated_projects_dir):
    return project_store.init_project("Demo Project")


def _build_plan(part_names):
    return {
        "required_parts": [{"part_name": name, "role": "primary"} for name in part_names]
    }


def test_seed_manifest_creates_entry_with_expected_fields(project_root):
    seed_manifest_from_plan(project_root, _build_plan(["Demo Project - primary part"]))

    manifest = project_store.load_json(project_root / "part_manifest.json")
    assert len(manifest["parts"]) == 1
    part = manifest["parts"][0]

    for field in (
        "part_name",
        "source_scad",
        "intended_material",
        "intended_color",
        "quantity",
        "shared_origin",
        "export_expected",
    ):
        assert field in part, f"missing seeded field {field}"

    assert part["quantity"] == 1
    assert part["shared_origin"] is False
    assert part["export_expected"] is True


def test_seed_manifest_marks_shared_origin_true_for_multiple_parts(project_root):
    seed_manifest_from_plan(project_root, _build_plan(["base", "text"]))

    manifest = project_store.load_json(project_root / "part_manifest.json")
    assert len(manifest["parts"]) == 2
    for part in manifest["parts"]:
        assert part["shared_origin"] is True


def test_seed_manifest_never_duplicates_entries_on_rerun(project_root):
    build_plan = _build_plan(["base", "text"])
    seed_manifest_from_plan(project_root, build_plan)
    seed_manifest_from_plan(project_root, build_plan)

    manifest = project_store.load_json(project_root / "part_manifest.json")
    assert len(manifest["parts"]) == 2


def test_seed_manifest_never_overwrites_existing_values(project_root):
    manifest_path = project_root / "part_manifest.json"
    project_store.save_json(
        manifest_path,
        {
            "parts": [
                {
                    "part_name": "base",
                    "file_path": "stl/base.stl",
                    "cad_source": "cad/base.scad",
                    "material": "PLA",
                    "color": "white",
                    "export_units": "mm",
                    "role": "base_plate",
                    "required_for_assembly": True,
                }
            ]
        },
    )

    seed_manifest_from_plan(project_root, _build_plan(["base"]))

    manifest = project_store.load_json(manifest_path)
    part = manifest["parts"][0]
    # Pre-existing, human/generator-set values must survive untouched.
    assert part["file_path"] == "stl/base.stl"
    assert part["cad_source"] == "cad/base.scad"
    assert part["material"] == "PLA"
    assert part["color"] == "white"
    assert part["role"] == "base_plate"
    # New Phase 3 fields should still be filled in since they weren't present before.
    assert part["intended_material"] == "TBD - human decision"
    assert "source_scad" in part
    assert "quantity" in part


def test_seed_manifest_ignores_required_parts_without_part_name(project_root):
    seed_manifest_from_plan(project_root, {"required_parts": [{"role": "primary"}]})
    manifest = project_store.load_json(project_root / "part_manifest.json")
    assert manifest["parts"] == []

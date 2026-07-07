import pytest

from factory import project_store
from factory.manufacturing.manifest import apply_selected_option_to_manifest, compute_assembly_intent


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture()
def project_root(isolated_projects_dir):
    return project_store.init_project("Demo Project")


def test_no_option_selected_status():
    result = compute_assembly_intent({"selected_manufacturing_option": None, "required_parts": [{"part_name": "x"}]})
    assert result["status"] == "no_option_selected"
    assert result["cad_generation_safe"] is False
    assert result["multipart_incomplete"] is False


def test_multipart_option_with_single_placeholder_part_is_incomplete():
    result = compute_assembly_intent(
        {"selected_manufacturing_option": "multipart_color", "required_parts": [{"part_name": "x"}]}
    )
    assert result["status"] == "multipart_incomplete"
    assert result["multipart_incomplete"] is True
    assert result["cad_generation_safe"] is False
    assert (
        result["note"]
        == "Selected option implies multipart planning, but detailed required_parts are still "
        "incomplete. Refine build_plan.json's required_parts (and re-run `factory plan`) before "
        "generating multi-part CAD."
    )


def test_multipart_option_with_multiple_parts_is_ready():
    result = compute_assembly_intent(
        {
            "selected_manufacturing_option": "multipart_color",
            "required_parts": [{"part_name": "a"}, {"part_name": "b"}],
        }
    )
    assert result["status"] == "multipart_ready"
    assert result["cad_generation_safe"] is True
    assert result["multipart_incomplete"] is False


def test_single_piece_option_is_ready():
    result = compute_assembly_intent(
        {"selected_manufacturing_option": "single_piece", "required_parts": [{"part_name": "x"}]}
    )
    assert result["status"] == "single_piece_ready"
    assert result["cad_generation_safe"] is True


@pytest.mark.parametrize(
    "option_id", ["multipart_build_volume", "multipart_color", "multipart_detail", "multipart_paint", "multipart_strength", "replaceable_components"]
)
def test_every_multipart_option_id_is_recognized_as_implying_multipart(option_id):
    result = compute_assembly_intent({"selected_manufacturing_option": option_id, "required_parts": [{"part_name": "x"}]})
    assert result["status"] == "multipart_incomplete"


def test_apply_selected_option_never_touches_existing_parts_array(project_root):
    manifest_path = project_root / "part_manifest.json"
    existing_parts = [
        {
            "part_name": "base",
            "file_path": "stl/base.stl",
            "material": "PLA",
            "color": "white",
            "export_units": "mm",
            "role": "base_plate",
            "required_for_assembly": True,
        }
    ]
    project_store.save_json(manifest_path, {"parts": existing_parts})

    apply_selected_option_to_manifest(project_root, {"selected_manufacturing_option": "single_piece", "required_parts": []})

    manifest = project_store.load_json(manifest_path)
    assert manifest["parts"] == existing_parts  # byte-for-byte untouched
    assert "assembly_intent" in manifest


def test_apply_selected_option_creates_manifest_if_missing(project_root):
    manifest_path = project_root / "part_manifest.json"
    manifest_path.unlink()

    apply_selected_option_to_manifest(
        project_root, {"selected_manufacturing_option": "single_piece", "required_parts": []}
    )

    manifest = project_store.load_json(manifest_path)
    assert manifest["parts"] == []
    assert manifest["assembly_intent"]["status"] == "single_piece_ready"


def test_apply_selected_option_refreshes_stale_assembly_intent(project_root):
    manifest_path = project_root / "part_manifest.json"
    apply_selected_option_to_manifest(
        project_root, {"selected_manufacturing_option": "multipart_color", "required_parts": [{"part_name": "x"}]}
    )
    first = project_store.load_json(manifest_path)["assembly_intent"]
    assert first["status"] == "multipart_incomplete"

    apply_selected_option_to_manifest(
        project_root,
        {
            "selected_manufacturing_option": "multipart_color",
            "required_parts": [{"part_name": "a"}, {"part_name": "b"}],
        },
    )
    second = project_store.load_json(manifest_path)["assembly_intent"]
    assert second["status"] == "multipart_ready"

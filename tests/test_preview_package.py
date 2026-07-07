import time

import pytest

from factory import project_store
from factory.preview_package import (
    REQUIRED_SAFETY_LINES,
    build_markdown_report,
    gather_preview_data,
    preview_package_paths,
    write_preview_package,
)


@pytest.fixture()
def isolated_projects_dir(tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)
    return projects_dir


@pytest.fixture()
def project_root(isolated_projects_dir):
    return project_store.init_project("Demo Project")


def test_gather_preview_data_on_empty_project(project_root):
    index = gather_preview_data(project_root)
    assert index["cad_files"] == []
    assert index["mesh_files"] == []
    assert index["render_files"] == []
    assert index["manifest_parts"] == []
    assert index["multipart_state"] == {"multi_part": False, "part_count": 0}
    assert "No CAD source, STL, or render files exist yet" in index["missing_visual_artifacts"][0]
    assert index["stale_previews"] == []


def test_gather_preview_data_with_cad_files_only(project_root):
    (project_root / "cad" / "part.scad").write_text("// scad source\n", encoding="utf-8")
    index = gather_preview_data(project_root)
    assert index["cad_files"] == ["cad/part.scad"]
    assert index["mesh_files"] == []
    assert any("no STL exported yet" in item for item in index["missing_visual_artifacts"])


def test_gather_preview_data_with_stl_only_no_manifest_entry(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl bytes")
    index = gather_preview_data(project_root)
    assert index["mesh_files"] == ["stl/part.stl"]
    assert any("Missing render for stl/part.stl" in item for item in index["missing_visual_artifacts"])


def test_gather_preview_data_with_render_present_is_not_missing(project_root):
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl bytes")
    (project_root / "renders" / "part_preview.png").write_bytes(b"fake png bytes")
    index = gather_preview_data(project_root)
    assert index["render_files"] == ["renders/part_preview.png"]
    assert index["missing_visual_artifacts"] == []
    assert index["stale_previews"] == []


def test_gather_preview_data_detects_stale_render_by_mtime(project_root):
    stl_path = project_root / "stl" / "part.stl"
    render_path = project_root / "renders" / "part_preview.png"
    stl_path.write_bytes(b"fake stl bytes")
    render_path.write_bytes(b"fake png bytes")

    # Make the STL newer than the render it was supposedly rendered from.
    future = time.time() + 10
    import os

    os.utime(stl_path, (future, future))

    index = gather_preview_data(project_root)
    assert len(index["stale_previews"]) == 1
    assert "part_preview.png" in index["stale_previews"][0]


def test_gather_preview_data_uses_manifest_parts_when_present(project_root):
    manifest_path = project_root / "part_manifest.json"
    project_store.save_json(
        manifest_path,
        {
            "parts": [
                {"part_name": "base", "file_path": "stl/base.stl", "material": "PLA", "color": "white", "role": "base_plate"},
                {"part_name": "text", "file_path": "stl/text.stl", "material": "PLA", "color": "black", "role": "raised_letters"},
            ]
        },
    )
    index = gather_preview_data(project_root)
    assert index["multipart_state"] == {"multi_part": True, "part_count": 2}
    assert len(index["missing_visual_artifacts"]) == 2  # both STLs missing
    assert "base" in index["missing_visual_artifacts"][0]


def test_gather_preview_data_handles_malformed_manifest_json(project_root):
    manifest_path = project_root / "part_manifest.json"
    manifest_path.write_text("{not valid json", encoding="utf-8")
    index = gather_preview_data(project_root)  # must not raise
    assert index["manifest_parts"] == []
    assert index["multipart_state"] == {"multi_part": False, "part_count": 0}


def test_gather_preview_data_handles_missing_manifest_file(project_root):
    (project_root / "part_manifest.json").unlink()
    index = gather_preview_data(project_root)  # must not raise
    assert index["manifest_parts"] == []


def test_gather_preview_data_handles_missing_brief_and_build_plan(project_root):
    (project_root / "brief.json").unlink()
    (project_root / "build_plan.json").unlink()
    index = gather_preview_data(project_root)  # must not raise
    assert index["project_status"] == "idea"
    assert index["target_printer"] is None
    assert index["selected_manufacturing_option"] is None


def test_markdown_report_contains_required_safety_lines(project_root):
    index = gather_preview_data(project_root)
    markdown = build_markdown_report(index)
    for line in REQUIRED_SAFETY_LINES:
        assert line in markdown


def test_markdown_report_contains_advisory_checklist(project_root):
    index = gather_preview_data(project_root)
    markdown = build_markdown_report(index)
    assert "advisory only" in markdown
    assert "- [ ] Does the preview match the intended object?" in markdown
    assert "- [ ] Is slicer review still required?" in markdown


def test_write_preview_package_writes_both_files(project_root):
    result = write_preview_package(project_root)
    index_path, report_path = preview_package_paths(project_root)
    assert result["index_path"] == index_path
    assert result["report_path"] == report_path
    assert index_path.is_file()
    assert report_path.is_file()

    loaded_index = project_store.load_json(index_path)
    assert loaded_index["project_name"] == "Demo Project"


def test_write_preview_package_does_not_duplicate_render_files(project_root):
    render_path = project_root / "renders" / "part_preview.png"
    render_bytes = b"original png bytes"
    (project_root / "stl" / "part.stl").write_bytes(b"fake stl")
    render_path.write_bytes(render_bytes)

    write_preview_package(project_root)

    package_dir = project_root / "preview_package"
    copied_pngs = list(package_dir.glob("*.png")) + list(package_dir.rglob("*.png"))
    assert copied_pngs == []  # no image files copied into preview_package/
    assert render_path.read_bytes() == render_bytes  # original untouched

    index = project_store.load_json(package_dir / "index.json")
    assert index["render_files"] == ["renders/part_preview.png"]  # referenced, not copied


def test_write_preview_package_only_writes_preview_package_files(project_root):
    before = {p for p in project_root.rglob("*") if p.is_file()}
    write_preview_package(project_root)
    after = {p for p in project_root.rglob("*") if p.is_file()}
    new_files = after - before
    assert new_files == {
        project_root / "preview_package" / "index.json",
        project_root / "preview_package" / "preview_report.md",
    }


def test_write_preview_package_never_touches_brief_status(project_root):
    brief_before = project_store.load_json(project_root / "brief.json")
    write_preview_package(project_root)
    brief_after = project_store.load_json(project_root / "brief.json")
    assert brief_before == brief_after

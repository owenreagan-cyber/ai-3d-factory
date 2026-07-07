from pathlib import Path

from factory.validators.multipart_check import check_manifest


def _checks_by_name(checks):
    return {c["name"]: c for c in checks}


def test_empty_manifest_warns_has_no_parts():
    checks = check_manifest({"parts": []}, Path("."))
    by_name = _checks_by_name(checks)
    assert by_name["manifest_has_parts"]["status"] == "WARN"


def test_single_clean_part_passes_all_checks(tmp_path):
    stl_path = tmp_path / "part.stl"
    stl_path.write_bytes(b"not a real mesh, existence is all that's checked")
    manifest = {
        "parts": [
            {
                "part_name": "part",
                "file_path": "part.stl",
                "export_units": "mm",
                "cad_source": "cad/part.scad",
                "quantity": 1,
                "transform_notes": "single part",
            }
        ]
    }
    checks = check_manifest(manifest, tmp_path)
    by_name = _checks_by_name(checks)
    assert by_name["manifest_has_parts"]["status"] == "PASS"
    assert by_name["duplicate_part_names"]["status"] == "PASS"
    assert by_name["consistent_export_units"]["status"] == "PASS"
    assert by_name["part_files_exist"]["status"] == "PASS"
    assert by_name["duplicate_outputs"]["status"] == "PASS"
    assert by_name["cad_sources_declared"]["status"] == "PASS"
    assert by_name["quantities_valid"]["status"] == "PASS"


def test_duplicate_part_names_fail():
    manifest = {
        "parts": [
            {"part_name": "base", "file_path": "a.stl", "export_units": "mm"},
            {"part_name": "base", "file_path": "b.stl", "export_units": "mm"},
        ]
    }
    checks = _checks_by_name(check_manifest(manifest, Path(".")))
    assert checks["duplicate_part_names"]["status"] == "FAIL"


def test_duplicate_outputs_fail_when_file_paths_collide():
    manifest = {
        "parts": [
            {"part_name": "base", "file_path": "shared.stl", "export_units": "mm"},
            {"part_name": "text", "file_path": "shared.stl", "export_units": "mm"},
        ]
    }
    checks = _checks_by_name(check_manifest(manifest, Path(".")))
    assert checks["duplicate_outputs"]["status"] == "FAIL"


def test_missing_cad_source_warns():
    manifest = {"parts": [{"part_name": "base", "file_path": "a.stl", "export_units": "mm"}]}
    checks = _checks_by_name(check_manifest(manifest, Path(".")))
    assert checks["cad_sources_declared"]["status"] == "WARN"


def test_source_scad_satisfies_cad_source_check():
    manifest = {
        "parts": [{"part_name": "base", "file_path": "a.stl", "export_units": "mm", "source_scad": "cad/base.scad"}]
    }
    checks = _checks_by_name(check_manifest(manifest, Path(".")))
    assert checks["cad_sources_declared"]["status"] == "PASS"


def test_invalid_quantity_fails():
    manifest = {
        "parts": [{"part_name": "base", "file_path": "a.stl", "export_units": "mm", "quantity": 0}]
    }
    checks = _checks_by_name(check_manifest(manifest, Path(".")))
    assert checks["quantities_valid"]["status"] == "FAIL"


def test_missing_quantity_is_not_flagged():
    manifest = {"parts": [{"part_name": "base", "file_path": "a.stl", "export_units": "mm"}]}
    checks = _checks_by_name(check_manifest(manifest, Path(".")))
    assert checks["quantities_valid"]["status"] == "PASS"


def test_shared_origin_consistency_warns_on_mixed_flags():
    manifest = {
        "parts": [
            {"part_name": "base", "file_path": "a.stl", "export_units": "mm", "shared_origin": True},
            {"part_name": "text", "file_path": "b.stl", "export_units": "mm", "shared_origin": False},
        ]
    }
    checks = _checks_by_name(check_manifest(manifest, Path(".")))
    assert checks["shared_origin_consistency"]["status"] == "WARN"


def test_shared_origin_consistency_passes_when_all_true():
    manifest = {
        "parts": [
            {"part_name": "base", "file_path": "a.stl", "export_units": "mm", "shared_origin": True},
            {"part_name": "text", "file_path": "b.stl", "export_units": "mm", "shared_origin": True},
        ]
    }
    checks = _checks_by_name(check_manifest(manifest, Path(".")))
    assert checks["shared_origin_consistency"]["status"] == "PASS"


def test_shared_origin_consistency_not_checked_for_single_part():
    manifest = {"parts": [{"part_name": "base", "file_path": "a.stl", "export_units": "mm"}]}
    checks = _checks_by_name(check_manifest(manifest, Path(".")))
    assert "shared_origin_consistency" not in checks


def test_missing_manifest_entries_warns_when_required_part_absent():
    manifest = {"parts": [{"part_name": "base", "file_path": "a.stl", "export_units": "mm"}]}
    checks = _checks_by_name(check_manifest(manifest, Path("."), required_part_names=["base", "text"]))
    assert checks["missing_manifest_entries"]["status"] == "WARN"
    assert "text" in checks["missing_manifest_entries"]["detail"]


def test_missing_manifest_entries_passes_when_all_present():
    manifest = {"parts": [{"part_name": "base", "file_path": "a.stl", "export_units": "mm"}]}
    checks = _checks_by_name(check_manifest(manifest, Path("."), required_part_names=["base"]))
    assert checks["missing_manifest_entries"]["status"] == "PASS"


def test_missing_manifest_entries_not_checked_without_required_part_names():
    manifest = {"parts": [{"part_name": "base", "file_path": "a.stl", "export_units": "mm"}]}
    checks = _checks_by_name(check_manifest(manifest, Path(".")))
    assert "missing_manifest_entries" not in checks

from typer.testing import CliRunner

from factory.cli import app

runner = CliRunner()


def test_list_printers_shows_all_four():
    result = runner.invoke(app, ["list-printers"])
    assert result.exit_code == 0
    assert "printers (4)" in result.stdout
    for printer_id in ("bambu_h2d", "bambu_p1s_1", "bambu_p1s_2", "elegoo_centauri_carbon"):
        assert printer_id in result.stdout


def test_show_printer_valid_id():
    result = runner.invoke(app, ["show-printer", "bambu_h2d"])
    assert result.exit_code == 0
    assert "Bambu Lab H2D" in result.stdout
    assert "AMS 2 Pro" in result.stdout


def test_show_printer_invalid_id():
    result = runner.invoke(app, ["show-printer", "not_a_real_printer"])
    assert result.exit_code == 1
    assert "unknown printer" in result.stdout.lower()


def test_list_accessories_shows_ams_variants():
    result = runner.invoke(app, ["list-accessories"])
    assert result.exit_code == 0
    assert "ams_2_pro" in result.stdout
    assert "ams_original" in result.stdout


def test_show_accessory_valid_id():
    result = runner.invoke(app, ["show-accessory", "ams_2_pro"])
    assert result.exit_code == 0
    assert "AMS 2 Pro" in result.stdout


def test_show_accessory_invalid_id():
    result = runner.invoke(app, ["show-accessory", "not_a_real_accessory"])
    assert result.exit_code == 1
    assert "unknown accessory" in result.stdout.lower()


def test_list_materials_shows_expected_ids():
    result = runner.invoke(app, ["list-materials"])
    assert result.exit_code == 0
    for material_id in ("pla", "petg", "abs", "asa", "tpu"):
        assert material_id in result.stdout


def test_show_material_valid_id():
    result = runner.invoke(app, ["show-material", "pla"])
    assert result.exit_code == 0
    assert "PLA" in result.stdout
    assert "paintable" in result.stdout.lower()


def test_show_material_invalid_id():
    result = runner.invoke(app, ["show-material", "not_a_real_material"])
    assert result.exit_code == 1
    assert "unknown material" in result.stdout.lower()


def test_fleet_summary_shows_all_four_printers_compactly():
    result = runner.invoke(app, ["fleet-summary"])
    assert result.exit_code == 0
    assert "fleet summary (4 printer(s))" in result.stdout
    assert "H2D" in result.stdout
    assert "Centauri Carbon" in result.stdout


def test_check_manufacturing_passes_on_real_config():
    result = runner.invoke(app, ["check-manufacturing"])
    assert result.exit_code == 0
    assert "0 FAIL" in result.stdout


def test_all_inspection_commands_are_read_only(tmp_path, monkeypatch):
    import factory.project_store as project_store

    # Point CONFIG_DIR's manufacturing subdir at a throwaway copy so we can
    # prove these commands don't write to it, without touching the real repo.
    import shutil

    fake_config = tmp_path / "manufacturing"
    shutil.copytree(project_store.MANUFACTURING_CONFIG_DIR, fake_config)
    monkeypatch.setattr(project_store, "MANUFACTURING_CONFIG_DIR", fake_config)

    before = {p: p.read_bytes() for p in sorted(fake_config.rglob("*.json"))}

    for args in (
        ["list-printers"],
        ["show-printer", "bambu_h2d"],
        ["list-accessories"],
        ["show-accessory", "ams_2_pro"],
        ["list-materials"],
        ["show-material", "pla"],
        ["fleet-summary"],
        ["check-manufacturing"],
    ):
        runner.invoke(app, args)

    after = {p: p.read_bytes() for p in sorted(fake_config.rglob("*.json"))}
    assert before == after
    assert set(before.keys()) == set(after.keys())  # no files added or removed


def test_validate_still_uses_canonical_printer_source_after_legacy_removal(tmp_path, monkeypatch):
    # Regression test for Phase 5: config/printers.json was removed, so
    # `factory validate`'s build-volume-fit check must now resolve the
    # primary printer from config/manufacturing/printers.json. CONFIG_DIR/
    # MANUFACTURING_CONFIG_DIR are left pointed at the real repo config so
    # this exercises the actual canonical file; only PROJECTS_DIR is isolated.
    import trimesh

    from factory import project_store

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    monkeypatch.setattr(project_store, "PROJECTS_DIR", projects_dir)

    result = runner.invoke(app, ["init-project", "phase5-compat-check"])
    assert result.exit_code == 0
    project_dir = projects_dir / "phase5-compat-check"

    mesh_path = project_dir / "stl" / "cube.stl"
    trimesh.creation.box(extents=(20, 20, 20)).export(str(mesh_path))
    validate_result = runner.invoke(app, ["validate", str(mesh_path)])
    assert validate_result.exit_code == 0

    report = project_store.load_json(project_dir / "validation" / "cube_validation.json")
    build_volume_check = next(c for c in report["checks"] if c["name"] == "build_volume_fit")
    assert "Bambu Lab H2D" in build_volume_check["detail"]

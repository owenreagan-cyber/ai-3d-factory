import pytest

from factory.manufacturing.inspect import (
    UnknownAccessoryError,
    UnknownMaterialError,
    UnknownPrinterError,
    fleet_summary,
    get_accessory_or_raise,
    get_material_or_raise,
    get_printer_or_raise,
    list_accessories,
    list_materials,
    list_printers,
)


def test_list_printers_returns_all_four_fleet_printers():
    printers = list_printers()
    ids = {p["printer_id"] for p in printers}
    assert ids == {"bambu_h2d", "bambu_p1s_1", "bambu_p1s_2", "elegoo_centauri_carbon"}


def test_get_printer_or_raise_valid_id():
    printer = get_printer_or_raise("bambu_h2d")
    assert printer["display_name"] == "Bambu Lab H2D"


def test_get_printer_or_raise_invalid_id_lists_valid_ids():
    with pytest.raises(UnknownPrinterError) as exc_info:
        get_printer_or_raise("not_a_real_printer")
    assert "bambu_h2d" in exc_info.value.valid_ids


def test_list_accessories_includes_ams_variants():
    accessories = list_accessories()
    ids = {a["accessory_id"] for a in accessories}
    assert {"ams_original", "ams_2_pro"}.issubset(ids)


def test_get_accessory_or_raise_valid_id():
    accessory = get_accessory_or_raise("ams_2_pro")
    assert accessory["display_name"] == "AMS 2 Pro"


def test_get_accessory_or_raise_invalid_id_lists_valid_ids():
    with pytest.raises(UnknownAccessoryError) as exc_info:
        get_accessory_or_raise("not_a_real_accessory")
    assert "ams_2_pro" in exc_info.value.valid_ids


def test_list_materials_includes_expected_ids():
    materials = list_materials()
    ids = {m["material_id"] for m in materials}
    assert ids == {"pla", "pla_plus", "petg", "abs", "asa", "tpu"}


def test_get_material_or_raise_valid_id():
    material = get_material_or_raise("pla")
    assert material["display_name"] == "PLA"


def test_get_material_or_raise_invalid_id_lists_valid_ids():
    with pytest.raises(UnknownMaterialError) as exc_info:
        get_material_or_raise("not_a_real_material")
    assert "pla" in exc_info.value.valid_ids


def test_fleet_summary_returns_four_printers_compactly():
    summaries = fleet_summary()
    assert len(summaries) == 4
    for summary in summaries:
        assert set(summary.keys()) == {
            "printer_id",
            "display_name",
            "unit_label",
            "manufacturer",
            "model",
            "build_volume_mm",
            "installed_accessories",
            "multicolor_supported",
            "ams_supported",
            "verified",
        }


def test_fleet_summary_reflects_ams_installation_per_printer():
    summaries = {s["printer_id"]: s for s in fleet_summary()}
    assert summaries["bambu_h2d"]["installed_accessories"] == ["AMS 2 Pro"]
    assert summaries["elegoo_centauri_carbon"]["installed_accessories"] == []
    assert summaries["elegoo_centauri_carbon"]["multicolor_supported"] is False

from factory.manufacturing import knowledge


def test_load_printers_includes_expected_fleet():
    printers = knowledge.load_printers()
    assert set(printers) == {"bambu_h2d", "bambu_p1s_1", "bambu_p1s_2", "elegoo_centauri_carbon"}


def test_load_printers_all_have_required_fields():
    required = {
        "printer_id",
        "display_name",
        "manufacturer",
        "model",
        "build_volume_mm",
        "enclosed",
        "default_nozzle_mm",
        "supported_nozzle_sizes_mm",
        "default_build_plate",
        "supported_build_plates",
        "default_materials",
        "supported_materials",
        "multicolor_supported",
        "ams_supported",
        "installed_accessories",
        "preferred_job_types",
        "notes",
    }
    for printer_id, printer in knowledge.load_printers().items():
        missing = required - set(printer)
        assert not missing, f"{printer_id} missing fields: {missing}"


def test_h2d_has_ams_2_pro_and_p1s_units_have_original_ams():
    printers = knowledge.load_printers()
    assert printers["bambu_h2d"]["installed_accessories"] == ["ams_2_pro"]
    assert printers["bambu_p1s_1"]["installed_accessories"] == ["ams_original"]
    assert printers["bambu_p1s_2"]["installed_accessories"] == ["ams_original"]


def test_centauri_carbon_has_no_ams_installed():
    printers = knowledge.load_printers()
    centauri = printers["elegoo_centauri_carbon"]
    assert centauri["installed_accessories"] == []
    assert centauri["ams_supported"] is False
    assert centauri["multicolor_supported"] is False


def test_load_accessories_includes_expected_catalog():
    accessories = knowledge.load_accessories()
    assert set(accessories) == {
        "ams_original",
        "ams_2_pro",
        "build_plate_smooth_pei",
        "build_plate_textured_pei",
        "build_plate_engineering",
        "nozzle_0_2",
        "nozzle_0_4",
        "nozzle_0_6",
        "nozzle_0_8",
    }


def test_load_materials_includes_expected_ids():
    materials = knowledge.load_materials()
    assert set(materials) == {"pla", "pla_plus", "petg", "abs", "asa", "tpu"}
    for material_id, material in materials.items():
        assert "good_for" in material, f"{material_id} missing good_for tags"


def test_load_planning_rules_has_seven_manufacturing_options():
    rules = knowledge.load_planning_rules()
    options = rules["manufacturing_options"]
    assert set(options) == {
        "single_piece",
        "multipart_build_volume",
        "multipart_color",
        "multipart_detail",
        "multipart_paint",
        "multipart_strength",
        "replaceable_components",
    }
    for option_id, option in options.items():
        assert option["advantages"], f"{option_id} has no advantages"
        assert option["disadvantages"], f"{option_id} has no disadvantages"


def test_find_printer_by_name_resolves_unambiguous_match():
    printer = knowledge.find_printer_by_name("Bambu H2D")
    assert printer is not None
    assert printer["printer_id"] == "bambu_h2d"


def test_find_printer_by_name_returns_none_for_ambiguous_match():
    # Two P1S units exist; free text without a unit label can't resolve to one.
    assert knowledge.find_printer_by_name("Bambu P1S") is None


def test_find_printer_by_name_returns_none_for_unknown_printer():
    assert knowledge.find_printer_by_name("Prusa MK4") is None


def test_find_printer_by_name_returns_none_for_empty_input():
    assert knowledge.find_printer_by_name("") is None
    assert knowledge.find_printer_by_name(None) is None


def test_printer_capabilities_merges_installed_accessory_capabilities():
    h2d = knowledge.get_printer("bambu_h2d")
    capabilities = knowledge.printer_capabilities(h2d)
    assert capabilities["multicolor_supported"] is True
    assert "multicolor" in capabilities["added_capabilities"]
    assert len(capabilities["installed_accessories"]) == 1
    assert capabilities["installed_accessories"][0]["accessory_id"] == "ams_2_pro"


def test_printer_capabilities_for_printer_with_no_accessories():
    centauri = knowledge.get_printer("elegoo_centauri_carbon")
    capabilities = knowledge.printer_capabilities(centauri)
    assert capabilities["multicolor_supported"] is False
    assert capabilities["installed_accessories"] == []
    assert capabilities["added_capabilities"] == []

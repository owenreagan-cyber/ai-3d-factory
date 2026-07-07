from factory.manufacturing import check


def _checks_by_name(checks):
    return {c["name"]: c for c in checks}


VALID_PRINTERS_DOC = {
    "primary_printer": "p1",
    "printers": {
        "p1": {
            "printer_id": "p1",
            "display_name": "Test Printer",
            "manufacturer": "Test",
            "model": "T1",
            "build_volume_mm": {"x": 200, "y": 200, "z": 200},
            "enclosed": True,
            "default_nozzle_mm": 0.4,
            "supported_nozzle_sizes_mm": [0.4],
            "default_build_plate": "build_plate_smooth_pei",
            "supported_build_plates": ["build_plate_smooth_pei"],
            "default_materials": ["pla"],
            "supported_materials": ["pla"],
            "multicolor_supported": False,
            "ams_supported": False,
            "installed_accessories": [],
            "preferred_job_types": ["prototyping"],
            "notes": "test printer",
        }
    },
}
VALID_ACCESSORIES_DOC = {"accessories": {"ams_original": {"accessory_id": "ams_original"}}}
VALID_MATERIALS_DOC = {"materials": {"pla": {"material_id": "pla"}}}
VALID_PLANNING_RULES_DOC = {
    "manufacturing_options": {
        option_id: {}
        for option_id in (
            "single_piece",
            "multipart_build_volume",
            "multipart_color",
            "multipart_detail",
            "multipart_paint",
            "multipart_strength",
            "replaceable_components",
        )
    }
}


def _patch_docs(monkeypatch, **overrides):
    docs = {
        "printers.json": VALID_PRINTERS_DOC,
        "accessories.json": VALID_ACCESSORIES_DOC,
        "materials.json": VALID_MATERIALS_DOC,
        "planning_rules.json": VALID_PLANNING_RULES_DOC,
    }
    docs.update(overrides)

    def fake_load(name):
        return docs.get(name)

    monkeypatch.setattr(check, "_load_or_none", fake_load)


def test_real_manufacturing_config_passes_with_no_failures():
    checks = check.check_manufacturing_knowledge_base()
    fail_count = sum(1 for c in checks if c["status"] == "FAIL")
    assert fail_count == 0, [c for c in checks if c["status"] == "FAIL"]


def test_valid_fake_config_passes_cleanly(monkeypatch):
    _patch_docs(monkeypatch)
    checks = _checks_by_name(check.check_manufacturing_knowledge_base())
    assert checks["printers_json_loads"]["status"] == "PASS"
    assert checks["printer_ids_unique"]["status"] == "PASS"
    assert checks["build_volumes_positive"]["status"] == "PASS"
    assert checks["nozzle_sizes_positive"]["status"] == "PASS"
    assert checks["installed_accessories_known"]["status"] == "PASS"
    assert checks["primary_printer_valid"]["status"] == "PASS"


def test_missing_config_file_fails(monkeypatch):
    _patch_docs(monkeypatch, **{"accessories.json": None})
    checks = _checks_by_name(check.check_manufacturing_knowledge_base())
    assert checks["accessories_json_loads"]["status"] == "FAIL"
    assert checks["manufacturing_config_complete"]["status"] == "FAIL"


def test_duplicate_printer_id_detected(monkeypatch):
    doc = {
        "primary_printer": "p1",
        "printers": {
            "p1": {**VALID_PRINTERS_DOC["printers"]["p1"], "printer_id": "dup"},
            "p2": {**VALID_PRINTERS_DOC["printers"]["p1"], "printer_id": "dup"},
        },
    }
    _patch_docs(monkeypatch, **{"printers.json": doc})
    checks = _checks_by_name(check.check_manufacturing_knowledge_base())
    assert checks["printer_ids_unique"]["status"] == "FAIL"
    assert "dup" in checks["printer_ids_unique"]["detail"]


def test_duplicate_accessory_id_detected(monkeypatch):
    doc = {
        "accessories": {
            "a1": {"accessory_id": "dup"},
            "a2": {"accessory_id": "dup"},
        }
    }
    _patch_docs(monkeypatch, **{"accessories.json": doc})
    checks = _checks_by_name(check.check_manufacturing_knowledge_base())
    assert checks["accessory_ids_unique"]["status"] == "FAIL"


def test_duplicate_material_id_detected(monkeypatch):
    doc = {
        "materials": {
            "m1": {"material_id": "dup"},
            "m2": {"material_id": "dup"},
        }
    }
    _patch_docs(monkeypatch, **{"materials.json": doc})
    checks = _checks_by_name(check.check_manufacturing_knowledge_base())
    assert checks["material_ids_unique"]["status"] == "FAIL"


def test_missing_accessory_reference_fails(monkeypatch):
    doc = {
        "primary_printer": "p1",
        "printers": {
            "p1": {**VALID_PRINTERS_DOC["printers"]["p1"], "installed_accessories": ["not_a_real_accessory"]},
        },
    }
    _patch_docs(monkeypatch, **{"printers.json": doc})
    checks = _checks_by_name(check.check_manufacturing_knowledge_base())
    assert checks["installed_accessories_known"]["status"] == "FAIL"
    assert "not_a_real_accessory" in checks["installed_accessories_known"]["detail"]


def test_invalid_build_volume_fails(monkeypatch):
    doc = {
        "primary_printer": "p1",
        "printers": {
            "p1": {**VALID_PRINTERS_DOC["printers"]["p1"], "build_volume_mm": {"x": -10, "y": 200, "z": 200}},
        },
    }
    _patch_docs(monkeypatch, **{"printers.json": doc})
    checks = _checks_by_name(check.check_manufacturing_knowledge_base())
    assert checks["build_volumes_positive"]["status"] == "FAIL"


def test_invalid_nozzle_size_fails(monkeypatch):
    doc = {
        "primary_printer": "p1",
        "printers": {
            "p1": {**VALID_PRINTERS_DOC["printers"]["p1"], "supported_nozzle_sizes_mm": [0.4, 0, -0.2]},
        },
    }
    _patch_docs(monkeypatch, **{"printers.json": doc})
    checks = _checks_by_name(check.check_manufacturing_knowledge_base())
    assert checks["nozzle_sizes_positive"]["status"] == "FAIL"


def test_missing_required_printer_field_fails(monkeypatch):
    incomplete_printer = dict(VALID_PRINTERS_DOC["printers"]["p1"])
    del incomplete_printer["build_volume_mm"]
    doc = {"primary_printer": "p1", "printers": {"p1": incomplete_printer}}
    _patch_docs(monkeypatch, **{"printers.json": doc})
    checks = _checks_by_name(check.check_manufacturing_knowledge_base())
    assert checks["printer_required_fields"]["status"] == "FAIL"
    assert "build_volume_mm" in checks["printer_required_fields"]["detail"]


def test_missing_optional_notes_does_not_fail(monkeypatch):
    printer = dict(VALID_PRINTERS_DOC["printers"]["p1"])
    printer["notes"] = ""
    doc = {"primary_printer": "p1", "printers": {"p1": printer}}
    _patch_docs(monkeypatch, **{"printers.json": doc})
    checks = _checks_by_name(check.check_manufacturing_knowledge_base())
    assert checks["printer_required_fields"]["status"] == "PASS"


def test_unknown_supported_material_warns_not_fails(monkeypatch):
    doc = {
        "primary_printer": "p1",
        "printers": {
            "p1": {**VALID_PRINTERS_DOC["printers"]["p1"], "supported_materials": ["not_a_real_material"]},
        },
    }
    _patch_docs(monkeypatch, **{"printers.json": doc})
    checks = _checks_by_name(check.check_manufacturing_knowledge_base())
    assert checks["supported_materials_known"]["status"] == "WARN"


def test_invalid_primary_printer_reference_fails(monkeypatch):
    doc = {"primary_printer": "does_not_exist", "printers": {"p1": VALID_PRINTERS_DOC["printers"]["p1"]}}
    _patch_docs(monkeypatch, **{"printers.json": doc})
    checks = _checks_by_name(check.check_manufacturing_knowledge_base())
    assert checks["primary_printer_valid"]["status"] == "FAIL"


def test_planning_rules_missing_option_ids_warns(monkeypatch):
    _patch_docs(monkeypatch, **{"planning_rules.json": {"manufacturing_options": {"single_piece": {}}}})
    checks = _checks_by_name(check.check_manufacturing_knowledge_base())
    assert checks["planning_rules_option_ids"]["status"] == "WARN"

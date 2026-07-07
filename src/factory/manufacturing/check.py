"""Local, read-only validation of the manufacturing knowledge base.

Backs `factory check-manufacturing`. Reads config/manufacturing/*.json and
reports PASS/WARN/FAIL per check, mirroring the style of
factory.validators.mesh_validate/multipart_check. Never writes files, never
contacts a printer/slicer/network, and never discovers hardware - it only
checks that the local JSON is internally consistent. See
docs/manufacturing-knowledge-base.md.
"""

from __future__ import annotations

from typing import Any

from factory import project_store

REQUIRED_PRINTER_FIELDS = (
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
)

_MANUFACTURING_OPTION_IDS = {
    "single_piece",
    "multipart_build_volume",
    "multipart_color",
    "multipart_detail",
    "multipart_paint",
    "multipart_strength",
    "replaceable_components",
}


def _load_or_none(name: str) -> dict[str, Any] | None:
    path = project_store.MANUFACTURING_CONFIG_DIR / name
    if not path.is_file():
        return None
    try:
        return project_store.load_json(path)
    except Exception:  # noqa: BLE001 - any parse/read failure means "did not load"
        return None


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def check_manufacturing_knowledge_base() -> list[dict[str, str]]:
    """Validate config/manufacturing/*.json. Returns a list of check dicts."""
    checks: list[dict[str, str]] = []

    printers_doc = _load_or_none("printers.json")
    accessories_doc = _load_or_none("accessories.json")
    materials_doc = _load_or_none("materials.json")
    planning_rules_doc = _load_or_none("planning_rules.json")

    checks.append(
        _check("printers_json_loads", "PASS" if printers_doc is not None else "FAIL", "config/manufacturing/printers.json")
    )
    checks.append(
        _check(
            "accessories_json_loads",
            "PASS" if accessories_doc is not None else "FAIL",
            "config/manufacturing/accessories.json",
        )
    )
    checks.append(
        _check(
            "materials_json_loads", "PASS" if materials_doc is not None else "FAIL", "config/manufacturing/materials.json"
        )
    )
    checks.append(
        _check(
            "planning_rules_json_loads",
            "PASS" if planning_rules_doc is not None else "FAIL",
            "config/manufacturing/planning_rules.json",
        )
    )

    if printers_doc is None or accessories_doc is None or materials_doc is None or planning_rules_doc is None:
        checks.append(
            _check(
                "manufacturing_config_complete",
                "FAIL",
                "One or more required config/manufacturing/*.json files failed to load; skipping further checks.",
            )
        )
        return checks

    printers = printers_doc.get("printers", {})
    accessories = accessories_doc.get("accessories", {})
    materials = materials_doc.get("materials", {})

    checks.extend(_check_unique_and_consistent_ids("printer", printers, "printer_id"))
    checks.extend(_check_unique_and_consistent_ids("accessory", accessories, "accessory_id"))
    checks.extend(_check_unique_and_consistent_ids("material", materials, "material_id"))

    checks.extend(_check_required_printer_fields(printers))
    checks.extend(_check_positive_build_volumes(printers))
    checks.extend(_check_positive_nozzle_sizes(printers))
    checks.extend(_check_installed_accessories_known(printers, accessories))
    checks.extend(_check_supported_materials_known(printers, materials))
    checks.extend(_check_planning_rules_option_ids(planning_rules_doc))

    primary_printer = printers_doc.get("primary_printer")
    if primary_printer and primary_printer not in printers:
        checks.append(
            _check(
                "primary_printer_valid",
                "FAIL",
                f"primary_printer {primary_printer!r} does not match any printer_id in printers.json.",
            )
        )
    else:
        checks.append(_check("primary_printer_valid", "PASS", f"primary_printer: {primary_printer!r}"))

    return checks


def _check_unique_and_consistent_ids(kind: str, entries: dict[str, Any], id_field: str) -> list[dict[str, str]]:
    checks = []
    declared_ids = [entry.get(id_field) for entry in entries.values()]
    duplicates = sorted({i for i in declared_ids if i and declared_ids.count(i) > 1})
    if duplicates:
        checks.append(_check(f"{kind}_ids_unique", "FAIL", f"Duplicate {id_field} values: {duplicates}."))
    else:
        checks.append(_check(f"{kind}_ids_unique", "PASS", f"All {len(entries)} {kind} id(s) are unique."))

    mismatched = [key for key, entry in entries.items() if entry.get(id_field) and entry.get(id_field) != key]
    if mismatched:
        checks.append(
            _check(
                f"{kind}_ids_consistent",
                "FAIL",
                f"{kind} entries whose {id_field} field doesn't match their JSON key: {sorted(mismatched)}.",
            )
        )
    else:
        checks.append(_check(f"{kind}_ids_consistent", "PASS", f"Every {kind}'s {id_field} matches its JSON key."))
    return checks


def _check_required_printer_fields(printers: dict[str, Any]) -> list[dict[str, str]]:
    missing_by_printer = {}
    for printer_id, printer in printers.items():
        missing = [f for f in REQUIRED_PRINTER_FIELDS if f not in printer]
        if missing:
            missing_by_printer[printer_id] = missing

    if missing_by_printer:
        return [
            _check(
                "printer_required_fields",
                "FAIL",
                f"Printers missing required fields: {missing_by_printer}.",
            )
        ]
    return [_check("printer_required_fields", "PASS", "Every printer has all required fields.")]


def _check_positive_build_volumes(printers: dict[str, Any]) -> list[dict[str, str]]:
    bad = []
    for printer_id, printer in printers.items():
        build_volume = printer.get("build_volume_mm") or {}
        dims = (build_volume.get("x"), build_volume.get("y"), build_volume.get("z"))
        if any(not isinstance(d, (int, float)) or isinstance(d, bool) or d <= 0 for d in dims):
            bad.append(printer_id)

    if bad:
        return [_check("build_volumes_positive", "FAIL", f"Printers with a non-positive/invalid build_volume_mm: {sorted(bad)}.")]
    return [_check("build_volumes_positive", "PASS", "Every printer's build_volume_mm is positive on all axes.")]


def _check_positive_nozzle_sizes(printers: dict[str, Any]) -> list[dict[str, str]]:
    bad = []
    for printer_id, printer in printers.items():
        default_nozzle = printer.get("default_nozzle_mm")
        sizes = printer.get("supported_nozzle_sizes_mm", [])
        values = [default_nozzle, *sizes]
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0 for v in values if v is not None):
            bad.append(printer_id)

    if bad:
        return [_check("nozzle_sizes_positive", "FAIL", f"Printers with a non-positive/invalid nozzle size: {sorted(bad)}.")]
    return [_check("nozzle_sizes_positive", "PASS", "Every printer's nozzle size(s) are positive.")]


def _check_installed_accessories_known(printers: dict[str, Any], accessories: dict[str, Any]) -> list[dict[str, str]]:
    unknown_refs = {}
    for printer_id, printer in printers.items():
        unknown = [a for a in printer.get("installed_accessories", []) if a not in accessories]
        if unknown:
            unknown_refs[printer_id] = unknown

    if unknown_refs:
        return [
            _check(
                "installed_accessories_known",
                "FAIL",
                f"Printers reference unknown accessory id(s): {unknown_refs}.",
            )
        ]
    return [_check("installed_accessories_known", "PASS", "Every installed_accessories entry references a known accessory.")]


def _check_supported_materials_known(printers: dict[str, Any], materials: dict[str, Any]) -> list[dict[str, str]]:
    unknown_refs = {}
    for printer_id, printer in printers.items():
        unknown = [m for m in printer.get("supported_materials", []) if m not in materials]
        if unknown:
            unknown_refs[printer_id] = unknown

    if unknown_refs:
        return [
            _check(
                "supported_materials_known",
                "WARN",
                f"Printers reference material id(s) not found in materials.json: {unknown_refs}.",
            )
        ]
    return [_check("supported_materials_known", "PASS", "Every supported_materials entry references a known material.")]


def _check_planning_rules_option_ids(planning_rules_doc: dict[str, Any]) -> list[dict[str, str]]:
    option_ids = set(planning_rules_doc.get("manufacturing_options", {}).keys())
    unexpected = sorted(option_ids - _MANUFACTURING_OPTION_IDS)
    missing = sorted(_MANUFACTURING_OPTION_IDS - option_ids)

    if unexpected or missing:
        detail_parts = []
        if missing:
            detail_parts.append(f"missing: {missing}")
        if unexpected:
            detail_parts.append(f"unexpected: {unexpected}")
        return [_check("planning_rules_option_ids", "WARN", "; ".join(detail_parts))]
    return [_check("planning_rules_option_ids", "PASS", "planning_rules.json's option ids match factory.manufacturing.decision_engine's known set.")]

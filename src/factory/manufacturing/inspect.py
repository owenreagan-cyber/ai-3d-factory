"""Read-only lookups over the manufacturing knowledge base.

Backs `factory list-printers`/`show-printer`/`list-accessories`/
`show-accessory`/`list-materials`/`show-material`/`fleet-summary`. Every
function here only reads config/manufacturing/*.json - no writes, no
project state changes, no network, no printer/slicer discovery or contact.
See docs/manufacturing-knowledge-base.md.
"""

from __future__ import annotations

from typing import Any

from factory.manufacturing import knowledge


class UnknownPrinterError(Exception):
    def __init__(self, printer_id: str, valid_ids: list[str]):
        self.printer_id = printer_id
        self.valid_ids = valid_ids
        super().__init__(f"Unknown printer {printer_id!r}. Known printers: {', '.join(sorted(valid_ids))}.")


class UnknownAccessoryError(Exception):
    def __init__(self, accessory_id: str, valid_ids: list[str]):
        self.accessory_id = accessory_id
        self.valid_ids = valid_ids
        super().__init__(f"Unknown accessory {accessory_id!r}. Known accessories: {', '.join(sorted(valid_ids))}.")


class UnknownMaterialError(Exception):
    def __init__(self, material_id: str, valid_ids: list[str]):
        self.material_id = material_id
        self.valid_ids = valid_ids
        super().__init__(f"Unknown material {material_id!r}. Known materials: {', '.join(sorted(valid_ids))}.")


def list_printers() -> list[dict[str, Any]]:
    """Return every printer's raw config entry (see knowledge.printer_capabilities()
    for the merged-with-accessories view used by `show-printer`/`fleet-summary`)."""
    return list(knowledge.load_printers().values())


def get_printer_or_raise(printer_id: str) -> dict[str, Any]:
    printer = knowledge.get_printer(printer_id)
    if printer is None:
        raise UnknownPrinterError(printer_id, list(knowledge.load_printers().keys()))
    return printer


def list_accessories() -> list[dict[str, Any]]:
    return list(knowledge.load_accessories().values())


def get_accessory_or_raise(accessory_id: str) -> dict[str, Any]:
    accessory = knowledge.get_accessory(accessory_id)
    if accessory is None:
        raise UnknownAccessoryError(accessory_id, list(knowledge.load_accessories().keys()))
    return accessory


def list_materials() -> list[dict[str, Any]]:
    return list(knowledge.load_materials().values())


def get_material_or_raise(material_id: str) -> dict[str, Any]:
    material = knowledge.get_material(material_id)
    if material is None:
        raise UnknownMaterialError(material_id, list(knowledge.load_materials().keys()))
    return material


def fleet_summary() -> list[dict[str, Any]]:
    """Return a compact capability summary for every printer in the fleet."""
    printers = knowledge.load_printers()
    summaries = []
    for printer in printers.values():
        capabilities = knowledge.printer_capabilities(printer)
        accessory_names = [a.get("display_name", "?") for a in capabilities["installed_accessories"]]
        summaries.append(
            {
                "printer_id": printer.get("printer_id"),
                "display_name": printer.get("display_name"),
                "unit_label": printer.get("unit_label"),
                "manufacturer": printer.get("manufacturer"),
                "model": printer.get("model"),
                "build_volume_mm": printer.get("build_volume_mm"),
                "installed_accessories": accessory_names,
                "multicolor_supported": capabilities["multicolor_supported"],
                "ams_supported": capabilities["ams_supported"],
                "verified": capabilities["verified"],
            }
        )
    return summaries

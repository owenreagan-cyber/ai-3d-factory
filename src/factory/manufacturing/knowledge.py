"""Local manufacturing knowledge base loader.

Reads config/manufacturing/{printers,materials,accessories,planning_rules}.json.
Local filesystem only: no network calls, no printer discovery, no hardware
detection or communication. installed_accessories is hand-maintained config
data, never a live hardware read. See docs/manufacturing-knowledge-base.md
and AGENT.md.
"""

from __future__ import annotations

import re
from typing import Any

from factory import project_store


def _load(name: str) -> dict[str, Any]:
    path = project_store.MANUFACTURING_CONFIG_DIR / name
    if not path.is_file():
        return {}
    return project_store.load_json(path)


def load_printers() -> dict[str, Any]:
    """Return the {printer_id: {...}} mapping from config/manufacturing/printers.json."""
    return _load("printers.json").get("printers", {})


def load_materials() -> dict[str, Any]:
    """Return the {material_id: {...}} mapping from config/manufacturing/materials.json."""
    return _load("materials.json").get("materials", {})


def load_accessories() -> dict[str, Any]:
    """Return the {accessory_id: {...}} mapping from config/manufacturing/accessories.json."""
    return _load("accessories.json").get("accessories", {})


def load_planning_rules() -> dict[str, Any]:
    """Return the full contents of config/manufacturing/planning_rules.json."""
    return _load("planning_rules.json")


def get_primary_printer_id() -> str | None:
    return _load("printers.json").get("primary_printer")


def get_printer(printer_id: str) -> dict[str, Any] | None:
    return load_printers().get(printer_id)


def get_accessory(accessory_id: str) -> dict[str, Any] | None:
    return load_accessories().get(accessory_id)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def find_printer_by_name(name: str | None) -> dict[str, Any] | None:
    """Best-effort, token-based match of free text (e.g. brief.json's
    intended_printer) against known printers' display_name/unit_label/model/
    manufacturer/printer_id.

    A printer matches if every word in `name` also appears somewhere in that
    printer's identifying fields (e.g. "Bambu H2D" matches "Bambu Lab H2D").
    Returns None - never guesses - when there is no match or more than one
    equally plausible match (e.g. "Bambu P1S" matches both P1S units).
    """
    needle_tokens = _tokens(name or "")
    if not needle_tokens:
        return None

    matches = []
    for printer in load_printers().values():
        haystack = " ".join(
            str(printer.get(field, ""))
            for field in ("display_name", "unit_label", "model", "manufacturer", "printer_id")
        )
        if needle_tokens <= _tokens(haystack):
            matches.append(printer)

    if len(matches) == 1:
        return matches[0]
    return None


def printer_capabilities(printer: dict[str, Any]) -> dict[str, Any]:
    """Merge a printer's own declared fields with capabilities added by its
    installed_accessories (per config/manufacturing/accessories.json).

    Reads config data only - never live hardware state.
    """
    accessories = load_accessories()
    installed_ids = printer.get("installed_accessories", [])
    added_capabilities: set[str] = set()
    installed_details = []
    for accessory_id in installed_ids:
        accessory = accessories.get(accessory_id)
        if accessory is None:
            continue
        added_capabilities.update(accessory.get("adds_capabilities", []))
        installed_details.append(accessory)

    return {
        "printer_id": printer.get("printer_id"),
        "display_name": printer.get("display_name"),
        "unit_label": printer.get("unit_label"),
        "build_volume_mm": printer.get("build_volume_mm"),
        "multicolor_supported": bool(printer.get("multicolor_supported", False))
        or "multicolor" in added_capabilities,
        "ams_supported": bool(printer.get("ams_supported", False)),
        "installed_accessories": installed_details,
        "added_capabilities": sorted(added_capabilities),
        "verified": bool(printer.get("verified", False)),
        "verification_note": printer.get("verification_note"),
        "notes": printer.get("notes"),
    }

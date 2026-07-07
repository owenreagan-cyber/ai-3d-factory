"""Part-manifest integration for CAD backends other than the built-in
OpenSCAD generator (see factory.openscad.generate._upsert_manifest_parts for
that path, which this does not touch or duplicate).

Used by the CadQuery starter backend (factory.cad.cadquery_backend). Local
filesystem only: no network, no printer/slicer contact. Same
upsert-by-part_name pattern used elsewhere in this repo (see
factory.manufacturing.manifest): a regeneration of the same part_name
refreshes the fields this function manages, but never touches a field it
doesn't know about (e.g. a human-added note), and never duplicates an entry.
OpenSCAD and CadQuery parts coexist in the same manifest, keyed by
part_name - this never touches an existing OpenSCAD-authored entry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import project_store

BACKEND_ID = "cadquery"


def upsert_cadquery_manifest_entry(
    project_dir: Path,
    *,
    part_name: str,
    cad_source: str,
    expected_stl_path: str,
    role: str = "mechanical_part",
    template: str = "mechanical-plate",
) -> Path:
    """Upsert one part_manifest.json entry for a CadQuery-generated part.

    Returns the manifest path. Never duplicates an entry for `part_name`,
    never overwrites a field this function doesn't manage, and never touches
    any other part's entry (including OpenSCAD-authored ones).
    """
    project_dir = Path(project_dir)
    manifest_path = project_dir / "part_manifest.json"
    manifest = project_store.load_json(manifest_path) if manifest_path.is_file() else {"parts": []}
    parts = manifest.setdefault("parts", [])
    by_name = {part.get("part_name"): part for part in parts}

    managed_fields = {
        "part_name": part_name,
        "file_path": expected_stl_path,
        "cad_source": cad_source,
        "backend": BACKEND_ID,
        "source": f"ai-3d-factory CadQuery template: {template}",
        "license": "original",
        "role": role,
        "required_for_assembly": True,
        "export_units": "mm",
    }

    entry = by_name.get(part_name)
    if entry is None:
        entry = dict(managed_fields)
        entry.setdefault("material", "TBD - human decision")
        entry.setdefault("color", "TBD - human decision")
        parts.append(entry)
        by_name[part_name] = entry
    else:
        entry.update(managed_fields)

    project_store.save_json(manifest_path, manifest)
    return manifest_path

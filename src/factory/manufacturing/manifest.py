"""Planning-time part_manifest.json seeding.

Runs from `factory plan`, before any CAD or STL exists for a project. This
only ever *fills in* manifest fields that are not already present for a given
part_name - it never overwrites a value already set, whether that value came
from a human hand-edit or from a later phase (e.g. `factory generate-openscad`
setting the real cad_source/file_path/material/color once CAD is actually
generated). Local filesystem only - see docs/file-lifecycle.md and
docs/manufacturing-knowledge-base.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import project_store


def seed_manifest_from_plan(project_dir: Path, build_plan: dict[str, Any]) -> Path:
    """Upsert one part_manifest.json entry per build_plan['required_parts'] entry.

    Never overwrites an existing key on an existing part_name entry, and
    never duplicates an entry for a part_name that's already present.
    """
    project_dir = Path(project_dir)
    manifest_path = project_dir / "part_manifest.json"
    manifest = project_store.load_json(manifest_path) if manifest_path.is_file() else {"parts": []}
    parts = manifest.setdefault("parts", [])
    by_name = {part.get("part_name"): part for part in parts}

    required_parts = build_plan.get("required_parts", [])
    multi_part = len(required_parts) > 1
    shared_origin_note = (
        "Multiple parts share one origin/coordinate system - see docs/slicer-review-workflow.md."
        if multi_part
        else "Single part, no alignment with other parts needed."
    )

    for required_part in required_parts:
        part_name = required_part.get("part_name")
        if not part_name:
            continue
        slug = project_store.slugify(part_name)
        placeholder_material = "TBD - human decision"
        placeholder_color = "TBD - human decision"
        seed_values = {
            "part_name": part_name,
            "source_scad": f"cad/{slug}.scad",
            "file_path": f"stl/{slug}.stl",
            "material": placeholder_material,
            "color": placeholder_color,
            "intended_material": placeholder_material,
            "intended_color": placeholder_color,
            "quantity": 1,
            "shared_origin": multi_part,
            "transform_notes": shared_origin_note,
            "export_units": "mm",
            "export_expected": True,
            "source": "ai-3d-factory manufacturing planner (seed)",
            "license": "original",
            "role": required_part.get("role", "primary"),
            "required_for_assembly": True,
        }

        entry = by_name.get(part_name)
        if entry is None:
            entry = dict(seed_values)
            parts.append(entry)
            by_name[part_name] = entry
        else:
            for key, value in seed_values.items():
                entry.setdefault(key, value)

    project_store.save_json(manifest_path, manifest)
    return manifest_path

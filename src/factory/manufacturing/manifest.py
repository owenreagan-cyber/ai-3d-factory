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

MULTIPART_OPTION_IDS = {
    "multipart_build_volume",
    "multipart_color",
    "multipart_detail",
    "multipart_paint",
    "multipart_strength",
    "replaceable_components",
}


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


def compute_assembly_intent(build_plan: dict[str, Any]) -> dict[str, Any]:
    """Summarize what a selected manufacturing_option means for assembly, without
    ever inventing a part breakdown.

    If the selected option implies a multi-part approach but
    build_plan['required_parts'] still only describes a single placeholder
    part, this reports that plainly (status "multipart_incomplete") instead
    of fabricating detailed geometry/parts - see docs/roadmap.md Phase 4.
    """
    selected_option_id = build_plan.get("selected_manufacturing_option")
    required_parts = build_plan.get("required_parts", [])
    parts_look_detailed = len(required_parts) > 1
    implies_multipart = selected_option_id in MULTIPART_OPTION_IDS

    if selected_option_id is None:
        status = "no_option_selected"
        note = "No manufacturing_option selected yet - run `factory choose-option`."
    elif implies_multipart and not parts_look_detailed:
        status = "multipart_incomplete"
        note = (
            "Selected option implies multipart planning, but detailed required_parts are still "
            "incomplete. Refine build_plan.json's required_parts (and re-run `factory plan`) before "
            "generating multi-part CAD."
        )
    elif implies_multipart:
        status = "multipart_ready"
        note = (
            f"Selected option {selected_option_id!r} implies multipart planning; "
            f"{len(required_parts)} part(s) currently planned."
        )
    else:
        status = "single_piece_ready"
        note = f"Selected option {selected_option_id!r} is a single-piece approach."

    return {
        "selected_manufacturing_option": selected_option_id,
        "status": status,
        "note": note,
        "cad_generation_safe": status in ("single_piece_ready", "multipart_ready"),
        "multipart_incomplete": status == "multipart_incomplete",
    }


def apply_selected_option_to_manifest(project_dir: Path, build_plan: dict[str, Any]) -> dict[str, Any]:
    """Persist compute_assembly_intent()'s result into part_manifest.json.

    Only ever writes the top-level `assembly_intent` key - the `parts` array
    (and any human edits within it) is read back and re-saved untouched, so
    this never duplicates, fabricates, or overwrites a part entry.
    """
    project_dir = Path(project_dir)
    manifest_path = project_dir / "part_manifest.json"
    manifest = project_store.load_json(manifest_path) if manifest_path.is_file() else {"parts": []}

    assembly_intent = compute_assembly_intent(build_plan)
    manifest["assembly_intent"] = assembly_intent
    project_store.save_json(manifest_path, manifest)
    return assembly_intent

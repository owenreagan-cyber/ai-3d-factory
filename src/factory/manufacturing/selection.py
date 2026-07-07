"""Human manufacturing-option selection workflow.

`factory list-options` reads build_plan.json's manufacturing_options and
presents them for a human to review. `factory choose-option` records that
explicit choice. Both are local JSON read/write only: no CAD/geometry
manipulation, no OpenSCAD invocation, no STL export, no contact with a
printer, slicer, or network, and no path here ever sets human_approved or
print_ready. See docs/manufacturing-knowledge-base.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import project_store
from factory.manufacturing.manifest import apply_selected_option_to_manifest

NEW_STATUS_AFTER_SELECTION = "manufacturing_option_selected"


class BuildPlanNotFoundError(Exception):
    pass


class UnknownManufacturingOptionError(Exception):
    def __init__(self, option_id: str, valid_ids: list[str]):
        self.option_id = option_id
        self.valid_ids = valid_ids
        super().__init__(f"Unknown manufacturing option {option_id!r}. Valid options: {', '.join(valid_ids)}.")


def _load_build_plan(project_dir: Path) -> dict[str, Any]:
    build_plan_path = Path(project_dir) / "build_plan.json"
    if not build_plan_path.is_file():
        raise BuildPlanNotFoundError(f"No build_plan.json found at {build_plan_path}. Run `factory plan` first.")
    return project_store.load_json(build_plan_path)


def list_manufacturing_options(project_dir: Path) -> dict[str, Any]:
    """Return build_plan.json's manufacturing_options, annotated for display."""
    build_plan = _load_build_plan(project_dir)
    manufacturing_options = build_plan.get("manufacturing_options", {})
    return {
        "options": manufacturing_options.get("options", []),
        "recommended_option": manufacturing_options.get("recommended_option"),
        "recommendation_rationale": manufacturing_options.get("recommendation_rationale"),
        "selected_manufacturing_option": build_plan.get("selected_manufacturing_option"),
        "requires_human_confirmation": manufacturing_options.get("requires_human_confirmation", True),
        "unanswered_questions": build_plan.get("unanswered_questions", []),
    }


def choose_manufacturing_option(project_dir: Path, option_id: str) -> dict[str, Any]:
    """Record a human's explicit manufacturing-option choice into build_plan.json.

    Only ever sets selected_manufacturing_option (top-level, and mirrored
    inside manufacturing_options) - every other build_plan.json field is
    preserved untouched. Typing a specific option_id is treated as the
    explicit human confirmation this option requires; nothing here silently
    picks or overrides that choice. Never touches CAD/geometry, never
    exports an STL, never invokes OpenSCAD, never contacts a printer or
    slicer, and never sets human_approved or print_ready.
    """
    project_dir = Path(project_dir)
    build_plan_path = project_dir / "build_plan.json"
    build_plan = _load_build_plan(project_dir)

    manufacturing_options = build_plan.get("manufacturing_options", {})
    options = manufacturing_options.get("options", [])
    valid_ids = [o["option_id"] for o in options]
    matching = next((o for o in options if o["option_id"] == option_id), None)
    if matching is None:
        raise UnknownManufacturingOptionError(option_id, valid_ids)

    build_plan["selected_manufacturing_option"] = option_id
    manufacturing_options["selected_manufacturing_option"] = option_id
    build_plan["manufacturing_options"] = manufacturing_options
    project_store.save_json(build_plan_path, build_plan)

    status_advanced = False
    brief_path = project_dir / "brief.json"
    if brief_path.is_file():
        brief = project_store.load_json(brief_path)
        status_advanced = project_store.advance_status(brief, NEW_STATUS_AFTER_SELECTION)
        if status_advanced:
            project_store.save_json(brief_path, brief)

    assembly_intent = apply_selected_option_to_manifest(project_dir, build_plan)

    return {
        "option": matching,
        "status_advanced": status_advanced,
        "available": matching.get("available", True),
        "availability_note": matching.get("availability_note"),
        "assembly_intent": assembly_intent,
    }

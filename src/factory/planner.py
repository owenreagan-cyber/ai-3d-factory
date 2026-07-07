"""Deterministic local planning + manufacturing advisor. No AI call - Phase 0/1/3.

Reads a project_brief.json and produces a build_plan.json next to it,
conforming to schemas/build_plan.schema.json, then seeds part_manifest.json
with planning-time placeholders (see factory.manufacturing.manifest). Every
decision that isn't purely mechanical (tool routing, manufacturing option,
material/color choice) is explained and left for explicit human confirmation
- this module never sets selected_manufacturing_option, never advances a
project past slicer_review_ready, and never contacts a printer or network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import project_store
from factory.manufacturing import decision_engine, knowledge, manifest
from factory.router import recommend_tool

VALIDATION_GATES = (
    "geometry_sanity_check",
    "dimension_fit_check",
    "multipart_alignment_check",
    "preview_render",
    "slicer_review_package",
    "human_approval",
)


def _resolve_target_printer(intended_printer: str) -> dict[str, Any]:
    printer = knowledge.find_printer_by_name(intended_printer)
    if printer is None:
        return {
            "printer_id": None,
            "display_name": intended_printer or None,
            "resolved": False,
            "resolved_from": "brief.intended_printer",
            "capabilities": None,
        }
    return {
        "printer_id": printer.get("printer_id"),
        "display_name": printer.get("display_name"),
        "resolved": True,
        "resolved_from": "brief.intended_printer",
        "capabilities": knowledge.printer_capabilities(printer),
    }


def _recommend_materials(description: str) -> dict[str, Any]:
    text = (description or "").lower()
    materials = knowledge.load_materials()
    matched: list[str] = []
    for material_id, material in materials.items():
        tags = material.get("good_for", [])
        if any(word and word in text for tag in tags for word in tag.split("-")):
            matched.append(material_id)

    if matched:
        return {
            "candidates": matched,
            "rationale": "Matched description keywords against config/manufacturing/materials.json good_for tags.",
        }
    return {
        "candidates": ["pla", "petg"],
        "rationale": (
            "No strong keyword match; defaulting to general-purpose candidates. Confirm the final "
            "material with a human before finalizing."
        ),
    }


def _build_unanswered_questions(
    target_printer: dict[str, Any], manufacturing_options: dict[str, Any], multi_part: bool
) -> list[str]:
    questions: list[str] = []

    if not target_printer["resolved"]:
        questions.append(
            f"Confirm the intended printer: brief.json's intended_printer "
            f"({target_printer['display_name']!r}) did not match a known printer in "
            "config/manufacturing/printers.json. Update brief.json or add this printer to the "
            "manufacturing knowledge base."
        )

    recommended = manufacturing_options["recommended_option"]
    questions.append(
        f"Review the manufacturing options below and set build_plan.json's "
        f"selected_manufacturing_option (currently only a non-binding recommendation: {recommended!r})."
    )
    questions.append(
        "Confirm final material(s) and color(s) for each part; part_manifest.json currently has "
        "TBD placeholders (intended_material/intended_color)."
    )
    if recommended != "single_piece":
        questions.append(
            "If proceeding with a multi-part manufacturing option, update required_parts (and "
            "re-run `factory plan`) to reflect the actual part breakdown before generating CAD."
        )
    if not multi_part:
        questions.append(
            "required_parts currently lists a single placeholder part - refine it to describe the "
            "project's real part(s) before generating CAD."
        )

    return questions


def draft_build_plan(brief: dict) -> dict:
    description = brief.get("description", "")
    project_name = brief.get("project_name", "unnamed project")
    intended_printer = brief.get("intended_printer", "")

    tool_recommendation = recommend_tool(description)
    target_printer = _resolve_target_printer(intended_printer)
    manufacturing_options = decision_engine.evaluate_manufacturing_options(
        description, target_printer["capabilities"]
    )
    materials = _recommend_materials(description)

    required_parts = [
        {
            "part_name": f"{project_name} - primary part",
            "role": "primary",
            "notes": "Placeholder part derived from brief. Refine after CAD/asset work begins.",
        }
    ]
    multi_part = len(required_parts) > 1

    return {
        "status": "plan_drafted",
        "tool_routing_recommendation": tool_recommendation,
        "required_parts": required_parts,
        "validation_gates": list(VALIDATION_GATES),
        "human_review_required": True,
        "manufacturing_goal": (description.strip() or "TODO: describe the manufacturing goal for this project."),
        "target_printer": target_printer,
        "assembly": {
            "multi_part": multi_part,
            "shared_origin_required": multi_part,
            "notes": (
                "required_parts currently reflects a single placeholder part; update it (and re-run "
                "`factory plan`) once a multi-part manufacturing_option is confirmed."
            ),
        },
        "materials": materials,
        "colors": [],
        "manufacturing_options": manufacturing_options,
        "selected_manufacturing_option": None,
        "unanswered_questions": _build_unanswered_questions(target_printer, manufacturing_options, multi_part),
    }


def plan_from_brief_path(brief_path: Path) -> Path:
    """Read brief.json at `brief_path`, write build_plan.json next to it, seed
    part_manifest.json's planning-time placeholders, and return the build_plan path.
    """
    brief_path = Path(brief_path)
    if not brief_path.is_file():
        raise FileNotFoundError(f"brief file not found: {brief_path}")

    brief = project_store.load_json(brief_path)
    build_plan = draft_build_plan(brief)

    build_plan_path = brief_path.parent / "build_plan.json"
    project_store.save_json(build_plan_path, build_plan)

    manifest.seed_manifest_from_plan(brief_path.parent, build_plan)

    return build_plan_path

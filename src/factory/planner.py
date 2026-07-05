"""Deterministic local planning stub. No AI call — this is Phase 0/1.

Reads a project_brief.json and produces a build_plan.json next to it,
conforming to schemas/build_plan.schema.json.
"""

from __future__ import annotations

from pathlib import Path

from factory import project_store
from factory.router import recommend_tool

VALIDATION_GATES = (
    "geometry_sanity_check",
    "dimension_fit_check",
    "multipart_alignment_check",
    "preview_render",
    "slicer_review_package",
    "human_approval",
)


def draft_build_plan(brief: dict) -> dict:
    description = brief.get("description", "")
    project_name = brief.get("project_name", "unnamed project")

    tool_recommendation = recommend_tool(description)

    required_parts = [
        {
            "part_name": f"{project_name} - primary part",
            "role": "primary",
            "notes": "Placeholder part derived from brief. Refine after CAD/asset work begins.",
        }
    ]

    return {
        "status": "plan_drafted",
        "tool_routing_recommendation": tool_recommendation,
        "required_parts": required_parts,
        "validation_gates": list(VALIDATION_GATES),
        "human_review_required": True,
    }


def plan_from_brief_path(brief_path: Path) -> Path:
    """Read brief.json at `brief_path`, write build_plan.json next to it, return that path."""
    brief_path = Path(brief_path)
    if not brief_path.is_file():
        raise FileNotFoundError(f"brief file not found: {brief_path}")

    brief = project_store.load_json(brief_path)
    build_plan = draft_build_plan(brief)

    build_plan_path = brief_path.parent / "build_plan.json"
    project_store.save_json(build_plan_path, build_plan)
    return build_plan_path

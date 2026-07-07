"""Deterministic CAD backend routing.

Explains which CAD backend(s) are recommended for a project's description,
without generating anything. Reuses `factory.router.recommend_tool()` - the
existing single source of truth for OpenSCAD/CadQuery/Blender/Meshy keyword
categories - instead of duplicating keyword lists here, so the two stay
consistent as backends are added. Read-only: never writes a file, never
contacts a network/printer/slicer. See docs/cad-backends.md.
"""

from __future__ import annotations

from typing import Any

from factory.cad.backend import get_backend_registry
from factory.router import _BLENDER_KEYWORDS, _MESHY_KEYWORDS, recommend_tool


def _matches(text: str, keywords: tuple[str, ...]) -> bool:
    return any(kw in text for kw in keywords)


def route_cad(description: str, selected_manufacturing_option: str | None = None) -> dict[str, Any]:
    """Recommend CAD backend(s) for `description` and flag any future-only needs.

    Returns:
        {
          "primary_recommendation": "openscad"|"cadquery"|"blender"|"meshy"|"unspecified",
          "rationale": str,
          "recommended_backends": [backend_id, ...],   # implementable now
          "future_only_needs": [{"backend_id", "display_name", "reason"}, ...],
          "cadquery_available": bool,
          "selected_manufacturing_option": str | None,
          "notes": [...],
        }
    """
    text = (description or "").lower()
    tool_recommendation = recommend_tool(description)
    primary = tool_recommendation["primary_tool"]
    registry = get_backend_registry()

    recommended_backends: list[str] = []
    if primary in ("openscad", "cadquery"):
        recommended_backends.append(primary)

    future_only_needs: list[dict[str, str]] = []
    if primary == "blender" or _matches(text, _BLENDER_KEYWORDS):
        blender = registry["blender"]
        future_only_needs.append(
            {
                "backend_id": "blender",
                "display_name": blender.display_name,
                "reason": (
                    "Description suggests mesh repair, boolean ops, or organic cleanup - "
                    "not implemented as a generation backend yet."
                ),
            }
        )
    if primary == "meshy" or _matches(text, _MESHY_KEYWORDS):
        meshy = registry["meshy"]
        future_only_needs.append(
            {
                "backend_id": "meshy",
                "display_name": meshy.display_name,
                "reason": (
                    "Description suggests organic/generative concept work - reserved for future, "
                    "explicit-approval-and-cost-gated use only; never called automatically."
                ),
            }
        )

    if not recommended_backends:
        # No implementable backend matched strongly (primary is "unspecified", or
        # is a future-only backend with no locally-available substitute) - default
        # to OpenSCAD as the conservative, always-available starting point, same
        # default recommend_tool() itself falls back to.
        recommended_backends.append("openscad")

    return {
        "primary_recommendation": primary,
        "rationale": tool_recommendation["rationale"],
        "recommended_backends": recommended_backends,
        "future_only_needs": future_only_needs,
        "cadquery_available": registry["cadquery"].status == "available",
        "selected_manufacturing_option": selected_manufacturing_option,
        "notes": [
            "This is a deterministic, local, keyword-based recommendation - no AI/LLM call.",
            "This never generates CAD source, writes a file, or contacts a network/printer/slicer.",
        ],
    }

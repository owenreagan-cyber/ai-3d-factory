"""Deterministic, local keyword-based tool routing recommendation.

No AI/LLM call. See docs/tool-routing.md for the human-readable policy this
mirrors.
"""

from __future__ import annotations

_OPENSCAD_KEYWORDS = (
    "plate",
    "sign",
    "text",
    "label",
    "profile",
    "organizer",
    "frame",
    "tile",
    "raised letter",
    "letters",
    "nameplate",
)

_CADQUERY_KEYWORDS = (
    "fillet",
    "chamfer",
    "mechanical",
    "engineering",
    "tolerance fit",
    "gear",
    "bearing",
    "thread",
    "bracket",
    "adapter",
    "mount",
    "clip",
    "hinge",
    "fixture",
    "enclosure",
)

_BLENDER_KEYWORDS = (
    "repair",
    "boolean",
    "organic",
    "sculpt",
    "cleanup",
    "imported mesh",
)

_MESHY_KEYWORDS = (
    "concept art",
    "generative",
    "meshy",
)


def recommend_tool(description: str) -> dict:
    """Recommend a primary CAD/mesh tool from a free-text description.

    Returns {"primary_tool": ..., "rationale": ...}. Meshy is only ever
    recommended with an explicit note that human approval is required
    before it can be used; this function never calls Meshy.
    """
    text = (description or "").lower()

    if any(kw in text for kw in _MESHY_KEYWORDS):
        return {
            "primary_tool": "meshy",
            "rationale": (
                "Description suggests organic/generative concept work. Meshy requires "
                "explicit human approval before use (see docs/tool-routing.md) and is "
                "never called automatically."
            ),
        }

    if any(kw in text for kw in _CADQUERY_KEYWORDS):
        return {
            "primary_tool": "cadquery",
            "rationale": (
                "Description suggests a mechanical/dimensioned solid (bracket, adapter, mount, clip, "
                "hinge, fixture, enclosure, fillets/chamfers, exact fits)."
            ),
        }

    if any(kw in text for kw in _BLENDER_KEYWORDS):
        return {
            "primary_tool": "blender",
            "rationale": "Description suggests mesh repair, boolean ops, or organic cleanup work.",
        }

    if any(kw in text for kw in _OPENSCAD_KEYWORDS):
        return {
            "primary_tool": "openscad",
            "rationale": "Description matches a parametric plate/sign/label/organizer-style part.",
        }

    return {
        "primary_tool": "unspecified",
        "rationale": (
            "No strong keyword match. Default to OpenSCAD for measured parts unless the "
            "geometry turns out to be organic; see docs/tool-routing.md."
        ),
    }

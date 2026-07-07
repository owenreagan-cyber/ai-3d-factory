"""Deterministic, local manufacturing decision engine.

No AI/LLM call: reads config/manufacturing/planning_rules.json and applies a
keyword heuristic, mirroring factory/router.py's existing tool-routing
pattern. Every manufacturing option is always explained (advantages and
disadvantages); the engine recommends exactly one but never selects it.
`selected_manufacturing_option` is always returned as None - only a human,
editing build_plan.json directly, sets that field. See
docs/manufacturing-knowledge-base.md.
"""

from __future__ import annotations

from typing import Any

from factory.manufacturing import knowledge

_OPTION_ORDER = (
    "single_piece",
    "multipart_build_volume",
    "multipart_color",
    "multipart_detail",
    "multipart_paint",
    "multipart_strength",
    "replaceable_components",
)


def _matches(text: str, keywords: list[str]) -> bool:
    return any(kw in text for kw in keywords)


def evaluate_manufacturing_options(
    description: str, printer_capabilities: dict[str, Any] | None
) -> dict[str, Any]:
    """Explain every known manufacturing option and non-bindingly recommend one.

    Returns:
        {
          "options": [{option_id, display_name, description, advantages,
                       disadvantages, available, availability_note}, ...],
          "recommended_option": str,
          "recommendation_rationale": str,
          "selected_manufacturing_option": None,
          "requires_human_confirmation": True,
        }
    """
    text = (description or "").lower()
    rules = knowledge.load_planning_rules()
    catalog = rules.get("manufacturing_options", {})

    multicolor_available = bool(printer_capabilities and printer_capabilities.get("multicolor_supported"))

    options: list[dict[str, Any]] = []
    matched_ids: list[str] = []
    for option_id in _OPTION_ORDER:
        rule = catalog.get(option_id)
        if rule is None:
            continue

        available = True
        availability_note = None
        if option_id == "multipart_color" and not multicolor_available:
            available = False
            availability_note = (
                "Not available for the current target printer: no multicolor-capable printer or AMS is "
                "configured for it. See config/manufacturing/printers.json installed_accessories."
            )

        options.append(
            {
                "option_id": option_id,
                "display_name": rule.get("display_name"),
                "description": rule.get("description"),
                "advantages": list(rule.get("advantages", [])),
                "disadvantages": list(rule.get("disadvantages", [])),
                "available": available,
                "availability_note": availability_note,
            }
        )
        if available and _matches(text, rule.get("prefer_when_keywords", [])):
            matched_ids.append(option_id)

    if matched_ids:
        recommended_option = matched_ids[0]
        rationale = (
            f"Description matched keywords associated with '{recommended_option}'. This is a non-binding "
            "suggestion from a deterministic, local keyword heuristic - review every option's advantages "
            "and disadvantages yourself before deciding."
        )
    else:
        recommended_option = "single_piece"
        rationale = (
            "No strong keyword match; defaulting to the simplest option (single-piece print). This is a "
            "non-binding suggestion - review every option's advantages and disadvantages before deciding."
        )

    return {
        "options": options,
        "recommended_option": recommended_option,
        "recommendation_rationale": rationale,
        "selected_manufacturing_option": None,
        "requires_human_confirmation": True,
    }

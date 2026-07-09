"""Phase 33: local, fully deterministic Design Orchestrator.

The first "decision brain" in this repo's pipeline:

    User Idea -> Project Intake -> Draft Brief -> Brief Merge ->
    Design Intent -> Reference Board -> Project Readiness ->
    Design Orchestrator -> CAD Engine -> Preview -> Review

It does **not generate CAD**. It evaluates whether a project is
sufficiently defined to proceed, and - if so - recommends the most
appropriate downstream design engine (OpenSCAD, CadQuery, Blender, Meshy,
FreeCAD, a hybrid workflow, manual design, or "not enough information to
say"). Nothing downstream is ever invoked automatically; this module only
ever produces a recommendation for a human to act on.

**This module never re-parses free-form text and never duplicates
extraction logic.** Every function here takes already-computed summaries
as input - `intake_summary` (Phase 30), `draft_brief_summary` (Phase 31),
`brief_update_summary` (Phase 32), `design_intent_summary`/`design_intent_detail`
(Phase 26/27), and `reference_board_summary` (Phase 28) - and only reads
their already-parsed fields (confidence levels, counts, structured values).
Where a text-based recommendation is still useful (no structured category
signal at all), it reuses `factory.router.recommend_tool()` - the existing,
single source of truth for OpenSCAD/CadQuery/Blender/Meshy keyword
categories (`docs/tool-routing.md`) - rather than inventing a second,
divergent keyword table.

No AI, no LLM, no network. No CAD generation, no OpenSCAD/CadQuery/Blender/
Meshy/FreeCAD execution of any kind - every "recommended engine" is a
string a human reads and acts on themselves. See
`docs/design-orchestrator.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import project_store
from factory.brief_generator import load_existing_brief, summarize_brief_update, summarize_draft_brief
from factory.design_intent_check import describe_design_intent_for_board, summarize_design_intent
from factory.project_intake import analyze as analyze_intake
from factory.reference_board import summarize_reference_board
from factory.router import recommend_tool

READINESS_STATES = (
    "Not Ready",
    "Needs Information",
    "Ready For Mechanical CAD",
    "Ready For Organic Modeling",
    "Ready For Mixed Workflow",
    "Ready For Manufacturing Review",
    "Blocked",
)

RECOMMENDED_ENGINES = (
    "OpenSCAD",
    "Blender",
    "Meshy (Concept Only)",
    "CadQuery",
    "FreeCAD",
    "Hybrid Workflow",
    "Manual Design",
    "Unknown",
)

# Deterministic category weights for the overall readiness score - each
# category's own percent (0-100) is multiplied by its weight and summed.
# Documented here as the single source of truth; see docs/design-orchestrator.md
# "Readiness scoring" for the reasoning behind each weight. Sums to 1.0.
CATEGORY_WEIGHTS: dict[str, float] = {
    "intake": 0.20,
    "brief": 0.20,
    "design_intent": 0.25,
    "reference_board": 0.15,
    "manufacturing": 0.20,
}

# Total number of fields merge_draft_brief() can ever touch (see
# factory.brief_generator._MERGE_FIELDS) - the denominator for "Brief %".
_TOTAL_MERGE_FIELDS = 8

_CONFIDENT = ("high", "medium")

# Category -> which family of engine it leans toward, purely from Phase 30's
# closed category vocabulary (factory.project_intake.CATEGORIES) - no new
# keyword table, just an engine-affinity mapping on top of an existing one.
# Chosen to agree with factory.router's own OpenSCAD/CadQuery keyword
# tables: "organizer"/"sign"/"storage"/"educational" already appear in
# _OPENSCAD_KEYWORDS (plate/sign/label/organizer/nameplate); "fixture"/
# "replacement part"/"accessory"/"mechanical" already appear in
# _CADQUERY_KEYWORDS (bracket/mount/clip/hinge/fixture/adapter/mechanical).
_OPENSCAD_CATEGORIES = ("sign", "organizer", "storage", "educational")
_CADQUERY_CATEGORIES = ("fixture", "replacement part", "accessory", "mechanical")
_ORGANIC_CATEGORIES = ("toy", "décor")

# visual_goals/style_direction keywords (Phase 30's own closed vocabulary -
# factory.project_intake._VISUAL_GOAL_KEYWORDS) split into which family of
# engine they lean toward, for projects whose category alone doesn't say.
_ORGANIC_VISUAL_KEYWORDS = frozenset({"anime", "cute", "ornate", "decorative", "rustic"})
_MECHANICAL_VISUAL_KEYWORDS = frozenset({
    "minimalist", "modern", "elegant", "sleek", "colorful", "colourful",
    "engraved", "embossed", "raised", "glossy", "matte", "industrial",
    "geometric", "lettering", "typography",
})

_HIGH_QUALITY_BAR = ("premium", "etsy-worthy", "gift", "presentation")


def _pct(count: int, total: int) -> int:
    return round(100 * count / total) if total else 0


def _as_dict(value: Any) -> dict[str, Any]:
    """Defensive coercion used throughout this module's scoring functions -
    every input here is *supposed* to already be a dict (or `None`), since
    it's an already-computed summary from an earlier phase, but nothing in
    this module ever trusts that blindly (e.g. a hand-crafted or malformed
    `intake_summary` JSON passed via `factory intake suggest-brief`'s
    `.json`-file input path). A non-dict value (an int, a list, a string,
    ...) degrades to an empty dict rather than raising."""
    return value if isinstance(value, dict) else {}


def _score_intake(draft_brief_summary: dict[str, Any] | None) -> int:
    """Reuses Phase 31's own `readiness.percent_populated` directly -
    computed once by `factory.brief_generator.compute_readiness()`, never
    re-derived here."""
    readiness = _as_dict(_as_dict(draft_brief_summary).get("readiness"))
    percent = readiness.get("percent_populated")
    return int(percent) if isinstance(percent, (int, float)) else 0


def _score_brief(brief_update_summary: dict[str, Any] | None) -> int:
    """How much of the existing brief.json's mergeable fields already hold
    real content - `fields_preserved_count` out of the 8 fields
    `factory.brief_generator.merge_draft_brief()` can ever touch."""
    preserved = _as_dict(brief_update_summary).get("fields_preserved_count", 0)
    return _pct(preserved, _TOTAL_MERGE_FIELDS) if isinstance(preserved, (int, float)) else 0


def _score_design_intent(design_intent_detail: dict[str, Any] | None) -> int:
    """Four sub-checks on the already-computed `design_intent_detail`
    (Phase 27): quality_standard set, use_case set, style_direction
    non-empty, and the manufacturability check landing on a definite
    "fits some configured printer" result."""
    design_intent_detail = _as_dict(design_intent_detail)
    if not design_intent_detail:
        return 0
    checks = (
        bool(design_intent_detail.get("quality_standard")),
        bool(design_intent_detail.get("use_case")),
        bool(design_intent_detail.get("style_direction")),
        design_intent_detail.get("manufacturability_result") == "fits_some_printers",
    )
    return _pct(sum(checks), len(checks))


def _score_reference_board(reference_board_summary: dict[str, Any] | None) -> int:
    """Three sub-checks on the already-computed `reference_board_summary`
    (Phase 28): has at least one reference, every reference is attached to
    `design_intent.reference_inputs`, and no license/URL advisory warnings
    were raised."""
    summary = _as_dict(reference_board_summary)
    count = summary.get("reference_count", 0)
    if not isinstance(count, (int, float)) or not count:
        return 0
    attached = summary.get("attached_to_design_intent_count", 0)
    checks = (
        True,  # has_references, already guaranteed by the count check above
        attached == count,
        not summary.get("warnings"),
    )
    return _pct(sum(checks), len(checks))


def _score_manufacturing(intake_summary: dict[str, Any] | None) -> int:
    """Four sub-checks directly on `intake_summary`'s own confidence
    fields (Phase 30) - printer/material/manufacturing-style/dimensional-
    constraints assumptions each already carry a confidence level; this
    only reads it, never re-derives it from text."""
    intake_summary = _as_dict(intake_summary)
    fields = ("printer_assumptions", "material_assumptions", "manufacturing_style", "dimensional_constraints")
    checks = [_as_dict(intake_summary.get(f)).get("confidence") in _CONFIDENT for f in fields]
    return _pct(sum(checks), len(checks))


def compute_readiness_score(
    intake_summary: dict[str, Any] | None,
    draft_brief_summary: dict[str, Any] | None,
    brief_update_summary: dict[str, Any] | None,
    design_intent_detail: dict[str, Any] | None,
    reference_board_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """Deterministic, weighted readiness score (0-100) plus a per-category
    breakdown - see `CATEGORY_WEIGHTS` above and `docs/design-orchestrator.md`
    "Readiness scoring" for exactly how each category percent is derived
    and why each weight was chosen. Never re-parses anything - every
    category score is read straight off an already-computed summary.
    """
    categories = {
        "intake": _score_intake(draft_brief_summary),
        "brief": _score_brief(brief_update_summary),
        "design_intent": _score_design_intent(design_intent_detail),
        "reference_board": _score_reference_board(reference_board_summary),
        "manufacturing": _score_manufacturing(intake_summary),
    }
    overall = round(sum(categories[name] * weight for name, weight in CATEGORY_WEIGHTS.items()))
    return {"overall": overall, "categories": categories}


def _visual_keywords(design_intent_detail: dict[str, Any] | None, intake_summary: dict[str, Any] | None) -> set[str]:
    keywords: set[str] = set()
    design_intent_detail = _as_dict(design_intent_detail)
    intake_summary = _as_dict(intake_summary)
    style_direction = design_intent_detail.get("style_direction")
    if isinstance(style_direction, list):
        keywords.update(str(k).lower() for k in style_direction)
    visual_goals = _as_dict(intake_summary.get("visual_goals")).get("value") or []
    if isinstance(visual_goals, list):
        keywords.update(str(k).lower() for k in visual_goals)
    return keywords


def _quality_target(design_intent_detail: dict[str, Any] | None, intake_summary: dict[str, Any] | None) -> str | None:
    design_intent_detail = _as_dict(design_intent_detail)
    intake_summary = _as_dict(intake_summary)
    if design_intent_detail.get("quality_standard"):
        return str(design_intent_detail["quality_standard"]).lower()
    value = _as_dict(intake_summary.get("quality_target")).get("value")
    if value and value != "unknown":
        return str(value).lower()
    return None


def _best_available_text(intake_summary: dict[str, Any] | None, design_intent_detail: dict[str, Any] | None) -> str:
    design_intent_detail = _as_dict(design_intent_detail)
    intake_summary = _as_dict(intake_summary)
    if design_intent_detail.get("use_case"):
        return str(design_intent_detail["use_case"])
    purpose = _as_dict(intake_summary.get("purpose")).get("value")
    if purpose:
        return str(purpose)
    return ""


def _category_leaning(category: str | None) -> str | None:
    if category in _OPENSCAD_CATEGORIES:
        return "openscad"
    if category in _CADQUERY_CATEGORIES:
        return "cadquery"
    if category in _ORGANIC_CATEGORIES:
        return "organic"
    return None


def compute_design_signals(
    intake_summary: dict[str, Any] | None, design_intent_detail: dict[str, Any] | None
) -> dict[str, Any]:
    """Shared organic/mechanical signal detection - computed once, used by
    both `determine_readiness_state()` and `recommend_engine()`, so the two
    can never disagree about the same underlying signal.

    Category (Phase 30's closed vocabulary) is the strongest signal and
    counts as a weight-2 vote for its family; each `style_direction`/
    `visual_goals` keyword hit is a weight-1 vote. This weighting matters:
    a single incidental style word - e.g. "anime-inspired **lettering**" on
    an otherwise clearly mechanical sign (`category == "sign"`, plus its
    own "raised"/"lettering" keywords, both mechanical-leaning) - must not
    alone be enough to call the whole project a mixed/hybrid design.
    `is_mixed` only fires when *both* sides have at least weight-2 worth of
    signal - a real, comparable mechanical-and-organic split, not one
    confident category vote against one stray keyword.
    """
    category = _as_dict(_as_dict(intake_summary).get("category")).get("value")
    leaning = _category_leaning(category)
    visual_keywords = _visual_keywords(design_intent_detail, intake_summary)
    organic_hits = visual_keywords & _ORGANIC_VISUAL_KEYWORDS
    mechanical_hits = visual_keywords & _MECHANICAL_VISUAL_KEYWORDS

    organic_strength = (2 if leaning == "organic" else 0) + len(organic_hits)
    mechanical_strength = (2 if leaning in ("openscad", "cadquery") else 0) + len(mechanical_hits)

    has_organic_signal = organic_strength > 0
    has_mechanical_signal = mechanical_strength > 0
    is_mixed = has_organic_signal and has_mechanical_signal and min(organic_strength, mechanical_strength) >= 2

    return {
        "has_organic_signal": has_organic_signal,
        "has_mechanical_signal": has_mechanical_signal,
        "is_mixed": is_mixed,
        "organic_strength": organic_strength,
        "mechanical_strength": mechanical_strength,
    }


def recommend_engine(
    intake_summary: dict[str, Any] | None,
    design_intent_detail: dict[str, Any] | None,
    *,
    blocked: bool,
    low_confidence: bool,
    signals: dict[str, Any],
) -> dict[str, Any]:
    """Deterministic engine recommendation - category first (Phase 30's
    closed `category` vocabulary, the strongest available structured
    signal), refined by organic/mechanical-leaning visual keywords
    (`style_direction`/`visual_goals`, via `compute_design_signals()`), and
    only falling back to `factory.router.recommend_tool()`'s free-text
    keyword matching when neither gives a usable signal. `signals` is
    `compute_design_signals()`'s own return value - reused directly, never
    recomputed, so this function and `determine_readiness_state()` can
    never disagree about the same underlying evidence. Returns
    `{"engine": ..., "rationale": ...}` - `engine` is always one of
    `RECOMMENDED_ENGINES`.
    """
    if blocked:
        return {
            "engine": "Manual Design",
            "rationale": (
                "The declared design intent doesn't fit any locally configured printer - a human needs "
                "to resize or split the design before any engine (automated or manual) can proceed."
            ),
        }

    category = _as_dict(_as_dict(intake_summary).get("category")).get("value")
    category_leaning = _category_leaning(category)
    has_organic_signal = signals["has_organic_signal"]
    has_mechanical_signal = signals["has_mechanical_signal"]

    if signals["is_mixed"]:
        return {
            "engine": "Hybrid Workflow",
            "rationale": (
                "Both mechanical/geometric signals (category or style keywords) and organic/sculptural "
                "signals are present with comparable strength - this looks like a mixed design (e.g. a "
                "mechanical part with a decorative organic section), best split across more than one "
                "engine."
            ),
        }

    if has_organic_signal and signals["organic_strength"] >= signals["mechanical_strength"]:
        if low_confidence:
            return {
                "engine": "Meshy (Concept Only)",
                "rationale": (
                    "Organic/sculptural signal detected, but the project is still too conceptual for "
                    "local Blender modeling to be worthwhile yet - Meshy remains gated behind explicit "
                    "human approval and cost review (see docs/meshy-approval-gate.md) and is never "
                    "called automatically."
                ),
            }
        return {
            "engine": "Blender",
            "rationale": "Organic/sculptural signal detected (category and/or style keywords) with enough definition to model locally.",
        }

    if has_mechanical_signal:
        if category_leaning == "cadquery":
            return {
                "engine": "CadQuery",
                "rationale": f"Category {category!r} (and/or mechanical style signals) matches CadQuery's precision-fit/bracket/mount/mechanism strengths.",
            }
        if category_leaning == "openscad":
            return {
                "engine": "OpenSCAD",
                "rationale": f"Category {category!r} matches OpenSCAD's parametric plate/sign/organizer strengths.",
            }
        # Mechanical-leaning purely from style keywords, no category match -
        # fall back to the shared text router for a second opinion.
        text = _best_available_text(intake_summary, design_intent_detail)
        tool = recommend_tool(text)["primary_tool"]
        engine = {"openscad": "OpenSCAD", "cadquery": "CadQuery", "blender": "Blender", "meshy": "Meshy (Concept Only)"}.get(
            tool, "OpenSCAD"
        )
        return {
            "engine": engine,
            "rationale": "Mechanical style signal detected without a matching category - deferred to factory.router.recommend_tool() on the best available description text.",
        }

    # No structured category or style signal at all - last resort, the
    # shared free-text router (reused, not duplicated).
    text = _best_available_text(intake_summary, design_intent_detail)
    if text:
        tool_result = recommend_tool(text)
        tool = tool_result["primary_tool"]
        if tool != "unspecified":
            engine = {"openscad": "OpenSCAD", "cadquery": "CadQuery", "blender": "Blender", "meshy": "Meshy (Concept Only)"}[tool]
            return {"engine": engine, "rationale": tool_result["rationale"]}

    return {
        "engine": "Unknown",
        "rationale": "No category, style, or descriptive text signal available yet to recommend an engine.",
    }


def determine_readiness_state(
    score: dict[str, Any],
    *,
    blocked: bool,
    signals: dict[str, Any],
    design_intent_detail: dict[str, Any] | None,
    reference_board_summary: dict[str, Any] | None,
) -> str:
    """Deterministic readiness-state decision tree - see
    `docs/design-orchestrator.md` "Readiness states" for the full
    reasoning. Checked in this exact priority order: a hard manufacturing
    block always wins; then the overall score gates "Not Ready"/"Needs
    Information"; then a genuinely mixed organic+mechanical signal
    (`signals["is_mixed"]`, comparable strength on both sides - not just
    one stray keyword against a confident category) always reads as
    "Ready For Mixed Workflow" (checked before either pure state); then a
    near-complete project (score >= 90, design intent and reference board
    both substantially populated) graduates to "Ready For Manufacturing
    Review"; then the two single-family "Ready For..." states, picked by
    whichever signal is stronger; a project passing the score gate with no
    organic/mechanical signal at all falls back to "Needs Information".
    `signals` is `compute_design_signals()`'s own return value - reused
    directly, never recomputed, so this function and `recommend_engine()`
    can never disagree about the same underlying evidence.
    """
    if blocked:
        return "Blocked"

    overall = score["overall"]
    if overall < 25:
        return "Not Ready"
    if overall < 60:
        return "Needs Information"

    if signals["is_mixed"]:
        return "Ready For Mixed Workflow"

    design_intent_ok = score["categories"]["design_intent"] >= 75
    reference_board_ok = score["categories"]["reference_board"] >= 60
    if overall >= 90 and design_intent_ok and reference_board_ok:
        return "Ready For Manufacturing Review"

    if signals["has_organic_signal"] and signals["organic_strength"] >= signals["mechanical_strength"]:
        return "Ready For Organic Modeling"
    if signals["has_mechanical_signal"]:
        return "Ready For Mechanical CAD"

    return "Needs Information"


def generate_readiness_advisories(
    intake_summary: dict[str, Any] | None,
    design_intent_detail: dict[str, Any] | None,
    reference_board_summary: dict[str, Any] | None,
    score: dict[str, Any],
) -> list[str]:
    """Consolidated, orchestrator-level advisory list - deterministic
    conditions checked directly against already-computed fields (never
    re-parsed text). `"Human approval required"` is always the last entry,
    unconditionally - the same standing reminder every phase in this
    pipeline carries."""
    intake_summary = _as_dict(intake_summary)
    score = _as_dict(score)
    categories = _as_dict(score.get("categories"))
    advisories: list[str] = []

    def _confidence(field: str) -> str:
        return _as_dict(intake_summary.get(field)).get("confidence", "unknown")

    if _confidence("dimensional_constraints") not in _CONFIDENT:
        advisories.append("Dimensions missing")
    if _confidence("material_assumptions") not in _CONFIDENT:
        advisories.append("Material unspecified")
    if _confidence("printer_assumptions") not in _CONFIDENT:
        advisories.append("Printer unspecified")

    quality_target = _quality_target(design_intent_detail, intake_summary)
    reference_count = _as_dict(reference_board_summary).get("reference_count", 0)
    if quality_target in _HIGH_QUALITY_BAR and not reference_count:
        advisories.append("Reference images recommended")

    if categories.get("design_intent", 0) < 100:
        advisories.append("Design intent incomplete")

    commercial_intent = _as_dict(intake_summary.get("commercial_intent"))
    if commercial_intent.get("value") and commercial_intent.get("confidence") in _CONFIDENT:
        advisories.append("Commercial review recommended")

    if categories.get("manufacturing", 0) < 100:
        advisories.append("Manufacturing review required")

    advisories.append("Human approval required")
    return advisories


def evaluate_project_readiness(
    intake_summary: dict[str, Any] | None,
    draft_brief_summary: dict[str, Any] | None,
    brief_update_summary: dict[str, Any] | None,
    design_intent_summary: dict[str, Any] | None,
    design_intent_detail: dict[str, Any] | None,
    reference_board_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    """The core, pure Design Orchestrator function - takes exactly the six
    already-computed summaries `factory.project_inspection.summarize_project()`
    produces (Phase 26-32) and returns a full readiness evaluation:

    ```
    {
      "readiness_state": one of READINESS_STATES,
      "recommended_engine": one of RECOMMENDED_ENGINES,
      "engine_rationale": str,
      "score": {"overall": int, "categories": {...}},
      "advisories": [str, ...],
    }
    ```

    Never re-parses free text, never writes anything, never contacts a
    network/printer/slicer, never invokes any CAD engine, and never sets
    `human_approved`/`print_ready`. Deterministic: the same six inputs
    always produce the exact same output.
    """
    score = compute_readiness_score(
        intake_summary, draft_brief_summary, brief_update_summary, design_intent_detail, reference_board_summary
    )

    blocked = _as_dict(design_intent_detail).get("manufacturability_result") == "fits_no_known_printers"

    signals = compute_design_signals(intake_summary, design_intent_detail)

    readiness_state = determine_readiness_state(
        score,
        blocked=blocked,
        signals=signals,
        design_intent_detail=design_intent_detail,
        reference_board_summary=reference_board_summary,
    )

    low_confidence = score["overall"] < 60
    engine_result = recommend_engine(
        intake_summary,
        design_intent_detail,
        blocked=blocked,
        low_confidence=low_confidence,
        signals=signals,
    )

    advisories = generate_readiness_advisories(intake_summary, design_intent_detail, reference_board_summary, score)

    return {
        "readiness_state": readiness_state,
        "recommended_engine": engine_result["engine"],
        "engine_rationale": engine_result["rationale"],
        "score": score,
        "advisories": advisories,
    }


def evaluate_readiness_for_path(path: Path) -> dict[str, Any]:
    """Convenience entry point for `factory readiness <path>` when `path`
    is a single project directory or a plain-text/Markdown idea file (not
    a directory of multiple projects - see `factory.preview_board.discover_projects()`
    for that case, used directly by the CLI).

    Computes the same six summaries `factory.project_inspection.summarize_project()`
    would, using the exact same leaf functions it calls (never re-implementing
    their parsing), then evaluates readiness. For a bare text/Markdown file
    (no project directory), `design_intent_summary`/`design_intent_detail`/
    `reference_board_summary` are naturally empty/`None` - there's no
    `brief.json` to read them from yet.
    """
    path = Path(path)

    intake_summary = analyze_intake(path)
    draft_brief_summary = summarize_draft_brief(intake_summary)

    existing_brief: dict[str, Any] | None = None
    if path.is_dir():
        try:
            existing_brief = load_existing_brief(path)
        except Exception:  # noqa: BLE001 - a broken existing brief degrades to "no existing brief" here, not an error; factory intake suggest-brief --update is the strict path for that
            existing_brief = None
    brief_update_summary = summarize_brief_update(existing_brief, intake_summary)

    design_intent_summary = None
    design_intent_detail = None
    if path.is_dir():
        brief_path = path / "brief.json"
        full_design_intent = summarize_design_intent(brief_path)
        if full_design_intent is not None:
            design_intent_summary = {
                "quality_standard": full_design_intent["quality_standard"],
                "use_case": full_design_intent["use_case"],
                "manufacturability_result": full_design_intent["manufacturability_check"]["result"],
            }
        design_intent_detail = describe_design_intent_for_board(brief_path)

    reference_board_summary = summarize_reference_board(path)

    return evaluate_project_readiness(
        intake_summary,
        draft_brief_summary,
        brief_update_summary,
        design_intent_summary,
        design_intent_detail,
        reference_board_summary,
    )

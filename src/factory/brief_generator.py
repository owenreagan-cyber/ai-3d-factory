"""Phase 31: local, fully deterministic Intake-to-Brief Draft Generation.

Converts an already-computed `intake_summary` (Phase 30,
`factory.project_intake`) into a human-reviewable **draft** - a proposed
`brief.json`, a proposed `design_intent` block, and a set of manufacturing
notes - never a file write by itself, never an automatic decision.

    User Idea -> Project Intake -> Draft Brief -> Design Intent ->
    Reference Board -> Manufacturing Planning -> CAD Generation ->
    Preview Board -> Review Gate

**This module never re-parses free-form text.** Every function here takes
an already-computed `intake_summary` dict as its sole input - the keyword/
regex heuristics that produced it live entirely in `factory.project_intake`
and are never duplicated or re-run here. This module's only job is
*shaping* that already-extracted data into draft artifacts, confidence-gated
so a low-confidence/absent field is never silently promoted into a
"real" value.

**Confidence gating, not invention.** A field is only populated in the
draft when its `intake_summary` confidence is `"high"` or `"medium"` -
`"low"`/`"unknown"` fields degrade to `None` (scalars) or `[]` (lists),
rendered as "unknown"/"not specified" by whatever reads the draft (CLI,
HTML). This module never guesses, never fills a gap with a plausible-
sounding default, and never marks anything `human_approved`/`print_ready`.

**No file is ever written except by an explicit `write_draft_brief()`
call, itself only reachable via `factory intake suggest-brief --write`,
itself refusing to overwrite an existing `brief.json` unless `--force` is
also given.** Every draft is advisory - human review and explicit
`--write` are always required before anything lands on disk. No AI, no
LLM, no network, no CAD generation. See `docs/brief-generator.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import project_store
from factory.project_intake import analyze as analyze_intake

# The fields tracked for "percent populated"/"unknown fields" readiness -
# matches the 13 intake_summary fields that carry independent signal
# (`warnings`/`source` are metadata, not extracted content, so excluded).
_TRACKED_FIELDS = (
    "project_name",
    "category",
    "purpose",
    "audience",
    "environment",
    "printer_assumptions",
    "material_assumptions",
    "quality_target",
    "manufacturing_style",
    "dimensional_constraints",
    "visual_goals",
    "functional_goals",
    "commercial_intent",
)

_CONFIDENT = ("high", "medium")


class ProjectDirectoryNotFoundError(Exception):
    """Raised by `write_draft_brief()` when the given `project_dir` doesn't
    exist - this module never creates a project directory, only (with
    explicit `--write`) a `brief.json` file inside an existing one."""


class BriefAlreadyExistsError(Exception):
    """Raised by `write_draft_brief()` when `<project_dir>/brief.json`
    already exists and `force` wasn't given - this module never silently
    overwrites a human-authored brief."""


class MalformedIntakeSummaryError(Exception):
    """Raised by `load_intake_summary_from_path()` when a `.json` path is
    given but its content doesn't parse as JSON, or doesn't look like an
    `intake_summary` (Phase 30) shape - the one real error condition when
    loading a pre-computed intake summary from disk."""


def _confident_value(field: Any, *, is_list: bool) -> Any:
    """Confidence gate: return `field["value"]` only when its confidence is
    `"high"` or `"medium"`, else `None` (scalar fields) or `[]` (list
    fields). Never invents a value - an absent/low-confidence field stays
    explicitly empty, for the CLI/HTML layer to render as "unknown"/"not
    specified" rather than embedding placeholder strings into typed data.
    """
    if not isinstance(field, dict) or field.get("confidence") not in _CONFIDENT:
        return [] if is_list else None
    value = field.get("value")
    if is_list:
        return list(value) if isinstance(value, list) and value else []
    return value


def compute_readiness(intake: dict[str, Any]) -> dict[str, Any]:
    """Deterministic "how much of this draft is actually populated"
    summary, for the Preview Board's compact "Draft Brief" card and
    `factory intake suggest-brief`'s human-readable header. A field counts
    as populated exactly when its own `intake_summary` confidence is
    `"high"`/`"medium"` - the same gate `generate_draft_brief()` and
    friends use, so this never disagrees with the draft it describes.
    """
    intake = intake or {}
    total = len(_TRACKED_FIELDS)
    populated = sum(
        1 for name in _TRACKED_FIELDS if (intake.get(name) or {}).get("confidence") in _CONFIDENT
    )
    unknown_count = total - populated
    percent_populated = round(100 * populated / total) if total else 0
    return {
        "status": "Ready",
        "percent_populated": percent_populated,
        "populated_count": populated,
        "unknown_count": unknown_count,
        "total_fields": total,
        "human_review_required": True,
    }


def generate_draft_brief(intake: dict[str, Any]) -> dict[str, Any]:
    """Confidence-gated draft of proposed `brief.json`-adjacent fields -
    every value is either taken directly from a `"high"`/`"medium"`
    confidence `intake_summary` field, or left `None`/`[]` ("unknown"/"not
    specified" once rendered). `review_notes` is filled in by
    `generate_draft()` (needs the full advisory list, computed after this
    function runs) - always `[]` when this function is called directly.
    """
    intake = intake or {}
    return {
        "project_name": _confident_value(intake.get("project_name"), is_list=False),
        "category": _confident_value(intake.get("category"), is_list=False),
        "purpose": _confident_value(intake.get("purpose"), is_list=False),
        "audience": _confident_value(intake.get("audience"), is_list=False),
        "environment": _confident_value(intake.get("environment"), is_list=False),
        "printer": _confident_value(intake.get("printer_assumptions"), is_list=True),
        "material": _confident_value(intake.get("material_assumptions"), is_list=True),
        "quality_target": _confident_value(intake.get("quality_target"), is_list=False),
        "manufacturing_style": _confident_value(intake.get("manufacturing_style"), is_list=True),
        "dimensional_constraints": _confident_value(intake.get("dimensional_constraints"), is_list=True),
        "visual_goals": _confident_value(intake.get("visual_goals"), is_list=True),
        "functional_goals": _confident_value(intake.get("functional_goals"), is_list=True),
        "commercial_intent": _confident_value(intake.get("commercial_intent"), is_list=False),
        "review_notes": [],
    }


def generate_draft_design_intent(intake: dict[str, Any]) -> dict[str, Any]:
    """Confidence-gated draft of a proposed `design_intent` block
    (`docs/design-intent-brief.md`'s shape, only the subset this module can
    honestly derive). `reference_inputs` is always `[]` - this phase never
    invents or auto-populates reference inputs; a human adds them via
    `factory reference-board add` (Phase 28/29). `manufacturability_constraints.max_size_mm`
    is deliberately never synthesized from `dimensional_constraints` - a
    raw match like `"48-inch"` names one axis, not a confirmed `[x, y, z]`
    triple, and guessing the other two would be inventing data.
    """
    intake = intake or {}
    return {
        "purpose": _confident_value(intake.get("purpose"), is_list=False),
        "quality_target": _confident_value(intake.get("quality_target"), is_list=False),
        "style": _confident_value(intake.get("visual_goals"), is_list=True),
        "manufacturing_notes": _confident_value(intake.get("manufacturing_style"), is_list=True),
        "reference_inputs": [],
        "warnings": list(intake.get("warnings") or []),
        "design_notes": _confident_value(intake.get("functional_goals"), is_list=True),
        "review_required": True,
        "confidence_summary": {
            name: (intake.get(name) or {}).get("confidence", "unknown") for name in _TRACKED_FIELDS
        },
    }


def generate_manufacturing_notes(intake: dict[str, Any]) -> dict[str, Any]:
    """Confidence-gated draft of manufacturing-relevant fields only
    (printer, material, manufacturing style, dimensional constraints) - a
    focused subset of `generate_draft_brief()`'s output, for a future
    manufacturing-planning consumer that only cares about this slice."""
    intake = intake or {}
    return {
        "printer": _confident_value(intake.get("printer_assumptions"), is_list=True),
        "material": _confident_value(intake.get("material_assumptions"), is_list=True),
        "manufacturing_style": _confident_value(intake.get("manufacturing_style"), is_list=True),
        "dimensional_constraints": _confident_value(intake.get("dimensional_constraints"), is_list=True),
    }


def generate_advisories(draft_brief: dict[str, Any]) -> list[str]:
    """Advisory list for a generated draft - always advisory, never a
    reason to block generation itself (this function never raises).
    `"Human approval required before save."` is always the last entry -
    the human-in-the-loop guarantee that applies to every draft this
    module ever produces, regardless of how complete it is.
    """
    advisories: list[str] = []
    if not draft_brief.get("material"):
        advisories.append("Material not specified.")
    if not draft_brief.get("printer"):
        advisories.append("Printer not specified.")
    if not draft_brief.get("dimensional_constraints"):
        advisories.append("Dimensions incomplete.")
    if draft_brief.get("quality_target") in ("premium", "etsy-worthy", "gift", "presentation"):
        advisories.append("Reference board recommended - see `factory reference-board add`.")
    if draft_brief.get("commercial_intent"):
        advisories.append("Commercial review recommended - see docs/licensing-policy.md.")
    if draft_brief.get("functional_goals"):
        advisories.append("Mechanical review recommended - functional/moving parts detected.")
    advisories.append("Human approval required before save.")
    return advisories


def generate_draft(intake: dict[str, Any]) -> dict[str, Any]:
    """Top-level draft generator - the one function `factory intake
    suggest-brief` calls. Combines `compute_readiness()`,
    `generate_draft_brief()`, `generate_draft_design_intent()`,
    `generate_manufacturing_notes()`, and `generate_advisories()` into one
    result. Deterministic: the same `intake_summary` always produces the
    exact same draft. Never writes anything - see `write_draft_brief()`
    for the one, explicit, opt-in write path.
    """
    intake = intake or {}
    draft_brief = generate_draft_brief(intake)
    advisories = generate_advisories(draft_brief)
    draft_brief["review_notes"] = list(advisories)

    return {
        "readiness": compute_readiness(intake),
        "brief": draft_brief,
        "design_intent": generate_draft_design_intent(intake),
        "manufacturing_notes": generate_manufacturing_notes(intake),
        "advisories": advisories,
    }


def summarize_draft_brief(intake: dict[str, Any]) -> dict[str, Any]:
    """Compact summary for `factory.project_inspection.summarize_project()`'s
    new `draft_brief_summary` field and the preview board's compact "Draft
    Brief" card - just `readiness` and `advisories`, not the full
    brief/design_intent/manufacturing_notes payload (that stays in
    `factory intake suggest-brief`'s output, to keep the board compact).
    """
    draft = generate_draft(intake)
    return {"readiness": draft["readiness"], "advisories": draft["advisories"]}


def load_intake_summary_from_path(path: Path) -> dict[str, Any]:
    """Resolve `factory intake suggest-brief <path>`'s input into an
    `intake_summary` dict: a project directory or a text/Markdown file is
    freshly analyzed via `factory.project_intake.analyze()` (the same
    canonical parser `factory intake analyze` uses - reused, not
    duplicated); a `.json` file is read directly and used as-is, on the
    assumption it's already a Phase 30 `intake_summary` (e.g. saved from a
    prior `factory intake analyze --json` run). Raises
    `MalformedIntakeSummaryError` if a `.json` path isn't valid JSON or
    doesn't look like an `intake_summary` shape - the one real error
    condition here.
    """
    path = Path(path)
    if path.is_file() and path.suffix.lower() == ".json":
        try:
            data = project_store.load_json(path)
        except (OSError, ValueError) as exc:
            raise MalformedIntakeSummaryError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict) or "warnings" not in data or "category" not in data:
            raise MalformedIntakeSummaryError(
                f"{path} does not look like an intake_summary (missing expected fields such as "
                "'category'/'warnings') - pass a project directory, a text/Markdown file, or JSON "
                "produced by `factory intake analyze --json`."
            )
        return data
    return analyze_intake(path)


def _build_design_intent_block(design_intent_draft: dict[str, Any]) -> dict[str, Any] | None:
    """Only the sub-fields with real signal, and only if at least one is
    present - an all-`None`/`[]` design_intent block is omitted entirely
    rather than written as a hollow placeholder (matches `design_intent`'s
    own documented "every field optional, whole block optional"
    philosophy - `docs/design-intent-brief.md`)."""
    block: dict[str, Any] = {}
    if design_intent_draft.get("quality_target"):
        block["quality_standard"] = design_intent_draft["quality_target"]
    if design_intent_draft.get("purpose"):
        block["use_case"] = design_intent_draft["purpose"]
    if design_intent_draft.get("style"):
        block["style_direction"] = list(design_intent_draft["style"])
    return block or None


def build_brief_json(draft: dict[str, Any]) -> dict[str, Any]:
    """Convert a `generate_draft()` result into an actual, schema-valid
    `brief.json` dict (`schemas/project_brief.schema.json`) - the shape
    `write_draft_brief()` writes. Every schema-required field that has no
    confident signal is written as the literal string `"unknown"`
    (`constraints` as `[]`) rather than a guessed system default (e.g.
    `"Owen"`/`"Bambu H2D"`) - honest about what wasn't actually determined,
    for a human to fill in during review. `status` is `"brief_created"`
    (matches `factory.project_store.default_brief()`'s own convention: the
    moment a `brief.json` exists, that's what its status means) and
    `required_human_approval` is always `True` (never anything else,
    anywhere in this repo). `design_intent` is included only when
    `_build_design_intent_block()` finds real signal; `manufacturing_notes`
    is included only when non-empty - both purely additive, informational
    extras `schemas/project_brief.schema.json`'s `additionalProperties:
    true` already allows.
    """
    brief = draft["brief"]

    result: dict[str, Any] = {
        "project_name": brief.get("project_name") or "unknown",
        "status": "brief_created",
        "owner": "unknown",
        "intended_printer": brief["printer"][0] if brief.get("printer") else "unknown",
        "description": brief.get("purpose") or "unknown",
        "constraints": list(brief.get("dimensional_constraints") or []),
        "required_human_approval": True,
    }

    design_intent_block = _build_design_intent_block(draft["design_intent"])
    if design_intent_block:
        result["design_intent"] = design_intent_block

    manufacturing_notes = draft.get("manufacturing_notes") or {}
    if any(manufacturing_notes.values()):
        result["manufacturing_notes"] = manufacturing_notes

    return result


def write_draft_brief(project_dir: Path, draft: dict[str, Any], *, force: bool = False) -> Path:
    """Write `build_brief_json(draft)` to `<project_dir>/brief.json` - the
    **only** file this entire module ever writes, and only when explicitly
    called (via `factory intake suggest-brief --write`, never
    automatically).

    Raises `ProjectDirectoryNotFoundError` if `project_dir` doesn't exist -
    this never creates the project directory itself. Raises
    `BriefAlreadyExistsError` if `<project_dir>/brief.json` already exists
    and `force` is `False` - this never silently overwrites a
    human-authored brief; pass `force=True` (only via an explicit
    `--force` CLI flag) to intentionally replace it.
    """
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        raise ProjectDirectoryNotFoundError(
            f"{project_dir} is not a directory - check the path, or run `factory init-project` first."
        )

    brief_path = project_dir / "brief.json"
    if brief_path.is_file() and not force:
        raise BriefAlreadyExistsError(
            f"{brief_path} already exists. Use --force to replace."
        )

    project_store.save_json(brief_path, build_brief_json(draft))
    return brief_path

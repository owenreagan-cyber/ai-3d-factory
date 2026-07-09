"""Phase 28: local, read-only Reference Board planning model.

A **Reference Board** is a project's optional, local record of where its
design intent came from - inspiration photos, existing STL/STEP files,
sketches, a MakerWorld/Thingiverse page, a Reddit/Pinterest/DeviantArt post,
a classroom or product photo, a remixable source file, and so on. This
module reads that record (`<project_dir>/reference_board.json`, if present)
and produces a read-only, advisory summary - it never fetches, downloads,
scrapes, searches, or otherwise contacts any `source_url` a reference
records. A URL here is inert metadata, exactly like `design_intent`'s
`reference_inputs[].description` (`docs/design-intent-brief.md`) - never a
target this module (or anything downstream of it) opens.

This is planning/data-model scaffolding for a future Source Discovery
feature, not that feature itself: no web crawling, no scraping, no search,
no downloading, and no API integration exists anywhere in this module. See
`docs/reference-board.md`.

Local filesystem only: reads at most one JSON file per project
(`reference_board.json`) via `factory.project_store.load_json()`. Never
writes, never contacts a network, never contacts a printer/slicer, never
sets `human_approved`/`print_ready`, and never advances any project's
status. Missing or absent `reference_board.json` is normal (most projects
won't have one) and returns a clean, empty result - not an error.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import project_store

REFERENCE_BOARD_FILENAME = "reference_board.json"

SOURCE_TYPES = (
    "inspiration",
    "reference",
    "remixable",
    "user_uploaded",
    "sketch",
    "image",
    "stl",
    "step",
    "vector",
    "unknown",
)

LICENSES = (
    "unknown",
    "personal_use",
    "commercial_allowed",
    "cc_by",
    "cc_by_sa",
    "cc_by_nc",
    "public_domain",
    "proprietary",
    "custom",
)

USAGE_INTENTS = (
    "design_reference_only",
    "remix_candidate",
    "dimensional_reference",
    "style_reference",
    "functional_reference",
    "manufacturing_reference",
)

ATTACHED_TO_VALUES = (
    "design_intent.reference_inputs",
    "project",
    "part",
    "unknown",
)

# License values that make a declared `remix_candidate` usage_intent risky -
# either nothing is known about reuse rights, or rights are explicitly
# restricted.
_UNSAFE_REMIX_LICENSES = ("unknown", "proprietary")

REQUIRED_SAFETY_NOTES = (
    "This is a local, structured planning record only - no source_url or file referenced here is ever "
    "fetched, downloaded, scraped, or searched by this module or anything that reads its output.",
    "Advisory only - a missing or unclear license, or an unsupported field value, is never a hard "
    "failure here, only a warning for a human to resolve.",
    "Never sets human_approved or print_ready, and never advances any project's status.",
)


def _empty_board() -> dict[str, Any]:
    return {"references": []}


def read_reference_board(project_dir: Path) -> dict[str, Any]:
    """Read `<project_dir>/reference_board.json`, if present.

    Read-only: never writes, never contacts a network. Returns
    `{"references": []}` (not an error) whenever the file is missing,
    unreadable, not a JSON object, or its `references` key isn't a list -
    most projects have no reference board at all. Entries inside
    `references` are returned exactly as read, unvalidated - see
    `summarize_reference_board()` for the validated/advisory view.
    """
    path = Path(project_dir) / REFERENCE_BOARD_FILENAME
    if not path.is_file():
        return _empty_board()

    try:
        data = project_store.load_json(path)
    except (OSError, ValueError):
        return _empty_board()

    if not isinstance(data, dict):
        return _empty_board()

    references = data.get("references")
    if not isinstance(references, list):
        return _empty_board()

    return {"references": references}


def _clean_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _normalize_reference(entry: Any, index: int) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate and normalize one raw reference entry.

    Returns `(None, [warning])` for an entry that isn't even a JSON object
    (skipped entirely - it can't be attributed to a title). Otherwise
    returns a normalized entry (every field always present, unsupported
    enum values degraded to a safe default) plus zero or more advisory
    warnings - malformed input never raises here.
    """
    if not isinstance(entry, dict):
        return None, [f"Reference #{index + 1} is not a valid object and was skipped."]

    title = _clean_str(entry.get("title")) or f"Reference #{index + 1}"
    warnings: list[str] = []

    raw_source_type = entry.get("source_type")
    if raw_source_type in SOURCE_TYPES:
        source_type = raw_source_type
    else:
        if raw_source_type is not None:
            warnings.append(
                f"{title}: source_type {raw_source_type!r} is not a supported value - treated as 'unknown'."
            )
        source_type = "unknown"

    raw_license = entry.get("license")
    if raw_license in LICENSES:
        license_value = raw_license
    else:
        if raw_license is not None:
            warnings.append(
                f"{title}: license {raw_license!r} is not a supported value - treated as 'unknown'."
            )
        license_value = "unknown"

    raw_usage_intent = entry.get("usage_intent")
    if raw_usage_intent in USAGE_INTENTS:
        usage_intent = raw_usage_intent
    else:
        if raw_usage_intent is not None:
            warnings.append(f"{title}: usage_intent {raw_usage_intent!r} is not a supported value.")
        usage_intent = None

    raw_attached_to = entry.get("attached_to")
    attached_to = raw_attached_to if raw_attached_to in ATTACHED_TO_VALUES else "unknown"

    source_url = _clean_str(entry.get("source_url"))
    if source_url is None:
        warnings.append(f"{title}: no source_url recorded.")

    if license_value == "unknown":
        warnings.append(f"{title}: license is unknown - commercial use unclear.")
    elif license_value == "proprietary":
        warnings.append(f"{title}: license is proprietary - confirm rights before reuse.")

    if usage_intent == "remix_candidate" and license_value in _UNSAFE_REMIX_LICENSES:
        warnings.append(
            f"{title}: marked as a remix candidate but its license is {license_value!r} - do not remix "
            "without confirming rights."
        )

    normalized = {
        "title": title,
        "source_url": source_url,
        "source_type": source_type,
        "license": license_value,
        "usage_intent": usage_intent,
        "attached_to": attached_to,
        "notes": _clean_str(entry.get("notes")),
    }
    return normalized, warnings


def summarize_reference_board(project_dir: Path) -> dict[str, Any]:
    """Read-only, advisory summary of a project's Reference Board, for
    `factory.project_inspection.summarize_project()` and the preview board.

    Always returns a dict (never `None`) - a project with no
    `reference_board.json` gets a clean, empty result
    (`reference_count: 0`, empty breakdowns, no warnings), not an error and
    not treated differently from a board that explicitly declares zero
    references. Every warning here is advisory, never a hard failure - see
    `docs/reference-board.md`. Never fetches, downloads, or otherwise
    contacts any `source_url`.
    """
    raw = read_reference_board(project_dir)
    references = raw["references"]

    by_license: dict[str, int] = {}
    by_source_type: dict[str, int] = {}
    by_usage_intent: dict[str, int] = {}
    attached_to_design_intent_count = 0
    warnings: list[str] = []

    for index, entry in enumerate(references):
        normalized, entry_warnings = _normalize_reference(entry, index)
        warnings.extend(entry_warnings)
        if normalized is None:
            continue

        by_license[normalized["license"]] = by_license.get(normalized["license"], 0) + 1
        by_source_type[normalized["source_type"]] = by_source_type.get(normalized["source_type"], 0) + 1
        if normalized["usage_intent"]:
            by_usage_intent[normalized["usage_intent"]] = by_usage_intent.get(normalized["usage_intent"], 0) + 1
        if normalized["attached_to"] == "design_intent.reference_inputs":
            attached_to_design_intent_count += 1

    if references and attached_to_design_intent_count == 0:
        warnings.append("No references are attached to design_intent.reference_inputs yet.")

    return {
        "reference_count": len(references),
        "by_license": by_license,
        "by_source_type": by_source_type,
        "by_usage_intent": by_usage_intent,
        "attached_to_design_intent_count": attached_to_design_intent_count,
        "warnings": warnings,
    }

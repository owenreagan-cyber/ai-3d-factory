"""Phase 28: local, read-only Reference Board planning model.
Phase 29: local, human-driven CLI management on top of it (init/show/
validate/add/list) - still no network, still fully local.

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
contacts a network, never contacts a printer/slicer, never sets
`human_approved`/`print_ready`, and never advances any project's status.
Missing or absent `reference_board.json` is normal (most projects won't
have one) and returns a clean, empty result - not an error.

Phase 29 added exactly two write operations, both local-filesystem-only via
`factory.project_store.save_json()`: `init_reference_board()` (creates a
documented starter file, never overwriting an existing one unless
`force=True`) and `add_reference()` (appends one new reference, never
overwriting or removing an existing entry). Every other function in this
module remains read-only. All CLI-facing validation/normalization still
flows through the one shared `_normalize_reference()` implementation below
- `factory.cli`'s `reference-board` commands stay thin wrappers around this
module, never re-implementing it.
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


class ProjectDirectoryNotFoundError(Exception):
    """Raised when a given `project_dir` doesn't exist at all - distinct from
    a project that exists but simply has no `reference_board.json` yet (that
    case is never an error - see `read_reference_board()`)."""


class MalformedReferenceBoardError(Exception):
    """Raised only when `reference_board.json` exists but can't be parsed as
    JSON (or can't be read at all) - the one condition Phase 29's `factory
    reference-board validate` treats as a real error. Every other
    incompleteness (missing fields, unsupported enum values, an empty or
    absent file) is advisory only, never raised as an error."""


def _empty_board() -> dict[str, Any]:
    return {"references": []}


def _require_project_dir(project_dir: Path) -> Path:
    """Raise `ProjectDirectoryNotFoundError` if `project_dir` doesn't exist.
    Used only by the two write operations (`init_reference_board()`,
    `add_reference()`) - read operations stay permissive (a nonexistent
    project directory behaves the same as an existing one with no
    `reference_board.json`: a clean, empty result)."""
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        raise ProjectDirectoryNotFoundError(
            f"{project_dir} is not a directory - check the path, or run `factory init-project` first."
        )
    return project_dir


def _load_raw_or_raise(project_dir: Path) -> Any:
    """Read `<project_dir>/reference_board.json`'s raw top-level JSON value.

    Returns `None` if the file simply doesn't exist (not an error). Raises
    `MalformedReferenceBoardError` if it exists but can't be parsed as JSON
    or can't be read - the single shared primitive behind both
    `read_reference_board()` (which swallows that error into a clean empty
    result, matching every other advisory-only guarantee in this module)
    and `check_reference_board_json_is_valid()` (which surfaces it, for
    `factory reference-board validate`).
    """
    path = Path(project_dir) / REFERENCE_BOARD_FILENAME
    if not path.is_file():
        return None
    try:
        return project_store.load_json(path)
    except (OSError, ValueError) as exc:
        raise MalformedReferenceBoardError(f"{path} is not valid JSON: {exc}") from exc


def check_reference_board_json_is_valid(project_dir: Path) -> None:
    """Raise `MalformedReferenceBoardError` if `<project_dir>/reference_board.json`
    exists but isn't valid, readable JSON. Does nothing otherwise - including
    when the file is simply absent, or is valid JSON with an unexpected shape
    (not a dict, no `references` list, malformed entries inside it) - those
    are all advisory conditions `summarize_reference_board()` already
    reports as warnings, never hard failures. This is the one real "error"
    condition for `factory reference-board validate`.
    """
    _load_raw_or_raise(project_dir)


def read_reference_board(project_dir: Path) -> dict[str, Any]:
    """Read `<project_dir>/reference_board.json`, if present.

    Read-only: never writes, never contacts a network. Returns
    `{"references": []}` (not an error) whenever the file is missing,
    unreadable, not a JSON object, or its `references` key isn't a list -
    most projects have no reference board at all. Entries inside
    `references` are returned exactly as read, unvalidated - see
    `summarize_reference_board()` for the validated/advisory view.
    """
    try:
        data = _load_raw_or_raise(project_dir)
    except MalformedReferenceBoardError:
        return _empty_board()

    if data is None or not isinstance(data, dict):
        return _empty_board()

    references = data.get("references")
    if not isinstance(references, list):
        return _empty_board()

    return {"references": references}


def reference_board_exists(project_dir: Path) -> bool:
    """`True` if `<project_dir>/reference_board.json` exists on disk (whether
    or not it's readable/well-formed) - used by `factory reference-board
    init` to decide whether it would be overwriting something."""
    return (Path(project_dir) / REFERENCE_BOARD_FILENAME).is_file()


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


def _normalize_all(project_dir: Path) -> tuple[list[Any], list[dict[str, Any]], list[str]]:
    """Shared primitive behind `summarize_reference_board()` and
    `normalize_references()` - reads the raw board once and normalizes every
    entry once, so the two public functions never duplicate this loop.
    Returns `(raw_references, normalized_entries, warnings)` - `normalized_entries`
    omits entries that weren't even a JSON object (their warning is still
    included in `warnings`)."""
    raw = read_reference_board(project_dir)
    references = raw["references"]

    normalized: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, entry in enumerate(references):
        entry_normalized, entry_warnings = _normalize_reference(entry, index)
        warnings.extend(entry_warnings)
        if entry_normalized is not None:
            normalized.append(entry_normalized)

    return references, normalized, warnings


def normalize_references(project_dir: Path) -> list[dict[str, Any]]:
    """Read-only, validated/normalized list of a project's references, in
    file order - for `factory reference-board list` and anything else that
    needs per-reference detail rather than `summarize_reference_board()`'s
    aggregate counts. Every entry always has every field (`title`,
    `source_url`, `source_type`, `license`, `usage_intent`, `attached_to`,
    `notes`), with unsupported enum values already degraded to a safe
    default - the same normalization `summarize_reference_board()` uses,
    never duplicated. Entries that aren't even a JSON object are omitted
    (they're unrepresentable) - see `summarize_reference_board()`'s
    `warnings` for that detail. Empty list (not an error) when there's no
    reference board at all.
    """
    _references, normalized, _warnings = _normalize_all(project_dir)
    return normalized


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
    references, normalized, warnings = _normalize_all(project_dir)

    by_license: dict[str, int] = {}
    by_source_type: dict[str, int] = {}
    by_usage_intent: dict[str, int] = {}
    attached_to_design_intent_count = 0

    for entry in normalized:
        by_license[entry["license"]] = by_license.get(entry["license"], 0) + 1
        by_source_type[entry["source_type"]] = by_source_type.get(entry["source_type"], 0) + 1
        if entry["usage_intent"]:
            by_usage_intent[entry["usage_intent"]] = by_usage_intent.get(entry["usage_intent"], 0) + 1
        if entry["attached_to"] == "design_intent.reference_inputs":
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


# ---- Phase 29: CLI-facing write operations (still local-only) ----


def _starter_board() -> dict[str, Any]:
    """A documented starter `reference_board.json` - explains itself in
    place so a human never has to consult this module's source to know what
    fields/values are supported. `notes` is read by nothing (like
    `design_intent`'s own `notes` convention elsewhere in this repo's
    example projects) - it's for a human reader only."""
    return {
        "notes": [
            "Local Reference Board - see docs/reference-board.md for the full field/vocabulary reference.",
            "No source_url here is ever fetched, downloaded, scraped, or searched automatically - it is "
            "inert metadata only, exactly like a URL written on a sticky note.",
            "Supported source_type values: " + ", ".join(SOURCE_TYPES) + ".",
            "Supported license values: " + ", ".join(LICENSES) + ".",
            "Supported usage_intent values: " + ", ".join(USAGE_INTENTS) + ".",
            "Supported attached_to values: " + ", ".join(ATTACHED_TO_VALUES) + ".",
            "Add references by hand-editing this file, or with `factory reference-board add --project "
            "<path> --title <title> [--url <url>] [--type <source_type>] [--license <license>] "
            "[--usage <usage_intent>] [--attached-to <attached_to>] [--notes <notes>]`.",
            "A missing field, an unrecognized value, or a missing license is never a hard failure - run "
            "`factory reference-board validate <path>` to see advisory warnings, never an error, unless "
            "this file itself becomes invalid JSON.",
        ],
        "references": [],
    }


def init_reference_board(project_dir: Path, *, force: bool = False) -> tuple[Path, bool]:
    """Create `<project_dir>/reference_board.json` with a documented starter
    shape, if one doesn't already exist.

    Returns `(path, created)` - `created` is `False` (not an error) when a
    file already exists and `force` is `False`, so re-running `factory
    reference-board init` on a project that already has references never
    loses data. Pass `force=True` to overwrite with a fresh starter file
    (only via an explicit `--force` CLI flag - never automatic). Raises
    `ProjectDirectoryNotFoundError` if `project_dir` doesn't exist - this
    never creates the project directory itself, only the file inside it.
    """
    project_dir = _require_project_dir(project_dir)
    path = project_dir / REFERENCE_BOARD_FILENAME
    if path.is_file() and not force:
        return path, False
    project_store.save_json(path, _starter_board())
    return path, True


def add_reference(
    project_dir: Path,
    *,
    title: str,
    source_url: str | None = None,
    source_type: str | None = None,
    license: str | None = None,
    usage_intent: str | None = None,
    attached_to: str | None = None,
    notes: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Append one new reference to `<project_dir>/reference_board.json`,
    creating the file first (via `init_reference_board()`'s starter shape)
    if it doesn't exist yet.

    Always appends - never overwrites or removes an existing entry, and
    never overwrites the file's other content (e.g. its `notes`). Values
    are written exactly as given, not silently corrected: an unrecognized
    `source_type`/`license`/`usage_intent`/`attached_to` is still saved (so
    nothing a human typed is ever discarded), and the same
    `_normalize_reference()` this module already uses for
    `summarize_reference_board()`/`normalize_references()` is reused (not
    duplicated) to compute advisory warnings about the just-added entry,
    returned alongside it for immediate CLI feedback.

    Returns `(raw_entry, warnings)`. Raises `ProjectDirectoryNotFoundError`
    if `project_dir` doesn't exist. Local filesystem only - no network, no
    printer/slicer contact, never sets `human_approved`/`print_ready`.
    """
    project_dir = _require_project_dir(project_dir)
    path = project_dir / REFERENCE_BOARD_FILENAME

    if path.is_file():
        try:
            data = project_store.load_json(path)
        except (OSError, ValueError) as exc:
            raise MalformedReferenceBoardError(
                f"{path} exists but is not valid JSON - fix or remove it before adding a reference."
            ) from exc
        if not isinstance(data, dict):
            data = {"references": []}
        references = data.get("references")
        if not isinstance(references, list):
            references = []
        data["references"] = references
    else:
        data = _starter_board()
        references = data["references"]

    new_entry: dict[str, Any] = {"title": title}
    if source_url is not None:
        new_entry["source_url"] = source_url
    if source_type is not None:
        new_entry["source_type"] = source_type
    if license is not None:
        new_entry["license"] = license
    if usage_intent is not None:
        new_entry["usage_intent"] = usage_intent
    if attached_to is not None:
        new_entry["attached_to"] = attached_to
    if notes is not None:
        new_entry["notes"] = notes

    references.append(new_entry)
    project_store.save_json(path, data)

    _normalized, warnings = _normalize_reference(new_entry, len(references) - 1)
    return new_entry, warnings

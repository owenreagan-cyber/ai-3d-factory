"""Phase 30: local, fully deterministic Project Intake Engine.

Converts a free-form natural-language product idea (plain text, Markdown,
or an existing project's `brief.json` description) into structured intake
metadata - the very first step in this repo's pipeline:

    User Idea -> Project Intake -> Project Brief -> Design Intent ->
    Reference Board -> Manufacturing Planning -> CAD Generation ->
    Preview Board -> Review Gate

**No AI, no LLM, no machine learning, and no network of any kind.** Every
field here is extracted with plain, closed keyword tables and regular
expressions - fully deterministic (the same input text always produces the
exact same output) and fully local. This module never generates CAD, never
runs OpenSCAD/CadQuery, never launches Blender, never calls Meshy, never
performs a web search, never scrapes a website, never downloads anything,
and never performs OCR or computer vision - it only reads text a human
already wrote (a `.txt`/`.md` file, or a project's own `brief.json`) and
looks for known words and patterns in it. See `docs/project-intake.md`.

Every extracted field carries a `confidence` (`"high"`/`"medium"`/`"low"`/
`"unknown"`) reflecting how directly the heuristic matched, never a
probability or a model score - there is no model. `warnings` is an
advisory list, never a hard failure: this module never raises on
ambiguous, sparse, or entirely absent input, it just returns lower
confidence and more advisories.

Read-only except where explicitly noted: `analyze_text_file()` and
`analyze_project()` only read files via `Path.read_text()` /
`factory.project_store.load_json()`. This module writes nothing, ever -
unlike `factory.reference_board`'s Phase 29 write operations, there is no
`factory intake` command that creates or modifies any file.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from factory import project_store

CONFIDENCE_LEVELS = ("high", "medium", "low", "unknown")

CATEGORIES = (
    "sign",
    "organizer",
    "toy",
    "décor",
    "fixture",
    "mechanical",
    "educational",
    "storage",
    "replacement part",
    "accessory",
    "unknown",
)

ENVIRONMENTS = ("classroom", "office", "home", "garage", "outdoor", "unknown")

MATERIALS = ("PLA", "PETG", "ABS", "TPU", "unknown")

PRINTERS = ("Bambu", "Prusa", "Voron", "generic FDM", "unknown")

QUALITY_TARGETS = ("prototype", "functional", "premium", "etsy-worthy", "presentation", "gift", "unknown")

MANUFACTURING_STYLES = (
    "single-part",
    "multi-part",
    "AMS",
    "single-color",
    "multi-color",
    "support-free preferred",
    "unknown",
)

SOURCES = ("brief_description", "text_file", "markdown_file", "none")

# ---- keyword tables (closed vocabulary, checked in this exact priority order) ----

_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sign", ("nameplate", "name plate", "sign", "plaque", "placard", "label")),
    ("organizer", ("organizer", "organiser", "holder", "caddy", "tray", "rack")),
    ("toy", ("toy", "figurine", "puzzle", "game piece")),
    ("décor", ("decor", "décor", "decoration", "ornament", "centerpiece")),
    ("fixture", ("fixture", "wall mount", "bracket", "mount")),
    ("mechanical", ("gear", "hinge", "mechanism", "linkage", "gearbox")),
    ("educational", ("classroom", "teacher", "student", "school", "educational")),
    ("storage", ("storage", "bin", "container")),
    ("replacement part", ("replacement part", "spare part", "replacement for", "broken part")),
    ("accessory", ("accessory", "case", "clip", "adapter", "stand")),
)

_ENVIRONMENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("classroom", ("classroom", "school", "teacher", "student")),
    ("office", ("office", "workplace", "cubicle", "desk")),
    ("home", ("home", "house", "kitchen", "bedroom", "living room")),
    ("garage", ("garage", "workshop", "toolbox")),
    ("outdoor", ("outdoor", "outside", "garden", "patio", "backyard")),
)

_MATERIAL_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("PLA", ("pla",)),
    ("PETG", ("petg", "pet-g")),
    ("ABS", ("abs",)),
    ("TPU", ("tpu",)),
)

_PRINTER_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Bambu", ("bambu", "ams")),
    ("Prusa", ("prusa",)),
    ("Voron", ("voron",)),
    ("generic FDM", ("generic fdm", "fdm printer", "any fdm")),
)

# Priority order when more than one quality signal is present (highest first) -
# distinct from _QUALITY_KEYWORDS' iteration order, which only controls how
# matches are collected, not which one wins.
_QUALITY_PRIORITY = ("etsy-worthy", "gift", "premium", "presentation", "functional", "prototype")

_QUALITY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("etsy-worthy", ("etsy-worthy", "etsy worthy")),
    ("gift", ("gift-quality", "gift quality", "gift-worthy", "as a gift", "for a gift")),
    ("premium", ("premium",)),
    ("presentation", ("presentation-quality", "presentation quality", "display piece", "showpiece")),
    ("functional", ("functional prototype", "functional part", "working prototype")),
    ("prototype", ("prototype", "proof of concept", "first draft")),
)

_MANUFACTURING_STYLE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("multi-part", ("multi-part", "multipart", "multiple parts", "modular", "assembly")),
    ("single-part", ("single-part", "single part", "one piece", "one-piece")),
    ("AMS", ("ams", "ams compatible", "ams-compatible", "ams compatibility")),
    ("multi-color", ("multi-color", "multicolor", "multi-colour", "two-color", "two-tone")),
    ("single-color", ("single-color", "single color", "one color", "one colour")),
    ("support-free preferred", ("support-free", "support free", "no supports", "avoid supports")),
)

_FUNCTIONAL_GOAL_KEYWORDS = (
    "hold", "holds", "holding", "store", "storing", "organize", "organizing", "mount", "mounting",
    "clip", "clips", "hinge", "hinged", "snap-fit", "snap fit", "flex", "flexes", "flexing",
    "hang", "hanging", "protect", "protecting", "attach", "attaching", "load-bearing", "load bearing",
)

_VISUAL_GOAL_KEYWORDS = (
    "anime", "minimalist", "modern", "cute", "elegant", "sleek", "colorful", "colourful",
    "engraved", "embossed", "raised", "glossy", "matte", "ornate", "rustic", "industrial",
    "geometric", "lettering", "typography", "decorative",
)

_COMMERCIAL_KEYWORDS = (
    "sell", "selling", "for sale", "customer", "customers", "client", "clients",
    "my shop", "etsy shop", "commission", "commissions", "profit", "buyers",
)

_DIMENSION_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:-\s*)?(?:mm|cm|millimeters?|centimeters?|inch(?:es)?|in\b|feet|foot|ft\b)",
    re.IGNORECASE,
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_MARKDOWN_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*\S)\s*$")


def _field(value: Any, confidence: str) -> dict[str, Any]:
    return {"value": value, "confidence": confidence}


def _contains_keyword(text_lower: str, keyword: str) -> bool:
    """Word-boundary keyword match - deliberately *not* a plain substring
    check (`keyword in text_lower`), which would false-positive on
    "de**sign**", "b**rack**et", "**pla**que", "**abs**olute", and similar:
    a whole-word/whole-phrase match only, case already normalized by the
    caller. This is the one shared primitive every keyword-table lookup in
    this module goes through."""
    return re.search(r"\b" + re.escape(keyword) + r"\b", text_lower) is not None


def _first_match(text_lower: str, table: tuple[tuple[str, tuple[str, ...]], ...]) -> tuple[str | None, list[str]]:
    """Scan `table` in order; return `(first_matching_key, all_matching_keys)`.
    `all_matching_keys` (in table order) is used by callers to decide
    confidence: a single distinct match is unambiguous ("high"), more than
    one distinct match is present-but-ambiguous ("medium")."""
    matched: list[str] = []
    for key, keywords in table:
        if any(_contains_keyword(text_lower, keyword) for keyword in keywords):
            matched.append(key)
    return (matched[0] if matched else None), matched


def _extract_single_enum(text_lower: str, table: tuple[tuple[str, tuple[str, ...]], ...]) -> dict[str, Any]:
    first, matched = _first_match(text_lower, table)
    if not matched:
        return _field("unknown", "unknown")
    return _field(first, "high" if len(matched) == 1 else "medium")


def _extract_list_enum(text_lower: str, table: tuple[tuple[str, tuple[str, ...]], ...]) -> dict[str, Any]:
    """For closed-vocabulary list fields (material/printer/manufacturing-style)
    where each table entry is a specific, low-ambiguity term: unlike a
    single-enum field, finding *more than one* distinct value here isn't
    ambiguity (a design can genuinely use two materials) - it's just more
    signal. So confidence is simply "did we find any explicit match at all",
    not "how many different candidates competed"."""
    _first, matched = _first_match(text_lower, table)
    if not matched:
        return _field([], "unknown")
    return _field(matched, "high")


def _extract_quality_target(text_lower: str) -> dict[str, Any]:
    _first, matched = _first_match(text_lower, _QUALITY_KEYWORDS)
    if not matched:
        return _field("unknown", "unknown")
    winner = next(candidate for candidate in _QUALITY_PRIORITY if candidate in matched)
    return _field(winner, "high" if len(matched) == 1 else "medium")


def _extract_keyword_list(text_lower: str, keywords: tuple[str, ...]) -> dict[str, Any]:
    matched = [kw for kw in keywords if _contains_keyword(text_lower, kw)]
    if not matched:
        return _field([], "unknown")
    return _field(matched, "high" if len(matched) >= 2 else "medium")


def _extract_dimensional_constraints(text: str) -> dict[str, Any]:
    """A number-plus-unit regex match (e.g. "48-inch", "120mm") is a precise,
    low-false-positive signal - confidence is "high" whenever at least one
    is found, "unknown" otherwise. Finding several doesn't add ambiguity,
    it adds information (e.g. a full x/y/z size spec)."""
    matches = [m.group(0).strip() for m in _DIMENSION_PATTERN.finditer(text)]
    if not matches:
        return _field([], "unknown")
    return _field(matches, "high")


def _extract_commercial_intent(text_lower: str) -> dict[str, Any]:
    matched = [kw for kw in _COMMERCIAL_KEYWORDS if _contains_keyword(text_lower, kw)]
    if not matched:
        return _field(False, "unknown")
    return _field(True, "high")


def _extract_audience(text_lower: str) -> dict[str, Any]:
    table = (
        ("Students", ("student", "students", "kids", "children", "child")),
        ("Teachers", ("teacher", "teachers", "educator")),
        ("Gift recipient", ("gift", "present", "surprise")),
        ("Customers", ("customer", "customers", "client", "clients")),
        ("Self", ("myself", "for me", "personal use", "my own")),
    )
    first, matched = _first_match(text_lower, table)
    if not matched:
        return _field(None, "unknown")
    return _field(first, "high" if len(matched) == 1 else "medium")


def _strip_markdown_headings(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not _MARKDOWN_HEADING.match(line))


def _extract_purpose(text: str) -> dict[str, Any]:
    body = _strip_markdown_headings(text).strip()
    if not body:
        return _field(None, "unknown")
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(body) if s.strip()]
    if not sentences:
        return _field(None, "unknown")
    purpose = sentences[0][:300]
    return _field(purpose, "medium")


def _extract_project_name(text: str) -> dict[str, Any]:
    for line in text.splitlines():
        heading = _MARKDOWN_HEADING.match(line)
        if heading:
            return _field(heading.group(1), "high")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            if len(stripped) <= 80:
                return _field(stripped, "medium")
            return _field(None, "unknown")
    return _field(None, "unknown")


def extract_intake_fields(text: str) -> dict[str, Any]:
    """Core, fully deterministic heuristic extraction over raw text (plain
    text or Markdown - Markdown syntax is never stripped before keyword
    matching, only before purpose/project-name sentence extraction, since
    every other heuristic here is a simple case-insensitive substring/regex
    match over the whole string). No network, no ML, no LLM - closed
    keyword tables and regexes only. See `docs/project-intake.md` for the
    full heuristic/confidence reference.

    Returns the `intake_summary` shape - every field is
    `{"value": ..., "confidence": "high"|"medium"|"low"|"unknown"}`, plus a
    top-level `warnings` (advisory-only, list of str). Never raises on
    empty, sparse, or malformed-looking input.
    """
    text = text or ""
    if not text.strip():
        return {
            "project_name": _field(None, "unknown"),
            "category": _field("unknown", "unknown"),
            "purpose": _field(None, "unknown"),
            "audience": _field(None, "unknown"),
            "environment": _field("unknown", "unknown"),
            "material_assumptions": _field([], "unknown"),
            "printer_assumptions": _field([], "unknown"),
            "quality_target": _field("unknown", "unknown"),
            "manufacturing_style": _field([], "unknown"),
            "functional_goals": _field([], "unknown"),
            "visual_goals": _field([], "unknown"),
            "dimensional_constraints": _field([], "unknown"),
            "commercial_intent": _field(False, "unknown"),
            "warnings": ["No project description text found to analyze - nothing could be inferred."],
        }

    text_lower = text.lower()

    category = _extract_single_enum(text_lower, _CATEGORY_KEYWORDS)
    environment = _extract_single_enum(text_lower, _ENVIRONMENT_KEYWORDS)
    material_assumptions = _extract_list_enum(text_lower, _MATERIAL_KEYWORDS)
    printer_assumptions = _extract_list_enum(text_lower, _PRINTER_KEYWORDS)
    quality_target = _extract_quality_target(text_lower)
    manufacturing_style = _extract_list_enum(text_lower, _MANUFACTURING_STYLE_KEYWORDS)
    functional_goals = _extract_keyword_list(text_lower, _FUNCTIONAL_GOAL_KEYWORDS)
    visual_goals = _extract_keyword_list(text_lower, _VISUAL_GOAL_KEYWORDS)
    dimensional_constraints = _extract_dimensional_constraints(text)
    commercial_intent = _extract_commercial_intent(text_lower)
    audience = _extract_audience(text_lower)
    purpose = _extract_purpose(text)
    project_name = _extract_project_name(text)

    warnings: list[str] = []
    if not dimensional_constraints["value"]:
        warnings.append("Dimensions not specified.")
    if not printer_assumptions["value"]:
        warnings.append("Printer not specified.")
    if not material_assumptions["value"]:
        warnings.append("Material not specified.")
    if quality_target["value"] in ("premium", "etsy-worthy", "gift", "presentation") and not any(
        _contains_keyword(text_lower, kw) for kw in ("photo", "picture", "image", "reference")
    ):
        warnings.append("Reference images recommended - see `factory reference-board add`.")
    if functional_goals["value"]:
        warnings.append("Mechanical testing recommended - functional/moving parts detected.")
    if commercial_intent["value"]:
        warnings.append("Commercial intent detected - review docs/licensing-policy.md before proceeding.")
    if quality_target["value"] == "gift":
        warnings.append("Gift-quality target detected - see docs/design-quality-standard.md.")

    weak_fields = [
        f["confidence"] in ("unknown", "low")
        for f in (category, environment, quality_target, material_assumptions, printer_assumptions)
    ]
    if sum(weak_fields) >= 3:
        warnings.append(
            "Human review recommended - intake confidence is low for several fields; review and complete "
            "this project's brief.json/design_intent by hand."
        )

    return {
        "project_name": project_name,
        "category": category,
        "purpose": purpose,
        "audience": audience,
        "environment": environment,
        "material_assumptions": material_assumptions,
        "printer_assumptions": printer_assumptions,
        "quality_target": quality_target,
        "manufacturing_style": manufacturing_style,
        "functional_goals": functional_goals,
        "visual_goals": visual_goals,
        "dimensional_constraints": dimensional_constraints,
        "commercial_intent": commercial_intent,
        "warnings": warnings,
    }


def analyze_text(text: str, *, source: str) -> dict[str, Any]:
    """`extract_intake_fields(text)` plus a `source` tag (one of `SOURCES`)
    recording where the analyzed text came from - for display/debugging
    only, never read by any downstream logic."""
    summary = extract_intake_fields(text)
    summary["source"] = source
    return summary


def analyze_text_file(file_path: Path) -> dict[str, Any]:
    """Read a plain-text or Markdown file and run `extract_intake_fields()`
    over its content. Read-only, local filesystem only - no network. A
    missing file, an unreadable/non-UTF-8 file, or an empty file all
    degrade to a clean "no signal" result (not an error), consistent with
    every other advisory-only guarantee in this module.
    """
    file_path = Path(file_path)
    try:
        text = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = ""
    source = "markdown_file" if file_path.suffix.lower() in (".md", ".markdown") else "text_file"
    return analyze_text(text, source=source)


def analyze_project(project_dir: Path) -> dict[str, Any]:
    """Read `<project_dir>/brief.json` (if present) and run the same
    heuristic extraction over its `project_name` + `description` +
    `constraints` text. Read-only. Returns a clean "no signal" result (not
    an error) whenever `brief.json` is missing, unreadable, or malformed -
    most of this function's guarantees mirror
    `factory.reference_board.summarize_reference_board()`'s. The brief's
    own literal `project_name` (a structured field, not inferred) always
    wins over any heading/first-line guess `extract_intake_fields()` would
    otherwise make from the description text.
    """
    project_dir = Path(project_dir)
    brief_path = project_dir / "brief.json"
    if not brief_path.is_file():
        return analyze_text("", source="none")

    try:
        brief = project_store.load_json(brief_path)
    except (OSError, ValueError):
        return analyze_text("", source="none")
    if not isinstance(brief, dict):
        return analyze_text("", source="none")

    name = brief.get("project_name")
    description = brief.get("description")
    constraints = brief.get("constraints")

    # description first, so purpose/first-sentence extraction reads the
    # actual descriptive prose rather than the (period-less) project_name
    # slug - project_name is appended after, still contributing to
    # keyword matching for every other field, and always overridden below
    # by the brief's own literal, structured project_name regardless of
    # extract_intake_fields()'s own project-name guess.
    parts: list[str] = []
    if isinstance(description, str):
        parts.append(description)
    if isinstance(name, str):
        parts.append(name)
    if isinstance(constraints, list):
        parts.extend(c for c in constraints if isinstance(c, str))

    summary = analyze_text("\n".join(parts), source="brief_description")
    if isinstance(name, str) and name.strip():
        summary["project_name"] = _field(name, "high")
    return summary


def analyze(path: Path) -> dict[str, Any]:
    """Single entry point for `factory intake analyze <path>` - dispatches
    on whether `path` is a project directory (`analyze_project()`) or a
    text/Markdown file (`analyze_text_file()`). Read-only either way; a
    nonexistent path degrades to a clean "no signal" result rather than
    raising, matching this module's other advisory-only guarantees.
    """
    path = Path(path)
    if path.is_dir():
        return analyze_project(path)
    if path.is_file():
        return analyze_text_file(path)
    return analyze_text("", source="none")

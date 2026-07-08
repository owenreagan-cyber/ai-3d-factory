"""Read-only advisory check: does a brief's optional
`design_intent.manufacturability_constraints.max_size_mm` fit within any
locally configured printer's build volume?

Local filesystem only: reads one JSON file (a `brief.json` or
`concept_brief.json`) and `config/manufacturing/printers.json` via
`factory.manufacturing.knowledge.load_printers()` - never contacts a
printer, never discovers printers, never contacts a slicer or network,
never installs anything, and never writes any file. This is a
size-only, declared-intent-vs-configured-fleet advisory: it never
inspects actual mesh geometry (that is `factory validate`'s job, on a
real STL, once one exists) and never sets `human_approved` or
`print_ready`, and never advances any project's status. See
`docs/design-intent-brief.md`.

Phase 26 added `summarize_design_intent()` - a read-only, human-facing
summary (quality standard, use case, style direction, declared size, and
the manufacturability advisory above) for surfacing in `factory report`
and the preview board. It reuses `check_design_intent_manufacturability()`
for every field that function already parses rather than re-deriving that
logic, and returns `None` (not an error) whenever `design_intent` is
absent - visibility only, still no approval/scoring/print-readiness
behavior. See `docs/design-intent-brief.md`.
"""

from __future__ import annotations

from itertools import permutations
from pathlib import Path
from typing import Any

from factory import project_store
from factory.manufacturing import knowledge

RESULT_NO_DESIGN_INTENT = "no_design_intent"
RESULT_NO_MAX_SIZE = "no_max_size"
RESULT_FITS_SOME = "fits_some_printers"
RESULT_FITS_NONE = "fits_no_known_printers"
RESULT_INVALID_MAX_SIZE = "invalid_max_size"
RESULT_MISSING_PRINTER_CONFIG = "missing_printer_config"
RESULT_UNREADABLE_FILE = "unreadable_file"

REQUIRED_SAFETY_NOTES = (
    "This is an advisory manufacturability check only - it compares declared design "
    "intent against known configured printer build volumes; it does not inspect actual "
    "mesh geometry.",
    "This command never contacts a printer, discovers printers, or communicates with a "
    "slicer or network.",
    "This is not an approval and not a print-readiness signal - human_approved and "
    "print_ready are never set by this check.",
    "Once a real STL exists, it still needs factory validate, factory render, factory "
    "review-gate, and human slicer review before anything is print-ready.",
)


def _valid_max_size(value: Any) -> tuple[float, float, float] | None:
    """Return (x, y, z) floats if `value` is a well-formed 3-element positive-number
    list/tuple, else None."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        dims = tuple(float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if any(d <= 0 for d in dims):
        return None
    return dims  # type: ignore[return-value]


def _fits_any_orientation(dims: tuple[float, float, float], volume: tuple[float, float, float]) -> bool:
    """Mirrors factory.validators.dimension_check.check_build_volume_fit's
    any-axis-orientation logic, generalized to a whole printer fleet rather
    than one target printer."""
    return any(all(d <= v for d, v in zip(perm, volume)) for perm in permutations(dims))


def _result(
    file_path: Path,
    result: str,
    *,
    quality_standard: str | None = None,
    max_size_mm: list[float] | Any | None = None,
    fitting_printers: list[dict[str, Any]] | None = None,
    non_fitting_printers: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "file": str(file_path),
        "result": result,
        "quality_standard": quality_standard,
        "max_size_mm": max_size_mm,
        "fitting_printers": fitting_printers or [],
        "non_fitting_printers": non_fitting_printers or [],
        "warnings": warnings or [],
        "notes": list(REQUIRED_SAFETY_NOTES),
    }


def check_design_intent_manufacturability(file_path: Path) -> dict[str, Any]:
    """Read a `brief.json`/`concept_brief.json` and report whether its optional
    `design_intent.manufacturability_constraints.max_size_mm` fits any locally
    configured printer's build volume.

    Read-only: never writes, never contacts a printer/slicer/network, never
    installs anything, never sets `human_approved`/`print_ready`, never
    advances any project status.
    """
    file_path = Path(file_path)

    try:
        data = project_store.load_json(file_path)
    except (OSError, ValueError):
        return _result(file_path, RESULT_UNREADABLE_FILE)

    design_intent = data.get("design_intent") if isinstance(data, dict) else None
    if not isinstance(design_intent, dict):
        return _result(file_path, RESULT_NO_DESIGN_INTENT)

    quality_standard = design_intent.get("quality_standard")

    constraints = design_intent.get("manufacturability_constraints")
    raw_max_size = constraints.get("max_size_mm") if isinstance(constraints, dict) else None

    if raw_max_size is None:
        return _result(file_path, RESULT_NO_MAX_SIZE, quality_standard=quality_standard)

    dims = _valid_max_size(raw_max_size)
    if dims is None:
        return _result(
            file_path,
            RESULT_INVALID_MAX_SIZE,
            quality_standard=quality_standard,
            max_size_mm=raw_max_size,
            warnings=[
                f"design_intent.manufacturability_constraints.max_size_mm ({raw_max_size!r}) is not "
                "a 3-element [x, y, z] list of positive numbers - skipped the printer fit check."
            ],
        )

    printers = knowledge.load_printers()
    if not printers:
        return _result(
            file_path,
            RESULT_MISSING_PRINTER_CONFIG,
            quality_standard=quality_standard,
            max_size_mm=list(dims),
            warnings=["config/manufacturing/printers.json is missing or has no printers configured."],
        )

    fitting: list[dict[str, Any]] = []
    non_fitting: list[dict[str, Any]] = []
    for printer_id, printer in sorted(printers.items()):
        build_volume = printer.get("build_volume_mm") or {}
        volume_dims = (
            float(build_volume.get("x", 0.0)),
            float(build_volume.get("y", 0.0)),
            float(build_volume.get("z", 0.0)),
        )
        entry = {
            "printer_id": printer_id,
            "display_name": printer.get("display_name", printer_id),
            "build_volume_mm": build_volume,
            "verified": printer.get("verified", False),
        }
        if _fits_any_orientation(dims, volume_dims):
            fitting.append(entry)
        else:
            non_fitting.append(entry)

    warnings: list[str] = []
    if fitting:
        unverified = [p["display_name"] for p in fitting if not p["verified"]]
        if unverified:
            warnings.append(
                f"{len(unverified)} fitting printer(s) have UNVERIFIED build volume specs "
                f"({', '.join(unverified)}) - confirm before treating this as a hard fit."
            )
        result = RESULT_FITS_SOME
    else:
        warnings.append(
            "No known configured printer fits this size in any orientation - consider "
            "splitting the design into multiple parts or resizing it."
        )
        result = RESULT_FITS_NONE

    return _result(
        file_path,
        result,
        quality_standard=quality_standard,
        max_size_mm=list(dims),
        fitting_printers=fitting,
        non_fitting_printers=non_fitting,
        warnings=warnings,
    )


def summarize_design_intent(file_path: Path) -> dict[str, Any] | None:
    """Read-only, human-facing summary of a brief's `design_intent`, for display in
    `factory report` and the preview board - visibility only, not a new judgment.

    Returns `None` (not an error) whenever `design_intent` is absent, the file is
    unreadable, or `design_intent` isn't a dict - most briefs won't have one at all.
    `quality_standard`, `max_size_mm`, and `manufacturability_check` are read via
    `check_design_intent_manufacturability()` rather than re-parsed here, so this
    function never duplicates that parsing/fit logic; it only adds the couple of
    extra display fields (`use_case`, `style_direction`) that function intentionally
    doesn't read (its scope is manufacturability only). A malformed `use_case`
    (not a string) or `style_direction` (not a list) degrades to `None` for that
    field rather than raising. Read-only: same guarantees as
    `check_design_intent_manufacturability()` - no writes, no network, no printer/
    slicer contact, never sets `human_approved`/`print_ready`.
    """
    file_path = Path(file_path)

    try:
        data = project_store.load_json(file_path)
    except (OSError, ValueError):
        return None

    design_intent = data.get("design_intent") if isinstance(data, dict) else None
    if not isinstance(design_intent, dict):
        return None

    manufacturability = check_design_intent_manufacturability(file_path)

    use_case = design_intent.get("use_case")
    style_direction = design_intent.get("style_direction")

    return {
        "quality_standard": manufacturability["quality_standard"],
        "use_case": use_case if isinstance(use_case, str) else None,
        "style_direction": style_direction if isinstance(style_direction, list) else None,
        "max_size_mm": manufacturability["max_size_mm"],
        "manufacturability_check": {
            "result": manufacturability["result"],
            "fitting_printers": [p["display_name"] for p in manufacturability["fitting_printers"]],
        },
    }

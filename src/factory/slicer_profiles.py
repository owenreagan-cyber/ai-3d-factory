"""Phase 39 Part 1/2: Slicer-Aware Review Profiles.

Customizes review guidance based on the detected local slicer
environment - never requires any of these applications to be installed,
never invents which one is installed, and never edits, launches, or
configures any of them. Reuses
`factory.slicer.local_slicer_probe.probe_slicers()` (the single, existing
local slicer-detection module - Phase 39 extended it in place with a
`PrusaSlicer` candidate rather than creating a second slicer registry)
for detection; this module owns only the review-guidance content mapped
to each detected (or undetected) slicer name.

**Never invents an installed profile.** If no supported slicer is
detected locally, `profile_status` is `"not_detected"` and
`get_slicer_review_profile()` falls back to a generic, slicer-agnostic
checklist - it never guesses which slicer a human might be using.
"""

from __future__ import annotations

from typing import Any

from factory.slicer.local_slicer_probe import probe_slicers

SUPPORTED_SLICER_NAMES = ("Bambu Studio", "OrcaSlicer", "PrusaSlicer")

PROFILE_STATUSES = ("detected", "not_detected")

CONFIDENCE_LEVELS = ("High", "Medium", "Low", "Unknown")

# Review guidance content only - never printer/material data (that stays
# in factory.manufacturing.knowledge) and never slicer settings/values
# (this module never invents or recommends a specific setting, only what
# to *review*).
_SLICER_PROFILES: dict[str, dict[str, Any]] = {
    "Bambu Studio": {
        "known_capabilities": [
            "AMS multi-material/multi-color",
            "Multi-plate project files",
            "Built-in calibration profiles",
        ],
        "review_categories": ["AMS assignments", "Filament mapping", "Build plate choice", "Support settings", "Wall count", "Strength settings"],
        "printer_questions": [
            "Confirm the correct Bambu printer profile is selected.",
            "Confirm build plate type matches the physical plate installed.",
            "Confirm nozzle size matches the physical nozzle installed.",
        ],
        "material_questions": [
            "Confirm filament profile matches the actual filament loaded.",
            "Confirm filament drying/prep matches this material's requirements.",
        ],
        "multi_material_questions": [
            "Confirm AMS filament mapping - each AMS slot assigned to the correct filament.",
            "Confirm plate selection for multi-plate projects.",
            "Confirm multi-color assignment per part/region.",
            "Confirm purge/prime tower expectations for this color count.",
        ],
    },
    "OrcaSlicer": {
        "known_capabilities": [
            "Calibration profile library (pressure advance, flow, etc.)",
            "Adaptive layer heights",
            "AMS/multi-material support (printer-dependent)",
        ],
        "review_categories": ["Filament profile", "Calibration profile", "Pressure advance awareness", "Supports", "Adaptive layers"],
        "printer_questions": [
            "Confirm the correct printer profile is selected.",
            "Confirm nozzle size matches the physical nozzle installed.",
        ],
        "material_questions": [
            "Confirm filament profile matches the actual filament loaded.",
            "Confirm a pressure-advance/flow calibration profile exists for this filament, if you rely on one.",
        ],
        "multi_material_questions": [
            "Confirm AMS/multi-material unit filament mapping, if applicable.",
            "Confirm multi-color assignment per part/region.",
            "Confirm purge/prime expectations for this color count.",
        ],
    },
    "PrusaSlicer": {
        "known_capabilities": [
            "Printer/filament/print settings profile system",
            "Multi-material unit (MMU) support (printer-dependent)",
        ],
        "review_categories": ["Filament profile", "Printer profile", "Support settings", "Layer settings"],
        "printer_questions": [
            "Confirm the correct printer profile is selected.",
            "Confirm nozzle size matches the physical nozzle installed.",
        ],
        "material_questions": [
            "Confirm filament profile matches the actual filament loaded.",
        ],
        "multi_material_questions": [
            "Confirm MMU filament mapping, if applicable.",
            "Confirm multi-color assignment per part/region.",
            "Confirm purge/prime expectations for this color count.",
        ],
    },
}

_GENERIC_PROFILE: dict[str, Any] = {
    "known_capabilities": [],
    "review_categories": ["Filament profile", "Printer profile", "Support settings", "Layer settings"],
    "printer_questions": [
        "Confirm the correct printer profile is selected in whichever slicer you use.",
        "Confirm nozzle size matches the physical nozzle installed.",
    ],
    "material_questions": [
        "Confirm the filament profile matches the actual filament loaded.",
    ],
    "multi_material_questions": [
        "Confirm multi-color/multi-material assignment per part/region.",
        "Confirm purge/prime expectations for this color count.",
    ],
}


def detect_slicer_profile() -> str:
    """Return the name of the first detected supported local slicer, in
    `SUPPORTED_SLICER_NAMES` priority order, or `"Unknown"` if none is
    detected. Reuses `probe_slicers()` directly - never a second
    detection pass."""
    detected = {entry["name"] for entry in probe_slicers() if entry["found"]}
    for name in SUPPORTED_SLICER_NAMES:
        if name in detected:
            return name
    return "Unknown"


def get_slicer_review_profile(slicer_name: str | None = None, *, multi_material: bool = False) -> dict[str, Any]:
    """Build a `SlicerReviewProfile` model for `slicer_name` (auto-detected
    via `detect_slicer_profile()` if not given). Never invents an
    installed profile - an undetected/unsupported slicer always falls back
    to the generic, slicer-agnostic checklist, and `profile_status`
    honestly reports whether a supported slicer was actually detected
    locally.
    """
    detected_slicers = probe_slicers()
    resolved_name = slicer_name if slicer_name is not None else detect_slicer_profile()

    warnings: list[str] = []
    limitations: list[str] = [
        "This profile only reflects local slicer application detection - it never reads that "
        "slicer's actual saved settings/profiles, and it never launches or configures it.",
    ]

    if resolved_name in _SLICER_PROFILES:
        content = _SLICER_PROFILES[resolved_name]
        profile_status = "detected"
        confidence = "High"
        found_names = {entry["name"] for entry in detected_slicers if entry["found"]}
        other_detected = sorted(found_names - {resolved_name})
        if other_detected:
            warnings.append(
                f"More than one supported slicer is detected locally ({resolved_name} and "
                f"{', '.join(other_detected)}) - this profile reflects {resolved_name} only, the "
                "first match in priority order."
            )
    else:
        content = _GENERIC_PROFILE
        profile_status = "not_detected"
        confidence = "Unknown" if resolved_name == "Unknown" else "Low"
        if resolved_name == "Unknown":
            warnings.append("No supported local slicer was detected - using a generic review checklist only.")
        else:
            warnings.append(f"{resolved_name!r} is not a slicer this repo has profile content for - using a generic review checklist only.")

    profile = {
        "slicer_name": resolved_name,
        "profile_status": profile_status,
        "known_capabilities": list(content["known_capabilities"]),
        "review_categories": list(content["review_categories"]),
        "printer_questions": list(content["printer_questions"]),
        "material_questions": list(content["material_questions"]),
        "multi_material_questions": list(content["multi_material_questions"]) if multi_material else [],
        "warnings": warnings,
        "limitations": limitations,
        "confidence": confidence,
    }
    return profile


def build_slicer_specific_checks(profile: dict[str, Any]) -> list[str]:
    """Flatten a `SlicerReviewProfile`'s printer/material/multi-material
    questions into one ordered "Additional Review Items" checklist -
    additive to (never a replacement of) `factory.slicer_intelligence`'s
    existing geometry/manufacturing checklist content.
    """
    checks: list[str] = []
    checks.extend(profile["printer_questions"])
    checks.extend(profile["material_questions"])
    checks.extend(profile["multi_material_questions"])
    return checks

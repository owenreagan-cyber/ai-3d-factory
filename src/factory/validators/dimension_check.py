"""Build-volume fit check against local printer config.

This never produces a hard FAIL by itself when the printer spec is marked
unverified in config/manufacturing/printers.json (the canonical printer
source - see docs/manufacturing-knowledge-base.md) - only WARN. Treat this
as advisory, not authoritative. See that file's per-printer
verification_note.
"""

from __future__ import annotations

from itertools import permutations


def check_build_volume_fit(bbox_mm: dict | None, printer: dict | None) -> dict:
    """Compare a bounding box (dict with x/y/z in mm) against a printer's build volume.

    Returns a check dict: {"name", "status", "detail"}.
    """
    name = "build_volume_fit"

    if bbox_mm is None:
        return {
            "name": name,
            "status": "WARN",
            "detail": "No bounding box available; skipped build volume fit check.",
        }

    if not printer:
        return {
            "name": name,
            "status": "WARN",
            "detail": "No printer config available; skipped build volume fit check.",
        }

    build_volume = printer.get("build_volume_mm")
    if not build_volume:
        return {
            "name": name,
            "status": "WARN",
            "detail": f"Printer {printer.get('display_name', '?')} has no build_volume_mm configured.",
        }

    verified = printer.get("verified", False)
    dims = (bbox_mm.get("x", 0.0), bbox_mm.get("y", 0.0), bbox_mm.get("z", 0.0))
    volume_dims = (build_volume.get("x", 0.0), build_volume.get("y", 0.0), build_volume.get("z", 0.0))

    fits = any(
        all(d <= v for d, v in zip(perm, volume_dims))
        for perm in permutations(dims)
    )

    verified_note = (
        "Printer spec is verified."
        if verified
        else "Printer spec is UNVERIFIED (placeholder values) - confirm before relying on this."
    )

    if fits:
        return {
            "name": name,
            "status": "WARN" if not verified else "PASS",
            "detail": (
                f"Bounding box {dims} mm fits within build volume {volume_dims} mm "
                f"for {printer.get('display_name', '?')} (some axis orientation). {verified_note}"
            ),
        }

    return {
        "name": name,
        "status": "WARN",
        "detail": (
            f"Bounding box {dims} mm does not fit within build volume {volume_dims} mm "
            f"for {printer.get('display_name', '?')} in any axis orientation. {verified_note} "
            "This is advisory only - re-check manually before assuming the part must be split."
        ),
    }

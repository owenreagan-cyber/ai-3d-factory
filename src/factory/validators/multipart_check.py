"""Sanity checks for a part_manifest.json describing a multi-part/multi-color project.

Phase 0/1 policy: prefer separate aligned STL files sharing one origin over
a single fused mesh for multi-color work (see docs/slicer-review-workflow.md).
This module only reads local files; it never fuses, aligns, or exports
anything itself.
"""

from __future__ import annotations

from pathlib import Path


def check_manifest(manifest: dict, manifest_dir: Path) -> list[dict]:
    """Return a list of check dicts ({"name", "status", "detail"}) for a part manifest."""
    checks: list[dict] = []
    parts = manifest.get("parts", [])

    if not parts:
        checks.append(
            {
                "name": "manifest_has_parts",
                "status": "WARN",
                "detail": "part_manifest.json has no parts listed yet.",
            }
        )
        return checks

    checks.append(
        {
            "name": "manifest_has_parts",
            "status": "PASS",
            "detail": f"{len(parts)} part(s) listed in manifest.",
        }
    )

    units = {p.get("export_units") for p in parts if p.get("export_units")}
    if len(units) > 1:
        checks.append(
            {
                "name": "consistent_export_units",
                "status": "WARN",
                "detail": f"Parts use mixed export_units: {sorted(units)}. Align units before assembly.",
            }
        )
    else:
        checks.append(
            {
                "name": "consistent_export_units",
                "status": "PASS" if units else "WARN",
                "detail": f"export_units: {sorted(units) if units else 'not set on any part'}.",
            }
        )

    missing_files = []
    for part in parts:
        file_path = part.get("file_path")
        if not file_path:
            missing_files.append(part.get("part_name", "<unnamed>"))
            continue
        resolved = (manifest_dir / file_path).resolve()
        if not resolved.is_file():
            missing_files.append(part.get("part_name", file_path))

    if missing_files:
        checks.append(
            {
                "name": "part_files_exist",
                "status": "WARN",
                "detail": f"Parts with missing/unresolved file_path: {missing_files}.",
            }
        )
    else:
        checks.append(
            {
                "name": "part_files_exist",
                "status": "PASS",
                "detail": "All part file_path entries resolve to existing files.",
            }
        )

    missing_transform_notes = [
        p.get("part_name", "<unnamed>") for p in parts if not p.get("transform_notes")
    ]
    if len(parts) > 1 and missing_transform_notes:
        checks.append(
            {
                "name": "shared_origin_documented",
                "status": "WARN",
                "detail": (
                    f"Parts missing transform_notes: {missing_transform_notes}. "
                    "Multi-part projects should document shared-origin alignment."
                ),
            }
        )
    else:
        checks.append(
            {
                "name": "shared_origin_documented",
                "status": "PASS",
                "detail": "transform_notes present where needed.",
            }
        )

    return checks

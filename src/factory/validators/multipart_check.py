"""Sanity checks for a part_manifest.json describing a multi-part/multi-color project.

Phase 0/1 policy: prefer separate aligned STL files sharing one origin over
a single fused mesh for multi-color work (see docs/slicer-review-workflow.md).
This module only reads local files; it never fuses, aligns, exports, or
otherwise manipulates geometry.
"""

from __future__ import annotations

from pathlib import Path


def check_manifest(
    manifest: dict, manifest_dir: Path, required_part_names: list[str] | None = None
) -> list[dict]:
    """Return a list of check dicts ({"name", "status", "detail"}) for a part manifest.

    `required_part_names`, if given (e.g. from build_plan.json's required_parts),
    enables an additional cross-check for parts that are planned but not yet
    present in the manifest.
    """
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
        if required_part_names:
            checks.append(
                {
                    "name": "missing_manifest_entries",
                    "status": "WARN",
                    "detail": f"Planned part(s) not yet in manifest: {sorted(required_part_names)}.",
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

    part_names = [p.get("part_name") for p in parts]
    seen: set[str] = set()
    duplicate_names = sorted({name for name in part_names if name and (name in seen or seen.add(name))})
    if duplicate_names:
        checks.append(
            {
                "name": "duplicate_part_names",
                "status": "FAIL",
                "detail": f"Duplicate part_name entries: {duplicate_names}. Merge or rename before proceeding.",
            }
        )
    else:
        checks.append(
            {
                "name": "duplicate_part_names",
                "status": "PASS",
                "detail": "No duplicate part_name entries.",
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
    file_paths = []
    for part in parts:
        file_path = part.get("file_path")
        if not file_path:
            missing_files.append(part.get("part_name", "<unnamed>"))
            continue
        file_paths.append(file_path)
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

    seen_paths: set[str] = set()
    duplicate_paths = sorted({p for p in file_paths if p in seen_paths or seen_paths.add(p)})
    if duplicate_paths:
        checks.append(
            {
                "name": "duplicate_outputs",
                "status": "FAIL",
                "detail": f"Multiple parts share the same file_path (would overwrite on export): {duplicate_paths}.",
            }
        )
    else:
        checks.append(
            {
                "name": "duplicate_outputs",
                "status": "PASS",
                "detail": "No two parts share the same file_path.",
            }
        )

    missing_cad_sources = [
        p.get("part_name", "<unnamed>")
        for p in parts
        if not (p.get("cad_source") or p.get("source_scad"))
    ]
    if missing_cad_sources:
        checks.append(
            {
                "name": "cad_sources_declared",
                "status": "WARN",
                "detail": (
                    f"Parts with no cad_source/source_scad recorded yet: {missing_cad_sources}. "
                    "Expected before CAD is generated; fill in once cad/ has source for this part."
                ),
            }
        )
    else:
        checks.append(
            {
                "name": "cad_sources_declared",
                "status": "PASS",
                "detail": "All parts have a cad_source/source_scad recorded.",
            }
        )

    invalid_quantities = [
        (p.get("part_name", "<unnamed>"), p.get("quantity"))
        for p in parts
        if "quantity" in p and (not isinstance(p.get("quantity"), int) or p.get("quantity") < 1)
    ]
    if invalid_quantities:
        checks.append(
            {
                "name": "quantities_valid",
                "status": "FAIL",
                "detail": f"Parts with invalid quantity (must be an integer >= 1): {invalid_quantities}.",
            }
        )
    else:
        checks.append(
            {
                "name": "quantities_valid",
                "status": "PASS",
                "detail": "All declared quantities are integers >= 1.",
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

    if len(parts) > 1:
        shared_origin_flags = {p.get("shared_origin") for p in parts if "shared_origin" in p}
        if not shared_origin_flags:
            checks.append(
                {
                    "name": "shared_origin_consistency",
                    "status": "WARN",
                    "detail": "Multi-part project but no part declares a shared_origin flag.",
                }
            )
        elif shared_origin_flags != {True}:
            checks.append(
                {
                    "name": "shared_origin_consistency",
                    "status": "WARN",
                    "detail": (
                        f"Multi-part project has inconsistent/false shared_origin flags: "
                        f"{sorted(str(v) for v in shared_origin_flags)}. All parts in one assembly "
                        "should share one origin."
                    ),
                }
            )
        else:
            checks.append(
                {
                    "name": "shared_origin_consistency",
                    "status": "PASS",
                    "detail": "All parts declare shared_origin: true.",
                }
            )

    if required_part_names:
        missing_entries = sorted(set(required_part_names) - {n for n in part_names if n})
        if missing_entries:
            checks.append(
                {
                    "name": "missing_manifest_entries",
                    "status": "WARN",
                    "detail": f"Planned part(s) not yet in manifest: {missing_entries}.",
                }
            )
        else:
            checks.append(
                {
                    "name": "missing_manifest_entries",
                    "status": "PASS",
                    "detail": "Every planned part has a manifest entry.",
                }
            )

    return checks

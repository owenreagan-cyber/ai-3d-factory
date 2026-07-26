"""Read-only local slicer discovery.

This module NEVER launches a slicer, never slices, never prints, and never
uploads anything. It only checks for known app bundle paths and PATH
binaries, mirroring ai-3d-factory-installer/scripts/check_slicers.sh.
"""

from __future__ import annotations

import shutil

SLICER_CANDIDATES = (
    {
        "name": "Bambu Studio",
        "app_paths": ("/Applications/BambuStudio.app", "/Applications/Bambu Studio.app"),
        "path_binary": "bambu-studio",
    },
    {
        "name": "OrcaSlicer",
        "app_paths": ("/Applications/OrcaSlicer.app",),
        "path_binary": "orcaslicer",
    },
    {
        "name": "PrusaSlicer",
        "app_paths": ("/Applications/PrusaSlicer.app", "/Applications/Original Prusa Drivers/PrusaSlicer.app"),
        "path_binary": "prusa-slicer",
    },
)


def probe_slicers() -> list[dict]:
    """Return a list of {"name", "found", "method", "path"} for known slicers.

    Read-only discovery only: checks /Applications and PATH. Never launches
    or configures anything.
    """
    results = []
    for candidate in SLICER_CANDIDATES:
        found_path = None
        method = None

        for app_path in candidate["app_paths"]:
            from pathlib import Path

            if Path(app_path).is_dir():
                found_path = app_path
                method = "applications_folder"
                break

        if not found_path:
            binary = shutil.which(candidate["path_binary"])
            if binary:
                found_path = binary
                method = "path_binary"

        results.append(
            {
                "name": candidate["name"],
                "found": found_path is not None,
                "method": method,
                "path": found_path,
            }
        )

    return results

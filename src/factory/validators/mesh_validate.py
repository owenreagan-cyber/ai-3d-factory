"""Local geometry sanity checks using trimesh.

This performs local, offline checks only. It never slices, never uploads,
and never claims a model is print-ready. See AGENT.md.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from factory.project_store import utc_now_iso
from factory.validators.dimension_check import check_build_volume_fit

RECOGNIZED_EXTENSIONS = {".stl", ".obj", ".ply", ".3mf", ".glb", ".gltf", ".off"}

BASE_LIMITATIONS = [
    "This is a local geometry sanity check only. It does not simulate slicing, "
    "supports, wall thickness, or printer-specific behavior.",
    "Watertightness and winding-consistency checks passing does not mean a model "
    "is print-ready. Human slicer review is always required.",
    "Units are assumed to be millimeters, matching common 3D-printing convention; "
    "this is not independently verified from the file itself.",
]


def _overall_status(checks: list[dict]) -> str:
    statuses = {c["status"] for c in checks}
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "PASS"


def _summary_message(overall_status: str) -> str:
    if overall_status == "FAIL":
        return "Geometry checks failed; fix the underlying file/mesh issue before requesting human slicer review."
    return "Geometry sanity check passed; human slicer review required."


def validate_mesh(file_path: Path, printer: dict | None = None) -> dict:
    file_path = Path(file_path)
    checks: list[dict] = []
    mesh_stats: dict[str, Any] = {
        "is_scene": None,
        "geometry_count": 0,
        "vertex_count": None,
        "face_count": None,
        "bounding_box_mm": None,
        "volume_mm3": None,
        "is_watertight": None,
        "winding_consistent": None,
    }
    limitations = list(BASE_LIMITATIONS)

    exists_readable = file_path.is_file() and os.access(file_path, os.R_OK)
    checks.append(
        {
            "name": "file_exists_readable",
            "status": "PASS" if exists_readable else "FAIL",
            "detail": str(file_path) if exists_readable else f"File not found or not readable: {file_path}",
        }
    )

    if not exists_readable:
        overall = _overall_status(checks)
        return {
            "source_file": str(file_path),
            "generated_at": utc_now_iso(),
            "overall_status": overall,
            "checks": checks,
            "mesh_stats": mesh_stats,
            "summary_message": _summary_message(overall),
            "limitations": limitations,
        }

    ext = file_path.suffix.lower()
    checks.append(
        {
            "name": "file_extension_recognized",
            "status": "PASS" if ext in RECOGNIZED_EXTENSIONS else "WARN",
            "detail": f"Extension: {ext or '(none)'}",
        }
    )

    try:
        import trimesh  # local import: heavy dependency, only needed here
    except ImportError as exc:
        checks.append(
            {
                "name": "trimesh_available",
                "status": "FAIL",
                "detail": f"trimesh is not installed/importable: {exc}",
            }
        )
        overall = _overall_status(checks)
        limitations.append("trimesh is unavailable in this environment; no mesh-level checks were run.")
        return {
            "source_file": str(file_path),
            "generated_at": utc_now_iso(),
            "overall_status": overall,
            "checks": checks,
            "mesh_stats": mesh_stats,
            "summary_message": _summary_message(overall),
            "limitations": limitations,
        }

    try:
        loaded = trimesh.load(str(file_path))
    except Exception as exc:  # noqa: BLE001 - trimesh raises many exception types
        checks.append(
            {
                "name": "trimesh_load",
                "status": "FAIL",
                "detail": f"trimesh could not load this file: {exc}",
            }
        )
        overall = _overall_status(checks)
        return {
            "source_file": str(file_path),
            "generated_at": utc_now_iso(),
            "overall_status": overall,
            "checks": checks,
            "mesh_stats": mesh_stats,
            "summary_message": _summary_message(overall),
            "limitations": limitations,
        }

    checks.append({"name": "trimesh_load", "status": "PASS", "detail": "File loaded successfully."})

    is_scene = isinstance(loaded, trimesh.Scene)
    mesh_stats["is_scene"] = is_scene

    if is_scene:
        geometries = list(loaded.geometry.values())
        mesh_stats["geometry_count"] = len(geometries)
        if not geometries:
            checks.append(
                {
                    "name": "scene_has_geometry",
                    "status": "FAIL",
                    "detail": "Scene contains no geometry.",
                }
            )
            overall = _overall_status(checks)
            return {
                "source_file": str(file_path),
                "generated_at": utc_now_iso(),
                "overall_status": overall,
                "checks": checks,
                "mesh_stats": mesh_stats,
                "summary_message": _summary_message(overall),
                "limitations": limitations,
            }
        if len(geometries) > 1:
            limitations.append(
                f"Source file contains {len(geometries)} separate geometries; "
                "aggregate stats below combine all of them into one bounding box/volume."
            )
        mesh = trimesh.util.concatenate(geometries) if len(geometries) > 1 else geometries[0]
        checks.append(
            {
                "name": "scene_vs_mesh",
                "status": "PASS",
                "detail": f"File is a scene with {len(geometries)} geometry object(s).",
            }
        )
    else:
        mesh_stats["geometry_count"] = 1
        mesh = loaded
        checks.append({"name": "scene_vs_mesh", "status": "PASS", "detail": "File is a single mesh object."})

    vertex_count = int(len(mesh.vertices)) if hasattr(mesh, "vertices") else None
    face_count = int(len(mesh.faces)) if hasattr(mesh, "faces") else None
    mesh_stats["vertex_count"] = vertex_count
    mesh_stats["face_count"] = face_count

    checks.append(
        {
            "name": "vertex_face_counts",
            "status": "PASS" if (vertex_count and face_count) else "FAIL",
            "detail": f"vertices={vertex_count}, faces={face_count}",
        }
    )

    bbox_mm = None
    try:
        extents = mesh.bounding_box.extents
        bbox_mm = {"x": float(extents[0]), "y": float(extents[1]), "z": float(extents[2])}
        mesh_stats["bounding_box_mm"] = bbox_mm
        checks.append(
            {
                "name": "bounding_box",
                "status": "PASS",
                "detail": f"{bbox_mm['x']:.2f} x {bbox_mm['y']:.2f} x {bbox_mm['z']:.2f} mm",
            }
        )
    except Exception as exc:  # noqa: BLE001
        checks.append({"name": "bounding_box", "status": "WARN", "detail": f"Could not compute bounding box: {exc}"})

    is_watertight = bool(getattr(mesh, "is_watertight", False))
    mesh_stats["is_watertight"] = is_watertight
    checks.append(
        {
            "name": "watertight",
            "status": "PASS" if is_watertight else "WARN",
            "detail": "Mesh is watertight." if is_watertight else "Mesh is NOT watertight (may have holes/gaps).",
        }
    )

    if is_watertight:
        try:
            volume = float(mesh.volume)
            mesh_stats["volume_mm3"] = volume
            checks.append({"name": "volume", "status": "PASS", "detail": f"{volume:.2f} mm^3"})
        except Exception as exc:  # noqa: BLE001
            checks.append({"name": "volume", "status": "WARN", "detail": f"Could not compute volume: {exc}"})
    else:
        checks.append(
            {
                "name": "volume",
                "status": "WARN",
                "detail": "Volume requires a watertight mesh; skipped.",
            }
        )

    try:
        winding_consistent = bool(mesh.is_winding_consistent)
        mesh_stats["winding_consistent"] = winding_consistent
        checks.append(
            {
                "name": "winding_consistency",
                "status": "PASS" if winding_consistent else "WARN",
                "detail": "Face winding is consistent." if winding_consistent else "Face winding is inconsistent.",
            }
        )
    except Exception as exc:  # noqa: BLE001
        checks.append({"name": "winding_consistency", "status": "WARN", "detail": f"Could not check winding: {exc}"})

    checks.append(check_build_volume_fit(bbox_mm, printer))
    if printer and not printer.get("verified", False):
        limitations.append(
            f"Printer '{printer.get('display_name', '?')}' build volume is an unverified placeholder "
            "(see config/printers.json)."
        )

    overall = _overall_status(checks)
    return {
        "source_file": str(file_path),
        "generated_at": utc_now_iso(),
        "overall_status": overall,
        "checks": checks,
        "mesh_stats": mesh_stats,
        "summary_message": _summary_message(overall),
        "limitations": limitations,
    }

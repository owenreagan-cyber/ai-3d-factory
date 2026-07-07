"""Project-level visual preview package.

Aggregates a project's existing CAD/STL/render/manifest state into a single
`preview_package/index.json` (machine-readable) and `preview_package/
preview_report.md` (human-readable), for a human to visually sanity-check a
project and for a future dashboard/launcher (see docs/product-vision.md) to
consume. This module never renders new images, never invokes OpenSCAD or
CadQuery, never exports STLs, and never contacts a printer/slicer/network - it only reads
files already on disk and references them by relative path (it never copies
render images). See docs/manufacturing-knowledge-base.md and AGENT.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import project_store

PREVIEW_PACKAGE_DIRNAME = "preview_package"
INDEX_FILENAME = "index.json"
REPORT_FILENAME = "preview_report.md"

REQUIRED_SAFETY_LINES = (
    "Human visual inspection required.",
    "Human slicer review required.",
    "Project is NOT print-ready.",
)

HUMAN_VISUAL_INSPECTION_CHECKLIST = (
    "Does the preview match the intended object?",
    "Are all expected parts visible?",
    "Are text/labels readable?",
    "Are multipart components visually distinct?",
    "Are colors/materials represented or clearly marked unknown?",
    "Are any renders missing?",
    "Are any previews stale?",
    "Is slicer review still required?",
)


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return project_store.load_json(path)
    except Exception:  # noqa: BLE001 - malformed JSON degrades to "missing", not a crash
        return None


def _render_stem_for(mesh_stem: str) -> str:
    return f"{mesh_stem}_preview"


def gather_preview_data(project_dir: Path) -> dict[str, Any]:
    """Read a project's existing files and compute the preview package index.

    Read-only: never writes, renders, exports, or contacts anything.
    """
    project_dir = Path(project_dir)

    brief = _safe_load_json(project_dir / "brief.json") or {}
    build_plan = _safe_load_json(project_dir / "build_plan.json") or {}
    manifest = _safe_load_json(project_dir / "part_manifest.json") or {}
    parts = manifest.get("parts", []) if isinstance(manifest.get("parts"), list) else []

    cad_dir = project_dir / "cad"
    stl_dir = project_dir / "stl"
    renders_dir = project_dir / "renders"

    cad_files = (
        sorted(p.name for p in cad_dir.iterdir() if p.is_file() and p.suffix in (".scad", ".py"))
        if cad_dir.is_dir()
        else []
    )
    mesh_files = sorted(p.name for p in stl_dir.glob("*.stl")) if stl_dir.is_dir() else []
    render_files = sorted(p.name for p in renders_dir.glob("*.png")) if renders_dir.is_dir() else []
    render_stems = {Path(name).stem for name in render_files}

    missing_visual_artifacts: list[str] = []
    stale_previews: list[str] = []

    if parts:
        for part in parts:
            part_name = part.get("part_name", "<unnamed>")
            file_path = part.get("file_path")
            mesh_path = (project_dir / file_path) if file_path else None

            if not file_path or not mesh_path.is_file():
                missing_visual_artifacts.append(
                    f"Missing STL for part {part_name!r} (expected {file_path or 'no file_path set'})."
                )
                continue

            mesh_stem = Path(file_path).stem
            render_name = f"{_render_stem_for(mesh_stem)}.png"
            render_path = renders_dir / render_name
            if not render_path.is_file():
                missing_visual_artifacts.append(
                    f"Missing render for part {part_name!r} (expected renders/{render_name})."
                )
                continue

            if render_path.stat().st_mtime + 1e-6 < mesh_path.stat().st_mtime:
                stale_previews.append(
                    f"renders/{render_name} is older than stl/{Path(file_path).name} for part {part_name!r} "
                    "- re-run `factory render` after the STL changed."
                )
    else:
        for mesh_name in mesh_files:
            mesh_stem = Path(mesh_name).stem
            render_name = f"{_render_stem_for(mesh_stem)}.png"
            render_path = renders_dir / render_name
            mesh_path = stl_dir / mesh_name
            if not render_path.is_file():
                missing_visual_artifacts.append(f"Missing render for stl/{mesh_name} (expected renders/{render_name}).")
                continue
            if render_path.stat().st_mtime + 1e-6 < mesh_path.stat().st_mtime:
                stale_previews.append(
                    f"renders/{render_name} is older than stl/{mesh_name} - re-run `factory render` after the STL changed."
                )

        if not mesh_files and cad_files:
            missing_visual_artifacts.append(
                f"{len(cad_files)} CAD source file(s) present but no STL exported yet - "
                "run the export commands in slicer_review/openscad_export_instructions.md and/or "
                "slicer_review/cadquery_export_instructions.md (whichever applies)."
            )
        elif not mesh_files and not cad_files:
            missing_visual_artifacts.append("No CAD source, STL, or render files exist yet for this project.")

    orphaned_renders = sorted(
        name
        for name in render_files
        if Path(name).stem.removesuffix("_preview") not in {Path(m).stem for m in mesh_files}
    )

    manifest_parts_summary = [
        {
            "part_name": part.get("part_name"),
            "file_path": part.get("file_path"),
            "material": part.get("material"),
            "color": part.get("color"),
            "role": part.get("role"),
        }
        for part in parts
    ]

    return {
        "project_name": brief.get("project_name") or project_dir.name,
        "project_dir": str(project_dir),
        "generated_at": project_store.utc_now_iso(),
        "project_status": brief.get("status", "idea"),
        "target_printer": build_plan.get("target_printer"),
        "selected_manufacturing_option": build_plan.get("selected_manufacturing_option"),
        "cad_files": [f"cad/{name}" for name in cad_files],
        "mesh_files": [f"stl/{name}" for name in mesh_files],
        "render_files": [f"renders/{name}" for name in render_files],
        "manifest_parts": manifest_parts_summary,
        "multipart_state": {"multi_part": len(parts) > 1, "part_count": len(parts)},
        "missing_visual_artifacts": missing_visual_artifacts,
        "stale_previews": stale_previews,
        "orphaned_renders": [f"renders/{name}" for name in orphaned_renders],
        "human_visual_inspection_checklist": list(HUMAN_VISUAL_INSPECTION_CHECKLIST),
        "notes": [
            "This index only references existing local files by relative path; it never copies renders "
            "or exports/generates new geometry.",
            "Human visual inspection required.",
            "Human slicer review required.",
            "Project is NOT print-ready.",
        ],
    }


def build_markdown_report(index: dict[str, Any]) -> str:
    """Render gather_preview_data()'s index into a human-readable Markdown report."""
    lines: list[str] = []
    lines.append(f"# Preview report: {index['project_name']}")
    lines.append("")
    lines.append(f"Generated: {index['generated_at']}")
    lines.append(f"Project status: `{index['project_status']}`")

    target_printer = index.get("target_printer") or {}
    printer_label = target_printer.get("display_name") or "(not planned yet)"
    lines.append(f"Target printer: {printer_label}")
    lines.append(f"Selected manufacturing option: {index.get('selected_manufacturing_option')!r}")
    lines.append("")

    lines.append("## Visual artifacts")
    lines.append("")
    lines.append(f"- CAD source files ({len(index['cad_files'])}):")
    for f in index["cad_files"]:
        lines.append(f"  - `{f}`")
    if not index["cad_files"]:
        lines.append("  - (none)")
    lines.append(f"- Mesh/STL files ({len(index['mesh_files'])}):")
    for f in index["mesh_files"]:
        lines.append(f"  - `{f}`")
    if not index["mesh_files"]:
        lines.append("  - (none)")
    lines.append(f"- Render/preview images ({len(index['render_files'])}):")
    for f in index["render_files"]:
        lines.append(f"  - `{f}`")
    if not index["render_files"]:
        lines.append("  - (none)")
    lines.append("")

    lines.append("## Manifest parts")
    lines.append("")
    if index["manifest_parts"]:
        for part in index["manifest_parts"]:
            lines.append(
                f"- **{part.get('part_name')}** - role: {part.get('role')}, "
                f"material: {part.get('material')}, color: {part.get('color')}, "
                f"file: `{part.get('file_path')}`"
            )
    else:
        lines.append("- (no parts in part_manifest.json)")
    lines.append("")
    lines.append(
        f"Multipart state: multi_part={index['multipart_state']['multi_part']}, "
        f"part_count={index['multipart_state']['part_count']}"
    )
    lines.append("")

    lines.append("## Missing visual artifacts")
    lines.append("")
    if index["missing_visual_artifacts"]:
        lines.extend(f"- {item}" for item in index["missing_visual_artifacts"])
    else:
        lines.append("- None detected.")
    lines.append("")

    lines.append("## Stale previews")
    lines.append("")
    if index["stale_previews"]:
        lines.extend(f"- {item}" for item in index["stale_previews"])
    else:
        lines.append("- None detected.")
    if index.get("orphaned_renders"):
        lines.append("")
        lines.append("Render images with no matching STL currently on disk (kept for reference, not deleted):")
        lines.extend(f"- `{f}`" for f in index["orphaned_renders"])
    lines.append("")

    lines.append("## Human visual inspection checklist")
    lines.append("")
    lines.append("This checklist is advisory only - checking these boxes does not approve, validate, or")
    lines.append("advance this project's status. A human must look at the actual renders/STLs.")
    lines.append("")
    for item in index["human_visual_inspection_checklist"]:
        lines.append(f"- [ ] {item}")
    lines.append("")

    lines.append("---")
    lines.append("")
    for safety_line in REQUIRED_SAFETY_LINES:
        lines.append(safety_line)
    lines.append("")

    return "\n".join(lines)


def preview_package_paths(project_dir: Path) -> tuple[Path, Path]:
    package_dir = Path(project_dir) / PREVIEW_PACKAGE_DIRNAME
    return package_dir / INDEX_FILENAME, package_dir / REPORT_FILENAME


def write_preview_package(project_dir: Path) -> dict[str, Any]:
    """Build (or refresh) projects/<slug>/preview_package/{index.json,preview_report.md}.

    Only ever writes those two files - never touches cad/, stl/, renders/,
    or any other project file, and never renders/exports/generates geometry.
    """
    project_dir = Path(project_dir)
    index = gather_preview_data(project_dir)
    report_markdown = build_markdown_report(index)

    index_path, report_path = preview_package_paths(project_dir)
    project_store.save_json(index_path, index)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_markdown, encoding="utf-8")

    return {"index": index, "index_path": index_path, "report_path": report_path}

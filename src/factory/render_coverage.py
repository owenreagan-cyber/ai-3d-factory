"""Local, read-only render coverage inspection for a single project.

Compares `stl/*.stl` against `renders/*.png` for one project directory,
using the same `<mesh_stem>_preview.png` naming convention
`factory.preview_package` already uses, so a project's render-coverage
picture is consistent everywhere it's shown (`factory render-coverage`,
`preview_package/index.json`, and the preview board).

This module never renders an image, never invokes a slicer, OpenSCAD,
CadQuery, or Blender, and never contacts a network or printer - it is a
pure filesystem read (`Path.glob` + `Path.stat`). See
docs/render-coverage.md and AGENT.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

RENDER_SUFFIX = "_preview"

NOTES = (
    "Read-only comparison of stl/*.stl against renders/*.png by filename stem "
    "(<name>.stl <-> renders/<name>_preview.png).",
    "This never renders anything, never invokes a slicer/OpenSCAD/CadQuery/Blender, "
    "and never contacts a network or printer.",
    "Render coverage is advisory only - it does not approve anything or mark anything print-ready.",
)


def _render_name_for(mesh_stem: str) -> str:
    return f"{mesh_stem}{RENDER_SUFFIX}.png"


def compute_render_coverage(project_dir: Path) -> dict[str, Any]:
    """Read-only render/mesh coverage summary for one project.

    Deterministic given unchanged files on disk: calling this twice in a
    row without any filesystem change returns equal dicts. Never writes,
    renders, exports, or contacts anything.
    """
    project_dir = Path(project_dir)
    stl_dir = project_dir / "stl"
    renders_dir = project_dir / "renders"

    mesh_names = sorted(p.name for p in stl_dir.glob("*.stl")) if stl_dir.is_dir() else []
    render_names = sorted(p.name for p in renders_dir.glob("*.png")) if renders_dir.is_dir() else []
    mesh_stems = {Path(name).stem for name in mesh_names}

    covered: list[dict[str, Any]] = []
    missing_renders: list[str] = []
    stale_renders: list[str] = []

    for mesh_name in mesh_names:
        mesh_stem = Path(mesh_name).stem
        render_name = _render_name_for(mesh_stem)
        mesh_path = stl_dir / mesh_name
        render_path = renders_dir / render_name

        if not render_path.is_file():
            missing_renders.append(f"stl/{mesh_name}")
            continue

        is_stale = render_path.stat().st_mtime + 1e-6 < mesh_path.stat().st_mtime
        if is_stale:
            stale_renders.append(f"renders/{render_name}")
        covered.append(
            {
                "mesh": f"stl/{mesh_name}",
                "render": f"renders/{render_name}",
                "stale": is_stale,
            }
        )

    orphan_renders = sorted(
        f"renders/{name}"
        for name in render_names
        if Path(name).stem.removesuffix(RENDER_SUFFIX) not in mesh_stems
    )

    total_meshes = len(mesh_names)
    total_renders = len(render_names)
    all_meshes_have_renders = total_meshes > 0 and not missing_renders
    visually_complete_for_slicer_review = all_meshes_have_renders and not stale_renders

    return {
        "project_dir": str(project_dir),
        "mesh_files": [f"stl/{name}" for name in mesh_names],
        "render_files": [f"renders/{name}" for name in render_names],
        "covered": covered,
        "missing_renders": missing_renders,
        "orphan_renders": orphan_renders,
        "stale_renders": stale_renders,
        "total_meshes": total_meshes,
        "total_renders": total_renders,
        "covered_count": len(covered),
        "all_meshes_have_renders": all_meshes_have_renders,
        "visually_complete_for_slicer_review": visually_complete_for_slicer_review,
        "notes": list(NOTES),
    }


def build_text_report(coverage: dict[str, Any]) -> list[str]:
    """Render `compute_render_coverage()`'s output into human-readable report lines."""
    lines: list[str] = []
    lines.append(f"project directory: {coverage['project_dir']}")
    lines.append(f"STL files: {coverage['total_meshes']}")
    lines.append(f"render files: {coverage['total_renders']}")
    lines.append(f"meshes with a matching render: {coverage['covered_count']}/{coverage['total_meshes']}")

    if coverage["missing_renders"]:
        lines.append(f"missing renders ({len(coverage['missing_renders'])}):")
        for item in coverage["missing_renders"]:
            lines.append(f"  - {item}")
    else:
        lines.append("missing renders: none")

    if coverage["stale_renders"]:
        lines.append(f"stale renders ({len(coverage['stale_renders'])}):")
        for item in coverage["stale_renders"]:
            lines.append(f"  - {item}")
    else:
        lines.append("stale renders: none detected")

    if coverage["orphan_renders"]:
        lines.append(f"orphan renders, no matching STL ({len(coverage['orphan_renders'])}):")
        for item in coverage["orphan_renders"]:
            lines.append(f"  - {item}")
    else:
        lines.append("orphan renders: none")

    lines.append(f"all meshes have a render: {coverage['all_meshes_have_renders']}")
    lines.append(f"visually complete for human slicer review: {coverage['visually_complete_for_slicer_review']}")
    lines.append("")
    lines.append("Render coverage is advisory only - it does not approve anything or mark anything print-ready.")
    lines.append("Human visual inspection required.")
    lines.append("Human slicer review required.")
    lines.append("Project is NOT print-ready.")
    return lines


def missing_and_stale_mesh_paths(coverage: dict[str, Any]) -> list[str]:
    """Return project-relative `stl/<name>.stl` paths that need a (re-)render.

    Combines `missing_renders` (no render at all) and `stale_renders`
    (render exists but is older than its mesh) into one de-duplicated,
    deterministic list, ordered missing-then-stale. This is the single
    shared source both `plan_render_commands()` (Phase 9) and
    `factory.preview_board`'s suggested actions (Phase 10) build on, so
    the two never drift apart.
    """
    stems_to_render: list[str] = list(coverage["missing_renders"])
    for render_path in coverage["stale_renders"]:
        # A stale render's source mesh is the same stem, under stl/.
        mesh_name = Path(render_path).stem.removesuffix(RENDER_SUFFIX) + ".stl"
        stems_to_render.append(f"stl/{mesh_name}")

    # Stable de-duplication, preserving the missing-then-stale order above.
    seen: set[str] = set()
    result: list[str] = []
    for mesh_path in stems_to_render:
        if mesh_path in seen:
            continue
        seen.add(mesh_path)
        result.append(mesh_path)
    return result


def plan_render_commands(coverage: dict[str, Any]) -> list[str]:
    """Return the local `factory render <stl_path>` commands a human could run.

    Purely a list of suggestions built from `missing_and_stale_mesh_paths()`
    - never executes anything itself.
    """
    return [f"factory render {mesh_path}" for mesh_path in missing_and_stale_mesh_paths(coverage)]

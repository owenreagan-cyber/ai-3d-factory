"""Local preview rendering with trimesh + matplotlib. No Blender, no GPU required.

This produces a quick visual sanity-check image only - not a slicer-accurate
render.
"""

from __future__ import annotations

from pathlib import Path


def render_preview(mesh_path: Path, output_path: Path) -> dict:
    """Render a simple isometric preview PNG of `mesh_path` to `output_path`.

    Returns {"status": PASS|WARN|FAIL, "detail": str, "output_path": str|None}.
    """
    mesh_path = Path(mesh_path)
    output_path = Path(output_path)

    if not mesh_path.is_file():
        return {"status": "FAIL", "detail": f"File not found: {mesh_path}", "output_path": None}

    try:
        import trimesh
    except ImportError as exc:
        return {"status": "FAIL", "detail": f"trimesh is not installed/importable: {exc}", "output_path": None}

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    except ImportError as exc:
        return {"status": "FAIL", "detail": f"matplotlib is not installed/importable: {exc}", "output_path": None}

    try:
        loaded = trimesh.load(str(mesh_path))
    except Exception as exc:  # noqa: BLE001
        return {"status": "FAIL", "detail": f"trimesh could not load this file: {exc}", "output_path": None}

    if isinstance(loaded, trimesh.Scene):
        geometries = list(loaded.geometry.values())
        if not geometries:
            return {"status": "FAIL", "detail": "Scene contains no geometry.", "output_path": None}
        mesh = trimesh.util.concatenate(geometries) if len(geometries) > 1 else geometries[0]
    else:
        mesh = loaded

    if not hasattr(mesh, "vertices") or not hasattr(mesh, "faces") or len(mesh.faces) == 0:
        return {"status": "FAIL", "detail": "Mesh has no renderable faces.", "output_path": None}

    try:
        fig = plt.figure(figsize=(6, 6))
        ax = fig.add_subplot(111, projection="3d")

        triangles = mesh.vertices[mesh.faces]
        collection = Poly3DCollection(triangles, facecolor="#b0b8c1", edgecolor="#2b2f36", linewidths=0.1)
        ax.add_collection3d(collection)

        bounds = mesh.bounds
        center = bounds.mean(axis=0)
        extent = (bounds[1] - bounds[0]).max() / 2 or 1.0
        ax.set_xlim(center[0] - extent, center[0] + extent)
        ax.set_ylim(center[1] - extent, center[1] + extent)
        ax.set_zlim(center[2] - extent, center[2] + extent)

        ax.view_init(elev=30, azim=45)
        ax.set_axis_off()
        ax.set_title(mesh_path.name, fontsize=10)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
    except Exception as exc:  # noqa: BLE001
        return {"status": "FAIL", "detail": f"Rendering failed: {exc}", "output_path": None}

    return {
        "status": "PASS",
        "detail": f"Preview rendered to {output_path}. This is a sanity-check render, not a slicer-accurate preview.",
        "output_path": str(output_path),
    }

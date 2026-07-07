"""Local, static, multi-project visual preview board.

Aggregates every project under a `projects_root` directory into one static
board (`preview_board/index.json` + `preview_board/index.html`) for a human
(Owen) to visually sanity-check project state across the whole workspace at
a glance, before trusting any generated CAD/STL output. This is a read-mostly
aggregator on top of `factory.preview_package` - it reuses
`gather_preview_data()` for the per-project file scan instead of duplicating
it, and prefers an existing `preview_package/index.json` when one is already
on disk.

This module never generates CAD, renders images, exports STLs, runs
OpenSCAD, runs CadQuery, invokes a slicer, launches Blender, contacts a
network, or contacts a printer. The only files it writes are
`preview_board/index.json` and `preview_board/index.html` under the given
output directory - it never touches `brief.json`, `build_plan.json`,
`part_manifest.json`, or any file inside an individual project. See
docs/preview-board.md and AGENT.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import preview_package, project_store

BOARD_DIRNAME = "preview_board"
INDEX_FILENAME = "index.json"
HTML_FILENAME = "index.html"

VISUAL_READINESS_STATES = (
    "needs_brief",
    "cad_source_ready",
    "needs_stl_export",
    "needs_render",
    "slicer_review_ready",
    "blocked_or_incomplete",
)

REQUIRED_SAFETY_LINES = (
    "Local static preview only - no server, no cloud, no printer/slicer communication.",
    "This is a visual inspection aid, not an approval and not a print-readiness signal.",
    "Human visual inspection required.",
    "Human slicer review required.",
    "No project shown here is print-ready.",
)


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return project_store.load_json(path)
    except Exception:  # noqa: BLE001 - malformed JSON degrades to "missing/unreadable", not a crash
        return None


def discover_projects(projects_root: Path) -> list[Path]:
    """List immediate subdirectories of `projects_root` treated as projects.

    Read-only directory listing. Skips hidden directories (leading '.') and
    this module's own `preview_board` output directory, so re-running the
    board command against its own output doesn't treat the board as a project.
    """
    projects_root = Path(projects_root)
    if not projects_root.is_dir():
        return []
    return sorted(
        (p for p in projects_root.iterdir() if p.is_dir() and not p.name.startswith(".") and p.name != BOARD_DIRNAME),
        key=lambda p: p.name,
    )


def _load_or_compute_preview_index(project_dir: Path) -> tuple[dict[str, Any], bool]:
    """Return (index_data, preview_package_existed_on_disk).

    Prefers an existing `preview_package/index.json`; falls back to
    `preview_package.gather_preview_data()` (also read-only - it never
    writes) when no package exists yet or the existing one is unreadable.
    """
    index_path, _ = preview_package.preview_package_paths(project_dir)
    existing = _safe_load_json(index_path)
    if existing is not None:
        return existing, True
    return preview_package.gather_preview_data(project_dir), False


def classify_visual_readiness(
    *,
    brief_status: str,
    manifest_status: str,
    cad_files: list[str],
    mesh_files: list[str],
    render_files: list[str],
    missing_visual_artifacts: list[str],
    stale_previews: list[str],
) -> str:
    """Deterministically classify a project's visual readiness.

    `brief_status`/`manifest_status` are each "missing", "unreadable", or
    "ok". Mirrors the "X_ready describes what's just been reached, next step
    implied" naming convention `project_store.PROJECT_STATUSES` already
    uses (e.g. `slicer_review_ready` there means "preview rendered, ready
    for slicer review" - same meaning here). Never returns/implies
    `human_approved` or `print_ready` - those aren't visual-readiness states
    and are never computed by this module.
    """
    if brief_status == "missing":
        return "needs_brief"
    if brief_status == "unreadable" or manifest_status == "unreadable":
        return "blocked_or_incomplete"
    if not cad_files and not mesh_files:
        return "cad_source_ready"
    if not mesh_files:
        return "needs_stl_export"
    if not render_files:
        return "needs_render"
    if missing_visual_artifacts or stale_previews:
        return "blocked_or_incomplete"
    return "slicer_review_ready"


def summarize_project(project_dir: Path, *, projects_root: Path | None = None) -> dict[str, Any]:
    """Read one project's existing files and summarize it for the board.

    Read-only: never writes, generates, renders, exports, or contacts
    anything. Only reads `brief.json`, `build_plan.json`, and whatever
    `preview_package.gather_preview_data()`/an existing
    `preview_package/index.json` already read.
    """
    project_dir = Path(project_dir)

    brief_path = project_dir / "brief.json"
    manifest_path = project_dir / "part_manifest.json"
    build_plan_path = project_dir / "build_plan.json"

    brief_status = "missing" if not brief_path.is_file() else ("ok" if _safe_load_json(brief_path) is not None else "unreadable")
    manifest_status = "missing" if not manifest_path.is_file() else ("ok" if _safe_load_json(manifest_path) is not None else "unreadable")
    build_plan = _safe_load_json(build_plan_path) or {}

    index, preview_package_exists = _load_or_compute_preview_index(project_dir)

    cad_files = index.get("cad_files", [])
    mesh_files = index.get("mesh_files", [])
    render_files = index.get("render_files", [])
    missing_visual_artifacts = index.get("missing_visual_artifacts", [])
    stale_previews = index.get("stale_previews", [])

    warnings: list[str] = []
    if brief_status == "missing":
        warnings.append("brief.json is missing.")
    elif brief_status == "unreadable":
        warnings.append("brief.json exists but could not be parsed as JSON.")
    if manifest_status == "missing":
        warnings.append("part_manifest.json is missing.")
    elif manifest_status == "unreadable":
        warnings.append("part_manifest.json exists but could not be parsed as JSON.")
    if not preview_package_exists:
        warnings.append(
            "No preview_package/index.json found - this summary was computed on the fly "
            "(read-only). Run `factory preview-project` to persist it."
        )
    warnings.extend(missing_visual_artifacts)
    warnings.extend(stale_previews)

    project_name = index.get("project_name") or project_dir.name

    try:
        rel_dir = str(project_dir.resolve().relative_to(Path(projects_root).resolve())) if projects_root else project_dir.name
    except ValueError:
        rel_dir = project_dir.name

    visual_readiness_state = classify_visual_readiness(
        brief_status=brief_status,
        manifest_status=manifest_status,
        cad_files=cad_files,
        mesh_files=mesh_files,
        render_files=render_files,
        missing_visual_artifacts=missing_visual_artifacts,
        stale_previews=stale_previews,
    )

    return {
        "project_name": project_name,
        "project_dir": rel_dir,
        "slug": project_dir.name,
        "brief_exists": brief_status != "missing",
        "brief_status": index.get("project_status") if brief_status == "ok" else None,
        "manufacturing_status": build_plan.get("status") if build_plan else None,
        "selected_manufacturing_option": index.get("selected_manufacturing_option"),
        "manifest_exists": manifest_status != "missing",
        "preview_package_exists": preview_package_exists,
        "cad_files": list(cad_files),
        "mesh_files": list(mesh_files),
        "render_files": list(render_files),
        "visual_readiness_state": visual_readiness_state,
        "warnings": warnings,
    }


def gather_board_data(projects_root: Path) -> dict[str, Any]:
    """Read every project under `projects_root` and compute the board index.

    Read-only: never writes, generates, renders, exports, or contacts
    anything.
    """
    projects_root = Path(projects_root)
    project_dirs = discover_projects(projects_root)
    projects = [summarize_project(p, projects_root=projects_root) for p in project_dirs]

    state_counts: dict[str, int] = {state: 0 for state in VISUAL_READINESS_STATES}
    for project in projects:
        state_counts[project["visual_readiness_state"]] += 1

    return {
        "generated_at": project_store.utc_now_iso(),
        "projects_root": str(projects_root),
        "project_count": len(projects),
        "state_counts": state_counts,
        "projects": projects,
        "notes": list(REQUIRED_SAFETY_LINES),
    }


def _escape_html(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_STATE_LABELS = {
    "needs_brief": "Needs brief",
    "cad_source_ready": "Ready for CAD source",
    "needs_stl_export": "Needs STL export",
    "needs_render": "Needs render",
    "slicer_review_ready": "Slicer review ready",
    "blocked_or_incomplete": "Blocked / incomplete",
}


def build_board_html(board: dict[str, Any]) -> str:
    """Render `gather_board_data()`'s output into a static, self-contained HTML page.

    No external CSS/JS, no CDN, no remote assets, no tracking - a single
    local file safe to open directly in a browser (file://).
    """
    rows: list[str] = []
    for project in board["projects"]:
        state = project["visual_readiness_state"]
        label = _STATE_LABELS.get(state, state)
        warnings_html = (
            "<ul class=\"warnings\">" + "".join(f"<li>{_escape_html(w)}</li>" for w in project["warnings"]) + "</ul>"
            if project["warnings"]
            else "<span class=\"none\">none</span>"
        )
        rows.append(
            "<tr>"
            f"<td>{_escape_html(project['project_name'])}<br><code>{_escape_html(project['project_dir'])}</code></td>"
            f"<td><span class=\"badge state-{_escape_html(state)}\">{_escape_html(label)}</span></td>"
            f"<td>{_escape_html(project['brief_status'] or '(none)')}</td>"
            f"<td>{_escape_html(project['manufacturing_status'] or '(none)')}</td>"
            f"<td>{_escape_html(project['selected_manufacturing_option'] or '(none)')}</td>"
            f"<td>{len(project['cad_files'])}</td>"
            f"<td>{len(project['mesh_files'])}</td>"
            f"<td>{len(project['render_files'])}</td>"
            f"<td>{'yes' if project['preview_package_exists'] else 'no'}</td>"
            f"<td>{'yes' if project['manifest_exists'] else 'no'}</td>"
            f"<td>{warnings_html}</td>"
            "</tr>"
        )

    state_summary = " &nbsp; ".join(
        f"<span class=\"badge state-{state}\">{_STATE_LABELS[state]}: {board['state_counts'][state]}</span>"
        for state in VISUAL_READINESS_STATES
    )

    rows_html = "\n".join(rows) if rows else "<tr><td colspan=\"11\">No projects found under this projects_root.</td></tr>"

    notes_html = "".join(f"<li>{_escape_html(n)}</li>" for n in board["notes"])

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ai-3d-factory preview board</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 2rem; background: #fafafa; color: #1a1a1a; }}
  h1 {{ margin-bottom: 0.25rem; }}
  .meta {{ color: #555; margin-bottom: 1rem; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff; }}
  th, td {{ border: 1px solid #ddd; padding: 0.5rem 0.75rem; text-align: left; vertical-align: top; font-size: 0.9rem; }}
  th {{ background: #f0f0f0; }}
  code {{ font-size: 0.8rem; color: #666; }}
  .badge {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 0.75rem; font-size: 0.8rem; background: #e0e0e0; }}
  .state-needs_brief {{ background: #fde2e2; }}
  .state-cad_source_ready {{ background: #fff3cd; }}
  .state-needs_stl_export {{ background: #fff3cd; }}
  .state-needs_render {{ background: #fff3cd; }}
  .state-slicer_review_ready {{ background: #d4edda; }}
  .state-blocked_or_incomplete {{ background: #fde2e2; }}
  ul.warnings {{ margin: 0; padding-left: 1.1rem; }}
  .none {{ color: #999; }}
  .safety {{ margin-top: 1.5rem; padding: 1rem; background: #fff8e1; border: 1px solid #f0e0a0; }}
  .safety li {{ margin-bottom: 0.25rem; }}
</style>
</head>
<body>
<h1>ai-3d-factory preview board</h1>
<p class="meta">Generated {_escape_html(board["generated_at"])} &middot; projects_root: <code>{_escape_html(board["projects_root"])}</code> &middot; {board["project_count"]} project(s)</p>
<p>{state_summary}</p>
<table>
<thead>
<tr>
  <th>Project</th>
  <th>Visual readiness</th>
  <th>Brief status</th>
  <th>Manufacturing status</th>
  <th>Selected option</th>
  <th>CAD files</th>
  <th>STL files</th>
  <th>Renders</th>
  <th>Preview package</th>
  <th>Manifest</th>
  <th>Warnings / missing artifacts</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
<div class="safety">
<ul>
{notes_html}
</ul>
</div>
</body>
</html>
"""


def preview_board_paths(output_dir: Path) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    return output_dir / INDEX_FILENAME, output_dir / HTML_FILENAME


def write_preview_board(
    projects_root: Path,
    *,
    output_dir: Path | None = None,
    fmt: str = "both",
) -> dict[str, Any]:
    """Build/refresh the static preview board for every project under `projects_root`.

    Writes only `<output_dir>/index.json` and/or `<output_dir>/index.html`
    (`output_dir` defaults to `<projects_root>/preview_board/`) - never
    touches any file inside an individual project, never renders a new
    image, never exports geometry, and never contacts a
    printer/slicer/network.
    """
    if fmt not in ("json", "html", "both"):
        raise ValueError(f"Unknown format {fmt!r}. Allowed: json, html, both")

    projects_root = Path(projects_root)
    output_dir = Path(output_dir) if output_dir is not None else projects_root / BOARD_DIRNAME

    board = gather_board_data(projects_root)
    index_path, html_path = preview_board_paths(output_dir)

    result: dict[str, Any] = {"board": board, "index_path": None, "html_path": None}

    if fmt in ("json", "both"):
        project_store.save_json(index_path, board)
        result["index_path"] = index_path

    if fmt in ("html", "both"):
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(build_board_html(board), encoding="utf-8")
        result["html_path"] = html_path

    return result

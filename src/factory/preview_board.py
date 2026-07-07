"""Local, static, multi-project visual preview board.

Aggregates every project under a `projects_root` directory into one static
board (`preview_board/index.json` + `preview_board/index.html`) for a human
(Owen) to visually sanity-check project state across the whole workspace at
a glance, before trusting any generated CAD/STL output.

Per-project classification (`visual_readiness_state`, `health_signals`,
`suggested_actions`) is computed by `factory.project_inspection` (Phase 13)
- this module is responsible only for discovering projects under a
`projects_root`, aggregating their summaries, and rendering the static
JSON/HTML board. `factory.review_gate` builds on the same
`project_inspection` layer independently, so the two can never disagree
about the same underlying facts without either depending on the other.

This module never generates CAD, renders images, exports STLs, runs
OpenSCAD, runs CadQuery, invokes a slicer, launches Blender, contacts a
network, or contacts a printer. The only files it writes are
`preview_board/index.json` and `preview_board/index.html` under the given
output directory - it never touches `brief.json`, `build_plan.json`,
`part_manifest.json`, or any file inside an individual project. See
docs/preview-board.md, docs/architecture.md, and AGENT.md.

Each project also gets a deterministic `suggested_actions` list - safe,
copyable local commands for the human to consider running next (e.g.
`factory render <path>` for a missing preview). Every action is advisory
only (`"safety": "manual_only"`) and this module never executes one, never
invokes a slicer/printer/network/cloud API, never launches Blender, and
never calls Meshy.

Each project also gets a deterministic `health_signals` summary: a
`summary` of `"ok"`/`"attention_needed"`/`"blocked"` plus structured
`items` (missing/unreadable brief or manifest, an unselected manufacturing
option, render coverage gaps, and local `validation/` report coverage -
`factory validate` is never run automatically, only checked for).
Severities always agree with `classify_visual_readiness()`'s own
precedence, and the only `"ready"` signal (`slicer_review_ready`)
explicitly means "ready for human slicer review", never an approval or
print-readiness claim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import project_store
from factory.project_inspection import (
    ACTION_SAFETY,
    HEALTH_SEVERITIES,
    VISUAL_READINESS_STATES,
    build_health_signals,
    build_suggested_actions,
    classify_visual_readiness,
    summarize_project,
)

BOARD_DIRNAME = "preview_board"
INDEX_FILENAME = "index.json"
HTML_FILENAME = "index.html"

REQUIRED_SAFETY_LINES = (
    "Local static preview only - no server, no cloud, no printer/slicer communication.",
    "This is a visual inspection aid, not an approval and not a print-readiness signal.",
    "Human visual inspection required.",
    "Human slicer review required.",
    "No project shown here is print-ready.",
)


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

_HEALTH_SUMMARY_LABELS = {
    "ok": "OK",
    "attention_needed": "Attention needed",
    "blocked": "Blocked",
}

_HEALTH_SEVERITY_LABELS = {
    "info": "Info",
    "warning": "Warning",
    "blocked": "Blocked",
    "ready": "Ready",
}


def _build_health_signals_html(projects: list[dict[str, Any]]) -> str:
    """Render each project's `health_signals` into a static 'Health signals' block.

    Plain text only - no JavaScript, no external CSS/CDN, no automatic
    action of any kind. This is a read-only summary of locally-derived
    signals (missing/unreadable files, render/validation coverage gaps) -
    never an approval or print-readiness determination.
    """
    blocks: list[str] = []
    for project in projects:
        signals = project.get("health_signals") or {"summary": "ok", "items": []}
        items = signals.get("items") or []
        summary = signals.get("summary", "ok")
        summary_label = _HEALTH_SUMMARY_LABELS.get(summary, summary)

        if items:
            item_rows = "".join(
                "<li>"
                f"<span class=\"health-severity health-{_escape_html(item['severity'])}\">"
                f"{_escape_html(_HEALTH_SEVERITY_LABELS.get(item['severity'], item['severity']))}</span> "
                f"{_escape_html(item['message'])}"
                "</li>"
                for item in items
            )
            items_html = f"<ul class=\"health-items\">{item_rows}</ul>"
        else:
            items_html = "<p class=\"none\">No health signals - nothing detected to flag.</p>"

        blocks.append(
            "<div class=\"project-health\">"
            f"<h3>{_escape_html(project['project_name'])} <code>{_escape_html(project['project_dir'])}</code> "
            f"<span class=\"badge health-summary-{_escape_html(summary)}\">{_escape_html(summary_label)}</span></h3>"
            + items_html
            + "</div>"
        )

    if not blocks:
        return "<p>No health signals - no projects were found under this projects_root.</p>"

    return "".join(blocks)


def _build_suggestions_html(projects: list[dict[str, Any]]) -> str:
    """Render each project's `suggested_actions` into a static 'Suggested next steps' block.

    Plain text/code blocks only - no external JS, no copy buttons, no
    automatic execution of anything. The human reads and, at most, copies
    the command text themselves.
    """
    blocks: list[str] = []
    for project in projects:
        actions = project.get("suggested_actions") or []
        if not actions:
            continue
        action_items = []
        for action in actions:
            action_items.append(
                "<div class=\"action\">"
                f"<p class=\"action-label\"><strong>{_escape_html(action['label'])}</strong> "
                f"<span class=\"safety-tag\">({_escape_html(action['safety'])})</span></p>"
                f"<pre><code>{_escape_html(action['command'])}</code></pre>"
                f"<p class=\"action-reason\">{_escape_html(action['reason'])}</p>"
                "</div>"
            )
        blocks.append(
            "<div class=\"project-suggestions\">"
            f"<h3>{_escape_html(project['project_name'])} <code>{_escape_html(project['project_dir'])}</code></h3>"
            + "".join(action_items)
            + "</div>"
        )

    if not blocks:
        return "<p>No suggested actions - either no projects were found, or nothing needs attention.</p>"

    return "".join(blocks)


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
        coverage = project["render_coverage"]
        coverage_text = f"{coverage['covered_count']}/{coverage['total_meshes']}"
        coverage_details = []
        if coverage["missing_renders"]:
            coverage_details.append(f"{len(coverage['missing_renders'])} missing")
        if coverage["stale_renders"]:
            coverage_details.append(f"{len(coverage['stale_renders'])} stale")
        if coverage["orphan_renders"]:
            coverage_details.append(f"{len(coverage['orphan_renders'])} orphan")
        if coverage_details:
            coverage_text += " (" + ", ".join(coverage_details) + ")"

        health = project.get("health_signals") or {"summary": "ok", "items": []}
        health_summary = health.get("summary", "ok")
        health_label = _HEALTH_SUMMARY_LABELS.get(health_summary, health_summary)
        health_count = len(health.get("items") or [])
        health_text = f"{health_label} ({health_count})" if health_count else health_label

        rows.append(
            "<tr>"
            f"<td>{_escape_html(project['project_name'])}<br><code>{_escape_html(project['project_dir'])}</code></td>"
            f"<td><span class=\"badge state-{_escape_html(state)}\">{_escape_html(label)}</span></td>"
            f"<td><span class=\"badge health-summary-{_escape_html(health_summary)}\">{_escape_html(health_text)}</span></td>"
            f"<td>{_escape_html(project['brief_status'] or '(none)')}</td>"
            f"<td>{_escape_html(project['manufacturing_status'] or '(none)')}</td>"
            f"<td>{_escape_html(project['selected_manufacturing_option'] or '(none)')}</td>"
            f"<td>{len(project['cad_files'])}</td>"
            f"<td>{len(project['mesh_files'])}</td>"
            f"<td>{len(project['render_files'])}</td>"
            f"<td>{_escape_html(coverage_text)}</td>"
            f"<td>{'yes' if project['preview_package_exists'] else 'no'}</td>"
            f"<td>{'yes' if project['manifest_exists'] else 'no'}</td>"
            f"<td>{warnings_html}</td>"
            "</tr>"
        )

    state_summary = " &nbsp; ".join(
        f"<span class=\"badge state-{state}\">{_STATE_LABELS[state]}: {board['state_counts'][state]}</span>"
        for state in VISUAL_READINESS_STATES
    )

    rows_html = "\n".join(rows) if rows else "<tr><td colspan=\"13\">No projects found under this projects_root.</td></tr>"

    notes_html = "".join(f"<li>{_escape_html(n)}</li>" for n in board["notes"])
    suggestions_html = _build_suggestions_html(board["projects"])
    health_signals_html = _build_health_signals_html(board["projects"])

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
  .suggestions {{ margin-top: 1.5rem; }}
  .suggestions-intro {{ color: #555; }}
  .project-suggestions {{ background: #fff; border: 1px solid #ddd; border-radius: 0.35rem; padding: 0.75rem 1rem; margin-bottom: 1rem; }}
  .project-suggestions h3 {{ margin: 0 0 0.5rem 0; font-size: 1rem; }}
  .action {{ margin-bottom: 0.75rem; padding-bottom: 0.75rem; border-bottom: 1px solid #eee; }}
  .action:last-child {{ margin-bottom: 0; padding-bottom: 0; border-bottom: none; }}
  .action-label {{ margin: 0 0 0.25rem 0; }}
  .safety-tag {{ color: #7a5c00; font-size: 0.8rem; font-weight: normal; }}
  .action pre {{ margin: 0.25rem 0; padding: 0.5rem 0.75rem; background: #f5f5f5; border: 1px solid #e0e0e0; border-radius: 0.25rem; overflow-x: auto; }}
  .action pre code {{ font-size: 0.85rem; color: #1a1a1a; user-select: all; }}
  .action-reason {{ margin: 0.25rem 0 0 0; color: #555; font-size: 0.85rem; }}
  .health {{ margin-top: 1.5rem; }}
  .health-intro {{ color: #555; }}
  .project-health {{ background: #fff; border: 1px solid #ddd; border-radius: 0.35rem; padding: 0.75rem 1rem; margin-bottom: 1rem; }}
  .project-health h3 {{ margin: 0 0 0.5rem 0; font-size: 1rem; }}
  ul.health-items {{ margin: 0; padding-left: 1.1rem; }}
  ul.health-items li {{ margin-bottom: 0.35rem; }}
  .health-severity {{ display: inline-block; padding: 0.1rem 0.4rem; border-radius: 0.6rem; font-size: 0.75rem; font-weight: 600; margin-right: 0.25rem; }}
  .health-info {{ background: #e0e0e0; color: #333; }}
  .health-warning {{ background: #fff3cd; color: #7a5c00; }}
  .health-blocked {{ background: #fde2e2; color: #8a1f1f; }}
  .health-ready {{ background: #d4edda; color: #1e5b2e; }}
  .health-summary-ok {{ background: #d4edda; }}
  .health-summary-attention_needed {{ background: #fff3cd; }}
  .health-summary-blocked {{ background: #fde2e2; }}
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
  <th>Health</th>
  <th>Brief status</th>
  <th>Manufacturing status</th>
  <th>Selected option</th>
  <th>CAD files</th>
  <th>STL files</th>
  <th>Renders</th>
  <th>Render coverage</th>
  <th>Preview package</th>
  <th>Manifest</th>
  <th>Warnings / missing artifacts</th>
</tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
<div class="health">
<h2>Health signals</h2>
<p class="health-intro">Local, read-only signals derived from files already on disk (missing/unreadable
JSON, render coverage gaps, validation report coverage). Advisory only - this is not an approval and
not a print-readiness determination, and nothing here was validated, rendered, or checked automatically.</p>
{health_signals_html}
</div>
<div class="suggestions">
<h2>Suggested next steps</h2>
<p class="suggestions-intro">Advisory only. Nothing on this page runs automatically - commands are
plain text for you to read, and copy yourself, only if and when you decide to run them.</p>
{suggestions_html}
</div>
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

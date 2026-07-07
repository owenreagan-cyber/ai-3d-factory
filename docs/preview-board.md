# Local visual preview board (Phase 8)

`factory preview-board <projects_root>` builds a **local, static** preview
board summarizing every project under `projects_root` at a glance - so Owen
can visually sanity-check where each project stands before trusting any
generated CAD/STL output, without having to run `factory report` on every
project one at a time.

## What this is not

- **Not a server.** Nothing here binds a port, starts a process that keeps
  running, or serves anything over HTTP. `index.html` is a plain static
  file - open it directly in a browser (`file://`) or drag it in.
- **Not a cloud app.** No accounts, no sync, no remote storage.
- **Not connected to a printer or slicer.** It never discovers, contacts,
  or sends anything to a printer or slicer.
- **Not a Blender or Meshy integration.** No mesh repair, no organic
  generation, nothing beyond reading files already on disk.
- **Not an approval mechanism.** The board's `visual_readiness_state`
  field is an advisory read of existing files - it never sets
  `human_approved` or `print_ready`, and it never writes to any project's
  `brief.json`, `build_plan.json`, or `part_manifest.json`. The highest
  status any `factory` command can set automatically remains
  `slicer_review_ready` (see `AGENT.md`).

## Usage

```bash
factory preview-board projects/                       # writes projects/preview_board/{index.json,index.html}
factory preview-board projects/ --output /tmp/board    # write elsewhere
factory preview-board projects/ --format json          # only index.json
factory preview-board projects/ --format html          # only index.html
```

`projects_root` is any directory containing project subdirectories (each
one an already-initialized `factory init-project` folder, i.e. with a
`brief.json`/`part_manifest.json`). It doesn't have to be this repo's own
`projects/` - point it at any folder of projects.

By default, output is written to `<projects_root>/preview_board/`:

- `index.json` - machine-readable board data (see shape below).
- `index.html` - a single self-contained static HTML page: inline CSS
  only, no external JS, no CDN, no remote assets, no tracking, no
  telemetry, no analytics.

Re-running the command is safe and deterministic given the same project
files - it only reads and then overwrites the two board output files.

## How it reuses `preview_package`

Rather than re-scanning `cad/`/`stl/`/`renders/` itself, the board reuses
`factory.preview_package`:

- If a project already has `preview_package/index.json` (from a prior
  `factory preview-project` run), the board reads that file directly.
- Otherwise it calls `factory.preview_package.gather_preview_data()` - the
  same read-only function `preview-project` itself uses - to compute an
  equivalent summary on the fly, without writing anything into that
  project. A warning noting this ("computed on the fly - run `factory
  preview-project` to persist it") is attached to that project's entry so
  it's clear the number came from a live scan, not a saved snapshot.

Either path produces the same `cad_files`/`mesh_files`/`render_files`/
`missing_visual_artifacts`/`stale_previews` shape, so a project's row on
the board looks the same either way.

Separately (Phase 9), each project's card also carries a `render_coverage`
field - always freshly computed via `factory.render_coverage.compute_render_coverage()`
rather than trusted from a possibly-stale cached `preview_package/index.json`,
so it's accurate even for a project that's never had `factory preview-project`
run on it. See `docs/render-coverage.md`.

## Visual readiness states

Each project is classified into exactly one state, evaluated in this
order (first match wins) - naming mirrors the "X_ready means the prior
step is done, next step implied" convention `project_store.PROJECT_STATUSES`
already uses (e.g. `slicer_review_ready` there):

| State | Meaning |
|---|---|
| `needs_brief` | `brief.json` is missing. Nothing to summarize yet. |
| `cad_source_ready` | Brief exists; no CAD source (`.scad`/`.py`) files *and* no STL yet. Ready for `factory generate-openscad` / `factory generate-cadquery`. |
| `needs_stl_export` | CAD source exists; no STL exported yet. |
| `needs_render` | STL exists (from local CAD source, or from an imported/scanned mesh with no local CAD source at all); at least one mesh has no matching render yet - whether that's all of them or just one of several (per `render_coverage.missing_renders`). |
| `slicer_review_ready` | Every mesh has a fresh (non-stale) render and the preview package reports no other missing/stale artifacts. Same meaning as the existing `slicer_review_ready` project status: ready for **human** slicer review, not print-ready. |
| `blocked_or_incomplete` | Something doesn't parse (corrupt `brief.json`/`part_manifest.json`), a render exists but is stale, or the preview package still flags a missing/stale artifact render coverage's directory-only view can't see (e.g. a manifest part whose file lives outside `stl/`). |

An **orphan render never blocks readiness by itself** - a render with no
matching STL currently on disk is common (renamed/removed part) and is
surfaced only as an advisory warning on the project's card, per
`docs/render-coverage.md`.

`human_approved` and `print_ready` are never computed or implied by this
module - see `AGENT.md` for why that boundary only moves via explicit
human action outside any `factory` command.

## Board JSON shape

```jsonc
{
  "generated_at": "2026-...Z",
  "projects_root": "projects",
  "project_count": 2,
  "state_counts": { "needs_brief": 0, "cad_source_ready": 1, "...": 0 },
  "projects": [
    {
      "project_name": "Demo Bracket",
      "project_dir": "demo-bracket",
      "slug": "demo-bracket",
      "brief_exists": true,
      "brief_status": "cad_generated",
      "manufacturing_status": "plan_drafted",
      "selected_manufacturing_option": null,
      "manifest_exists": true,
      "preview_package_exists": false,
      "cad_files": ["cad/mechanical_plate.py"],
      "mesh_files": [],
      "render_files": [],
      "render_coverage": {
        "total_meshes": 0, "total_renders": 0, "covered_count": 0,
        "missing_renders": [], "stale_renders": [], "orphan_renders": [],
        "all_meshes_have_renders": false, "visually_complete_for_slicer_review": false,
        "...": "..."
      },
      "visual_readiness_state": "needs_stl_export",
      "warnings": ["No preview_package/index.json found - ...", "..."]
    }
  ],
  "notes": ["Local static preview only - ...", "..."]
}
```

## What it does not do

- Does not generate CAD, run OpenSCAD, or run CadQuery.
- Does not export or render meshes.
- Does not invoke or launch a slicer.
- Does not invoke or launch Blender.
- Does not call Meshy or any paid/cloud API.
- Does not contact a printer, discover printers, or talk to Bambu Cloud.
- Does not write to any project's `brief.json`, `build_plan.json`, or
  `part_manifest.json` - it only writes the two board files described
  above.
- Does not set `human_approved` or `print_ready` on anything.

See also `docs/visual-preview-package.md` (per-project preview package,
which this board aggregates) and `docs/roadmap.md` Phase 8.

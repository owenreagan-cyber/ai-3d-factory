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

## How it's built

The board does no per-project file scanning itself. Each project's row
comes entirely from `factory.project_inspection.summarize_project()`
(Phase 13 - see `docs/architecture.md`'s "Shared inspection layer" note),
the same function `factory review-gate` builds on independently - so a
project's row on the board and its `review-gate` result can never
silently disagree about the same underlying facts. `preview_board.py`
itself is responsible only for discovering projects under `projects_root`
(`discover_projects()`), aggregating their summaries
(`gather_board_data()`), and rendering the JSON/HTML.

`summarize_project()`, in turn, reuses `factory.preview_package` rather
than re-scanning `cad/`/`stl/`/`renders/` itself:

- If a project already has `preview_package/index.json` (from a prior
  `factory preview-project` run), it reads that file directly.
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

## Suggested next steps (Phase 10)

Each project's card also carries a `suggested_actions` list - deterministic,
structured next-step suggestions the human can read and, if they choose,
copy and run themselves. **Nothing here is ever executed automatically.**
Each action has this shape:

```jsonc
{
  "kind": "render_missing_mesh",
  "label": "Render missing STL preview",
  "command": "factory render projects/demo/stl/part_a.stl",
  "safety": "manual_only",
  "reason": "STL exists but matching render PNG is missing"
}
```

`safety` is always `"manual_only"` - every action in this repo is advisory
text, never something this module runs. `command` is plain text; the board
HTML renders it in a `<pre><code>` block for easy copying, never behind a
JS "copy" button (there is no JavaScript on the page at all).

One suggestion set per project, driven by the same `visual_readiness_state`
already computed above (so a project never gets a suggestion for a step
that's already superseded by a more fundamental one):

| State | `kind` | What it suggests |
|---|---|---|
| `needs_brief` | `create_brief_missing` | Create `brief.json` (points at `docs/file-lifecycle.md`), then `factory plan`. |
| `cad_source_ready` | `generate_cad_source` | Run `factory route-cad <path>` (read-only) to pick a backend, then generate CAD source yourself. |
| `needs_stl_export` | `export_stl_manual` | Review the CAD source, then export it into `stl/` yourself - STL export is always manual in this repo. |
| `needs_render` | `render_missing_mesh` | One suggestion per mesh still missing (or with a stale) render: `factory render <project_path>/stl/<name>.stl`. Reuses `factory.render_coverage.missing_and_stale_mesh_paths()` - the same function `factory plan-renders` is built on - so the two never drift apart. |
| `slicer_review_ready` | `review_slicer_manually` | Open the STLs in Bambu Studio/OrcaSlicer for **manual review only** - explicitly "do not slice-and-send or print yet." |
| `blocked_or_incomplete` | `inspect_blocked_project` | Run `factory report <path>` / `factory render-coverage <path>` (both read-only); the `reason` field explains the actual cause (corrupt JSON, a stale render, or a preview-package-flagged artifact). |

No action ever suggests printing, slicing-and-sending, uploading, calling
a cloud/paid API, calling Meshy, or launching Blender - and none set
`human_approved` or `print_ready`.

**Phase 11 addition:** on top of the one primary state-driven suggestion
above, each project also gets one `validate_mesh_manual` suggestion per
STL file that has no local `validation/<name>_validation.json` report yet
(`factory validate <path>` never runs automatically). This is orthogonal
to `visual_readiness_state` - checking geometry is independent of visual
progress, so it's applied regardless of which state a project is in.

## Health signals (Phase 11)

Each project's card also carries a `health_signals` object - a local,
read-only rollup of everything worth flagging, for scanning many projects
at a glance without reading every warning individually:

```jsonc
{
  "summary": "attention_needed",
  "items": [
    {
      "kind": "manifest_missing",
      "severity": "warning",
      "message": "part_manifest.json is missing.",
      "suggested_action_kind": "inspect_blocked_project"
    }
  ]
}
```

`summary` is a deterministic rollup of `items`: `"blocked"` if any item is
`"blocked"`-severity, else `"attention_needed"` if any is `"warning"`,
else `"ok"`. **This is a visual-inspection aid only** - `summary`/`items`
never set `human_approved` or `print_ready`, and the highest severity used
for a positive result is `"ready"` (see `slicer_review_ready` below),
never an approval.

Severities always agree with `visual_readiness_state`'s own precedence -
a `"blocked"` health item only ever appears for exactly the condition that
puts (or would put) the project into `blocked_or_incomplete`; a normal,
expected, non-corrupt gap is `"warning"`; and purely informational context
is `"info"`:

| `kind` | Severity | When |
|---|---|---|
| `brief_missing` | `warning` | `brief.json` doesn't exist yet. |
| `brief_unreadable` | `blocked` | `brief.json` exists but isn't valid JSON. |
| `manifest_missing` | `warning` | `part_manifest.json` doesn't exist yet. |
| `manifest_unreadable` | `blocked` | `part_manifest.json` exists but isn't valid JSON. |
| `manufacturing_option_not_selected` | `info` | Brief exists but no option chosen yet (`factory choose-option`). Not shown before a brief exists, to avoid redundant noise. |
| `preview_package_missing` | `info` | No `preview_package/index.json` yet - a live summary was computed instead. |
| `preview_package_unreadable` | `warning` | `preview_package/index.json` exists but isn't valid JSON. |
| `render_missing` | `warning` | At least one STL has no matching render yet. |
| `render_stale` | `blocked` | At least one render is older than its STL - always coincides with `blocked_or_incomplete`. |
| `render_orphan` | `info` | A render has no matching STL currently on disk - advisory only, never blocking. |
| `missing_visual_artifacts` / `stale_preview_artifacts` | `blocked` | The preview package's manifest-aware check flags something render coverage's directory-only view can't see. |
| `validation_missing` | `warning` | At least one STL has no local `validation/<name>_validation.json` report yet. |
| `validation_present` | `info` | At least one STL already has a local validation report. |
| `slicer_review_ready` | `ready` | Every mesh has a fresh render and nothing else was flagged - ready for **human** slicer review, explicitly "not print-ready" in the message text. |

`suggested_action_kind` (when set) names the matching entry in
`suggested_actions`'s `kind` vocabulary - a hint at what would resolve
that signal, not a promise that exact action is already in the list for
every state.

The board's HTML gets a "Health signals" section (one block per project,
severity-colored badges, plain text only - no JavaScript) and a compact
"Health" column in the summary table (e.g. "Attention needed (2)").

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
      "warnings": ["No preview_package/index.json found - ...", "..."],
      "suggested_actions": [
        {
          "kind": "export_stl_manual",
          "label": "Export CAD source to STL",
          "command": "Review the CAD source under projects/demo-bracket/cad/, then export it "
                       "yourself into projects/demo-bracket/stl/ ...",
          "safety": "manual_only",
          "reason": "CAD source exists but no STL has been exported yet. STL export is always a "
                     "manual, human-run step in this repo."
        }
      ],
      "health_signals": {
        "summary": "attention_needed",
        "items": [
          {
            "kind": "manufacturing_option_not_selected",
            "severity": "info",
            "message": "No manufacturing option has been selected yet - see `factory list-options` / `factory choose-option`.",
            "suggested_action_kind": null
          }
        ]
      }
    }
  ],
  "notes": ["Local static preview only - ...", "..."]
}
```

## What it does not do

- Does not generate CAD, run OpenSCAD, or run CadQuery.
- Does not export or render meshes.
- Does not run `factory validate` - it only checks whether a
  `validation/<name>_validation.json` report already exists on disk.
- Does not invoke or launch a slicer.
- Does not invoke or launch Blender.
- Does not call Meshy or any paid/cloud API.
- Does not contact a printer, discover printers, or talk to Bambu Cloud.
- Does not write to any project's `brief.json`, `build_plan.json`, or
  `part_manifest.json` - it only writes the two board files described
  above.
- Does not set `human_approved` or `print_ready` on anything.
- Does not execute any `suggested_actions` command - ever, automatically
  or otherwise. There is no "run" button anywhere in the generated HTML.

See also `docs/visual-preview-package.md` (per-project preview package,
which this board aggregates), `docs/render-coverage.md` (the render-gap
detection `needs_render` suggestions are built on), `docs/review-gate.md`
(Phase 12 - a single-project pass/warn/fail pre-flight check built
directly on this module's `summarize_project()`, not merged into the
board itself - see that doc's "Why this isn't merged into `factory
preview-board`" section), and `docs/roadmap.md` Phase 8 (board
foundation) / Phase 10 (action suggestions) / Phase 11 (health signals) /
Phase 12 (review gate).

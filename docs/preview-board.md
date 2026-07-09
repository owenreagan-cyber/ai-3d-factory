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

For example, `factory preview-board examples` boards every immediate
subdirectory of `examples/` (including `simple-nameplate/`,
`mechanical-plate/`, and the `future-organic-models/` folder itself - not
its nested concept subdirectories, since `discover_projects()` only lists
immediate subdirectories). Concept placeholders under
`future-organic-models/` use `concept_brief.json` rather than `brief.json`
specifically so a board rooted at `examples/future-organic-models` reports
them as `needs_brief` instead of implying they're real, in-progress
projects. See `docs/examples-library.md`.

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

## Design intent summary (Phase 26)

Each project's card also carries a `design_intent_summary` field - a
compact, read-only view of the project's `brief.json`
`design_intent` block (`docs/design-intent-brief.md`), if it has one:

```jsonc
{
  "quality_standard": "Etsy-worthy",
  "use_case": "kitchen organization",
  "manufacturability_result": "fits_some_printers"
}
```

`None` whenever the brief has no `design_intent` block (most projects
won't) - not an error, and not shown as a warning. Built from
`factory.design_intent_check.summarize_design_intent()`, which itself
reuses Phase 25's `check_design_intent_manufacturability()` rather than
re-deriving that parsing/fit logic - so `manufacturability_result` here
is always the same value `factory check-design-intent` would report for
the same brief. `factory report` shows the fuller version of the same
data (quality standard, use case, style direction, declared size, and
which known printers fit) as a `Design Intent:` section - see
`docs/design-intent-brief.md`.

This field is **purely additive and purely presentational**: it is never
read by `classify_visual_readiness()`, `build_health_signals()`, or
`build_suggested_actions()`, so its presence or absence cannot change a
project's `visual_readiness_state`, health signals, or suggested actions.
It does not judge creativity, approve a design, score anything, or set
`human_approved`/`print_ready` - it only surfaces an existing brief field
that would otherwise require a separate `factory check-design-intent`
run to see.

## Design intent detail and the Design Intent card (Phase 27)

Each project's card also carries `design_intent_detail` - a superset of
`design_intent_summary` above, adding `style_direction`,
`reference_input_count` (the length of the brief's optional
`design_intent.reference_inputs` list), `design_notes` (the brief's
optional `design_intent.iteration_plan.acceptance_notes`), and
`warnings` (the same advisory warnings `factory check-design-intent`
already computes, e.g. an unverified printer spec):

```jsonc
{
  "quality_standard": "Etsy-worthy",
  "use_case": "classroom organization",
  "style_direction": ["minimal", "functional"],
  "manufacturability_result": "fits_some_printers",
  "reference_input_count": 1,
  "design_notes": "Snug fit on the existing bin, no wobble.",
  "warnings": []
}
```

`None` under the exact same conditions as `design_intent_summary` -
`design_intent_summary`'s own shape is unchanged by this; `design_intent_detail`
is a new, additive sibling field, built by
`factory.design_intent_check.describe_design_intent_for_board()` (reuses
`check_design_intent_manufacturability()`, no parsing logic duplicated).

The board's **HTML** now renders `design_intent_detail` (and the rest of a
project's existing summary) as a per-project overview card, right after the
state-count line and before the existing summary table: **Project Header**,
**Design Intent** (Quality/Purpose/Style/Design notes), **Manufacturing
Overview** (manufacturing status, selected option, design-intent
manufacturability fit, reference input count, warnings/advisories),
**Artifacts** (CAD/STL/Render present-or-missing badges), **Health Signals**
(a compact badge pointing at the detailed section further down the page),
and **Review Readiness** (a Review Ready / Review Not Ready badge from
`visual_readiness_state`). Every field renders a clear fallback ("Not
specified"/"None"/"Unknown") rather than ever being left blank - most
projects have no `design_intent` block, which renders a single explanatory
line instead of empty rows. Static HTML/CSS only: no JavaScript, no
external assets, no CDN, no tracking. This is purely presentational - it
adds no new field to the JSON board shape beyond `design_intent_detail`
above, removes no existing HTML section (the summary table, "Health
signals", and "Suggested next steps" sections are unchanged and still
follow the cards), and introduces no new judgment, scoring, or approval
semantics.

## Reference Board summary and card (Phase 28)

Each project's card also carries `reference_board_summary` - a read-only,
advisory summary of the project's optional `reference_board.json`
(`factory.reference_board`, `docs/reference-board.md`), independent of
`brief.json`/`design_intent` entirely (computed even for a project with no
brief at all):

```jsonc
{
  "reference_count": 1,
  "by_license": {"unknown": 1},
  "by_source_type": {"inspiration": 1},
  "by_usage_intent": {"design_reference_only": 1},
  "attached_to_design_intent_count": 1,
  "warnings": ["Classroom storage inspiration: license is unknown - commercial use unclear."]
}
```

Always a dict, never `None` - a "clean empty result"
(`reference_count: 0`, empty breakdowns, no warnings) whenever no
`reference_board.json` exists, exactly like `design_intent_summary`/
`design_intent_detail` return `None` for a brief with no `design_intent`.
Purely additive and purely presentational, the same guarantees as
`design_intent_summary`/`design_intent_detail`: never read by
`classify_visual_readiness()`, `build_health_signals()`, or
`build_suggested_actions()`, and `factory review-gate`'s JSON output still
never includes it.

The board's **HTML** gained a compact "Reference Board" card section,
right after "Design Intent" (references feed design intent) and before
"Manufacturing Overview" - reference count, a license-status breakdown, a
usage-intent breakdown, and any advisory warnings (missing/unknown/
proprietary license, missing `source_url`, a `remix_candidate` with an
unsafe license, an unsupported field value, or no references attached to
`design_intent.reference_inputs`). Compact by design: counts and
warnings, not a full per-reference listing - no titles or URLs rendered
individually. A project with zero references renders a single
explanatory line instead of empty rows. Static HTML/CSS only - no
JavaScript, no external assets, no CDN, no tracking - and, same as the
module itself, no `source_url` is ever fetched, downloaded, or rendered as
a clickable link. See `docs/reference-board.md` for the full field/
vocabulary reference and what this phase explicitly does not do (no
Source Discovery, no scraping, no downloading, no search, no API
integration).

`reference_board.json` no longer has to be hand-edited - Phase 29 added
`factory reference-board init/show/validate/add/list` on top of this same
module, still entirely local. The board's HTML/JSON output is unaffected
by that CLI (Phase 29 is CLI-only, no board layout changes) - see
`docs/reference-board.md`'s "CLI management (Phase 29)" section.

## Project Intake summary and card (Phase 30)

Each project's card also carries `intake_summary` - a read-only, fully
deterministic heuristic analysis (`factory.project_intake`,
`docs/project-intake.md`) of the project's `brief.json`
`project_name`/`description`/`constraints` free text. **No AI, no LLM, no
network** - closed keyword tables and regexes only:

```jsonc
{
  "project_name": {"value": "Demo Project", "confidence": "high"},
  "category": {"value": "sign", "confidence": "medium"},
  "purpose": {"value": "A premium classroom sign...", "confidence": "medium"},
  "audience": {"value": "Students", "confidence": "medium"},
  "environment": {"value": "classroom", "confidence": "medium"},
  "material_assumptions": {"value": ["PLA"], "confidence": "high"},
  "printer_assumptions": {"value": ["Bambu"], "confidence": "high"},
  "quality_target": {"value": "etsy-worthy", "confidence": "medium"},
  "manufacturing_style": {"value": [], "confidence": "unknown"},
  "functional_goals": {"value": [], "confidence": "unknown"},
  "visual_goals": {"value": [], "confidence": "unknown"},
  "dimensional_constraints": {"value": [], "confidence": "unknown"},
  "commercial_intent": {"value": false, "confidence": "unknown"},
  "warnings": ["Dimensions not specified."],
  "source": "brief_description"
}
```

Always a dict, never `None` - computed unconditionally (independent of
`brief_status`, a project can be intake-analyzed before it has anything
else). Purely additive and purely presentational, the same guarantees as
`design_intent_summary`/`design_intent_detail`/`reference_board_summary`:
never read by `classify_visual_readiness()`, `build_health_signals()`, or
`build_suggested_actions()`, and `factory review-gate`'s JSON output still
never includes it.

The board's **HTML** gained a compact "Project Intake" card section,
placed *first* in each project's card - upstream of "Design Intent" in
this repo's pipeline (User Idea -> Project Intake -> Project Brief ->
Design Intent -> Reference Board -> ...) - category, audience,
environment, quality target, material assumptions, and advisory warnings.
Deliberately compact: per-field confidence levels and less commonly needed
fields (printer assumptions, manufacturing style, functional/visual goals,
dimensional constraints, commercial intent) stay in `factory intake
analyze --json` output, not duplicated in the card. Static HTML/CSS only -
no JavaScript, no external assets, no CDN, no tracking, and (same
guarantee as the module itself) no network call, AI/LLM API call, web
search, or download of any kind. See `docs/project-intake.md` for the full
field/heuristic/confidence reference and this phase's non-goals.

## Draft Brief summary and card (Phase 31)

Each project's card also carries `draft_brief_summary` - a compact
`{readiness, advisories}` view of `factory.brief_generator.generate_draft()`,
derived from the project's own `intake_summary` above (never re-parses
`brief.json`'s free text a second time):

```jsonc
{
  "readiness": {
    "status": "Ready",
    "percent_populated": 85,
    "populated_count": 11,
    "unknown_count": 2,
    "total_fields": 13,
    "human_review_required": true
  },
  "advisories": [
    "Reference board recommended - see `factory reference-board add`.",
    "Human approval required before save."
  ]
}
```

Always a dict, never `None` - computed unconditionally, same reasoning as
`intake_summary`. Purely additive and purely presentational: never read by
`classify_visual_readiness()`, `build_health_signals()`, or
`build_suggested_actions()`, and `factory review-gate`'s JSON output still
never includes it.

The board's **HTML** gained a compact "Draft Brief" card section, right
after "Project Intake" (a draft brief is the next pipeline step) and
before "Design Intent" - readiness status, percent populated, unknown-
field count, and a standing "Human review required" reminder. The full
`brief`/`design_intent`/`manufacturing_notes` draft (and the only actual
write path, `--write`) live in `factory intake suggest-brief`, not here -
**the preview board itself never writes anything, for this card or any
other.** Static HTML/CSS only - no JavaScript, no external assets. See
`docs/brief-generator.md` for the full draft shape, the human-approval
model, and this phase's non-goals.

## Brief Update summary and card (Phase 32)

Each project's card also carries `brief_update_summary` - a compact
`{merge_available, fields_to_add_count, fields_preserved_count,
human_review_required}` view of `factory.brief_generator.merge_draft_brief()`,
comparing the project's own existing `brief.json` against its
`intake_summary`'s draft:

```jsonc
{
  "merge_available": true,
  "fields_to_add_count": 3,
  "fields_preserved_count": 2,
  "human_review_required": true
}
```

Always a dict, never `None` - computed unconditionally, same reasoning as
`draft_brief_summary`. Purely additive and purely presentational: never
read by `classify_visual_readiness()`, `build_health_signals()`, or
`build_suggested_actions()`, and `factory review-gate`'s JSON output still
never includes it.

The board's **HTML** gained a compact "Brief Update" card section, right
after "Draft Brief" and before "Design Intent" - but **deliberately
terser** than every other card on this board: when `merge_available` is
`false` (the common case - most real projects already have real content
in every field merge cares about), the card renders exactly one line,
`"Up to date - nothing to merge."`, instead of a status/count block. Only
when a safe merge is genuinely available does the fuller block appear
(a `Merge available` badge, fields-to-add count, preserved count, the
standing "Human review required" reminder). This asymmetry is intentional
- Phase 32's own requirement was "keep it compact, don't make the board
noisy," and a third near-identical status card that mostly says "nothing
to do" on every project would have been exactly that. The full merge
preview (and the only actual write path, `--write --update`) lives in
`factory intake suggest-brief --update`, not here - **the preview board
itself never merges or writes anything, for this card or any other.**
Static HTML/CSS only - no JavaScript, no external assets. See
`docs/brief-generator.md`'s "Merge mode (Phase 32)" section for the full
merge rules and this phase's non-goals.

## Project Readiness dashboard (Phase 33)

Each project's card also carries `design_orchestrator_summary` -
`factory.design_orchestrator.evaluate_project_readiness()`'s full result,
computed from the six summaries above (`intake_summary`,
`draft_brief_summary`, `brief_update_summary`, `design_intent_summary`,
`design_intent_detail`, `reference_board_summary` - never re-parsed a
second time):

```jsonc
{
  "readiness_state": "Ready For Mechanical CAD",
  "recommended_engine": "OpenSCAD",
  "engine_rationale": "Category 'sign' matches OpenSCAD's parametric plate/sign/organizer strengths.",
  "score": {
    "overall": 86,
    "categories": {
      "intake": 100, "brief": 90, "design_intent": 100,
      "reference_board": 60, "manufacturing": 80
    }
  },
  "advisories": ["Reference images recommended", "Human approval required"]
}
```

Always a dict, never `None` - computed unconditionally, same reasoning as
every other Phase 26-32 summary. Purely additive and purely advisory:
never read by `classify_visual_readiness()`, `build_health_signals()`, or
`build_suggested_actions()`, and `factory review-gate`'s JSON output still
never includes it. **No CAD is ever generated and no engine is ever
invoked by computing this field** - `recommended_engine` is a string,
nothing more.

The board's **HTML** gained a "Project Readiness" dashboard section,
placed **first** in each project's card - overall score, recommended
engine, readiness state, and the top remaining advisories. This is a
**dashboard that summarizes the existing detail cards below it - it does
not remove or replace any of them.** Project Intake, Draft Brief, Brief
Update, Design Intent, Reference Board, Manufacturing Overview, Artifacts,
Health Signals, and Review Readiness are all completely unchanged and
still follow the dashboard, in the same order as before. Static HTML/CSS
only - no JavaScript, no external assets. See `docs/design-orchestrator.md`
for the full scoring model, readiness-state decision tree, and engine
recommendation rules.

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
      },
      "design_intent_summary": null,
      "design_intent_detail": null,
      "reference_board_summary": {
        "reference_count": 0,
        "by_license": {},
        "by_source_type": {},
        "by_usage_intent": {},
        "attached_to_design_intent_count": 0,
        "warnings": []
      },
      "intake_summary": {
        "project_name": {"value": "Demo Bracket", "confidence": "high"},
        "category": {"value": "unknown", "confidence": "unknown"},
        "purpose": {"value": null, "confidence": "unknown"},
        "audience": {"value": null, "confidence": "unknown"},
        "environment": {"value": "unknown", "confidence": "unknown"},
        "material_assumptions": {"value": [], "confidence": "unknown"},
        "printer_assumptions": {"value": [], "confidence": "unknown"},
        "quality_target": {"value": "unknown", "confidence": "unknown"},
        "manufacturing_style": {"value": [], "confidence": "unknown"},
        "functional_goals": {"value": [], "confidence": "unknown"},
        "visual_goals": {"value": [], "confidence": "unknown"},
        "dimensional_constraints": {"value": [], "confidence": "unknown"},
        "commercial_intent": {"value": false, "confidence": "unknown"},
        "warnings": ["Dimensions not specified.", "Printer not specified.", "Material not specified."],
        "source": "brief_description"
      },
      "draft_brief_summary": {
        "readiness": {
          "status": "Ready",
          "percent_populated": 0,
          "populated_count": 0,
          "unknown_count": 13,
          "total_fields": 13,
          "human_review_required": true
        },
        "advisories": [
          "Material not specified.",
          "Printer not specified.",
          "Dimensions incomplete.",
          "Human approval required before save."
        ]
      },
      "brief_update_summary": {
        "merge_available": false,
        "fields_to_add_count": 0,
        "fields_preserved_count": 2,
        "human_review_required": true
      },
      "design_orchestrator_summary": {
        "readiness_state": "Not Ready",
        "recommended_engine": "Unknown",
        "engine_rationale": "No category, style, or descriptive text signal available yet to recommend an engine.",
        "score": {
          "overall": 0,
          "categories": {
            "intake": 0, "brief": 0, "design_intent": 0,
            "reference_board": 0, "manufacturing": 0
          }
        },
        "advisories": [
          "Dimensions missing", "Material unspecified", "Printer unspecified",
          "Design intent incomplete", "Manufacturing review required",
          "Human approval required"
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
- Does not judge, score, or approve a project's `design_intent` (Phase 26,
  extended in Phase 27) - `design_intent_summary`/`design_intent_detail`
  and the HTML Design Intent card are display-only mirrors of an existing
  brief field, never an input to `visual_readiness_state`,
  `health_signals`, or `suggested_actions`.
- Does not fetch, download, scrape, or search anything for a project's
  Reference Board (Phase 28) - `reference_board_summary` and the HTML
  Reference Board card only read and summarize a local
  `reference_board.json`; every `source_url` on it is inert metadata,
  never a target this board (or anything it calls) opens. See
  `docs/reference-board.md`.
- Does not call an AI/LLM, does not perform a web search, and does not
  read a project's free-form idea text with anything other than closed
  keyword tables and regexes (Phase 30) - `intake_summary` and the HTML
  Project Intake card only reflect
  `factory.project_intake`'s fully deterministic analysis of
  `brief.json`'s own `project_name`/`description`/`constraints` text. See
  `docs/project-intake.md`.
- Does not write anything for a project's Draft Brief (Phase 31) -
  `draft_brief_summary` and the HTML Draft Brief card only display
  `factory.brief_generator`'s readiness/advisories; the only write path
  (`factory intake suggest-brief --write`) is a separate, explicit,
  human-run CLI command the preview board never invokes. See
  `docs/brief-generator.md`.
- Does not merge or write anything for a project's Brief Update
  (Phase 32) - `brief_update_summary` and the HTML Brief Update card only
  display counts from `factory.brief_generator.merge_draft_brief()`; the
  only write path (`factory intake suggest-brief --write --update`) is a
  separate, explicit, human-run CLI command the preview board never
  invokes. See `docs/brief-generator.md`'s "Merge mode (Phase 32)".
- Does not generate CAD or invoke any engine for a project's Project
  Readiness dashboard (Phase 33) - `design_orchestrator_summary` and the
  HTML Project Readiness dashboard only display a score and a recommended
  engine *name* from `factory.design_orchestrator.evaluate_project_readiness()`;
  nothing in this board (or anything it calls) ever launches OpenSCAD,
  CadQuery, Blender, Meshy, or FreeCAD. The dashboard summarizes the
  existing detail cards below it - it removes and replaces none of them.
  See `docs/design-orchestrator.md`.

## Readiness signals are not a design-quality score

Every status this board shows - `visual_readiness_state`,
`health_signals`, and (on the project's own `factory review-gate` run,
not merged into this board - see below) `pass`/`warn`/`fail` - is a
**local artifact/readiness signal**: does the right file exist, is it
fresh, is the manifest readable. None of these are a design-quality
score, and none of them are an approval. A project can show
`slicer_review_ready` on this board while still being a rough first
draft that hasn't been checked against
`docs/design-quality-standard.md`'s "Etsy-worthy" standard.

Seeing a project reach `slicer_review_ready` here should prompt the
*human* review described in `docs/review-gate.md`'s "Human review
quality checklist" - design intent, silhouette/proportions, artifact
quality, functional fit, manufacturability, and the rest - not be
mistaken for that review having already happened.

See also `docs/visual-preview-package.md` (per-project preview package,
which this board aggregates), `docs/render-coverage.md` (the render-gap
detection `needs_render` suggestions are built on), `docs/review-gate.md`
(Phase 12 - a single-project pass/warn/fail pre-flight check built
directly on this module's `summarize_project()`, not merged into the
board itself - see that doc's "Why this isn't merged into `factory
preview-board`" section, and its "Human review quality checklist"),
`docs/design-quality-standard.md`, `docs/design-intent-brief.md` (Phase 26
- the `design_intent_summary` field above; Phase 27 - `design_intent_detail`
and the HTML Design Intent card), `docs/reference-board.md` (Phase 28 -
`reference_board_summary` and the HTML Reference Board card; Phase 29 -
the `factory reference-board` CLI), `docs/project-intake.md` (Phase 30 -
`intake_summary` and the HTML Project Intake card), `docs/brief-generator.md`
(Phase 31 - `draft_brief_summary` and the HTML Draft Brief card; Phase 32 -
`brief_update_summary` and the HTML Brief Update card),
`docs/design-orchestrator.md` (Phase 33 - `design_orchestrator_summary`
and the HTML Project Readiness dashboard), and `docs/roadmap.md` Phase 8
(board foundation) / Phase 10 (action suggestions) / Phase 11 (health
signals) / Phase 12 (review gate) / Phase 23 (human review quality
checklist) / Phase 26 (design intent visibility) / Phase 27 (design intent
preview board visualization) / Phase 28 (source discovery and reference
board planning) / Phase 29 (reference board CLI management) / Phase 30
(intelligent project intake engine) / Phase 31 (intake-to-brief draft
generation) / Phase 32 (brief update / merge workflow) / Phase 33 (project
readiness dashboard & design orchestrator).

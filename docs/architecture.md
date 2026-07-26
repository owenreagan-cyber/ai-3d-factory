# Architecture

`ai-3d-factory` is a local-first CLI (`factory`) built as a thin Python
package (`src/factory/`). There is no server, no daemon, no database, and
no network calls in Phase 0/1 — every command reads and writes local files
under the repo (mainly `projects/<slug>/`) and exits.

## Flow

```
idea/brief -> build plan -> part manifest -> CAD/assets (later phase)
  -> mesh validation -> preview rendering -> slicer review package
  -> human approval -> (future) print-ready status
```

Each stage corresponds to a CLI command and a JSON file, validated against
a schema in `schemas/`:

| Stage | Command | File | Schema |
|---|---|---|---|
| Brief | `factory init-project <name>` | `brief.json` | `project_brief.schema.json` |
| Plan | `factory plan <brief.json>` | `build_plan.json` | `build_plan.schema.json` |
| Manufacturing decision | `factory list-options <project_dir>` (read-only) then `factory choose-option <project_dir> <option_id>` | `build_plan.json`'s `selected_manufacturing_option` | `build_plan.schema.json` |
| Parts | `factory plan` seeds it; `factory choose-option` adds an `assembly_intent` summary; `factory generate-openscad` fills in CAD-time fields; manual edit for the rest | `part_manifest.json` | `part_manifest.schema.json` |
| Validation | `factory validate <mesh>` | `validation/*.json` | `validation_report.schema.json` |
| Preview | `factory render <mesh>` | `renders/*.png` | n/a |
| Preview package | `factory preview-index` (read-only) then `factory preview-project` | `preview_package/index.json`, `preview_package/preview_report.md` | n/a |
| Slicer review | (human, in Bambu Studio/OrcaSlicer) | `slicer_review/*.json` | `slicer_review.schema.json` |

`factory list-printers`/`show-printer`/`list-accessories`/`show-accessory`/
`list-materials`/`show-material`/`fleet-summary`/`check-manufacturing` sit
outside this per-project flow: they read `config/manufacturing/*.json`
directly (not a `projects/<slug>/` file) and never write anything - see
`docs/manufacturing-knowledge-base.md`.

## Package layout

- `factory/cli.py` — the Typer app; wires all commands, no business logic.
- `factory/project_store.py` — repo/project paths, slugs, JSON read/write.
- `factory/planner.py` — deterministic (non-AI) build-plan + manufacturing-advisor generator.
- `factory/router.py` — deterministic keyword-based tool routing recommendation.
- `factory/manufacturing/` — manufacturing knowledge base loader
  (`knowledge.py`), deterministic manufacturing-option decision engine
  (`decision_engine.py`), planning-time part_manifest seeding and
  assembly-intent computation (`manifest.py`), the human option-selection
  workflow (`selection.py`), read-only knowledge lookups (`inspect.py`), and
  knowledge-base internal-consistency validation (`check.py`). See
  `docs/manufacturing-knowledge-base.md`.
- `factory/validators/` — mesh geometry checks, dimension/build-volume fit,
  multi-part manifest sanity checks.
- `factory/previews/` — trimesh + matplotlib preview rendering.
- `factory/preview_package.py` — aggregates existing CAD/STL/render/manifest
  files into a project-level `preview_package/index.json` +
  `preview_report.md` (missing/stale detection, human inspection checklist).
  Never renders new images or exports geometry itself. See
  `docs/visual-preview-package.md`.
- `factory/slicer/` — read-only local slicer discovery.
- `factory/openscad/` — local, deterministic OpenSCAD source generation.
- `factory/cad/` — CAD backend registry and read-only routing
  (`backend.py`, `router.py`), and the CadQuery starter backend
  (`cadquery_backend.py`, `manifest.py`); CadQuery is an optional
  dependency this repo never installs. See `docs/cad-backends.md`.
- `factory/render_coverage.py` — read-only `stl/*.stl` vs. `renders/*.png`
  comparison for one project (missing/stale/orphan renders); the single
  shared implementation both `factory/project_inspection.py` and
  `factory/preview_package.py` call rather than reimplementing. See
  `docs/render-coverage.md`.
- `factory/project_inspection.py` — the shared, read-only, single-project
  inspection layer both `factory/preview_board.py` and
  `factory/review_gate.py` build on (extracted from `preview_board.py` in
  Phase 13 specifically to remove circular-import pressure). Its
  `summarize_project()` reads one project's `brief.json`/`build_plan.json`/
  `part_manifest.json`/`cad/`/`stl/`/`renders/`/`validation/` (reusing
  `factory/preview_package.py` and `factory/render_coverage.py`, never
  duplicating their file scans) and returns `visual_readiness_state`
  (`classify_visual_readiness()`), a deterministic `suggested_actions`
  list (advisory-only, `"safety": "manual_only"`, never executed), and a
  deterministic `health_signals` rollup (`summary` +
  `info`/`warning`/`blocked`/`ready` items, including local
  `validation/`-report-coverage checking - `factory validate` is never run
  automatically). Never writes a file. See `docs/architecture.md`'s
  "Shared inspection layer" note below.
- `factory/preview_board.py` — aggregates every project under a
  `projects_root` into one static, local `preview_board/index.json` +
  `index.html` (no server, no external assets), using
  `factory/project_inspection.py`'s `summarize_project()` for each
  project's data. This module owns only project discovery, board
  aggregation, and JSON/HTML rendering (`suggested_actions` render as
  plain `<pre><code>` blocks in a "Suggested next steps" section,
  `health_signals` in a "Health signals" section - no JavaScript, no copy
  button). See `docs/preview-board.md`.
- `factory/review_gate.py` — a read-only pass/warn/fail pre-flight check
  ("is this project ready for a **human** to review it in a slicer?")
  built directly on `factory/project_inspection.py`'s `summarize_project()`
  - it does **not** import `factory/preview_board.py`. It reads the
  already-computed `health_signals` items by `kind` and applies its own,
  purpose-specific stricter policy on top (e.g. a missing render is a hard
  blocker here, not just a warning). `pass` never implies
  `human_approved`/`print_ready` - the status ceiling stays
  `slicer_review_ready`. See `docs/review-gate.md`.
- `factory/examples_library.py` — a small, read-only, statically
  hand-maintained registry describing each example under `examples/`
  (`list_examples()`/`get_example()`); never scans `examples/` dynamically
  and never generates, renders, exports, validates, or contacts anything.
  See `docs/examples-library.md`.
- `factory/future_cloud_tools.py` — a small, read-only module that reads
  `config/future_cloud_tools.json` (`list_future_cloud_tools()`/
  `get_future_cloud_tool()`) and reports each future cloud/paid tool's
  (currently just Meshy) gate status. Never reads `.env`, never validates
  credentials, never makes a network call, and never enables anything -
  it only reports what's already recorded as disabled/future-gated. See
  `docs/meshy-approval-gate.md`.
- `factory/future_local_tools.py` — the same pattern as
  `future_cloud_tools.py`, for future *local* (non-cloud) tool
  integrations (currently just Blender): reads `config/
  future_local_tools.json` (`list_future_local_tools()`/
  `get_future_local_tool()`) and reports each tool's gate status. Never
  launches a tool, never searches the filesystem for an installed
  application, never calls `subprocess`, and never enables anything. See
  `docs/blender-local-track.md`.
- `factory/design_intent_check.py` — a small, read-only, advisory check
  (`check_design_intent_manufacturability()`): reads a `brief.json`/
  `concept_brief.json`'s optional `design_intent.manufacturability_
  constraints.max_size_mm` (Phase 24's proposed shape - see
  `docs/design-intent-brief.md`) and compares it, in every axis
  orientation (same technique `factory.validators.dimension_check`
  already uses for a real mesh), against every printer in `config/
  manufacturing/printers.json` via `factory.manufacturing.knowledge`.
  Never inspects real mesh geometry, never contacts a printer/slicer/
  network, never writes a file, and never sets `human_approved`/
  `print_ready`.

### Shared inspection layer (Phase 13)

`factory/project_inspection.py` is the single source of truth both
single-project (`review_gate`) and multi-project (`preview_board`)
surfaces read from, so the two can never silently disagree about the same
underlying facts. The dependency graph is one-directional and acyclic:

```
factory/render_coverage.py   factory/preview_package.py
             \                        /
              \                      /
             factory/project_inspection.py
              /                            \
             /                              \
factory/preview_board.py          factory/review_gate.py
```

`project_inspection.py` imports only `preview_package`/`render_coverage`/
`project_store` - never `preview_board` or `review_gate`. `preview_board.py`
still re-exports `project_inspection`'s public names
(`summarize_project`, `classify_visual_readiness`, `build_suggested_actions`,
`build_health_signals`, `VISUAL_READINESS_STATES`, `HEALTH_SEVERITIES`,
`ACTION_SAFETY`) for backward compatibility with existing
`from factory.preview_board import ...` call sites - they are the literal
same function/constant objects, not copies.

**Phase 36 addendum:** `factory/slicer_readiness.py` sits as a *third*
top-level consumer above this same layer, alongside `preview_board.py`
and `review_gate.py` - it calls `review_gate.evaluate_review_gate()`
directly (which itself already depends on `project_inspection.py`), so it
cannot be imported back into `project_inspection.py` without recreating
the exact cycle this diagram exists to avoid:

```
                     factory/project_inspection.py
                      /                            \
                     /                              \
    factory/preview_board.py          factory/review_gate.py
                     \                              /
                      \                            /
                     factory/slicer_readiness.py
```

This is why `slicer_readiness_summary` (Phase 36) is merged into each
board project's dict by `preview_board.gather_board_data()` itself,
rather than living inside `project_inspection.summarize_project()` like
every earlier phase's additive field - see `docs/slicer-readiness.md`
"Architectural note" and `docs/review-gate.md`'s Phase 36 addendum for
the full account.

**Phase 37 addendum:** `factory/manual_review_workspace.py` sits one
layer further up still - it calls `slicer_readiness.assess_slicer_readiness()`
directly, so the same cycle-avoidance applies transitively:

```
                     factory/project_inspection.py
                      /                            \
                     /                              \
    factory/preview_board.py          factory/review_gate.py
                     \                              /
                      \                            /
                     factory/slicer_readiness.py
                                  |
                     factory/manual_review_workspace.py
```

`manual_review_summary` (Phase 37) is merged into each board project's
dict the same way, at the same `preview_board.gather_board_data()`
aggregation point - see `docs/manual-review-workspace.md` "Architectural
note".

**Phase 38 addendum:** `factory/slicer_intelligence.py` sits one layer
further up still - it calls
`manual_review_workspace.assess_manual_review_workspace()` directly, so
the same cycle-avoidance applies transitively once more:

```
                     factory/project_inspection.py
                      /                            \
                     /                              \
    factory/preview_board.py          factory/review_gate.py
                     \                              /
                      \                            /
                     factory/slicer_readiness.py
                                  |
                     factory/manual_review_workspace.py
                                  |
                     factory/slicer_intelligence.py
```

`slicer_intelligence_summary` (Phase 38) is merged into each board
project's dict the same way, at the same
`preview_board.gather_board_data()` aggregation point - see
`docs/slicer-intelligence.md` "Architectural note".

**Phase 39 addendum:** `factory/slicer_history.py` sits at the very top of
this same chain - it calls
`slicer_intelligence.evaluate_slicer_intelligence()` directly, so the same
cycle-avoidance applies transitively once more:

```
                     factory/project_inspection.py
                      /                            \
                     /                              \
    factory/preview_board.py          factory/review_gate.py
                     \                              /
                      \                            /
                     factory/slicer_readiness.py
                                  |
                     factory/manual_review_workspace.py
                                  |
                     factory/slicer_intelligence.py
                                  |
                     factory/slicer_history.py
```

`slicer_history_summary` (Phase 39) is merged into each board project's
dict the same way, at the same `preview_board.gather_board_data()`
aggregation point - see `docs/slicer-analysis-history.md`. Note that
`factory/slicer_profiles.py` (Phase 39, Part 1/2) is *not* in this chain
at all - it only depends on `factory.slicer.local_slicer_probe`, so it
sits alongside `factory/manufacturing/knowledge.py` as a simple, low-level
module `factory/slicer_intelligence.py` consumes directly, with no
circular-import risk.

**Phase 40 addendum:** `factory/project_timeline.py` sits at the very top
of this same chain - it reads receipts written by
`factory.slicer_readiness`/`factory.manual_review_workspace`/
`factory.slicer_history` (via each module's own lightweight, read-only
receipt-reader function, e.g. `read_slicer_readiness_receipt()`), so the
same cycle-avoidance applies transitively once more:

```
                     factory/project_inspection.py
                      /                            \
                     /                              \
    factory/preview_board.py          factory/review_gate.py
                     \                              /
                      \                            /
                     factory/slicer_readiness.py
                                  |
                     factory/manual_review_workspace.py
                                  |
                     factory/slicer_intelligence.py
                                  |
                     factory/slicer_history.py
                                  |
                     factory/project_timeline.py
```

`timeline_summary` (Phase 40) is merged into each board project's dict
the same way, at the same `preview_board.gather_board_data()` aggregation
point - see `docs/project-timeline.md`.

## Aggregation Layer Convention

This is the standing, permanent rule the diagram above has demonstrated
five times in a row (Phases 36 through 40) - **documented once here so
future phases apply it by design, rather than re-discovering it
empirically each time.**

**Core modules may be consumed by summary/dashboard layers. Feature
modules must not import upward into aggregation layers.**

Preferred direction:

```
Core Systems
      |
      v
Summary Functions
      |
      v
Preview/Dashboard Aggregation
```

Data flows strictly one way: a core system (`project_inspection.py`,
`review_gate.py`, or any module built on them, such as
`slicer_readiness.py`) is read by a summary function
(`summarize_slicer_readiness()`, `summarize_project_timeline()`, etc.),
which is in turn read by an aggregation layer
(`preview_board.gather_board_data()`). Nothing downstream of
`project_inspection.py` ever gets imported back into it.

**Avoid, always:**

```
project_inspection
      |
      v
feature module
      |
      v
project_inspection
```

The moment any feature/summary module needs to add a per-project field to
the Preview Board, and that module (directly or transitively) depends on
`review_gate.py` or `project_inspection.py` itself, it **cannot** also be
imported *into* `project_inspection.summarize_project()` - doing so
creates a genuine circular import (confirmed empirically the first time
this came up, in Phase 36, and every time since). The fix is always the
same: add the new summary field inside
`factory.preview_board.gather_board_data()` instead, at the aggregation
point, never inside `project_inspection.py`. This is why
`slicer_readiness_summary`, `manual_review_summary`,
`slicer_intelligence_summary`, `slicer_history_summary`, and
`timeline_summary` all live on the board's per-project dict without ever
touching `project_inspection.summarize_project()`'s own return shape.

**Applies to every future phase**, not just the five above - any new
aggregation/dashboard/summary module (Phase 42's health dashboard
included) must sit *above* `project_inspection.py` in this same graph,
never be imported by it, and wire its own per-project field into
`preview_board.gather_board_data()` the same way.

## Why local-first

Every check in this repo (geometry validation, dimension fit, preview
rendering, slicer discovery) is designed to run entirely offline, using
only the local filesystem and local Python libraries (`trimesh`,
`matplotlib`, `jsonschema`). This keeps the tool safe, boring, and
reliable: nothing here can silently call out to a paid API, upload a
design, or reach a printer. See `AGENT.md` and `docs/safety-gates.md`.

## What Phase 0/1 does not do

- Generate or import 3D geometry (CAD/asset generation is Phase 2+).
- Fuse or align multi-part meshes automatically.
- Package a `.3mf` (experimental, later phase).
- Talk to a slicer, printer, or any cloud service.

See `docs/roadmap.md` for what later phases add.

## This CLI is the engine, not the final product

Everything above is a terminal-first local engine by design - fast to
build, easy to test, trivially safe to reason about. It is not the intended
long-term day-to-day experience: see `docs/product-vision.md` for the
future visual/launcher direction (Mac app launcher, local dashboard, mesh
and manufacturing-option previews, ...). That document is vision-only -
nothing in it is implemented, and every safety boundary here carries
forward unchanged into any future UI built on top of this engine.

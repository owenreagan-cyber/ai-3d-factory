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

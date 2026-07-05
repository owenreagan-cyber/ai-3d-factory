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
| Parts | (manual edit for now) | `part_manifest.json` | `part_manifest.schema.json` |
| Validation | `factory validate <mesh>` | `validation/*.json` | `validation_report.schema.json` |
| Preview | `factory render <mesh>` | `renders/*.png` | n/a |
| Slicer review | (human, in Bambu Studio/OrcaSlicer) | `slicer_review/*.json` | `slicer_review.schema.json` |

## Package layout

- `factory/cli.py` — the Typer app; wires all commands, no business logic.
- `factory/project_store.py` — repo/project paths, slugs, JSON read/write.
- `factory/planner.py` — deterministic (non-AI) build-plan stub generator.
- `factory/router.py` — deterministic keyword-based tool routing recommendation.
- `factory/validators/` — mesh geometry checks, dimension/build-volume fit,
  multi-part manifest sanity checks.
- `factory/previews/` — trimesh + matplotlib preview rendering.
- `factory/slicer/` — read-only local slicer discovery.

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

# Local example project library (Phase 14)

`examples/` is a permanent local library of example `ai-3d-factory`
projects, committed to this repo (unlike `projects/`, which is
gitignored - see the repo root `README.md`). It exists so the CAD/preview/
review-gate/preview-board workflow is demonstrated end to end without
requiring anyone to first create their own project.

## What this is not

- **Not an approval mechanism.** No example sets `human_approved` or
  `print_ready` as a real field/status value anywhere.
- **Not print-ready.** No example in this library is claimed to be ready
  to print; the highest status any example reaches automatically is
  `cad_generated`.
- **Not connected to Meshy, Blender, or any paid/cloud API.** Every file
  under `examples/` was produced locally, with no network access and no
  dependency installs.
- **Not a slicer/printer integration.** Nothing under `examples/` was
  sliced, sent to a printer, or uploaded anywhere.

## Two tiers

### Working local demo examples

`examples/simple-nameplate/` and `examples/mechanical-plate/` are real,
runnable workflow examples - every file was produced by actually running
the `factory` CLI (or, for `mechanical-plate/`, by hand-authoring a
`.scad` file the CLI is designed to accept directly, since this repo
already documents `cad/*.scad`/`cad/*.py` as human-editable, not only
generator output).

Both:

- Have a real `brief.json`, `part_manifest.json`, and `cad/` source.
- Stop at the CAD-source stage - `brief.json` status `cad_generated`, **no
  STL committed** - so they stay small, reviewable text diffs instead of
  shipping committed binary meshes.
- Are compatible with `factory preview-index`, `factory preview-project`,
  `factory review-gate`, and `factory preview-board` - none of these
  commands crash or behave differently against an `examples/` path than
  against a `projects/<slug>/` path (see `docs/architecture.md`: nothing
  in this repo actually requires `projects/`, it's just the conventional
  location).
- Currently make `factory review-gate` report **`fail`** ("No STL files
  exist yet - there is nothing to visually review in a slicer.") - this is
  correct, expected behavior, not a bug. Each example's own `README.md`
  documents the exact local commands (`openscad -o ...`, `factory
  validate`, `factory render`, `factory preview-project`) to continue it
  to `slicer_review_ready` yourself, entirely locally.

### Future / roadmap concept examples

`examples/future-organic-models/{car-concept,animal-concept,
human-figure-study}/` are concept-only placeholders for organic/freeform
modeling directions (cars, animals, people) this repo may support once a
future Blender local-automation phase (`docs/roadmap.md` Phase 18) and/or
a Meshy safety/cost approval gate (`docs/roadmap.md` Phase 15) exist.

**No CAD, mesh, render, or generated asset exists for any of them.** Each
concept directory contains only a `README.md` and a `concept_brief.json`
- deliberately **not** `brief.json`, so `factory preview-index`/
`preview-project`/`review-gate`/`preview-board` correctly report them as
missing a brief (`needs_brief`) rather than implying they're real,
progressable projects. They are not expected to pass `factory
review-gate`, and are intentionally excluded from "working example"
expectations.

## `factory list-examples` / `factory show-example <name>`

Two small, read-only, additive commands (`factory/examples_library.py`)
that inspect a small, statically hand-maintained registry describing each
example - they never scan `examples/` dynamically, never generate,
render, export, validate, or contact anything.

```bash
factory list-examples
factory show-example simple-nameplate
factory show-example future-organic-models/car-concept
```

Each entry reports:

| Field | Meaning |
|---|---|
| `path` | Path relative to the repo root. |
| `exists` | Whether that path is currently a directory on disk (a static registry entry could in principle drift from disk; this flags it). |
| `type` | `working` or `future-concept`. |
| `backend` | `openscad`, `cadquery`, `future_blender`, `future_meshy`, or `mixed` (both future organic backends are possible - see `docs/roadmap.md` Phase 15/18). |
| `status` | `demo_only`, `concept_only`, or `slicer_review_ready_possible`. |
| `safety_notes` | Plain-language notes on what was and wasn't done to build this example. |

`factory show-example` additionally prints ready-to-copy next commands
(`preview-index`/`preview-project`/`review-gate`) for `working` examples.

## Directory layout

```
examples/
├── README.md
├── simple-nameplate/           # working demo (OpenSCAD, generated via factory generate-openscad)
│   ├── README.md
│   ├── brief.json
│   ├── build_plan.json
│   ├── part_manifest.json
│   ├── cad/nameplate.scad
│   ├── cad/README.md
│   ├── slicer_review/openscad_export_instructions.md
│   └── preview_package/{index.json,preview_report.md}
├── mechanical-plate/           # working demo (hand-authored OpenSCAD)
│   └── ... (same shape as simple-nameplate/)
├── future-organic-models/      # roadmap/spec only - no CAD, mesh, or render
│   ├── README.md
│   ├── car-concept/{README.md,concept_brief.json}
│   ├── animal-concept/{README.md,concept_brief.json}
│   └── human-figure-study/{README.md,concept_brief.json}
├── gv60_plate_frame/            # pre-existing Phase 0/1 brief-only example
├── mr_reagan_nameplate/         # pre-existing Phase 0/1 brief-only example
└── simple_test_cube/            # pre-existing Phase 0/1 brief-only example
```

## Safety

Building this library used only already-installed local tools: the
`factory` CLI itself (`generate-openscad`, `preview-project`), and the
OpenSCAD binary already present on this machine (used once, outside the
repo, in a scratch path, only to confirm `mechanical_plate.scad` exports a
valid manifold solid - that check's output was not committed). No package
was installed. No network call was made. No printer, slicer, Bambu Cloud,
Meshy, or paid/cloud API was contacted. No MCP was configured. No Blender
add-on was touched.

See `AGENT.md`, `docs/safety-gates.md`, and `docs/roadmap.md` Phase 14 for
the full context.

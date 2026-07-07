# Local example project library (Phase 14, extended in Phases 15 and 19)

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

`examples/simple-nameplate/`, `examples/mechanical-plate/`,
`examples/multipart-classroom-sign/`, and `examples/storage-bin-lid/` are
real, runnable workflow examples - every file was produced by actually
running the `factory` CLI (or, for `mechanical-plate/`/
`multipart-classroom-sign/`/`storage-bin-lid/`, by hand-authoring `.scad`
files the CLI is designed to accept directly, since this repo already
documents `cad/*.scad`/`cad/*.py` as human-editable, not only generator
output).

All four:

- Have a real `brief.json`, `part_manifest.json`, and `cad/` source.
- Stop at the CAD-source stage - `brief.json` status `cad_generated`, **no
  STL/PNG committed** - so they stay small, reviewable text diffs instead
  of shipping committed binary meshes.
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

`examples/multipart-classroom-sign/` (Phase 15) is the library's first
**multi-part assembly** example: a base plate, a raised room-number text
layer, and an optional accent badge - `cad/base.scad`,
`cad/text_layer.scad`, `cad/badge.scad` - all sharing one origin per
`docs/slicer-review-workflow.md`, with a matching 3-entry
`part_manifest.json` (`shared_origin: true`, matching `transform_notes`
on every part, the badge marked `required_for_assembly: false` since it's
optional). `factory.preview_package.gather_preview_data()` correctly
reports `multipart_state.multi_part: true` for it. It exists as a
baseline pattern for richer future multi-part models (cars, animals,
people, classroom/manufacturing demos) - no built-in `factory
generate-openscad` template currently covers more than the 2-part
`multipart-nameplate` shape, so this example intentionally shows how to
hand-author a 3-part assembly using the same shared-origin convention.

`examples/storage-bin-lid/` (Phase 19) is the library's first **practical
household/classroom utility** example, using the same 3-part
shared-origin pattern: `cad/lid_panel.scad` (a rounded-rectangle lid with
a downward-facing friction-fit lip, inset from the outer edge, sized to
sit inside a storage bin's opening), `cad/raised_label.scad` (raised
label text - `"CRAYONS"` as a placeholder), and `cad/pull_tab.scad` (a
small raised grip tab along the front edge). `part_manifest.json` marks
`lid_panel` as `required_for_assembly: true` and both the label and pull
tab as `required_for_assembly: false` (optional enhancements over a bare
lid). It exists to demonstrate that the multi-part shared-origin pattern
`multipart-classroom-sign/` introduced generalizes to everyday labeled-
container objects, not just signage.

**Future working examples should keep raising this bar, not just prove a
command runs.** See `docs/design-quality-standard.md`'s "Etsy-worthy"
standard - a future richer example (once the Meshy/Blender tracks below
exist) should demonstrate a polished, intentional, gift-worthy result,
not just a technically-generated mesh.

### Future / roadmap concept examples

`examples/future-organic-models/{car-concept,animal-concept,
human-figure-study}/` are concept-only placeholders for organic/freeform
modeling directions (cars, animals, people) this repo may support once
the (not yet phase-numbered) Blender local repair/render track and/or
Meshy approval/cost-gated implementation track (`docs/roadmap.md`) are
scheduled and completed. Meshy's approval/cost gate itself was **designed
in Phase 16 but not implemented** - see `docs/meshy-approval-gate.md`.
Each `concept_brief.json` now points at `docs/meshy-approval-gate.md` and
`config/future_cloud_tools.json` directly.

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
| `backend` | `openscad`, `cadquery`, `future_blender`, `future_meshy`, or `mixed` (both future organic backends are possible - see the Meshy and Blender future tracks in `docs/roadmap.md`; Meshy's approval/cost gate was designed in Phase 16). |
| `status` | `demo_only`, `concept_only`, `slicer_review_ready_possible`, or `cad_generated` (the last used for both multi-part examples, `multipart-classroom-sign` and `storage-bin-lid` - see below). |
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
├── multipart-classroom-sign/   # working demo (hand-authored OpenSCAD, 3-part assembly)
│   ├── README.md
│   ├── brief.json
│   ├── build_plan.json
│   ├── part_manifest.json      # 3 parts: base_plate, sign_text, accent_badge
│   ├── cad/{base.scad,text_layer.scad,badge.scad,README.md}
│   ├── slicer_review/openscad_export_instructions.md
│   └── preview_package/{index.json,preview_report.md}
├── storage-bin-lid/            # working demo (hand-authored OpenSCAD, 3-part assembly)
│   ├── README.md
│   ├── brief.json
│   ├── build_plan.json
│   ├── part_manifest.json      # 3 parts: lid_panel, raised_label_text, pull_tab
│   ├── cad/{lid_panel.scad,raised_label.scad,pull_tab.scad,README.md}
│   ├── slicer_review/openscad_export_instructions.md
│   └── preview_package/{index.json,preview_report.md}
├── future-organic-models/      # roadmap/spec only - no CAD, mesh, or render
│   ├── README.md
│   ├── car-concept/{README.md,concept_brief.json}
│   ├── animal-concept/{README.md,concept_brief.json}
│   └── human-figure-study/{README.md,concept_brief.json}
├── gv60_plate_frame/            # pre-existing Phase 0/1 brief-only example
├── mr_reagan_nameplate/         # pre-existing Phase 0/1 brief-only example
└── simple_test_cube/            # pre-existing Phase 0/1 brief-only example
```

## The Meshy approval/cost gate (Phase 16)

`docs/meshy-approval-gate.md` and `config/future_cloud_tools.json`
(inspectable read-only via `factory check-future-tools`) are a **design
scaffold**, not an implementation: they exist so a future phase that adds
real Meshy calls has to satisfy an already-written checklist (explicit
human approval, a cost/budget cap, per-run confirmation, input review
before upload, output review after generation, a local storage policy,
license/ownership notes, student/privacy/data notes, a local-only
fallback, and a restatement that generated output still needs the full
validate/render/review-gate/human-review pipeline) instead of that gate
being invented under time pressure later. Meshy's `enabled` flag in
`config/future_cloud_tools.json` is `false`, and nothing in this repo can
flip it - that requires a human editing the file directly, as an explicit,
reviewed decision.

## Safety

Building this library used only already-installed local tools: the
`factory` CLI itself (`generate-openscad`, `preview-project`), and the
OpenSCAD binary already present on this machine (used a handful of times,
outside the repo, in a scratch path, only to confirm each hand-authored
`.scad` file exports a valid solid - that check's output was never
committed). No package was installed. No network call was made. No
printer, slicer, Bambu Cloud, Meshy, or paid/cloud API was contacted. No
MCP was configured. No Blender add-on was touched. No STL, PNG, or other
binary generated asset is committed anywhere under `examples/`.

See `AGENT.md`, `docs/safety-gates.md`, and `docs/roadmap.md` Phase 14/15
for the full context.

# examples/

A permanent local library of example `ai-3d-factory` projects, committed
to this repo so the workflow is demonstrated end to end without depending
on `projects/` (gitignored - see the repo root `README.md`). See
`../docs/examples-library.md` for the full write-up.

**Nothing in this directory is an approval or a print-readiness signal.**
No example here contains `human_approved: true` or `print_ready` as a
real status/field value, and no example claims automatic printing.

## Working local demo examples

Real, runnable workflow examples - every file was produced by actually
running the `factory` CLI (or, where noted, by hand-authoring a file the
CLI is designed to accept directly), entirely locally, with no network
access and no dependency installs.

- **`simple-nameplate/`** - a single-color OpenSCAD nameplate with raised
  text, built with `factory generate-openscad --template nameplate`.
- **`mechanical-plate/`** - a rounded-corner mounting plate with 4 corner
  holes, hand-authored in OpenSCAD (mirroring the built-in CadQuery
  `mechanical-plate` template's parameters, since CadQuery isn't installed
  in this environment).
- **`multipart-classroom-sign/`** - a 3-part assembly (base plate + raised
  room-number text + an optional accent badge, all sharing one origin),
  hand-authored in OpenSCAD since no built-in template covers a 3-part
  sign with a badge accent yet (only the 2-part `multipart-nameplate`
  template exists). A baseline pattern for richer future multi-part models
  (cars, animals, people, classroom/manufacturing demos) to build on.
- **`storage-bin-lid/`** - a 3-part assembly (a lid panel with a
  friction-fit lip + a raised label + a raised pull tab, all sharing one
  origin), hand-authored in OpenSCAD. A practical household/classroom
  utility example - the kind of everyday labeled-container object the
  library should keep growing toward.

All four stop at the CAD-source stage (status `cad_generated`, no STL
exported) so they stay small, reviewable text diffs rather than shipping
committed binary meshes. All four are compatible with `factory
preview-index`, `factory preview-project`, `factory review-gate`, and
`factory preview-board` - `review-gate` currently (and correctly) reports
`FAIL` for each, since there's no STL yet to visually review. Each
example's own `README.md` shows the exact local commands to continue it
to `slicer_review_ready` yourself, if you want to.

## Future / roadmap concept examples

- **`future-organic-models/`** - `car-concept/`, `animal-concept/`, and
  `human-figure-study/`: concept-only placeholders for organic/freeform
  modeling directions (cars, animals, people) this repo may support once
  a future Blender local-automation phase and/or Meshy safety/cost
  approval gate exist. **No CAD, mesh, render, or generated asset exists
  for any of these** - see `future-organic-models/README.md`.

## Pre-existing brief-only examples

`gv60_plate_frame/`, `mr_reagan_nameplate/`, and `simple_test_cube/`
predate this library structure (Phase 0/1) and remain as-is: a single
`brief.json` each (plus a `README.md` for `simple_test_cube/`), used as
starter briefs rather than full CAD-through-preview demonstrations.

## Safety

Every example in this directory was built without: Meshy execution,
OpenAI/Claude/Gemini or any other paid/cloud API call, uploads, printer
communication or discovery, Bambu Cloud, automatic printing, slicer
print/send commands, MCP, or Blender automation/add-ons. No example sets
`human_approved` or `print_ready` automatically or manually. The highest
status any example in this library reaches automatically is
`slicer_review_ready` - achievable only if you run the manual local export
steps documented in `simple-nameplate/README.md` /
`mechanical-plate/README.md` / `multipart-classroom-sign/README.md` /
`storage-bin-lid/README.md` yourself. No STL, PNG, or other binary
generated asset is committed anywhere in this directory.

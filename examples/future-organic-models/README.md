# future-organic-models/

Roadmap / spec examples only. **Nothing under this directory is a working
project, a generated model, or a printable part.** These are placeholders
that describe organic/freeform modeling directions this repo may support
once the relevant gates exist - they exist so the shape of a future
example is on record, not to demonstrate a working pipeline the way
`../simple-nameplate/` and `../mechanical-plate/` do.

## Why these are concept-only today

Everything currently implemented in `ai-3d-factory` is parametric CAD
(OpenSCAD, optionally CadQuery) - see `docs/tool-routing.md` and
`AGENT.md`'s "Prefer parametric CAD for measured parts." Cars, animals,
people, and other organic/sculptural forms are a poor fit for parametric
primitives; the intended future backends for that kind of geometry are:

- **Blender**, for freeform/organic modeling and higher-fidelity renders -
  reserved for Phase 18 ("Blender repair/render automation") and still
  requiring a local, non-interactive, add-on-free invocation. See
  `docs/roadmap.md` and `AGENT.md` ("No installing Blender add-ons").
- **Meshy**, for AI-assisted mesh generation - reserved for a dedicated
  future phase, gated behind an explicit per-use human approval step and a
  visible cost/credit estimate *before* any call is made. Off by default.
  See `docs/roadmap.md`, `docs/tool-routing.md`, and
  `docs/licensing-policy.md`.

Neither gate exists yet in this repo. Until they do, nothing under
`future-organic-models/` will be generated, rendered, or exported - each
subdirectory is a `concept_brief.json` (deliberately not `brief.json` -
see below) plus a `README.md` describing intent only.

## Why `concept_brief.json`, not `brief.json`

Every command that treats a directory as a real project
(`factory preview-index`, `factory preview-project`, `factory review-gate`,
`factory preview-board`) looks for a `brief.json` file. These
concept-only subdirectories intentionally do **not** have one, so those
commands correctly report `brief_missing` / `needs_brief` instead of
implying there's a real, progressable project here. `concept_brief.json`
holds the same kind of descriptive fields as a real brief, but under a
name no command reads automatically.

## What's here

- `car-concept/` - an original license-plate-adjacent car accessory
  concept (not a reproduction of any manufacturer part).
- `animal-concept/` - an original organic-form animal figure concept.
- `human-figure-study/` - an original organic-form human figure study
  concept.

None of these contain STL files, renders, or any generated mesh asset.
None of these are `human_approved` or `print_ready`, and none of them are
expected to pass `factory review-gate`.

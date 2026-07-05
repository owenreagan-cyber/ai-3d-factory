# Slicer review workflow

Bambu Studio (and OrcaSlicer) support importing several separate STL files
as one object with multiple parts, each keeping its own color/material
assignment. This repo's multi-part policy (see `part_manifest.json`) is
built around that workflow.

## Aligned multi-part STL workflow

1. **Export separate STL files per color/material**, not a single fused
   mesh. Each part gets its own entry in `part_manifest.json`.
2. **Keep every part on the same shared origin/coordinate system.** A part
   designed to sit at a specific position relative to the others must be
   exported without re-centering — record the alignment convention in each
   part's `transform_notes` field.
3. **Import all part STLs into Bambu Studio as one object with multiple
   parts** (drag-select all files during import, or use "Load as part"
   after importing the first file). Bambu Studio will keep them positioned
   relative to each other, provided step 2 was followed.
4. **Assign colors/materials to each part manually** in Bambu Studio's
   object list — this repo does not write slicer project files or presets.
5. **A human reviews, in the slicer**:
   - Plate layout (fits the plate, sensible orientation).
   - Colors/materials assigned correctly per part.
   - Scale (matches intended real-world measurements).
   - Orientation (matches design intent, minimizes supports where possible).
   - Supports (whether needed, and whether the auto-generated supports look
     reasonable).
6. **No auto-print.** This repo's job ends once the parts are ready for
   this human review. Nothing here invokes a slice-and-print action.

## What `factory` does and doesn't do here

- `factory validate` and `factory render` prepare per-part sanity checks
  and previews before a human opens the slicer.
- `factory report` shows whether a project has clean validation + renders
  (i.e. `slicer_review_ready`) and whether a human approval is on record.
- Nothing in this repo launches Bambu Studio/OrcaSlicer, imports files into
  it, assigns materials, or slices/prints. `factory inspect-slicer` only
  checks whether the apps are installed (see `docs/tool-routing.md`).

## Recording the review

`schemas/slicer_review.schema.json` defines the expected shape of a
completed review record: which parts were reviewed, a checklist, and a
`human_approval` block. In Phase 0/1 this file is written and filled in by
a human (or a future phase's tooling under human direction) — no `factory`
command generates or auto-approves it. `auto_print_allowed` in that schema
is hard-coded `false` and is not meant to ever change.

## 3MF packaging

Bundling multi-part projects into a single `.3mf` (which can embed
per-part color/material assignments) is a future, experimental direction —
see `docs/roadmap.md` Phase 6. It is not implemented in Phase 0/1; the
separate-aligned-STL workflow above is the supported path today.

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

## Human review checklist, before any approval

Step 5 above ("a human reviews, in the slicer") is the last local
checkpoint before `human_approved` - it should cover more than plate
layout. See `docs/review-gate.md`'s "Human review quality checklist" and
`docs/design-quality-standard.md` for the full standard; in short, before
recording an approval:

1. **Visual design review** - does it match the brief's intent (its
   `design_intent` block, if the brief has one - see
   `docs/design-intent-brief.md`, or its `description` if not)? Strong
   silhouette, clean proportions, Etsy-worthy polish (or an intentional
   style choice), not a blobby/generic/artifact look.
2. **Functional review** - does it actually do the job (hollow body and
   coin slot for a bank, correct grip force for a clip, correct fit for
   an organizer)? For anything under tension/flex (clips, hinges,
   springs), treat it as a prototype until physically tested.
3. **Manufacturing review** - wall thickness, overhangs, part splitting,
   material suitability for the part's actual use.
4. **Slicer review** - plate layout, orientation, supports, seams,
   infill, and per-part colors/materials, per the numbered steps above.
5. **Final human decision** - only a human, having actually looked at
   all of the above, records `human_approved` (and, separately and
   later, `print_ready`) - never inferred from any `factory` command's
   output.

**No automatic slicer send. No automatic print. No automatic
`human_approved` or `print_ready`** - every one of those remains an
explicit, human-initiated action outside this repo's automation, exactly
as `AGENT.md` and `docs/safety-gates.md` already require.

## 3MF packaging

Bundling multi-part projects into a single `.3mf` (which can embed
per-part color/material assignments) is a future, experimental direction
- the (not yet phase-numbered) "3MF packaging experiments track" in
`docs/roadmap.md`'s "Future tracks, not yet phase-numbered" section. It is
not implemented; the separate-aligned-STL workflow above is the supported
path today.

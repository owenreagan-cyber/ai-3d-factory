# Design intent brief fields (planning only, Phase 24)

**This document is planning only. It does not implement anything.** No
`factory` command reads, writes, requires, or validates a `design_intent`
field today. `schemas/project_brief.schema.json` is not modified by this
phase. This document exists so a future implementation has a concrete,
already-thought-through shape to build toward, instead of inventing one
under time pressure - the same spirit as `docs/meshy-approval-gate.md`
(Phase 16) and `docs/blender-local-track.md` (Phase 21).

## Why this exists

`docs/design-quality-standard.md`'s "Etsy-worthy" checklist and
`docs/review-gate.md`'s "Human review quality checklist" (Phase 23) both
ask questions like "does it match the brief?" and "does it look
intentional?" - but today's `brief.json` (`schemas/project_brief.schema.json`)
only captures `project_name`/`status`/`owner`/`intended_printer`/
`description`/`constraints`/`required_human_approval`. There's nowhere to
record *what the design was actually trying to achieve* - style, function,
proportions, materials, safety - so a human reviewer has nothing concrete
to compare the output against besides a free-text `description`. This
document proposes an additive `design_intent` object to fill that gap.

## Additive, future, optional - never a breaking change

- **Additive only.** `design_intent` would be a new, optional top-level
  key. `schemas/project_brief.schema.json` already sets
  `"additionalProperties": true`, so a `brief.json` with a `design_intent`
  block validates today, without any schema change, against every
  existing test in `tests/test_schema_files.py`.
- **Every existing `brief.json` remains valid.** None of the working
  examples (`examples/simple-nameplate/`, `examples/mechanical-plate/`,
  `examples/multipart-classroom-sign/`, `examples/storage-bin-lid/`) are
  required to add this field - see "Existing examples are not required to
  change" below.
- **No automatic `human_approved`.** Filling in `design_intent` - however
  thoroughly - never sets `human_approved`. It's input to a human review,
  not a substitute for one.
- **No automatic `print_ready`.** Same reasoning - `design_intent` shapes
  what a human checks for, it doesn't compute a pass/fail verdict.
- **Used for human review and future planning, not automatic approval.**
  A future `factory` command could *display* `design_intent` alongside
  `docs/review-gate.md`'s human review quality checklist (e.g. "does the
  output match `design_intent.style_direction`?") - it would never use
  `design_intent` to auto-approve or auto-advance a project's status. The
  highest status any command sets automatically remains
  `slicer_review_ready`, exactly as documented everywhere else in this
  repo.

## Proposed shape

```yaml
design_intent:
  quality_standard: "Etsy-worthy"    # see docs/design-quality-standard.md

  audience_or_user: "..."            # who this is for (self, gift, classroom, ...)
  use_case: "..."                    # what it's actually used for

  style_direction: ["cute", "designer-toy", "ceramic-smooth"]

  reference_inputs:
    - type: "image|sketch|text|existing_object"
      description: "..."
      local_only: true               # reference material never leaves this machine
                                      # without a separate, explicit Meshy approval
                                      # (see docs/meshy-approval-gate.md)

  visual_goals:
    silhouette: "..."
    proportions: "..."
    surface_detail: "..."
    color_material_intent: "..."

  functional_goals:
    primary_function: "..."
    required_features: ["...", "..."]
    mechanical_behavior: "none|flex|hinge|clip|snap_fit|load_bearing"
    tension_or_flex_notes: "..."     # required whenever mechanical_behavior
                                      # is anything other than "none" - see
                                      # docs/design-quality-standard.md's
                                      # functional/mechanical track

  manufacturability_constraints:
    max_size_mm: [0, 0, 0]           # [x, y, z], matches build-volume-fit
                                      # checks in factory validate
    preferred_materials: ["..."]
    avoid_supports_where_possible: true
    multipart_allowed: true
    child_safe_edges: true

  iteration_plan:
    prototype_strategy: "..."        # e.g. "print one small test piece first"
    test_points: ["...", "..."]
    acceptance_notes: "..."          # what "done" looks like for this design
```

### Field-by-field notes

- **`quality_standard`** - almost always `"Etsy-worthy"` (the one
  standard this repo defines - see `docs/design-quality-standard.md`);
  the field exists so a future project could explicitly opt into a
  different bar (e.g. `"functional prototype only, polish not required"`)
  without that being an implicit, undocumented exception.
- **`reference_inputs`** - deliberately structured as a list with an
  explicit `local_only` flag per entry. This is the natural place a
  future Meshy-track implementation would read from to decide what (if
  anything) a human has approved for upload - see
  `docs/meshy-approval-gate.md`'s "Explicit input review before upload"
  requirement. `design_intent` itself never uploads anything; it's a
  planning record.
- **`visual_goals`** - free-text on purpose. This isn't meant to be a
  measurable spec (that's `manufacturability_constraints`), it's meant to
  give a human reviewer (or a future generation step) the same mental
  picture the person writing the brief had.
- **`functional_goals.mechanical_behavior`** - a closed enum
  (`none|flex|hinge|clip|snap_fit|load_bearing`) specifically so
  "this part flexes" is a structured, checkable fact, not buried in
  prose - directly feeding `docs/design-quality-standard.md`'s
  "Functional objects under tension or repeated stress must be treated
  as prototypes until physically tested" rule and
  `docs/review-gate.md`'s "Tension/flex risk" checklist item.
- **`manufacturability_constraints`** - the bridge between "what I want"
  and "what's actually printable" - `max_size_mm` in particular is meant
  to eventually cross-check against `factory validate`'s existing
  build-volume-fit logic (`config/manufacturing/printers.json`), though
  that wiring is not implemented by this phase.
- **`iteration_plan`** - exists because `docs/design-quality-standard.md`
  explicitly rejects "first draft as deliverable" - this field is where a
  human records *how* they intend to iterate, before they start, not
  just that they will.

## Existing examples are not required to change

None of the four working examples (`simple-nameplate`, `mechanical-plate`,
`multipart-classroom-sign`, `storage-bin-lid`) need a `design_intent`
block - they're small, deliberately-scoped OpenSCAD demos, not the kind of
open-ended custom design this field is for, and retrofitting one onto each
would be noise, not signal. This phase instead adds `design_intent` to two
**concept-only** examples where it's actually illustrative:
`examples/future-organic-models/piggy-bank-design-study/concept_brief.json`
and `examples/future-functional-designs/chip-bag-clip-study/concept_brief.json`
- see each file for a worked example of the shape above. Both already use
`concept_brief.json`, not `brief.json`, so no `factory` command reads
either file as a real, in-progress project either way.

## What this phase does not do

- Does not modify `schemas/project_brief.schema.json`.
- Does not require `design_intent` anywhere, or validate its shape if
  present.
- Does not change what `factory init-project`, `factory plan`, or any
  other command reads or writes.
- Does not change `factory review-gate`'s pass/warn/fail logic -
  `review-gate` remains artifact/readiness-based (see
  `docs/review-gate.md`'s "Human review quality checklist"), not a
  design-quality judge; it does not read `design_intent` and does not
  compare output against it.
- Does not set `human_approved` or `print_ready` on anything, ever.

See also `docs/design-quality-standard.md`, `docs/review-gate.md`,
`docs/slicer-review-workflow.md`, `docs/file-lifecycle.md`,
`docs/meshy-approval-gate.md`, `docs/blender-local-track.md`,
`schemas/project_brief.schema.json`, and `AGENT.md`.

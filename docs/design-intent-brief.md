# Design intent brief fields (planning in Phase 24, first read-only check in Phase 25, visibility in Phase 26, Preview Board visualization in Phase 27)

**This document is planning-first.** Phase 24 defined the `design_intent`
shape below without implementing anything - no `factory` command read,
wrote, required, or validated it. Phase 25 added exactly one small,
read-only, advisory consumer: `factory check-design-intent` (see "The
first real consumer: `factory check-design-intent`" below) compares
`design_intent.manufacturability_constraints.max_size_mm`, if present,
against known local printer build volumes. Phase 26 added a second,
purely presentational consumer: `factory report` and the preview board
now *display* `design_intent` (quality standard, use case, style
direction, declared size, and Phase 25's manufacturability advisory) if a
brief has one, so a human doesn't have to separately run
`factory check-design-intent` to see it - see "Visibility in `factory
report` and the preview board (Phase 26)" below. Phase 27 gave that same
data a first-class visual home in the Preview Board's static HTML - a
per-project "Design Intent" card, still purely presentational - see
"Preview Board visualization (Phase 27)" below. Nothing else in this
document is implemented - `schemas/project_brief.schema.json` is still
unmodified, and no other field in `design_intent` is read by anything.
This document exists so a future implementation has a concrete,
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

## The first real consumer: `factory check-design-intent`

```bash
factory check-design-intent examples/future-organic-models/piggy-bank-design-study/concept_brief.json
factory check-design-intent path/to/brief.json --json
```

Read-only and purely advisory (`src/factory/design_intent_check.py`):
reads the given `brief.json`/`concept_brief.json`, reads
`design_intent.manufacturability_constraints.max_size_mm` if present, and
compares it (in every axis orientation, same technique
`factory.validators.dimension_check` already uses for a real mesh's
bounding box) against every printer in
`config/manufacturing/printers.json`. It reports one of seven advisory
results - `no_design_intent`, `no_max_size`, `fits_some_printers`,
`fits_no_known_printers`, `invalid_max_size`, `missing_printer_config`,
`unreadable_file` - plus which known printers fit, which don't, and
advisory warnings (e.g. an otherwise-fitting printer's spec being
unverified). It never inspects an actual mesh's real geometry (that
remains `factory validate`'s job, on a real STL); it never contacts a
printer, slicer, or network; it never writes a file; and it never sets
`human_approved` or `print_ready`. See `docs/design-quality-standard.md`'s
"Comparing output against `design_intent`" for how this fits into the
broader human review.

## Visibility in `factory report` and the preview board (Phase 26)

```bash
factory report projects/my-part          # shows a "Design Intent:" section if brief.json has one
factory preview-board projects/          # each project's index.json entry gets a compact design_intent_summary
```

`factory.design_intent_check.summarize_design_intent(file_path)` is the
new read-only helper (`src/factory/design_intent_check.py`): it reads
`design_intent.quality_standard`, `use_case`, and `style_direction` for
display, and reuses `check_design_intent_manufacturability()` unchanged
for `max_size_mm` and the manufacturability advisory - no parsing logic is
duplicated between the two. Returns `None` (not an error) whenever
`design_intent` is absent, unreadable, or not a dict.

- **`factory report`** prints a `Design Intent:` block (quality standard,
  use case, style, declared max size, and the manufacturability advisory
  result/fitting printers) whenever the project's `brief.json` has a
  `design_intent` block, immediately followed by a line stating this is
  advisory only. Prints nothing extra, and raises no error, when
  `design_intent` is absent or malformed.
- **The preview board** (`factory.project_inspection.summarize_project()`,
  consumed by both `factory preview-board` and, transitively,
  `factory review-gate`) gained one new field per project,
  `design_intent_summary` - a compact
  `{quality_standard, use_case, manufacturability_result}` object, or
  `None` if the project's brief has no `design_intent`. This field is
  purely additive to the board's JSON shape; it is never read by
  `classify_visual_readiness()`, `build_health_signals()`, or
  `build_suggested_actions()`, so it cannot change a project's
  `visual_readiness_state`, health signals, or suggested actions.
- **`factory review-gate` is unchanged.** `evaluate_review_gate()`
  constructs its own JSON output from a fixed key set and never includes
  `design_intent_summary` - the gate remains a pure artifact/readiness
  check, exactly as before Phase 26. See `docs/review-gate.md`.
- Visibility only: this does not judge creativity, approve a design,
  score anything, set `human_approved` or `print_ready`, or replace the
  Etsy-worthy/slicer/human review described in `docs/review-gate.md`'s
  "Human review quality checklist" - it only makes an existing brief field
  easier to see without a separate command.

### What Phase 26 does not do

- Does not approve designs, score designs, or mark anything
  `human_approved` or `print_ready`.
- Does not change `factory review-gate`'s pass/warn/fail logic, blocking/
  warning/ready item classification, or JSON output shape in any way -
  `review-gate` still does not read `design_intent`. See "Visibility in
  `factory report` and the preview board" above and `docs/review-gate.md`.
- Does not change `visual_readiness_state`, `health_signals`, or
  `suggested_actions` - `design_intent_summary` is a display-only field
  the board's classification logic never reads.
- Does not write anything back into `brief.json`, `build_plan.json`, or
  any other project file - `factory report` and `factory preview-board`
  remain exactly as read-only as before.
- Does not contact a printer, a slicer, or the network; does not launch
  Blender; does not call Meshy; does not install any dependency.
- Does not duplicate `design_intent` parsing logic -
  `summarize_design_intent()` reuses
  `check_design_intent_manufacturability()` for every field that function
  already parses.

## Preview Board visualization (Phase 27)

```bash
factory preview-board projects/          # index.html now shows a per-project "Design Intent" card
```

Phase 26 made `design_intent` visible in the preview board's **JSON**
(`design_intent_summary`) and in `factory report`'s text output; the board's
**HTML** kept showing only the plain summary table, health signals, and
suggested actions - a human still had to open `index.json` or run
`factory report` separately to see design intent. Phase 27 closes that gap
purely on the presentation side:

- **`factory.design_intent_check.describe_design_intent_for_board()`** - a
  new function alongside `summarize_design_intent()`, reusing
  `check_design_intent_manufacturability()` the same way. Adds three fields
  `summarize_design_intent()` intentionally doesn't read:
  `reference_input_count` (the length of the optional
  `design_intent.reference_inputs` list), `design_notes` (the optional
  `design_intent.iteration_plan.acceptance_notes`), and `warnings` (the
  same advisory warnings `check_design_intent_manufacturability()` already
  computes). `summarize_design_intent()` itself is untouched.
- **`design_intent_detail`** - a new, additive field on each preview-board
  project entry (`factory.project_inspection.summarize_project()`), built
  from the function above. `design_intent_summary` (Phase 26) keeps its
  exact three-field shape unchanged; `design_intent_detail` is a new
  sibling field, not a replacement, with the same `None`-when-absent
  semantics and the same non-classifying guarantee (never read by
  `classify_visual_readiness()`, `build_health_signals()`, or
  `build_suggested_actions()`).
- **The board's HTML** gained a per-project overview card, rendered right
  after the state-count summary and before the existing table: Project
  Header, Design Intent (Quality/Purpose/Style/Design notes), Manufacturing
  Overview (manufacturing status, selected option, design-intent
  manufacturability fit, reference input count, warnings/advisories),
  Artifacts (CAD/STL/Render present-or-missing badges), Health Signals (a
  compact pointer to the existing detailed section), and Review Readiness
  (a Review Ready / Review Not Ready badge). Every field renders a clear
  fallback ("Not specified"/"None"/"Unknown") instead of ever being left
  blank - most projects have no `design_intent` block, which renders one
  explanatory line instead of empty rows. Static HTML/CSS only - no
  JavaScript, no external assets, no CDN, no tracking.
- The existing summary table, "Health signals" section, and "Suggested
  next steps" section are all unchanged and still follow the cards -
  nothing was removed, only added above it. See `docs/preview-board.md`.

### What Phase 27 does not do

- Does not change `schemas/project_brief.schema.json` or the
  `design_intent` shape documented above - it only reads fields the shape
  already documents (`reference_inputs`, `iteration_plan.acceptance_notes`).
- Does not change `design_intent_summary`'s shape - `design_intent_detail`
  is a new, additive sibling field.
- Does not approve designs, score designs, or mark anything
  `human_approved` or `print_ready`.
- Does not change `visual_readiness_state`, `health_signals`, or
  `suggested_actions` - `design_intent_detail` is display-only, exactly
  like `design_intent_summary`.
- Does not change `factory review-gate`'s JSON output shape - it still
  never includes `design_intent_summary` or `design_intent_detail`.
- Does not remove or restructure the existing summary table, "Health
  signals" section, or "Suggested next steps" section.
- Does not add JavaScript, external assets, a CDN dependency, or tracking
  of any kind to the board's HTML.
- Does not contact a printer, a slicer, or the network; does not launch
  Blender; does not call Meshy; does not install any dependency.
- Does not duplicate `design_intent` parsing logic -
  `describe_design_intent_for_board()` reuses
  `check_design_intent_manufacturability()` for every field that function
  already parses.

## What Phase 25 does not do

- Does not modify `schemas/project_brief.schema.json`.
- Does not require `design_intent` anywhere. `factory check-design-intent`
  reads it if present and reports `no_design_intent` (a normal, non-error
  advisory result, not a failure) if not.
- Does not validate `design_intent`'s shape beyond the one field
  `factory check-design-intent` reads
  (`manufacturability_constraints.max_size_mm`) - every other proposed
  field above remains unread by any command.
- Does not change what `factory init-project`, `factory plan`, or any
  other pre-existing command reads or writes.
- Does not change `factory review-gate`'s pass/warn/fail logic -
  `review-gate` remains artifact/readiness-based (see
  `docs/review-gate.md`'s "Human review quality checklist"), not a
  design-quality judge; it does not read `design_intent` and does not
  compare output against it. `factory check-design-intent` is a
  deliberately separate, optional command - not a new requirement folded
  into `review-gate`.
- Does not contact a printer, discover printers, contact a slicer, or
  make any network call.
- Does not set `human_approved` or `print_ready` on anything, ever.

See also `docs/design-quality-standard.md`, `docs/review-gate.md`,
`docs/preview-board.md` (Phase 26's `design_intent_summary` field),
`docs/slicer-review-workflow.md`, `docs/file-lifecycle.md`,
`docs/meshy-approval-gate.md`, `docs/blender-local-track.md`,
`schemas/project_brief.schema.json`, and `AGENT.md`.

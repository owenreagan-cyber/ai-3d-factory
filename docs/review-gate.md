# Local review gate (Phase 12)

`factory review-gate <project_dir>` answers one narrow, deterministic
question: **does this project have everything a human needs on disk to
sit down and review it in a slicer?** It reads local files only and
returns `pass`, `warn`, or `fail` - a pre-flight check before opening a
project in Bambu Studio/OrcaSlicer, so Owen doesn't discover a missing
render or a corrupt manifest only after opening the slicer.

## What this is not

- **Not an approval mechanism.** `pass` means only "ready for human
  slicer review" - never `human_approved`, never `print_ready`. The
  status ceiling this gate ever names is `slicer_review_ready`.
- **Not a validator.** It never runs `factory validate` - it only checks
  whether a `validation/<name>_validation.json` report already exists.
- **Not a renderer.** It never runs `factory render` - it only checks
  whether `renders/<name>_preview.png` already exists and is fresh.
- **Not connected to a printer, slicer, or cloud.** It never discovers,
  contacts, or sends anything to a printer or slicer, and makes no
  network calls.
- **Not a Blender or Meshy integration.**
- **Read-only.** It never writes, modifies, or deletes any file, in the
  project or anywhere else.

## Usage

```bash
factory review-gate projects/my-part           # human-readable report
factory review-gate projects/my-part --json     # machine-readable JSON
```

Exit code is `0` for `pass`/`warn`, `1` for `fail` - convenient for
scripting a quick pre-flight check without parsing output.

This works against any directory shaped like a project, not only
`projects/<slug>/` - e.g. `factory review-gate examples/simple-nameplate`
correctly reports `fail` ("No STL files exist yet"), since that committed
example intentionally stops at the CAD-source stage. See
`docs/examples-library.md`.

## Human review quality checklist

Passing `factory review-gate` means only: **ready for human slicer
review.** It does not mean any of the following, and never will
automatically:

- `human_approved`
- `print_ready`
- Etsy-worthy
- safe for use
- durable
- food-safe
- child-safe
- ready to sell
- ready to print

`review-gate` is a **local artifact-presence check** - it confirms the
files a human needs (brief, manifest, STL, fresh renders, a validation
report) exist and aren't stale or corrupt. It has no opinion on whether
the design itself is any good - see `docs/design-quality-standard.md`
for that standard. A `pass` result and a genuinely well-designed part are
two different questions; a project can `pass` this gate while still
being a rough first draft that needs another iteration pass.

Before Owen (or anyone) approves anything, the actual human review should
cover:

- **Design intent** - does it match the brief? If `brief.json` has a
  structured `design_intent` block (see `docs/design-intent-brief.md`,
  Phase 24 - style direction, visual/functional goals, manufacturability
  constraints, an iteration plan), compare against that directly; if not,
  compare against the project's `description`/`constraints` as today.
- **Silhouette/proportions** - does it look intentional, not accidental?
- **Etsy-worthy quality** - polished, useful, gift-worthy/display-worthy
  where appropriate (see `docs/design-quality-standard.md`).
- **Artifact quality** - no blobby/generic/random-AI look, unless that
  look was an intentional style choice.
- **Functional fit** - does it actually solve the problem it's for?
- **Manufacturability** - wall thickness, overhangs, supports, part
  splitting.
- **Material suitability** - does the chosen material fit the part's
  actual use?
- **Assembly fit**, for multipart projects - do the parts actually align
  at their shared origin (see `docs/slicer-review-workflow.md`)?
- **Tension/flex risk**, for clips/hinges/springs and other parts under
  repeated stress - see `docs/design-quality-standard.md`'s functional/
  mechanical track; these remain prototypes until physically tested.
- **Safety/usage concerns** - sharp edges, choking hazards, food contact,
  anything context-specific (classroom, gift, display).
- **Slicer preview** - orientation, supports, seams, infill, color/
  material plan, once actually opened in Bambu Studio/OrcaSlicer.
- **Prototype/iteration plan** - is this the finished part, or does it
  need another pass?

None of this is automated, checked, or scored by `review-gate` or any
other `factory` command - it is exactly as advisory as the existing
human visual inspection checklist in `docs/visual-preview-package.md`.
`review-gate`'s job ends at confirming the files exist to *have* this
review; having the review is still entirely a human act. This holds even
if `brief.json` has a `design_intent` block (`docs/design-intent-brief.md`)
- `review-gate` does not read, parse, or compare against `design_intent`;
it remains a purely artifact/readiness-based check, never a
design-quality judge, regardless of how much intent a brief records.

## How it reuses existing logic

`factory.review_gate.evaluate_review_gate()` is a thin layer over
`factory.project_inspection.summarize_project()` (Phase 8-11 logic,
extracted into its own module in Phase 13 - see `docs/architecture.md`) -
it does not re-derive brief/manifest/render/validation status itself, and
does not import `factory.preview_board`. It reads the
already-computed `health_signals` items **by `kind`** and applies its own
pass/warn/fail policy on top, because this gate's purpose (readiness for
human slicer review specifically) is narrower and in one place stricter
than the board's general-purpose visual-readiness health check:

- On the preview board, a missing render is only a `"warning"` (the fix
  is simple: run `factory render`). For this gate, a missing render is a
  **hard blocker** - there's nothing to visually review in a slicer
  without a render yet.
- Everything else (missing/unreadable brief, unreadable manifest, stale
  renders, an unreadable preview package, orphan renders, missing
  validation, an unselected manufacturing option) keeps the same
  blocking/warning classification the health signals already use.
- "No STL files at all" is checked directly (not from a health-signal
  `kind` - the board doesn't have a distinct signal for this, it's
  implied by `visual_readiness_state` instead) and is always a hard
  blocker for this gate.

Because the gate reads `summarize_project()`'s output rather than
re-scanning files, it can never disagree with what the preview board
already shows for the same project - the two are always looking at the
same underlying facts, just applying different, purpose-specific
policies on top.

## Result semantics

| `result` | Meaning |
|---|---|
| `fail` | At least one hard blocker - project is missing a required local artifact or has unreadable/corrupt data. Not ready to open in a slicer for review yet. |
| `warn` | No hard blockers, but at least one advisory item (see below) should be addressed first. |
| `pass` | No blockers and no warnings - project appears ready for human slicer review. **Still not an approval, still not print-ready.** |

### Hard blockers (`result: "fail"`)

- Missing `brief.json`
- Unreadable `brief.json`
- Unreadable `part_manifest.json`
- No STL files at all
- At least one STL file has no matching render
- At least one render is older than the STL it previews
- A preview-package-flagged missing/stale visual artifact (manifest-aware
  cases render coverage's directory-only view can't see)
- Unreadable `preview_package/index.json` (if one exists on disk)

### Warnings (`result: "warn"`, not blocking)

- Missing `part_manifest.json` (present-but-empty is fine; genuinely
  absent is a warning, not a blocker)
- No manufacturing option selected yet (`factory choose-option`)
- At least one STL has no local validation report yet
- An orphan render (no matching STL currently on disk) - advisory only,
  never blocking
- `preview_package/index.json` doesn't exist yet, but was computed live
  instead (same read-only fallback the board and `factory preview-index`
  already use)

### Ready items (positive signals, never blocking)

- STL files are present
- Every STL has a matching, up-to-date render
- A validation report exists (per mesh that has one)
- `preview_package` data is available (persisted or computed live)
- `slicer_review_ready` (from the board's own classification)

## JSON shape

```jsonc
{
  "project_dir": "projects/my-part",
  "gate": "human_slicer_review",
  "result": "warn",
  "status_ceiling": "slicer_review_ready",
  "summary": "No blocking issues, but 1 advisory item(s) should be addressed before human slicer review.",
  "blocking_items": [],
  "warning_items": [
    {
      "kind": "validation_missing",
      "severity": "warning",
      "message": "1 STL file(s) have no local validation report yet. Run `factory validate` manually for each mesh before trusting geometry.",
      "suggested_action_kind": "validate_mesh_manual"
    }
  ],
  "ready_items": [
    {"kind": "stl_files_present", "severity": "info", "message": "1 STL file(s) present.", "suggested_action_kind": null},
    {"kind": "all_renders_fresh", "severity": "info", "message": "Every STL file has a matching, up-to-date render.", "suggested_action_kind": null},
    {"kind": "slicer_review_ready", "severity": "ready", "message": "...", "suggested_action_kind": "review_slicer_manually"}
  ],
  "suggested_actions": [
    {
      "kind": "validate_mesh_manual",
      "label": "Run local geometry validation",
      "command": "factory validate projects/my-part/stl/part.stl",
      "safety": "manual_only",
      "reason": "stl/part.stl has no local validation report yet - run `factory validate` manually before trusting this mesh's geometry."
    }
  ],
  "notes": [
    "This gate only determines readiness for HUMAN slicer review.",
    "Passing this gate is not an approval and not a print-readiness signal.",
    "..."
  ]
}
```

`suggested_actions` is passed through directly from
`factory.project_inspection.build_suggested_actions()` - the same
deterministic, `"safety": "manual_only"` action list the preview board
itself shows for
this project. Nothing in `review_gate` (or anything it calls) ever
executes one of these commands.

## Why this isn't merged into `factory preview-board`

At Phase 12, `review_gate` called `factory.preview_board.summarize_project()`
directly, which meant wiring a compact `review_gate` field back into each
board card would have required `preview_board.py` to import from
`review_gate.py` while `review_gate.py` already imported from
`preview_board.py` - a circular module import. Phase 13 resolved that by
extracting the shared inspection logic (`summarize_project()`,
`classify_visual_readiness()`, `build_health_signals()`,
`build_suggested_actions()`) into `factory.project_inspection` - both
`preview_board.py` and `review_gate.py` now depend on that module
independently, and `review_gate.py` no longer imports `preview_board.py`
at all (see `docs/architecture.md`'s "Shared inspection layer" note).

The circular-import blocker is gone, but `review_gate` still isn't merged
into board cards - that remains a deliberate scope decision (not a
technical necessity) so each phase stays small and reviewable. Run
`factory review-gate` alongside `factory preview-board` for now; a future
phase could add a compact `review_gate` field to board cards cheaply,
since both already sit on the same shared layer.

See also `docs/preview-board.md` (the board this reuses),
`docs/render-coverage.md`, `docs/architecture.md`,
`docs/design-quality-standard.md` (the human review quality checklist
above), `docs/visual-preview-package.md`, and `docs/roadmap.md` Phase 12
(this command) / Phase 13 (the shared-layer refactor) / Phase 23 (the
human review quality checklist).

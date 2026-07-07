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

## How it reuses existing logic

`factory.review_gate.evaluate_review_gate()` is a thin layer over
`factory.preview_board.summarize_project()` (Phase 8-11) - it does not
re-derive brief/manifest/render/validation status itself. It reads the
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
`factory.preview_board.build_suggested_actions()` - the same deterministic,
`"safety": "manual_only"` action list the preview board itself shows for
this project. Nothing in `review_gate` (or anything it calls) ever
executes one of these commands.

## Why this isn't merged into `factory preview-board`

`factory.preview_board.summarize_project()` already computes everything
`review_gate` needs, and `review_gate` calls it directly. Wiring a compact
`review_gate` field back into each board card, however, would require
`preview_board.py` to import from `review_gate.py` while `review_gate.py`
already imports `summarize_project` from `preview_board.py` - a circular
module import. Rather than work around that with a deferred/lazy import
(a design smell not worth taking on for a "nice to have" field), Phase 12
keeps `review_gate` as an independent, single-project command. Run
`factory review-gate` alongside `factory preview-board` for now; a future
phase could resolve this cleanly by extracting the shared classification
into a third module both depend on, if that turns out to be worth doing.

See also `docs/preview-board.md` (the board this reuses),
`docs/render-coverage.md`, and `docs/roadmap.md` Phase 12.

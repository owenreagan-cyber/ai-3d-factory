# Unified Project Timeline & Event Model (Phase 40)

`factory.project_timeline` is the Factory's project memory - a read-only,
chronological event log derived entirely from systems that already
exist:

```
generation_receipt.json -> export_receipt.json ->
slicer_readiness_receipt.json -> manual_review_workspace_receipt.json ->
slicer_analysis_history.json -> brief.json's status_history ->
Unified Project Timeline
```

## This is not a new receipt system

**It stores nothing new for derived events.** Every event is computed
fresh, on every call, by reading whatever receipts already exist. It
never writes a receipt of its own for anything a receipt already
records, and it can never disagree with the systems it reads - if it
ever does, that's a bug in this module, never grounds to "correct" the
underlying receipt.

The only thing that persists across calls is
`brief.json["status_history"]` (see `factory.project_store.advance_status()`),
which is an additive extension of a file this repo already owns, not a
new store - see "Where the timeline's data comes from" below.

## Reuses rather than duplicates

- `factory.generation_gate.read_last_execution_receipt()` (Phase 34)
- `factory.export_pipeline.read_export_receipt()` (Phase 35)
- `factory.slicer_readiness.read_slicer_readiness_receipt()` (Phase 36)
- `factory.manual_review_workspace.read_workspace_receipt()` (Phase 37)
- `factory.slicer_history.read_analysis_history()`/`detect_changes()`
  (Phase 39 - `detect_changes` is a public alias for that module's own
  `_detect_changes()`, added specifically for this reuse, mirroring the
  same alias convention `factory.slicer_readiness` already established
  in Phase 37)
- `factory.project_inspection.HEALTH_SEVERITIES` (Phase 13) - the exact
  existing `info`/`warning`/`blocked`/`ready` vocabulary, reused verbatim
  as this module's `severity` field rather than inventing a second one

## Event model

```python
TimelineEvent = {
    "event_id": str,        # deterministic: sha256(source + timestamp + label)[:16]
    "timestamp": str | None, # ISO 8601, verbatim from the source receipt/snapshot; None only
                              # for an "unavailable" placeholder event (see below)
    "date": str | None,      # "YYYY-MM-DD", derived from timestamp, for day-grouping
    "category": str,         # fixed vocabulary - see below
    "status": str,           # "completed" | "changed" | "recorded" | "unavailable"
    "severity": str,         # "info" | "warning" | "blocked" | "ready" (HEALTH_SEVERITIES, reused)
    "label": str,            # short human-readable line, e.g. "STL exported: stl/part.stl"
    "source": str,           # which system produced this event
    "detail": str | None,    # optional longer note
}
```

**`status` and `severity` are two independent axes, on purpose.**
`status` describes what *kind* of fact the event represents (a stage
finished, a value changed, an action was explicitly recorded, or a
stage's timestamp is unavailable); `severity` describes how much
attention it deserves (reusing the exact vocabulary
`factory.project_inspection.build_health_signals()` already uses, rather
than inventing a second severity scale). A `⚠` in the CLI means
`severity in ("warning", "blocked")`; a `✓` means `ready`/`info`; a `?`
means `status == "unavailable"`.

**Event categories** (a fixed, closed set - every category here is
actually produced by a real adapter; none is a placeholder for a future
source that doesn't exist yet): `brief`, `manufacturing_plan`, `cad`,
`export`, `validation`, `preview`, `approval`, `package`, `workspace`,
`slicer_analysis`, `material_change`, `printer_change`, `risk_change`,
`warning_change`.

## Where the timeline's data comes from

| Adapter | Reads | Produces |
|---|---|---|
| `_events_from_status_history()` | `brief.json`'s `status`/`status_history` | one event per early-pipeline stage reached (`brief_created`, `plan_drafted`, `plan_approved`, `manufacturing_option_selected`, `cad_generated`) |
| `_events_from_generation_receipt()` | `generation_receipt.json` | one `cad` event (preferred over the status_history-derived one, when present - richer engine/template detail) |
| `_events_from_export_receipt()` | `export_receipt.json`'s per-file records | one `export` + one `validation` + one `preview` event per exported file |
| `_events_from_slicer_readiness_receipt()` | `slicer_readiness_receipt.json` | `approval`/`package` events |
| `_events_from_workspace_receipt()` | `manual_review_workspace_receipt.json` | one `workspace` event |
| `_events_from_slicer_history()` | `slicer_analysis_history.json` | one `slicer_analysis` event per saved snapshot, plus `material_change`/`printer_change`/`risk_change`/`warning_change`/(`export`|`cad`)-as-changed events between *consecutive* saved snapshots |

Later export-pipeline stages (`mesh_exported`, `geometry_validated`,
`dimension_validated`, `preview_rendered`, `slicer_review_ready`) are
deliberately **not** derived from `status_history` - they're already
covered more precisely by the `export_receipt`/`slicer_readiness`
adapters, and duplicating them from the coarser status field would add a
redundant, less detailed second event for the same fact.

## "Unavailable" is never "empty"

`brief.json`'s early pipeline stages had no timestamp trail anywhere in
this repo until this phase. `project_store.advance_status()` now
appends `{"status": ..., "at": ...}` to `brief["status_history"]`
whenever a status genuinely changes - **append-only, never
retroactive**. An existing project whose `brief.json` predates this
field (or that skipped a stage entirely, e.g. jumping straight from
`plan_drafted` to `manufacturing_option_selected`) simply has no
`status_history` entry for that stage.

When a project has clearly **reached** a stage (per its current
`status`) but has no timestamped `status_history` entry for it, this
module emits an explicit event with `status: "unavailable"`,
`timestamp: None`, `severity: "info"` - it never silently omits the
stage as if it hadn't happened, and never invents a timestamp for it. A
stage the project genuinely has **not yet reached** produces no event at
all (correctly absent, not "unavailable" - those are different signals).

```python
# default_brief() seeds the very first entry for any project created
# after this phase shipped - not retroactive, just the first genuine one:
{"status_history": [{"status": "brief_created", "at": "2026-...Z"}]}
```

## Ordering

Undated ("unavailable") events sort first, in early-pipeline stage
order; dated events follow, sorted by timestamp ascending. The CLI
groups dated events by day (`July 27`) and undated events under a single
"Date unavailable" heading shown first.

## The CLI

```bash
factory timeline <project_dir> [--json]
```

**Entirely read-only - there is no write flag, and no `--history` flag**
(the whole command is inherently historical; a separate flag for that
would be redundant, per this phase's own review). Human-readable output
groups events by day; `--json` returns the full flat, sorted event list.

Example:

```
Project Timeline

Date unavailable

? Brief created (date unavailable - project predates history tracking)
? CAD generated (date unavailable - project predates history tracking)

July 27

✓ STL exported: stl/part.stl
✓ Validation completed
✓ Preview rendered

July 28

⚠ Material changed
✓ Review package created

This is a read-only view of existing receipts - it never writes, generates,
exports, validates, invokes a slicer, or contacts a printer/network.
```

## JSON contract

`--json` is the entire stdout, never mixed with plain text: `{"events":
[...], "errors": [], "no_automatic_print": true}` on success; on a
missing project directory, `{"errors": [...], "no_automatic_print":
true}` with exit code 1.

## Preview Board integration

### Architectural note

Same reasoning as every Phase 36-39 summary field - see the "Aggregation
Layer Convention" in `docs/architecture.md`. `factory.project_timeline`
reads receipts written by `factory.slicer_readiness`/
`factory.manual_review_workspace`, which transitively import
`factory.review_gate`, which already imports
`factory.project_inspection.summarize_project()`. Adding
`timeline_summary` inside `project_inspection.py` would recreate the same
circular import. `factory.preview_board.gather_board_data()` calls
`summarize_project_timeline(project_dir)` directly per project instead.

### The card

A compact "Project Timeline" card, placed right after "Slicer
Intelligence": total event count, the latest dated event (if any), and a
"Tracking: Partial - N early stage(s) predate history tracking" note
whenever any unavailable events exist. A project with zero events shows
a single explanatory line rather than an empty section. This card never
derives an event itself - the full chronological list lives in
`factory timeline <project>`, not on the board.

`summarize_project_timeline()`'s fields: `event_count`,
`dated_event_count`, `unavailable_event_count`, `latest_event` (`{label,
date, category}` or `None`).

## Failure handling

A malformed `brief.json` degrades to `[]` for the status_history adapter
rather than raising; a malformed receipt from any other adapter degrades
the same way (each adapter's underlying `read_*()` function already
handles this - see each source module's own failure handling). A project
with no receipts at all yet returns an empty event list, not an error.

## Limitations

- **No timestamp source exists yet for intake, design intent, or
  reference board** - only the five stages this module's adapters cover
  have real receipt-backed timestamps. A future phase could add one if a
  genuine timestamp source for those stages is ever built; this module
  will not invent one in the meantime.
- **`status_history` is append-only and never retroactive** - a project
  that skipped a stage, or predates this phase entirely, has a
  permanently incomplete history for that stage; nothing backfills it.
- **Change-detection events (Part 4) only compare *consecutive* saved
  snapshots** - inherited directly from `factory.slicer_history`'s own
  scope; this module does not compute a "diff since 3 saves ago."
- **This module has no write path of its own** - the only new
  persistence in this phase is `status_history`, an additive extension
  of `brief.json` that already existed.

## Non-goals

- **No AI, no LLM, no machine learning of any kind.**
- **No network calls.**
- **Never invokes a slicer, generates G-code, or contacts a printer.**
- **Never re-scores readiness, risk, or approval** - every fact is read
  verbatim from the system that already computed it.
- **Never becomes authoritative** - if this module's rendering of an
  event ever disagrees with the receipt it came from, the receipt is
  correct.

See also `docs/slicer-analysis-history.md` (Phase 39),
`docs/slicer-intelligence.md` (Phase 38),
`docs/manual-review-workspace.md` (Phase 37),
`docs/slicer-readiness.md` (Phase 36), `docs/architecture.md`
("Aggregation Layer Convention"), `docs/preview-board.md`, and
`docs/roadmap.md` Phase 40.

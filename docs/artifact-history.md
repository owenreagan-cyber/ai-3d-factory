# Artifact History & Diff Planning (Phase 41)

`factory.artifact_history` is a safe, read-only artifact version history
and comparison system, built directly on Phase 40's unified timeline:

```
Receipts -> Phase 40 project_timeline.py -> Phase 41 artifact_history.py
-> Diff Reports -> Rollback Plans (report only, never executed)
```

**This phase is about understanding change - not restoring files.** It
answers "what changed, when, and what would a rollback affect" without
ever modifying anything. There is no write path anywhere in this module.

## Artifact History is a VIEW, never authoritative

The hierarchy is:

```
Source Artifact -> Receipt/Manifest/Snapshot -> Timeline ->
Artifact History View -> Diff Reports
```

If this module's rendering of a version or diff ever disagrees with the
receipt/timeline event it came from, **the receipt/timeline is correct -
this module has a bug.** Nothing here ever "corrects" the underlying
record.

## This is not a new receipt system

**Version numbers are derived, never stored.** A version is simply the
1-based ordinal of an artifact-relevant timeline event, in chronological
order. There is no `artifact_versions.json` counter file and no hidden
mutable state - re-running `factory.project_timeline.get_project_timeline()`
and this module's own derivation always reproduces the exact same version
numbering for the exact same underlying receipts.

## Reuses rather than duplicates

- `factory.project_timeline.get_project_timeline()` (Phase 40) - the
  single source of event ordering, identity, and (additively, Phase 41)
  per-event artifact fingerprints. This module never re-scans a receipt
  independently; every fingerprint it uses was already attached to a
  timeline event by Phase 40's own adapters, each of which already reused
  the underlying receipt's own already-recorded fingerprint field.
- `factory.slicer_history.detect_changes()` (Phase 39) indirectly - the
  `material_change`/`printer_change`/`risk_change`/`warning_change`
  timeline events Phase 40 already derived from it are reused directly
  here (by timestamp range), never re-invoked a second time.
- The exact `sha256:<hex digest>` fingerprint convention established in
  Phase 35/37 (`factory.slicer_readiness.file_fingerprint()`/
  `relative_path()`) - no new hash function, no new path normalization,
  no new artifact identity rule.

## How Phase 40's timeline feeds this phase

Phase 40's `TimelineEvent` was extended additively with a `fingerprints`
field (`dict[str, str]`, empty by default), populated by each adapter
from data it already has in scope - no new file reads, no new hashing:

| Event category | Fingerprints come from |
|---|---|
| `cad` | none (the generation receipt carries no fingerprint of its own) |
| `export` | `export_receipt.json`'s per-record `source_fingerprint`/`output_fingerprint` |
| `approval` | `slicer_readiness_receipt.json`'s `artifact_fingerprints` |
| `package` | `slicer_readiness_receipt.json`'s `package.artifact_fingerprints` |
| `workspace` | `manual_review_workspace_receipt.json`'s `artifact_fingerprints` |
| `slicer_analysis` | `slicer_analysis_history.json`'s per-snapshot `artifact_fingerprints` |

`validation` and `preview` timeline events (also derived from
`export_receipt.json`) carry **no fingerprint of their own** - the export
receipt never stores one for those sub-steps. Their fingerprints only
ever enter `get_artifact_history()`'s cumulative view once a later
`approval`/`package`/`workspace`/`slicer_analysis` event backfills them.

## Version derivation

```python
VERSION_EVENT_CATEGORIES = ("cad", "export", "validation", "preview", "approval", "package", "workspace")
```

`get_artifact_history(project_dir)` filters Phase 40's timeline to these
categories, then walks them in chronological order building a
**cumulative** fingerprint dict - each version folds in every fingerprint
recorded by that event and every event before it. A version's shape:

```python
{
    "version_id": int,              # 1-based ordinal, derived, never stored
    "timestamp": str, "date": str,
    "source_event_id": str, "source_event_category": str, "source_event_label": str,
    "artifacts": {category: [rel_path, ...]},   # non-empty categories only
    "fingerprints": {rel_path: "sha256:..."},   # cumulative up to this version
    "artifact_count": int,
    "validation_state": str,        # latest validation event's label at/before this version
    "preview_state": str,           # same, for preview
    "review_state": str,            # same, for approval/package/workspace, or "Pending"
}
```

`ARTIFACT_CATEGORIES` classifies a fingerprinted relative path using this
repo's own existing directory conventions (`docs/file-lifecycle.md`) -
never a new scheme: `cad/` -> `cad`, `stl/` -> `stl`,
`validation/` -> `validation`, `renders/` -> `preview`,
`part_manifest.json` -> `manifest`, `build_plan.json` -> `build_plan`,
`slicer_review/`/`manual_review/` -> `review_package`.

`get_artifact_snapshot(project_dir, version_id)` returns one version (or
`None`). `get_artifact_history_for_path()` is the CLI's entry point.

## Diff planning

```python
diff_artifact_versions(project_dir, from_version, to_version)
```

Compares two versions' cumulative fingerprint dicts category by category
(a path present in one but not the other, or present in both with a
different fingerprint, counts as changed). It then reuses - **never
re-derives** - Phase 39/40's own already-detected
`material_change`/`printer_change`/`risk_change`/`warning_change`
timeline events, by checking whether one falls within the two versions'
timestamp range, and separately checks whether a prior approval is
invalidated between the two versions (mirroring
`factory.slicer_readiness`'s own live invalidation rule, applied here to
two historical versions instead of live files). `Brief`/`Design
Intent`/`Reference Board` are never tracked by this module at all - they
always report as unchanged. Raises `UnknownVersionError` for a
`version_id` that doesn't exist, rather than silently comparing against
`None`. Returns:

```python
{
    "from_version": int, "to_version": int,
    "changed": [str, ...], "unchanged": [str, ...],
    "impact": "Requires slicer review." | "No re-review needed - artifacts are identical.",
    "dry_run": True, "no_automatic_print": True,
}
```

## Rollback planning - report only

```python
build_rollback_plan(project_dir, to_version)
```

Reuses `diff_artifact_versions()` directly (diffing `to_version` against
the current latest version) - the "what would change" question is
identical whether framed as a forward diff or a rollback plan, so there
is no second comparison implementation. Returns:

```python
{
    "current_version": int, "target_version": int,
    "would_affect": [str, ...], "would_not_affect": [str, ...],
    "action": "Manual review required. No files changed.",
    "dry_run": True,
    "no_files_restored": True, "no_files_copied": True,
    "no_files_deleted": True, "no_manifest_modified": True,
    "no_automatic_print": True,
}
```

**This never restores, copies, or deletes a file, and never modifies a
manifest.** Actual file restoration would be a future, separately
approved capability - not part of this phase.

## The CLI

```bash
factory artifact-history <project_dir> [--json]
factory artifact-diff <project_dir> --from VERSION --to VERSION [--json]
factory artifact-rollback-plan <project_dir> --to VERSION [--json]
```

All three are entirely read-only - there is no write flag on any of
them. An unknown version passed to `--from`/`--to` exits with code 1 and
a clean error (JSON: `{"errors": [...], "no_automatic_print": true}`,
same shape as every other read-only command in this repo).

Example:

```
Artifact History

Project:
demo-sign

Version 1

CAD generated

Validation: Not yet reached
Preview: Not yet reached
Review: Pending

Version 5

Human approval recorded

Cad:
cad/sign.scad

Stl:
stl/sign.stl

Validation: Passed
Preview: Rendered
Review: Human approval recorded

This is a read-only view - it never writes, restores, copies, or deletes a file,
and never invokes a slicer or contacts a printer/network.
```

## JSON contract

Same convention as every other read-only command in this repo - `--json`
is the entire stdout, never mixed with plain text:

- `artifact-history --json`: `{"versions": [...], "errors": [], "no_automatic_print": true}`
- `artifact-diff --json`: the `diff_artifact_versions()` dict plus `"errors": []`
- `artifact-rollback-plan --json`: the `build_rollback_plan()` dict plus `"errors": []`

On a missing project directory or unknown version, all three return
`{"errors": [...], "no_automatic_print": true}` with exit code 1.

## Preview Board integration

### Architectural note

Same reasoning as every Phase 36-40 summary field - see the "Aggregation
Layer Convention" in `docs/architecture.md`. This module calls
`factory.project_timeline.get_project_timeline()`, which reads receipts
written by `factory.slicer_readiness`/`factory.manual_review_workspace`,
which transitively import `factory.review_gate`, which already imports
`factory.project_inspection.summarize_project()`. Adding
`artifact_history_summary` inside `project_inspection.py` would recreate
the same circular import. `factory.preview_board.gather_board_data()`
calls `summarize_artifact_history(project_dir)` directly per project
instead.

### The card

A compact "Artifact History" card, placed right after "Project
Timeline" and before "Project Intake": version count, latest version
number, a short list of what changed since the previous version (or
"None" if nothing did, omitted entirely if there's no previous version
to compare against yet), and a "Rollback: Plan available" row. A project
with no artifact-relevant timeline events yet shows a single explanatory
line rather than an empty section. This card never derives a version or
computes a diff itself for display purposes - the full version list,
diff, and rollback plan live in `factory
artifact-history`/`artifact-diff`/`artifact-rollback-plan`, not on the
board.

`summarize_artifact_history()`'s fields: `history_available`,
`version_count`, `latest_version`, `changed_since_previous` (`None` when
there's no earlier version to diff against, a list otherwise),
`current_artifact_state` (`{validation, preview, review}`).

## Failure handling

A project with no artifact-relevant timeline events yet returns an empty
version list, not an error - every public function degrades the same way
every Phase 36-40 read-only function does (each ultimately depends on
`factory.project_timeline.get_project_timeline()`'s own already-hardened
failure handling for malformed receipts).

## Limitations

- **A category with only ever one occurrence in the underlying receipt
  (`cad`/`export`/`validation`/`preview`/`approval`/`package`/`workspace`
  are all single overwrite-in-place records, not per-occurrence lists)
  cannot show a "before vs after" *content* change once it has already
  occurred once.** Re-triggering the same action (e.g. calling
  `record_approval()` a second time) doesn't append a new timeline event
  for that category - it overwrites the existing one in place, so
  `get_artifact_history()`'s recomputed position for that category always
  reflects its *current* state, no matter when a caller captured that
  version's integer `version_id`. Concretely: if you read `v1 =
  get_artifact_history(...)[-1]["version_id"]` right after an approval,
  then re-approve later, a subsequent `diff_artifact_versions(project,
  v1, v2)` call resolves `v1` *fresh* at diff time - which now means "the
  latest approval," not "the approval as it was when you read `v1`." The
  only way to compare a genuinely earlier state against a later one is to
  anchor the earlier reference to a category that is provably never
  re-triggered between the two moments (e.g. `cad`'s generation-receipt
  event, which this repo's own test suite anchors to for exactly this
  reason - see `tests/test_artifact_history.py`), or to a **new**
  category reached for the first time (e.g. `package`, if it never
  existed before).
- **Version numbers are positions, not frozen snapshots.** They are
  recomputed fresh on every call to `get_artifact_history()`/
  `diff_artifact_versions()`; nothing in this module caches a version's
  content across calls. This is intentional (per this phase's own
  "derived, never stored" requirement) but means a `version_id` captured
  earlier in a script and reused later can silently resolve to different
  content if the underlying receipt changed in between - see above.
- **`validation`/`preview` categories never carry their own fingerprint**
  - detecting that their *content* changed requires a later
  `approval`/`package`/`workspace`/`slicer_analysis` event to have
  backfilled a new fingerprint at that path; there is no way to diff two
  validation reports directly against each other.
- **No file restoration** - rollback planning is a report only. Actual
  restoration (copying an older STL/CAD file back into place) is
  explicitly out of scope for this phase and would be a future,
  separately approved capability.
- **This module has no write path of its own** - it introduces no new
  persistence at all, not even an additive one (contrast with Phase 40's
  `status_history`).

## Non-goals

- **No AI, no LLM, no machine learning of any kind.**
- **No network calls.**
- **Never invokes a slicer, generates G-code, or contacts a printer.**
- **Never restores, copies, or deletes a file, and never modifies a
  manifest** - there is no write path anywhere in this module, including
  in the "rollback plan" command.
- **Never re-scores readiness, risk, or approval** - every fact is read
  verbatim from the timeline events that already computed it.
- **Never becomes authoritative** - if this module's rendering of a
  version or diff ever disagrees with the receipt/timeline event it came
  from, the receipt/timeline is correct.

See also `docs/project-timeline.md` (Phase 40),
`docs/slicer-analysis-history.md` (Phase 39),
`docs/slicer-intelligence.md` (Phase 38),
`docs/manual-review-workspace.md` (Phase 37),
`docs/slicer-readiness.md` (Phase 36), `docs/architecture.md`
("Aggregation Layer Convention"), `docs/preview-board.md`, and
`docs/roadmap.md` Phase 41.

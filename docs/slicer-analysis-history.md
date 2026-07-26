# Slicer Analysis History and Change Comparison (Phase 39, Part 3/4)

`factory.slicer_history` is a lightweight, local, append-only history of
explicitly-saved Slicer Review Intelligence snapshots, answering one
question: **"What changed since the last review?"**

```
Slicer Readiness -> Manual Review Workspace -> Slicer Review Intelligence
-> Slicer-Aware Review Profiles -> Analysis History -> Human Slicer Review
-> (never automatic printing)
```

## History is observational

**It does not control workflow. It does not approve anything.** Nothing
in this module ever affects `factory.slicer_readiness`'s
`readiness_status`, ever records or invalidates approval, ever triggers
slicing, or ever triggers printing. It is purely a record of what a past
analysis looked like, for a human to compare against.

## Persistence is explicit only

`save_analysis_snapshot()` is the **only** function in this module (or
anywhere in this phase) that writes anything, and it is only ever called
by `factory slicer-inspect --save-analysis` - never automatically:

- **Not** during `factory preview-board` generation.
- **Not** during a plain `factory slicer-inspect` call (with or without
  `--json`).
- **Not** during `--history` or `--compare` (both entirely read-only).
- **Not** during any readiness/approval check
  (`factory.slicer_readiness`/`factory.review_gate` never call into this
  module at all).

Reading history (`read_analysis_history()`, `compare_slicer_analysis()`,
`summarize_slicer_history()`) is always safe and side-effect-free.

## Reuses rather than duplicates

- `factory.slicer_intelligence.evaluate_slicer_intelligence()` (Phase 38)
  - the live analysis a snapshot captures.
- `factory.slicer_readiness.summarize_slicer_readiness()` (Phase 36) - the
  readiness summary embedded in each snapshot.
- `factory.slicer_readiness.file_fingerprint()`/`relative_path()` (public
  aliases added in Phase 37 for exactly this kind of cross-module reuse) -
  the same `sha256:<hex digest>` artifact fingerprint convention every
  prior phase's receipt already uses. No new hashing scheme.
- `factory.export_pipeline.read_export_receipt()` - the current set of
  source/output files to fingerprint.

## Where history lives

`generated/slicer_analysis_history.json` - a fifth sibling of Phase
34/35/36/37's own receipts (`generation_receipt.json`,
`export_receipt.json`, `slicer_readiness_receipt.json`,
`manual_review_workspace_receipt.json`), but shaped differently on
purpose: those four each track only the *current* state of one thing;
this one is an **append-only array** of every snapshot ever explicitly
saved (`{"project": ..., "snapshots": [...]}`), since answering "what
changed" requires keeping more than just the latest state.

## Snapshot model

Each saved snapshot:

| Field | Meaning |
|---|---|
| `timestamp` | When this snapshot was saved. |
| `project` | Project name. |
| `analysis_type` | Always `"slicer_intelligence"` - reserved for future snapshot types. |
| `artifact_fingerprints` | `sha256:` fingerprints of every current CAD/STL file plus `part_manifest.json`/`build_plan.json`. |
| `readiness_summary` | Verbatim `factory.slicer_readiness.summarize_slicer_readiness()` output. |
| `slicer_intelligence_summary` | `{risk_level, build_volume_fit, confidence}` - a compact extract, not the full analysis. |
| `printer_id` / `printer_display_name` | The resolved target printer at save time (or `None`). |
| `materials` | Each part's material string, in manifest order. |
| `detected_slicer_names` | Which supported slicers were locally detected at save time. |
| `slicer_profile_name` | The slicer profile name active at save time (Phase 39, Part 1). |
| `risk_level` / `confidence` | Duplicated at the top level too, for convenient direct comparison. |
| `warnings` | Every warning `evaluate_slicer_intelligence()` reported at save time. |

## Change comparison

`compare_slicer_analysis(project_dir)` compares a **fresh, live**
analysis against the **most recently saved** snapshot - never two
historical snapshots against each other. This answers "what's different
right now", not "what changed between two past saves." Detected change
categories:

| Category | Detected by comparing |
|---|---|
| **STL changed** | Any `stl/`-path fingerprint. |
| **CAD changed** | Any `cad/`-path (`.scad`/`.py`) fingerprint. |
| **Printer changed** | `printer_id`. |
| **Material changed** | The full `materials` list (order-sensitive). |
| **Validation changed** | `readiness_summary.validation_status`. |
| **Risk changed** | `risk_level`. |
| **Slicer environment changed** | The set of `detected_slicer_names`. |
| **Warnings changed** | The set of `warnings`. |

If no history exists yet, `compare_slicer_analysis()` reports
`history_available: False` and a recommendation to run
`--save-analysis` first - never a crash, never a guessed baseline.

Example:

```
Slicer Intelligence Comparison

Previous:
Risk: Low

Current:
Risk: Moderate

Changes:
⚠ STL changed
⚠ Warnings changed

Recommendation:
Human review recommended - re-check the change(s) above before proceeding.
```

## Compact summary for Preview Board / project inspection

`summarize_slicer_history(project_dir)` is deliberately different from
`compare_slicer_analysis()`: it compares only the **two most recent
saved** snapshots (never a live analysis, never a write) - cheap enough
to compute on every Preview Board render:

| Field | Meaning |
|---|---|
| `history_available` | Whether any snapshot has ever been saved. |
| `latest_analysis` | `{timestamp, risk_level, confidence}` of the most recent saved snapshot, or `None`. |
| `previous_analysis` | Same shape, for the second-most-recent snapshot - `None` if fewer than two snapshots exist. |
| `changes_detected` | Count of change categories between those two snapshots - `None` if fewer than two exist. |
| `risk_change` | `"<previous> -> <current>"` if `risk_level` differs between them, else `None`. |

## The CLI

```bash
factory slicer-inspect <project> [--json]
factory slicer-inspect <project> --history [--json]
factory slicer-inspect <project> --compare [--json]
factory slicer-inspect <project> --save-analysis [--json]
```

- Default (no flags) and `--history`/`--compare` are entirely read-only.
- `--save-analysis` is the only write path - appends one snapshot and
  reports its path/count; combines with the default analysis output
  (the human-readable/JSON payload also includes what was just saved).
- `--history` lists every saved snapshot's timestamp/risk/confidence.
- `--compare` shows the live-vs-last-saved comparison above.

## JSON contract

Each mode's `--json` output is the entire stdout, never mixed with plain
text: default mode returns `evaluate_slicer_intelligence()`'s full model
plus `save_result` (populated only when `--save-analysis` was also
passed) and `errors`; `--history` returns `{"snapshots": [...], "errors":
[], "no_automatic_print": true}`; `--compare` returns
`compare_slicer_analysis()`'s full result plus `errors`.

## Failure handling

A missing or malformed `generated/slicer_analysis_history.json`
(`read_analysis_history()`) degrades to `[]` rather than raising - a
corrupted history file never blocks saving a fresh one, and never
crashes `--compare`/`--history`/the Preview Board.

## Limitations

- **History-to-history comparisons only look at the two most recent
  saves** (`summarize_slicer_history()`) - inspecting the full history
  timeline requires `--history` (or reading the JSON file directly).
- **No automatic pruning** - `generated/slicer_analysis_history.json`
  grows with every explicit `--save-analysis` call; there is no
  built-in retention policy.
- **Material/printer change detection is exact, not semantic** - e.g.
  reordering parts in `part_manifest.json` without changing any material
  would still report "Material changed" (the comparison is
  order-sensitive), by design (simplicity over cleverness).

## Non-goals

- **No AI, no LLM, no machine learning of any kind.**
- **No network calls.**
- **Never invokes a slicer, generates G-code, or contacts a printer.**
- **Never affects readiness, approval, or any hard blocker.**
- **Never writes automatically** - explicit `--save-analysis` only.

See also `docs/slicer-intelligence.md` (Phase 38), `docs/slicer-profiles.md`
(Phase 39, Part 1/2), `docs/manual-review-workspace.md` (Phase 37),
`docs/slicer-readiness.md` (Phase 36), and `docs/roadmap.md` Phase 39.

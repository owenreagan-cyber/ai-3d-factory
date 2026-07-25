# Slicer Review Readiness Promotion and Review Package (Phase 36)

`factory.slicer_readiness` is the formal bridge between Phase 35's
completed export/validate/render pipeline and human slicer review:

```
Guided Export Pipeline -> STL Validation and Preview -> Artifact
Finalization -> Slicer Review Readiness -> Human Approval -> Manual
Slicer Review -> (never automatic printing)
```

**This is a thin assessment/promotion layer over already-computed
state.** It never re-implements mesh validation, render-freshness
checking, review-gate logic, slicer detection, artifact fingerprinting,
manifest-completeness checks, or manufacturing checks. It reads:

- `factory.project_inspection.summarize_project()` - already reusing
  Phase 8-35's own logic (`export_pipeline_summary`,
  `generation_gate_summary`, `generation_execution_summary`,
  `health_signals`, `render_coverage`, `design_orchestrator_summary`).
- `factory.review_gate.evaluate_review_gate()` - the existing
  pass/warn/fail human-slicer-review gate, never rewritten here.
- `factory.slicer.local_slicer_probe.probe_slicers()` - existing
  read-only local slicer discovery.
- `factory.manufacturing.manifest.compute_assembly_intent()` - existing
  multipart-status logic.

...and combines them into one deterministic readiness assessment, score,
and (only with explicit confirmation) a local review package conforming
to the pre-existing `schemas/slicer_review.schema.json`.

## Read-only unless explicitly writing

`assess_slicer_readiness(project_dir)` never writes anything, never
invokes a subprocess, and never launches a slicer. Only two functions
write, and only when explicitly called:

- `record_approval(project_dir, note=..., approved_by=...)` - records
  human approval. Gated behind the CLI's `--approve` flag.
- `create_review_package(project_dir, output_dir=..., overwrite=...)` -
  writes the review package. Gated behind the CLI's `--create-package
  --confirm-package` (both required together).

## Technical readiness vs. human approval

These are two separate, never-conflated states. A project can satisfy
every technical signal (`readiness_status == "ready_for_review_package"`
is *reachable*) and still have no approval recorded - approval is always
a separate, explicit, human-recorded action. It is automatically
invalidated the moment a relevant artifact's fingerprint changes; a stale
approval is never silently trusted.

## Decision states

`READINESS_STATES` (11 total), evaluated by
`_evaluate_readiness_status()` in a fixed priority order - first match
wins, mirroring the exact style of `factory.generation_gate` and
`factory.export_pipeline.plan_export()`:

1. **`blocked`** - Review Gate itself returned `"fail"` (a hard blocker
   there always wins first, before this module's own checks); or any STL
   failed validation; or the manifest's assembly intent is
   `multipart_incomplete`.
2. **`not_ready`** - no expected STL at all, or the current STL count is
   zero with some still missing and none stale.
3. **`stale_artifacts`** - any STL or preview is stale relative to its
   source.
4. **`not_ready`** (again) - some required STL are still missing (not
   covered by the stale check above).
5. **`needs_validation`** - validation hasn't run for every current STL
   yet.
6. **`needs_preview`** - a required preview render is missing.
7. **`needs_manifest_completion`** - `part_manifest.json` is missing or
   unreadable, unresolved material/color, or an unresolved target
   printer.
8. **`needs_information`** - every physical artifact checks out, but
   Phase 33's Design Orchestrator readiness_state is `"Not Ready"` (a
   much rarer, lower bar - overall score < 25% - than its ordinary,
   common `"Needs Information"` resting state, which is folded into
   `warnings` only and never gates progression).
9. **`needs_human_approval`** - every technical signal is satisfied but
   no approval is recorded (or approval was invalidated).
10. **`ready_for_review_package`** - approved and technically ready, no
    package created yet (or the existing one is stale).
11. **`review_package_created`** - approved, technically ready, and a
    current package exists.

`ready_for_slicer_review` is `True` only for states 10 and 11
(`_READY_STATES`) - never derived from the score.

### Review Gate's stricter blocking shadows some states in practice

`factory.review_gate` treats a few conditions as **hard blockers**
(`render_missing`, `render_stale`, `manifest_unreadable`, zero STL files
at all) that this module's own ladder also independently checks lower
down. In the real pipeline, review_gate's check runs first (step 1
above), so - for example - a project with a corrupted manifest after an
otherwise-complete export reports `"blocked"` (from Review Gate), not
this module's own `"needs_manifest_completion"` branch. The ladder still
handles these states correctly in isolation (see
`tests/test_slicer_readiness.py`'s direct `_evaluate_readiness_status()`
unit tests) - they exist for robustness and any future loosening of
Review Gate's own policy, even though today's Review Gate makes a subset
of them effectively unreachable through the CLI. This is a discovered
interaction, not a bug: the two modules are allowed to disagree (Review
Gate documents this itself), and this module's priority order correctly
defers to Review Gate's stricter verdict first.

## Readiness scoring

A documented, weighted, capped 0-100 score - **purely informational,
never used to bypass a hard blocker.** `readiness_status` (and therefore
`ready_for_slicer_review`) is computed entirely independently of the
score in `_evaluate_readiness_status()`; a failed validation still
reports `blocked` no matter how high every other category scores.

| Category | Weight | What it measures |
|---|---|---|
| STL | 25% | Fraction of expected STL that are current. |
| Validation | 25% | Mean of per-file validation points (passed=1.0, passed-with-warnings=0.7, failed/unavailable/not-run=0.0). |
| Preview | 15% | Fraction of expected previews that are current. |
| Manifest | 15% | Assembly-intent completeness (`single_piece_ready`/`multipart_ready`=100, `multipart_incomplete`=50, `no_option_selected`=25, readable-but-uncomputed=60, unreadable=0). |
| Manufacturing | 10% | Mean of material/color resolution fraction and printer-resolved (100/0). |
| Receipts | 5% | 50 points each for a present generation receipt and export receipt. |
| Review gate | 5% | Review Gate's own result (`pass`=100, `warn`=60, `fail`=0). |

Weights sum to exactly 1.0. The overall score is `round(sum(sub_score *
weight))`.

## Multi-part and multi-color handling

Multipart status (`manifest["assembly_intent"]`) is read directly from
`factory.manufacturing.manifest.compute_assembly_intent()` - never
re-derived. `multipart_incomplete` is a hard blocker (state 1 above);
`multipart_ready`/`single_piece_ready` are not. Material and color
resolution is read from each part's `material`/`color` field in
`part_manifest.json`, using the exact `"TBD - human decision"` /
`"unknown"` / `"unresolved"` placeholder convention already established
in this repo - an unresolved value is a warning (folds into
`needs_manifest_completion`), never a hard blocker. The human review
checklist (`build_review_checklist()`) adds multi-material/AMS-slot-
mapping items only when the manifest's own part count is greater than
one - never invented for a single-piece project.

## Artifact freshness and approval invalidation

Every write path shares one fingerprint snapshot function
(`_snapshot_artifact_fingerprints()`), fingerprinting every source CAD
file, current STL, validation report, and render the export receipt
knows about, plus `part_manifest.json`/`build_plan.json` - using the same
`sha256:<hex digest>` convention `factory.export_pipeline` already
established (never re-derived independently).

- **Approval invalidation**: `record_approval()` snapshots fingerprints
  at approval time. `assess_slicer_readiness()` re-fingerprints on every
  call and reports `approval_status: "invalidated"` the instant any
  recorded file is missing or its content has changed - an approval is
  never silently trusted past a source change.
- **Package staleness**: `create_review_package()` snapshots its own
  fingerprint set at package-creation time (recorded in the readiness
  receipt's `package` block); `package_status` reports `"stale"` the same
  way once any of those files change.

## Local slicer detection

`assess_slicer_readiness()` calls `factory.slicer.local_slicer_probe.probe_slicers()`
directly - never re-implemented. Slicer presence/absence is **advisory
only**: a project can still reach `ready_for_review_package` and have a
package created with no local slicer detected at all (an advisory note is
added, nothing more). This module never launches a detected slicer, never
opens a file in one, and never queries it beyond the existing read-only
probe.

## Human approval

`record_approval(project_dir, *, note=None, approved_by=None)`:

- Raises `ApprovalNotAllowedError` unless `readiness_status` is already
  `needs_human_approval`, `ready_for_review_package`, or
  `review_package_created` - approval is never recordable on a
  blocked/not-ready project.
- Writes only `generated/slicer_readiness_receipt.json`'s `approval`
  block (upserted - never destroys an existing `package` block from a
  prior write).
- Never invokes a slicer, never creates a print job, never implies print
  authorization.

## Review package creation

`create_review_package(project_dir, *, output_dir=None, overwrite=False)`:

- Raises `PackageNotAllowedError` unless `readiness_status` is
  `ready_for_review_package` or `review_package_created` (technically
  ready *and* approved).
- Raises `PackageCollisionError` if a package already exists and
  `overwrite=False` - an existing package is never silently replaced.
- Writes `slicer_review/slicer_review_manifest.json`, validated against
  the pre-existing `schemas/slicer_review.schema.json` (not a new,
  invented shape) - `project_name`, `status`, `parts_for_review`,
  `human_checklist`, `human_approval`, `auto_print_allowed` (always
  `false`), plus this phase's own readiness/fingerprint/warning fields.
- Writes a human-readable `slicer_review/README.md` with the same
  checklist, a warnings section, and the no-automatic-print declaration.
- **References existing STL/validation/render files by relative path -
  never copies them**, mirroring `factory.preview_package`'s own
  established "reference, don't duplicate" convention. Copying artifacts
  into a portable package remains a possible future extension, explicitly
  deferred - see "Limitations" below.
- Never touches source CAD, STL, validation, or render files.

## Preview Board integration

### Architectural note: why `slicer_readiness_summary` isn't on `summarize_project()`

Every other Phase 26-35 additive board field lives directly on
`factory.project_inspection.summarize_project()`, because
`project_inspection.py` is the shared base layer those phases sit below.
This phase is different: per its own requirement to consume the existing
Review Gate result without rewriting it, `assess_slicer_readiness()` must
call `factory.review_gate.evaluate_review_gate()` directly - and
`review_gate.py` itself already imports `summarize_project()`. Adding a
`slicer_readiness_summary` field computed via this module *inside*
`project_inspection.py` would therefore create a genuine circular import
(`project_inspection -> slicer_readiness -> review_gate ->
project_inspection`) - **confirmed empirically** while building this
phase (a temporary import was added, `python -c "import
factory.project_inspection"` failed with exactly that circular-import
error, then the file was restored byte-for-byte and the diff verified
clean).

`factory.slicer_readiness` instead sits **above**
`project_inspection.py` in the dependency graph - a top-level consumer,
like `review_gate.py` and `preview_board.py` already are, not beneath it.
`factory.preview_board.gather_board_data()` calls
`summarize_slicer_readiness(project_dir)` directly per project and merges
the result into that project's dict alongside every other summary - the
same visible per-project field as an additive `project_inspection` field,
from a different, architecturally necessary layer.

### The card

`factory.preview_board.build_board_html()` renders a compact "Slicer
Review Readiness" card, placed right after "Post-Generation Pipeline"
(all four meta-cards - Project Readiness, Generation Gate,
Post-Generation Pipeline, Slicer Review Readiness - summarize what's
possible next). Shows: status (badged), score, human-approval status
(badged), review-package status (badged), blocker count, warning count,
and the next suggested action. Purely presentational - it never
assesses, approves, or creates a package itself; it never opens a slicer;
every field is exactly what `summarize_slicer_readiness()` already
computed read-only.

`summarize_slicer_readiness()`'s fields: `status`, `score`,
`ready_for_package`, `human_approval_required`, `approval_status`,
`stl_status`, `validation_status`, `preview_status`, `manifest_status`,
`package_status`, `blocker_count`, `warning_count`, `next_action`.

## The CLI

```bash
factory slicer-readiness <project_dir> [--json]
    [--create-package] [--confirm-package] [--output-dir ...]
    [--approve] [--approval-note ...]
    [--refresh] [--include-warnings] [--force-package]
```

- Read-only by default: always computes and prints a full assessment,
  writes nothing.
- `--approve [--approval-note "..."]` records human approval (see
  above) - fails cleanly (`errors`, exit 1) via `ApprovalNotAllowedError`
  if not yet technically ready.
- `--create-package` requires `--confirm-package` together (an error,
  exit 1, if `--create-package` is passed alone) - and requires prior
  approval; `--force-package` allows overwriting an existing package.
- `--output-dir` overrides the default `slicer_review/` package location.
- `--refresh` is accepted for explicitness but is inert - the assessment
  is always freshly computed regardless.
- `--include-warnings` prints every warning message in full; without it,
  only a count is shown (`N (pass --include-warnings to list them)`).
- Human-readable output ends with an explicit "No slicer was opened." /
  "No file was uploaded." / "No print was started." trailer, matching
  this repo's "no automatic printing" convention everywhere else.

### Example: not yet ready

```
Slicer Review Readiness

Project:
storage-bin-lid-example

Technical readiness:
blocked

Readiness score:
4%

STL files:
0 current / 3 required
...
Blocking reasons:
- No STL files exist yet - there is nothing to visually review in a slicer.

No slicer was opened.
No file was uploaded.
No print was started.
```

### Example: technically ready, awaiting approval

```
Slicer Review Readiness

Project:
demo-sign

Technical readiness:
needs_human_approval

Readiness score:
88%
...
Human approval:
Required

Review package:
Not Created

Next actions:
- Review the assessment, then run `factory slicer-readiness <project> --approve` once satisfied.

No slicer was opened.
No file was uploaded.
No print was started.
```

## JSON contract

`--json` is the entire stdout on every path, including every error
(missing project directory, `--create-package` without
`--confirm-package`, `ApprovalNotAllowedError`, `PackageNotAllowedError`,
`PackageCollisionError`) - never mixed with plain text before or after.
Top-level fields mirror `assess_slicer_readiness()`'s ~35-field result
(`project_path`, `project_name`, `readiness_status`, `readiness_score`,
`readiness_sub_scores`, `ready_for_slicer_review`,
`human_approval_required`, `approval_recorded`, `approval_status`,
`approval_note`, STL/validation/preview/manifest counts and statuses,
`multipart_status`, `material_status`, `printer_status`,
`export_receipt_status`, `generation_receipt_status`,
`manufacturing_status`, `review_gate_status`, `blockers`, `warnings`,
`advisories`, `next_actions`, `local_slicer_status`, `detected_slicers`,
`package_available`, `package_status`, `package_path`, `dry_run`,
`no_automatic_print`), plus this CLI's own `project`, `approval_result`,
`package_result`, `errors`.

## Failure handling

Every failure mode resolves to a structured, honest outcome rather than a
crash or false success: missing project directory (CLI-level `errors` +
exit 1, clean JSON); malformed `part_manifest.json`/`build_plan.json`
(`needs_manifest_completion`/`blocked`, never a crash);
malformed/missing `generated/slicer_readiness_receipt.json`
(`read_slicer_readiness_receipt()` returns `None` rather than raising,
approval/package both report their "not present" state);
`--create-package` without `--confirm-package` (rejected before touching
disk); approval attempted before technical readiness
(`ApprovalNotAllowedError`, nothing written); package creation attempted
before approval or while blocked (`PackageNotAllowedError`, nothing
written); package creation attempted over an existing package without
`--force-package` (`PackageCollisionError`, the existing package is left
untouched - never partially overwritten); no local slicer detected
(advisory only, never blocks anything).

## Limitations

- **References, never copies, package artifacts** - a fully portable/
  self-contained package (copying STL/validation/render files alongside
  the manifest) is a deliberate future option, not yet built; see
  "Not yet started" in `docs/roadmap.md` Phase 36.
- **One current approval/package state, not an append-only history** -
  the readiness receipt reflects only the current approval and package
  state, same convention as Phase 34/35's own execution receipts.
- **Review Gate's stricter blocking policy shadows a subset of this
  module's own ladder states in the real pipeline today** - see "Review
  Gate's stricter blocking shadows some states in practice" above. This
  is an intentional deference to Review Gate's existing, documented
  policy, not a bug.
- **The human review checklist is tailored from known project data
  only** - it never infers a checklist item this project's own manifest/
  intake data doesn't support.

## Non-goals

- **No AI, no LLM, no machine learning of any kind.**
- **No network calls, no web search, no scraping.**
- **Never invokes a slicer, opens a file in one, uploads anything, queues
  a print job, or contacts a printer.** `auto_print_allowed` is always
  `false`.
- **Never invokes Blender, Meshy, or FreeCAD.**
- **Never installs anything.**
- **Never re-implements mesh validation, render-freshness checking,
  review-gate logic, slicer detection, artifact fingerprinting,
  manifest-completeness checks, or manufacturing checks** - each is read
  directly from its existing module.
- **Never sets `human_approved` or `print_ready`** - this repo's ceiling
  everywhere remains `slicer_review_ready`.

See also `docs/export-pipeline.md` (Phase 35), `docs/generation-gate.md`
(Phase 34), `docs/review-gate.md`, `docs/preview-board.md`,
`docs/slicer-review-workflow.md`, `docs/file-lifecycle.md`, and
`docs/roadmap.md` Phase 36.

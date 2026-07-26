# Manual Review Workspace (Phase 37)

`factory.manual_review_workspace` is the Factory's first true pre-slicer
review workspace - it organizes everything a human needs before opening
Bambu Studio, OrcaSlicer, or another slicer:

```
Guided Export Pipeline -> STL Validation and Preview ->
Slicer Review Readiness -> Human Approval -> Review Package ->
Manual Review Workspace -> Human Slicer Review ->
(never automatic printing)
```

Phase 36 (`docs/slicer-readiness.md`) determines that a project is
**technically ready**. Phase 37 does not re-determine readiness - it
**organizes** everything a human needs, on top of that already-computed
assessment: printer/material profile inspection, a structured
multi-category review checklist, and a deterministic confidence/risk
pair.

**This phase does NOT slice, does NOT generate G-code, and does NOT
print.** It only prepares an organized local review workspace.

## This is a thin organizing layer over already-computed state

It never re-implements mesh validation, the artifact registry, the
preview package, Review Gate logic, slicer discovery, or receipt
tracking. It reuses:

- `factory.slicer_readiness.assess_slicer_readiness()` directly - itself
  already reusing `factory.project_inspection.summarize_project()`,
  `factory.review_gate.evaluate_review_gate()`, and
  `factory.slicer.local_slicer_probe.probe_slicers()`.
- `factory.manufacturing.knowledge` - the existing local printer/material
  reference data (`config/manufacturing/printers.json`/`materials.json`),
  never a second lookup table.

It adds two genuinely new things this repo did not have before:

1. **Printer/material profile inspection** - what's actually known
   locally about the project's target printer and materials, always
   reporting `"Unknown"` rather than inventing a value that isn't
   actually known.
2. **A structured, multi-category human review checklist** plus a
   deterministic `review_confidence`/`remaining_risk` pair - richer than
   Phase 36's flat checklist, but never inventing a category item the
   project's own data doesn't support.

## Read-only unless explicitly creating a workspace

`assess_manual_review_workspace()` never writes anything, never invokes a
subprocess, and never launches a slicer. Only
`create_manual_review_workspace()` writes, and only when explicitly
called - the CLI gates it behind `--create-workspace
--confirm-workspace`.

## Workspace model

`assess_manual_review_workspace(project_dir)` returns:

| Field | Meaning |
|---|---|
| `project` | Project name. |
| `project_path` | Absolute project directory path. |
| `workspace_status` | One of `WORKSPACE_STATES` (below). |
| `technical_readiness` | Verbatim `readiness_status` from `assess_slicer_readiness()` - never re-derived. |
| `approval_status` | Verbatim `approval_status` from `assess_slicer_readiness()`. |
| `printer_summary` | Printer profile - see "Printer profile inspection". |
| `material_summary` | Per-part material/color state - see "Material profile inspection". |
| `stl_summary` | `{expected, current, stale, missing}` - a thin extract of the Phase 36 assessment. |
| `preview_summary` | `{status, current, stale, missing}`. |
| `validation_summary` | `{status, passed, passed_with_warnings, failed}`. |
| `receipt_summary` | `{generation_receipt_status, export_receipt_status, review_package_status, review_package_path}`. |
| `review_checklist` | Structured, multi-category checklist - see below. |
| `review_confidence` | `High` / `Medium` / `Low` / `Unknown` - deterministic. |
| `remaining_risk` | `Low` / `Moderate` / `High` / `Unknown` - deterministic. |
| `warnings` | Every Phase 36 warning, plus printer/material-specific warnings this phase adds. |
| `recommended_actions` | Ordered, human-readable next steps. |
| `detected_slicers` / `local_slicer_status` | Verbatim from Phase 36 (`factory.slicer.local_slicer_probe`, unchanged). |
| `workspace_path` | Relative path to the workspace manifest, once created. |
| `dry_run` / `no_automatic_print` | Always `True`. |

## Workspace status

`WORKSPACE_STATES` - a fixed priority ladder, mirroring the exact style
of `factory.slicer_readiness`'s own state machine:

1. **`not_ready`** - the underlying Phase 36 assessment hasn't yet
   reached `needs_human_approval` or better (i.e. some technical signal -
   STL, validation, preview, manifest, review gate - still blocks
   progress).
2. **`needs_approval`** - every technical signal is satisfied
   (`readiness_status` is `needs_human_approval`, `ready_for_review_package`,
   or `review_package_created`) but human approval hasn't been recorded
   yet.
3. **`ready_to_create`** - approved and technically ready; no workspace
   exists yet (or the existing one is unrecognized/`"unknown"`).
4. **`stale_workspace`** - a workspace exists but a fingerprinted artifact
   (STL, validation report, render, `part_manifest.json`,
   `build_plan.json`, or the Phase 36 review package itself) has changed
   since it was created.
5. **`workspace_created`** - a current, up-to-date workspace exists.

**Important:** `needs_human_approval`, `ready_for_review_package`, and
`review_package_created` are mutually exclusive on the exact same
underlying signal - `factory.slicer_readiness`'s own ladder ties
`readiness_status` and `approval_status` together (unapproved always
resolves to `needs_human_approval`; approved always resolves to one of
the other two). `_compute_workspace_status()` therefore checks against
all three (`_TECHNICALLY_READY_STATES`) when deciding `not_ready` vs.
`needs_approval` - checking only the two approved-adjacent states would
incorrectly report every unapproved-but-otherwise-ready project as
`not_ready` (a bug caught and fixed during this phase's own manual
lifecycle verification - see the completion report).

## Printer profile inspection

`_printer_profile(build_plan)` reuses
`factory.manufacturing.knowledge.get_printer()`/`printer_capabilities()` -
never a second printer lookup table, never contacts, discovers, or
configures real hardware, never installs or launches a slicer. Reports:

- **Printer** - `display_name`, from `build_plan.json`'s resolved
  `target_printer` (see `docs/manufacturing-knowledge-base.md`).
- **Nozzle** - `default_nozzle_mm` from the local printer knowledge base.
- **Layer height** - **always `"Unknown"`.** This repo's printer
  knowledge base never records layer height (it's a per-print
  slicer-profile choice, not a printer hardware attribute) - reporting it
  honestly as unknown, rather than guessing a common default, is a
  deliberate design choice per this phase's own "never invent values"
  requirement.
- **Build volume** - `build_volume_mm` (`{x, y, z}`), from the printer
  knowledge base.
- **AMS availability** - `ams_supported`/`multicolor_supported`, from
  `printer_capabilities()` (which already merges in capabilities added by
  installed accessories, e.g. an AMS unit).

If the target printer isn't resolved in `build_plan.json` at all, or
resolves to a `printer_id` this repo's local knowledge base doesn't
recognize, every field reports `"Unknown"` (or the raw `display_name` if
that much is known) rather than inventing plausible-looking numbers.

## Material profile inspection

`_material_summary(manifest_json)` reads each part's `material`/`color`
fields from `part_manifest.json` directly - reusing the exact
`"TBD - human decision"`/unresolved-marker convention
`factory.slicer_readiness` already established, never a second
definition of "unresolved". For each resolved material string,
`_material_profile_lookup()` does a best-effort, **exact** (case-
insensitive) match against `factory.manufacturing.knowledge.load_materials()`'s
`material_id`/`display_name` fields - never fuzzy-matched, and if no
confident match exists, the field is simply `None` rather than a guessed
profile. `multi_material` is `True` whenever more than one distinct
resolved material appears across parts (used to decide whether the "AMS"
checklist category applies - see below).

## Review checklist

`build_structured_review_checklist()` returns a list of
`{"category": ..., "items": [...]}` objects (not a flat list, unlike
Phase 36's `build_review_checklist()`), always in the same order, with a
category included only when the project's own data actually supports it:

| Category | Always included? |
|---|---|
| Geometry, Scale, Orientation, Supports, Walls, Top/Bottom, Infill, Material, Color | Always. |
| AMS | Only if the target printer supports AMS, or the project is multi-material. |
| Multipart Assembly | Only if `part_manifest.json` has more than one part. |
| Moving Parts, Tolerances, Clearances, Fragile Features | Always (generic risk-review prompts, not geometry-specific). |
| Build Volume | Only if the target printer's build volume is actually known locally. |
| Estimated Risks, Human Approval | Always. |

## Review confidence and remaining risk

Both are purely deterministic functions of the already-computed Phase 36
assessment plus printer/material resolution - never a re-score of
readiness itself:

- **`review_confidence`**: `"Unknown"` if the underlying assessment is
  `unsupported_project_state` (declared in
  `factory.slicer_readiness.READINESS_STATES` but never actually produced
  today - see "Limitations"); `"Low"` if not yet at least
  `needs_human_approval`; `"High"` only if the readiness score is >= 85,
  the printer is resolved, every material/color is confirmed, there are
  no validation warnings, and there are no other warnings at all;
  otherwise `"Medium"`.
- **`remaining_risk`**: `"Unknown"` for the same unreachable state as
  above; `"High"` for `blocked`/`not_ready`/`stale_artifacts`/
  `needs_validation`/`needs_preview`; otherwise counts unresolved risk
  points (printer not resolved, material/color unresolved, validation
  warnings present) - 0 points is `"Low"`, 1-2 is `"Moderate"`, 3 is
  `"High"`.

## Artifact freshness and workspace staleness

`_snapshot_workspace_fingerprints()` fingerprints every source CAD file,
current STL, validation report, and render the export receipt knows
about, plus `part_manifest.json`, `build_plan.json`, **and (if present)
the Phase 36 review package file itself** - so recreating the package
(even with unchanged STL/validation/render) invalidates a previously
created workspace too. Uses the exact `sha256:<hex digest>` convention
`factory.export_pipeline`/`factory.slicer_readiness` already established -
never re-derived independently.

## Workspace creation

`create_manual_review_workspace(project_dir, *, output_dir=None,
overwrite=False)`:

- Raises `WorkspaceNotAllowedError` unless the underlying Phase 36
  assessment is both technically ready
  (`ready_for_review_package`/`review_package_created`) **and**
  approved - the same gate `create_review_package()` uses, since a
  workspace is never more permissive than the package it organizes.
- Raises `WorkspaceCollisionError` if a workspace already exists and
  `overwrite=False` - an existing workspace is never silently replaced.
- Writes `manual_review/review_manifest.json` - printer/material/STL/
  validation/preview/receipt summaries, the structured checklist,
  `review_confidence`/`remaining_risk`, warnings, a reference to the
  Phase 36 review package (if one exists), artifact fingerprints, and
  `auto_print_allowed: false`.
- Writes a human-readable `manual_review/README.md` with the same
  checklist (as Markdown checkboxes), a warnings section, and a
  **Human sign-off** section requiring explicit acknowledgment that no
  automatic printing occurred.
- **Does not require a Phase 36 review package to already exist** - it
  references one if present (`review_package_path` in the manifest) but
  its own hard requirements are only technical readiness + approval,
  matching the pipeline's overall placement without introducing an
  artificial extra dependency the task didn't ask for.
- **References existing STL/validation/render/package files by relative
  path - never copies them**, mirroring
  `factory.preview_package`/`factory.slicer_readiness`'s own established
  "reference, don't duplicate" convention.
- Never touches source CAD, STL, validation, render, or review-package
  files.

## Preview Board integration

### Architectural note: why `manual_review_summary` isn't on `summarize_project()`

Same reasoning as Phase 36's `slicer_readiness_summary` (see
`docs/slicer-readiness.md`'s own "Architectural note"):
`factory.manual_review_workspace` calls
`factory.slicer_readiness.assess_slicer_readiness()`, which calls
`factory.review_gate.evaluate_review_gate()`, which already imports
`factory.project_inspection.summarize_project()`. Adding
`manual_review_summary` inside `project_inspection.py` would recreate the
exact circular import
(`project_inspection -> manual_review_workspace -> slicer_readiness ->
review_gate -> project_inspection`) Phase 36 already discovered and
worked around. `factory.preview_board.gather_board_data()` calls
`summarize_manual_review_workspace(project_dir)` directly per project and
merges the result in at the same aggregation point as
`slicer_readiness_summary` - the same visible per-project field, from the
same architecturally necessary layer above `project_inspection.py`.

### The card

`factory.preview_board.build_board_html()` renders a compact "Manual
Review Workspace" card, placed right after "Slicer Review Readiness" (all
five meta-cards - Project Readiness, Generation Gate, Post-Generation
Pipeline, Slicer Review Readiness, Manual Review Workspace - summarize
what's possible next). Shows: workspace status (badged), printer display
name, a material label (single/multi-material, flagged if unresolved),
review confidence (badged), remaining risk (badged), review-package
availability (badged), the next suggested action, and a standing "Human
review required" reminder. Purely presentational - it never assesses,
inspects a printer profile, or creates a workspace itself; it never opens
a slicer, generates G-code, or prints anything.

Example (workspace ready, technically resolved):

```
MANUAL REVIEW WORKSPACE
Workspace: Ready
Printer: Bambu X1C
Material: PLA
Review Confidence: Medium
Remaining Risk: Moderate
Package: Available
Human review required
```

`summarize_manual_review_workspace()`'s fields: `workspace_status`,
`printer_display_name`, `material_multi`, `material_unresolved`,
`review_confidence`, `remaining_risk`, `package_available`,
`warning_count`, `next_action`.

## The CLI

```bash
factory review-workspace <project_dir> [--json]
    [--create-workspace] [--confirm-workspace] [--output-dir ...]
    [--force-workspace]
```

- Read-only by default: always computes and prints a full workspace
  assessment - project, printer, material, current STL files, validation
  summary, preview summary, receipts, the structured review checklist,
  outstanding warnings, and recommended next actions.
- `--create-workspace` requires `--confirm-workspace` together (an error,
  exit 1, if `--create-workspace` is passed alone) - and requires the
  underlying Phase 36 assessment to already be approved and technically
  ready; `--force-workspace` allows overwriting an existing workspace.
- `--output-dir` overrides the default `manual_review/` location.
- Human-readable output ends with an explicit "No slicer was opened." /
  "No G-code was generated." / "No print was started." trailer.

## JSON contract

`--json` is the entire stdout on every path, including every error
(missing project directory, `--create-workspace` without
`--confirm-workspace`, `WorkspaceNotAllowedError`,
`WorkspaceCollisionError`) - never mixed with plain text before or after.
Top-level fields mirror `assess_manual_review_workspace()`'s model (above)
plus this CLI's own `workspace_result`, `errors`.

## Failure handling

Every failure mode resolves to a structured, honest outcome rather than a
crash or false success: missing project directory (CLI-level `errors` +
exit 1, clean JSON); `--create-workspace` without `--confirm-workspace`
(rejected before touching disk); workspace creation attempted before
technical readiness or approval (`WorkspaceNotAllowedError`, nothing
written); workspace creation attempted over an existing workspace without
`--force-workspace` (`WorkspaceCollisionError`, the existing workspace is
left untouched); malformed/missing
`generated/manual_review_workspace_receipt.json`
(`read_workspace_receipt()` returns `None` rather than raising,
`workspace_status` correctly falls back to `ready_to_create`); an
unresolved/unrecognized printer or material (reported as `"Unknown"`/
`None`, never invented, never a crash).

## Limitations

- **`"unsupported_project_state"` is declared but currently unreachable.**
  It's part of `factory.slicer_readiness.READINESS_STATES` for
  forward-compatibility, but `_evaluate_readiness_status()` never actually
  returns it today - `review_confidence`/`remaining_risk`'s `"Unknown"`
  branch for this state is unit-tested directly (white-box), not via a
  real project, since no real project currently reaches it.
- **Layer height is never known locally** - this repo's printer knowledge
  base has no such field; it is always reported `"Unknown"`, by design,
  not as a gap to eventually fill with a guess.
- **Material profile matching is exact, not fuzzy** - a material string
  that doesn't exactly match a known `material_id`/`display_name`
  (case-insensitively) reports no profile, rather than a best-guess
  nearest match.
- **A workspace does not require a Phase 36 review package to already
  exist** - it references one if present but can be created without it,
  a deliberate scope decision (see "Workspace creation" above).
- **One current workspace state, not an append-only history** - the
  workspace receipt reflects only the current workspace state, same
  convention as every earlier phase's own receipt.

## Non-goals

- **No AI, no LLM, no machine learning of any kind.**
- **No network calls, no web search, no scraping.**
- **Never invokes a slicer, opens a file in one, generates G-code,
  queues a print job, or contacts a printer.**
- **Never invokes Blender, Meshy, or FreeCAD.**
- **Never installs anything** - not a slicer, not a printer profile.
- **Never re-implements mesh validation, the artifact registry, the
  preview package, Review Gate logic, slicer discovery, or receipt
  tracking** - each is read directly from its existing module.
- **Never sets `human_approved` or `print_ready`** - this repo's ceiling
  everywhere remains `slicer_review_ready`.

## Phase 38: consumed directly by `factory.slicer_intelligence`

`factory.slicer_intelligence.evaluate_slicer_intelligence()` (Phase 38,
see `docs/slicer-intelligence.md`) calls
`assess_manual_review_workspace()` from this module directly, reusing its
`printer_summary`/`material_summary`/`stl_summary`/`validation_summary`
wholesale rather than re-deriving any of it. This module stays unchanged
by Phase 38: it does not know about build-volume-fit analysis, geometry
risk categories, or review-priority scoring - Phase 38 sits one further
layer above it in the dependency graph (see `docs/architecture.md`'s
Phase 38 addendum).

See also `docs/slicer-readiness.md` (Phase 36), `docs/export-pipeline.md`
(Phase 35), `docs/generation-gate.md` (Phase 34),
`docs/manufacturing-knowledge-base.md`, `docs/review-gate.md`,
`docs/preview-board.md`, `docs/slicer-review-workflow.md`,
`docs/slicer-intelligence.md` (Phase 38, the next pipeline step),
`docs/slicer-profiles.md` / `docs/slicer-analysis-history.md` (Phase 39),
`docs/file-lifecycle.md`, and `docs/roadmap.md` Phase 37.

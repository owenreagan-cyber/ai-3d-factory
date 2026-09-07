# Manufacturing Readiness Intelligence & Final Production Gate (Phase 52)

`factory.manufacturing_readiness` is the final aggregation layer over
every readiness signal this repo has ever computed. It answers one
question:

> **Is this project ready to enter manufacturing preparation?**

It never answers:

> "Should the printer automatically start?"

```
Manufacturing readiness  !=  printing approval.
Automatic printing remains impossible.
```

**This is a pure aggregation layer.** It computes nothing a lower module
hasn't already computed, validates no geometry, contacts no printer/
slicer/network, and never modifies an artifact. No code path in this
module calls Meshy, launches Blender, executes CAD, invokes a slicer, or
contacts a printer.

## Mandatory inspection this phase performed before writing any code

Per this phase's own spec: `factory.design_review`, `factory.hybrid_workflow`,
`factory.blender_adaptation`, `factory.cad_augmentation`,
`factory.slicer_intelligence`, `factory.slicer_readiness`,
`factory.manual_review_workspace`, `factory.project_health`,
`factory.project_timeline`, `factory.artifact_history`,
`factory.project_store`, `factory.preview_board`, `factory.cli`,
`factory.validators.*`, plus `docs/design-review.md`,
`docs/hybrid-workflow.md`, `docs/blender-adaptation.md`,
`docs/cad-augmentation.md`, `docs/slicer-readiness.md`,
`docs/slicer-intelligence.md`, `docs/manual-review-workspace.md`,
`docs/project-health.md`, `docs/architecture.md`, `docs/file-lifecycle.md`,
`docs/roadmap.md`, `docs/phase-registry.md`, and every test file for
those modules. Findings:

- **`factory.design_review` (Phase 51) already is** almost exactly the
  aggregation layer this phase's spec describes - but scoped only to the
  hybrid (Meshy -> Blender -> CAD) pipeline. `factory.project_health`
  (Phase 42) is the equivalent complete ladder for the *traditional*
  (brief -> orchestrator -> CAD -> export) pipeline. By explicit design,
  neither reads the other.
- Readiness/state enums already existed in seven places
  (`design_review.READINESS_STATES`, `hybrid_workflow`'s own
  plan-level `manufacturing_readiness` field, `slicer_readiness.READINESS_STATES`,
  `manual_review_workspace.WORKSPACE_STATES`, `slicer_intelligence.ANALYSIS_STATES`/
  `BUILD_VOLUME_FIT_STATES`, `project_health.HEALTH_LEVELS`) - this
  phase's own `READINESS_STATES` is a new, ninth, deliberately
  non-colliding vocabulary (see "Readiness states" below).
- Blockers/warnings, scoring, printer/material resolution, human
  approval status, mesh validation, and build-volume fit each already
  have exactly one canonical source (`design_review`/`project_health`
  for the first two, `manual_review_workspace` for the third,
  `slicer_readiness.assess_slicer_readiness()["approval_status"]` for
  the fourth, `validators.mesh_validate` for the fifth,
  `slicer_intelligence._build_volume_analysis` for the sixth) - none of
  them are recomputed here.
- **The one genuinely missing piece:** a pipeline-agnostic union of the
  two complete ladders, plus one new blocker rule (an impossible
  build-volume fit, which today neither aggregator escalates to blocker
  severity), plus a single flat human-confirmation checklist instead of
  three overlapping ones.

## Why this is not a second `design_review`/`project_health`

This phase does not extend, modify, or duplicate either module's
scoring - both stay completely untouched, matching every prior phase's
own stated invariant. `factory.manufacturing_readiness` sits **above**
both in the dependency graph (it calls `evaluate_design_review()` and
`evaluate_project_health()` directly, the same "top-level consumer"
relationship `preview_board.py` already has to every summary module),
never the reverse - see `docs/architecture.md`'s "Aggregation Layer
Convention".

## Pipeline lens

`_is_hybrid_pipeline()` reuses the exact same check
`factory.design_review.summarize_design_review()` itself already makes:
if any stage of the hybrid artifact chain (Meshy/Blender-adaptation/
CAD-augmentation) is present, the project is treated as `"hybrid"`;
otherwise `"traditional"`. Both `evaluate_design_review()` and
`evaluate_project_health()` are always called, on every project,
regardless of which pipeline is active - both are cheap, pure, read-only
functions that already report honestly (`"not_reviewed"`, mostly-zero
categories) when their own pipeline has no evidence. This is what makes
the union safe: nothing is guessed for the inactive pipeline, it's just
mostly empty.

## Field derivation - every field has evidence

| Field | Source |
|---|---|
| `design_status`, `scale_status`, `manufacturing_status`, `printer_status`, `material_status` | `factory.design_review["required_human_confirmations"]` - genuinely pipeline-agnostic, since printer/material resolution reads `build_plan.json`/`part_manifest.json` regardless of which pipeline produced the artifact. |
| `geometry_status` | `design_review.score_categories["geometry"]["score"]` (hybrid) or `project_health.health_score_categories["validation"]` (traditional) - reused verbatim, never re-validated. |
| `artifact_status` | Hybrid: fraction of the 3-stage chain present. Traditional: `project_health.LIFECYCLE_STAGES` ordinal position (has the project reached `cad_generation` or later) - reused directly, not a second file-existence check. |
| `slicer_status` | `project_health.readiness_summary["status"]` - `factory.slicer_readiness`'s own `readiness_status`, passed through, never recomputed. |
| `human_review_status` | `project_health.readiness_summary["approval_status"]` - the canonical "has a human approved" flag everywhere else in this repo already uses. |
| `readiness_score` | `design_review["design_quality_score"]` (hybrid) or `health["health_score"]` (traditional) - whichever pipeline's own already-weighted score applies; `readiness_score_source` names which, `readiness_score_weights` carries the weights when hybrid. |
| `blockers`/`warnings` | Union of `design_review["blockers"/"warnings"]` and `health["blockers"/"warnings"]`, each tagged with its source pipeline, de-duplicated - plus one new rule (see below). |

## The one new blocker rule this phase adds

An impossible build-volume fit is a genuine manufacturing obstruction -
matching this phase's own spec's BLOCKER example - but today neither
`design_review` nor `project_health` escalates
`slicer_intelligence.build_volume_analysis["fit_status"] == "does_not_fit"`
to blocker severity (it's informational only in both). This module reads
that one already-computed field directly (one extra, cheap, read-only
call to `evaluate_slicer_intelligence()`) and classifies it as a blocker
at this aggregation layer. It never re-runs the build-volume analysis
itself.

## Human confirmation checklist

One flat, explicit checklist - never three overlapping ones. Reuses
`design_review`'s own five confirmations (renaming `material_confirmed`/
`printer_confirmed` to `material_selected`/`printer_selected` to match
this phase's own spec's example checklist) and adds two new items,
both sourced from already-computed evidence, never invented:

- `design_intent_confirmed`, `dimensions_confirmed`,
  `manufacturing_purpose_confirmed`, `material_selected`,
  `printer_selected` - read straight off `design_review["required_human_confirmations"]`.
- `slicer_review_complete` - `True` iff `slicer_status` is
  `ready_for_review_package`/`review_package_created`.
- `final_artifact_approved` - `True` iff `human_review_status == "approved"`.

`completed_requirements`/`missing_requirements` are the same checklist,
partitioned by `confirmed`.

## Readiness states

Closed vocabulary - deliberately excludes `approved_for_print` and
`automatic_manufacture_ready`, matching this repo's standing
`config/agent_policy.json` ceiling (`status_gates.max_automatic_status:
"slicer_review_ready"`). `manufacturing_review_ready` is reused with the
exact same meaning `factory.design_review` already gives it (printer +
material both confirmed) - not a second, conflicting definition.

Decision tree, first match wins - **a high `readiness_score` never
overrides a blocker**, because `blocked` is checked first, before the
score is even read:

1. **`blocked`** - one or more blockers exist (broken lineage, failed
   geometry validation, an impossible build-volume fit, a genuine
   traditional-pipeline obstruction).
2. **`not_ready`** - `artifact_status == "absent"`; nothing to review
   yet.
3. **`needs_information`** - design intent, dimensions, or manufacturing
   purpose are not yet confirmed.
4. **`design_review_complete`** - the design itself is solid, but
   printer and/or material are not yet selected.
5. **`manufacturing_review_ready`** - printer and material are both
   selected, but `slicer_status` hasn't yet reached
   `needs_human_approval` or later.
6. **`human_approval_required`** - every technical gate has cleared;
   `slicer_status == "needs_human_approval"` - the single remaining
   requirement is a human's approval action.
7. **`slicer_preparation_ready`** - `slicer_status` has reached
   `ready_for_review_package`/`review_package_created` - by
   `factory.slicer_readiness`'s own state machine, this can only be
   reached once approval has already been recorded.

**Deliberate ordering note:** this phase's own spec listed
`slicer_preparation_ready` before `human_approval_required` as an
example. This implementation reaches `human_approval_required` *before*
`slicer_preparation_ready`, because `factory.slicer_readiness`'s own
state machine reaches `needs_human_approval` strictly before
`ready_for_review_package`/`review_package_created` - approval is a
precondition of the package being "ready", never the reverse. State
*names*, not the spec's example list order, are what this repo's
ceiling actually constrains; the semantically correct order was chosen
over matching the example's literal sequence.

No code path in this module ever returns a state beyond
`slicer_preparation_ready`.

## Scoring

`readiness_score` is never independently computed - it is always
whichever pipeline's own already-weighted, already-documented score
applies (`design_review.QUALITY_CATEGORY_WEIGHTS` for hybrid,
`project_health.HEALTH_CATEGORY_WEIGHTS` for traditional).
`readiness_score_source` names which; `readiness_score_weights` carries
the weights dict when hybrid (traditional weights remain documented in
`docs/project-health.md` rather than re-declared here). **The score
never overrides a blocker** - see "Readiness states" above; a 95% score
with a missing printer still reports `needs_information`/
`design_review_complete`, never anything higher, and a project with any
blocker reports `blocked` regardless of score.

## Printer/material handling

Never a second printer database, never a guess. `printer_summary`/
`material_summary` are `design_review`'s own (in turn
`factory.manual_review_workspace`'s own) already-computed objects,
passed through verbatim - unresolved fields are always the string
`"Unknown"`, never invented defaults for material, nozzle, layer height,
printer, or process settings.

## Lineage / timeline

`lineage_summary` folds in `factory.artifact_history.summarize_artifact_history()`/
`factory.project_timeline.summarize_project_timeline()`'s own already-
computed counts (`artifact_version_count`, `timeline_event_count`, etc.)
as read-only context. **No new timeline event category or artifact-
history classification rule is added** - this phase never persists a
snapshot of its own analysis; `evaluate_manufacturing_readiness()`
always recomputes fresh, exactly like `factory design-review`/`factory
health`.

## CLI

```
factory manufacturing-readiness <project_dir> [--json] [--verbose]
```

A single, flat, read-only command - no `plan`/`execute` subcommands (there
is nothing to execute), and no `approve`/`print`/`manufacture`/`send`
verb anywhere. `--verbose` only affects the human-readable renderer
(shows warnings in addition to blockers); JSON output always includes
everything. This command never writes a file.

## Preview Board

`manufacturing_readiness_summary` is wired into
`factory.preview_board.gather_board_data()` at the aggregation point
only (per the standing "Aggregation Layer Convention" in
`docs/architecture.md`). One new compact "Manufacturing Readiness"
section is added, placed as the very first card-section (ahead of
"Project Health") - the outermost aggregation layer, spanning both
"Project Health" and "Hybrid Design Review" beneath it. It reuses
existing badge CSS classes verbatim (no new CSS, no JavaScript) and
never invokes Meshy/Blender/CAD/a subprocess of any kind during board
generation.

## Testing

`tests/test_manufacturing_readiness.py` (fresh/idea-stage project is
`not_ready`, hybrid chain with no brief/manifest is `needs_information`,
missing printer/material are `needs_information` never a blocker, failed
geometry validation and broken lineage are both `blocked`, readiness
score never overrides a blocker, blockers/warnings tagged by pipeline,
completed/missing requirements partition the checklist, scoring weights
documented, `automatic_print_allowed` always `False`),
`tests/test_manufacturing_readiness_cli.py` (`--json`/`--verbose`, no
forbidden verbs registered, never writes a file),
`tests/test_manufacturing_readiness_preview.py` (Preview Board summary +
HTML card wiring, no execution during board generation, summary reused
directly not reimplemented), and
`tests/test_manufacturing_readiness_safety.py` (AST scans: no
subprocess/network import; never imports `factory.blender_adapter`/
`factory.export_pipeline`/`cadquery`/any Meshy transport module;
behavioral proof the evaluation survives poisoned `socket`/`subprocess`;
no file is ever written; readiness states respect the repo-wide
automation ceiling).

## Limitations

- **Not a license/ownership check.** `factory.reference_board`'s license
  tracking is not folded into this phase's blocker model (it wasn't in
  this phase's reuse list) - "unknown ownership/license" from the
  spec's own blocker examples is not yet implemented as a blocker
  anywhere in this repo. Flagged as a candidate for a future phase, not
  invented here.
- `readiness_score` is only as comparable across projects as
  `design_quality_score`/`health_score` already are to each other -
  this phase does not attempt to normalize the two onto one shared
  scale; they remain two different, independently-documented scoring
  systems, and `readiness_score_source` always says which one produced
  the number.
- `slicer_preparation_ready` vs. `human_approval_required` ordering is a
  deliberate deviation from this phase's own spec's example list order
  - see "Readiness states" above for the full reasoning.
- Like `factory.design_review`, this module inherits every limitation of
  the modules it aggregates (coarse keyword-driven manufacturing-intent
  classification, no aesthetic/artistic quality assessment, print-
  readiness reuse only as good as `part_manifest.json`/`export_receipt.json`).

## No-authority rule

Never launches Meshy, Blender, a CAD backend, a slicer, or contacts a
printer/network. Never modifies geometry, a receipt, or any execution
artifact. Never writes any file. Never sets `human_approved`/
`print_ready`, and never reaches `approved_for_print`/
`automatic_manufacture_ready` in any field this module ever returns.

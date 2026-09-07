# Hybrid Design Quality Review & Manufacturing Readiness Gate (Phase 51)

`factory.design_review` is the final intelligence layer over the Meshy
-> Blender -> CAD pipeline (Phases 47-50). It answers one question:

> **Is this hybrid artifact chain actually ready for human manufacturing
> review?**

Never "is it ready to print."

```
Generated artifact    != Good design
Validated mesh        != Manufacturing ready
Manufacturing ready   != Human approved
Human approved        != Print approved
Automatic printing remains impossible.
```

**This is review only.** It does not execute anything, does not modify
geometry, does not repair models, and does not approve printing. No code
path in this module calls Meshy, launches Blender, executes CAD
(OpenSCAD/CadQuery), invokes a slicer, or contacts a printer/network.

## Mandatory inspection this phase performed before writing any code

Per this phase's own spec: `factory.hybrid_workflow`,
`factory.blender_adaptation`, `factory.cad_augmentation`,
`factory.design_orchestrator`, `factory.design_intent_check`,
`factory.project_health`, `factory.slicer_intelligence`,
`factory.slicer_readiness`, `factory.manual_review_workspace`,
`factory.project_timeline`, `factory.artifact_history`,
`factory.preview_board`, `factory.cli`, `factory.validators.*`, and
`docs/hybrid-workflow.md`, `docs/blender-adaptation.md`,
`docs/cad-augmentation.md`, `docs/design-quality-standard.md`,
`docs/file-lifecycle.md`, `docs/architecture.md`, `docs/roadmap.md`,
`docs/phase-registry.md`, plus every test file for those modules.
Findings:

- **Existing quality concepts:** `docs/design-quality-standard.md`
  defines the "Etsy-worthy" bar (polished, intentional, useful,
  gift-worthy) - explicitly **vision/planning only**, never implemented
  by any command, and explicitly stating that passing `factory validate`
  "has cleared a geometry sanity check - it has not cleared this
  standard." No code anywhere in this repo measures silhouette,
  proportion, or polish - nor could it, without an actual human eye or a
  vision-capable AI this repo does not invoke.
- **Existing readiness concepts:** `factory.project_health` (Phase 42)
  already computes a deterministic, weighted health score - but every
  one of its inputs (`design_orchestrator_summary`,
  `generation_gate_summary`, `export_pipeline_summary`) is scoped to the
  **traditional, CAD-first pipeline** (`brief.json` -> Design
  Orchestrator -> CAD generation -> `export_receipt.json` ->
  `part_manifest.json`). It has no field anywhere that reads a Meshy
  receipt, a Blender adaptation receipt, or a CAD augmentation receipt.
  For a hybrid AI-generated project, most of its categories score `0` -
  not because the project is unhealthy, but because it took a path
  `project_health` was never taught to look for.
- **Existing validation concepts:** `factory.validators.mesh_validate.validate_mesh()`
  is the one real geometry validator in this repo (watertight, manifold,
  winding-consistency, bounding box, volume, build-volume fit). Reused
  directly here, never re-implemented.
- **Gaps Phase 51 fills:** a quality/readiness lens specific to the
  hybrid pipeline that (a) knows how to find a Meshy/Blender/CAD-
  augmentation artifact chain in the first place, (b) verifies that
  chain's own internal consistency (parent/child fingerprints), (c)
  reuses every existing scale/intent/print-readiness system against
  *whichever artifact is actually current* (not what
  `factory.hybrid_workflow.build_adaptation_plan()` alone would find,
  since that function has no Blender/CAD-augmentation receipt
  awareness), and (d) produces one deterministic, fully-traceable
  report - never a black-box score.

## Why this is not `factory.project_health`, and does not touch it

This phase does not extend, modify, or duplicate `factory.project_health`'s
scoring - it stays completely untouched, matching every prior Meshy/
Blender/CAD-adjacent phase's own stated invariant (Phase 48/49/50 all say
the same). `factory.design_review` is a **parallel, narrower lens**,
reusing the exact reuse-pattern `project_health` itself established
(Phase 36/38/48/49/50's own summary functions), just applied to a
different input chain. If a project happens to go through *both*
pipelines (unlikely but not forbidden), both evaluations simply coexist -
neither overrides the other.

**"Do not make AI generation increase health automatically" is honored
by construction:** `factory.project_health`'s own score never reads
anything this module produces. Nothing in `factory.design_review`
writes into `project_health`'s inputs, and no new category was added to
`HEALTH_CATEGORY_WEIGHTS`. If a saved `design_review_report.json`
snapshot exists, `factory.project_health` still never reads it - the two
systems are, and remain, entirely independent views.

## Why this is not `docs/design-quality-standard.md`'s "Etsy-worthy" bar

Read that document's own words again: **"A mesh that passes `factory
validate` ... has cleared a geometry sanity check - it has not cleared
this standard."** `design_quality_score` in this module measures
**pipeline readiness and evidentiary completeness** - is there a
declared intent, is the lineage consistent, is the geometry valid, is
the scale confirmed, is the manufacturing purpose classified, does the
expected mechanical feature exist, is print-readiness data available -
**never aesthetic merit.** Every category's own `reasoning`/`inputs`
travel with its score for exactly this reason: so a human reading a
"design_quality_score: 85" never mistakes it for "this looks 85% as good
as a professional design." It measures how much of the *process* this
repo can verify happened, not how good the *result* looks.

## Module layout - nothing duplicated

```
factory/blender_adaptation.py    - read_blender_adaptation_receipt() (reused)
factory/cad_augmentation.py      - read_cad_augmentation_receipt() (reused)
factory/hybrid_workflow.py       - assess_scale()/assess_manufacturing_intent() (reused)
factory/design_intent_check.py   - summarize_design_intent() (reused)
factory/manual_review_workspace.py - assess_manual_review_workspace() (reused)
factory/slicer_readiness.py      - assess_slicer_readiness() (reused)
factory/slicer_intelligence.py   - evaluate_slicer_intelligence() (reused)
factory/validators/mesh_validate.py - validate_mesh() (reused)
factory/design_review.py         - NEW module: chain resolution, scoring, readiness state, checkpoints, recommendations
factory/preview_board.py         - design_review_summary + a compact "Hybrid Design Review" card (aggregation point only)
factory/cli.py                   - `factory design-review <project> [--json] [--save]`
```

`factory.design_review` never invokes a subprocess itself, never imports
`factory.blender_adapter` (the module that actually runs Blender),
`factory.export_pipeline` (the module that actually runs OpenSCAD), or
`cadquery` - proven by a static AST scan, not just inspection.

## Artifact chain resolution

`_resolve_artifact_chain()` reads, in order, the three existing receipt
readers - never re-implementing any of them:

1. A real (non-mock) `generated/meshy_receipt.json`.
2. `factory.blender_adaptation.read_blender_adaptation_receipt()`.
3. `factory.cad_augmentation.read_cad_augmentation_receipt()`.

Each stage is reported `present: True/False` - a stage that never ran is
never silently assumed. The **organic component** is whichever is the
most-downstream organic-origin artifact (Blender-adapted, else the raw
Meshy artifact, else whatever CAD augmentation ran directly against, if
any); the **mechanical component** only exists if CAD augmentation
actually ran. These stay two independent paths - never boolean-merged,
matching Phase 50's own "never a fused mesh" design.

**Lineage consistency** (not just completeness) is verified: for every
present downstream stage, this module recomputes a fresh `sha256`
fingerprint of its recorded parent artifact and compares it against that
receipt's own recorded `input_hash`. A mismatch, or a missing parent
file, is a genuine **broken link** - the file changed or disappeared
after the adaptation/augmentation step ran, which invalidates that
step's own provenance claim (the same "a fingerprint mismatch
invalidates approval" reasoning `factory.slicer_readiness`/
`factory.artifact_history` already apply elsewhere in this repo, applied
here to lineage instead of human approval). A project with an
*incomplete* chain (e.g. Meshy-only, nothing further yet) is not treated
as broken - only an actual mismatch is.

## Quality categories

Six categories feed the weighted score; a seventh (**functional
completeness**) is evaluated and reported but deliberately excluded from
the score itself - see "Scoring model" below for why.

1. **Design intent alignment** - does a human declare
   `design_intent.use_case`? Reuses
   `factory.design_intent_check.summarize_design_intent()` - never
   re-parses `brief.json`. This category cannot and does not judge
   whether the *artifact* actually matches the declared intent's style
   (that remains a human/vision-AI judgment this repo does not
   automate) - only whether an intent was declared at all, and how
   specific it is.
2. **Artifact lineage** - see "Artifact chain resolution" above. A
   broken link is both a category-0 score and a hard blocker.
3. **Geometry quality** - reuses `factory.validators.mesh_validate.validate_mesh()`
   directly against whichever organic/mechanical components are
   present, averaged. Never a new validator, never a new watertight/
   manifold check.
4. **Scale suitability** - reuses `factory.hybrid_workflow.assess_scale()`.
   If a Blender adaptation receipt exists with
   `single_shot_human_confirmation: true`, scale is already treated as
   resolved (a human already confirmed a target dimension and a real,
   gated execution already applied it - Phase 49's own execution gate
   *is* that confirmation). Otherwise falls back to `assess_scale()`'s
   own confidence/implausibility read against whatever `design_intent`
   evidence exists. Never silently rescales anything - this module has
   no write path to a mesh at all.
5. **Manufacturing intent** - reuses
   `factory.hybrid_workflow.assess_manufacturing_intent()` directly
   (decorative/functional/mechanical/replacement/educational/collectible,
   with its own confidence).
6. **Functional completeness** (reported, not scored) - for a hybrid
   workflow that expects a mechanical feature (either because
   `assess_manufacturing_intent()` flagged `mechanical_features_expected`,
   or because a CAD augmentation receipt already exists regardless of
   what the coarse intent classifier guessed), does one actually exist?
   **Never infers *which* specific feature (coin slot vs. mounting vs.
   base) was needed** - only whether *some* CAD augmentation happened
   when the workflow's own evidence says one was expected. A missing
   expected feature is both a `functional_completeness.score == 0` and a
   hard blocker.
7. **Print readiness** - reuses
   `factory.manual_review_workspace.assess_manual_review_workspace()`/
   `factory.slicer_readiness.assess_slicer_readiness()`/
   `factory.slicer_intelligence.evaluate_slicer_intelligence()` directly.
   For a hybrid project with no `part_manifest.json`/`export_receipt.json`
   (true of most Meshy/Blender/CAD-augmentation-only projects), these
   honestly report "no parts"/"printer unresolved" - a real, useful
   signal ("printer not configured"), never a bug this module routes
   around or fakes data to avoid.

## Scoring model

Explicit, documented weights (sum to 1.0):

| Category | Weight | Reasoning |
|---|---|---|
| Design intent | 20% | The strongest available signal of *what this is for* - without it, every downstream classification is a weak guess. |
| Geometry | 20% | The one objective, machine-checkable fact this repo can verify directly. |
| Scale | 15% | Critical, but binary once confirmed (Phase 49's execution gate already resolves it definitively for adapted artifacts). |
| Manufacturing | 20% | Drives what "done" even means (decorative vs. functional vs. mechanical have different bars). |
| Lineage | 10% | Usually either perfectly consistent or badly broken - a narrower, more binary signal than the others, weighted accordingly. |
| Review readiness | 15% | Reuses Phase 36's own established readiness score - a broad, already-weighted signal in its own right. |

`design_quality_score = round(sum(category_score * weight))`. Every
category entry carries its own `score`, `reasoning` (a sentence naming
exactly which existing system/field produced it), and `inputs` (the raw
facts) - **never a single magic number without explanation.**
`functional_completeness` is deliberately excluded from the weighted sum
- it is a binary gate ("is the expected feature present"), not a graded
quality dimension, and is already fully captured as a blocker when it
fails; including it in the weighted average would let a high score on
every *other* category mask a completely missing mechanical feature.

## Readiness states

Closed vocabulary, in the exact order checked (first match wins) - and
**deliberately excludes `approved_for_print`** or anything stronger than
`approved_for_slicer_review`, matching this repo's standing
`config/agent_policy.json` ceiling (`status_gates.max_automatic_status:
"slicer_review_ready"`):

1. **`blocked`** - a hard blocker exists (broken lineage, FAIL geometry,
   a missing expected mechanical feature).
2. **`not_reviewed`** - no artifact chain exists yet; nothing to review.
3. **`needs_information`** - one or more required human confirmations
   (below) is unresolved.
4. **`approved_for_slicer_review`** - `factory.slicer_readiness`'s own
   `readiness_status` already reports `ready_for_review_package`/
   `review_package_created` - the existing pipeline has already signed
   off.
5. **`manufacturing_review_ready`** - every confirmation is resolved and
   a printer + material are both actually selected.
6. **`design_review_ready`** - every confirmation is resolved, but
   printer/material are not yet configured.

No code path in this module ever returns a state beyond
`approved_for_slicer_review`.

## Human checkpoints - never inferred

`required_human_confirmations` names five specific, concrete items, each
read straight off existing evidence - never auto-confirmed:

- `design_intent_confirmed` - has a human declared `design_intent.use_case`?
- `dimensions_confirmed` - was target size explicitly confirmed (a real
  Blender adaptation execution, or a declared `max_size_mm`)?
- `manufacturing_purpose_confirmed` - is manufacturing intent
  confidently classified (not a weak default)?
- `material_confirmed` - is material/color assigned with nothing
  unresolved?
- `printer_confirmed` - is an actual printer selected (not just a fleet
  default)?

## Recommended actions

Generated only from already-computed gaps - never fabricated, never
vague. Examples this module actually produces: *"Confirm target size
before manufacturing..."*, *"Configure a printer profile before
manufacturing review."*, *"Confirm the manufacturing purpose..."*,
*"Requires human slicer review before any further status advances."*,
and (reused verbatim from `factory.slicer_intelligence`'s own detected
geometry risks) *"Review geometry risk: ..."*. This module never invents
a mesh-analysis capability it doesn't have (e.g. it does not claim to
detect "the coin slot is too small" - only that geometry validation
passed/warned/failed, and that a mechanical feature exists or doesn't).

## Lineage integration - reused, not duplicated

Reuses `factory.project_timeline`/`factory.artifact_history`'s existing
receipt readers as *input* (via the same receipts they themselves read)
to verify lineage. **This phase adds no new timeline event category and
no new artifact-history classification rule** - unlike Phases 49/50, a
design review is never itself a persisted "artifact-relevant event";
`factory design-review` behaves exactly like `factory health`/`factory
report` - computed fresh, on demand, from whatever already exists. No
new lineage system is built.

## Receipt / persistence model

**No execution receipt exists, because nothing executes.** By default,
`factory design-review <project>` computes a review fresh, every call,
and writes nothing - exactly like `factory health`. Only
`factory design-review <project> --save` additionally writes
`generated/design_review_report.json` - a **versioned** (`design_review_version`),
**fingerprinted-by-construction** (its own `review.artifact_chain`
carries every relevant fingerprint already) **read-only analysis
snapshot**, never an execution receipt. It is always safely
overwritable on the next `--save` (there is no execution to protect -
only an analysis a human may want to re-run and re-save), and its
filename (`design_review_report.json`) never collides with any
`*_receipt.json` in this repo.

## CLI

```
factory design-review <project_dir> [--json] [--save]
```

A single, flat command - no `plan`/`execute` subcommands (there is
nothing to execute), and no `approve`/`print`/`manufacture` verb
anywhere. `--save` is the only way this command ever writes a file;
without it, the command is exactly as read-only as `factory health`.

## Preview Board

`design_review_summary` is wired into
`factory.preview_board.gather_board_data()` at the aggregation point
only (per the standing "Aggregation Layer Convention" in
`docs/architecture.md`). Unlike Phases 48-50 (which deliberately added
no new HTML card), this phase adds one small, compact "Hybrid Design
Review" section - status badge, score, and up to two top risks - mirroring
the existing "Project Health" card's exact template/CSS classes (no new
CSS, no JavaScript). It never invokes Meshy/Blender/CAD/a subprocess of
any kind during board generation - `summarize_design_review()` always
recomputes the review fresh (never reads a saved snapshot), so it can
never go stale relative to the current artifacts on disk.

## Project Health - unchanged

`factory.project_health`'s `health_score` computation is untouched by
this phase - see "Why this is not `factory.project_health`" above.

## Testing

`tests/test_design_review.py` (chain resolution for every combination -
full hybrid, Meshy-only, Blender-only, CAD-only, empty/no-artifact,
broken lineage by mutation and by deletion, invalid geometry, unknown
scale, missing printer/material/design-intent, functional-completeness
blocking, weighted-score arithmetic, readiness-state vocabulary),
`tests/test_design_review_cli.py` (`--json`/`--save`, no forbidden verbs
registered), `tests/test_design_review_safety.py` (AST scans: no
subprocess/network import; never imports `factory.blender_adapter`/
`factory.export_pipeline`/`cadquery`/any Meshy transport module;
behavioral proof the review survives poisoned `socket`/`subprocess`; no
receipt or artifact is ever modified, twice in a row; the snapshot
filename never collides with an execution receipt), and
`tests/test_design_review_preview.py` (Preview Board summary + HTML card
wiring, no execution during board generation).

## Limitations

- **Cannot assess aesthetic/artistic quality at all** - see "Why this is
  not `docs/design-quality-standard.md`'s 'Etsy-worthy' bar" above. This
  is the single most important limitation of this entire phase.
- Manufacturing-intent and functional-completeness classification are
  both coarse, keyword-driven reads (inherited from
  `factory.hybrid_workflow`'s own Phase 48 design) - always low/medium
  confidence unless a human explicitly declares intent.
- Functional completeness can only ever check *whether* a mechanical
  feature exists, never whether it's the *right* one, sized correctly,
  or functionally sound - "never infer hidden features" is a hard
  design boundary, not an oversight.
- Print-readiness reuse is only as good as `part_manifest.json`/
  `export_receipt.json` - for a pure hybrid project (no traditional CAD
  export ever run), this legitimately reports "unresolved," which is
  correct, not a bug, but means `review_readiness`'s score is often low
  for an otherwise well-formed hybrid artifact until a human explicitly
  configures a printer/material for it.
- The optional snapshot (`--save`) is never automatically refreshed - a
  human must re-run `--save` to update it; nothing in this repo reads it
  automatically for any decision.

## No-authority rule

Never launches Meshy, Blender, a CAD backend, a slicer, or contacts a
printer/network. Never modifies geometry, a receipt, or any execution
artifact. Never sets `human_approved`/`print_ready`, and never reaches
`approved_for_print` in any field this module ever returns. See
`docs/hybrid-workflow.md`, `docs/blender-adaptation.md`, and
`docs/cad-augmentation.md` for the still-standing execution-gate rules
this phase only ever *reads evidence from*, never bypasses.

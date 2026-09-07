# Hybrid Design Workflow Manager (Phase 48)

`factory.hybrid_workflow` is the adaptation-planning layer between a
generative-AI concept artifact and manufacturing-ready Factory output.
**It never transforms anything.** It reads whatever already exists (a
Meshy receipt, a CAD generation/export receipt, an optional
`design_intent` block in `brief.json`) and produces one deterministic,
read-only `AdaptationPlan` - a recommendation a human reviews, never an
action taken.

    Meshy creates concepts.
    Factory transforms concepts into manufacturable designs.

## Why this phase exists

Phase 47B proved Meshy can produce a real, watertight, previewable
concept artifact end-to-end (see `docs/meshy-live-transport.md`). The
Phase 47B.7 post-flight review of that first real artifact (a piggy
bank, task `01a07ca5-0c06-7459-b1f4-68f383774fae`) also proved the
opposite half of the same lesson: the artifact came back with a
**~1479 x 1903 x 1412 mm bounding box** - roughly 1.9 meters tall. Every
geometry check passed (watertight, winding-consistent); the only WARN
was an unconfigured build-volume-fit check. The mesh was clean. The
*scale* was not manufacturing-ready, and nothing in this repo had a way
to say so before this phase.

    AI generated        != Manufacturing ready
    Mesh validated       != Printable
    Printable            != Good product
    Good product         != Human approved

Meshy is a good concept generator. Meshy output is not automatically
manufacturing-ready. This phase is the layer that says so, explicitly,
before anything downstream treats a concept as a finished part.

## Pipeline position

```
Idea
 |
Intake
 |
Design Intent
 |
Design Orchestrator          <- pre-generation engine recommendation (Phase 33)
 |
Engine Selection
 |
Meshy / Blender / CAD        <- generation (Phase 47 / future Blender-CAD tracks)
 |
Hybrid Design Workflow Manager   <- THIS PHASE (post-generation adaptation planning)
 |
Manufacturing Adaptation     <- future, separately-approved execution
 |
Validation
 |
Preview
 |
Review
 |
Slicer Readiness
 |
Human approval
```

**Not the same thing as `factory.design_orchestrator`.** That module
recommends an engine *before* any generation happens, from intake/brief/
design-intent signals alone - it already has a `"Hybrid Workflow"` value
in its own `RECOMMENDED_ENGINES` for a mixed organic+mechanical signal.
This module operates strictly *after* generation, on an artifact that
already exists, deciding what adaptation that specific artifact needs
next. Neither module re-implements the other.

## What this phase does not do

- Does not call Meshy, launch Blender, execute a CAD backend, invoke a
  slicer, or contact a printer or network.
- Does not rescale, repair, remesh, sculpt, hollow, or otherwise mutate
  any mesh file. `automatic_execution_allowed` is hardcoded `False` in
  every plan this module returns, and every individual adaptation step
  in a plan (except the read-only `factory_validation` step) carries its
  own `requires_human_confirmation: true`.
- Does not write a new receipt of its own. There is nothing to write yet
  - nothing here executes. A future, separately-scoped phase may add a
  `hybrid_workflow_receipt` once real adaptation execution exists.
- Does not bypass Blender qualification, headless rules, artifact
  provenance, validation, or review. A recommended Blender adaptation
  step always carries `factory.blender_gate.evaluate_blender_execution_gate()`'s
  real `gate_status`/`project_execution_approved` verbatim - it never
  claims Blender is ready to execute when the gate says otherwise
  (as of this phase, Blender's own project-execution gate remains
  unreached; see `docs/blender-local-track.md`).
- Does not change any project's `health_score` merely because a plan
  exists (see "Project Health" below).
- Does not invent a universal size table. The only size hints this
  module ever proposes (`figurine: 100-200mm`, `desk object: 50-300mm`)
  are Phase 48's own specified examples, always marked low-confidence,
  and never a substitute for a human-declared
  `design_intent.manufacturability_constraints.max_size_mm`.

## Workflow types

A minimum useful set (`WORKFLOW_TYPES`), not an exhaustive taxonomy:

| Workflow type | Typical origin | Typical routing |
| --- | --- | --- |
| `organic_concept_to_print` | Meshy | Blender adaptation -> validation |
| `decorative_collectible` | Meshy, no stronger signal | Blender adaptation -> validation |
| `hybrid_organic_mechanical` | Meshy + mechanical intent | Blender adaptation -> CAD augmentation -> validation |
| `mechanical_part_refinement` | CAD (OpenSCAD/CadQuery/FreeCAD) | CAD augmentation -> validation |
| `functional_product_design` | CAD + functional intent | CAD augmentation -> validation |
| `replacement_part_reconstruction` | Either, + replacement-part intent | CAD augmentation -> validation |
| `unknown` | No input artifact yet | (no steps) |

Classification is a coarse, always-advisory keyword read of a project's
own declared `design_intent.use_case` (via
`factory.design_intent_check.summarize_design_intent()` - never
re-parsed here), combined with the artifact's own provenance
(Meshy-origin vs. CAD-origin). `required_human_confirmations` always
includes "confirm workflow_type classification" - it is never treated
as ground truth.

## Tool routing

Reuses, never re-implements:

- `factory.engine_registry.get_tool_registry()` - per-tool suitability
  fields (`organic_modeling_suitability`, `mechanical_design_suitability`,
  `mesh_cleanup_suitability`, etc.). A CAD augmentation step's
  `candidate_tools` list is filtered to a fixed, small, hand-reviewed set
  (`cadquery`, `openscad_stable`, `freecad`) with
  `mechanical_design_suitability == "high"` - never every registry entry
  that happens to score high on an unrelated axis (a slicer, for
  instance).
- `factory.blender_gate.evaluate_blender_execution_gate()` (Phase 45) -
  the one existing source of "is Blender actually usable right now".

```
Organic collectible:      Meshy -> Blender -> Validation
Mechanical bracket:        CAD -> Validation
Organic + mechanical:      Meshy -> Blender -> CAD augmentation -> Validation
```

## Scale assessment

`assess_scale()` - a genuinely new capability. Nothing in this repo
before this phase judged whether an artifact's *absolute* size was
plausible; `factory.validators.dimension_check.check_build_volume_fit()`
only checks fit against a *configured printer's* build volume, a
different question entirely.

```json
{
  "current_dimensions_mm": {"x": 1478.97, "y": 1902.83, "z": 1411.77},
  "expected_dimensions_mm": null,
  "scale_factor": null,
  "implausible": false,
  "confidence": "unknown",
  "reason": "No declared design-intent size and no matching use-case hint - cannot assess plausibility.",
  "requires_human_confirmation": true
}
```

Priority order for `expected_dimensions_mm`:

1. **High confidence**: a project's own declared
   `design_intent.manufacturability_constraints.max_size_mm` (already
   read by `factory.design_intent_check`, never re-parsed here).
2. **Low confidence**: a loose keyword match against `design_intent.use_case`
   using Phase 48's own example table (`figurine`, `desk object`) -
   advisory only.
3. **Unknown**: neither exists. `expected_dimensions_mm` stays `None` -
   never guessed.

`requires_human_confirmation` is `true` unconditionally. This module
never rescales anything under any circumstance.

## Manufacturing intent

`assess_manufacturing_intent()` answers, at low/medium confidence only:
is this decorative, functional, load-bearing, mechanical, educational, a
replacement part, or a collectible? Built entirely from
`design_intent.use_case` keyword matches - reuses the existing reader,
never duplicates intake parsing. A Meshy-origin artifact with no
declared `use_case` at all gets a weak `"collectible"` default (Meshy is
reserved for organic concept generation in this repo - see
`docs/meshy-approval-gate.md`), explicitly labeled low-confidence and
always subject to human confirmation.

## Blender -> CAD handoff - implemented for one workflow in Phase 50

```
Meshy organic concept
        |
Blender cleanup           (geometry, scale, orientation)
        |
Manufacturing analysis
        |
CAD augmentation           (coin slot, base, mounting features)
        |
Validation                 (final object)
```

For the piggy-bank motivating example: Meshy supplies the body shape,
Blender adaptation cleans geometry/scale/orientation (Phase 49), and CAD
augmentation adds the functional coin slot, flat base, and mounting
features a sculpted mesh alone doesn't guarantee at dimensional
precision (Phase 50). None of this is executed by *this module* - it is
the plan `build_adaptation_plan()` proposes, gated on Blender's own
project-execution approval and a separately-approved CAD augmentation
step.

**Phase 50 implements the CAD half, narrowly, for one workflow:**
`factory.cad_augmentation.run_organic_mechanical_augmentation()`
generates a parametric functional-feature part (never a boolean-merge
with the organic mesh - see `docs/cad-augmentation.md`'s "Never a fused
mesh") and exports it via OpenSCAD - the only CAD engine this repo ever
executes for real (CadQuery remains never-executed, per
`docs/cad-backends.md`'s own standing policy). Verified live, end to
end, against the real piggy-bank artifact: a real 120x80x10mm base plate
with a 30x6x12mm coin slot and four 4mm mounting holes, producing a
genuine three-stage lineage (`meshy -> blender_adaptation ->
cad_augmentation`). See `docs/cad-augmentation.md`.

## Artifact lineage (future) - implemented for one workflow in Phase 49

A future real adaptation chain enters `factory.project_timeline`/
`factory.artifact_history` exactly like every other artifact-relevant
event already does (Meshy's own receipt -> timeline event, Phase 47B.7) -
never a second lineage/version model. Phase 48 itself adds no new
timeline adapter, because it writes no new artifact or receipt; there is
nothing yet to enter the timeline.

**Phase 49 implements exactly this, narrowly, for one workflow:**
`factory.blender_adaptation.run_organic_cleanup_workflow()` executes the
Blender adaptation step this module only ever recommended, and its
receipt (`generated/blender_adaptation_receipt.json`) follows the exact
reuse pattern anticipated above - parent artifact, child artifact, tool,
timestamp, fingerprint, and human-confirmation state, entering
`factory.project_timeline` as one new `blender_adaptation` event
category and `factory.artifact_history` via one additive path-
classification rule. See `docs/blender-adaptation.md`.

**Phase 50 extends the same chain one more link:**
`factory.cad_augmentation.run_organic_mechanical_augmentation()`
executes the CAD augmentation step this module only ever recommended,
following the identical receipt -> timeline-event -> artifact-history
reuse pattern (`generated/cad_augmentation_receipt.json` -> one new
`cad_augmentation` event category -> one additive path-classification
rule). See `docs/cad-augmentation.md`.

## Receipts

No `hybrid_workflow_receipt` exists - this module itself still writes
nothing; it remains planning-only. **Phase 49's `factory.blender_adaptation`
does write a receipt** (`generated/blender_adaptation_receipt.json`), but
that is a distinct module with its own gated execution path, not a
change to `factory.hybrid_workflow`'s own behavior. Meshy's own receipt,
the generation receipt, and the export receipt are all read (never
replaced) as this module's only inputs.

## Project Health

`factory.project_health`'s `health_score` is entirely untouched by this
phase, matching every prior Meshy-adjacent phase's own invariant - a
project's health must not appear "better" or "worse" merely because a
hybrid-workflow plan/recommendation exists for it (see
`tests/test_hybrid_workflow_preview.py`).

## Preview Board

`hybrid_workflow_summary` is wired into
`factory.preview_board.gather_board_data()` at the aggregation point
only (per the standing "Aggregation Layer Convention" in
`docs/architecture.md` - never inside `factory.project_health`/
`factory.project_inspection`, which would recreate a known circular
import). Deliberately no new HTML card: `workflow_type`,
`manufacturing_readiness`, `issue_count`, and `recommended_engine` are
compact enough to fold into existing readiness views rather than add
another noisy section.

## CLI

```
factory workflow plan <project_dir> [--json]
factory workflow assess <artifact_path> [--json]
```

Planning only - there is deliberately no `workflow execute` command.
`factory workflow plan` re-runs the existing Factory mesh validator
against a project's already-recorded input artifact and returns the full
`AdaptationPlan`. `factory workflow assess` is a lighter, standalone read
on any single mesh file with no project/receipt context required.

## Safety

Proven by `tests/test_hybrid_workflow_safety.py`: no subprocess/network-
capable import anywhere in `factory.hybrid_workflow` (a static AST scan,
not just inspection); `factory.blender_adapter`/`factory.cad.backend`
(the modules that actually execute Blender/CAD) are never imported;
every plan/assessment function still succeeds with `socket.socket`/
`subprocess.run`/`subprocess.Popen` poisoned to raise; no artifact file
is ever modified by planning, twice in a row; no new file appears on
disk merely from calling `build_adaptation_plan()`.

## Limitations

- Workflow-type and manufacturing-intent classification are both coarse
  keyword reads, not real natural-language understanding - always
  low/medium confidence, always subject to human confirmation.
- Scale assessment's `implausible` flag uses a simple 2x/0.5x ratio
  heuristic against whatever expected size is available; it is a
  sanity check, not a rigorous statistical model.
- No real Blender or CAD augmentation step has ever been executed by
  *this module* - `adaptation_steps` are recommendations, not proof any
  tool chain actually works end-to-end for a given artifact. (Phase 49's
  separate `factory.blender_adaptation` module executes the Blender half
  for `organic_cleanup_workflow`; Phase 50's separate
  `factory.cad_augmentation` module executes the CAD half for
  `organic_mechanical_augmentation` - both real, gated, verified live.
  Complex multi-feature CAD augmentation, and mechanical-only workflow
  types like `mechanical_part_refinement`, remain unimplemented.)
- No `hybrid_workflow_receipt`/timeline/artifact-history writer exists in
  *this* module, since nothing here executes; Phase 49's
  `factory.blender_adaptation` fills exactly this gap for its own one
  workflow, via its own receipt.

## Design quality / manufacturing readiness review (Phase 51)

`factory.design_review` (`factory design-review <project>`) is the final
intelligence layer over this module's whole pipeline - it answers "is
this artifact chain ready for human manufacturing review?" by reusing
`assess_scale()`/`assess_manufacturing_intent()` directly, applied to
whichever artifact is *actually current* (which this module alone cannot
determine, since it has no Blender/CAD-augmentation receipt awareness -
see "Artifact lineage" above). It never modifies geometry, never
executes anything, and never approves printing. See
`docs/design-review.md`.

See `docs/architecture.md`, `docs/meshy-adapter.md`,
`docs/meshy-live-transport.md`, `docs/blender-local-track.md`,
`docs/roadmap.md` Phase 48, `docs/phase-registry.md`, and `AGENT.md`.

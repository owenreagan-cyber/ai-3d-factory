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

## Blender -> CAD handoff (future)

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
Blender adaptation would clean geometry/scale/orientation, and CAD
augmentation would add the functional coin slot, flat base, and any
mounting/access features a sculpted mesh alone doesn't guarantee at
dimensional precision. None of this is executed by Phase 48 - it is the
plan `build_adaptation_plan()` proposes, gated on Blender's own
project-execution approval (still unreached) and a future, separately-
approved CAD augmentation phase.

## Artifact lineage (future)

A future real adaptation chain enters `factory.project_timeline`/
`factory.artifact_history` exactly like every other artifact-relevant
event already does (Meshy's own receipt -> timeline event, Phase 47B.7) -
never a second lineage/version model. Phase 48 itself adds no new
timeline adapter, because it writes no new artifact or receipt; there is
nothing yet to enter the timeline. When a future phase actually executes
a Blender/CAD adaptation step, its receipt should follow the same
`project_timeline`/`artifact_history` reuse pattern as
`factory.hybrid_workflow`'s own design already anticipates: parent
artifact, child artifact, tool, version, timestamp, fingerprint, and
human approval state, each just another timeline event these two
existing systems already know how to version and diff.

## Receipts

No `hybrid_workflow_receipt` exists yet - there is nothing to persist
until real adaptation execution exists. Meshy's own receipt, the
generation receipt, and the export receipt are all read (never
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
  this module - `adaptation_steps` are recommendations, not proof any
  tool chain actually works end-to-end for a given artifact.
- No `hybrid_workflow_receipt`/timeline/artifact-history writer exists
  yet, since nothing here executes; this is a documented, deliberate gap
  for a future execution phase to fill.

See `docs/architecture.md`, `docs/meshy-adapter.md`,
`docs/meshy-live-transport.md`, `docs/blender-local-track.md`,
`docs/roadmap.md` Phase 48, `docs/phase-registry.md`, and `AGENT.md`.

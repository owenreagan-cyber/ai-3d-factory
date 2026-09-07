# CAD Augmentation Execution Gate & Organic-Mechanical Hybrid Workflow (Phase 50)

`factory.cad_augmentation` builds the controlled bridge from an
already-adapted organic artifact to a manufacturing-ready hybrid
product:

```
Blender adapted organic artifact
    |
CAD augmentation
    |
Manufacturing-ready hybrid artifact
    |
Validation
    |
Preview
    |
Human review
```

This is the second real-execution gate this repo has built (after Phase
49's Blender adaptation) - the first to combine an AI-adapted organic
body with an engineered functional feature.

```
AI concept              != engineering design
CAD output                != manufacturing approved
Validation                  != human approval
Human approval                 != print approval
Automatic printing remains impossible.
```

CAD is an engineering augmentation tool here - **not** an automatic
product designer, not an automatic dimension solver, and not an
automatic engineering-approval system.

## Mandatory inspection this phase performed before writing any code

Per this phase's own spec: `factory.hybrid_workflow`,
`factory.blender_adaptation`/`blender_adapter`/`blender_gate`,
`factory.export_pipeline`, `factory.generation_gate`,
`factory.engine_registry`, `factory.design_orchestrator`,
`factory.project_timeline`, `factory.artifact_history`,
`factory.validators.*`, `factory.cli`, `factory.preview_board`, and
`factory.cad.{backend,router,cadquery_backend,manifest}`, plus
`docs/hybrid-workflow.md`, `docs/blender-adaptation.md`,
`docs/cad-backends.md`, `docs/openscad-generation.md`,
`docs/file-lifecycle.md`, `docs/architecture.md`, `docs/roadmap.md`,
`docs/phase-registry.md`, and the export-pipeline/hybrid-workflow/
blender-adaptation/artifact-history/timeline test files. Findings:

- **Current CAD capabilities:** OpenSCAD (`factory.openscad.generate`,
  `available`, `factory_workflow_verified` qualification) and CadQuery
  (`factory.cad.cadquery_backend`, `available` when installed,
  `not_installed` on this machine) both write source only into a
  project's `cad/` directory, via the general-purpose `factory
  generate-openscad`/`generate-cadquery` commands - neither is scoped to
  "attach a feature to an already-existing externally-adapted mesh."
- **Current CAD execution safety:** OpenSCAD has a complete, bounded,
  tested subprocess-execution path (`factory.export_pipeline`, Phase
  35). **CadQuery has none, by explicit, repeated, unconditional
  design** - see "Why OpenSCAD executes and CadQuery does not" below.
- **OpenSCAD status:** `available`, `cli_available=True`,
  `mechanical_design_suitability="high"` in `factory.engine_registry`,
  genuinely installed and working on this development machine.
- **CadQuery status:** `available` only if installed (`not_installed`
  on this machine), `mechanical_design_suitability="high"` too - tied
  with OpenSCAD/FreeCAD on paper, but never executed regardless of
  suitability score (see below).
- **FreeCAD status:** `mechanical_design_suitability="high"` as well,
  but `cli_available=False` and `qualification_level="metadata_only"` -
  no execution path exists anywhere in this repo, matching
  `docs/roadmap.md`'s framing of FreeCAD as "future complex workflows."
- **Existing generation paths:** `factory.cad.router.route_cad()` is a
  *different* routing concern (pre-generation, text-description-based,
  for `factory route-cad`/intake) - never reused or duplicated here.
  `factory.hybrid_workflow._mechanical_augmentation_step()` already
  computes the right candidate-tool list for *this* concern
  (post-adaptation, artifact-specific augmentation); this phase reuses
  the same underlying `factory.engine_registry` data and fixed tool-id
  list, never re-scoring suitability.
- **Where CAD augmentation attaches:** exactly where
  `factory.hybrid_workflow.build_adaptation_plan()`'s
  `cad_mechanical_augmentation` step already describes - after a
  Blender-adapted (or any) artifact exists, using the identical
  reuse pattern every Phase 34-49 receipt/lineage integration already
  established. No existing system is duplicated.

## Why OpenSCAD executes and CadQuery does not

`docs/cad-backends.md` states, repeatedly and unconditionally (not
"not yet"): **this repo does not import or execute the CadQuery source
it writes** - `factory.cad.cadquery_backend.generate_cadquery()` writes
`.py` source only, and `factory.export_pipeline` itself refuses to run
it (`"manual_export_required"`, regardless of `--confirm-export`).
`factory.tool_qualification`'s own in-process CadQuery capability probe
(`cq.Workplane("XY").box(10, 10, 10)`) is a narrow, documented exception
scoped to a throwaway 10mm-cube fixture - never a real project artifact.

This is a meaningfully different textual signal from Blender's own
history: `docs/blender-adapter.md` explicitly staged "a future real
Blender project-generation phase" that Phase 49 then became. No CadQuery
doc anywhere in this repo stages an analogous future execution phase -
the policy reads as standing and permanent, not a placeholder waiting
for its own "Phase 45." This phase does not relax it, read it narrowly,
or carve out a new exception for "fixed, Factory-authored code" the way
Blender's fixture-to-real-execution progression did - CadQuery execution
stays exactly as forbidden here as everywhere else in this repo.

**OpenSCAD, by contrast, already has a complete, safe, bounded,
already-tested execution path** (`factory.export_pipeline`, Phase 35)
and is explicitly the right tool for "simple parametric additions" - a
coin slot, mounting holes, a flat base plate, exactly this workflow's
scope. This phase's one real execution therefore routes through OpenSCAD
only, reusing `factory.export_pipeline.run_scad_source_to_stl()` (the
one new function that module gained - the same resolved-executable/
argument-list/`shell=False`/hard-timeout/output-verification safety
posture `run_export()` already uses, generalized to an arbitrary output
path since this workflow's directory convention differs from the
`cad/` -> `stl/` project layout `run_export()` is scoped to).

CadQuery and FreeCAD are still reported as candidate engines (from
`factory.engine_registry`'s own suitability data) so a human sees the
full picture - `recommended_cad_engine` never claims either will be
executed, and no code path in this module ever calls the `cadquery`
package's API or launches FreeCAD.

## Never a fused mesh - a second, separate part

`factory.validators.multipart_check`'s own standing policy (Phase 0/1,
`docs/slicer-review-workflow.md`) is: **prefer separate aligned STL
files sharing one origin over a single fused mesh for multi-color/
multi-material work.** `organic_mechanical_augmentation` follows this
exactly - it never booleans, merges, or otherwise combines the organic
mesh's own triangle data with the newly generated CAD feature. It
produces one new, independent STL (the "mechanical component"), which
becomes part of the same product alongside the existing organic artifact
(the "organic component") the same way every other multi-part project in
this repo already works (`examples/multipart-classroom-sign/`,
`examples/storage-bin-lid/`).

This also sidesteps a real, unresolved technical risk this phase
deliberately does not take on: booleaning a CAD kernel solid against an
arbitrary, possibly non-manifold-adjacent, multi-million-triangle organic
mesh is exactly the kind of "automatic parametric reconstruction"/
"complex assembly" this phase's own spec excludes. A human aligns and
assembles the two parts in their slicer, exactly as the existing
multi-part convention already expects.

## Module layout - nothing duplicated

```
factory/engine_registry.py       - mechanical_design_suitability (Phase 43, reused verbatim)
factory/export_pipeline.py       - resolve_openscad_executable() (reused) + run_scad_source_to_stl() (new, Phase 50)
factory/blender_adaptation.py    - read_blender_adaptation_receipt() (reused, for organic-component lineage)
factory/cad_augmentation.py      - NEW module: routing, parameter model, planning, gating, receipt, lineage wiring, CLI-facing logic
factory/project_timeline.py      - _events_from_cad_augmentation_receipt() (new, additive adapter)
factory/artifact_history.py      - generated/cad_augmentation/*.stl classified as "stl" (new, additive rule)
factory/preview_board.py         - cad_augmentation_summary (new, aggregation point only)
factory/cli.py                   - `factory cad-augment plan|execute` (new Typer group)
```

`factory.cad_augmentation` never invokes a subprocess itself - it calls
`factory.export_pipeline.run_scad_source_to_stl()`, which remains the
only real invocation this phase adds. It never imports `cadquery`,
`factory.cad.cadquery_backend`, or `factory.blender_adapter` (proven by a
static AST scan, not just inspection).

## The one supported workflow: `organic_mechanical_augmentation`

Fixed, deterministic operation sequence
(`factory.cad_augmentation.CAD_AUGMENTATION_OPERATIONS`), rendered
verbatim in every plan a human reviews before confirming:

```
generate_scad_source -> export_stl
```

Explicitly **not** attempted, this phase or without a separate, future,
explicitly-scoped phase: full reverse engineering, automatic parametric
reconstruction, complex multi-feature assemblies, mechanical simulation,
or stress analysis. The generated feature is one parametric OpenSCAD
"functional base plate" - a rectangular plate with an optional coin slot
cutout and optional 4-corner mounting holes, mirroring
`factory.cad.cadquery_backend._mechanical_plate_source()`'s own
parametrization style (box + optional cutouts), reimplemented in
OpenSCAD since this phase never executes CadQuery.

## CAD routing - reuses `engine_registry`, adds nothing parallel

`factory.cad_augmentation._select_cad_engine()` reuses the exact same
fixed candidate-tool-id list and `mechanical_design_suitability` registry
field `factory.hybrid_workflow._mechanical_augmentation_step()` already
uses (`cadquery`, `freecad`, `openscad_stable`, filtered to `"high"`) -
never a second suitability scorer. It then narrows to exactly one
*executable* engine (`openscad_stable`) - see "Why OpenSCAD executes and
CadQuery does not" above. `recommended_cad_engine` is always this one
engine or `None`; `candidate_engines` lists every "high"-suitability tool
for a human's awareness, whether or not this phase can execute it.

## Parameter model - explicit only, never guessed

Every critical dimension is required, with no silent default:

- `base_width_mm`, `base_length_mm`, `base_height_mm` - always required.
- `coin_slot_width_mm`, `coin_slot_length_mm`, `coin_slot_depth_mm` -
  become required together the moment any *one* of them is given (a
  coin slot with an unspecified depth is not a safe default to invent).
  `coin_slot_position_x_mm`/`coin_slot_position_y_mm` default to
  centered on the base plate if omitted - a placement convenience, never
  a critical dimension (a slot's *size* matters for function; its
  default position does not, the same way
  `factory.cad.cadquery_backend`'s own `hole_margin_mm` already has a
  sensible, documented default).
- `mounting_hole_diameter_mm` - optional; if given, adds four
  corner-positioned mounting holes at `mounting_hole_margin_mm` (default
  8.0mm, mirroring the CadQuery template's identical default) from each
  edge.

`build_augmentation_plan()`'s `required_parameters` lists every one of
these with `required`/`provided`/`value`; `requires_human_input` lists
exactly the required-but-missing ones. `execution_allowed` is `False`
whenever `requires_human_input` is non-empty - `execute` additionally
makes `--base-width-mm`/`--base-length-mm`/`--base-height-mm` required
CLI options, so a human cannot even attempt execution without them.

## The execution gate - explicit confirmation, controlled output, bounded execution

`factory.cad_augmentation.run_organic_mechanical_augmentation()`
requires, freshly re-checked on **every single call**, nothing cached:

1. **A valid augmentation plan** - `build_augmentation_plan()` reports no
   `blockers` and `execution_allowed: true` (input artifact exists and
   validates, a project directory is resolvable, every required
   parameter provided, an executable CAD engine available, the planned
   output path does not already exist).
2. **Explicit, per-invocation human confirmation** - `--confirm`. Like
   Phase 49, there is no standing "approved" state anywhere in this
   repo; every execution is a one-shot decision, recorded as
   `single_shot_human_confirmation: true` (never conflated with
   `project_execution_approved`, which stays hardcoded `false`
   everywhere).
3. **Controlled, deterministic output path** - the feature source and
   output STL paths are always the two Factory-computed paths under
   `generated/cad_augmentation/`; no command in this repo accepts an
   arbitrary caller-supplied output path. Refuses to overwrite an
   existing file at either path.
4. **Bounded execution** - the one real OpenSCAD subprocess call
   (`factory.export_pipeline.run_scad_source_to_stl()`) uses the same
   resolved-executable/argument-list/`shell=False`/hard-timeout safety
   posture every other OpenSCAD invocation in this repo already uses; a
   zero exit code alone is never treated as success.

No bypass exists for any of the four - `build_augmentation_plan()` is
the only source of truth each check reads.

## Backend safety

- **OpenSCAD** - the existing safe generation pattern
  (`factory.export_pipeline`) is reused unmodified in spirit: resolved
  executable, argument list, `shell=False`, hard timeout, output
  existence/non-emptiness verified before success is ever reported.
- **CadQuery** - never executed (see above). No code path in
  `factory.cad_augmentation` imports `cadquery` or calls its API -
  proven by a static AST scan in `tests/test_cad_augmentation_safety.py`.
- **FreeCAD** - never launched, no GUI, no subprocess call of any kind.
  `cli_available=False` in `factory.engine_registry`; this phase adds no
  new FreeCAD capability.
- No AppleScript, GUI automation, mouse/keyboard control, or arbitrary
  script execution anywhere in this module.

## Adaptation plan model

`factory.cad_augmentation.build_augmentation_plan()` returns:

```json
{
  "input_artifact": "...",
  "project": "...",
  "workflow_type": "organic_mechanical_augmentation",
  "organic_component": {
    "is_blender_adapted": true,
    "blender_workflow": "organic_cleanup_workflow",
    "blender_scale_factor_applied": 0.07883,
    "mesh_stats": { "...": "bounding_box_mm, volume_mm3, watertight, ..." }
  },
  "mechanical_component": {
    "coin_slot_requested": true,
    "mounting_holes_requested": true,
    "parameters": [ { "name": "base_width_mm", "required": true, "provided": true, "value": 120.0 }, "..." ]
  },
  "recommended_cad_engine": "openscad_stable",
  "candidate_engines": ["cadquery", "freecad", "openscad_stable"],
  "cad_operations": ["generate_scad_source", "export_stl"],
  "required_parameters": ["..."],
  "requires_human_input": [],
  "human_confirmations": ["..."],
  "output_artifact": ".../generated/cad_augmentation/<stem>_feature.stl",
  "validation_plan": {"validator": "factory.validators.mesh_validate.validate_mesh", "reused": true},
  "preview_plan": {"renderer": "factory.previews.render_preview.render_preview", "reused": true},
  "issues_found": [],
  "execution_allowed": true,
  "automatic_execution_allowed": false,
  "no_automatic_print": true
}
```

Plan first. Execution requires confirmation -
`build_augmentation_plan()` never generates CAD source or invokes
OpenSCAD by itself, regardless of its own `execution_allowed` value.

## Artifact lineage - extends the Meshy -> Blender -> CAD chain

A completed execution writes
`generated/cad_augmentation_receipt.json`, which
`factory.project_timeline._events_from_cad_augmentation_receipt()` (one
new, additive adapter, mirroring
`_events_from_blender_adaptation_receipt()` exactly) turns into exactly
one `cad_augmentation` timeline event, carrying both the organic input
artifact's and the new feature artifact's `{relative_path:
sha256_fingerprint}` pairs. `factory.artifact_history` picks these up
automatically through its existing, unchanged version-derivation logic -
the only change needed there was one additive path-classification rule
(`generated/cad_augmentation/*.stl` -> `"stl"`).

**Verified live** against `projects/meshy-live-smoke-test`'s real
piggy-bank artifact: `factory timeline`/`factory artifact-history` both
render a genuine three-stage lineage chain -
`meshy -> blender_adaptation -> cad_augmentation` - with correct parent/
child fingerprints at every stage.

## Receipt: `generated/cad_augmentation_receipt.json`

Written only on `augmentation_status == "succeeded"`; never overwrites
an existing receipt.

```json
{
  "cad_augmentation_version": 1,
  "workflow": "organic_mechanical_augmentation",
  "input_artifact": "generated/blender/adapted/<stem>_adapted.stl",
  "input_hash": "sha256:...",
  "feature_source": "generated/cad_augmentation/<stem>_feature.scad",
  "output_artifact": "generated/cad_augmentation/<stem>_feature.stl",
  "output_hash": "sha256:...",
  "cad_engine": "openscad_stable",
  "cad_engine_version": "OpenSCAD version 2021.01",
  "operations": ["generate_scad_source", "export_stl"],
  "parameters": {"base_width_mm": 120.0, "base_length_mm": 80.0, "base_height_mm": 10.0, "...": "..."},
  "single_shot_human_confirmation": true,
  "confirmed_by": null,
  "validation_status": "PASS",
  "preview_status": "PASS",
  "human_review_state": "required",
  "project_execution_approved": false,
  "automatic_print_allowed": false,
  "no_automatic_print": true,
  "mesh_boolean_merge_performed": false
}
```

## Validation and preview - reused, not duplicated, never trusting CAD output

After a successful execution, the *new* feature output is re-validated
(`factory.validators.mesh_validate.validate_mesh()`, which already
reuses `factory.validators.dimension_check.check_build_volume_fit()`
internally - no separate dimension-check call needed) and re-previewed
(`factory.previews.render_preview.render_preview()` ->
`<stem>_feature_preview.png`) - the same Factory validator/renderer
every other mesh in this repo goes through. A zero OpenSCAD exit code
never overrides Factory validation: a `FAIL` on the generated feature is
recorded as an error even though the subprocess itself exited 0.
"Preview: final hybrid artifact, not just the source mesh" is satisfied
by previewing the newly generated feature part specifically - the
artifact this workflow actually produced - never by re-showing the
organic body's own, already-existing preview as if nothing changed.

## CLI

```
factory cad-augment plan <artifact_path> [--base-width-mm N] [--base-length-mm N] [--base-height-mm N]
    [--coin-slot-width-mm N] [--coin-slot-length-mm N] [--coin-slot-depth-mm N]
    [--coin-slot-position-x-mm N] [--coin-slot-position-y-mm N]
    [--mounting-hole-diameter-mm N] [--mounting-hole-margin-mm N] [--json]

factory cad-augment execute <artifact_path> --base-width-mm N --base-length-mm N --base-height-mm N
    [--coin-slot-width-mm N] [--coin-slot-length-mm N] [--coin-slot-depth-mm N]
    [--coin-slot-position-x-mm N] [--coin-slot-position-y-mm N]
    [--mounting-hole-diameter-mm N] [--mounting-hole-margin-mm N]
    --confirm [--confirmed-by NAME] [--json]
```

Kept as its own Typer group, separate from `factory workflow` (planning-
only, per Phase 48's own documented invariant) and `factory blender-adapt`
(a different workflow). No `factory cad run-arbitrary-file` or any other
arbitrary-execution interface exists - every command name is a fixed,
narrow verb, and no option anywhere accepts a script/file path.

## Preview Board

`cad_augmentation_summary` is wired into
`factory.preview_board.gather_board_data()` at the aggregation point
only (per the standing "Aggregation Layer Convention" in
`docs/architecture.md`), mirroring `blender_adaptation_summary`'s own
placement exactly. It only ever reads an existing receipt (or reports
`augmentation_available: false`) - never invokes OpenSCAD, never a
subprocess of any kind, during board generation. Deliberately no new
HTML card.

## Project Health - unchanged

`factory.project_health`'s `health_score` computation is untouched by
this phase, matching every prior Blender/Meshy-adjacent phase's own
invariant.

## Testing

`tests/test_cad_augmentation.py` (routing, parameter model, SCAD
generation, plan generation, gated execution, receipt shape - real
`openscad` CLI conventions mocked via monkeypatched
`export_pipeline.resolve_openscad_executable`/`subprocess.run`, the same
convention `tests/test_export_pipeline.py` already established),
`tests/test_cad_augmentation_cli.py` (`plan`/`execute` commands),
`tests/test_cad_augmentation_safety.py` (AST scans: no subprocess/
network import in `factory.cad_augmentation` itself; no `cadquery`
import or API call site anywhere; no `factory.blender_adapter` import;
path containment; no overwrite of the organic artifact or an existing
receipt/output; the generated SCAD source never references the input
STL path at all - proving there is no accidental merge path; behavioral
proof that planning survives poisoned `socket`/`subprocess`), and
`tests/test_cad_augmentation_preview.py` (Preview Board summary wiring,
no OpenSCAD execution during board generation).

**Real execution verified** end-to-end against
`projects/meshy-live-smoke-test` (a gitignored, disposable smoke-test
project - never `examples/`, never a production project): a real
120x80x10mm base plate with a 30x6x12mm coin slot and four 4mm mounting
holes was generated, exported, validated (WARN - the same generic
unconfigured-build-volume note every mesh in this repo without a
confirmed printer gets), and previewed (PASS), with no lingering
`openscad` process, `examples/`/`state/`/`config/` byte-identical
afterward, and every output correctly contained under
`generated/cad_augmentation/`.

## Limitations

- Only one feature template exists (a rectangular base plate with an
  optional coin slot and optional 4-corner mounting holes) - no general
  parametric-feature library.
- No `--force`/`--overwrite-generated` flag exists - a collision with an
  existing output, feature source, or receipt always blocks; a human
  must remove the conflicting file themselves before re-running.
- A project may run `organic_mechanical_augmentation` once per input
  artifact through the single `generated/cad_augmentation_receipt.json`
  path - re-running against a different organic artifact within the same
  project will refuse to overwrite that receipt (mirrors Phase 49's
  identical, documented limitation).
- No combined organic+mechanical preview render exists - the two parts
  are previewed independently; a human aligns and reviews them together
  in a slicer, exactly as the existing multi-part convention already
  expects.
- CadQuery/FreeCAD routing is reported but never exercised for real -
  if a future phase ever wants a CadQuery-executed workflow, that
  requires its own separate, explicit, dated authorization (mirroring
  how Phase 49 itself became Blender's authorization), never an
  incidental side effect of this phase.

**Phase 51 addendum:** `factory.design_review` (`factory design-review
<project>`) reads this module's own `read_cad_augmentation_receipt()`
directly to verify lineage consistency and functional-completeness
(does the expected mechanical feature actually exist) - never a second
receipt reader, never a re-derivation of this module's own execution
gate. See `docs/design-review.md`.

## No-authority rule

Never launches a GUI (OpenSCAD, FreeCAD, or otherwise), installs an
add-on, changes an application preference, contacts a slicer, printer,
or network, generates G-code, executes CadQuery, or performs a mesh
boolean-merge. Never sets `human_approved`/`print_ready`.
`project_execution_approved` stays `false` everywhere this phase's code
touches it - a single-shot, per-invocation human confirmation is
recorded under its own, differently named field
(`single_shot_human_confirmation`), never conflated with a standing
approval state. See `docs/cad-backends.md` and
`docs/blender-adaptation.md` for the still-standing rules this phase
narrows only for its own one workflow, never for broader CAD automation.

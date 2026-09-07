# Blender Adaptation Execution Gate & Controlled Organic Cleanup Workflow (Phase 49)

`factory.blender_adaptation` proves exactly one safe Blender adaptation
workflow, end to end, against a real project artifact:

```
Meshy artifact
    |
Blender controlled adaptation
    |
Factory artifact
    |
Validation
    |
Preview
    |
Human review
```

This is the first module in this repo that executes real Blender
automation against a real project artifact. Phase 45
(`docs/blender-adapter.md`) proved Blender *can* run headlessly and
export a mesh the Factory can validate and preview - but only against one
throwaway fixture, never a project file. Phase 47B/47B.7 proved Meshy can
produce a real, watertight, previewable concept artifact - and that the
artifact's *scale* is not automatically manufacturing-ready (the first
real piggy-bank artifact came back at a ~1.9 meter bounding box). Phase
48 (`docs/hybrid-workflow.md`) built the planning layer that says so, and
recommends a Blender adaptation step - but never executes it. This phase
is the "future, separately-approved execution" both of those documents
named and deferred to.

## The core distinctions this phase holds in full

```
AI output              != manufacturing ready
Blender output          != approved product
Validation               != human approval
Human approval             != print approval
Automatic printing remains impossible.
```

Blender is an adaptation tool here - **not** an automatic product
generator, not an automatic repair system, and not an automatic
manufacturing-approval system.

## Why real execution is safe to add in this phase, without touching `config/future_local_tools.json`

`docs/blender-local-track.md`'s original checklist (Phase 21) requires "a
named, dated decision... not an inferred default" before real Blender
project automation is authorized, and `config/future_local_tools.json`'s
`tools.blender.enabled`/`allows_automation`/`allows_background_execution`
record that this has not happened. Phase 45's own gate-checklist item 1
resolved the identical question for its fixture pipeline by treating
**that phase's own spec** as the dated, explicit human instruction that
narrowly authorized it - without flipping any config flag, because a
one-shot, Factory-owned, throwaway-fixture pipeline is not "Blender
automation is enabled" in the sense that config represents.

**This phase follows the identical precedent.** This phase's own dated
spec (2026-09-07) is the explicit human instruction that narrowly
authorizes exactly `organic_cleanup_workflow`, and `config/future_local_tools.json`
stays untouched:

- `enabled`/`allows_automation`/`allows_background_execution` correctly
  continue to mean "Blender runs unattended, on its own, as a standing
  state" - never true here. Every single real execution requires a
  **fresh** `--confirm` flag on that exact CLI invocation; nothing about
  a prior confirmation, a prior qualification, or a prior execution is
  ever cached, persisted, or trusted across calls.
- The workflow scope is exactly as narrow as the fixture pipeline's:
  **one workflow, three fixed operations (import STL, apply one uniform
  scale factor, export STL), never mesh repair, remeshing, decimation,
  smoothing, retopology, sculpting, texturing, or any broader Blender
  use.**
- Flipping that repo-wide config would be a much bigger, and different,
  claim than what this phase actually authorizes - it would read as "all
  Blender automation, for every future workflow, is now approved,"
  which this phase's spec explicitly does not say. Leaving it `false`
  and documenting the narrower authorization here instead keeps that
  config's meaning intact for whatever broader decision is eventually
  made.

If a future phase ever does want to flip that config (e.g. to support a
second workflow, or scheduled/unattended execution), that remains the
separate, later, explicit decision `docs/blender-local-track.md` always
described - this phase does not make it, and does not need to in order
to implement `organic_cleanup_workflow` safely.

## Mandatory inspection this phase performed before writing any code

Per this phase's own spec, before any implementation: `factory.hybrid_workflow`,
`factory.blender_gate`, `factory.blender_adapter`, `factory.tool_qualification`,
`factory.meshy_live_adapter`, `factory.meshy_adapter`, `factory.project_timeline`,
`factory.artifact_history`, `factory.export_pipeline`,
`factory.validators.mesh_validate`, `factory.project_store`,
`factory.project_health`, `factory.preview_board`, `factory.cli`, and the
docs this file cross-references throughout, plus every Blender/hybrid-
workflow/mesh-validation/artifact-history/timeline test file that already
existed. Findings:

- **Existing Blender safety model:** `factory.blender_gate` (read-only
  planning, zero subprocess) + `factory.blender_adapter` (the sole
  subprocess-invoking module, two real invocations, both bounded,
  `--background`/`--factory-startup`/`-Y`/`--offline-mode`, argument
  list, `shell=False`, hard timeout) - see `docs/blender-adapter.md`.
- **Existing Blender execution capability:** exactly the Phase 45
  fixture pipeline (a fixed sphere, `tempfile.TemporaryDirectory()`-only,
  never a project file). No project-artifact execution path existed.
- **Current blockers:** none technical - Phase 45/48 both explicitly
  documented this exact future step and left the door open, narrowly.
  The only real decision was *how* to gate real execution without
  either inventing a second permission system or silently expanding
  `config/future_local_tools.json`'s meaning (resolved above).
- **Current artifact lifecycle:** `projects/<slug>/generated/` holds
  lazily-created, per-source receipts (`generation_receipt.json`,
  `export_receipt.json`, `meshy_receipt.json`, each read by
  `factory.project_timeline` via one additive adapter function).
  `factory.artifact_history` derives version numbers purely from
  timeline events + fingerprints, never a stored counter.
- **Where adaptation attaches:** exactly at the point
  `factory.hybrid_workflow.build_adaptation_plan()`'s
  `blender_organic_adaptation` step already describes - reading the same
  Meshy/CAD-origin artifact, reusing the same `assess_scale()`, and
  writing a new receipt/timeline-event/artifact-history-entry using the
  identical reuse pattern every other Phase 34-48 receipt already
  established. No existing system is duplicated.

## Module layout - nothing duplicated

```
factory/hybrid_workflow.py     - assess_scale() (Phase 48, reused verbatim)
factory/blender_gate.py        - plan_organic_cleanup_execution() (new, read-only planning)
factory/blender_adapter.py     - run_organic_cleanup_workflow() (new, the one additional bounded subprocess call)
factory/blender_adaptation.py  - NEW module: orchestration, gating, receipt, lineage wiring, CLI-facing logic
factory/project_timeline.py    - _events_from_blender_adaptation_receipt() (new, additive adapter)
factory/artifact_history.py    - generated/blender/*.stl classified as "stl" (new, additive rule)
factory/preview_board.py       - blender_adaptation_summary (new, aggregation point only)
factory/cli.py                 - `factory blender-adapt plan|execute` (new Typer group)
```

`factory.blender_adaptation` never launches Blender itself - it calls
`factory.blender_adapter.run_organic_cleanup_workflow()`, which remains
the only module in this repo that ever passes Blender to `subprocess`.
It never re-derives scale plausibility - it calls
`factory.hybrid_workflow.assess_scale()`. It never invents a second
Blender permission system - it calls
`factory.blender_gate.evaluate_blender_execution_gate()`/
`plan_organic_cleanup_execution()`. It never writes a second lineage/
version model - it feeds `factory.project_timeline`/`factory.artifact_history`
additively, exactly like Meshy's own receipt already does.

## The one supported workflow: `organic_cleanup_workflow`

Fixed, deterministic operation sequence (`factory.blender_gate.ORGANIC_CLEANUP_OPERATIONS`),
rendered verbatim in every plan a human reviews before confirming:

```
import_stl -> apply_scale_factor -> export_stl
```

Explicitly **not** attempted, this phase or without a separate, future,
explicitly-scoped phase: mesh repair, remeshing, decimation, smoothing,
retopology, sculpting, texturing, rigging, animation, Geometry Nodes
automation, procedural generation, or any other broader Blender use.
Only one uniform scale factor is ever applied - never anisotropic
per-axis scaling, never rotation, never translation beyond whatever the
import itself produces.

The script: `blender_fixtures/factory_organic_cleanup_workflow.py` -
fixed, hand-written, repository-reviewed, checked into version control,
living outside `src/` for the identical reason
`blender_fixtures/factory_qualification_fixture.py` does (so its
`import bpy` never collides with the repo-wide
`tests/test_blender_gate.py::test_no_blender_execution_code_anywhere_in_src`
scan). It imports only `bpy`/`sys`, reads no file or environment variable
of its own choosing (its only inputs are the two paths and the scale
factor given after `--`), and writes to exactly one path - the output
path it was given.

## Scale normalization - the primary use case

**Never silently scales anything.** `organic_cleanup_workflow` requires a
human-supplied target dimension before it will compute a scale factor,
and requires a fresh `--confirm` before it will apply one:

- `factory blender-adapt plan <artifact> [--target-max-mm N]` - fully
  read-only. Reuses `factory.hybrid_workflow.assess_scale()` for a
  *plausibility* read of the artifact's current size against whatever
  `design_intent` evidence already exists (unchanged from Phase 48:
  high-confidence declared `max_size_mm`, low-confidence use-case hint,
  or unknown - never guessed). Independently, if `--target-max-mm` is
  given, computes `proposed_scale_factor = target_max_mm /
  current_largest_dimension_mm` - a *proposal*, never applied by
  planning.
- `factory blender-adapt execute <artifact> --target-max-mm N --confirm`
  - `--target-max-mm` is **required** here (never inferred from
  `design_intent`, never defaulted); `--confirm` is required and is
  never persisted or reusable across calls.

Every plan/receipt reports current dimensions, target dimensions, the
computed scale factor, and `assess_scale()`'s own confidence/reason -
never an assumption that all figurines, all objects, or all Meshy output
share one size convention (unchanged from Phase 48's own explicit
design principle).

## The execution gate - reuses `factory.blender_gate`, adds nothing parallel

`factory.blender_adaptation.run_organic_cleanup_workflow()` requires,
freshly re-checked on **every single call**, nothing cached:

1. **A valid adaptation plan** - `build_adaptation_execution_plan()`
   reports no `issues_found` and `execution_allowed: true` (input
   artifact exists and validates, a project directory is resolvable, a
   positive scale factor is computable, the planned output path does not
   already exist).
2. **Blender detected** -
   `factory.blender_gate.evaluate_blender_execution_gate()["detected"]`.
3. **A fresh, full fixture-qualification proof** -
   `factory.blender_adapter.qualify_blender_adapter(confirm_fixture=True)`
   must reach `adapter_qualification_status == "qualified"` **on this
   exact call**. This re-runs the entire Phase 45 fixture pipeline
   (headless verify, fixture export, Factory validation, Factory
   preview, cleanup verification) immediately before touching the real
   artifact - proving the pipeline actually works right now, never
   trusting a qualification that happened at some earlier time. This is
   deliberately expensive (two real Blender invocations per confirmed
   execution) in exchange for never trusting cached/stale evidence - the
   same "verify fresh, never cache" philosophy Phase 45 already
   established for its own headless check.
4. **Explicit, per-invocation human confirmation** - `--confirm`. There
   is no standing "approved" state anywhere in this repo; every
   execution is a one-shot decision, recorded in the receipt as
   `single_shot_human_confirmation: true` (deliberately not named
   `project_execution_approved`, which this repo's vocabulary reserves
   for a *standing* approval state that stays hardcoded `false`
   everywhere).
5. **Output path approval** - the output path is always the one
   deterministic, Factory-computed child-artifact path
   (`<project>/generated/blender/adapted/<stem>_adapted.stl`); no
   command in this repo accepts an arbitrary caller-supplied output
   path. Refuses to overwrite an existing file at that path, checked
   twice (once while planning, once again, defensively, immediately
   before the copy in `factory.blender_adapter`).

No bypass exists for any of the five - `build_adaptation_execution_plan()`
and `evaluate_blender_execution_gate()` are the only sources of truth
each check reads.

## Blender execution policy (the one additional real invocation)

`factory.blender_adapter.run_organic_cleanup_workflow()` is the third
real Blender invocation this repo ever makes (after Phase 45's two), and
uses the identical safety posture:

- An absolute, already-resolved binary path (from
  `factory.blender_gate.resolve_blender_binary()`), argument list,
  `shell=False`, a hard timeout (300s - a real project artifact can be
  larger/more complex than the Phase 45 fixture sphere), `--background`,
  `--factory-startup`, `-Y`, `--offline-mode`, `--python-exit-code 1`.
- Blender only ever **reads** the caller-supplied input artifact path
  (never writes to it) and writes its output to a fresh
  `tempfile.TemporaryDirectory()`-contained path this function itself
  constructs - **Blender never writes directly into a project
  directory.** Only after the temp output is verified to exist, be
  non-empty, and be the only unexpected file in that temp directory is
  it copied (a plain Python file copy, not a second Blender step) to the
  caller's real, already safety-checked `final_output_path` - which is
  re-checked for non-existence immediately before the copy, defensively.
- Before/after temp-directory inventory detects any unexpected file
  Blender's own run might create, exactly like the Phase 45 fixture
  pipeline's own unexpected-file detection.
- The script passed to `--python` is always
  `factory.blender_gate.ORGANIC_CLEANUP_SCRIPT_PATH` - a fixed module
  constant, never a path any caller can override (mirrors
  `FIXTURE_SCRIPT_PATH`'s identical guarantee).

## Adaptation plan model

`factory.blender_adaptation.build_adaptation_execution_plan()` returns:

```json
{
  "input_artifact": "...",
  "project": "...",
  "source_engine": "meshy",
  "workflow_type": "organic_cleanup_workflow",
  "blender_gate_status": "ready_for_project_execution",
  "adaptation_operations": ["import_stl", "apply_scale_factor", "export_stl"],
  "current_dimensions_mm": {"x": 1478.97, "y": 1902.83, "z": 1411.77},
  "scale_assessment": { "...": "factory.hybrid_workflow.assess_scale() output, reused verbatim" },
  "target_dimensions": {"target_max_dimension_mm": 150.0, "note": "..."},
  "proposed_scale_factor": 0.079,
  "requires_human_confirmation": true,
  "output_artifact": ".../generated/blender/adapted/<stem>_adapted.stl",
  "validation_plan": {"validator": "factory.validators.mesh_validate.validate_mesh", "reused": true},
  "preview_plan": {"renderer": "factory.previews.render_preview.render_preview", "reused": true},
  "issues_found": [],
  "execution_allowed": true,
  "automatic_execution_allowed": false,
  "no_automatic_print": true
}
```

Plan first. Execution requires confirmation - `build_adaptation_execution_plan()`
never executes anything by itself, regardless of its own
`execution_allowed` value.

## Artifact lineage - reuses `project_timeline`/`artifact_history`, no second model

A completed execution writes `generated/blender_adaptation_receipt.json`,
which `factory.project_timeline._events_from_blender_adaptation_receipt()`
(one new, additive adapter, mirroring `_events_from_meshy_receipt()`
exactly) turns into exactly one `blender_adaptation` timeline event,
carrying both the input artifact's and the output artifact's
`{relative_path: sha256_fingerprint}` pairs. `factory.artifact_history`
picks these up automatically through its existing, unchanged
version-derivation logic (a version is the ordinal of any
artifact-relevant timeline event) - the only change needed there was one
additive path-classification rule
(`generated/blender/*.stl` -> `"stl"`), mirroring the identical rule
Phase 47B.7 already added for `generated/meshy/*.stl`.

## Receipt: `generated/blender_adaptation_receipt.json`

Written only on `organic_cleanup_status == "succeeded"`; never overwrites
an existing receipt (a project may run this workflow once per input
artifact through this receipt path - re-running against the same input
after a successful receipt already exists is refused, the same
collision-protection convention `factory.meshy_live_adapter` already
established for `generated/meshy/raw|processed/<task_id>.stl`).

```json
{
  "blender_adaptation_version": 1,
  "workflow": "organic_cleanup_workflow",
  "input_artifact": "generated/meshy/processed/<task_id>.stl",
  "input_hash": "sha256:...",
  "output_artifact": "generated/blender/adapted/<task_id>_adapted.stl",
  "output_hash": "sha256:...",
  "blender_version": "5.2.0",
  "blender_path": "/Applications/Blender.app/Contents/MacOS/Blender",
  "operations": ["import_stl", "apply_scale_factor", "export_stl"],
  "scale_factor_applied": 0.079,
  "target_max_dimension_mm": 150.0,
  "source_dimensions_mm": {"x": 1478.97, "y": 1902.83, "z": 1411.77},
  "output_dimensions_mm": {"x": 116.84, "y": 150.0, "z": 111.53},
  "single_shot_human_confirmation": true,
  "confirmed_by": null,
  "fixture_qualification_status": "qualified",
  "validation_status": "PASS",
  "preview_status": "PASS",
  "human_review_state": "required",
  "project_execution_approved": false,
  "automatic_print_allowed": false,
  "no_automatic_print": true
}
```

## Validation and preview - reused, not duplicated

After a successful execution, the adapted output is re-validated
(`factory.validators.mesh_validate.validate_mesh()`) and re-previewed
(`factory.previews.render_preview.render_preview()` -> `<stem>_adapted_preview.png`)
- the exact same Factory validator/renderer every other mesh in this
repo goes through. A provider/tool reporting "success" never overrides
Factory validation: a `FAIL` on the adapted output is recorded as an
error on the execution result even though the Blender subprocess itself
exited 0.

## CLI

```
factory blender-adapt plan <artifact_path> [--target-max-mm N] [--json]
factory blender-adapt execute <artifact_path> --target-max-mm N --confirm [--confirmed-by NAME] [--json]
```

Kept as its own Typer group, separate from `factory workflow` (which
`docs/hybrid-workflow.md` explicitly documents as planning-only, with
"deliberately no `workflow execute` command" - adding real execution
there would silently break that documented invariant). There is no
`factory blender run-script` or any other arbitrary-execution interface -
every command name is a fixed, narrow verb, and no option anywhere
accepts a script path.

## Preview Board

`blender_adaptation_summary` is wired into
`factory.preview_board.gather_board_data()` at the aggregation point only
(per the standing "Aggregation Layer Convention" in `docs/architecture.md`),
mirroring `hybrid_workflow_summary`'s own placement exactly. It only ever
reads an existing receipt (or reports `adaptation_available: false`) -
never invokes Blender, never a subprocess of any kind, during board
generation. Deliberately no new HTML card - the summary is compact enough
to fold into existing views, the same call Phase 48 already made for
`hybrid_workflow_summary`.

## Project Health - unchanged

`factory.project_health`'s `health_score` computation is untouched by
this phase, matching every prior Blender/Meshy-adjacent phase's own
invariant.

## Testing

`tests/test_blender_adaptation.py` (plan generation, scale-factor
computation, gate behavior, receipt shape - a fake shell script standing
in for the real Blender binary, the same convention
`tests/test_blender_adapter.py`/`tests/test_tool_qualification_openscad.py`
already established), `tests/test_blender_adaptation_cli.py` (`plan`/
`execute` commands), `tests/test_blender_adaptation_safety.py` (AST scans:
no subprocess/network import in `factory.blender_adaptation` itself; the
new Blender script imports only `bpy`/`sys`, writes to exactly one path,
reads no hardcoded external path; path containment; no overwrite of the
original artifact or an existing receipt/output; behavioral proof that
planning survives poisoned `socket`/`subprocess`), and
`tests/test_blender_adaptation_preview.py` (Preview Board summary wiring,
no Blender execution during board generation).

## Limitations

- Every confirmed execution re-runs the entire Phase 45 fixture pipeline
  first (two real Blender invocations per call) - deliberately
  conservative, not optimized for repeated calls. A future phase could
  reconsider this if it proves wasteful in practice, the same "not built
  speculatively" stance Phase 45 already took for its own qualification
  caching question.
- Only a single uniform scale factor is supported - no anisotropic
  scaling, no rotation/reorientation, no bounding-box-fit-to-printer
  logic beyond what `factory.validators.dimension_check` already does
  post-adaptation via the reused validator.
- No `--force`/`--overwrite-generated` flag exists - a collision with an
  existing output or receipt always blocks; a human must remove the
  conflicting file themselves before re-running.
- No CAD augmentation execution exists - `factory.hybrid_workflow`'s
  `hybrid_organic_mechanical` routing still recommends a CAD step this
  repo does not yet execute.
- A project may run `organic_cleanup_workflow` once per input artifact
  through the single `generated/blender_adaptation_receipt.json` path -
  re-running against a different input artifact within the same project
  will refuse to overwrite that receipt (a future phase could key the
  receipt per-input-artifact if this proves limiting).

## No-authority rule

Never launches Blender's GUI, installs an add-on, changes a Blender
preference, contacts a slicer, printer, or network, generates G-code, or
sets `human_approved`/`print_ready`. `project_execution_approved` stays
`false` everywhere this phase's code touches it - a single-shot,
per-invocation human confirmation is recorded under its own, differently
named field (`single_shot_human_confirmation`), never conflated with a
standing approval state. See `docs/blender-local-track.md` and
`docs/blender-adapter.md` for the still-standing rules this phase
narrows only for its own one workflow, never for broader Blender
automation.

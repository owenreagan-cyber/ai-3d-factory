# Architecture

`ai-3d-factory` is a local-first CLI (`factory`) built as a thin Python
package (`src/factory/`). There is no server, no daemon, no database, and
no network calls in Phase 0/1 — every command reads and writes local files
under the repo (mainly `projects/<slug>/`) and exits.

## Flow

```
idea/brief -> build plan -> part manifest -> CAD/assets (later phase)
  -> mesh validation -> preview rendering -> slicer review package
  -> human approval -> (future) print-ready status
```

Each stage corresponds to a CLI command and a JSON file, validated against
a schema in `schemas/`:

| Stage | Command | File | Schema |
|---|---|---|---|
| Brief | `factory init-project <name>` | `brief.json` | `project_brief.schema.json` |
| Plan | `factory plan <brief.json>` | `build_plan.json` | `build_plan.schema.json` |
| Manufacturing decision | `factory list-options <project_dir>` (read-only) then `factory choose-option <project_dir> <option_id>` | `build_plan.json`'s `selected_manufacturing_option` | `build_plan.schema.json` |
| Parts | `factory plan` seeds it; `factory choose-option` adds an `assembly_intent` summary; `factory generate-openscad` fills in CAD-time fields; manual edit for the rest | `part_manifest.json` | `part_manifest.schema.json` |
| Validation | `factory validate <mesh>` | `validation/*.json` | `validation_report.schema.json` |
| Preview | `factory render <mesh>` | `renders/*.png` | n/a |
| Preview package | `factory preview-index` (read-only) then `factory preview-project` | `preview_package/index.json`, `preview_package/preview_report.md` | n/a |
| Slicer review | (human, in Bambu Studio/OrcaSlicer) | `slicer_review/*.json` | `slicer_review.schema.json` |

`factory list-printers`/`show-printer`/`list-accessories`/`show-accessory`/
`list-materials`/`show-material`/`fleet-summary`/`check-manufacturing` sit
outside this per-project flow: they read `config/manufacturing/*.json`
directly (not a `projects/<slug>/` file) and never write anything - see
`docs/manufacturing-knowledge-base.md`.

## Package layout

- `factory/cli.py` — the Typer app; wires all commands, no business logic.
- `factory/project_store.py` — repo/project paths, slugs, JSON read/write.
- `factory/planner.py` — deterministic (non-AI) build-plan + manufacturing-advisor generator.
- `factory/router.py` — deterministic keyword-based tool routing recommendation.
- `factory/manufacturing/` — manufacturing knowledge base loader
  (`knowledge.py`), deterministic manufacturing-option decision engine
  (`decision_engine.py`), planning-time part_manifest seeding and
  assembly-intent computation (`manifest.py`), the human option-selection
  workflow (`selection.py`), read-only knowledge lookups (`inspect.py`), and
  knowledge-base internal-consistency validation (`check.py`). See
  `docs/manufacturing-knowledge-base.md`.
- `factory/validators/` — mesh geometry checks, dimension/build-volume fit,
  multi-part manifest sanity checks.
- `factory/previews/` — trimesh + matplotlib preview rendering.
- `factory/preview_package.py` — aggregates existing CAD/STL/render/manifest
  files into a project-level `preview_package/index.json` +
  `preview_report.md` (missing/stale detection, human inspection checklist).
  Never renders new images or exports geometry itself. See
  `docs/visual-preview-package.md`.
- `factory/slicer/` — read-only local slicer discovery.
- `factory/openscad/` — local, deterministic OpenSCAD source generation.
- `factory/cad/` — CAD backend registry and read-only routing
  (`backend.py`, `router.py`), and the CadQuery starter backend
  (`cadquery_backend.py`, `manifest.py`); CadQuery is an optional
  dependency this repo never installs. See `docs/cad-backends.md`.
- `factory/render_coverage.py` — read-only `stl/*.stl` vs. `renders/*.png`
  comparison for one project (missing/stale/orphan renders); the single
  shared implementation both `factory/project_inspection.py` and
  `factory/preview_package.py` call rather than reimplementing. See
  `docs/render-coverage.md`.
- `factory/project_inspection.py` — the shared, read-only, single-project
  inspection layer both `factory/preview_board.py` and
  `factory/review_gate.py` build on (extracted from `preview_board.py` in
  Phase 13 specifically to remove circular-import pressure). Its
  `summarize_project()` reads one project's `brief.json`/`build_plan.json`/
  `part_manifest.json`/`cad/`/`stl/`/`renders/`/`validation/` (reusing
  `factory/preview_package.py` and `factory/render_coverage.py`, never
  duplicating their file scans) and returns `visual_readiness_state`
  (`classify_visual_readiness()`), a deterministic `suggested_actions`
  list (advisory-only, `"safety": "manual_only"`, never executed), and a
  deterministic `health_signals` rollup (`summary` +
  `info`/`warning`/`blocked`/`ready` items, including local
  `validation/`-report-coverage checking - `factory validate` is never run
  automatically). Never writes a file. See `docs/architecture.md`'s
  "Shared inspection layer" note below.
- `factory/preview_board.py` — aggregates every project under a
  `projects_root` into one static, local `preview_board/index.json` +
  `index.html` (no server, no external assets), using
  `factory/project_inspection.py`'s `summarize_project()` for each
  project's data. This module owns only project discovery, board
  aggregation, and JSON/HTML rendering (`suggested_actions` render as
  plain `<pre><code>` blocks in a "Suggested next steps" section,
  `health_signals` in a "Health signals" section - no JavaScript, no copy
  button). See `docs/preview-board.md`.
- `factory/review_gate.py` — a read-only pass/warn/fail pre-flight check
  ("is this project ready for a **human** to review it in a slicer?")
  built directly on `factory/project_inspection.py`'s `summarize_project()`
  - it does **not** import `factory/preview_board.py`. It reads the
  already-computed `health_signals` items by `kind` and applies its own,
  purpose-specific stricter policy on top (e.g. a missing render is a hard
  blocker here, not just a warning). `pass` never implies
  `human_approved`/`print_ready` - the status ceiling stays
  `slicer_review_ready`. See `docs/review-gate.md`.
- `factory/examples_library.py` — a small, read-only, statically
  hand-maintained registry describing each example under `examples/`
  (`list_examples()`/`get_example()`); never scans `examples/` dynamically
  and never generates, renders, exports, validates, or contacts anything.
  See `docs/examples-library.md`.
- `factory/future_cloud_tools.py` — a small, read-only module that reads
  `config/future_cloud_tools.json` (`list_future_cloud_tools()`/
  `get_future_cloud_tool()`) and reports each future cloud/paid tool's
  (currently just Meshy) gate status. Never reads `.env`, never validates
  credentials, never makes a network call, and never enables anything -
  it only reports what's already recorded as disabled/future-gated. See
  `docs/meshy-approval-gate.md`.
- `factory/future_local_tools.py` — the same pattern as
  `future_cloud_tools.py`, for future *local* (non-cloud) tool
  integrations (currently just Blender): reads `config/
  future_local_tools.json` (`list_future_local_tools()`/
  `get_future_local_tool()`) and reports each tool's gate status. Never
  launches a tool, never searches the filesystem for an installed
  application, never calls `subprocess`, and never enables anything. See
  `docs/blender-local-track.md`.
- `factory/design_intent_check.py` — a small, read-only, advisory check
  (`check_design_intent_manufacturability()`): reads a `brief.json`/
  `concept_brief.json`'s optional `design_intent.manufacturability_
  constraints.max_size_mm` (Phase 24's proposed shape - see
  `docs/design-intent-brief.md`) and compares it, in every axis
  orientation (same technique `factory.validators.dimension_check`
  already uses for a real mesh), against every printer in `config/
  manufacturing/printers.json` via `factory.manufacturing.knowledge`.
  Never inspects real mesh geometry, never contacts a printer/slicer/
  network, never writes a file, and never sets `human_approved`/
  `print_ready`.

### Shared inspection layer (Phase 13)

`factory/project_inspection.py` is the single source of truth both
single-project (`review_gate`) and multi-project (`preview_board`)
surfaces read from, so the two can never silently disagree about the same
underlying facts. The dependency graph is one-directional and acyclic:

```
factory/render_coverage.py   factory/preview_package.py
             \                        /
              \                      /
             factory/project_inspection.py
              /                            \
             /                              \
factory/preview_board.py          factory/review_gate.py
```

`project_inspection.py` imports only `preview_package`/`render_coverage`/
`project_store` - never `preview_board` or `review_gate`. `preview_board.py`
still re-exports `project_inspection`'s public names
(`summarize_project`, `classify_visual_readiness`, `build_suggested_actions`,
`build_health_signals`, `VISUAL_READINESS_STATES`, `HEALTH_SEVERITIES`,
`ACTION_SAFETY`) for backward compatibility with existing
`from factory.preview_board import ...` call sites - they are the literal
same function/constant objects, not copies.

**Phase 36 addendum:** `factory/slicer_readiness.py` sits as a *third*
top-level consumer above this same layer, alongside `preview_board.py`
and `review_gate.py` - it calls `review_gate.evaluate_review_gate()`
directly (which itself already depends on `project_inspection.py`), so it
cannot be imported back into `project_inspection.py` without recreating
the exact cycle this diagram exists to avoid:

```
                     factory/project_inspection.py
                      /                            \
                     /                              \
    factory/preview_board.py          factory/review_gate.py
                     \                              /
                      \                            /
                     factory/slicer_readiness.py
```

This is why `slicer_readiness_summary` (Phase 36) is merged into each
board project's dict by `preview_board.gather_board_data()` itself,
rather than living inside `project_inspection.summarize_project()` like
every earlier phase's additive field - see `docs/slicer-readiness.md`
"Architectural note" and `docs/review-gate.md`'s Phase 36 addendum for
the full account.

**Phase 37 addendum:** `factory/manual_review_workspace.py` sits one
layer further up still - it calls `slicer_readiness.assess_slicer_readiness()`
directly, so the same cycle-avoidance applies transitively:

```
                     factory/project_inspection.py
                      /                            \
                     /                              \
    factory/preview_board.py          factory/review_gate.py
                     \                              /
                      \                            /
                     factory/slicer_readiness.py
                                  |
                     factory/manual_review_workspace.py
```

`manual_review_summary` (Phase 37) is merged into each board project's
dict the same way, at the same `preview_board.gather_board_data()`
aggregation point - see `docs/manual-review-workspace.md` "Architectural
note".

**Phase 38 addendum:** `factory/slicer_intelligence.py` sits one layer
further up still - it calls
`manual_review_workspace.assess_manual_review_workspace()` directly, so
the same cycle-avoidance applies transitively once more:

```
                     factory/project_inspection.py
                      /                            \
                     /                              \
    factory/preview_board.py          factory/review_gate.py
                     \                              /
                      \                            /
                     factory/slicer_readiness.py
                                  |
                     factory/manual_review_workspace.py
                                  |
                     factory/slicer_intelligence.py
```

`slicer_intelligence_summary` (Phase 38) is merged into each board
project's dict the same way, at the same
`preview_board.gather_board_data()` aggregation point - see
`docs/slicer-intelligence.md` "Architectural note".

**Phase 39 addendum:** `factory/slicer_history.py` sits at the very top of
this same chain - it calls
`slicer_intelligence.evaluate_slicer_intelligence()` directly, so the same
cycle-avoidance applies transitively once more:

```
                     factory/project_inspection.py
                      /                            \
                     /                              \
    factory/preview_board.py          factory/review_gate.py
                     \                              /
                      \                            /
                     factory/slicer_readiness.py
                                  |
                     factory/manual_review_workspace.py
                                  |
                     factory/slicer_intelligence.py
                                  |
                     factory/slicer_history.py
```

`slicer_history_summary` (Phase 39) is merged into each board project's
dict the same way, at the same `preview_board.gather_board_data()`
aggregation point - see `docs/slicer-analysis-history.md`. Note that
`factory/slicer_profiles.py` (Phase 39, Part 1/2) is *not* in this chain
at all - it only depends on `factory.slicer.local_slicer_probe`, so it
sits alongside `factory/manufacturing/knowledge.py` as a simple, low-level
module `factory/slicer_intelligence.py` consumes directly, with no
circular-import risk.

**Phase 40 addendum:** `factory/project_timeline.py` sits at the very top
of this same chain - it reads receipts written by
`factory.slicer_readiness`/`factory.manual_review_workspace`/
`factory.slicer_history` (via each module's own lightweight, read-only
receipt-reader function, e.g. `read_slicer_readiness_receipt()`), so the
same cycle-avoidance applies transitively once more:

```
                     factory/project_inspection.py
                      /                            \
                     /                              \
    factory/preview_board.py          factory/review_gate.py
                     \                              /
                      \                            /
                     factory/slicer_readiness.py
                                  |
                     factory/manual_review_workspace.py
                                  |
                     factory/slicer_intelligence.py
                                  |
                     factory/slicer_history.py
                                  |
                     factory/project_timeline.py
```

`timeline_summary` (Phase 40) is merged into each board project's dict
the same way, at the same `preview_board.gather_board_data()` aggregation
point - see `docs/project-timeline.md`.

**Phase 41 addendum:** `factory/artifact_history.py` sits at the very top
of this same chain - it reads `factory.project_timeline.get_project_timeline()`
(never a receipt directly), so the same cycle-avoidance applies
transitively once more:

```
                     factory/project_inspection.py
                      /                            \
                     /                              \
    factory/preview_board.py          factory/review_gate.py
                     \                              /
                      \                            /
                     factory/slicer_readiness.py
                                  |
                     factory/manual_review_workspace.py
                                  |
                     factory/slicer_intelligence.py
                                  |
                     factory/slicer_history.py
                                  |
                     factory/project_timeline.py
                                  |
                     factory/artifact_history.py
```

`artifact_history_summary` (Phase 41) is merged into each board
project's dict the same way, at the same
`preview_board.gather_board_data()` aggregation point - see
`docs/artifact-history.md`.

**Phase 42 addendum:** `factory/project_health.py` sits at the very top
of this same chain - it calls `factory.slicer_readiness`/
`factory.manual_review_workspace`/`factory.slicer_intelligence` directly
(the same "top-level consumer" relationship `preview_board.py` already
has), so the same cycle-avoidance applies transitively once more:

```
                     factory/project_inspection.py
                      /                            \
                     /                              \
    factory/preview_board.py          factory/review_gate.py
                     \                              /
                      \                            /
                     factory/slicer_readiness.py
                                  |
                     factory/manual_review_workspace.py
                                  |
                     factory/slicer_intelligence.py
                                  |
                     factory/slicer_history.py
                                  |
                     factory/project_timeline.py
                                  |
                     factory/artifact_history.py
                                  |
                     factory/project_health.py
```

`project_health_summary` (Phase 42) is merged into each board project's
dict the same way, at the same `preview_board.gather_board_data()`
aggregation point - see `docs/project-health.md`.

**Phase 43 addendum:** `factory/engine_registry.py` is a **peer**
aggregation module, not another link in the chain above - it never
consumes `project_inspection`/`review_gate`/any project data at all (a
tool registry is project-independent), so it has no circular-import risk
to avoid in the first place:

```
factory/engine_registry.py  --->  factory/preview_board.py   (board-wide "Tool Environment" section)
                             --->  factory/project_health.py  (per-project "tool_environment_summary" field)
                             --->  factory/cli.py             (`factory engines`/`factory engines probe`)
```

`factory.project_health.evaluate_project_health()` calling
`factory.engine_registry.summarize_tool_environment()` is safe for the
same reason: `engine_registry` sits below both, imported by, never
importing, either aggregation layer. See `docs/engine-registry.md`.

**Phase 44 addendum:** `factory/tool_qualification.py` sits **above**
`engine_registry`, forming one more link:

```
factory/engine_registry.py  --->  factory/tool_qualification.py  --->  factory/cli.py (`factory engines qualify`)
```

It is not consumed by `factory/preview_board.py` or
`factory/project_health.py` at all in this phase (both would need to
trigger real qualification work - a bounded subprocess for OpenSCAD - as
a side effect of board/health generation, which Phase 44 explicitly
forbids); `factory.tool_qualification` is a CLI-only consumer of
`engine_registry` for now. See `docs/tool-qualification.md`.

**Phase 45 addendum:** `factory/blender_gate.py` and
`factory/blender_adapter.py` form two more links, both CLI-only, neither
consumed by `preview_board`/`project_health` (for the same "never trigger
real execution as a side effect of viewing a board/health summary"
reasoning Phase 44 already established):

```
factory/engine_registry.py  --->  factory/blender_gate.py  --->  factory/blender_adapter.py  --->  factory/cli.py (`factory blender inspect`/`qualify`)
```

`blender_gate` is read-only (permission/readiness/dry-run planning, zero
subprocess calls); `blender_adapter` is the only module in this repo that
ever passes Blender to `subprocess`, and only against one Factory-owned
temporary fixture, never a project. `factory.tool_qualification`'s own
Blender result (Phase 44) is untouched - Phase 45's deeper evidence lives
in this separate pair of modules, joined only at the CLI layer
(`factory.blender_adapter.build_blender_report()`), never written back
into Phase 44's result. See `docs/blender-adapter.md`.

**Phase 46 addendum:** `factory/meshy_approval.py` is one more link,
CLI-and-preview-board-consumed (unlike Phase 44/45's Blender/OpenSCAD
qualification modules, this one performs no subprocess/network work at
all - joining it into `preview_board`'s always-regenerated output carries
no side-effect risk):

```
factory/engine_registry.py  --->  factory/meshy_approval.py  --->  factory/cli.py (`factory meshy status`/`policy`)
                             \--->  factory/preview_board.py (`meshy_policy_summary`, a field
                                     deliberately separate from `tool_environment_summary`)
```

It also reads `factory/future_cloud_tools.py` (Phase 16's existing kill
switch) and `factory/reference_board.py`'s `LICENSES` vocabulary directly
- neither of those modules imports it back. Deliberately **not** consumed
by `factory/project_health.py` at all - `health_score` stays entirely
untouched by Meshy policy state, matching the same "a mechanical project
must not become unhealthy because a cloud tool is ungated" reasoning
Phase 43 already established for tool detection generally. See
`docs/meshy-policy.md`.

**Phase 47A addendum:** `factory/meshy_models.py` (pure data) ->
`factory/meshy_mock_transport.py` (the `MeshyTransport` interface + the
only implementation, `MockMeshyTransport`) -> `factory/meshy_adapter.py`
(orchestration) sits *above* `factory.meshy_approval` in the same
direction every prior phase's aggregation layer has - `meshy_adapter`
imports `meshy_approval` directly, never the reverse:

```
factory/meshy_models.py  --->  factory/meshy_mock_transport.py  --->  factory/meshy_adapter.py
                                                                            |
                                                          factory/meshy_approval.py (Phase 46, read-only)
                                                          factory/validators/mesh_validate.py (reused)
                                                          factory/previews/render_preview.py (reused)
                                                                            |
                                                                            v
                                              factory/cli.py (`factory meshy plan`/`mock-run`)
```

No `HttpMeshyTransport` existed until Phase 47B - `MockMeshyTransport`
was never a placeholder for one, it was the only transport the mocked
architecture needed to prove itself against. See `docs/meshy-adapter.md`.

**Phase 47B addendum:** `factory/meshy_http_transport.py` (the only
module in this repo allowed to open a real network connection) sits
alongside `meshy_mock_transport.py`, both satisfying the same
`MeshyTransport` interface; `factory/meshy_ledger.py`/
`factory/meshy_live_approval.py` (persistent, gitignored local state) and
`factory/meshy_live_adapter.py` (the gated orchestrator enforcing the
locked live-execution order) sit above them, in the same
above-`meshy_approval` direction:

```
factory/meshy_http_transport.py  --->  factory/meshy_live_adapter.py
factory/meshy_ledger.py           --->        |
factory/meshy_live_approval.py    --->        |
                                               |
                             factory/meshy_approval.py (Phase 46, read-only)
                             factory/validators/mesh_validate.py (reused)
                             factory/previews/render_preview.py (reused)
                                               |
                                               v
                       factory/cli.py (`factory meshy live-plan`/`live-run`)
```

`meshy_live_adapter.py` never imports `urllib`/network code directly - it
only ever constructs `HttpMeshyTransport`/`LiveMeshyCredentialProvider`
after every gate in the locked order has passed, and accepts them as
injectable factories for testing. See `docs/meshy-live-transport.md`.

**Phase 48 addendum:** `factory/hybrid_workflow.py` sits *downstream* of
the artifact-producing systems above, never upstream - it reads a Meshy
receipt, a CAD generation/export receipt, and (via
`factory.design_intent_check`) an optional `design_intent` block, and
reuses `factory.engine_registry`/`factory.blender_gate` for tool routing
rather than re-scoring suitability itself:

```
factory/meshy_live_adapter.py (receipt)  --->
factory/generation_gate.py (receipt)     --->  factory/hybrid_workflow.py
factory/export_pipeline.py (receipt)     --->        |
factory/design_intent_check.py (reused)  --->        |
factory/engine_registry.py (reused)      --->        |
factory/blender_gate.py (reused)         --->        |
factory/validators/mesh_validate.py (reused)         |
                                                       v
                          factory/cli.py (`factory workflow plan`/`assess`)
                          factory/preview_board.py (`hybrid_workflow_summary`, aggregation point only)
```

This module never transforms an artifact and writes nothing - it is
planning only. It never imports `factory.blender_adapter` (the module
that actually invokes Blender) or `factory.cad.backend` (CAD execution);
a recommended step's readiness is always the real gate's own status,
never re-asserted independently. See `docs/hybrid-workflow.md`.

**Phase 49 addendum:** `factory/blender_adaptation.py` is the first
module in this repo that executes real Blender automation against a real
project artifact - narrowly, for exactly one workflow
(`organic_cleanup_workflow`). It sits *between* `factory.hybrid_workflow`
(which only recommends a Blender adaptation step) and
`factory.blender_adapter` (the sole subprocess-invoking module), never
duplicating either:

```
factory/hybrid_workflow.py (assess_scale, reused)   --->
factory/blender_gate.py (plan, reused)              --->  factory/blender_adaptation.py
factory/blender_adapter.py (execution, reused)      --->        |
factory/design_intent_check.py (reused)             --->        |
factory/validators/mesh_validate.py (reused)                    |
factory/previews/render_preview.py (reused)                     |
                                                                  v
                          factory/cli.py (`factory blender-adapt plan`/`execute`)
                          factory/project_timeline.py (`blender_adaptation` event, additive)
                          factory/artifact_history.py (`generated/blender/` classified as `stl`, additive)
                          factory/preview_board.py (`blender_adaptation_summary`, aggregation point only)
```

Every real execution re-checks Blender detection and runs a fresh
fixture-qualification proof (`factory.blender_adapter.qualify_blender_adapter(confirm_fixture=True)`)
on that exact call - nothing about a prior qualification or a prior
execution is ever cached or trusted. The original input artifact is
never modified; a new child artifact is always written to
`generated/blender/adapted/`, never overwriting an existing file. See
`docs/blender-adaptation.md`.

**Phase 50 addendum:** `factory/cad_augmentation.py` extends the same
chain one more link - the controlled bridge from an already-adapted
organic artifact to a manufacturing-ready hybrid product. It reuses
`factory.engine_registry` for CAD routing (never a second selector) and
`factory.export_pipeline` for the one bounded OpenSCAD execution this
phase adds (never a second subprocess mechanism; CadQuery is never
executed - see `docs/cad-backends.md`/`docs/cad-augmentation.md`):

```
factory/engine_registry.py (suitability, reused)      --->
factory/export_pipeline.py (OpenSCAD execution, reused) --->  factory/cad_augmentation.py
factory/blender_adaptation.py (lineage read, reused)  --->        |
factory/validators/mesh_validate.py (reused)                      |
factory/previews/render_preview.py (reused)                       |
                                                                    v
                          factory/cli.py (`factory cad-augment plan`/`execute`)
                          factory/project_timeline.py (`cad_augmentation` event, additive)
                          factory/artifact_history.py (`generated/cad_augmentation/` classified as `stl`, additive)
                          factory/preview_board.py (`cad_augmentation_summary`, aggregation point only)
```

The generated CAD feature is always a new, independent STL - never a
boolean-merge with the organic mesh (`factory.validators.multipart_check`'s
own standing "separate STLs over a fused mesh" policy). Verified live,
end to end, against `projects/meshy-live-smoke-test`'s real piggy-bank
artifact, producing a genuine three-stage lineage
(`meshy -> blender_adaptation -> cad_augmentation`). See
`docs/cad-augmentation.md`.

**Phase 51 addendum:** `factory/design_review.py` is the final
intelligence layer over the whole chain - never executing, never
modifying geometry, only reading:

```
factory/blender_adaptation.py (receipt read, reused)   --->
factory/cad_augmentation.py (receipt read, reused)     --->  factory/design_review.py
factory/hybrid_workflow.py (assess_scale/intent, reused) --->     |
factory/design_intent_check.py (reused)                --->      |
factory/manual_review_workspace.py (reused)            --->      |
factory/slicer_readiness.py (reused)                   --->      |
factory/slicer_intelligence.py (reused)                --->      |
factory/validators/mesh_validate.py (reused)                     |
                                                                   v
                          factory/cli.py (`factory design-review <project>`)
                          factory/preview_board.py (`design_review_summary` + a compact card, aggregation point only)
```

**Phase 52 addendum:** `factory/manufacturing_readiness.py` is the final
aggregation layer over *both* readiness ladders - the hybrid one
(`design_review`) and the traditional one (`project_health`), which by
explicit design never read each other. Never executing, never modifying
geometry, only reading:

```
factory/design_review.py (evaluate_design_review, reused)       --->
factory/project_health.py (evaluate_project_health, reused)      --->  factory/manufacturing_readiness.py
factory/slicer_intelligence.py (build_volume_analysis only, reused) --->      |
factory/artifact_history.py (summarize_artifact_history, reused) --->        |
factory/project_timeline.py (summarize_project_timeline, reused) --->        |
                                                                              v
                          factory/cli.py (`factory manufacturing-readiness <project>`)
                          factory/preview_board.py (`manufacturing_readiness_summary` + a compact card, aggregation point only)
```

This is the first module to sit *above* both `design_review.py` and
`project_health.py` in the dependency graph at once - it calls both
directly (the same "top-level consumer" relationship `preview_board.py`
already has to every summary module) and neither is modified by this
phase. See `docs/manufacturing-readiness.md`.

Unlike Phases 49/50, this phase adds **no new timeline event category
and no new artifact-history classification rule** - a design review is
never itself a persisted "artifact-relevant event"; it behaves exactly
like `factory health`, computed fresh on demand. `factory.project_health`
stays entirely untouched - this is a parallel lens, not an extension of
its scoring. See `docs/design-review.md`.

## Aggregation Layer Convention

This is the standing, permanent rule the diagram above has demonstrated
seven times in a row (Phases 36 through 42) - **documented once here so
future phases apply it by design, rather than re-discovering it
empirically each time.**

**Core modules may be consumed by summary/dashboard layers. Feature
modules must not import upward into aggregation layers.**

Preferred direction:

```
Core Systems
      |
      v
Summary Functions
      |
      v
Preview/Dashboard Aggregation
```

Data flows strictly one way: a core system (`project_inspection.py`,
`review_gate.py`, or any module built on them, such as
`slicer_readiness.py`) is read by a summary function
(`summarize_slicer_readiness()`, `summarize_project_timeline()`, etc.),
which is in turn read by an aggregation layer
(`preview_board.gather_board_data()`). Nothing downstream of
`project_inspection.py` ever gets imported back into it.

**Avoid, always:**

```
project_inspection
      |
      v
feature module
      |
      v
project_inspection
```

The moment any feature/summary module needs to add a per-project field to
the Preview Board, and that module (directly or transitively) depends on
`review_gate.py` or `project_inspection.py` itself, it **cannot** also be
imported *into* `project_inspection.summarize_project()` - doing so
creates a genuine circular import (confirmed empirically the first time
this came up, in Phase 36, and every time since). The fix is always the
same: add the new summary field inside
`factory.preview_board.gather_board_data()` instead, at the aggregation
point, never inside `project_inspection.py`. This is why
`slicer_readiness_summary`, `manual_review_summary`,
`slicer_intelligence_summary`, `slicer_history_summary`,
`timeline_summary`, `artifact_history_summary`,
`project_health_summary`, (Phase 48) `hybrid_workflow_summary`, (Phase
49) `blender_adaptation_summary`, (Phase 50)
`cad_augmentation_summary`, (Phase 51) `design_review_summary`, and
(Phase 52) `manufacturing_readiness_summary` all live on the board's
per-project dict without ever touching
`project_inspection.summarize_project()`'s own return shape.

**Applies to every future phase**, not just the seven above - any new
aggregation/dashboard/summary module must sit *above* `project_inspection.py`
in this same graph, never be imported by it, and wire its own per-project
field into `preview_board.gather_board_data()` the same way. (A module
that consumes no project data at all - like Phase 43's `engine_registry`
- has no per-project field to wire in and no cycle to avoid; it is simply
a peer module the aggregation layers call directly.)

## Why local-first

Every check in this repo (geometry validation, dimension fit, preview
rendering, slicer discovery) is designed to run entirely offline, using
only the local filesystem and local Python libraries (`trimesh`,
`matplotlib`, `jsonschema`). This keeps the tool safe, boring, and
reliable: nothing here can silently call out to a paid API, upload a
design, or reach a printer. See `AGENT.md` and `docs/safety-gates.md`.

## What Phase 0/1 does not do

- Generate or import 3D geometry (CAD/asset generation is Phase 2+).
- Fuse or align multi-part meshes automatically.
- Package a `.3mf` (experimental, later phase).
- Talk to a slicer, printer, or any cloud service.

See `docs/roadmap.md` for what later phases add.

## This CLI is the engine, not the final product

Everything above is a terminal-first local engine by design - fast to
build, easy to test, trivially safe to reason about. It is not the intended
long-term day-to-day experience: see `docs/product-vision.md` for the
future visual/launcher direction (Mac app launcher, local dashboard, mesh
and manufacturing-option previews, ...). That document is vision-only -
nothing in it is implemented, and every safety boundary here carries
forward unchanged into any future UI built on top of this engine.

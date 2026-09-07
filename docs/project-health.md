# Project Health Dashboard & Unified Factory Status View (Phase 42)

`factory.project_health` is the first unified, single-project health
view - it aggregates existing Factory intelligence (Phases 13, 26-41)
into one deterministic dashboard:

```
Feature Modules -> Summary Models -> Project Health Dashboard -> Human Understanding
```

## This phase summarizes - it does not decide

**This phase does not create new manufacturing logic, does not create
new readiness rules, and does not replace any existing system.** Every
number, status, and message the dashboard shows was already computed by
an existing module; this module's own job is arithmetic (a documented
weighted average) and read-only aggregation, never a second source of
truth.

**Core principle:** the dashboard must not

- recalculate readiness,
- duplicate risk logic,
- duplicate validation logic,
- duplicate artifact checks,
- create new approval rules, or
- override an existing blocker.

If this module's rendering of a status, score, or blocker ever disagrees
with the module that produced it, that module is correct - this is a bug
here, never grounds to "correct" the underlying record.

## Reuses rather than duplicates

- `factory.project_inspection.summarize_project()` - brief/manifest
  status, CAD/mesh files, `health_signals`, `design_orchestrator_summary`
  (Phase 33), `generation_gate_summary`/`generation_execution_summary`
  (Phase 34), `export_pipeline_summary` (Phase 35).
- `factory.slicer_readiness.assess_slicer_readiness()` (Phase 36) - the
  full technical readiness assessment: blockers/warnings/advisories,
  `readiness_status`, `readiness_score`, approval/package state.
- `factory.manual_review_workspace.assess_manual_review_workspace()`
  (Phase 37) - printer/material resolution, `workspace_status`,
  `review_confidence`, `remaining_risk`.
- `factory.slicer_intelligence.evaluate_slicer_intelligence()` (Phase
  38/39) - `risk_level`, geometry/manufacturing risks, build-volume fit.
- `factory.project_timeline.get_project_timeline()`/
  `summarize_project_timeline()` (Phase 40) - recent activity, event
  counts.
- `factory.artifact_history.get_artifact_history()`/
  `summarize_artifact_history()` (Phase 41) - latest version, changes
  since the previous version.
- `factory.project_store.PROJECT_STATUSES` - the repo's own canonical
  pipeline-stage ordering, reused directly for `completion_percentage`
  rather than a second stage-counting scheme.

## Architectural note

Same reasoning as every Phase 36-41 summary field - see the "Aggregation
Layer Convention" in `docs/architecture.md`. `factory.slicer_readiness`/
`factory.manual_review_workspace`/`factory.slicer_intelligence` each
transitively import `factory.review_gate`, which already imports
`factory.project_inspection.summarize_project()`. This module calls all
three directly (the same "top-level consumer" relationship
`preview_board.py` already has), so it sits **above**
`project_inspection.py` in the dependency graph, never beneath it.
Adding `project_health_summary` *inside* `project_inspection.py` would
recreate the exact circular import Phase 36 discovered and every phase
since has avoided. `factory.preview_board.gather_board_data()` merges
`project_health_summary` in at the same aggregation point as every other
Phase 36-41 field instead.

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

## Scoring model

`compute_health_score()` returns a deterministic weighted percentage
(0-100) plus a per-category breakdown. Every category is read straight
off an already-computed summary - this function performs no independent
assessment of its own. Weights sum to 1.0:

| Category | Weight | Formula |
|---|---|---|
| Project Definition | 15% | Average of the Design Orchestrator's own `intake`/`brief` category percentages (Phase 33) |
| Design Intent | 10% | Average of the Design Orchestrator's own `design_intent`/`reference_board` category percentages |
| Manufacturing Planning | 15% | 100 if a manufacturing option has been selected (`build_plan.json`), else the Design Orchestrator's `manufacturing` category percentage |
| CAD Generation | 15% | 100 if a confirmed generation receipt exists; 75 if CAD source exists without one; 40 if the generation gate would allow/needs-confirm generation; else 0 |
| Artifact Completeness | 15% | `100 * current_stl_count / expected_stl_count` (Phase 35's own counts) |
| Validation | 15% | `export_pipeline_summary`'s aggregated `validation_status` mapped through the same 1.0/0.7/0.0 point convention `factory.slicer_readiness`'s own validation scoring already uses |
| Review Readiness | 15% | `factory.slicer_readiness`'s own already-computed `readiness_score`, reused directly |

**This score is purely informational - it never overrides a hard
blocker.** A project can score 85% and still report
`overall_status: "Blocked"`. `health_level` (`excellent`/`good`/`fair`/
`poor`) is a coarse label derived from the score alone (thresholds: 85,
65, 40) - also purely informational, never read by the blocked/lifecycle
logic.

`completion_percentage` is a *different* number from `health_score`: it
reuses `factory.project_store.PROJECT_STATUSES`'s own canonical pipeline
ordering directly (`status_index(brief.json["status"]) / 12 * 100`) -
progress *through* the pipeline, not the *quality* of what's been done so
far. A well-defined idea can have a high `health_score` while
`completion_percentage` is still low, and vice versa.

## Blocked vs. not-yet-reached

`readiness_status == "blocked"` (Phase 36) also fires for entirely
normal in-progress states - e.g. an STL exists but hasn't been rendered
yet, which `factory.review_gate` correctly treats as blocking *for
slicer review specifically*, not a genuine project-level problem.
Treating that as a dashboard-level "Blocked" would misreport nearly every
early- or mid-stage project as stuck.

A genuine obstruction (`_is_hard_blocked()`) is only:

1. `design_orchestrator_summary["readiness_state"] == "Blocked"` (Phase
   25/33 - the part doesn't fit any configured printer), or
2. `health_signals["summary"] == "blocked"` (Phase 13 - an unreadable
   brief/manifest, a stale render, or missing/stale preview artifacts -
   genuine corruption/staleness, not "hasn't happened yet"), or
3. `readiness_assessment["validation_failure_count"] > 0` (an actual
   failed STL validation).

Only when one of these is true does `overall_status` become `"Blocked"`
and `lifecycle_stage` become `"blocked"`. The same distinction applies to
the aggregated `blockers` list: `readiness_assessment["blockers"]` (a
flat string list with no structured "kind" to filter on) is only
surfaced there when `hard_blocked` is `True` - otherwise those
"haven't gotten there yet" facts are already visible in `warnings` (via
`project_inspection`'s own missing-artifact messages). Similarly,
`export_pipeline_summary`'s own blocking reasons are only surfaced when
its `decision` is `"unsupported_source"`, `"ambiguous_source"`, or
`"export_tool_missing"` - not `"blocked"` (no CAD source *yet*, true for
every pre-CAD project), `"manual_export_required"` (this repo's normal,
expected CadQuery policy), `"output_collision"`, or `"needs_confirmation"`
(both safety gates on an already-successful export, not obstructions).

## Lifecycle stages

```python
LIFECYCLE_STAGES = (
    "idea", "intake", "briefing", "design", "planning", "cad_generation",
    "export", "validation", "review_preparation", "slicer_review", "complete", "blocked",
)
```

Determined by `_determine_lifecycle_stage()`, read-only, in this order:

1. A genuine obstruction (see above) always resolves to `"blocked"`,
   regardless of anything else.
2. No `brief.json` yet -> `"intake"` if Project Intake (Phase 30) found
   a real category signal, else `"idea"`.
3. `brief.json["status"] == "brief_created"` with a declared
   `design_intent` block -> `"design"`; otherwise mapped directly from
   `brief.json`'s own `status` field (`brief_created` -> `"briefing"`,
   `plan_drafted`/`plan_approved`/`manufacturing_option_selected` ->
   `"planning"`).
4. No CAD source and no STL yet -> whichever early stage step 2/3
   resolved.
5. CAD source exists, no STL yet -> `"cad_generation"`.
6. STL exists -> the receipt-backed slicer-readiness stack (Phase 36) is
   a more precise, more current signal than `brief.json`'s own status
   (which is not always advanced for every micro-step), refined by
   `readiness_status`: `not_ready`/`stale_artifacts` -> `"export"`;
   `needs_validation`/`needs_preview` -> `"validation"`;
   `needs_manifest_completion`/`needs_information`/`needs_human_approval`
   -> `"review_preparation"`; `ready_for_review_package`/
   `review_package_created` -> `"slicer_review"`. When `readiness_status`
   resolves to the generic `"blocked"` value for the benign
   missing-render reason described above, `export_pipeline_summary`'s own
   `validation_status`/`preview_status` disambiguates between
   `"validation"` (not yet validated/rendered) and a plain `"export"`
   fallback.
7. `brief.json["status"] in ("human_approved", "print_ready")` always
   overrides to `"complete"` - the most explicit, human-set completion
   signal this repo has.

Never mutates `brief.json` or any other file - purely a read of already
existing evidence.

## Blockers, warnings, risks, strengths

Every message is read **verbatim** from the module that produced it -
never rewritten, never re-derived - each tagged with its `source` module
so it stays traceable:

- **`blockers`** - `export_pipeline_summary`'s genuine blocking reasons
  (see above) plus `readiness_assessment["blockers"]` (Phase 36, already
  folds in `factory.review_gate`'s own blocking items when relevant),
  surfaced only when `hard_blocked` is `True`.
- **`warnings`** - `project_inspection`'s own brief/manifest/render-
  coverage warnings plus `evaluate_slicer_intelligence()`'s own
  `warnings` list (Phase 38/39), which already includes every warning
  `factory.manual_review_workspace`/`factory.slicer_readiness` produced
  beneath it (each layer appends to the one below rather than replacing
  it) - reused here as a single, already-deduplicated list.
- **`risks`** - `evaluate_slicer_intelligence()`'s own `geometry_risks`/
  `manufacturing_risks` (Phase 38), each already `{"category", "message"}`
  - never a second risk-detection pass.
- **`strengths`** - positive signals, each a direct restatement of an
  existing boolean/enum this repo already computed (human approval
  recorded, a review package exists, validation passed cleanly, a
  readiness score >= 90%, design intent declared, reference materials
  attached, artifacts stable since the last version, full timeline
  history available) - never a new judgment call.

## Next action

One deterministic, human-readable recommendation - never automated.
`_determine_next_action()` prefers each layer's own already-computed
"what to do next" text (`export_pipeline_summary["next_step"]`,
`readiness_assessment["next_actions"][0]`,
`workspace["recommended_actions"][0]`) over inventing new phrasing,
falling back to a short generic instruction (e.g. "Create project
brief", "Generate CAD", "Human final review") only where no existing
computed text applies yet. Nothing here executes, generates, validates,
approves, or slices anything - `next_action` is always a string a human
reads and acts on themselves.

## Confidence

`confidence` (`high`/`medium`/`low`) measures how much receipt-backed
evidence this evaluation had to work with - **not** how good the project
is. It counts missing/degraded signals (unreadable or missing brief,
missing manifest, no export receipt, no generation receipt, no artifact
history yet) - more missing evidence lowers confidence. A project with
`confidence: "low"` may still have an accurate `health_score`; the field
just says the evaluation rests on thinner ground.

## Recent activity

`_recent_activity()` is a thin window over Phase 40's own timeline - the
last 5 dated events, most recent first, each `{"label", "date",
"severity", "category"}`. It never re-parses a receipt itself, only reads
`factory.project_timeline.get_project_timeline()`'s own already-computed,
already-ordered event list.

## The CLI

```bash
factory health <project_dir> [--json] [--verbose]
```

Entirely read-only - there is no write flag. Human-readable output
(default) shows Status/Health/Lifecycle/Completion/Blockers/Warnings/
Risks/Next Action; `--verbose` additionally shows the category score
breakdown, full blocker/warning/risk detail, strengths, recent activity,
and artifact history detail. `--json` returns the full
`evaluate_project_health()` payload plus `"errors": []`.

Example:

```
PROJECT HEALTH

Storage Bin Lid

Status:
Ready for Slicer Review

Health:
87% (good)

Lifecycle:
slicer_review

Completion:
77%

Blockers:
0

Warnings:
2

Risks:
1

Next Action:
Open the parts in a local slicer for manual review - see manual_review/README.md.

Confidence: high

This is a read-only aggregation of existing Factory intelligence - it never
recalculates readiness, never overrides a blocker, and never writes anything.
Human approval required. No automatic printing.
```

## JSON contract

`--json` is the entire stdout, never mixed with plain text: the full
`evaluate_project_health()` dict plus `"errors": []` on success; on a
missing project directory, `{"errors": [...], "no_automatic_print":
true}` with exit code 1. Deterministic: the same underlying files always
produce the exact same JSON.

## Preview Board integration

### Architectural note

See "Architectural note" above - `factory.preview_board.gather_board_data()`
calls `summarize_project_health(project_dir)` directly per project, the
same architectural pattern as `slicer_readiness_summary`/
`manual_review_summary`/`slicer_intelligence_summary`/`timeline_summary`/
`artifact_history_summary`.

### The card

A compact "Project Health" card - **the first card section on every
project**, ahead of "Project Readiness" (a dashboard *of* dashboards,
summarizing every card below it without replacing or removing any of
them): Status, Health (score + level badge), Stage, Blocker count,
Warning count, Next action. `summarize_project_health()`'s fields:
`status`, `score`, `health_level`, `lifecycle_stage`, `blocker_count`,
`warning_count`, `next_action`.

## Failure handling

A project with no receipts at all yet still returns a full, honest
evaluation - every underlying `summarize_*`/`assess_*`/`evaluate_*`
function already degrades gracefully for missing files (see each
module's own "Failure handling"); this module never raises for a bare or
partially-populated project.

## Limitations

- **The health score is a documented heuristic, not a certification.**
  It exists to give a rough at-a-glance sense of progress and quality; it
  is never authoritative over any individual module's own assessment.
- **A rare multi-part-assembly-incomplete condition may not always
  escalate `lifecycle_stage` to `"blocked"`** if it doesn't also trip
  `health_signals["summary"] == "blocked"` or a validation failure - the
  underlying message is still visible via `readiness_summary`/
  `readiness_assessment["blockers"]` either way, just not necessarily
  reflected in the coarser `lifecycle_stage`/`overall_status` fields.
- **`confidence` measures evidence, not quality** - a low-confidence
  evaluation is not necessarily a low-quality project, just one with less
  receipt-backed history to draw on.
- **No file restoration, no automatic action of any kind** - this module
  has no write path of its own at all.

## Non-goals

- **No AI, no LLM, no machine learning of any kind.**
- **No network calls.**
- **Never invokes a slicer, generates G-code, or contacts a printer.**
- **Never recalculates readiness, duplicates risk/validation/artifact
  logic, creates new approval rules, or overrides an existing blocker.**
- **Never becomes authoritative** - if this module's rendering of a
  status, score, or blocker ever disagrees with the module that produced
  it, that module is correct.

## Consumed by Phase 52

`factory.manufacturing_readiness` (Phase 52) reads this module's
`evaluate_project_health()` directly as its traditional-pipeline lens,
alongside `factory.design_review`'s hybrid-pipeline lens - the two
ladders this module explicitly does not read (see "Why this is not
`factory.design_review`" precedent set in reverse). Phase 52 never
modifies `HEALTH_CATEGORY_WEIGHTS` or any other scoring here; see
`docs/manufacturing-readiness.md`.

See also `docs/artifact-history.md` (Phase 41),
`docs/project-timeline.md` (Phase 40),
`docs/slicer-analysis-history.md` (Phase 39),
`docs/slicer-intelligence.md` (Phase 38),
`docs/manual-review-workspace.md` (Phase 37),
`docs/slicer-readiness.md` (Phase 36),
`docs/design-orchestrator.md` (Phase 33), `docs/architecture.md`
("Aggregation Layer Convention"), `docs/preview-board.md`, and
`docs/roadmap.md` Phase 42.

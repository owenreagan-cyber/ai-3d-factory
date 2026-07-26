# Slicer Review Intelligence & Print Risk Analysis (Phase 38)

`factory.slicer_intelligence` is a deterministic, read-only analysis
layer that identifies potential slicer-review concerns before a human
opens a slicer:

```
Slicer Readiness -> Manual Review Workspace ->
Slicer Review Intelligence -> Human Slicer Review ->
(never automatic printing)
```

**This does NOT slice, does NOT generate G-code, does NOT control a
printer, and does NOT replace human slicer judgment.** It prepares a
more intelligent review experience on top of Phase 36's readiness
assessment and Phase 37's workspace - identifying build-volume fit,
geometry risks, manufacturing risks, and review priorities, all from data
this repo already measures.

## This is a thin analysis layer over already-computed state

It never re-implements mesh validation, dimension checks, printer/
material knowledge, artifact fingerprinting, or checklist generation. It
reuses:

- `factory.manual_review_workspace.assess_manual_review_workspace()`
  (Phase 37) directly - itself already reusing
  `factory.slicer_readiness.assess_slicer_readiness()` (Phase 36),
  `factory.manufacturing.knowledge` (printer/material profiles), and
  `factory.slicer.local_slicer_probe.probe_slicers()`.
- `factory.export_pipeline.read_export_receipt()` - to find each current
  STL's already-written validation report path.
- Each project's own `validation/<name>_validation.json`'s already-
  computed `mesh_stats` (bounding box, volume, watertight, vertex/face
  counts) - written by `factory.validators.mesh_validate.validate_mesh()`
  - never re-parses the STL itself.
- `factory.validators.dimension_check.check_build_volume_fit()` - called
  fresh with the project's own resolved target printer, since the
  validation report's own embedded check may reflect the fleet's default
  printer instead (see "Build volume analysis" below) - never
  re-implemented.
- `factory.manufacturing.knowledge.get_printer()` - for the printer's
  `verified` flag.

## Only reports risks supported by existing measurable data

Geometry risks are derived only from a part's own already-measured
bounding box/volume/watertight data. Anything not measurable by this
repo's existing tools (overhangs, bridging, supports, orientation) is
surfaced as a review *prompt*, never a claimed detection.

**Language matters here.** Every finding is phrased as a "Possible Risk,"
never "Will Fail" - this module never claims a model will fail to print,
only that something is worth a human's attention before slicing.

## Read-only, always

`evaluate_slicer_intelligence()` never writes anything, never invokes a
subprocess, never launches a slicer, never generates G-code, and never
contacts a printer or the network. There is no write path in this phase
at all - unlike Phase 36/37, this module has no `--create-*`/`--confirm-*`
flag, because it produces no persistent artifact of its own; it's purely
an analysis lens over state Phase 36/37 already track.

## Analysis model

`evaluate_slicer_intelligence(project_dir)` returns:

| Field | Meaning |
|---|---|
| `project` | Project name. |
| `project_path` | Absolute project directory path. |
| `analysis_status` | One of `ANALYSIS_STATES` - how much geometry data is actually available. |
| `printer` | Verbatim `printer_summary` from `assess_manual_review_workspace()` - never re-derived. |
| `material` | Per-part `{part_name, material, status}` - `status` is `known`/`unresolved`/`unknown_material`. |
| `build_volume_analysis` | See below. |
| `geometry_risks` | List of `{category, message}` - only categories supported by measured data. |
| `manufacturing_risks` | List of `{category, message}` - unresolved material/color/printer, validation failures/warnings. |
| `orientation_considerations` | Generic review prompts - never a prescribed orientation. |
| `support_considerations` | Generic review prompts - never a computed support plan. |
| `adhesion_considerations` | Review prompts, present only when a Large Flat Areas risk was found. |
| `multi_material_considerations` | Review prompts, present only for AMS-capable printers or multi-material projects. |
| `review_priority` | Ordered, deduplicated list of every finding's message - manufacturing risks first, then build-volume concerns, then geometry risks. |
| `risk_level` | `Low`/`Moderate`/`High`/`Unknown` - purely informational, never a blocker. |
| `warnings` | Every Phase 37 warning, plus this phase's own material/geometry-derived warnings. |
| `advisories` | Softer notes (e.g. an unverified printer spec). |
| `recommended_actions` | Ordered, human-readable next steps. |
| `confidence` | `High`/`Medium`/`Low`/`Unknown` - how much measured geometry data actually underlies this analysis. |
| `detected_slicers` / `local_slicer_status` | Verbatim from Phase 36 (`factory.slicer.local_slicer_probe`, unchanged). |
| `dry_run` / `no_automatic_print` | Always `True`. |

## Analysis status

`ANALYSIS_STATES`:

- **`no_geometry_data`** - no current STL has a readable validation
  report with `mesh_stats` yet (e.g. nothing exported, or every report is
  missing/unreadable).
- **`partial_geometry_data`** - some but not all current STLs have
  readable `mesh_stats`.
- **`full_geometry_data`** - every current STL has a readable validation
  report with `mesh_stats`.

## Build volume analysis

`check_build_volume_fit()` (unchanged, from `factory.validators.
dimension_check`) is called fresh per part, using the project's own
resolved `build_plan.json` target printer - **not** whatever printer the
part's validation report's own embedded `build_volume_fit` check used.
This matters: `factory.export_pipeline.run_validation()` defaults to the
manufacturing fleet's *primary* printer when validating, which may not be
the project's actually-selected target printer - re-checking with the
correct printer here avoids reporting a fit result against the wrong
machine.

For each part with a known bounding box and a resolved printer:

- **Fits** - the bounding box fits the build volume in some axis
  orientation. `remaining_margin_mm` reports the `{x, y, z}` margin for
  the *best* fitting orientation (largest minimum margin across all six
  permutations) - a genuinely new calculation (`_best_fit_margin()`) this
  repo didn't previously have, since `check_build_volume_fit()` itself
  only returns a PASS/WARN + text detail, not the winning permutation.
- **Does Not Fit** - no orientation fits. `remaining_margin_mm` is
  `None` - never invented for a part that doesn't fit.
- **Unknown** - no bounding box available yet, or no resolved printer
  with a known build volume. **Never invents a dimension.**

The top-level `fit_status`/`remaining_margin_mm` aggregate across every
part: `does_not_fit` if any part doesn't fit, else `unknown` if any part
is unknown, else `fits`; the aggregate margin is the *tightest* (smallest)
margin across every fitting part - the number a human most needs to see
first, never an average that could mask a tight part.

Example:

```
BUILD VOLUME
Printer: Bambu Lab H2D
Part: Fits
Remaining margin:
X: 190mm
Y: 220mm
Z: 311mm
```

## Geometry risk analysis

Only categories directly supported by already-measured `bounding_box_mm`/
`volume_mm3`/`is_watertight` data:

| Category | Signal | Guard against false positives |
|---|---|---|
| **Tall Narrow Geometry** | `z >= 3x` the larger of `x`/`y`. | Only above a 40mm minimum height - a tiny tall boss isn't flagged just because its aspect ratio looks dramatic. |
| **Large Flat Areas** | The smallest bbox dimension is <= 10mm and the other two are each >= 50mm and >= 6x the thin dimension. | Requires a genuinely large footprint, not just any thin part. |
| **Thin Features** | `volume_mm3 / (x*y*z)` (the "fill ratio") is below 15% - only computed when the mesh is watertight (volume requires it). | Both `volume_mm3` and the bounding box are already measured; never re-derived. |
| **Fragile Features** | `is_watertight` is `False`. | Reuses the exact watertight flag `mesh_validate()` already computes. |
| **Multi-part Alignment** | `part_manifest.json` has more than one part. | Reuses the same part-count signal Phase 37's checklist already uses. |

Overhangs, bridging, and supports are **never** computed geometry risks -
this repo has no per-face normal/slicing analysis to support such a
claim honestly. They are represented purely as review *prompts* in
`support_considerations` instead (see below).

## Support, orientation, and adhesion considerations

**Never computed, never a slicer call, never a support plan.** These are
always generic human review *questions*, mirroring
`factory.manual_review_workspace`'s own checklist convention exactly:

- `orientation_considerations` - always present, generic prompts (never
  a prescribed single orientation, never an automatic rotation):
  strongest face placement, cosmetic surface visibility, support
  minimization, layer-direction effects.
- `support_considerations` - present only once *some* geometry data
  exists (there's something to look at); otherwise `"Unknown"` (empty
  list). Never calculates supports.
- `adhesion_considerations` - present only when a "Large Flat Areas" risk
  was actually found - never invented for a project with no such risk.

## Material analysis

Reuses `factory.manual_review_workspace`'s already-computed
`material_summary` (which itself already cross-references the local
materials knowledge base) - never a second lookup. Each part's material
classifies as:

- **`known`** - the manifest's material string matched a known material
  in `factory.manufacturing.knowledge.load_materials()`.
- **`unresolved`** - the manifest still has a `"TBD"`/unresolved
  placeholder value.
- **`unknown_material`** - a real-looking material string was set, but it
  doesn't match anything in the local knowledge base ("Potential
  Concern") - a warning to confirm final filament, never invented
  settings for it.

## Multi-material considerations

Present only for AMS-capable printers or genuinely multi-material
projects (reusing `printer_summary["ams_available"]`/
`material_summary["multi_material"]` from Phase 37, never re-derived):
review color assignment per part, review part separation for multi-color
printing, review assembly order. **Never calculates purge, never
optimizes AMS slot assignments, never modifies anything.**

## Risk scoring

`risk_level` (`Low`/`Moderate`/`High`/`Unknown`) is a deterministic
summary: `Unknown` when there's no geometry data and no manufacturing
risks either; `High` whenever the build-volume fit is `does_not_fit`, or
three or more findings (geometry + manufacturing risks) exist; `Moderate`
for one or two findings; `Low` otherwise.

**`risk_level` is purely informational and never blocks anything.** It is
never consulted by `factory.slicer_readiness.assess_slicer_readiness()`
or `factory.review_gate.evaluate_review_gate()` - hard blockers remain
entirely controlled by those two modules, unaffected by anything this
phase computes.

## Confidence

`confidence` (`High`/`Medium`/`Low`/`Unknown`) reflects how much measured
geometry data actually underlies the analysis - a distinct concept from
`risk_level` (how worried to be) and from Phase 37's own
`review_confidence` (how ready/resolved the project is):
`Unknown` with no geometry data at all; `Low` with only partial geometry
data across parts; `High` when every part has full stats (bbox + volume +
watertight); `Medium` otherwise.

## Preview Board integration

### Architectural note: why `slicer_intelligence_summary` isn't on `summarize_project()`

Same reasoning as Phase 36/37's own summary fields:
`factory.slicer_intelligence` calls
`factory.manual_review_workspace.assess_manual_review_workspace()`, which
calls `factory.slicer_readiness.assess_slicer_readiness()`, which calls
`factory.review_gate.evaluate_review_gate()`, which already imports
`factory.project_inspection.summarize_project()`. Adding
`slicer_intelligence_summary` inside `project_inspection.py` would
recreate the exact circular import Phase 36 already discovered and Phase
37 confirmed again transitively. `factory.preview_board.gather_board_data()`
calls `summarize_slicer_intelligence(project_dir)` directly per project
and merges the result in at the same aggregation point as
`slicer_readiness_summary`/`manual_review_summary`.

### The card

`factory.preview_board.build_board_html()` renders a compact "Slicer
Intelligence" card, placed right after "Manual Review Workspace" (all six
meta-cards - Project Readiness, Generation Gate, Post-Generation
Pipeline, Slicer Review Readiness, Manual Review Workspace, Slicer
Intelligence - summarize what's possible next). Shows: risk level
(badged), build volume fit (badged), review item count, the top review
priority, analysis confidence (badged), and a standing "Human review
required" reminder. Purely presentational - it never analyzes anything
itself; it never opens a slicer, generates G-code, or prints anything.

Example:

```
SLICER INTELLIGENCE
Risk: Moderate
Build: Fits
Review Items: 3
Priority: Confirm orientation
Human review required
```

`summarize_slicer_intelligence()`'s fields: `risk_level`,
`build_volume_fit`, `review_item_count`, `top_priority`, `confidence`,
`warning_count`.

## The CLI

```bash
factory slicer-inspect <project_dir> [--json]
```

Entirely read-only - there is no write flag. Shows project, printer,
build volume (with remaining margin, when it fits), risk level, review
priorities (numbered), warnings, advisories, and confidence.
Human-readable output ends with an explicit "No slicer was opened." /
"No G-code was generated." / "No print was started." trailer.

Example:

```
Slicer Review Intelligence

Project:
Teacher Nameplate

Printer:
Bambu Lab H2D

Build Volume:
Fits
  remaining margin - x: 190.0mm, y: 220.0mm, z: 311.0mm

Risk:
Moderate

Review Priorities:
1.
Confirm final filament.
2.
Possible Risk: 3 parts require assembly/alignment review in the slicer.

Warnings:
- Material unconfirmed for: base, text, badge.

Confidence: High

No slicer was opened.
No G-code was generated.
No print was started.
```

## JSON contract

`--json` is the entire stdout on every path, including the only error
this command can hit (a missing project directory) - never mixed with
plain text before or after. Top-level fields mirror
`evaluate_slicer_intelligence()`'s model (above) plus this CLI's own
`errors` (always `[]` on success, since there is no write path to fail).

## Failure handling

Every failure mode resolves to a structured, honest outcome rather than a
crash or false success: missing project directory (CLI-level `errors` +
exit 1, clean JSON); malformed/missing validation report
(`_load_part_geometry()` marks that part's `mesh_stats` as `None` /
`validation_report_status: "unreadable"`/`"missing"` rather than raising);
unresolved/unrecognized printer or material (reported honestly, never
invented); no current STL at all (`analysis_status: "no_geometry_data"`,
`confidence: "Unknown"`, geometry-dependent sections degrade to empty
lists rather than guessing).

## Limitations

- **No per-face geometry analysis** - overhangs, bridging, wall
  thickness, and support requirements are never computed; they exist
  only as generic review prompts, by design, not as a gap to eventually
  fill with a simulated slice.
- **Build-volume-fit margin picks one "best" orientation** - it does not
  account for print-orientation tradeoffs (support minimization,
  cosmetic-surface-down, strength along a specific axis); it is a
  geometric fit check only.
- **Material matching is exact, not fuzzy** - inherited from
  `factory.manual_review_workspace`'s own material lookup; a material
  string that doesn't exactly match a known one reports
  `unknown_material` rather than a best-guess nearest match.
- **No history** - every call recomputes fresh from current files; there
  is no persisted analysis to compare against over time (by design - this
  phase has no write path at all).

## Non-goals

- **No AI, no LLM, no machine learning of any kind.**
- **No network calls, no web search, no scraping.**
- **Never invokes a slicer, generates G-code, queues a print job, or
  contacts a printer.**
- **Never selects a slicer profile, never auto-orients a model, never
  auto-generates supports, never auto-optimizes a print.**
- **Never invokes Blender, Meshy, or FreeCAD.**
- **Never installs anything.**
- **Never re-implements mesh validation, dimension checks, printer/
  material knowledge, artifact fingerprinting, or checklist generation** -
  each is read directly from its existing module.
- **`risk_level` never blocks printing** - hard blockers remain entirely
  controlled by `factory.slicer_readiness`/`factory.review_gate`.

See also `docs/manual-review-workspace.md` (Phase 37),
`docs/slicer-readiness.md` (Phase 36), `docs/export-pipeline.md`
(Phase 35), `docs/manufacturing-knowledge-base.md`,
`docs/review-gate.md`, `docs/preview-board.md`,
`docs/slicer-review-workflow.md`, and `docs/roadmap.md` Phase 38.

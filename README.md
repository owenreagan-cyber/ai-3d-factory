# ai-3d-factory

`ai-3d-factory` is a local-first CLI that helps create, organize, validate,
preview, and package 3D print projects for human slicer review. It is not
an auto-printer; see `AGENT.md` for the full philosophy and safety rules.

## What this repo is not

- Not an auto-printer. Nothing here sends a print job, slices with intent
  to print, or controls a printer.
- Not connected to Meshy or any paid generative-mesh/AI API. Meshy is
  future-only, always disabled by default, and gated behind a documented
  approval/cost checklist before any implementation may add real calls -
  see `docs/meshy-approval-gate.md` and `factory check-future-tools`.
- Not connected to Bambu cloud or any printer over LAN/USB.
- Not something that marks a project `print_ready` automatically.

## Before you start

Make sure the toolchain foundation is installed and verified. This repo
does not install system packages itself:

```bash
cd ~/Projects/ai-3d-factory-installer
./install.sh --dry-run
./install.sh --install
./verify.sh
```

## Setup

```bash
cd ~/Projects/ai-3d-factory
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

Copy `.env.example` to `.env` only if and when you have a specific,
approved, local-only use for one of the currently optional and unused
variables. Do not fill in real API keys; this project does not call paid
APIs. See `AGENT.md`.

## CLI usage

```bash
factory status                       # environment + safety status
factory init-project my-part         # scaffold projects/my-part/
factory plan projects/my-part/brief.json   # printer-aware plan + manufacturing options
factory list-options projects/my-part      # explain every manufacturing option
factory choose-option projects/my-part <option_id>   # record your explicit choice
factory list-printers                # inspect the printer fleet (read-only)
factory show-printer bambu_h2d
factory list-accessories             # inspect the accessory catalog (read-only)
factory list-materials                # inspect materials (read-only)
factory fleet-summary                 # compact view of all printers
factory check-manufacturing           # validate config/manufacturing/*.json
factory route-cad projects/my-part    # read-only CAD backend recommendation
factory generate-openscad projects/my-part --template test-cube
factory generate-cadquery projects/my-part --template mechanical-plate
factory validate path/to/model.stl
factory render path/to/model.stl
factory render-coverage projects/my-part  # read-only STL/render coverage report
factory plan-renders projects/my-part     # lists suggested `factory render` commands, runs none
factory preview-index projects/my-part    # read-only visual-artifact summary
factory preview-project projects/my-part  # build/refresh preview_package/
factory preview-board projects/           # static local board across all projects
factory review-gate projects/my-part      # pass/warn/fail gate for HUMAN slicer review only
factory inspect-slicer               # read-only slicer discovery
factory report projects/my-part      # includes manufacturing + preview package summary
factory list-examples                 # list the committed examples/ library (read-only)
factory show-example simple-nameplate # detail for one example (read-only)
factory check-future-tools            # read-only Meshy/future cloud tool gate status
factory check-local-tools              # read-only Blender/future local tool gate status
factory check-design-intent brief.json # read-only design_intent vs. known printer build volumes
```

`factory plan` reads a local manufacturing knowledge base
(`config/manufacturing/`: printers, materials, accessories, planning rules)
to resolve the target printer, explain every manufacturing option (single
piece vs. various multi-part approaches) with pros/cons, and recommend one -
non-bindingly, always requiring explicit human confirmation via
`factory choose-option`. `config/manufacturing/printers.json` is the sole
canonical printer source; `factory list-printers`/`show-printer`/
`list-accessories`/`show-accessory`/`list-materials`/`show-material`/
`fleet-summary` inspect it directly (all read-only), and
`factory check-manufacturing` validates it for internal consistency. See
`docs/manufacturing-knowledge-base.md`.

`factory preview-project` aggregates a project's existing CAD/STL/render/
manifest files into `preview_package/index.json` + `preview_report.md` - a
visual-artifact summary and advisory human inspection checklist, never a
new render or an automatic approval. See `docs/visual-preview-package.md`.

`factory route-cad` explains (read-only) which CAD backend a project's
brief points to - OpenSCAD or CadQuery today, Blender/Meshy reserved for
later. `factory generate-cadquery` is a CadQuery starter backend
(`mechanical-plate` template): CadQuery is optional and never installed by
this repo, so the command fails cleanly if it isn't already available. See
`docs/cad-backends.md`.

`factory render-coverage` compares `stl/*.stl` against `renders/*.png` for
one project - which meshes have a matching render, which are missing one,
which renders are stale or orphaned. `factory plan-renders` only lists the
`factory render <stl_path>` commands a human could run to fix gaps; it
never runs them. Both feed the same coverage data into
`preview_package/index.json` (`render_coverage`, `missing_renders`,
`all_meshes_have_renders`) and into `factory preview-board`. See
`docs/render-coverage.md`.

`factory preview-board` aggregates every project under a `projects_root`
into one static local board (`preview_board/index.json` +
`preview_board/index.html` - no server, no cloud, plain HTML you open
directly). Each project is classified into a visual-readiness state
(`needs_brief`, `cad_source_ready`, `needs_stl_export`, `needs_render`,
`slicer_review_ready`, `blocked_or_incomplete`) - a visual inspection aid,
never an approval or print-readiness signal. Each project also gets a
`suggested_actions` list - safe, copyable next-step commands (e.g. `factory
render <path>` for a missing preview, or `factory validate <path>` for an
STL with no local validation report yet) shown in a "Suggested next steps"
section on the board's HTML page as plain text/code blocks. A
`health_signals` field (`summary`: ok/attention_needed/blocked, plus
structured `items`) rolls up everything worth flagging - missing/unreadable
files, render/validation coverage gaps - for scanning many projects at a
glance, shown in a "Health signals" section and a compact "Health" column.
Each project also gets a "Design Intent" card (quality target, purpose,
style, manufacturing fit, reference input count, and design notes/warnings
if the brief declares a `design_intent` block - see
`docs/design-intent-brief.md`), a compact "Reference Board" card right
next to it (reference count, license-status/usage-intent breakdowns, and
advisory warnings if the project has an optional `reference_board.json` -
see `docs/reference-board.md`), plus CAD/STL/Render/Review-readiness
status badges - visualization only, static HTML/CSS, no JavaScript.
Nothing is ever run automatically; the human decides what to copy and
execute. See `docs/preview-board.md`.

`factory review-gate` is a read-only pass/warn/fail pre-flight check for
one project: does it have everything needed on disk for a **human** to
review it in a slicer? It reuses the same `preview-board` classification
(no duplicated logic) but applies its own, slightly stricter policy - a
missing render is a hard blocker here (nothing to look at yet), not just
a warning. `pass` means only "ready for human slicer review" - never an
approval, never print-ready; the status ceiling stays `slicer_review_ready`.
Exit code is `0` for pass/warn, `1` for fail. See `docs/review-gate.md`.

`review-gate`/`preview-board` check local **readiness** (do the right
files exist, are they fresh) - they say nothing about whether a design is
actually good. Before approving anything, a human should also work
through `docs/review-gate.md`'s "Human review quality checklist" against
the "Etsy-worthy" standard in `docs/design-quality-standard.md`.

`factory check-design-intent <brief_or_concept_brief.json>` is a small,
read-only, advisory command: if the file has an optional `design_intent`
block (see `docs/design-intent-brief.md`), it reports whether the
declared `manufacturability_constraints.max_size_mm` fits any locally
configured printer's build volume. It never inspects real mesh geometry,
never contacts a printer/slicer/network, never writes a file, and never
sets `human_approved`/`print_ready` - it's a size sanity check on
declared intent, not a substitute for `factory validate` or the human
review checklist above.

`factory reference-board init/show/validate/add/list <project_dir>` manages
a project's optional local Reference Board (`reference_board.json` -
inspiration photos, existing files, a MakerWorld/Thingiverse/Reddit/
Pinterest/DeviantArt page, a sketch, and so on - see
`docs/reference-board.md`) without hand-editing JSON: `init` creates a
documented starter file (never overwriting one that exists, unless
`--force`), `show`/`list` display it, `validate` runs the same advisory
checks the preview board already surfaces (never failing on incomplete
data - only malformed JSON is an error), and `add --project <dir> --title
<title> [--url ...] [--type ...] [--license ...] [--usage ...]
[--attached-to ...] [--notes ...]` appends one new reference, always
additive - never overwriting or removing an existing entry. Fully local:
no search, scraping, downloading, or API/network call of any kind - a
recorded `--url` is inert metadata, never fetched.

`factory intake analyze <project_dir_or_text_or_markdown_file> [--json]` is
the Project Intake Engine (`factory.project_intake`, see
`docs/project-intake.md`) - the first step in this repo's pipeline (User
Idea -> Project Intake -> Project Brief -> Design Intent -> Reference
Board -> ...). Converts a free-form idea (plain text, Markdown, or an
existing project's `brief.json` description) into structured metadata -
category, audience, environment, material/printer assumptions, quality
target, manufacturing style, functional/visual goals, dimensional
constraints, and commercial intent, each with a confidence level, plus
advisory warnings. **Fully deterministic - no AI, no LLM, no network, no
search, no downloading**: every field comes from a closed keyword table or
regex, never a model. Entirely read-only - it never creates or edits a
`brief.json`, `design_intent`, or `reference_board.json`; a human still
authors the actual brief by hand.

`factory intake suggest-brief <project_dir_or_text_or_markdown_or_intake_json>
[--json] [--write] [--force] [--update]` is the Intake-to-Brief Draft
Generator and safe Merge/Update workflow (`factory.brief_generator`, see
`docs/brief-generator.md`) - the next pipeline steps: User Idea -> Project
Intake -> **Draft Brief** -> **Brief Merge/Update** -> Design Intent ->
Reference Board -> .... Shapes an already-computed `intake_summary` into a
proposed `brief.json`/`design_intent`/manufacturing-notes draft - a field
is only populated when its intake confidence is high/medium, everything
else stays explicitly "unknown"/"not specified," never guessed. **Without
`--write`, this is entirely read-only** - it just prints the draft (or,
with `--update`, a merge preview). **With `--write` alone, it writes
exactly one file**, `<project_dir>/brief.json`, and only after confirming
the project directory exists and `brief.json` doesn't already exist there
(`--force` to intentionally *replace* it wholesale). **With `--update`
(alone, or with `--write`), it safely *merges* instead** - a field already
holding real content in an existing `brief.json` is always preserved
untouched; only genuinely missing/placeholder fields get filled from a
confident draft value. `--force` and `--update` are mutually exclusive and
rejected together. Every draft/merge ends with "Human approval required
before save" - a generated result, however complete, is never itself an
approval.

`factory readiness <project_dir_or_projects_root_or_text_or_markdown_file>
[--json]` is the Design Orchestrator (`factory.design_orchestrator`, see
`docs/design-orchestrator.md`) - the pipeline's first "decision brain":
User Idea -> Project Intake -> Draft Brief -> Brief Merge -> Design Intent
-> Reference Board -> **Project Readiness** -> **Design Orchestrator** ->
CAD Engine -> .... Evaluates whether a project is sufficiently defined to
proceed and recommends the most appropriate downstream engine (OpenSCAD,
CadQuery, Blender, `Meshy (Concept Only)`, FreeCAD, a hybrid workflow,
manual design, or unknown) from a weighted 0-100 readiness score across
five categories (Intake/Brief/Design Intent/Reference Board/Manufacturing
- weights documented in `docs/design-orchestrator.md`). **No CAD is ever
generated and no engine is ever invoked** - `recommended_engine` is a
string a human reads and acts on themselves. Fully deterministic: reuses
the same six summaries every phase above it already computed, plus the
existing `factory.router.recommend_tool()` keyword router as a text-based
fallback, rather than duplicating parsing or inventing a second keyword
table.

`factory generate-from-readiness <project_dir_or_text_or_markdown_file>
[--confirm-generate] [--json]` is the Readiness-Gated CAD Generation Router
(`factory.generation_gate`, see `docs/generation-gate.md`) - the pipeline's
next step: Project Readiness -> Design Orchestrator -> **Readiness-Gated
CAD Router** -> CAD Engine -> .... **An adapter/gate around this repo's
*existing* local CAD generation (OpenSCAD, CadQuery), not a second CAD
backend.** Dry run by default: always computes and shows a full generation
plan (recommended engine, template, what's still missing) but writes
nothing. Only with `--confirm-generate`, and only if every readiness gate
independently passes (a supported, locally-available engine; readiness
state one of the four `"Ready For ..."` states; score at or above a
conservative threshold; no critical information missing), does it call the
existing `generate_openscad()`/`generate_cadquery()` - never Blender,
never Meshy, never FreeCAD, never an install, never a network/printer
contact. After a successful confirmed generation, it also writes an
execution receipt (`<project_dir>/generated/generation_receipt.json` -
project, engine, template, readiness score/state, files generated,
artifact sizes, and a normalized artifact-tracking breakdown reusing this
repo's existing manifest/validation infrastructure rather than
duplicating it); dry runs never produce one. Fully deterministic: reuses
the Design Orchestrator's already-computed readiness summary outright,
never re-scores anything.

`factory export-from-cad <project_dir> [--confirm-export] [--json]
[--source ...] [--output-dir ...] [--overwrite-stl] [--validate] [--render]
[--all] [--resume]` is the Guided Export Pipeline (`factory.export_pipeline`,
see `docs/export-pipeline.md`) - the pipeline's next step: CAD Source
Generation -> **Guided Export Pipeline** -> STL Verification -> Validation
and Preview -> Artifact Finalization -> Human Review Gate -> .... **This
orchestrates existing local commands - it never re-implements CAD
generation, STL export, mesh validation, or preview rendering.** Dry run by
default: always computes a full export plan (CAD source found, exporter
detected, expected output, collisions/staleness) but invokes no subprocess
and writes nothing. Only with `--confirm-export`, and only for OpenSCAD
source with a local `openscad` executable found and no unresolved output
collision (pass `--overwrite-stl` to allow one), does it actually export -
using argument-list subprocess execution, a bounded timeout, and full
post-exit verification (output exists, is non-empty, has a plausible mesh
extension - a zero exit code alone is never treated as success). **CadQuery
source is never executed automatically** - this repo's existing
manual-export policy for CadQuery is unchanged; the exact manual command is
shown instead. `--validate`/`--render`/`--all` optionally call the existing
`factory.validators.mesh_validate`/`factory.previews.render_preview`
directly against the resulting (or an already-existing) STL, and
`--resume` skips a source file's step when a prior export receipt already
records it as current for that exact fingerprint. Writes
`<project_dir>/generated/export_receipt.json` (a sibling of Phase 34's
generation receipt, upserted per source file - dry runs never produce one)
and never invokes Blender, Meshy, a slicer, or a printer.

`factory slicer-readiness <project_dir> [--json] [--create-package]
[--confirm-package] [--output-dir ...] [--approve] [--approval-note ...]
[--refresh] [--include-warnings] [--force-package]` is Slicer Review
Readiness Promotion (`factory.slicer_readiness`, see
`docs/slicer-readiness.md`) - the pipeline's next step: Guided Export
Pipeline -> STL Validation and Preview -> **Slicer Review Readiness** ->
Human Approval -> Manual Slicer Review -> .... **A thin assessment/
promotion layer over already-computed state, never re-implementing mesh
validation, review-gate logic, slicer detection, or manufacturing
checks.** Read-only by default: always computes a full readiness
assessment (11 machine-readable states, a documented weighted score that
can never override a hard blocker) but writes nothing, records no
approval, creates no package, and never invokes a slicer. Only
`--approve` records human approval (fails cleanly unless every technical
signal is already satisfied; automatically invalidated the moment a
relevant artifact's fingerprint changes), and only `--create-package
--confirm-package` (both required together, and only once approved)
writes `slicer_review/slicer_review_manifest.json` - conforming to the
pre-existing `schemas/slicer_review.schema.json` - plus a human-readable
checklist README, **referencing existing STL/validation/render files by
relative path, never copying them**. `auto_print_allowed` is always
`false`; the CLI always ends with an explicit no-automatic-print trailer.

`factory review-workspace <project_dir> [--json] [--create-workspace]
[--confirm-workspace] [--output-dir ...] [--force-workspace]` is the
Manual Review Workspace (`factory.manual_review_workspace`, see
`docs/manual-review-workspace.md`) - the pipeline's next step: Slicer
Review Readiness -> Human Approval -> Review Package -> **Manual Review
Workspace** -> Human Slicer Review -> .... **This phase does not slice,
does not generate G-code, and does not print** - it only organizes
everything a human needs before opening a slicer, on top of Phase 36's
already-computed readiness. Read-only by default: always computes a full
workspace assessment (local printer/material profile inspection -
reporting `"Unknown"` rather than inventing an unresolved value; a
structured multi-category review checklist; a deterministic
`review_confidence`/`remaining_risk` pair) but writes nothing and never
invokes a slicer. Only `--create-workspace --confirm-workspace` (both
required together, and only once the underlying Phase 36 assessment is
both technically ready and approved) writes
`manual_review/review_manifest.json` plus a human-readable checklist
README with a Human sign-off section, **referencing existing STL/
validation/render/review-package files by relative path, never copying
them**. The CLI always ends with an explicit no-automatic-print trailer.

`factory slicer-inspect <project_dir> [--json] [--history] [--compare]
[--save-analysis]` is Slicer Review Intelligence & Print Risk Analysis
(`factory.slicer_intelligence`, see `docs/slicer-intelligence.md`) - the
pipeline's next step: Manual Review Workspace -> **Slicer Review
Intelligence** -> Slicer-Aware Review Profiles -> Analysis History ->
Human Slicer Review -> .... **This does not slice, does not generate
G-code, does not control a printer, and does not replace human slicer
judgment** - it identifies potential slicer-review concerns before a
human opens a slicer, on top of Phase 37's already-computed workspace
state. **Default (and `--history`/`--compare`) is entirely read-only.**
Reuses `factory.manual_review_workspace.assess_manual_review_workspace()`
for every printer/material/technical-readiness signal, and each current
STL's already-written validation report (bounding box, volume,
watertight) for build-volume-fit (a genuinely new per-axis
remaining-margin calculation atop the existing
`check_build_volume_fit()`) and geometry-risk analysis (Tall Narrow
Geometry, Large Flat Areas, Thin Features, Fragile Features, Multi-part
Alignment - only categories supported by already-measured data, always
phrased "Possible Risk," never "Will Fail"). A deterministic
`risk_level`/`confidence` pair is purely informational - it never
overrides `factory.slicer_readiness`/`factory.review_gate`'s own hard
blockers.

Phase 39 added slicer-aware review guidance (`factory.slicer_profiles`,
see `docs/slicer-profiles.md`) - a `slicer_profile`/`slicer_specific_checks`
addition to the same analysis (Bambu Studio/OrcaSlicer/PrusaSlicer/Unknown,
reusing `factory.slicer.local_slicer_probe.probe_slicers()`, never
inventing an installed profile) - and a lightweight, local, append-only
analysis history (`factory.slicer_history`, see
`docs/slicer-analysis-history.md`). **History is observational only** -
it never affects readiness, approval, slicing, or printing. `--history`
lists every saved snapshot; `--compare` shows what changed between a
fresh live analysis and the most recently saved one (STL/CAD/printer/
material/validation/risk/slicer-environment/warnings changes); only
`--save-analysis` writes anything (`generated/slicer_analysis_history.json`,
never written automatically by any other command or by `factory
preview-board`). The CLI always ends with an explicit no-automatic-print
trailer.

This CLI is the local engine, not the final intended user experience - see
`docs/product-vision.md` for the (not-yet-built) future visual/launcher
direction.

`examples/` is a permanent, committed library of example projects (unlike
`projects/`, which is gitignored) demonstrating this workflow end to end:
`examples/simple-nameplate/`, `examples/mechanical-plate/`,
`examples/multipart-classroom-sign/` (a 3-part base+text+badge assembly),
and `examples/storage-bin-lid/` (a 3-part lid+label+pull-tab assembly)
are real, runnable demos built with the actual CLI/OpenSCAD source
(stopping at the CAD-source stage, no STL/PNG committed);
`examples/future-organic-models/` is a set of concept-only roadmap
placeholders (no CAD/mesh/render) for future Blender/Meshy-backed organic
modeling. `factory list-examples`/`show-example <name>` inspect the
library (read-only). See
`docs/examples-library.md`. `examples/intake-benchmarks/` is a separate,
small set of plain-Markdown files (not `factory`-managed projects) used
only to exercise the Project Intake Engine's parsing - see
`docs/project-intake.md`.

## Workflow

idea/brief -> build plan -> part manifest -> CAD/assets later phase
  -> mesh validation -> preview rendering -> slicer review package
  -> human approval -> future print-ready status

Phase 0/1 stops at `slicer_review_ready`. Human approval is always required
beyond that point; see `docs/safety-gates.md`.

## Repo layout

```
ai-3d-factory/
├── config/          # printers, materials, tolerances, agent policy
│   └── manufacturing/  # printer fleet, accessories, materials, planning rules
├── docs/            # architecture, safety, tool routing, workflows
├── schemas/         # JSON Schemas for briefs/plans/manifests/reports
├── src/factory/     # the factory CLI package
├── prompts/         # reference prompts for AI-assisted design steps
├── examples/        # committed example projects (working demos + roadmap concepts)
├── projects/        # your actual projects (contents gitignored)
└── tests/           # pytest suite
```

## Safety

See `AGENT.md`, `docs/safety-gates.md`, and `config/agent_policy.json` for
the full allowed/blocked list: printing, cloud upload, printer control,
paid APIs, MCP, Blender add-ons, and copyrighted assets. This repo carries
forward the same boundaries as `ai-3d-factory-installer` and does not
relax any of them by default.

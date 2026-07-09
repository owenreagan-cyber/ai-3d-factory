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
`docs/design-intent-brief.md`) plus CAD/STL/Render/Review-readiness status
badges - visualization only, static HTML/CSS, no JavaScript. Nothing is
ever run automatically; the human decides what to copy and execute. See
`docs/preview-board.md`.

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
`docs/examples-library.md`.

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

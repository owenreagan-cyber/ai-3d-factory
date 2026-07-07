# Roadmap

Automatic printing is never a default behavior in any phase below. Every
phase adds capability up through "ready for human slicer review" — the
human-approval and print-initiation boundary in `AGENT.md` does not move.

## Phase 0/1 (this repo, current)

Foundation: CLI (`factory`), JSON schemas, local mesh validation, local
preview rendering, read-only slicer discovery, project scaffolding.

## Phase 2 — CAD generation helpers (started)

OpenSCAD and CadQuery generation helpers: turn a build plan / part
manifest into starter parametric CAD source under `cad/`, and export it to
`stl/`. Still fully local; no AI call required to export geometry, though
an AI-assisted authoring step may propose the CAD source for human review.

**Started:** `factory generate-openscad` writes local, parametric `.scad`
source for four templates (`test-cube`, `nameplate`, `sign`,
`multipart-nameplate`) into a project's `cad/`, keeps
`slicer_review/openscad_export_instructions.md` and `part_manifest.json`
in sync, and advances `brief.json` status to `cad_generated`. See
`docs/openscad-generation.md`. STL export itself is still a manual,
human-run step (no automatic OpenSCAD invocation yet).

**Not yet started:** CadQuery generation helpers, and any automated,
locally-validated OpenSCAD export command.

## Phase 3 — manufacturing knowledge & printer-aware planning (started)

A local manufacturing knowledge base (`config/manufacturing/`: printers,
materials, accessories, planning rules) and a deterministic decision engine
that turn `factory plan` into a manufacturing advisor, not just a tool
router. See `docs/manufacturing-knowledge-base.md` for the full write-up.

**Started:** `factory plan` now resolves `brief.json`'s `intended_printer`
against a multi-printer fleet (`config/manufacturing/printers.json`),
explains every manufacturing option (single-piece, multipart for build
volume/color/detail/painting/strength, replaceable components) with
advantages/disadvantages and a non-binding recommendation
(`factory.manufacturing.decision_engine`), and seeds `part_manifest.json`
with planning-time placeholders (`factory.manufacturing.manifest`) without
ever overwriting a human edit or a later phase's real values.
`factory.validators.multipart_check` gained duplicate-name, duplicate-output,
missing-CAD-source, invalid-quantity, and shared-origin-consistency checks.
`factory report` now surfaces target printer/accessories/build volume,
every manufacturing option, the recommendation, manifest/multipart/
validation summaries, and every remaining human decision.

**Not yet started (at the time):** `factory add-printer` / `factory
add-accessory` commands (the knowledge base is hand-edited JSON for now),
automatically proposing a `required_parts` breakdown once a human confirms
a multi-part option, and reconciling the Phase 0/1 single-printer
`config/printers.json` with the Phase 3 fleet-aware
`config/manufacturing/printers.json` (resolved in Phase 5 - see below).

## Phase 4 — human manufacturing decision workflow + product vision foundations (started)

The human-in-the-loop half of Phase 3's decision engine: a workflow for
Owen to explicitly choose one of the manufacturing options `factory plan`
already explains, plus long-term product vision documentation for a future
visual/launcher experience (not built yet). See `docs/product-vision.md`.

**Started:** `factory list-options <project_dir>` prints every
manufacturing option from `build_plan.json` (advantages, disadvantages,
availability, recommendation, current selection) plus every unanswered
question. `factory choose-option <project_dir> <option_id>` records an
explicit human choice into `build_plan.json`'s `selected_manufacturing_option`
- typing a specific option id *is* the human confirmation that option
requires - without touching any other build_plan field, and advances
`brief.json`'s status forward-only to the new `manufacturing_option_selected`
status (never past it automatically; never to `human_approved`/`print_ready`).
`factory.manufacturing.manifest.compute_assembly_intent()` reflects the
selected option in `part_manifest.json` as a computed `assembly_intent`
summary - if the option implies a multi-part approach but `required_parts`
is still just a placeholder, it says so plainly ("Selected option implies
multipart planning, but detailed required_parts are still incomplete")
instead of fabricating a part breakdown. `factory report` now shows the
selected option (or the unresolved-decision state), that assembly-intent
summary, and whether CAD generation can proceed safely.
`docs/product-vision.md` documents the intended long-term visual
app/launcher direction and reserves (but does not implement) `factory
serve`/`open`/`preview-project`/`launcher-info`.

**Not yet started:** any actual UI/launcher/dashboard code, automatically
proposing a `required_parts` breakdown once multipart is confirmed (still a
manual follow-up by design - see Phase 3's "not yet started" list), and
`factory add-printer`/`factory add-accessory`.

## Phase 5 — manufacturing knowledge maintenance (started)

Makes the manufacturing knowledge base inspectable, validated, and ready for
future UI/launcher workflows - no CadQuery, no UI, no printer control or
hardware discovery. See `docs/manufacturing-knowledge-base.md`.

**Started:** `config/manufacturing/printers.json` is now the sole canonical
printer source - the old Phase 0/1 `config/printers.json` was removed once
`factory validate`'s build-volume-fit check was redirected to read from the
canonical fleet via `factory.manufacturing.knowledge`. Seven new read-only
commands make the knowledge base directly inspectable: `factory
list-printers`/`show-printer <id>`, `list-accessories`/`show-accessory <id>`,
`list-materials`/`show-material <id>`, and `fleet-summary` (a compact view of
all four printers). `factory check-manufacturing` validates
`config/manufacturing/*.json` for internal consistency (unique/consistent
ids, required printer fields, positive build volumes/nozzle sizes, known
accessory/material references, planning-rule option ids) with PASS/WARN/FAIL
output - see `factory.manufacturing.check`. All of the above are read-only:
no file writes, no project-state changes, no hardware discovery, no network.
`config/manufacturing/fleet_state.example.json` documents (as an example
only, not live data) a future structure for tracking each printer's current
setup (installed nozzle/build plate, loaded materials, spool slots) as
distinct from its fixed capabilities - not read by any command yet.

**Not yet started:** `factory add-printer` / `factory add-accessory`
commands; wiring `fleet_state`/current-setup data into the planner or
decision engine; reconciling `config/materials.json` with
`config/manufacturing/materials.json`; CadQuery generation helpers (still
Phase 2); any UI/launcher code (still the Future track below).

## Phase 6 — Blender repair/render automation

Scripted (non-interactive) Blender invocations for mesh repair (fixing
non-manifold geometry flagged by `factory validate`) and higher-fidelity
preview renders, as a local subprocess call — no Blender add-ons, no
Blender MCP.

## Phase 7 — optional Meshy, with approval/cost gates

Optional Meshy integration for organic concept generation, gated behind an
explicit per-use human approval step and a visible cost/credit estimate
before any call is made. Off by default; see `docs/licensing-policy.md`
and `docs/tool-routing.md`.

## Phase 8 — 3MF packaging experiments

Experimental packaging of multi-part projects into a single `.3mf` with
embedded per-part color/material assignments, as an alternative to the
separate-aligned-STL workflow in `docs/slicer-review-workflow.md`.

## Phase 9 — advanced slicer review automation

Richer slicer-review package generation (e.g. auto-populated checklists
from validation reports, plate-layout suggestions) — still ending at
human review, never at auto-slice or auto-print.

## Future track — visual workspace / launcher (not scheduled to a phase number)

The Mac app launcher, Dock icon, Shortcuts/Automator wrapper, "Chief of
Staff" command, local visual dashboard, and the visual preview requirements
(mesh preview, CAD source preview, manufacturing option preview,
multipart/exploded preview, planning board) described in
`docs/product-vision.md` are a long-term direction layered on top of the
CLI engine above, not a specific numbered phase yet. They will be assigned
phase numbers once a concrete implementation is scoped.

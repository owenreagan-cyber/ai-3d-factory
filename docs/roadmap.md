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

**Not yet started:** `factory add-printer` / `factory add-accessory`
commands (the knowledge base is hand-edited JSON for now), automatically
proposing a `required_parts` breakdown once a human confirms a multi-part
option, and reconciling the Phase 0/1 single-printer `config/printers.json`
with the Phase 3 fleet-aware `config/manufacturing/printers.json`.

## Phase 4 — Blender repair/render automation

Scripted (non-interactive) Blender invocations for mesh repair (fixing
non-manifold geometry flagged by `factory validate`) and higher-fidelity
preview renders, as a local subprocess call — no Blender add-ons, no
Blender MCP.

## Phase 5 — optional Meshy, with approval/cost gates

Optional Meshy integration for organic concept generation, gated behind an
explicit per-use human approval step and a visible cost/credit estimate
before any call is made. Off by default; see `docs/licensing-policy.md`
and `docs/tool-routing.md`.

## Phase 6 — 3MF packaging experiments

Experimental packaging of multi-part projects into a single `.3mf` with
embedded per-part color/material assignments, as an alternative to the
separate-aligned-STL workflow in `docs/slicer-review-workflow.md`.

## Phase 7 — advanced slicer review automation

Richer slicer-review package generation (e.g. auto-populated checklists
from validation reports, plate-layout suggestions) — still ending at
human review, never at auto-slice or auto-print.

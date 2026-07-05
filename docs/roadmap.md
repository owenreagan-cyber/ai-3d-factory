# Roadmap

Automatic printing is never a default behavior in any phase below. Every
phase adds capability up through "ready for human slicer review" — the
human-approval and print-initiation boundary in `AGENT.md` does not move.

## Phase 0/1 (this repo, current)

Foundation: CLI (`factory`), JSON schemas, local mesh validation, local
preview rendering, read-only slicer discovery, project scaffolding.

## Phase 2 — CAD generation helpers

OpenSCAD and CadQuery generation helpers: turn a build plan / part
manifest into starter parametric CAD source under `cad/`, and export it to
`stl/`. Still fully local; no AI call required to export geometry, though
an AI-assisted authoring step may propose the CAD source for human review.

## Phase 3 — multi-part / multi-color workflows

Tooling to help keep multi-part STL exports aligned to a shared origin,
and to pre-fill `part_manifest.json` entries (material/color/transform
notes) from a build plan, reducing manual manifest editing.

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

# Tool routing

`factory plan` produces a deterministic, keyword-based `tool_routing_recommendation`
(see `factory/router.py`) — no AI call. This document is the human-readable
policy that logic mirrors, and the source of truth when the two disagree.
As of Phase 7, `factory route-cad <project_dir>` (see `docs/cad-backends.md`)
explains this same routing at the CAD-backend level (available now vs.
future-only), read-only, without generating anything.

## OpenSCAD — default for measured, parametric, flat/decorative parts

Use for: signs, plates, text, labels, frames, organizers, tiles, flat
decorative geometry, simple parametric shapes.

Why: parametric models are easy to validate, re-parameterize, and export
deterministically to STL. This is the default starting point for anything
with real-world measurements that isn't a mechanical/dimensioned solid.

As of Phase 2, `factory generate-openscad` implements this for a handful
of common shapes (test cube, nameplate, sign, multi-part nameplate) as
local, deterministic templates — see `docs/openscad-generation.md`. It
writes `.scad` source only; exporting to STL is still a manual step.

## CadQuery — mechanical solids and dimensioned functional parts

Use for: brackets, adapters, mounts, clips, hinges, mechanical fixtures,
enclosures, boxes with fillets/chamfers, and other dimensioned functional
solids with exact engineering fits.

Why: CadQuery's boundary-representation (B-rep) modeling handles precise
fillets/chamfers and engineering fits more naturally than OpenSCAD's CSG
approach.

As of Phase 7, `factory generate-cadquery --template mechanical-plate`
implements a small starter backend (a parametric rectangular plate with
optional corner fillets, mounting holes, and an engraved label) — see
`docs/cad-backends.md`. CadQuery is an optional dependency: this repo never
installs it, and the command fails with a clear message if it isn't already
present in the environment. Like OpenSCAD, it writes source only; exporting
to STL is a manual, human-run step.

## Blender — future: mesh repair, booleans, organic cleanup, visual renders

Reserved for: repairing imported/scanned meshes, boolean operations,
organic mesh cleanup, and higher-fidelity visual renders (beyond the CLI's
quick matplotlib preview). Not the default path for measured parts — reach
for it when geometry is genuinely organic or a parametric approach isn't a
good fit. Not implemented as a generation backend yet; see `docs/roadmap.md`.

## Meshy — future: organic concept generation only, explicit approval required

Reserved for: organic concept generation, and only that. Every use will
require explicit human approval before the call is made — no automatic or
"surprise credits" usage. Not implemented in this repo; see
`docs/roadmap.md` and `docs/licensing-policy.md`.

## Bambu Studio / OrcaSlicer — human slicer review only

Use for: a human to review plate layout, per-part colors/materials, scale,
orientation, and supports before printing. `factory inspect-slicer`
performs read-only discovery of these apps; nothing in this repo launches
them, slices with them, or sends a print job through them. See
`docs/slicer-review-workflow.md`.

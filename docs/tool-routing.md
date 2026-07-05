# Tool routing

`factory plan` produces a deterministic, keyword-based `tool_routing_recommendation`
(see `factory/router.py`) — no AI call. This document is the human-readable
policy that logic mirrors, and the source of truth when the two disagree.

## OpenSCAD — default for measured, parametric parts

Use for: plates, signs, text, simple profiles, organizers, brackets,
frames, tiles, raised letters.

Why: parametric models are easy to validate, re-parameterize, and export
deterministically to STL. This is the default starting point for anything
with real-world measurements.

## CadQuery — mechanical/engineering solids

Use for: mechanical parts, fillets, chamfers, exact engineering solids,
threaded or tolerance-critical fits.

Why: CadQuery's boundary-representation (B-rep) modeling handles precise
fillets/chamfers and engineering fits more naturally than OpenSCAD's CSG
approach.

## Blender — mesh repair, booleans, organic cleanup, visual renders

Use for: repairing imported/scanned meshes, boolean operations, organic
mesh cleanup, and higher-fidelity visual renders (beyond the CLI's quick
matplotlib preview).

Not the default path for measured parts — reach for it when geometry is
genuinely organic or a parametric approach isn't a good fit.

## Meshy — organic concept generation only, explicit approval required

Use for: organic concept generation, and only that. Every use requires
explicit human approval before the call is made — no automatic or
"surprise credits" usage. Not implemented in Phase 0/1; see
`docs/roadmap.md` Phase 5.

## Bambu Studio / OrcaSlicer — human slicer review only

Use for: a human to review plate layout, per-part colors/materials, scale,
orientation, and supports before printing. `factory inspect-slicer`
performs read-only discovery of these apps; nothing in this repo launches
them, slices with them, or sends a print job through them. See
`docs/slicer-review-workflow.md`.

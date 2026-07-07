# car-concept (roadmap placeholder - concept only)

**Not a working example. Not generated. Not printable.** See
`../README.md` for why this whole directory is concept-only.

An original organic-form car-related accessory concept - not a
reproduction of any manufacturer part, logo, or badge (see
`../../../docs/licensing-policy.md`). No CAD source, mesh, or render
exists for this concept, and none will be generated until a future
Blender local-automation phase and/or a Meshy safety/cost approval gate
exist (see `../../../docs/roadmap.md`).

This directory intentionally contains only `README.md` and
`concept_brief.json` - no `brief.json`, no `cad/`, no `stl/`, no
`renders/`, no `part_manifest.json`. `factory preview-index` /
`factory preview-project` / `factory review-gate` will each report this
directory as missing a brief if pointed at it directly; that is expected.

## Meshy/Blender approval gates

If this concept is ever implemented, the two possible future backends
each require their own separate, explicit approval before any code may
call them:

- **Meshy** (cloud, paid, generative-mesh API) requires the full gate
  documented in `../../../docs/meshy-approval-gate.md` (designed in
  Phase 16, not implemented) - explicit human approval, a cost/budget
  cap, per-run confirmation, input review before upload, and output
  review after generation. `factory check-future-tools` (read-only)
  reports its current, always-disabled gate status from
  `../../../config/future_cloud_tools.json`.
- **Blender** requires the "Blender local repair/render track" (not yet
  phase-numbered - see `../../../docs/roadmap.md`) - a future local,
  non-interactive automation pass, no add-ons, no MCP.

Neither gate exists yet. No CAD, mesh, render, or generated asset exists
for this concept, no cloud/network call has been made to build this
placeholder, and no file has been uploaded anywhere.

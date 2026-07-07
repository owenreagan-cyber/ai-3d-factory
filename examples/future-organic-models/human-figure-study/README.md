# human-figure-study (roadmap placeholder - concept only)

**Not a working example. Not generated. Not printable.** See
`../README.md` for why this whole directory is concept-only.

An original, stylized, non-representational organic-form human figure
study - not a likeness of any real or copyrighted person or character
(see `../../../docs/licensing-policy.md`). No CAD source, mesh, or render
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
- **Blender** requires the full gate documented in
  `../../../docs/blender-local-track.md` (planned in Phase 21, not
  implemented) - explicit human approval, a local Blender path/version
  check, dry-run mode, output directory isolation, no overwriting
  original meshes, provenance metadata, and before/after
  validation/render. `factory check-local-tools` (read-only) reports its
  current, always-disabled gate status from
  `../../../config/future_local_tools.json`. This is the (not yet
  phase-numbered) "Blender local repair/render track" - see
  `../../../docs/roadmap.md`.

A human-figure concept specifically also falls under
`docs/meshy-approval-gate.md`'s student/privacy/data note: no photo,
name, or personal description of any real person may be sent to Meshy or
any other cloud service without a separately reviewed decision - this
concept is stylized/non-representational precisely to avoid that
question until such a policy exists.

Neither gate exists yet. No CAD, mesh, render, or generated asset exists
for this concept, no cloud/network call has been made to build this
placeholder, and no file has been uploaded anywhere.

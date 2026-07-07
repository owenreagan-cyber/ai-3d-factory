# piggy-bank-design-study (roadmap placeholder - concept only)

**Not a working example. Not generated. Not printable.** See
`../README.md` for why this whole directory is concept-only, and
`../../../docs/design-quality-standard.md` for the full standard this
concept exists to illustrate.

This is the canonical worked example from `docs/design-quality-standard.md`'s
"Piggy bank example": a reference photo of a pig turned into a **polished,
gift-worthy piggy bank** - not a single-shot "picture to blob" generation.
No CAD source, mesh, or render exists for this concept, and none will be
generated until a future Blender local-automation phase and/or a Meshy
safety/cost approval gate exist (see `../../../docs/roadmap.md`).

## The staged workflow this concept follows

```
reference image or idea
  -> style direction
  -> concept brief
  -> high-quality model path
  -> cleanup/refinement
  -> manufacturability adaptation
  -> render/preview/review
  -> human slicer review
```

## What a real brief for this concept would define

- **Style** (a real choice): cute, realistic, cartoon, anime-inspired,
  designer-toy, ceramic-style, luxury/gift, or funny/exaggerated.
- **Function**: hollow body, a coin slot, a removable plug or access
  door - a piggy bank that can't be emptied has failed its function.
- **Features**: snout, ears, eyes, legs, tail, facial expression -
  proportioned and placed intentionally.
- **Manufacturability**: wall thickness, overhangs/supports, part
  splitting, smoothing, safe edges.
- **Quality bar**: polished and gift-worthy - if it reads as blobby or
  like a rough first pass, it is not done.

This directory intentionally contains only `README.md` and
`concept_brief.json` - no `brief.json`, no `cad/`, no `stl/`, no
`renders/`, no `part_manifest.json`. `factory preview-index` /
`factory preview-project` / `factory review-gate` will each report this
directory as missing a brief if pointed at it directly; that is expected.

## Meshy/Blender approval gates

If this concept is ever implemented, the two possible future backends
each require their own separate, explicit approval before any code may
call them - see `../car-concept/README.md` for the full gate write-up
(identical requirements apply here): `../../../docs/meshy-approval-gate.md`
(Meshy, designed in Phase 16, not implemented) and
`../../../docs/blender-local-track.md` (Blender, planned in Phase 21, not
implemented). `factory check-future-tools` / `factory check-local-tools`
(both read-only) report their current, always-disabled gate status.

Neither gate exists yet. No CAD, mesh, render, or generated asset exists
for this concept, no cloud/network call has been made to build this
placeholder, and no file has been uploaded anywhere.

# chip-bag-clip-study (roadmap placeholder - concept only)

**Not a working example. Not generated. Not printable.** See
`../README.md` for why this whole directory is concept-only, and
`../../../docs/design-quality-standard.md` for the full standard this
concept exists to illustrate.

This is the canonical worked example from `docs/design-quality-standard.md`'s
functional/mechanical design track: a chip bag clip, planned with
flex/tension, material, and iteration considerations from the start -
not just "the minimum geometry that technically clips." No CAD source,
mesh, or render exists for this concept.

## What a real brief for this concept would define

- **Design style, not just function** - proportioned, finished edges, a
  considered shape, not only "the minimum geometry that technically
  clips."
- **Flex/tension planning** - geometry (thickness, hinge shape, fillet
  radii) planned for repeated flex from the start, not discovered by
  breaking prints.
- **Material choice tradeoffs** - PETG (flexible, fatigue-resistant) vs.
  TPU (very flexible, different fit) vs. PLA (rigid, prone to snapping
  under repeated flex).
- **Layer orientation** - directly affects where a flexing part is
  strong vs. where it delaminates.
- **Fatigue and failure risks** - named explicitly (where, after how
  much use, in which material).
- **Prototype test strips** - small, cheap test geometry to validate the
  flex/material choice before committing to the full part.
- **Grip force tuning** - iterating until the clip grips with the right
  amount of force.
- **Iteration loop** - expect several rounds of print-test-adjust.
- **Review before use** - a human checks the finished part before it's
  trusted for real use, every time.

## Prototype status

**Functional objects under tension or repeated stress must be treated as
prototypes until physically tested by a human.** `ai-3d-factory` may help
plan and design this concept - geometry, material tradeoffs,
orientation, iteration - but it must never claim or guarantee strength,
food safety, or durability without a human actually testing the physical
part. This concept is not `human_approved` and not `print_ready`, even
after a future prototype pass, until that physical testing happens.

This directory intentionally contains only `README.md` and
`concept_brief.json` - no `brief.json`, no `cad/`, no `stl/`, no
`renders/`, no `part_manifest.json`. `factory preview-index` /
`factory preview-project` / `factory review-gate` will each report this
directory as missing a brief if pointed at it directly; that is expected.

No CAD, mesh, render, or generated asset exists for this concept, no
cloud/network call has been made to build this placeholder, and no file
has been uploaded anywhere.

Whether a future design is CAD-authored or generated, it must satisfy
function, tension, material, and prototype-review expectations before
being considered - see `../../../docs/blender-local-track.md`'s
"Design-quality review for Blender outputs" (Phase 22) and
`../../../docs/design-quality-standard.md`'s functional/mechanical track.

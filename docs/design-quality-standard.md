# Design quality standard

**This document is planning/vision only. It does not change any
`factory` command's behavior, does not implement any generation
pipeline, and does not relax any safety gate in `AGENT.md` or
`docs/safety-gates.md`.** It exists so future phases building toward
richer custom objects (`docs/roadmap.md`'s "Rich organic examples track"
and any functional-design work) are aimed at the right bar from the
start, instead of discovering it late.

## The standard is "Etsy-worthy"

`ai-3d-factory` should help Owen create custom 3D-printable objects that
look **polished, intentional, useful, gift-worthy, display-worthy, and
potentially sellable** - not merely technically printable. "It's a
watertight mesh" is a floor, not a finish line.

This applies across the kinds of objects this repo is meant for: piggy
banks, animals, cars, people/figures, kitchen tools, clips, organizers,
gifts, classroom objects, and decorative items.

### The app should avoid

- Blocky default shapes, unless intentionally styled that way (e.g. a
  deliberately low-poly/geometric aesthetic is a style choice; an
  un-styled box standing in for an animal is not).
- Blobby image-to-3D outputs - a shape that technically resembles the
  reference photo's silhouette from one angle but reads as an
  amorphous blob from any other angle.
- Generic, unrefined meshes with no attention to proportion, symmetry,
  or surface quality.
- Random AI-generation artifacts (stray geometry, melted/smeared
  features, asymmetric errors a human wouldn't design in on purpose).
- Printable-but-ugly first drafts shipped as if they were finished
  output.
- Designs that ignore function, proportions, or manufacturability in
  favor of "it renders."

### The app should aim for

- Strong silhouette - recognizable at a glance, even in profile.
- Clear style direction - cute, realistic, cartoon, geometric, whatever
  was chosen, but *chosen*, not accidental.
- Useful function - the object does the job it's for (holds coins,
  grips a bag, organizes a drawer).
- Clean proportions - parts relate to each other the way a human
  designer would size them, not whatever a generator happened to output.
- Polished details - the small touches (a facial expression, a
  chamfered edge, a consistent wall thickness) that separate "made this"
  from "generated this."
- Manufacturable geometry - prints cleanly on the target printer, with
  reasonable supports, orientation, and wall thickness.
- Material-aware design - the design accounts for what the chosen
  material can actually do (flex, rigidity, layer strength, food
  contact, heat).
- Previewable/reviewable outputs - a human can look at renders/previews
  and actually evaluate quality before committing to a print.
- Iteration toward quality - a first pass is a draft, not a deliverable;
  the workflow expects refinement passes.

## Two design tracks

### 1. Artistic / organic custom design track

Examples: a pig photo turned into a polished piggy bank, an animal
figurine, a car concept, a person/character/bust study, a decorative
mascot, a toy-like object, a display model.

**Important: the goal is not "picture to pig blob."** A single-shot
image-to-mesh pass that vaguely resembles the input is not the bar. The
goal is a staged design workflow:

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

Each arrow is a real step with a real decision in it, not a formality -
skipping straight from "reference image" to "STL" is exactly the
blob-generation failure mode this standard exists to rule out.

#### Piggy bank example, worked through the standard

- **Style** (a real choice, recorded in the brief, not defaulted):
  cute, realistic, cartoon, anime-inspired, designer-toy, ceramic-style,
  luxury/gift, or funny/exaggerated.
- **Function**: hollow body (so it can hold coins), a coin slot sized
  and placed sensibly, a removable plug or access door (so it can be
  emptied) - a piggy bank that can't be emptied has failed its function
  regardless of how it looks.
- **Features**: snout, ears, eyes, legs, tail, facial expression -
  proportioned and placed the way an intentional design would, not
  scattered wherever the source geometry happened to have bumps.
- **Manufacturability**: wall thickness (thick enough to be sturdy,
  thin enough to be reasonable), overhangs and supports, part splitting
  (if the design is cleaner as multiple aligned parts - see
  `docs/slicer-review-workflow.md`), smoothing, and safe edges (no sharp
  points a kid could be hurt on, if this is a classroom/gift context).
- **Quality bar**: polished and gift-worthy. If it reads as "blobby" or
  "a rough first pass," it is not done - it goes back through
  cleanup/refinement, not straight to `slicer_review_ready`.

### 2. Functional / mechanical custom design track

Examples: a chip bag clip, a kitchen utensil, a storage part, a drawer
divider, a bracket, a hinge/flexure part, a classroom tool, an organizer.

#### Chip clip example, worked through the standard

- **Design style, not just function.** Even a purely functional object
  should look designed - proportioned, finished edges, a considered
  shape - not just "the minimum geometry that technically clips."
- **Flex/tension planning.** A clip has to flex repeatedly without
  cracking - geometry (thickness, hinge shape, fillet radii) has to be
  planned for that from the start, not discovered by breaking prints.
- **Material choice tradeoffs** - e.g. PETG (more flexible, more
  fatigue-resistant) vs. TPU (very flexible, different fit/print
  behavior) vs. PLA (rigid, cheap, but prone to snapping under repeated
  flex) - a real tradeoff decision, recorded, not a default.
- **Layer orientation** - print orientation directly affects where a
  flexing part is strong vs. where it delaminates; this has to be
  planned, not left to slicer defaults.
- **Fatigue and failure risks** - named explicitly (where it's likely to
  crack, after roughly how much use, in which material) rather than
  implied by silence.
- **Prototype test strips** - small, cheap printable test geometry (a
  single flex tab, not the whole clip) to validate the flex/material
  choice before committing to the full part.
- **Grip force tuning** - iterating on geometry until the clip grips
  with the right amount of force (not so loose it's useless, not so
  tight it snaps or won't fit the bag).
- **Iteration loop** - expect several rounds of print-test-adjust, same
  spirit as the artistic track's cleanup/refinement step.
- **Review before use** - a human checks the finished part before it's
  trusted for real use, every time.

**Important: functional objects under tension or repeated stress must be
treated as prototypes until physically tested.** `ai-3d-factory` may help
plan and design them - geometry, material tradeoffs, orientation,
iteration - but it must never claim or guarantee strength, food safety,
or durability without a human actually testing the physical part. This is
the same spirit as `AGENT.md`'s "Never claim a model is print-ready just
because a mesh is watertight" - "the geometry is sound" is not "the part
is safe to trust."

## The core principle

**`ai-3d-factory` should not optimize only for "can it generate a
printable mesh?"** It should optimize for **"can it help Owen develop a
custom, polished, useful, and visually intentional object that is safe to
review and manufacture locally?"**

A mesh that passes `factory validate` (watertight, manifold, reasonable
dimensions) has cleared a geometry sanity check - it has not cleared this
standard. Nothing in this document changes what any `factory` command
actually does today: the highest status any command sets automatically is
still `slicer_review_ready` (see `config/agent_policy.json`), human slicer
review is still required, and `human_approved`/`print_ready` still require
an explicit human decision, exactly as documented everywhere else in this
repo. This standard is about what "good" means once real generation
pipelines exist (`docs/meshy-approval-gate.md`'s and
`docs/blender-local-track.md`'s future tracks) - it is a bar to build
toward, not a feature being shipped today.

See also `docs/roadmap.md`'s "Custom Design Quality Pipeline" and "Rich
organic examples track", `docs/product-vision.md`, `docs/tool-routing.md`,
`docs/meshy-approval-gate.md`, `docs/blender-local-track.md`,
`docs/slicer-review-workflow.md`, and `AGENT.md`.

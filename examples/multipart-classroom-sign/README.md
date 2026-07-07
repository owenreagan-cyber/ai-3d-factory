# multipart-classroom-sign

A committed, permanent local example of the `ai-3d-factory` **multi-part**
assembly workflow: a classroom sign with a base plate, a separately-colored
raised room-number text layer, and a small accent badge/icon, all sharing
one origin per `docs/slicer-review-workflow.md`. This is a **real working
example** (not a roadmap/concept placeholder like
`../future-organic-models/`), and is meant as a baseline pattern for
richer future multi-part models (cars, animals, people, classroom/
manufacturing demos) to build on.

## Why hand-authored, not `factory generate-openscad`

`factory generate-openscad --template multipart-nameplate` already
generates a 2-part base+text pair (`factory/openscad/templates.py`), but
no built-in template covers a 3-part assembly with an additional icon/
badge accent. Rather than force this example into the 2-part template,
`cad/base.scad`, `cad/text_layer.scad`, and `cad/badge.scad` are
hand-authored, following the exact same shared-origin convention the
built-in `multipart-nameplate` template already uses (same
`plate_width`/`plate_depth`/`plate_height` parameters across all three
files, same `(0,0,0)` origin, no re-centering). `cad/README.md` and
`slicer_review/openscad_export_instructions.md` document this the same
way generated projects do.

`base.scad` also has 4 optional corner mounting holes (set
`mounting_hole_diameter = 0` to omit them) - a stand-in for the
"mounting hole markers" a real classroom/manufacturing sign might need.

## How this example was built

```bash
# cad/base.scad, cad/text_layer.scad, cad/badge.scad, brief.json,
# part_manifest.json, slicer_review/openscad_export_instructions.md were
# written by hand (no generator covers this 3-part shape yet), then:
factory preview-project examples/multipart-classroom-sign
```

Each `.scad` file's syntax was checked locally with the OpenSCAD binary
already installed on this machine (`openscad -o <tmp>.stl cad/<name>.scad`,
run against a scratch path outside this repo, for each of the three
files) to confirm each exports a single, valid solid. That check's output
was not committed - see "Current state" below.

## Current state

- Status: `cad_generated`. **No STL has been exported for any part.**
- `part_manifest.json` lists 3 parts (`base_plate`, `sign_text`,
  `accent_badge` - the badge is marked `required_for_assembly: false`,
  since it's an optional accent), each with `shared_origin: true` and
  matching `transform_notes`.
- `factory preview-index` / `factory preview-project`: report 3 missing
  visual artifacts (one per part - none of the three STLs exist yet) and
  correctly detect `multi_part: true`.
- `factory review-gate examples/multipart-classroom-sign`: **fails** ("No
  STL files exist yet"). Expected and correct - like the other working
  examples, this one intentionally stops at the CAD-source stage.

## Continuing this example locally (optional, not done automatically)

```bash
openscad -o examples/multipart-classroom-sign/stl/base.stl examples/multipart-classroom-sign/cad/base.scad
openscad -o examples/multipart-classroom-sign/stl/text_layer.stl examples/multipart-classroom-sign/cad/text_layer.scad
openscad -o examples/multipart-classroom-sign/stl/badge.stl examples/multipart-classroom-sign/cad/badge.scad
factory validate examples/multipart-classroom-sign/stl/base.stl
factory validate examples/multipart-classroom-sign/stl/text_layer.stl
factory validate examples/multipart-classroom-sign/stl/badge.stl
factory render examples/multipart-classroom-sign/stl/base.stl
factory render examples/multipart-classroom-sign/stl/text_layer.stl
factory render examples/multipart-classroom-sign/stl/badge.stl
factory preview-project examples/multipart-classroom-sign
factory review-gate examples/multipart-classroom-sign
```

This can locally advance the example to `slicer_review_ready` - it still
never becomes `human_approved` or `print_ready` automatically. See
`../../docs/examples-library.md`.

## Safety

- No Meshy, no OpenAI/Claude/Gemini/paid API calls, no uploads, no printer
  or slicer automation were used to build this example.
- No `human_approved` or `print_ready` field appears anywhere in this
  example, and nothing here claims this sign is ready to print.
- No STL or PNG file is committed anywhere in this example.

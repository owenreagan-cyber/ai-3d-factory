# mechanical-plate

A committed, permanent local example of the `ai-3d-factory` workflow: a
rectangular mounting plate with rounded corners and 4 corner mounting
holes. This is a **real workflow example** (not a roadmap/concept
placeholder like `../future-organic-models/`).

## Why OpenSCAD instead of CadQuery here

`factory generate-cadquery --template mechanical-plate` already has a
CadQuery template with this exact shape (`factory/cad/cadquery_backend.py`)
- but CadQuery is an optional dependency this repo never installs, and it
is not installed in the environment this example was built in. Rather than
skip a mechanical-plate example, `cad/mechanical_plate.scad` is a
hand-authored OpenSCAD file with the same parameter names
(`length_mm`, `width_mm`, `thickness_mm`, `corner_radius_mm`,
`hole_diameter_mm`, `hole_margin_mm`) so it's easy to compare the two
backends. This repo's `cad/README.md` files already document that
`.scad`/`.py` source is meant to be human-editable directly, not only
generator output - see `docs/cad-backends.md`.

Its syntax was checked locally with the OpenSCAD binary already installed
on this machine (`openscad -o <tmp>.stl cad/mechanical_plate.scad`, run
against a scratch path outside this repo) to confirm it exports a single,
manifold solid. That check's output was not committed - see "Current
state" below.

## Current state

- Status: `cad_generated`. **No STL has been exported.**
- `factory preview-index` / `factory preview-project`: report one missing
  visual artifact (`stl/mechanical_plate.stl` doesn't exist yet).
- `factory review-gate examples/mechanical-plate`: **fails** ("No STL
  files exist yet"). Expected and correct - this example intentionally
  stops at the CAD-source stage.

## Continuing this example locally (optional, not done automatically)

```bash
openscad -o examples/mechanical-plate/stl/mechanical_plate.stl examples/mechanical-plate/cad/mechanical_plate.scad
factory validate examples/mechanical-plate/stl/mechanical_plate.stl
factory render examples/mechanical-plate/stl/mechanical_plate.stl
factory preview-project examples/mechanical-plate
factory review-gate examples/mechanical-plate
```

If you have CadQuery installed, you can instead compare the other backend
directly (writes a second, independent CAD source file - does not replace
`mechanical_plate.scad`):

```bash
factory generate-cadquery examples/mechanical-plate --template mechanical-plate \
  --length-mm 80 --width-mm 50 --thickness-mm 5 --corner-radius-mm 4 \
  --hole-diameter-mm 4 --hole-margin-mm 8
```

None of this happens automatically, and none of it touches a network,
cloud API, printer, or slicer. See `../../docs/examples-library.md` and
`../../docs/cad-backends.md`.

## Safety

- No Meshy, no OpenAI/Claude/Gemini/paid API calls, no uploads, no printer
  or slicer automation were used to build this example.
- No `human_approved` or `print_ready` field appears anywhere in this
  example, and nothing here claims this part is ready to print.

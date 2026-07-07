# OpenSCAD export instructions

This file lists the local commands to export each hand-authored `.scad`
file in this example to its own STL. **Nothing in this repo runs these
commands automatically.** Run them yourself, in a terminal, only after
you've reviewed the `.scad` source. This requires OpenSCAD to be installed
locally (see ai-3d-factory-installer).

```bash
openscad -o stl/base.stl cad/base.scad
openscad -o stl/text_layer.stl cad/text_layer.scad
openscad -o stl/badge.stl cad/badge.scad
```

All three parts share the same `(0,0,0)` origin - export each one without
re-centering, then import all three STLs into Bambu Studio/OrcaSlicer as
one object with multiple parts (see
`../../../docs/slicer-review-workflow.md`).

After exporting, run `factory validate stl/<name>.stl` and `factory render
stl/<name>.stl` on each exported file, then update `part_manifest.json`
with the real material/color choices before requesting human slicer
review.

This repo never slices, prints, or uploads anything - exporting to STL is
the last step this documentation covers.

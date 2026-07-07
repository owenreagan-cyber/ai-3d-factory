# OpenSCAD export instructions

This file lists the local command to export the hand-authored `.scad` file
in this example to an STL. **Nothing in this repo runs this command
automatically.** Run it yourself, in a terminal, only after you've
reviewed the `.scad` source. This requires OpenSCAD to be installed
locally (see ai-3d-factory-installer).

```bash
openscad -o stl/mechanical_plate.stl cad/mechanical_plate.scad
```

After exporting, run `factory validate stl/mechanical_plate.stl` and
`factory render stl/mechanical_plate.stl`, then update `part_manifest.json`
with the real material/color choices before requesting human slicer
review. See `docs/slicer-review-workflow.md`.

This repo never slices, prints, or uploads anything - exporting to STL is
the last step this documentation covers.

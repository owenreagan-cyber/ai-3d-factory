# OpenSCAD export instructions

This file lists the local commands to export each generated .scad file to an STL.
**Nothing in this repo runs these commands automatically.** Run them yourself, in a
terminal, only after you've reviewed the .scad source. This requires OpenSCAD to be
installed locally (see ai-3d-factory-installer).

```bash
openscad -o stl/nameplate.stl cad/nameplate.scad
```

After exporting, run `factory validate stl/<name>.stl` and `factory render stl/<name>.stl` on each exported file, then update `part_manifest.json` with the real material/color choices before requesting human slicer review. See `docs/slicer-review-workflow.md`.

This repo never slices, prints, or uploads anything - exporting to STL is the last step this documentation covers.

# cad/

Hand-authored OpenSCAD source: `mechanical_plate.scad` - a rectangular
mounting plate with rounded corners and 4 corner mounting holes. Not
written by `factory generate-openscad` (no built-in template covers this
shape yet - see `docs/cad-backends.md`); parameter names mirror `factory
generate-cadquery --template mechanical-plate` so the two backends stay
easy to compare.

This is a plain, human-editable OpenSCAD (`.scad`) file - feel free to
open and adjust the parameters at the top. After editing, re-export to STL
and re-run `factory validate` / `factory render` before treating the part
as done.

This repo does not run OpenSCAD automatically. See
`../slicer_review/openscad_export_instructions.md` for the exact export
command.

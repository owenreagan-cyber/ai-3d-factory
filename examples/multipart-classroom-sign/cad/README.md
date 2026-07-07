# cad/

Hand-authored OpenSCAD source for a 3-part assembly: `base.scad` (base
plate with optional corner mounting holes), `text_layer.scad` (raised
room-number text), and `badge.scad` (a small raised accent badge/icon).
Not written by `factory generate-openscad` - no built-in template covers a
3-part sign with an icon/badge accent yet (the built-in
`multipart-nameplate` template only covers a base + text pair - see
`docs/cad-backends.md` and `factory/openscad/templates.py`).

All three files share the same `plate_width`/`plate_depth`/`plate_height`
parameters and the same `(0,0,0)` origin - each part is meant to be
exported and imported into the slicer independently, without re-centering
any of them, exactly like the built-in `multipart-nameplate` template's
`nameplate_base.scad`/`nameplate_text.scad` pair. See
`../../../docs/slicer-review-workflow.md`.

These are plain, human-editable OpenSCAD (`.scad`) files - feel free to
open and adjust the parameters at the top of each. After editing,
re-export to STL and re-run `factory validate` / `factory render` before
treating any part as done.

This repo does not run OpenSCAD automatically. See
`../slicer_review/openscad_export_instructions.md` for the exact export
commands.

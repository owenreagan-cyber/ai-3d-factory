# cad/

Hand-authored OpenSCAD source for a 3-part assembly: `lid_panel.scad` (the
main lid panel, with a downward-facing friction-fit lip inset from the
outer edge), `raised_label.scad` (raised label text), and `pull_tab.scad`
(a small raised grip tab along the front edge). Not written by `factory
generate-openscad` - no built-in template covers a bin-lid shape yet (the
built-in templates are test-cube/nameplate/sign/multipart-nameplate - see
`docs/cad-backends.md` and `factory/openscad/templates.py`).

All three files share the same `lid_width`/`lid_depth`/`lid_height`
parameters and the same `(0,0,0)` origin - each part is meant to be
exported and imported into the slicer independently, without re-centering
any of them, exactly like the built-in `multipart-nameplate` template's
`nameplate_base.scad`/`nameplate_text.scad` pair and
`examples/multipart-classroom-sign/`'s `base.scad`/`text_layer.scad`/
`badge.scad`. See `../../../docs/slicer-review-workflow.md`.

These are plain, human-editable OpenSCAD (`.scad`) files - feel free to
open and adjust the parameters at the top of each. After editing,
re-export to STL and re-run `factory validate` / `factory render` before
treating any part as done.

This repo does not run OpenSCAD automatically. See
`../slicer_review/openscad_export_instructions.md` for the exact export
commands.

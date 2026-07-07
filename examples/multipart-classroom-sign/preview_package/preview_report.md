# Preview report: multipart-classroom-sign-example

Generated: 2026-07-07T20:22:00.462051+00:00
Project status: `cad_generated`
Target printer: (not planned yet)
Selected manufacturing option: None

## Visual artifacts

- CAD source files (3):
  - `cad/badge.scad`
  - `cad/base.scad`
  - `cad/text_layer.scad`
- Mesh/STL files (0):
  - (none)
- Render/preview images (0):
  - (none)

## Manifest parts

- **base_plate** - role: base_plate, material: TBD - human decision, color: TBD - base color, file: `stl/base.stl`
- **sign_text** - role: raised_letters, material: TBD - human decision, color: TBD - contrasting text color, file: `stl/text_layer.stl`
- **accent_badge** - role: accent_badge, material: TBD - human decision, color: TBD - accent/badge color, file: `stl/badge.stl`

Multipart state: multi_part=True, part_count=3

## Render coverage

Meshes with a matching render: 0/0 (all meshes have a render: False; visually complete for human slicer review: False)

This is advisory only - see `factory render-coverage <project_dir>` for the full per-mesh breakdown and `factory plan-renders <project_dir>` for suggested local commands.

## Missing visual artifacts

- Missing STL for part 'base_plate' (expected stl/base.stl).
- Missing STL for part 'sign_text' (expected stl/text_layer.stl).
- Missing STL for part 'accent_badge' (expected stl/badge.stl).

## Stale previews

- None detected.

## Human visual inspection checklist

This checklist is advisory only - checking these boxes does not approve, validate, or
advance this project's status. A human must look at the actual renders/STLs.

- [ ] Does the preview match the intended object?
- [ ] Are all expected parts visible?
- [ ] Are text/labels readable?
- [ ] Are multipart components visually distinct?
- [ ] Are colors/materials represented or clearly marked unknown?
- [ ] Are any renders missing?
- [ ] Are any previews stale?
- [ ] Is slicer review still required?

---

Human visual inspection required.
Human slicer review required.
Project is NOT print-ready.

# OpenSCAD generation (Phase 2)

`factory generate-openscad` writes local, parametric OpenSCAD (`.scad`)
source files into an already-initialized project's `cad/` directory. It is
a deterministic template system — no AI call, no network, no OpenSCAD
invocation. See `AGENT.md` and `docs/safety-gates.md` for the safety rules
this command follows.

## Usage

```bash
factory init-project my-part          # if not already created
factory generate-openscad projects/my-part --template test-cube
factory generate-openscad projects/my-part --template nameplate --text "MR REAGAN"
factory generate-openscad projects/my-part --template sign --text "READ"
factory generate-openscad projects/my-part --template multipart-nameplate --text "MR REAGAN"
```

Pass `--force` to overwrite `.scad` files from a previous run of the same
template; without it, the command refuses to overwrite anything and exits
non-zero.

## Templates

| Template | Files written | Output |
|---|---|---|
| `test-cube` | `test_cube.scad` | 20mm calibration cube with a corner orientation notch. |
| `nameplate` | `nameplate.scad` | Single-color raised-text nameplate (base + text fused). |
| `sign` | `sign.scad` | Single-color rectangular sign/plate with raised text. |
| `multipart-nameplate` | `nameplate_base.scad`, `nameplate_text.scad` | Two-part, multi-color nameplate: base plate and raised letters as separate files sharing one origin. |

`nameplate`, `sign`, and `multipart-nameplate` require `--text`; `test-cube`
does not take one.

All generated files are plain OpenSCAD: parameters are named variables at
the top of the file with comments, dimensions are explicit and in
millimeters, and no external library (e.g. BOSL2) is required. Feel free
to open and hand-edit a generated file — re-export and re-validate
afterward.

## What else the command does

Beyond writing `.scad` files, each run:

- (Re)writes `cad/README.md` noting what was last generated.
- Regenerates `slicer_review/openscad_export_instructions.md` by scanning
  every `.scad` file currently in `cad/`, so it always reflects the
  project's current CAD source — not just the most recent template run.
- Upserts matching entries into `part_manifest.json` (by `part_name`):
  `file_path` (the STL path the export instructions point to),
  `export_units: "mm"`, `source`/`license: "original"`, `role`,
  `transform_notes`, and a `cad_source` pointer back to the `.scad` file.
  Material/color are left as `"TBD"`-style placeholders for `multipart-nameplate`
  since color choice is a human decision the plan is deferring to.
- Advances the project's `brief.json` status to `cad_generated` — but only
  forward; it never regresses a project that's already further along, and
  it never sets `human_approved` or `print_ready`.

## What it does not do

- **This command itself** does not invoke OpenSCAD — exporting to STL from
  `factory generate-openscad` is still a manual step, run the commands
  written to `slicer_review/openscad_export_instructions.md` yourself,
  once you've reviewed the generated source. A separate, opt-in command,
  `factory export-from-cad --confirm-export` (Phase 35, see
  `docs/export-pipeline.md`), *can* invoke a local `openscad` executable
  for you — dry run by default, only with explicit confirmation, and only
  if the executable is found; it never replaces the instructions file
  above and never runs automatically as part of generation.
- It does not call `factory validate` or `factory render` for you. Do that
  after exporting (`factory export-from-cad --validate --render`, or
  those two commands directly), per the instructions file.
- It does not fuse `multipart-nameplate`'s two files into one STL. Keep
  them as separate aligned exports for per-part color assignment in the
  slicer — see `docs/slicer-review-workflow.md`.
- It never marks anything `slicer_review_ready`, `human_approved`, or
  `print_ready`. Those still require running `factory validate` /
  `factory render` (for the former) and explicit human sign-off (for the
  latter two).

## Multi-part alignment

`multipart-nameplate` generates `nameplate_base.scad` and
`nameplate_text.scad` as independent files that both model their geometry
from the same `(0, 0, 0)` corner, using identical `plate_width` /
`plate_depth` / `plate_height` values duplicated at the top of each file
(OpenSCAD has no shared-header mechanism across independently-exported
files without extra tooling, so keep these values in sync by hand if you
edit them). When you export both to STL and import them into Bambu
Studio/OrcaSlicer as separate parts, do not re-center either one — their
shared origin is what keeps them aligned. `part_manifest.json` records
this in each part's `transform_notes`.

## Automated export (Phase 35)

The "optional, explicit, locally-validated export command" this section
used to describe as a future candidate is now implemented — see
`factory export-from-cad` in `docs/export-pipeline.md`. It orchestrates
the existing OpenSCAD CLI (never re-implementing generation or export),
is dry-run by default, and only invokes a subprocess with explicit
`--confirm-export` and a detected local executable.

## Future: BOSL2

BOSL2 (a popular OpenSCAD utility library) remains a candidate for a
later phase — see `docs/roadmap.md`. Plain OpenSCAD (no external library)
is still intentionally sufficient for every template this repo generates
today.

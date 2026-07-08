# Visual preview package (Phase 6)

A project-level, human-readable (and machine-readable) summary of a
project's existing visual artifacts - CAD source, exported meshes, render
images, and manifest parts - aggregated for a human to visually
sanity-check before slicer review, and for a future dashboard/launcher (see
`docs/product-vision.md`) to consume without re-deriving this itself.

**This is not a new rendering pipeline.** `factory render` (Phase 0/1)
already produces the actual preview PNGs, one mesh at a time. The preview
package never renders a new image, invokes OpenSCAD, exports an STL, or
contacts a printer/slicer/network - it only reads files already on disk
(`cad/*.scad`, `stl/*.stl`, `renders/*.png`, `brief.json`, `build_plan.json`,
`part_manifest.json`) and writes a summary of what it found. See
`factory.preview_package`.

## Files

```
projects/<slug>/preview_package/
├── index.json          # machine-readable summary (for a future dashboard/launcher)
└── preview_report.md   # human-readable summary + inspection checklist
```

`index.json` references existing files by relative path (e.g.
`"renders/nameplate_base_preview.png"`) - it never copies a render image
into `preview_package/`. There is exactly one render image on disk per
mesh, same as before this phase.

## Commands

- **`factory preview-index <project_dir>`** - read-only. Prints the same
  summary information to the console without writing anything.
  Use this to check a project's visual-artifact state without
  building/refreshing the package file.
- **`factory preview-project <project_dir>`** - builds/refreshes
  `preview_package/index.json` and `preview_package/preview_report.md` from
  whatever `cad/`, `stl/`, `renders/`, and `part_manifest.json` currently
  contain. Safe to re-run at any time; it always reflects current disk
  state, never a stale cache from a prior run.

Both commands work on any project directory, including ones created before
Phase 6 - `preview_package/` is created on demand (via the same
`mkdir(parents=True)` pattern `project_store.save_json` already uses
elsewhere), not scaffolded by `factory init-project`.

## What the index/report contain

- Project name, status, target printer, selected manufacturing option (from
  `brief.json`/`build_plan.json`).
- CAD source files (`cad/*.scad`), mesh files (`stl/*.stl`), render images
  (`renders/*.png`) - counted and listed by relative path.
- Manifest parts (name, role, material, color, file path) and multipart
  state (`multi_part`, `part_count`).
- **Missing visual artifacts**: a required part with no STL yet, or an STL
  with no corresponding render yet (matched by the same
  `<stem>_preview.png` naming convention `factory render` already uses).
- **Stale previews**: a render whose file is older than the STL it was
  rendered from (by file mtime) - a signal that the mesh changed after the
  last `factory render` run, so the image on disk may not reflect the
  current geometry.
- **Orphaned renders**: a render image whose corresponding STL no longer
  exists (e.g. after a rename) - noted for awareness, never deleted.
- **Render coverage** (Phase 9, see `docs/render-coverage.md`):
  `render_coverage` (the full `factory.render_coverage.compute_render_coverage()`
  output - per-mesh coverage, missing/stale/orphan renders, and the two
  summary flags below), plus top-level convenience copies `missing_renders`
  and `all_meshes_have_renders`. `preview_report.md` gets a matching
  "Render coverage" section. These are additive fields - every field that
  existed before Phase 9 is unchanged.
- A static **human visual inspection checklist** (see below).

## Render preview vs. visual approval

`factory render` produces a single mesh's preview PNG - a mechanical,
deterministic operation. **Looking at that PNG and deciding it looks right
is a separate, human act** that this repo never automates:

- The preview package's checklist is advisory text only - checking a box
  in `preview_report.md` (it's a plain Markdown `- [ ]`, not a form) does
  not change any file, status, or field. Nothing in `factory` reads or acts
  on checked/unchecked boxes.
- Building or refreshing the preview package never advances a project's
  status, and never sets `human_approved` or `print_ready` - see
  `docs/safety-gates.md`.
- Every `preview-index`/`preview-project` run ends with all three of:
  "Human visual inspection required.", "Human slicer review required.",
  "Project is NOT print-ready."

### Previews prove presence, not quality

`preview_package/index.json` and `preview_report.md` can tell a human
*that* a CAD file, mesh, or render exists and is fresh - they cannot tell
anyone whether the design itself is any good. A project can have a
complete, fresh preview package and still be a rough first draft that
hasn't been checked against `docs/design-quality-standard.md`'s
"Etsy-worthy" standard. The human visual inspection this package sets up
for should actually apply that standard - and, once a project reaches
`slicer_review_ready`, the fuller checklist in `docs/review-gate.md`'s
"Human review quality checklist" - not stop at "the files are all
present."

## How a future dashboard/launcher would use this

`preview_package/index.json` is intentionally the machine-readable half of
this package - stable field names, relative file paths, and pre-computed
missing/stale lists - so a future visual dashboard (see
`docs/product-vision.md`'s "Planning board"/"Multipart-exploded preview"
requirements) can render it directly instead of re-implementing this
file-scanning and staleness logic itself. No UI reads or writes it today;
this phase only produces the data.

## Safety

Both commands are covered by the same boundaries as every other `factory`
command: no printer/slicer contact, no network, no cloud upload, no
automatic `human_approved`/`print_ready`, and the project status ceiling
remains `slicer_review_ready`. See `AGENT.md` and `docs/safety-gates.md`.

See also `docs/design-quality-standard.md` (the "Etsy-worthy" standard
human visual inspection should apply) and `docs/review-gate.md`'s "Human
review quality checklist" (Phase 23).

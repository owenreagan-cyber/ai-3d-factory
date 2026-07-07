# Local render coverage inspection (Phase 9)

`factory render-coverage <project_dir>` compares a project's `stl/*.stl`
files against its `renders/*.png` files and reports which meshes have a
matching preview render, which don't, and which render files are orphaned
(no matching STL currently on disk). It's a local, read-only trust check -
a way to see exactly what's missing before treating a project as ready for
human slicer review, especially for projects with several parts.

## What this is not

- **Not a renderer.** It never calls `factory render` for you, never
  invokes OpenSCAD/CadQuery/Blender, and produces no images itself.
- **Not connected to a printer or slicer.** It never discovers, contacts,
  or sends anything to a printer or slicer.
- **Not an approval mechanism.** Render coverage is advisory. It never
  sets `human_approved` or `print_ready`, and the highest status any
  `factory` command can set automatically remains `slicer_review_ready`.

## Usage

```bash
factory render-coverage projects/my-part           # human-readable report
factory render-coverage projects/my-part --json     # machine-readable JSON
factory plan-renders projects/my-part               # suggested `factory render` commands - lists only, runs nothing
```

## What it checks

For a project directory, using the same `<mesh_stem>_preview.png` naming
convention `factory.preview_package` and `factory render` already use:

- STL files present (`stl/*.stl`).
- Render PNG files present (`renders/*.png`).
- Which STL files have a matching, up-to-date render (`covered`).
- Which STL files are missing a render entirely (`missing_renders`).
- Which renders are older than the mesh they're supposed to preview
  (`stale_renders`) - same mtime comparison `preview_package` uses.
- Which render files have no matching STL currently on disk
  (`orphan_renders`) - kept for reference, never deleted, never treated as
  blocking by itself.
- `all_meshes_have_renders`: every mesh has *some* render, ignoring
  staleness.
- `visually_complete_for_slicer_review`: every mesh has a render **and**
  none are stale. This is the practical "done" signal - still advisory,
  still not an approval.

This is a pure filesystem read (`Path.glob` + `Path.stat`) - nothing here
generates geometry, renders an image, or contacts a slicer/printer/network.
It never writes a file, so it's also fully deterministic: calling it twice
in a row with unchanged files on disk returns an identical result.

## `factory plan-renders` - suggestions only, never runs anything

`factory plan-renders <project_dir>` lists the `factory render <stl_path>`
commands a human could run to fix missing/stale coverage - and nothing
else. It never executes those commands, never batch-renders, and never
launches any external tool. Copy/paste (or manually type) the ones you
want to run yourself.

## Integration with `factory preview-project` / `preview_package/index.json`

`factory.preview_package.gather_preview_data()` now calls
`factory.render_coverage.compute_render_coverage()` internally (reused,
not reimplemented) and adds three new fields to
`preview_package/index.json`, additive and fully backward-compatible with
every field that existed before this phase:

- `render_coverage` - the full nested object described above.
- `missing_renders` - convenience top-level copy of
  `render_coverage["missing_renders"]`.
- `all_meshes_have_renders` - convenience top-level copy of the same flag.

The existing `missing_visual_artifacts`, `stale_previews`, and
`orphaned_renders` fields are unchanged - they remain
`preview_package`'s own richer, manifest-aware view (it matches a
manifest part's `file_path` directly, which can in principle live outside
`stl/`), while `render_coverage` is `render_coverage`'s simpler,
directory-only view. In the common case (parts' files live under `stl/`,
one STL per part) the two agree; `preview_package`'s human-readable
report (`preview_report.md`) now includes a "Render coverage" section
summarizing the same numbers.

## Integration with `factory preview-board`

Each project card in `factory preview-board`'s output (`preview_board/
index.json` and `index.html`) includes a `render_coverage` field with the
same shape, always freshly computed (not read from a possibly-stale
cached `preview_package/index.json`, so it's correct even before you've
run `factory preview-project`). The board's visual-readiness
classification is conservative and unchanged in spirit, refined for
render coverage specifically:

- Any mesh missing a render (all of them, or just one of several) ->
  `needs_render`.
- All meshes have *some* render, but one is stale, or `preview_package`'s
  own manifest-aware check flags something -> `blocked_or_incomplete`.
- All meshes have a fresh render and nothing else is flagged ->
  `slicer_review_ready`.
- An orphan render never blocks by itself - it's surfaced as an advisory
  warning on the project's card, not a state change.

`human_approved`/`print_ready` are never computed or implied here either.

## JSON shape

```jsonc
{
  "project_dir": "projects/my-part",
  "mesh_files": ["stl/a.stl", "stl/b.stl"],
  "render_files": ["renders/a_preview.png"],
  "covered": [
    {"mesh": "stl/a.stl", "render": "renders/a_preview.png", "stale": false}
  ],
  "missing_renders": ["stl/b.stl"],
  "orphan_renders": [],
  "stale_renders": [],
  "total_meshes": 2,
  "total_renders": 1,
  "covered_count": 1,
  "all_meshes_have_renders": false,
  "visually_complete_for_slicer_review": false,
  "notes": ["..."]
}
```

See also `docs/visual-preview-package.md` (per-project preview package)
and `docs/preview-board.md` (multi-project board), and `docs/roadmap.md`
Phase 9.

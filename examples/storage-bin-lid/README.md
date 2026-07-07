# storage-bin-lid

A committed, permanent local example of the `ai-3d-factory` **multi-part**
assembly workflow: a labeled storage-bin/classroom-supply-bin lid with a
friction-fit lip, a separately-colored raised label, and a raised pull
tab, all sharing one origin per `docs/slicer-review-workflow.md`. This is
a **real working example** (not a roadmap/concept placeholder like
`../future-organic-models/`), and is meant as a **practical household/
classroom utility baseline** - the kind of everyday object (a bin, a
storage container, a labeled organizer part) the library should grow
toward, alongside `../multipart-classroom-sign/`.

## What this demonstrates

- **`cad/lid_panel.scad`** - the main lid: a rounded-rectangle panel with
  a downward-facing friction-fit lip inset from the outer edge, sized to
  sit inside a storage bin's top opening (like a picture frame's backing
  ring, not a solid plug).
- **`cad/raised_label.scad`** - raised label text (`"CRAYONS"` as a
  placeholder - change `label_text` for your own bin), meant as its own
  separately-colored part.
- **`cad/pull_tab.scad`** - a small raised tab along the front edge, for
  gripping the lid to lift it off.

## Why hand-authored, not `factory generate-openscad`

No built-in template covers a bin-lid shape (the built-in templates are
`test-cube`/`nameplate`/`sign`/`multipart-nameplate` - see
`docs/cad-backends.md`). All three files use the exact same shared-origin
convention the built-in `multipart-nameplate` template and
`../multipart-classroom-sign/` already use: matching
`lid_width`/`lid_depth`/`lid_height` parameters across all three files,
same `(0,0,0)` origin, no re-centering.

## How this example was built

```bash
# cad/lid_panel.scad, cad/raised_label.scad, cad/pull_tab.scad, brief.json,
# part_manifest.json, slicer_review/openscad_export_instructions.md were
# written by hand (no generator covers this shape yet), then:
factory preview-project examples/storage-bin-lid
```

Each `.scad` file's syntax was checked locally with the OpenSCAD binary
already installed on this machine (`openscad -o <tmp>.stl cad/<name>.scad`,
run against a scratch path outside this repo, for each of the three
files) to confirm each exports a valid solid. That check's output was not
committed - see "Current state" below.

## Current state

- Status: `cad_generated`. **No STL has been exported for any part.**
- `part_manifest.json` lists 3 parts (`lid_panel` required for assembly;
  `raised_label_text` and `pull_tab` marked `required_for_assembly: false`
  as optional enhancements), each with `shared_origin: true` and matching
  `transform_notes`.
- `factory preview-index` / `factory preview-project`: report 3 missing
  visual artifacts (one per part - none of the three STLs exist yet) and
  correctly detect `multi_part: true`.
- `factory review-gate examples/storage-bin-lid`: **fails** ("No STL
  files exist yet"). Expected and correct - like every other working
  example in this library, this one intentionally stops at the
  CAD-source stage.

## Continuing this example locally (optional, not done automatically)

```bash
openscad -o examples/storage-bin-lid/stl/lid_panel.stl examples/storage-bin-lid/cad/lid_panel.scad
openscad -o examples/storage-bin-lid/stl/raised_label.stl examples/storage-bin-lid/cad/raised_label.scad
openscad -o examples/storage-bin-lid/stl/pull_tab.stl examples/storage-bin-lid/cad/pull_tab.scad
factory validate examples/storage-bin-lid/stl/lid_panel.stl
factory validate examples/storage-bin-lid/stl/raised_label.stl
factory validate examples/storage-bin-lid/stl/pull_tab.stl
factory render examples/storage-bin-lid/stl/lid_panel.stl
factory render examples/storage-bin-lid/stl/raised_label.stl
factory render examples/storage-bin-lid/stl/pull_tab.stl
factory preview-project examples/storage-bin-lid
factory review-gate examples/storage-bin-lid
```

This can locally advance the example to `slicer_review_ready` - it still
never becomes `human_approved` or `print_ready` automatically. See
`../../docs/examples-library.md`.

## Safety

- No Meshy, no OpenAI/Claude/Gemini/paid API calls, no uploads, no printer
  or slicer automation were used to build this example.
- No `human_approved` or `print_ready` field appears anywhere in this
  example, and nothing here claims this lid is ready to print.
- No STL or PNG file is committed anywhere in this example.

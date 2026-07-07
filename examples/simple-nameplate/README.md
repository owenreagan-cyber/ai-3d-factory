# simple-nameplate

A committed, permanent local example of the `ai-3d-factory` workflow: a
single-color desk nameplate with raised text. This is a **real workflow
example** (not a roadmap/concept placeholder like `../future-organic-models/`)
- every file here was produced by actually running the `factory` CLI
locally, with no network access and no dependency installs.

## How this example was built

```bash
factory generate-openscad examples/simple-nameplate --template nameplate --text "AI 3D Factory"
factory preview-project examples/simple-nameplate
```

`brief.json` and `part_manifest.json` were hand-written first (matching what
`factory init-project` would scaffold); `factory generate-openscad` then
wrote `cad/nameplate.scad`, `cad/README.md`, and
`slicer_review/openscad_export_instructions.md`, upserted the `nameplate`
part into `part_manifest.json`, and advanced `brief.json`'s status forward
to `cad_generated` - all local, deterministic, no OpenSCAD binary invoked,
no STL exported. `factory preview-project` then built
`preview_package/index.json` and `preview_package/preview_report.md` from
what was on disk at that point.

## Current state

- Status: `cad_generated`. **No STL has been exported.**
- `factory preview-index` / `factory preview-project`: report one missing
  visual artifact (`stl/nameplate.stl` doesn't exist yet).
- `factory review-gate examples/simple-nameplate`: **fails** ("No STL files
  exist yet"). That's expected and correct, not a bug - this example
  intentionally stops at the CAD-source stage so it stays a small, safe,
  reviewable text diff instead of shipping a committed binary mesh.

## Continuing this example locally (optional, not done automatically)

If you want to see the rest of the pipeline, you can run these yourself
(none of this happens automatically, and none of it touches a network,
cloud API, printer, or slicer):

```bash
openscad -o examples/simple-nameplate/stl/nameplate.stl examples/simple-nameplate/cad/nameplate.scad
factory validate examples/simple-nameplate/stl/nameplate.stl
factory render examples/simple-nameplate/stl/nameplate.stl
factory preview-project examples/simple-nameplate
factory review-gate examples/simple-nameplate
```

This can locally advance the example to `slicer_review_ready` - it still
never becomes `human_approved` or `print_ready` automatically. See
`../../docs/examples-library.md`.

## Safety

- No Meshy, no OpenAI/Claude/Gemini/paid API calls, no uploads, no printer
  or slicer automation were used to build this example.
- No `human_approved` or `print_ready` field appears anywhere in this
  example, and nothing here claims this part is ready to print.

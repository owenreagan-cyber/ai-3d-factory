# CAD backends (Phase 7)

`factory` supports more than one CAD source-generation backend. This doc
covers the backend registry, the read-only routing command, and the
CadQuery starter backend. See `docs/openscad-generation.md` for the
OpenSCAD generator itself (unchanged by this phase) and `docs/tool-routing.md`
for the human-readable policy both routing layers mirror.

## Backend registry

`factory.cad.backend.get_backend_registry()` describes every CAD backend
this repo knows about, each with a `status`:

| Backend | Status | Notes |
|---|---|---|
| `openscad` | `available` | Implemented since Phase 2 — see `docs/openscad-generation.md`. |
| `cadquery` | `available` if the `cadquery` package is importable, else `not_installed` | Implemented since Phase 7 — see below. |
| `blender` | `future` | Reserved for mesh repair/organic cleanup/render — see the "Blender local repair/render track" in `docs/roadmap.md` (not yet phase-numbered). |
| `meshy` | `future_gated` | Reserved for organic concept generation, explicit-approval-and-cost-gated — the gate itself was designed in `docs/roadmap.md` Phase 16 (`docs/meshy-approval-gate.md`, the full required checklist; `config/future_cloud_tools.json`; `factory check-future-tools`, read-only); actually calling Meshy is the (not yet phase-numbered) "Meshy approval/cost-gated implementation track". See also `docs/licensing-policy.md`. |

This registry is unchanged by Phase 43 - `factory.engine_registry`
(`docs/engine-registry.md`) aggregates it (plus FreeCAD, Plasticity,
Autodesk Fusion, Onshape, the three slicers, and Bambu Connect) into one
canonical tool inventory via `factory engines`/`factory engines probe`,
without replacing or duplicating this backend registry's own routing
logic.

Also unchanged by Phase 44 - `factory.tool_qualification`
(`docs/tool-qualification.md`) reuses this module's `is_cadquery_available()`
directly for its CadQuery qualification check (never a second
importability check), and never rewrites this registry's `status`
values. OpenSCAD reaches `factory engines qualify`'s highest
qualification level (`factory_workflow_verified`) on top of this
backend's existing `available` status; CadQuery gets the equivalent
qualification only when actually installed - it stays `not_installed`
here otherwise, exactly as this table already shows.

The registry is recomputed on every call (not cached at import time), so
`cadquery`'s status always reflects the current environment. Nothing in
`factory.cad.backend` installs a package, generates geometry, writes a
file, or contacts a network/printer/slicer — it is pure data plus a local
`importlib.util.find_spec` availability check.

## `factory route-cad <project_dir>` — read-only recommendation

Explains which CAD backend(s) a project's `brief.json` description points
to, without generating anything. It reuses
`factory.router.recommend_tool()` — the same deterministic, keyword-based
logic `factory plan` already uses for `tool_routing_recommendation` — so
the two never disagree.

```bash
factory route-cad projects/my-part
```

Output includes:

- `primary_recommendation` — `openscad`, `cadquery`, `blender`, `meshy`, or
  `unspecified`, plus the rationale.
- `recommended_backends` — the subset that's actually implementable today
  (only `openscad`/`cadquery`; falls back to `openscad` if nothing else
  matched).
- `future_only_needs` — flags when the description suggests `blender` or
  `meshy`, with a plain-language reason neither is a generation backend
  yet.
- `cadquery_available` — whether `cadquery` is importable in *this*
  environment right now.

This command only reads `brief.json`/`build_plan.json`. It never writes a
file, generates CAD, or contacts a printer/slicer/network.

## `factory generate-cadquery` — CadQuery starter backend

CadQuery is an **optional dependency**: this repo never installs it. If
`cadquery` isn't already importable in your environment, the command fails
immediately with a clear error and writes nothing — it does not attempt an
install, and nothing else in the run is affected.

```bash
factory init-project my-bracket                     # if not already created
factory generate-cadquery projects/my-bracket --template mechanical-plate
factory generate-cadquery projects/my-bracket --template mechanical-plate \
    --length-mm 100 --width-mm 60 --thickness-mm 6 \
    --corner-radius-mm 5 --hole-diameter-mm 4.2 --label-text "REV A"
```

Pass `--force` to overwrite an existing `.py` file from a previous run of
the same template; without it, the command refuses to overwrite anything
and exits non-zero.

### Templates

| Template | File written | Output |
|---|---|---|
| `mechanical-plate` | `mechanical_plate.py` | Parametric rectangular plate with optional corner fillets, four corner mounting holes, and a centered engraved label. |

All parameters are in millimeters and named at the top of the generated
script with comments — open and hand-edit it, then re-export, exactly like
a generated `.scad` file.

### What else the command does

Beyond writing the `.py` source, each run:

- (Re)writes `slicer_review/cadquery_export_instructions.md`, listing the
  local `python cad/<name>.py` command for every CadQuery `.py` script
  currently in `cad/`.
- Upserts a matching entry into `part_manifest.json` (by `part_name`):
  `file_path` (the STL path the script exports to), `cad_source`,
  `backend: "cadquery"`, `export_units: "mm"`, `source`/`license:
  "original"`, `role`. Material/color are left as `"TBD - human decision"`
  placeholders. This never touches an OpenSCAD-authored manifest entry —
  OpenSCAD and CadQuery parts coexist in the same manifest, keyed by
  `part_name`.
- Advances `brief.json`'s status to `cad_generated` — forward-only, same
  rule as `factory generate-openscad`; it never regresses a project that's
  already further along, and never sets `human_approved` or `print_ready`.

### What it does not do

- It does not import or execute the CadQuery source it writes. Exporting
  to STL is a manual step — run `python cad/mechanical_plate.py` yourself
  (see `slicer_review/cadquery_export_instructions.md`), once you've
  reviewed the generated source. **This remains true after Phase 35**
  (`docs/export-pipeline.md`): `factory export-from-cad` never executes
  CadQuery source either — for a CadQuery-sourced project it always
  reports `"manual_export_required"` and shows this exact manual command,
  regardless of `--confirm-export`. Once you've run it yourself,
  `factory export-from-cad --validate --render` (or `factory validate`/
  `factory render` directly) works against the resulting STL exactly as
  it would for an OpenSCAD-sourced one.
- It does not call `factory validate` or `factory render` for you. Do that
  after exporting.
- It does not install `cadquery`, or any other package.
- It never marks anything `slicer_review_ready`, `human_approved`, or
  `print_ready`.

## `factory preview-index` / `preview-project` and CadQuery

`factory.preview_package.gather_preview_data()` lists CAD source files
from both OpenSCAD (`cad/*.scad`) and CadQuery (`cad/*.py`) — a project
using either or both backends gets an accurate `cad_files` count and
missing-STL detection either way.

## Example: `examples/mechanical-plate/`

`examples/mechanical-plate/cad/mechanical_plate.scad` is a hand-authored
OpenSCAD file with the same parameter names as the `mechanical-plate`
CadQuery template above (`length_mm`, `width_mm`, `thickness_mm`,
`corner_radius_mm`, `hole_diameter_mm`, `hole_margin_mm`), written because
CadQuery isn't installed in the environment this example was built in. See
`docs/examples-library.md` and `examples/mechanical-plate/README.md`.

## Example: `examples/multipart-classroom-sign/`

`examples/multipart-classroom-sign/cad/{base.scad,text_layer.scad,
badge.scad}` hand-authors a 3-part assembly following the same
shared-origin convention as the built-in `multipart-nameplate` OpenSCAD
template (`factory/openscad/templates.py`) - same `plate_width`/
`plate_depth`/`plate_height` parameters across all three files, same
`(0,0,0)` origin, no re-centering - since no built-in template currently
covers more than a 2-part base+text pair. See `docs/examples-library.md`,
`docs/slicer-review-workflow.md`, and
`examples/multipart-classroom-sign/README.md`.

## Phase 50 addendum: CAD augmentation of an already-adapted artifact

`factory.cad_augmentation` (`factory cad-augment plan|execute`, see
`docs/cad-augmentation.md`) is a *different* concern from everything
above - it never generates a new project's CAD source from a text
description (that remains `factory generate-openscad`/`generate-cadquery`/
`route-cad`'s job). Instead it attaches a parametric functional feature
(a coin slot, mounting holes, a base plate) to an artifact that already
exists (typically a Blender-adapted organic mesh, Phase 49), producing a
new, independent STL under `generated/cad_augmentation/` - never a fused
mesh, never mixed into `cad/`/`stl/`.

**This phase does not relax the CadQuery policy above.** The one real
execution this phase performs routes through OpenSCAD only, reusing
`factory.export_pipeline`'s existing bounded execution path
(`run_scad_source_to_stl()`); CadQuery and FreeCAD remain reported
candidate engines (via the same `mechanical_design_suitability` registry
field this doc's routing section describes) but are never executed.

## Example: `examples/storage-bin-lid/`

`examples/storage-bin-lid/cad/{lid_panel.scad,raised_label.scad,
pull_tab.scad}` hand-authors a second 3-part shared-origin assembly - a
practical household/classroom utility object rather than signage. Same
`lid_width`/`lid_depth`/`lid_height` parameters across all three files,
same `(0,0,0)` origin. See `docs/examples-library.md`,
`docs/slicer-review-workflow.md`, and
`examples/storage-bin-lid/README.md`.

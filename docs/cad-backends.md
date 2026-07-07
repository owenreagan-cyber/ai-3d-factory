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
| `blender` | `future` | Reserved for mesh repair/organic cleanup/render — see `docs/roadmap.md` Phase 17. |
| `meshy` | `future_gated` | Reserved for organic concept generation, explicit-approval-and-cost-gated — see `docs/roadmap.md` Phase 14 and `docs/licensing-policy.md`. |

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
  reviewed the generated source.
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

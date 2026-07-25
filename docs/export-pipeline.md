# Guided Export Pipeline (Phase 35)

`factory.export_pipeline` is the next gated step after Phase 34's
Readiness-Gated CAD Generation Router:

```
CAD Source Generation -> Guided Export Pipeline -> STL Verification ->
Validation and Preview -> Artifact Finalization -> Human Review Gate ->
Slicer Review -> (never automatic printing)
```

**This orchestrates existing local commands - it never re-implements CAD
generation, STL export, mesh validation, or preview rendering.** It calls
`factory.validators.mesh_validate.validate_mesh()` and
`factory.previews.render_preview.render_preview()` directly. Its one new
capability - actually invoking the OpenSCAD CLI to export an STL - is the
first automated subprocess execution in this repo; everything else here
is planning, verification, and bookkeeping around existing pieces.

**Dry run by default.** Every entry point defaults to
`confirm_export=False` - it always computes and returns a full *export
plan* (which CAD source would be exported, with which tool, to which
output, and what's blocking it), and never invokes a subprocess or writes
a file unless `confirm_export=True` is explicitly passed *and* every gate
independently passes.

## OpenSCAD only for automatic export

CadQuery source (`cad/*.py`) is **never executed** by this module.
Running a generated CadQuery script means running arbitrary local Python
that imports `cadquery` - this repo's existing architecture
(`factory.cad.cadquery_backend`, `docs/cad-backends.md`) has always
treated that as an explicit, manual, human-run step ("It does not import
or execute the CadQuery source it writes"). This phase does not silently
change that policy: a CadQuery-sourced project always resolves to
`"manual_export_required"`, with the exact manual command
(`python cad/<file>.py`) surfaced as an advisory, never executed here -
regardless of `--confirm-export`. Once a human has run it manually,
`--validate`/`--render` still work against the resulting STL - those two
steps never touch CAD source and are safe regardless of which engine
produced the mesh.

## Decision states

`plan_export(project_dir, source=..., output_dir=..., overwrite_stl=...,
confirm_export=...)` is the core, pure planning function - never invokes a
subprocess, never writes a file, regardless of `confirm_export`. Priority
order (first match wins):

1. **`blocked`** - an explicit `--source`/`--output-dir` resolves outside
   the project directory; or no recognized CAD source (`.scad`/`.py`)
   exists under `cad/` at all.
2. **`unsupported_source`** - `--source` names a file with an unrecognized
   extension, or (with no `--source`) only unrecognized files exist.
3. **`ambiguous_source`** - no `--source` given and *both* OpenSCAD and
   CadQuery source exist in the same project. Pass `--source` to
   disambiguate. (Multiple files of the *same* engine - e.g. a 3-part
   multi-part project - is not ambiguous; every file of that engine is
   included in the plan.)
4. **`manual_export_required`** - resolved engine is CadQuery, always -
   see above.
5. **`export_tool_missing`** - resolved engine is OpenSCAD but no local
   `openscad` executable is found. `--confirm-export` cannot force this.
6. **`output_collision`** - any expected output STL already exists and
   `--overwrite-stl` wasn't passed. `--confirm-export` cannot force past
   an unresolved collision.
7. **`needs_confirmation`** / **`allowed`** - otherwise, depending on
   `confirm_export`. `"allowed"` is the only decision a caller should
   treat as "safe to actually export."

`export_command`/`export_supported`/`export_tool_available` describe
*how* export would happen; `blocking_reasons` explains, in the same
priority order, every reason it isn't `"allowed"` yet.

## Tool detection

`resolve_openscad_executable()` checks the standard macOS `.app` bundle
location, then `PATH` via `shutil.which()` - the same discovery style
`factory.slicer.local_slicer_probe.probe_slicers()` already uses for
Bambu Studio/OrcaSlicer. Purely read-only: never installs, downloads, or
launches anything. Called during planning (to report availability) and
again immediately before the actual subprocess call in `run_export()`.

## Source-to-output mapping

Each recognized CAD source file maps to exactly one expected STL by stem:
`cad/<name>.scad` / `cad/<name>.py` -> `<output_directory>/<name>.stl`
(`output_directory` defaults to `stl/`, overridable via `--output-dir`,
which must resolve inside the project directory). A multi-part project
(multiple `.scad` files sharing one engine) produces one plan entry per
file - every file is exported, validated, and rendered independently in
one `--all` run.

## Freshness and stale detection

**File existence alone is never treated as currentness.** For each
expected STL, `_stl_freshness()` reports one of:

| Status | Meaning |
|---|---|
| `current` | The STL exists and matches its source (see below). |
| `stale` | The STL exists but its source has changed since it was produced. |
| `unknown` | The STL exists but its source file no longer exists (can't compare). |
| `missing` | No STL exists yet at the expected path. |

Freshness prefers a **fingerprint** (`sha256:<hex>` of the source file's
bytes) comparison against the prior export receipt's recorded fingerprint
for that exact source file - the strongest signal, immune to a modification-
time reset (e.g. a fresh `git checkout`). When no receipt entry exists yet
for that file, it falls back to a plain modification-time comparison,
mirroring the same epsilon-guarded convention
`factory.render_coverage.compute_render_coverage()` already uses for
render-vs-mesh staleness. Preview staleness (render older than its STL)
reuses `compute_render_coverage()` directly rather than re-deriving it.

## Output collision protection

By default, an existing STL at an expected output path is always a
**collision** - `plan_export()` never overwrites it, and the plan's
`output_collisions` list names every affected path plus its freshness.
Pass `--overwrite-stl` to allow overwriting; even then, the *source CAD*
is never touched, and unrelated outputs are never removed. The plan
surfaces the overwrite intent as an advisory (`"--overwrite-stl passed -
will overwrite N existing STL(s)"`) so it's visible in both the human-
readable and `--json` output.

## Export execution: `run_export()`

The one, explicit subprocess/write path for OpenSCAD. **Only ever called
when `plan["decision"] == "allowed"`** - raises `ValueError` otherwise,
mirroring `factory.generation_gate.run_generation()`'s exact defensive
guard. Steps, every one required before `success` is ever `True`:

1. Verify the source file still exists.
2. Verify its fingerprint still matches what the plan recorded - if it
   changed since planning (a race), reject with a clear error rather than
   exporting stale-relative-to-itself content.
3. Re-resolve the executable (never assumes it's still there).
4. Invoke it via **argument-list subprocess execution** -
   `subprocess.run([executable, "-o", str(stl_path), str(source_path)],
   capture_output=True, text=True, timeout=120)` - **never** a shell
   string.
5. Capture stdout, stderr, exit code, and wall-clock duration.
6. **A zero exit code alone is never treated as success.** The output
   file must actually exist, be non-empty, and have a `.stl` extension.
7. On success, record the output's size and fingerprint, and best-effort
   probe `<executable> --version` for the receipt (never blocks export on
   failure to detect a version).

Every failure mode - timeout, nonzero exit, zero exit with no file, empty
file, source-changed-since-planning, source missing at execution time,
failure to launch the executable at all - is captured as a structured
`errors: [...]` list on the result, never a silent success.

## Validation and preview reuse

`run_validation()` calls `factory.validators.mesh_validate.validate_mesh()`
directly and writes the report to `validation/<stem>_validation.json` -
the exact convention `factory validate` already uses. It never
re-implements a check, never suppresses a warning, and never reinterprets
PASS/WARN/FAIL - it only *normalizes the label* for this pipeline's own
vocabulary:

| `overall_status` | Normalized `status` |
|---|---|
| `PASS` | `passed` |
| `WARN` | `passed_with_warnings` |
| `FAIL` (mesh genuinely invalid) | `failed` |
| `FAIL` (specifically because `trimesh` isn't importable) | `unavailable` |

For a multi-part project, `run_multipart_check()` also reuses
`factory.validators.multipart_check.check_manifest()` against
`part_manifest.json` (cross-referenced with `build_plan.json`'s
`required_parts` when present) - never a second manifest-consistency
checker.

`run_render()` calls `factory.previews.render_preview.render_preview()`
directly and writes to `renders/<stem>_preview.png` - the same convention
`factory render` uses. It never trusts a reported `PASS` at face value:
if the renderer claims success but the output file is missing or empty,
the result is downgraded to `failed` rather than passed through.

**A validation or render failure never deletes the STL** and never lets
the overall pipeline claim `completed` - see "Partial completion" below.

## Partial completion

Every confirmed run's overall state is one of:
`export_failed` / `validation_failed` / `render_failed` / `partial_pipeline`
/ `completed`. `completed` requires every requested step (export, and -
if requested via `--validate`/`--render`/`--all` - validation and render)
to have actually succeeded for every source file; anything short of that
is `partial_pipeline` (steps simply weren't requested/finished) or a more
specific `*_failed` state (a step ran and failed). **The pipeline is
never reported `completed` when any requested stage failed.**

## Execution receipts

`generated/export_receipt.json` - a **sibling** of Phase 34's
`generated/generation_receipt.json`, never merged into it: Phase 34's
receipt reflects one CAD *generation* run and every current Generation
Gate test pins its exact shape; this receipt reflects a project's
*export/validate/render history* and is upserted many times, once per
source file, across many separate runs, without ever touching Phase 34's
file.

**Written only after a confirmed run actually attempted something** -
never for a dry run. Upserted **by `source_file`**, the same
upsert-by-key pattern `factory.openscad.generate._upsert_manifest_parts()`
and `factory.cad.manifest.upsert_cadquery_manifest_entry()` already use
for `part_manifest.json`: a record for a source file this run didn't
touch is preserved untouched. **A failed or partial run never destroys a
prior successful record for a different (or untouched) source file** -
each source file's own export/validation/render sub-record is replaced
independently.

```jsonc
{
  "project": "projects/classroom-sign",
  "no_automatic_print": true,
  "exports": [
    {
      "source_file": "cad/sign.scad",
      "output_stl": "stl/sign.stl",
      "export": {
        "command": ["/opt/homebrew/bin/openscad", "-o", "stl/sign.stl", "cad/sign.scad"],
        "started_at": "...", "completed_at": "...", "duration_seconds": 0.99,
        "exit_code": 0, "stdout_summary": "...", "stderr_summary": "...",
        "success": true, "errors": [],
        "output_size_bytes": 88542,
        "output_fingerprint": "sha256:...", "source_fingerprint": "sha256:...",
        "export_tool_version": "OpenSCAD version 2021.01"
      },
      "validation": {"status": "passed_with_warnings", "report_path": "validation/sign_validation.json"},
      "render": {"status": "passed", "render_path": "renders/sign_preview.png"},
      "pipeline_state": "completed"
    }
  ],
  "last_completed_stage": "completed",
  "pipeline_state": "completed",
  "updated_at": "..."
}
```

`no_automatic_print: true` is a fixed, immutable declaration on every
receipt - mirroring `schemas/slicer_review.schema.json`'s hard-coded
`auto_print_allowed: false`.

## Artifact registry

`build_artifact_registry(project_dir)` normalizes every category this
phase's spec calls out - CAD source, STL, validation, preview, review,
and both receipts - into one read-only structure, reusing the plan and
both receipts rather than re-deriving anything. `"review"` is
deliberately a pointer string (`"run factory review-gate <project_dir>
..."`), not a computed result: `factory.review_gate.evaluate_review_gate()`
needs `factory.project_inspection.summarize_project()`, and this module
must stay a leaf the same way `factory.generation_gate` does -
`project_inspection` imports *this* module for its own additive field, so
the reverse import would be circular.

## Resume behavior

`--resume` skips a source file's export/validate/render step when the
receipt already records it as current for that **exact source
fingerprint** - it never assumes a prior file is current just because it
exists. Examples:

- Export succeeded, validation failed: resume re-runs validation (and
  render, if requested) only - export is skipped.
- Validation succeeded, render missing (not previously requested): resume
  runs only the render step.
- CAD source changed after export: the fingerprint no longer matches, so
  resume re-runs export (and every step after it) for that file.

Every resumed step still writes an honest, real record - `--resume` never
fabricates a "success" for a step it skipped; it only reuses the receipt's
prior record for a step whose current fingerprint still matches.

## The CLI

```bash
factory export-from-cad <project_dir>                                   # dry-run plan only
factory export-from-cad <project_dir> --json                            # machine-readable dry run
factory export-from-cad <project_dir> --confirm-export                  # export, if the plan allows it
factory export-from-cad <project_dir> --confirm-export --all            # export + validate + render
factory export-from-cad <project_dir> --confirm-export --overwrite-stl  # allow replacing an existing STL
factory export-from-cad <project_dir> --source cad/base.scad            # disambiguate a multi-source project
factory export-from-cad <project_dir> --validate --render                # validate/render an existing STL only
factory export-from-cad <project_dir> --confirm-export --all --resume   # skip already-current stages
```

Sample dry run:

```
$ factory export-from-cad projects/classroom-sign
Guided Export Plan

Project:
classroom-sign

Source engine:
OpenSCAD

CAD source:
cad/sign.scad

Exporter:
OpenSCAD CLI

Exporter available:
Yes

Expected output:
stl/sign.stl

Decision:
needs_confirmation

Post-export checks:
- Verify output exists
- Verify output is non-empty
- Validate mesh
- Render preview
- Update artifact tracking
- Update execution receipt

No files written.
Re-run with --confirm-export to begin export.

This only inspected/exported existing local CAD source and, if requested, ran this repo's
existing local validator/renderer - it never invoked Blender, never called Meshy, never sliced,
and never contacted any printer/network. No automatic printing.
```

**Never prints plain text before or after JSON** with `--json` - the
entire stdout is one `json.dumps(...)` call, including on every error
path (missing project directory, an unsafe `--source`/`--output-dir`).
Writing the receipt itself never triggers a console confirmation message
in the human-readable mode either - `--json` surfaces `receipt.path` as
data instead.

## JSON contract

Top-level fields: `export_plan` (the full raw plan), `dry_run`, `decision`,
`source` (`{engine, backend, files, selected}`), `exporter`
(`{tool, available}`), `expected_outputs`, `freshness`
(`{existing, stale}`), `collisions`, `blockers`, `advisories`, `execution`
(per-source export/validate/render records, or `null` if nothing was
attempted), `validation`, `preview`, `artifact_registry`, `receipt`
(`{path, pipeline_state}`), `errors`, `no_automatic_print` (always `true`).

## Failure handling

Every failure mode named in this phase's spec resolves to a structured,
honest outcome rather than a crash or a false success: missing project
(CLI-level `errors` + exit 1), missing CAD source (`blocked`), multiple
ambiguous sources (`ambiguous_source`), unsupported source type
(`unsupported_source`), exporter unavailable (`export_tool_missing`),
unsafe output directory / source path (`blocked`, `UnsafePathError` caught
internally - `plan_export()` never lets it propagate), subprocess timeout/
nonzero exit/zero-exit-with-no-output/empty output (all captured in
`run_export()`'s `errors` list, `success: False`), output collision
(`output_collision`), source changed during execution (rejected before the
subprocess call actually happens), malformed export receipt JSON
(`read_export_receipt()` returns `None` rather than raising), partial
pipeline completion (`partial_pipeline`/`*_failed`, never `completed`).

## Limitations

- **Only OpenSCAD gets automatic export.** CadQuery source always
  requires a manual step, by design - see "OpenSCAD only for automatic
  export" above.
- **One plan-and-execute pass per CLI invocation.** The plan is rebuilt
  once per invocation, not re-checked mid-run for every file in a
  multi-part project; `run_export()`'s own fingerprint check is what
  catches a genuine race (the source changing between planning and that
  specific file's export).
- **Fixed 120-second export timeout, not configurable via the CLI** -
  reasonable for the local templates this repo generates today; a very
  large or slow-to-render OpenSCAD file could need a longer budget in a
  future phase.
- **One receipt per project, not a full history across every past run** -
  each source file's entry reflects only its most recent attempt; a
  human who needs deeper history should rely on version control of the
  `generated/` directory (check `.gitignore` before assuming it's
  tracked) or their own logging.
- **`--resume`'s freshness check is fingerprint-only for the source CAD**
  - it does not separately re-verify the STL's own byte content beyond
  what the freshness/collision check already covers.

## Non-goals

- **No AI, no LLM, no machine learning of any kind.**
- **No network calls, no web search, no scraping, no printer/slicer
  contact, no print submission.**
- **Never invokes Blender, Meshy, or FreeCAD.**
- **Never installs anything** - not OpenSCAD, not `cadquery`, nothing.
- **Never executes CadQuery source** - see above.
- **Never sets `human_approved` or `print_ready`.**
- **Never re-scores project readiness or the Generation Gate decision** -
  those are read from Phase 30-34's own already-computed summaries where
  relevant, never recomputed here.
- **Never duplicates mesh validation, multipart validation, dimension
  validation, or manufacturing inspection** - `factory.validators.*` is
  called directly, never re-implemented.

See also `docs/generation-gate.md` (Phase 34), `docs/openscad-generation.md`,
`docs/cad-backends.md`, `docs/render-coverage.md`, `docs/preview-board.md`,
`docs/review-gate.md`, `docs/slicer-review-workflow.md`,
`docs/file-lifecycle.md`, and `docs/roadmap.md` Phase 35.

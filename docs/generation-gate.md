# Generation Gate (Phase 34)

`factory.generation_gate` is the first gated bridge between the Design
Orchestrator (Phase 33) and this repo's *existing* local CAD generation
backends:

```
User Idea -> Project Intake -> Draft Brief -> Brief Merge ->
Design Intent -> Reference Board -> Project Readiness ->
Design Orchestrator -> Readiness-Gated CAD Router -> CAD Engine ->
Preview -> Review -> Slicer Review -> (never automatic printing)
```

**This is an adapter/gate around existing local generation, not a second
CAD backend.** It never generates geometry itself - it only decides
*whether* `factory.openscad.generate.generate_openscad()` or
`factory.cad.cadquery_backend.generate_cadquery()` (both already
implemented, in earlier phases) are allowed to run, and if so, with which
template/parameters. Only engines with a real, already-implemented local
backend can ever be generated - today that's OpenSCAD and CadQuery. Any
other recommended engine (Blender, `Meshy (Concept Only)`, FreeCAD, Hybrid
Workflow, Manual Design, Unknown) always returns `"Unsupported Engine"` -
this module never launches Blender, never calls Meshy, never generates
FreeCAD source, never installs anything, never contacts a network.

**Dry run by default.** Every entry point defaults to
`confirm_generate=False` - it always computes and returns a full
*generation plan* (what would be generated, with what backend/template,
and what's still missing), and never calls a generation backend unless
`confirm_generate=True` is explicitly passed *and* every readiness gate
independently passes. No file is ever written by this module except via
the one, explicit, opt-in path (`run_generation()`).

## Never re-scores, never re-generates

Every function here takes an already-computed `design_orchestrator_summary`
(Phase 33, `factory.design_orchestrator.evaluate_project_readiness()`) as
input - the readiness score, state, and recommended engine are read, never
recomputed. It never re-implements OpenSCAD or CadQuery generation itself:
`run_generation()` calls the existing `generate_openscad()`/
`generate_cadquery()` functions directly. It never imports
`factory.project_inspection` (that would be circular -
`project_inspection` imports *this* module, not the other way around).

## Plan generation

`plan_generation(intake_summary, design_orchestrator_summary)` picks a
deterministic local template for the recommended engine, or returns `None`
if no confident local template exists for that engine/category
combination - generation is never attempted blind.

| Engine | Template | Notes |
|---|---|---|
| OpenSCAD | `"sign"` | The one OpenSCAD template (of `factory.openscad.templates.ALLOWED_TEMPLATES`) that fits every OpenSCAD-leaning category this repo's category->engine mapping produces. `params.text` comes from `intake_summary`'s project name, or `"Untitled"`. |
| CadQuery | `"mechanical-plate"` | CadQuery's one local template (`factory.cad.cadquery_backend.ALLOWED_TEMPLATES == ("mechanical-plate",)`) - a generic dimensioned plate/bracket with the generator's own conservative default dimensions. |
| anything else | `None` | No confident local template - `evaluate_generation_gate()` always resolves this to `"Dry Run Only"` (see below), never a guess. |

## Decision states

`evaluate_generation_gate(intake_summary, design_orchestrator_summary,
confirm_generate=...)` is the core, pure gate decision. Priority order
(first match wins):

1. **`Blocked`** - `readiness_state == "Blocked"`, always, regardless of
   engine/score/confirmation. A hard manufacturability block from the
   Design Orchestrator always wins here too.
2. **`Unsupported Engine`** - `recommended_engine` not in
   `SUPPORTED_ENGINES` (`"OpenSCAD"`, `"CadQuery"`), or CadQuery
   recommended but the `cadquery` package isn't installed in this
   environment ("not available here," distinct from "not implemented at
   all," but the same bucket for the caller).
3. **`Dry Run Only`** - readiness state isn't one of the four `"Ready For
   ..."` states, or the overall score is below `MINIMUM_READINESS_SCORE`
   (60 - matching the Design Orchestrator's own `"Ready For ..."`
   boundary, so this gate never disagrees with what "ready" already means
   elsewhere in the pipeline), or a critical advisory (`Dimensions
   missing`/`Material unspecified`/`Printer unspecified`) is present, or
   no local template plan could be determined. **Even `--confirm-generate`
   cannot force generation past this gate.**
4. **`Needs Confirmation`** (if `confirm_generate` is `False`) /
   **`Allowed`** (if `True`) - otherwise. `"Allowed"` is the only decision
   a caller should ever treat as "safe to actually generate."

`required_before_generation` lists, in the same order the checks above
ran, every reason generation isn't (yet) `"Allowed"` - always empty when
the decision is `"Allowed"`.

## Execution: `run_generation()`

The one, explicit write path this module has. **Only ever called when
`gate_result["decision"] == "Allowed"`** - raises `ValueError` otherwise,
as a defensive guard against accidentally generating when the gate said
no; the CLI (or any caller) is responsible for checking that first. Calls
`generate_openscad()`/`generate_cadquery()` directly - never
re-implements CAD generation. Returns
`{"written_files": [str, ...], "warnings": [str, ...]}`.

**Writes CAD *source* only** (`cad/*.scad` or `cad/*.py`), exactly like
the generators it calls - STL export is always a separate, manual,
human-run step (see `docs/openscad-generation.md`, `docs/cad-backends.md`).
Never invokes OpenSCAD/CadQuery/Blender/Meshy/FreeCAD binaries, never
exports an STL, never contacts a network/printer/slicer.

If the underlying generator raises (most commonly
`GeneratedFileExistsError` - re-running confirmed generation on a project
that already has that template's CAD source, without `--force`; there is
no `--force` on `factory generate-from-readiness` itself, only on
`factory generate-openscad`/`generate-cadquery` directly), the CLI catches
it and reports a clear `generation_error` instead of crashing - see "The
CLI" below.

## Execution receipts

**After a successful confirmed generation** (and only then -
`run_generation()` actually returned, decision was `"Allowed"`),
`write_generation_receipt(project_dir, gate_result, generation_result)`
writes `<project_dir>/generated/generation_receipt.json`. **Dry runs never
produce a receipt** - `"Needs Confirmation"`, `"Blocked"`, `"Unsupported
Engine"`, and `"Dry Run Only"` never reach this function. One receipt
reflects the most recent confirmed run for a project, not a history - a
later confirmed run overwrites it. Writing a receipt never triggers a
console confirmation message by itself; `factory generate-from-readiness`
surfaces the path only via `--json` output (see "The CLI" below).

Every field is read from `gate_result`/`generation_result` (already
computed) or from files the generation call itself already wrote (the
manifest) or that may already exist from an earlier, separate, manual
export/validate/render step - `build_execution_receipt()` never
generates, validates, or re-scores anything itself:

| Field | Meaning |
|---|---|
| `project` | The project directory path, as given. |
| `engine` | `"OpenSCAD"` / `"CadQuery"` (the plan's engine - human-facing). |
| `backend` | `"openscad"` / `"cadquery"` (matches `factory.cad.backend.get_backend_registry()`'s `backend_id`). |
| `template` | The template name from the plan (e.g. `"sign"`, `"mechanical-plate"`). |
| `readiness_score` | The Design Orchestrator's overall score at the time of this run. |
| `readiness_state` | The Design Orchestrator's readiness state at the time of this run. |
| `execution_decision` | Always `"Allowed"` for a written receipt - kept explicit for audit clarity. |
| `files_generated` | Project-relative POSIX paths of every file this run wrote (e.g. `["cad/sign.scad"]`). |
| `artifact_sizes` | `{relative_path: size_bytes}` for each generated file. |
| `artifact_tracking` | The normalized artifact-category breakdown - see below. |
| `validation_status` | One flat summary string collapsed from `artifact_tracking["validation"]` - `"not_applicable"` (no tracked parts), `"not_yet_validated"`, `"PASS"`, `"WARN"`, `"FAIL"`, or `"mixed"` (parts disagree). |
| `warnings` | Echoed from `generation_result["warnings"]`. |
| `errors` | Always `[]` - a receipt is only ever written after success. |
| `success` | Always `true`. |
| `timestamp` | ISO 8601 UTC, when the receipt was written. |

## Artifact tracking

`build_artifact_tracking(project_dir, written_files)` normalizes every
artifact category this phase tracks into one structure, reusing existing
manifest/validator infrastructure wherever possible rather than
duplicating it:

| Category | How it's derived |
|---|---|
| `cad_source` | One entry per written file, categorized `"OpenSCAD"` (`.scad`), `"CadQuery"` (`.py`), or `"Other"` by extension - never re-parsed, just the file this run just wrote. |
| `manifest` | Reads `part_manifest.json` (already upserted by `run_generation()` itself, via `factory.openscad.generate._upsert_manifest_parts` or `factory.cad.manifest.upsert_cadquery_manifest_entry` - never re-derived), filtered to only the entries whose `cad_source` matches a file this run wrote (an unrelated part from an earlier generation never leaks in). |
| `stl` | For each matched manifest part, whether its expected STL (`file_path`) already exists on disk and its size if so. Right after a fresh confirmed generation this is normally `exists: false` - STL export is a separate, manual step - and that is the expected, honest common case, not an error. |
| `validation` | For each matched part, whether a `validation/<stem>_validation.json` report already exists (the same naming convention `factory validate` and `factory.project_inspection._compute_validation_coverage` already use) and, if so, its `overall_status`. **Never runs `factory.validators.mesh_validate` itself** - only reads a report a separate, manual `factory validate` run may have already written. |
| `preview` | For each matched part, whether a `renders/<stem>_preview.png` already exists (same convention `factory render` uses). Never renders anything itself. |
| `review` | A pointer string to `factory review-gate <project_dir>` rather than a computed field - `factory.review_gate.evaluate_review_gate()` needs `factory.project_inspection.summarize_project()`, and this module must never import `project_inspection` (see "Never re-scores, never re-generates" above). |

## The CLI

```bash
factory generate-from-readiness <project_dir_or_text_or_markdown_file>                    # dry-run plan only
factory generate-from-readiness <path> --json                                             # machine-readable dry run
factory generate-from-readiness <path> --confirm-generate                                 # actually generate, if the gate allows it
factory generate-from-readiness <path> --confirm-generate --json                          # machine-readable confirmed run
```

Sample dry run:

```
$ factory generate-from-readiness examples/storage-bin-lid
Generation Plan

Project:
storage-bin-lid

Readiness:
36%

Status:
Needs Information

Recommended Engine:
OpenSCAD

Decision:
Dry Run Only

Would Generate:
OpenSCAD CAD artifacts (OpenSCAD "sign" template, text='storage-bin-lid-example')

Required Before Generation:
- material unspecified
- printer unspecified
- readiness state is 'Needs Information', not one of the "Ready For ..." states
- readiness score 36% is below the 60% threshold

No files written.

This only inspected existing project files and, if --confirm-generate was passed and the
gate allowed it, ran this repo's existing local OpenSCAD/CadQuery generator - it never invoked
Blender, never called Meshy, never installed anything, and never contacted any printer/network.
```

Sample confirmed generation (on a fully-ready project, `--json`):

```json
{
  "decision": "Allowed",
  "recommended_engine": "OpenSCAD",
  "readiness_state": "Ready For Mechanical CAD",
  "readiness_score": 89,
  "plan": {"engine": "OpenSCAD", "template": "sign", "params": {"text": "Classroom Sign"}, "human_summary": "..."},
  "required_before_generation": [],
  "confirm_generate": true,
  "project": "projects/classroom-sign",
  "generation_result": {"written_files": ["projects/classroom-sign/cad/sign.scad"], "warnings": []},
  "receipt_path": "projects/classroom-sign/generated/generation_receipt.json"
}
```

**Clear blocking reasons, consistent output:** every non-`"Allowed"`
decision surfaces its `required_before_generation` list in both output
modes; a write conflict from the underlying generator (most commonly
re-running confirmed generation on a project that already has that
template's CAD source) is caught and reported as a `generation_error`
(exit code 1, both output modes) rather than an unhandled traceback - no
receipt is written on that path. `--json` includes `receipt_path` only
when a receipt was actually written; the human-readable mode never prints
a special receipt confirmation line (writing the receipt is silent by
design - see "Execution receipts" above).

Never writes any file without `--confirm-generate` *and* an `"Allowed"`
decision; never invokes Blender, Meshy, FreeCAD, or any network/printer.

## Connected to project inspection and the preview board

`factory.project_inspection.summarize_project()` gained two additive
fields:

- **`generation_gate_summary`** (compact `{decision, recommended_engine,
  ready, reason}`) - always evaluated as a dry run (`confirm_generate=False`
  - project inspection is read-only and must never trigger actual
  generation).
- **`generation_execution_summary`** (compact `{receipt_available,
  last_execution, last_execution_engine}`, Phase 34 execution receipts) -
  has a confirmed generation ever actually run for this project, and when.
  Reads at most one file (`generated/generation_receipt.json`) if it
  exists; never writes, never triggers generation. **Deliberately a
  separate field from `generation_gate_summary`** rather than added keys
  on it, so that field's shape stays exactly
  `{"decision", "recommended_engine", "ready", "reason"}` - the shape every
  Generation Gate test already pins.

Both are always a dict, never `None`, purely additive: neither is read by
`classify_visual_readiness()`, `build_health_signals()`, or
`build_suggested_actions()`, and neither appears in
`factory.review_gate.evaluate_review_gate()`'s JSON output.

The preview board's **HTML** gained a compact "Generation Gate" section,
placed right after "Project Readiness" (both are "meta" cards summarizing
what's possible next): the gate decision, recommended engine, a Ready
Yes/No badge, the top reason why (if not ready), and - from
`generation_execution_summary` - whether a receipt is available and when
the last confirmed execution happened (`"Never"` if none). Same
guarantees as every other card section: purely presentational, no
JavaScript, no external assets, and this board never generates CAD or
invokes any engine - the only write path
(`factory generate-from-readiness --confirm-generate`) is a separate,
explicit, human-run CLI command the preview board never invokes.

## Limitations

- **Exactly two templates, total.** OpenSCAD always resolves to `"sign"`,
  CadQuery always resolves to `"mechanical-plate"` - there is no per-
  category template selection within an engine yet (e.g. a `"frame"`
  category still generates the generic `"sign"` template). A future phase
  could add finer-grained template selection once more local templates
  exist.
- **No multi-part planning.** `plan_generation()` always returns a single-
  part plan; a project whose category implies multiple parts (e.g. a
  multi-part assembly) still only generates one part per confirmed run.
- **One receipt per project, not a history.** A later confirmed run
  overwrites `generated/generation_receipt.json` - there is no append-only
  execution log. A human who needs a full history should keep their own
  copies or rely on version control of the `generated/` directory (which,
  like `projects/`, is a per-project working directory - check
  `.gitignore` before assuming it's tracked).
- **Artifact tracking reflects file existence, not correctness.** `"stl":
  {"exists": true}` means a file is present at the expected path - it says
  nothing about whether that STL is actually valid geometry (that's what
  `factory validate`'s report, read but never generated here, is for).
- **`validation_status`/`review` are read-only summaries of *other*
  commands' output**, not a re-implementation - if `factory validate` or
  `factory review-gate` have never been run, the honest answer is
  "not yet" rather than a computed judgment.

## Non-goals

- **No AI, no LLM, no machine learning of any kind.**
- **No network calls, no web search, no scraping, no printer/slicer
  contact.**
- **Never invokes Blender, Meshy, or FreeCAD** - `"Unsupported Engine"` is
  the only outcome for any of them.
- **Never installs anything** - not `cadquery`, not OpenSCAD, nothing.
- **Never exports an STL, never slices, never prints.**
- **Never sets `human_approved` or `print_ready`.**
- **Never re-scores readiness** - every score/state/engine value is read
  from the Design Orchestrator's own already-computed summary, never
  recomputed here.
- **Never duplicates mesh validation, multipart validation, dimension
  validation, or manufacturing inspection** - `factory.validators.*` and
  `factory.manufacturing.*` are read from (existing reports) where
  relevant, never re-implemented.

See also `docs/design-orchestrator.md` (Phase 33), `docs/openscad-generation.md`,
`docs/cad-backends.md`, `docs/preview-board.md`, `docs/review-gate.md`,
`docs/slicer-review-workflow.md`, and `docs/roadmap.md` Phase 34.

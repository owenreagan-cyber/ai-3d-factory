# Blender Local Execution Gate & Adapter (Phase 45)

`factory.blender_gate` and `factory.blender_adapter` together build the
first controlled local Blender execution path in this repo. They answer
a question Phase 44 deliberately stopped short of: **"can this detected
Blender installation actually run headlessly and produce a mesh the
Factory can validate and preview?"**

```
specialized probes -> factory.engine_registry -> factory.tool_qualification
    -> factory.blender_gate -> factory.blender_adapter -> CLI
```

## This phase summarizes, gates, and proves - it does not authorize

**This phase does not enable Blender automation on real projects, does
not implement mesh repair or rendering workflows, and does not grant
project generation.** Every real Blender invocation this phase makes
targets exactly one, fixed, Factory-owned, throwaway qualification
fixture - never a project file, never a user- or project-supplied
script.

## The locked safety progression

```
Detected -> Metadata Qualified -> Headless Runtime Qualified ->
Fixture Execution Qualified -> Adapter Qualified ->
Project Execution Eligible -> Explicit Human Confirmation ->
Actual Project Execution
```

This phase's code can reach, at most, **Adapter Qualified** - for the one
narrow `fixture_organic_model` workflow only. **Project Execution
Eligible and everything after it remain entirely unimplemented.**
`project_execution_approved` is hardcoded `False` on every result either
module produces, with no code path that ever sets it `True`.

- **Detected** (Phase 43) - a `.app` bundle/PATH check found Blender.
- **Metadata Qualified** (Phase 44) - path + `Info.plist` version, no
  subprocess. `factory.tool_qualification`'s Blender result is
  **unchanged by this phase** - it still stops at `metadata_only`/
  `requires_manual_qualification`. This phase's own, separate,
  deeper evidence lives in `factory.blender_adapter`, joined at the CLI
  layer, never written back into Phase 44's result.
- **Headless Runtime Qualified** (new, this phase) - one bounded, real,
  Python-free `blender --background --factory-startup -Y --offline-mode
  --version` subprocess call succeeded. Verified fresh on every `factory
  blender qualify` call - never cached, never trusted from a prior run.
- **Fixture Execution Qualified** / **Adapter Qualified** (new, this
  phase, only with `--confirm-fixture`) - the full fixture pipeline
  (below) succeeded end to end.
- **Project Execution Eligible** onward - **not implemented**. No code
  path in this repo makes real project Blender generation possible.

## Why real Blender execution is safe to add in this phase

`docs/blender-local-track.md` (Phase 21) established "no subprocess call,
no headless invocation" as a standing rule, and Phase 43/44 both
preserved it as binding, not just "uncertain enough to skip" - explicitly
naming Phase 45 as the gate-review phase that would decide whether a
bounded headless probe is ever safe to add. This is that phase, and it
answers narrowly: **yes, for exactly `--background` (Blender's own
standard, universally-documented non-interactive mode, the same one used
by every render farm/CI pipeline) against one Factory-owned throwaway
fixture** - never for real project automation, which stays exactly as
gated as before. See "Gate checklist reconciliation" below for the
item-by-item accounting.

## Blender execution policy

Every real Blender invocation in this repo (there are exactly two call
sites, both in `factory.blender_adapter`) uses:

- An absolute, already-resolved binary path - `factory.blender_gate.resolve_blender_binary()`
  joins Phase 43's `.app` bundle detection with a read-only
  `Contents/MacOS/Blender` existence check. Never a fresh `PATH` lookup,
  never a guess.
- An argument list, never a shell string - `shell=False` (Python's
  default, never overridden).
- A hard timeout on every call (60s for the version probe, 180s for the
  fixture pipeline).
- `--background` - headless, no visible window.
- `--factory-startup` - skip the user's `startup.blend`.
- `-Y`/`--disable-autoexec` - defense in depth; already Blender's own
  default, passed explicitly anyway.
- `--offline-mode` - force network off regardless of the user's Blender
  preference.
- Captured `stdout`/`stderr` on every call.

The two call sites:

1. **`verify_headless_runtime()`** - `--version` only. No `-P`/`--python`/
   `--python-expr` flag is ever passed here; Blender executes zero Python
   for this check.
2. **`run_fixture_qualification()`** - the same flags, plus `--python
   blender_fixtures/factory_qualification_fixture.py -- <tmp_stl_path>`
   and `--python-exit-code 1` (a distinguishable non-zero exit if the
   fixture script itself raises).

## Startup isolation - what is and is not achieved

`--factory-startup` skips reading `startup.blend` from the user's home
directory, so the fixture never depends on the user's saved scene,
window layout, or recent-files list. **This is not a complete guarantee
that zero user preference influences the run** - Blender's user
preferences file (`userpref.blend`, distinct from `startup.blend`) may
still enable add-ons the user previously turned on; `--factory-startup`
does not disable those. No `--addons` flag is ever passed by this repo
(so no *additional* add-on is ever enabled beyond whatever the user's own
preferences already have on), and the fixture script's own actions are
narrow enough (create one primitive, export one STL) that this remaining
gap is a documented limitation, not a claimed full isolation.

## Python execution policy - the fixture script is not arbitrary Python

**Blender Python is an arbitrary-code execution surface. This repo never
runs a general-purpose Blender script, and never will as part of this
phase.** Exactly one script exists:
`blender_fixtures/factory_qualification_fixture.py` - fixed,
hand-written, repository-reviewed, checked into version control. No
command in this repo accepts a user- or project-supplied script path; no
CLI option, no function parameter, no config file entry names an
alternate script.

That file:

- Imports only `bpy` and `sys` - both part of Blender's own embedded
  Python. No `subprocess`, `socket`, `urllib`, `requests`, `os.system`.
- Reads no file, no environment variable, no network resource of its own
  choosing. Its only input is the single output path
  `factory.blender_adapter` passes after `--` on the command line.
- Writes to exactly one path - the output path it was given. Never a
  second file, never a delete.
- Installs no add-on, loads no external `.blend` file.

It deliberately lives **outside** `src/` (in a new top-level
`blender_fixtures/` directory) so its `import bpy` line never collides
with the pre-existing repo-wide safety scan in
`tests/test_blender_gate.py::test_no_blender_execution_code_anywhere_in_src`
(which correctly still scans every `.py` file under `src/` for `import
bpy`/`from bpy` and finds none - unchanged and still passing). This is a
deliberate, documented placement choice, not an oversight.
`tests/test_blender_adapter_safety.py` statically parses this file's own
AST (not just a substring scan) to prove the import/write constraints
above, every time the test suite runs.

## The fixture: `fixture_organic_model`

The one, deliberately narrow, workflow this phase's adapter supports.
Explicitly **not** attempted, this phase or ever without a separate,
future, explicitly-scoped phase: character generation, Geometry Nodes
automation, sculpting automation, texture generation, asset downloads,
add-on installation, automatic retopology, full product design,
prompt-to-Blender generation, or arbitrary mesh repair.

Pipeline:

```
blender_fixtures/factory_qualification_fixture.py (Factory-owned, static)
        -> blender --background (headless)
        -> tempfile.TemporaryDirectory()-only .stl export
        -> factory.validators.mesh_validate.validate_mesh() (reused, not duplicated)
        -> factory.previews.render_preview.render_preview() (reused, not duplicated)
        -> cleanup, verified
```

The fixture object itself is a fixed 10mm-radius UV sphere - a
placeholder shape chosen only to prove the pipeline, never a product,
user design, or copyrighted character.

Every check is recorded individually (`factory blender qualify
--confirm-fixture --verbose`):

1. **Binary detected** - reused from `factory.blender_gate.resolve_blender_binary()`.
2. **Headless runtime verified** - the `--version` call above, run fresh,
   never skipped even when confirming the fixture.
3. **Fixture executed** - the one real, bounded Blender invocation.
4. **STL exists and is non-empty** - a plain filesystem check on the
   output path this module itself constructed.
5. **Factory mesh validation completed** - `validate_mesh()` reused
   directly; a `WARN` (e.g. "no printer config available") still counts
   as `qualified`, the same `pass`/`warn`/`fail` distinction Phase 44's
   OpenSCAD qualification already established. A `FAIL` does not.
6. **Factory preview render completed** - `render_preview()` reused
   directly; no Blender-specific render/visual-QA subsystem exists.
7. **Temporary artifacts cleaned** - the `TemporaryDirectory` context
   manager removes the directory on exit; this is verified with an
   explicit `Path.exists()` check, never assumed.

**Unexpected-file detection:** the temporary directory is inventoried
before and after the Blender invocation; any file besides the one
expected STL is reported as a warning (`unexpected_files`). Nothing can
escape the directory, since the output path is constructed by
`factory.blender_adapter`, never by the fixture script or any external
input.

`adapter_qualification_status` reaches `"qualified"` only when the
fixture executed, the STL validated `pass`/`warn` (never `fail`), and the
preview rendered `PASS`/`WARN` (never `FAIL`). **`project_execution_approved`
stays `false` on the result regardless of this outcome.**

## Default behavior - dry-run unless explicitly confirmed

`factory blender inspect` is fully read-only - zero subprocess calls.
`factory blender qualify` (no flag) runs exactly one bounded, real,
Python-free headless probe (`--version`) - no fixture is created, no temp
directory is made. Only `factory blender qualify --confirm-fixture`
additionally runs the real fixture pipeline above. Every invocation is
live - **no qualification state is persisted** between runs (the same
"do not persist by default" decision Phase 44 made for
`factory.tool_qualification`; see "Limitations" below for when a future
phase might reconsider this).

## Gate checklist reconciliation

`docs/blender-local-track.md`'s original 10-item "Required future gates
before implementation" checklist is preserved verbatim (never silently
reinterpreted) and reconciled additively against this phase's own
15-item checklist in `factory.blender_gate.reconcile_gate_checklist()`
(`factory blender inspect`/`qualify --verbose` both render it):

| # | New (Phase 45) item | Maps to original | Status | Why |
|---|---|---|---|---|
| 1 | Explicit human approval for Blender local execution phase | #1 | **partially satisfied** | Satisfied narrowly for this phase's one-shot, Factory-owned qualification-fixture pipeline only - this phase's own spec is the dated, explicit instruction that authorized it. **Not** satisfied for real project automation: `config/future_local_tools.json`'s `blender.enabled` stays `false`. |
| 2 | Blender path/version known | #2 | satisfied | Phase 43 detection + this phase's real `--version` corroboration. Still auto-discovered, not human-reviewed - see "Limitations". |
| 3 | Headless/background invocation verified | new | satisfied | One bounded, real, fresh-every-call `--version` probe. |
| 4 | Dry-run planning exists | #3 | satisfied | `plan_blender_fixture_execution()` - never launches Blender. |
| 5 | Output isolated to safe directories | #4 | **partially satisfied** | Satisfied for the fixture (temp dir only). A real project's `<project>/generated/blender/` convention is documented, not implemented. |
| 6 | Existing artifacts protected from overwrite | #5 | satisfied | The fixture never touches a project file - nothing to overwrite. A real workflow's refuse-by-default policy is documented, not implemented. |
| 7 | Provenance recorded | #6 | **deferred** | The fixture is never persisted as a project artifact - no `part_manifest.json` entry is written. Future mapping documented below. |
| 8 | Generated mesh validated through Factory validators | #7 | satisfied | `validate_mesh()` reused. "Before/after" (a repair-workflow concept) doesn't apply to fresh generation. |
| 9 | Generated mesh preview/render path verified | #8 | satisfied | `render_preview()` reused. Same "before/after doesn't apply to generation" note. |
| 10 | Review Gate remains required | #9 | satisfied | Unchanged - the fixture never enters any project pipeline. |
| 11 | No slicer/printer contact | #10 | satisfied | Verified by `tests/test_blender_adapter_safety.py`. |
| 12 | No network | #10 | satisfied | `--offline-mode` on every real invocation, plus the fixture script imports no network module. |
| 13 | Bounded subprocess execution | new | satisfied | Argument list, `shell=False`, hard timeout, captured output. |
| 14 | No arbitrary external Python | new | satisfied | Exactly one Factory-owned script; no override path exists. |
| 15 | Temporary fixture cleanup verified | new | satisfied | `TemporaryDirectory()` + explicit post-hoc `Path.exists()` check. |

## Provenance model (documented for a future phase, not implemented here)

A future real Blender-generated project artifact must record, in
`part_manifest.json` (the same discipline every other part's `source`
field already requires - `docs/licensing-policy.md`):

- Engine (`"blender"`) and Blender version/binary path (or a normalized
  engine identity).
- Workflow/template name.
- Factory version/phase that generated it.
- Source inputs and output files, with fingerprints.
- Execution timestamp, warnings, validation state.
- An explicit "no automatic print" declaration.

**No such receipt is ever written by this phase** - qualification
fixtures are throwaway evidence, not project artifacts. Building this is
future work, gated behind a real Blender project-generation phase (not
Phase 45), and must integrate with the existing Phase 34/35 generation-
receipt shape (`docs/file-lifecycle.md`) - never a new, unrelated receipt
model, and never destructively changing the existing OpenSCAD/CadQuery
receipt shape.

**Phase 49 writes exactly this receipt** for its one workflow -
`generated/blender_adaptation_receipt.json`, a sibling of
`generated/meshy_receipt.json`/`generated/export_receipt.json`, carrying
every field listed above (engine/version/path, workflow name, source
input and output artifact with fingerprints, timestamp, warnings,
validation state, and an explicit `no_automatic_print: true` /
`automatic_print_allowed: false` declaration). See
`docs/blender-adaptation.md`.

## Receipt and output-directory mapping for a future phase

A future real Blender workflow's output should land in
`<project>/generated/blender/` (never mixed into `stl/`/`renders/` as if
it were the existing local pipeline's own output), refuse to overwrite an
existing file by default (a future `--force`/`--overwrite-generated` flag
would need to be added deliberately, consistent with this repo's other
override conventions), and must still pass through
`factory.project_timeline`/`factory.artifact_history` additively, the
same way every other Phase 40/41-tracked artifact does - never a special
case that pollutes either with fixture-only noise. **None of this is
implemented in Phase 45** - qualification fixtures never touch a
project, so neither system is ever invoked by this phase.

**Phase 49 implements exactly this mapping**, for exactly one workflow
(`organic_cleanup_workflow`): `generated/blender/adapted/<stem>_adapted.stl`,
refuse-to-overwrite (no `--force` flag exists), and additive
`project_timeline`/`artifact_history` wiring. See
`docs/blender-adaptation.md`.

## Registry / qualification integration

`factory.engine_registry`'s static Blender record (Phase 43) is
unchanged. `factory.tool_qualification`'s Blender result (Phase 44) is
unchanged - still `metadata_only`/`requires_manual_qualification`.
`factory.blender_adapter.build_blender_report()` joins all three at
runtime (`gate` + `qualification`), the same "join, never rewrite"
pattern `docs/tool-qualification.md`'s own registry integration already
established. Nothing here rewrites Phase 43's static metadata based on
one machine's current qualification state.

## Project Health - unchanged

`factory.project_health`'s `health_score` computation is untouched by
this phase. A mechanical OpenSCAD project does not become "less healthy"
because Blender is absent or unqualified - engine availability is
separate from project health, unchanged from Phase 44's own rule.

## Preview Board - unchanged behavior, one more pointer line

The board-wide "Tool Environment" section (Phase 43/44) gains one more
static hint line pointing at `factory blender inspect`/`qualify` - never
a per-tool card, never an automatic qualification run as a side effect of
viewing the board. `factory.blender_adapter.run_fixture_qualification()`
is never called by `factory.preview_board`.

## Limitations

- Blender's path is still auto-discovered (Phase 43's `.app` bundle scan),
  not human-reviewed - the original checklist's "never an assumed or
  auto-discovered path" wording is only partially satisfied, exactly like
  the Phase 43 registry amendment already narrowed for detection purposes.
- `--factory-startup` does not guarantee zero add-on influence from the
  user's own preferences (see "Startup isolation" above) - a documented
  gap, not a claimed full isolation.
- No qualification history is persisted; every `factory blender qualify`
  call re-verifies live. If repeatedly running the fixture proves wasteful
  in practice, a future phase could add an explicit, machine-local,
  gitignored qualification record (never committed, never granting
  `project_execution_approved` by itself) - not built speculatively here.
- CadQuery-shaped "in-process capability test" reasoning does not apply
  to Blender - Blender Python always runs inside a separate `blender`
  process via `--python`, never imported into the Factory's own Python
  process.
- This phase proves the adapter can run one fixture once. It says nothing
  about performance at scale, concurrent invocations, or long-running
  Blender processes - out of scope until a real execution phase exists.

## No-authority rule

Read-only with respect to every project. Never writes to `examples/` or
`projects/`. Never modifies Homebrew, installs or upgrades Blender, adds
an add-on, or changes a Blender preference. Never contacts a slicer,
printer, or network (see `--offline-mode`). Never generates G-code. Never
sets `human_approved`/`print_ready`. `project_execution_approved` is
hardcoded `false` everywhere. See `docs/blender-local-track.md` for the
still-standing rules this phase narrows only for its own one-shot
qualification fixture, never for real project automation.

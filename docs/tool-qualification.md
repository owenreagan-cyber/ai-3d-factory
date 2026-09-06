# Local Tool Environment Qualification (Phase 44)

`factory.tool_qualification` answers a question `factory.engine_registry`
(Phase 43) deliberately does not: **"can this detected local tool actually
perform the minimum capability the Factory expects from it?"**

```
specialized probes -> factory.engine_registry -> factory.tool_qualification -> CLI / Preview Board
```

## Purpose

Phase 43 built the canonical registry and safe detection (path/PATH/
package-metadata checks, one bounded `openscad --version` probe). It
deliberately stopped there - every tool's `qualification_status` stayed
`not_tested`/`not_applicable`/`not_installed`. Phase 44 is the first phase
that gathers real evidence: it exercises a tool's actual documented
capability (in a narrow, bounded, temporary-fixture way) rather than just
checking that a binary exists.

## Detected != Qualified != Execution Approved

Three separate facts, never collapsed into one:

1. **Detected** (Phase 43) - a filesystem/PATH/package-metadata check
   found the tool locally. Says nothing about whether it works.
2. **Qualified** (this phase) - evidence was gathered by actually running
   (a bounded, temporary version of) the tool's expected workflow. A tool
   can be `detected: true` and `qualification_status: "not_installed"` is
   never possible, but `detected: true` with `qualification_status:
   "unqualified"` or `"requires_manual_qualification"` absolutely is - a
   tool that's present is not automatically a tool that works, or a tool
   this phase was willing to run further.
3. **Execution approved** - a human has explicitly turned on automation
   for that tool. **`execution_approved` is hardcoded `False` on every
   single result this module ever produces, with no code path that ever
   sets it `True`.** Qualification is evidence *for* a future approval
   decision (Phase 45 for Blender, a future phase for FreeCAD); it is
   never that decision itself.

A tool may legitimately be `detected: true`, `qualification_status:
"qualified"`, `execution_approved: false` all at the same time.

## Qualification levels

`metadata_only` < `cli_verified` < `capability_verified` <
`factory_workflow_verified`; `manual_required` is a parallel track for
tools this phase deliberately never probes further than metadata. Levels
are ordered by *how much was actually proven*, never by how "good" a tool
is:

- **`metadata_only`** - path + version only (from Phase 43's existing
  detection). Nothing was executed.
- **`cli_verified`** - the tool's CLI actually responded (e.g. a
  `--version` call succeeded).
- **`capability_verified`** - a real capability was exercised (a fixture
  was built and/or exported) but the full pipeline through Factory
  validation did not fully succeed.
- **`factory_workflow_verified`** - the complete
  fixture -> export -> `factory.validators.mesh_validate.validate_mesh()`
  pipeline succeeded (PASS or WARN). Only OpenSCAD (and CadQuery, if
  installed) can reach this level in this phase.
- **`manual_required`** - this phase deliberately never probes past
  metadata for this tool (Blender, FreeCAD, every slicer) or never
  qualifies it at all (the five deferred tools) - see below.

`qualification_status` (`qualified`, `partially_qualified`, `unqualified`,
`not_installed`, `not_tested`, `requires_manual_qualification`,
`probe_failed`, `unsupported`) is the headline verdict; `qualification_level`
records how far the evidence actually reached. `requires_manual_qualification`
is exactly the spec's own guidance: "if a tool cannot be meaningfully
qualified without visible GUI interaction, return this status - do not
launch it."

## Per-tool policy

### OpenSCAD (stable) - qualified end-to-end

The only tool this phase qualifies all the way to
`factory_workflow_verified`, because the Factory already uses it in
production (`factory.export_pipeline`). Five checks, each recorded
individually and shown in `factory engines qualify openscad_stable
--verbose`:

1. **Binary detected** - reuses `factory.engine_registry.probe_all_tools()`
   (which itself reuses `factory.export_pipeline.resolve_openscad_executable()`)
   - never a second lookup.
2. **CLI responds** - the version string `probe_all_tools(include_version_subprocess=True)`
   already obtained (the same safe, timeout-bounded `openscad --version`
   pattern `factory.export_pipeline._probe_tool_version()` established) -
   no second version subprocess call.
3. **Temporary SCAD exported** - one bounded `openscad -o <tmp>.stl
   <tmp>.scad` subprocess call against a fixed, hand-written `cube([10,
   10, 10]);` fixture, inside a `tempfile.TemporaryDirectory()`.
   Argument-list, `shell=False`, a hard timeout (30s - the fixture is
   trivial, so this is much shorter than `factory.export_pipeline`'s
   120s production export timeout).
4. **STL exists and is non-empty; Factory mesh validation completed** -
   `factory.validators.mesh_validate.validate_mesh()` (the exact function
   `factory.export_pipeline.run_validation()` calls in production) is
   called directly against the temporary STL. No report file is written -
   this module has no write path into any project.
5. **Temporary artifacts cleaned** - the `TemporaryDirectory` context
   manager removes the directory on exit; this is verified (not assumed)
   and reported honestly if it somehow didn't happen.

A validation result of `WARN` (e.g. "no printer config available" for a
fixture with no associated project) still counts as `"qualified"` - the
same `passed`/`passed_with_warnings` distinction
`factory.export_pipeline`'s own `validation_status` vocabulary already
draws. A validation `FAIL` downgrades the result to `"partially_qualified"`/
`"capability_verified"` (export worked, but the Factory doesn't consider
the result trustworthy) - never silently treated as full qualification.

### OpenSCAD (snapshot/development) - not distinguishable yet

No separate snapshot-channel detection path exists (see
`docs/engine-registry.md`) - the only local `openscad` binary found is
always attributed to `openscad_stable`. `openscad_snapshot` qualifies as
`not_installed` with a `skip`-status check explaining why. Building a
real second detection path (and only then deciding its qualification) is
explicitly future work - this phase never guesses.

### CadQuery - an in-process capability test, not "arbitrary Python"

If `factory.cad.backend.is_cadquery_available()` reports the package
importable, this phase runs an equivalent progressive check: a tiny,
fixed, deterministic `cadquery.Workplane("XY").box(10, 10, 10)` is
constructed in memory and exported to a temporary STL, then the same
`validate_mesh()` reuse as OpenSCAD applies.

**This is explicitly not the "arbitrary project Python" this repo's
`factory.cad.cadquery_backend` policy forbids executing.**
`factory.cad.cadquery_backend` never imports or executes the CadQuery
`.py` source *it writes for a project* - that policy is about untrusted,
project- or user-authored code. This phase's capability probe
(`factory.tool_qualification._run_cadquery_capability_probe()`) only
calls the already-installed, vetted `cadquery` library's own documented
API with fixed, hand-written qualification code - the same trust boundary
as importing any other already-installed Python dependency. It never
reads, imports, or evaluates any project's own generated CadQuery source.

CadQuery is not installed in this repo's own development environment;
every "package present" code path is exercised entirely by monkeypatched
tests (see `tests/test_tool_qualification_cadquery.py`).

### Blender and FreeCAD - metadata only, by standing policy

**Neither is ever passed to `subprocess` in this phase.**
`docs/blender-local-track.md`'s existing "no subprocess call, no headless
invocation" rule for Blender is treated as authoritative and binding
here, not just "uncertain enough to skip" - it is an explicit, standing
repository rule, and `factory.engine_registry` (Phase 43) already
extended the same rule to FreeCAD by symmetry. Qualification for both
stops at `metadata_only` (the path + `Info.plist` version Phase 43's
`probe_all_tools()` already computed) with a `skip`-status "Headless/CLI
probe" check recording exactly why, so the qualification result stays
fully explainable even though it stopped short. If detected,
`qualification_status` is `requires_manual_qualification` (never
`"qualified"`, never `"unqualified"` - a policy choice not to probe
further is neither a pass nor a failure). Whether a future bounded
headless probe is ever safe for either tool is a **Phase 45** gate
decision, never this phase's.

### Bambu Studio, OrcaSlicer, PrusaSlicer - metadata only, GUI-only tools

All three are `cli_available: False`/`gui_only: True` in the Phase 43
registry - no documented-safe headless flag exists for any of them in
this repo. Qualification stops at `metadata_only` (path + `Info.plist`
version) for the same reason as Blender/FreeCAD - `requires_manual_qualification`
if detected, `not_installed` otherwise. Never slices, never generates
G-code, never launches a GUI, never contacts a printer.

### Meshy, Plasticity, Autodesk Fusion, Onshape, Bambu Connect - deferred

`qualification_status: "unsupported"` **regardless of whether
`probe_all_tools()` happens to report one of these detected** (a GUI-only
app like Plasticity or Bambu Connect *could* be locally installed; that
alone still never qualifies it - "qualified merely because installed" is
exactly the conflation this phase's design principles forbid). None of
the five is ever executed, contacted, authenticated to, or has a
credential read. Meshy's cloud/cost/license gate is Phase 46; none of
that work happens here.

## Temporary fixture policy

Every real local-execution qualification (OpenSCAD, and CadQuery when
installed) happens entirely inside a `tempfile.TemporaryDirectory()` -
never inside `examples/`, `projects/`, an application directory, a user
profile directory, or a slicer profile directory. The directory (and
everything in it) is removed by Python's own context manager on exit;
`temporary_artifacts_cleaned` reports whether that actually happened
(verified via `Path(...).exists()`, never assumed) rather than always
claiming success. See `tests/test_tool_qualification_safety.py` for the
automated proof that no temporary fixture ever lands under `examples/`
or `projects/`.

## Persistence

**Qualification results are not persisted.** `factory engines qualify`
runs live every time and returns fresh results - there is no
`qualification_history.json` in this phase. Machine-specific values
(paths, versions, pass/fail) are expected to vary between runs and
machines; only the Phase 43 registry's own static metadata is
deterministic across environments. Whether persisting a qualification
history would help a future Phase 45 decision is noted as a possible
follow-up, not built here.

## CLI

```
factory engines qualify                       # every registered tool
factory engines qualify <tool_id>              # one tool only
factory engines qualify [--json] [--verbose]
```

`--verbose` shows every recorded check (with its evidence) and any
warnings/errors; the default human view shows only the headline
detected/version/qualification/level/execution fields plus the summary.
`--json` returns the full `{qualification_version, results, summary,
safety}` contract with no console text mixed in.

## JSON contract

```json
{
  "qualification_version": 1,
  "results": [ { "tool_id": "...", "...": "..." } ],
  "summary": {
    "total_tools": 13,
    "qualification_scope": 8,
    "qualified": 0,
    "partially_qualified": 0,
    "unqualified": 0,
    "not_installed": 0,
    "not_tested": 0,
    "manual_required": 0,
    "cloud_gated": 2,
    "unsupported": 5,
    "failed": 0,
    "execution_approved": 0
  },
  "safety": {
    "software_installed": false,
    "software_upgraded": false,
    "gui_launched": false,
    "network_used": false,
    "slicer_executed": false,
    "gcode_generated": false,
    "printer_contacted": false,
    "automatic_print_allowed": false
  }
}
```

`results` is always a list (a single entry when a `tool_id` is given), so
the shape is identical whether qualifying one tool or all thirteen.
Machine-specific values (paths, versions, statuses) are expected to vary
between environments - only `qualification_version` and the vocabulary
itself are guaranteed stable.

## Error handling

A per-tool qualification failure (a probe raising unexpectedly, a
validator error, a cleanup failure) is captured inside that tool's own
result (`qualification_status: "probe_failed"`, or an honest `errors`/
`warnings` entry) and never aborts the rest - `qualify_all_tools()`
always returns exactly 13 results, one per `factory.engine_registry.TOOL_IDS`
entry, regardless of what happened to any individual tool.

## Registry integration

Phase 43's registry stays stable and unchanged by this phase - no static
registry field is rewritten based on one machine's current qualification
result. A caller that wants both pictures joins them itself:
`factory.engine_registry.get_tool_registry()` (canonical metadata) plus
`factory.tool_qualification.qualify_all_tools()` (this run's evidence).

## Preview Board and Project Health

Neither integration runs qualification automatically - both would make
the Preview Board (regenerated freely, often) spawn a real subprocess as
a side effect of merely viewing it, which this phase explicitly forbids.
The board's existing "Tool Environment" section (Phase 43) gained exactly
one line pointing at `factory engines qualify` for real evidence; nothing
else changed. `factory.project_health` is entirely unchanged by this
phase - `health_score` never depends on local tool qualification. Any
future health integration is explicitly out of scope here and would need
its own design.

## Safety guarantees

- No install, no upgrade, ever.
- No GUI application launch, ever.
- No AppleScript/`osascript`, no `open`, no `pkill`, no GUI automation.
- Blender and FreeCAD are never passed to `subprocess`, in any form.
- No slicer execution, no G-code generation, no printer communication.
- No Meshy/Onshape network contact, no credential reads, no
  authentication.
- No Homebrew mutation, and no Homebrew subprocess call of any kind.
- Every real subprocess call this module makes (OpenSCAD only) uses an
  argument list, `shell=False`, and a hard timeout - proven in
  `tests/test_tool_qualification_safety.py` by spying on `subprocess.run`'s
  actual call arguments, not just reading the source.
- `execution_approved` is `False` on every result, with no override path.

## Limitations

- `detected_architecture` is not qualified in this phase (Phase 43's own
  limitation carries forward unchanged).
- The OpenSCAD stable/snapshot distinction still cannot be probed
  differently - both would resolve through the same
  `resolve_openscad_executable()` path if a snapshot were ever installed;
  a real second detection path remains future work.
- CadQuery's in-process capability test has never actually run against a
  real local installation in this repo's own development environment
  (`cadquery` is not installed here) - every "package present" path is
  exercised entirely through monkeypatched tests.
- Qualification results are point-in-time and machine-specific; nothing
  is cached or compared across runs in this phase.

## Phase 45 handoff

Blender: detected (`/Applications/Blender.app`, version `5.2.0` via
`Info.plist`), `qualification_level: "metadata_only"`,
`qualification_status: "requires_manual_qualification"`,
`execution_approved: false`. Every one of `docs/blender-local-track.md`'s
ten "Required future gates before implementation" remains unsatisfied -
this phase performed detection-adjacent evidence gathering only; it did
not seek, and could not grant, any of that checklist's approvals
(explicit human approval to enable automation, dry-run mode, output
directory isolation, provenance metadata, before/after validation/render,
etc.).

FreeCAD: not detected on this development machine
(`qualification_status: "not_installed"`). No headless-CLI capability was
probed (by the same no-subprocess policy as Blender) even in an
environment where FreeCAD is installed - a future phase choosing to build
a FreeCAD execution adapter starts from the same `metadata_only`
evidence level as Blender, with no scheduled adapter phase yet.

## No-authority rule

This module never overrides, recalculates, or replaces any decision an
existing module already makes - `factory.engine_registry`'s registry
metadata, `factory.design_orchestrator.recommend_engine()`'s
recommendation, and every existing approval-gate config stay exactly as
authoritative as before this phase. `tool_qualification` only adds
evidence on top of what Phase 43 already established.

See also `docs/engine-registry.md`, `docs/blender-local-track.md`,
`docs/meshy-approval-gate.md`, `docs/architecture.md`, `docs/roadmap.md`,
and `AGENT.md`.

# Blender local repair/render track (planning only, Phase 21)

**This document is a planning and safety scaffold. It does not implement
Blender automation.** No code in this repo launches Blender, imports a
Blender add-on, configures Blender MCP, or runs a Blender script. This
phase exists to write down, in advance, exactly what must be true before
the (not yet scheduled) "Blender local repair/render track" is allowed to
add real Blender automation - so the gate is designed before the feature,
not after, mirroring how `docs/meshy-approval-gate.md` (Phase 16) did the
same for Meshy.

## What the Blender track is, in this repo's context

Blender is a free, local, general-purpose 3D application - reserved in
`docs/roadmap.md`'s "Future tracks, not yet phase-numbered" section (the
"Blender local repair/render track", not a numbered phase) and
`docs/tool-routing.md` for **mesh repair, boolean operations, organic
mesh cleanup, and higher-fidelity visual renders** - never for measured
parametric parts (those stay OpenSCAD/CadQuery, per `AGENT.md`'s "Prefer
parametric CAD for measured parts").

- **Future-only.** `factory.cad.backend.get_backend_registry()` already
  lists `blender` with `status: "future"` - it has never been
  `"available"`.
- **Local, not cloud - but still gated.** Unlike Meshy, a future Blender
  integration would run entirely on this machine, with no network call
  and no per-use cost. That removes the cost/budget-cap and
  upload-review concerns `docs/meshy-approval-gate.md` requires, but
  every other concern (automation, provenance, trust, and the same
  validate/render/review-gate/human-review pipeline) still applies in
  full - "local" is not "automatically safe to trust."
- **Disabled by default, and will stay disabled by default.** Nothing in
  a future implementation may flip this on as part of "just building the
  feature" - enabling it is a separate, explicit, human decision. See
  `config/future_local_tools.json`.

## Hard rules that apply today, in this phase

- No Blender execution of any kind - no subprocess call, no headless
  invocation, no scripted `.blend` file processing.
- No Blender automation - nothing in this repo triggers Blender to run,
  on a schedule, on a file-system event, or as a side effect of any
  `factory` command.
- No Blender add-ons - none installed, none referenced as a dependency.
- No Blender MCP - not configured, not planned as a default.
- No background Blender execution - no daemon, no watch mode, no
  headless server process.
- No automatic repair acceptance - if Blender ever repairs a mesh, a
  human must review the before/after result before it's treated as the
  project's real geometry.
- No automatic render trust - a Blender-rendered preview is exactly as
  advisory as the existing `factory render` preview: it helps a human
  look at the part, it never substitutes for human slicer review.
- No automatic print-readiness inference from a Blender pass completing.
  A Blender-repaired or Blender-rendered mesh is exactly as "not
  print-ready" as any other mesh in this repo until it passes the same
  local validation/render/review-gate/human slicer review pipeline.
- No automatic `human_approved` setting - a future Blender pass, like
  Meshy, is a *geometry source or repair step*, never an approval. The
  part still needs its own separate `human_approved` sign-off after
  slicer review.
- The highest status any `factory` command may set automatically remains
  `slicer_review_ready` - unchanged by this phase, unchanged by any
  future Blender integration. See `config/agent_policy.json`'s
  `status_gates.max_automatic_status`.

## Intended future uses (not implemented yet)

1. **Local mesh repair planning.** Given a mesh `factory validate`
   flagged as non-manifold or otherwise broken, a future command could
   plan (not run) a Blender repair pass - explaining what it would try,
   never invoking Blender itself.
2. **Local higher-quality render generation.** An alternative to the
   existing `factory render` (trimesh + matplotlib quick preview) for a
   higher-fidelity visual, still entirely local, still never a substitute
   for opening the part in a slicer.
3. **Exploded/multipart assembly views.** A visual aid for multi-part
   projects (like `examples/multipart-classroom-sign/` and
   `examples/storage-bin-lid/`) showing how parts fit together - advisory
   only, same as the rest of `docs/visual-preview-package.md`'s human
   inspection checklist.
4. **Organic model cleanup after future approved/gated generation.** If
   the Meshy approval/cost-gated implementation track (`docs/roadmap.md`)
   is ever completed and produces a raw generated mesh, a future Blender
   pass could clean it up (retopology, manifold repair) before it enters
   the normal validate/render/review-gate pipeline - Blender never
   replaces that pipeline, it only feeds into it.
5. **No cloud dependency.** Every one of the above stays 100% local -
   Blender is a locally-installed application, not a service call.

## Required future gates before implementation

Before any future phase may implement actual Blender automation, **all**
of the following must exist and be reviewed - this list is the actual
gate, not just documentation about one:

1. **Explicit human approval to enable Blender automation.** A named,
   dated decision (not an inferred default) that Blender automation is
   turned on for this repo - the same spirit as
   `docs/meshy-approval-gate.md`'s first requirement.
   `config/future_local_tools.json`'s
   `tools.blender.requires_explicit_human_approval` records that this
   approval has not happened yet.
2. **Local Blender path/version check.** Before any invocation, a
   read-only check that a specific, human-confirmed local Blender
   installation exists and is a compatible version - never an assumed or
   auto-discovered path (see `config/future_local_tools.json`'s
   `requires_local_path_review`).
3. **Dry-run mode.** Every new Blender-invoking command must support a
   dry-run that shows exactly what it would do (which file, which
   operation, expected output path) without launching Blender, before the
   real mode is trusted.
4. **Output directory isolation.** Blender-produced files write to their
   own clearly-named subdirectory (e.g. `blender_output/` or similar),
   never mixed into `stl/`/`renders/` as if they were the existing local
   pipeline's own output, until a human has reviewed them.
5. **No overwriting original meshes.** A repair pass writes a new file
   alongside the original - it never replaces or deletes the
   human-authored or previously-validated source mesh.
6. **Repaired mesh provenance metadata.** Any Blender-touched part's
   `part_manifest.json` entry must record what happened (e.g. `"source":
   "Blender repair (approved <date>) from <original file>"`), the same
   discipline `docs/licensing-policy.md` and
   `part_manifest.schema.json`'s `source` field already require for every
   part.
7. **Before/after validation reports.** `factory validate` must run (and
   be shown to a human) on both the pre-repair and post-repair mesh, so a
   "repair" that silently makes geometry worse is visible, not hidden.
8. **Before/after render previews.** Same idea for `factory render` (or a
   future Blender-based render) - a human should be able to visually
   compare before and after, not just trust a "repair succeeded" message.
9. **`factory review-gate` remains required.** A Blender pass changes
   *where geometry comes from or how it looks*, never *what happens to it
   afterward* - the part still needs to pass `review-gate` and then human
   slicer review before `human_approved`, exactly like every other part.
10. **No slicer/printer communication.** A future Blender integration is
    scoped to mesh repair and rendering only - never slicing, never
    sending a file to a printer, never discovering printers. See
    `config/future_local_tools.json`'s `allows_printer_or_slicer_calls`.

## Design-quality review for Blender outputs

Future Blender work is not just repair/automation - it must preserve or
improve the design quality `docs/design-quality-standard.md` ("Etsy-worthy":
polished, intentional, useful, gift-worthy, display-worthy) requires, the
same standard `docs/meshy-approval-gate.md`'s "Design-quality gate"
applies to Meshy output:

- Cleanup should improve shape clarity, not erase character - a repair
  pass that manifolds a mesh by shaving off the features that made it
  recognizable has traded one failure (bad geometry) for another (a
  generic blob).
- Repairs should not destroy intentional style details - the
  before/after validation/render comparison this doc already requires
  (see "Required future gates before implementation" above) exists
  precisely so a human can catch this, not just confirm the mesh is now
  watertight.
- Renders should help assess silhouette, proportions, and polish - a
  higher-fidelity Blender render is only useful if a human actually uses
  it to judge those things, not just to confirm "something rendered."
- Organic models (animals, figures, decorative objects) should be
  checked against the Etsy-worthy standard in
  `docs/design-quality-standard.md`'s artistic/organic track - the same
  piggy-bank-style bar `docs/meshy-approval-gate.md` applies to Meshy
  output applies here too, regardless of which tool touched the mesh
  last.
- Functional objects (clips, brackets, organizers) should be checked
  against `docs/design-quality-standard.md`'s functional/mechanical
  track - a Blender repair pass on a functional part must not silently
  change wall thickness, flex geometry, or fit in ways that break the
  function, and the part remains a prototype until physically tested,
  same as any other functional design.

## What this phase does not do

- Does not launch Blender, import a Blender add-on, or configure Blender
  MCP.
- Does not add Blender (or any Blender-Python binding) to
  `pyproject.toml`'s dependencies.
- Does not implement repair, render, or cleanup logic of any kind.
- Does not change `factory.cad.backend`'s `blender` entry's `status` from
  `"future"`.
- Does not grant any of the approvals in the checklist above - it only
  writes down what they must be, so a future phase can be checked against
  this list instead of inventing the gate under time pressure.

## Read-only inspection

`factory check-local-tools` reads `config/future_local_tools.json` and
reports Blender's current gate status. It never launches Blender, never
searches for a local Blender installation (not even a read-only
`/Applications` scan), never calls `subprocess`, never installs anything,
and never enables anything - see `src/factory/future_local_tools.py`.

## Phase 43 amendment - registry-level path detection

Phase 43 (`docs/engine-registry.md`) added `factory.engine_registry`, a
**different module** from `factory.future_local_tools`/`factory
check-local-tools`, which does perform a read-only `.app` bundle/`PATH`
detection check for Blender - the same technique
`factory.slicer.local_slicer_probe.probe_slicers()` already uses for
slicers. This is a narrow, deliberate amendment to this document's
original "never searches the filesystem for an installed application,
not even a read-only `/Applications` scan" note, scoped to
`engine_registry` only:

- `factory.future_local_tools.py`/`factory check-local-tools` are
  **unchanged** - they still read `config/future_local_tools.json` only,
  with no filesystem discovery of their own.
- `factory.engine_registry` may look for a local Blender installation by
  path (and, if found, read its version from `Info.plist` - a plain file
  read, never process execution), purely to answer "is this tool
  detected on this machine?" for the registry's own inventory purpose.
- Every hard rule above is preserved in full: **no subprocess call, no
  headless invocation, no launch** of Blender by `engine_registry`
  either. Detection is not automation, and detecting a path is not the
  same as trusting, launching, or scripting the application that lives
  there.

See `docs/engine-registry.md`'s "Blender and FreeCAD: local, near-term,
never executed" for the full detail.

## Phase 44 amendment - qualification stops at metadata only, still no subprocess

Phase 44 (`docs/tool-qualification.md`) added `factory.tool_qualification`,
which gathers real evidence for most other in-scope tools (a bounded
local-execution test for OpenSCAD, an equivalent in-process capability
test for CadQuery). **Blender is deliberately excluded from that deeper
treatment.** This document's "no subprocess call, no headless invocation"
rule (see "Hard rules that apply today, in this phase" above) is treated
as authoritative and binding for `factory.tool_qualification` too, not
just "uncertain enough to skip" - qualification for Blender stops at
`qualification_level: "metadata_only"` (the same path + `Info.plist`
version Phase 43's `probe_all_tools()` already computed), with a
`skip`-status "Headless/CLI probe" check recording exactly why, so the
result stays fully explainable even though it stopped short.
`qualification_status` is `"requires_manual_qualification"` when
detected (never `"qualified"`, never `"unqualified"` - a policy choice
not to probe further is neither a pass nor a failure), and
`execution_approved` stays `false` regardless. Whether a future bounded
`blender --background --version` probe is ever safe to add remains a
**Phase 45** gate-review decision, never something a qualification phase
decides on its own.

## Phase 45 amendment - a bounded, one-shot fixture execution path, still no project automation

Phase 44 named this document's "no subprocess call, no headless
invocation" rule the standing, binding policy for Blender - and
explicitly named **Phase 45** as the gate-review phase that would decide
whether a bounded headless probe is ever safe to add. This is that
review, and its answer is narrow: **`factory.blender_gate`/
`factory.blender_adapter` add exactly two real Blender invocations - a
`--version` headless probe and one `--background` run of a single,
fixed, Factory-owned, repository-reviewed qualification-fixture script
(`blender_fixtures/factory_qualification_fixture.py`) - never a project
file, never a user- or project-supplied script, never real project
automation.**

Every hard rule above stays in force for real project use:

- **No Blender automation on any actual project** - this phase's Blender
  invocations only ever target one throwaway qualification fixture in a
  `tempfile.TemporaryDirectory()`. No project file is ever read, written,
  or repaired by this phase.
- **No Blender add-ons, no Blender MCP** - unchanged. No `--addons` flag
  is ever passed.
- **No automatic repair acceptance, render trust, print-readiness
  inference, or `human_approved` setting** - unchanged; this phase
  produces no repair, no project render, and touches no project status at
  all.
- **`config/future_local_tools.json`'s `blender.enabled` stays `false`,
  and `requires_explicit_human_approval` stays `true`** - this phase does
  not flip either. The one-shot qualification-fixture pipeline this phase
  adds is authorized narrowly by this phase's own spec (a dated, explicit
  human instruction), which is a different, narrower thing than
  "Blender automation is enabled for real project use" - that remains a
  separate, later, explicit decision this document's original checklist
  still gates in full.
- **`factory.cad.backend`'s `blender` entry's `status` stays `"future"`**
  - unchanged by this phase, exactly as this document's original "what
  this phase does not do" section required.

See `docs/blender-adapter.md` for the full gate-checklist reconciliation
(the original 10-item list above, mapped item-by-item against a new
15-item Phase 45 checklist), the exact subprocess/startup-isolation/
Python-execution safety policy, and why the fixture script deliberately
lives outside `src/` (so `import bpy` never appears in the repo-wide scan
`test_no_blender_execution_code_anywhere_in_src()` below still runs
against).

**Phase 48 addendum:** `factory.hybrid_workflow` recommends a Blender
adaptation step for organic (Meshy-origin) artifacts, always carrying
`evaluate_blender_execution_gate()`'s real `gate_status`/
`project_execution_approved` verbatim - it never claims Blender is ready
to execute a real project when this gate says otherwise, and it never
imports `factory.blender_adapter` (the only module that actually invokes
Blender). A recommended step is a plan a human reviews, not a bypass of
anything above. See `docs/hybrid-workflow.md`.

## Phase 49 amendment - one real, gated project-artifact workflow, `config/future_local_tools.json` still untouched

Phase 45 authorized exactly two real Blender invocations, both against a
throwaway fixture, never a project file. **Phase 49 is the "future,
later, explicit decision" this document's checklist item 1 and Phase
45's own gate-checklist item 1 both named** - the first real Blender
execution against a real project artifact in this repo. Its answer is
just as narrow as Phase 45's: **exactly one workflow
(`organic_cleanup_workflow`: import a Meshy/CAD-origin STL, apply one
explicit uniform scale factor, export a new child STL), never mesh
repair, remeshing, decimation, smoothing, or any other broader
automation.**

Consistent with every hard rule above, still in force for this narrower
real-project use:

- **`config/future_local_tools.json`'s `tools.blender.enabled`/
  `allows_automation`/`allows_background_execution` stay `false`** -
  this phase's own dated spec is the explicit human instruction that
  narrowly authorizes `organic_cleanup_workflow`, the same pattern
  Phase 45's spec used for its fixture pipeline, never a standing
  "automation is on" state. Every real execution requires a fresh
  `--confirm` on that exact call; nothing is cached or persisted between
  calls, and no code path flips this config.
- **Output directory isolation, no overwrite** - a real adapted artifact
  writes to `<project>/generated/blender/adapted/`, never `stl/`/
  `renders/`, and never overwrites the original input artifact or an
  existing output file.
- **Provenance recorded** - `generated/blender_adaptation_receipt.json`
  records engine/version, workflow, source input and output artifacts
  with fingerprints, and human-confirmation state.
- **Before/after validation and preview** - the adapted output is
  re-validated (`factory.validators.mesh_validate.validate_mesh()`) and
  re-previewed (`factory.previews.render_preview.render_preview()`) -
  both reused, never a Blender-specific implementation.
- **`factory review-gate` remains required, no slicer/printer contact** -
  unchanged; a Blender-adapted artifact is exactly as "not print-ready"
  as any other mesh until it passes the same pipeline.
- **No repair acceptance, no automatic `human_approved`/`print_ready`** -
  unchanged; scale/orientation adaptation is not a design-quality
  judgment, and this phase makes none.

See `docs/blender-adaptation.md` for the full gate design (the fresh,
never-cached fixture-qualification-proof-before-real-execution model),
the exact subprocess/safety policy for the second Factory-owned Blender
script, and why `config/future_local_tools.json` is deliberately left
unchanged.

See also `config/future_local_tools.json`, `docs/roadmap.md`'s "Blender
local repair/render track", `docs/design-quality-standard.md`,
`docs/meshy-approval-gate.md`, `docs/tool-routing.md`,
`docs/cad-backends.md`, `docs/safety-gates.md`, `config/agent_policy.json`,
`docs/engine-registry.md`, `docs/tool-qualification.md`,
`docs/blender-adapter.md`, `docs/hybrid-workflow.md`,
`docs/blender-adaptation.md`, and `AGENT.md`.

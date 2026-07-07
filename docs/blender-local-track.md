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

See also `config/future_local_tools.json`, `docs/roadmap.md`'s "Blender
local repair/render track", `docs/tool-routing.md`, `docs/cad-backends.md`,
`docs/safety-gates.md`, `config/agent_policy.json`, and `AGENT.md`.

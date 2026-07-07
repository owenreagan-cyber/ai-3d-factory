# Meshy approval and cost gate (design only, Phase 16)

**This document is a design and safety scaffold. It does not implement
Meshy.** No code in this repo calls Meshy, imports a Meshy SDK, or reads a
Meshy API key. This phase exists to write down, in advance, exactly what
must be true before any future phase is allowed to add that integration -
so the gate is designed before the feature, not after.

## What Meshy is, in this repo's context

Meshy is a third-party, paid, cloud-hosted generative-mesh API - reserved
in `docs/roadmap.md` (Phase 16, "optional Meshy, with approval/cost
gates") and `docs/tool-routing.md` for **organic concept generation
only** (cars, animals, people, and other sculptural/organic forms that
don't fit parametric CAD - see `docs/tool-routing.md`'s "Prefer
parametric CAD for measured parts" note in `AGENT.md`).

- **Future-only.** `factory.cad.backend.get_backend_registry()` already
  lists `meshy` with `status: "future_gated"` - it has never been
  `"available"`.
- **Cloud/paid/API-backed.** Every call would leave this machine, cost
  money, and depend on a third-party service being up. That is a
  fundamentally different trust boundary than every other backend in this
  repo (OpenSCAD, CadQuery), which run entirely local, offline, and free.
- **Disabled by default, and will stay disabled by default.** Nothing in
  a future implementation may flip this on as part of "just building the
  feature" - enabling it is a separate, explicit, human decision. See
  `config/future_cloud_tools.json`.

## Hard rules that apply today, in this phase

- No API key for Meshy (or any other paid/cloud service) exists anywhere
  in this repo, in `.env`, `.env.example`, `config/`, or any committed
  file. `.env.example` documents `MESHY_API_KEY` as a commented-out,
  empty, **not approved for use yet** placeholder only - see
  `tests/test_safety_policy.py::test_env_example_has_no_uncommented_secret_values`.
- No automatic upload of any file to Meshy or any other service.
- No automatic generation call of any kind.
- No automatic acceptance of generated mesh output - a human must review
  every generated asset before it's used for anything.
- No automatic print-readiness inference from a generated mesh existing.
  A Meshy-generated mesh is exactly as "not print-ready" as a hand-authored
  one until it passes the same local validation/render/review-gate/human
  slicer review pipeline every other part in this repo goes through.
- No automatic `human_approved` setting - Meshy usage itself needs a
  separate human approval (see the checklist below) *and* the resulting
  part still needs the normal `human_approved` sign-off after slicer
  review, same as any other part. These are two different approvals for
  two different things.
- The highest status any `factory` command may set automatically remains
  `slicer_review_ready` - unchanged by this phase, unchanged by any future
  Meshy integration. See `config/agent_policy.json`'s
  `status_gates.max_automatic_status`.

## Required future gate checklist

Before any future phase may implement actual Meshy calls, **all** of the
following must exist and be reviewed - this list is the actual gate, not
just documentation about one:

1. **Explicit human approval for using Meshy at all.** A named, dated
   decision (not an inferred default) that Meshy usage is turned on for
   this repo. `config/future_cloud_tools.json`'s
   `tools.meshy.requires_explicit_human_approval` records that this
   approval has not happened yet.
2. **Explicit cost/budget cap.** A hard, human-set limit (e.g. "$X per
   month" or "N credits") that the tool refuses to exceed, checked
   *before* any call is made, not just logged after the fact.
3. **Explicit per-run confirmation.** Every individual Meshy call requires
   its own human "yes, generate this" - no batch/background/automatic
   generation, no "generate this whole project's parts" without a
   confirmation per part.
4. **Explicit input review before upload.** A human reviews exactly what
   would be sent to Meshy (prompt text, any reference image, any
   parameters) before it leaves the machine - no silent uploads of
   project data, student names, or other local content.
5. **Explicit output review after generation.** A human visually inspects
   every generated mesh before it's treated as usable project geometry -
   same spirit as the existing "human visual inspection required" line
   every preview/report command already prints.
6. **Local storage policy for generated assets.** Where generated
   meshes/textures get written (which project subdirectory), how they're
   named, and whether/how they're distinguished from hand-authored
   `cad/`/`stl/` content in `part_manifest.json` (e.g. a `source` value
   like `"Meshy (approved <date>)"`, the exact phrasing
   `part_manifest.schema.json`'s `source` field already documents as an
   example).
7. **License/ownership notes.** What rights the generated mesh actually
   carries, whether Meshy's terms of service allow the intended use
   (educational, personal print, etc.), and how that's recorded per-part
   in `part_manifest.json`'s `source`/`license` fields - same discipline
   `docs/licensing-policy.md` already requires for every part.
8. **Student/privacy/data notes.** Since this tool may be used in a
   classroom context (see `examples/multipart-classroom-sign/` and
   `examples/future-organic-models/`), a explicit policy on what data
   (names, photos, personal descriptions) may or may not be sent to a
   third-party API, and default-to-no unless a specific use has been
   reviewed.
9. **Fallback local-only path.** If Meshy is unavailable, over budget, or
   simply not approved for a given use, the tool must degrade to "use
   OpenSCAD/CadQuery, or ask a human to model this by hand" - never to
   "silently skip validation" or "guess at organic geometry locally."
10. **Clear restatement that generated output still requires the full
    pipeline.** A Meshy-generated mesh is not exempt from anything: it
    still needs `factory validate`, `factory render`,
    `factory review-gate`, and human slicer review before
    `human_approved`, exactly like every other mesh in this repo. Meshy
    changes *where geometry comes from*, never *what happens to it
    afterward*.

## What this phase does not do

- Does not call Meshy, import a Meshy SDK, or add one to
  `pyproject.toml`'s dependencies.
- Does not add any API key, `.env` value, or network configuration.
- Does not implement upload, generation, or acceptance logic of any kind.
- Does not change `factory.cad.backend`'s `meshy` entry's `status` from
  `"future_gated"`.
- Does not grant any of the approvals in the checklist above - it only
  writes down what they must be, so a future phase can be checked against
  this list instead of inventing the gate under time pressure.

## Read-only inspection

`factory check-future-tools` (see `docs/architecture.md`) reads
`config/future_cloud_tools.json` and reports each future cloud tool's
gate status. It never reads `.env`, never validates credentials, never
makes a network call, and never enables anything - see
`src/factory/future_cloud_tools.py`.

See also `config/future_cloud_tools.json`, `docs/roadmap.md` Phase 16,
`docs/tool-routing.md`, `docs/licensing-policy.md`, `docs/safety-gates.md`,
`config/agent_policy.json`, and `AGENT.md`.

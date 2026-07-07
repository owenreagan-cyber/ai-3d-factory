# Product vision (long-term, not yet built)

This document describes where `ai-3d-factory` is headed. **Nothing in this
document is implemented.** It exists so future work (this repo's or a future
agent's) has a stable target to build toward incrementally, instead of the
CLI's shape drifting phase-to-phase without a destination. See
`docs/roadmap.md` for what's actually shipped.

## The current CLI is the engine, not the product

Everything built through Phase 4 - `factory status/init-project/plan/
list-options/choose-option/generate-openscad/validate/render/inspect-slicer/
report` - is a local, scriptable **engine**. It is deliberately
terminal-first: no windows, no daemons, no background processes. That was
the right starting point (fast to build, easy to test, trivially safe to
reason about), but it is not the intended long-term user experience for
day-to-day use.

## The vision

> **Owen's AI 3D Factory**: a local-first visual manufacturing assistant for
> designing, planning, previewing, validating, and preparing 3D-printable
> projects for human review.

The engine stays exactly as safe as it is today - everything below is a
*view onto* the same local JSON files and the same CLI commands, never a
replacement for the human-approval boundary in `AGENT.md`. A prettier
surface does not get to skip `docs/safety-gates.md`.

## Future access surfaces (not implemented)

None of the following exist yet. They are listed so a future implementation
phase has a menu of "how a human might actually launch this" to choose from,
without any one of them being assumed as the only path:

- **Mac app launcher** - a small native or web-wrapped app that shells out to
  the same `factory` CLI commands this repo already has.
- **Dock icon** - a way to open the launcher without a terminal.
- **Apple Shortcuts or Automator wrapper** - for triggering common flows
  (e.g. "plan this project") outside a terminal session.
- **A "Chief of Staff" command** - a single entry point that surfaces "what
  needs my decision right now" across all projects (unresolved manufacturing
  options, WARN/FAIL validation reports, missing manifest entries) - a
  cross-project view `factory report` doesn't attempt today since it's
  scoped to one project directory.
- **Local visual dashboard** - a local (not cloud-hosted) web view over
  `projects/`, read-only unless a human takes an explicit action.
- **Transferable setup for another MacBook Pro M4** - the whole point of
  keeping this local-first and config-driven (see
  `docs/manufacturing-knowledge-base.md`) is that moving to new hardware
  should mean "clone the repo, reinstall the toolchain via
  `ai-3d-factory-installer`," not "reconfigure a cloud account."

## Future visual requirements (not implemented)

These describe *what a future UI needs to show*, not how to build it:

1. **Mesh preview** - render an STL/mesh file to a PNG for quick visual
   review. (A first, minimal version of this already exists as
   `factory render`'s matplotlib preview - the future version is
   higher-fidelity, not a new concept.)
2. **CAD source preview** - render OpenSCAD/CadQuery source to a preview
   image without requiring a human to open OpenSCAD themselves first.
3. **Manufacturing option preview** - a visual, side-by-side comparison of
   one-piece vs. multipart vs. detail-split vs. color-split options (the
   same data `factory list-options` already prints as text - see
   `docs/manufacturing-knowledge-base.md` - rendered instead of read).
4. **Multipart/exploded preview** - show each part of a multi-part assembly
   separately, their shared origin, an exploded-assembly view, and
   color/material labels per part (from `part_manifest.json`).
5. **Planning board** - a visual surface listing manufacturing options with
   pros/cons, printer fit (build volume, AMS/multicolor availability),
   material/color implications, and explicit human decision
   buttons/checklist - a visual front-end for the exact decision `factory
   choose-option` already records as text.

Phase 5's `factory list-printers`/`show-printer`/`list-accessories`/
`show-accessory`/`list-materials`/`show-material`/`fleet-summary` (see
`docs/manufacturing-knowledge-base.md`) are the read-only data layer a
future Planning board or fleet view would call - they already return
structured, human-readable knowledge-base data; a future UI renders it
instead of printing it.

Phase 6's `preview_package/index.json` (see `docs/visual-preview-package.md`)
is the read/write data layer for requirements 1, 2, and 4 above: it already
lists every CAD/mesh/render file, every manifest part, and every missing or
stale artifact by relative path - a future UI reads that file and renders
the images it references, instead of re-deriving this file-scanning logic.

## Future reserved commands (documented, not implemented)

These command names are reserved for the future UI/launcher track. **They do
not exist in `factory` today** - do not attempt to call them, and do not add
stub implementations that print "not implemented" (that's speculative
surface area this repo doesn't need yet):

| Reserved command | Future purpose |
|---|---|
| `factory serve` | Would start a local (not internet-exposed) web server hosting the visual dashboard - reads project JSON, never a print/slicer/network gateway. |
| `factory open` | Would open the Mac app launcher or local dashboard for a given project. |
| `factory launcher-info` | Would report what launcher/UI surfaces are installed and how to reach them (analogous to `factory inspect-slicer`, but for this repo's own future UI, not a slicer). |

`factory preview-project` was reserved here in Phase 4 but is now implemented
(Phase 6) - see `docs/visual-preview-package.md`. Its actual scope is
narrower than originally speculated above: it aggregates existing
CAD/STL/render/manifest files into a `preview_package/index.json` +
`preview_report.md` for a human (or future UI) to read; it does not itself
render new mesh/CAD-source/exploded-view images - those remain future UI
work per the visual requirements above.

## What does not change

Every boundary in `AGENT.md` and `docs/safety-gates.md` carries forward
unchanged into any future UI:

- No auto-print, from a CLI command or a future dashboard button alike.
- No printer discovery or printer/slicer communication - a visual dashboard
  reads local JSON/config, the same way `factory report` does today.
- No cloud services, no paid APIs, no MCP.
- `human_approved` and `print_ready` still require an explicit human action;
  a future UI's "approve" button is that explicit action, not a bypass of
  it.
- The highest status any `factory` command (CLI or future UI) may set
  automatically remains `slicer_review_ready`.

See `docs/roadmap.md` for how future phases are expected to sequence toward
this vision.

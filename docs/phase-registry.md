# Phase registry

A flat, at-a-glance list of every completed phase - number, title, commit
(where known), status, and a one-line note. Manually maintained, kept in
sync with `docs/roadmap.md`'s "Completed phases" section (that document
has the full write-up per phase; this one is just the index). See
`docs/roadmap.md`'s "Roadmap numbering policy" for how numbers are
assigned and why this file exists.

Not a database, not generated - a plain text table, updated by hand
whenever a phase completes.

| # | Title | Commit | Status | Notes |
|---|---|---|---|---|
| 0/1 | Foundation | - | complete | CLI, schemas, local mesh validation/preview, read-only slicer discovery, project scaffolding. |
| 2 | CAD generation helpers | - | complete | `factory generate-openscad`, 4 templates. |
| 3 | Manufacturing knowledge & printer-aware planning | - | complete | `config/manufacturing/`, decision engine. |
| 4 | Human manufacturing decision workflow + product vision foundations | - | complete | `list-options`/`choose-option`; `docs/product-vision.md`. |
| 5 | Manufacturing knowledge maintenance | - | complete | Read-only knowledge-base inspection commands. |
| 6 | Visual preview package foundation | - | complete | `preview-index`/`preview-project`. |
| 7 | CAD backend routing & CadQuery starter | - | complete | `route-cad`, `generate-cadquery --template mechanical-plate`. |
| 8 | Local visual preview board foundation | - | complete | `preview-board`. |
| 9 | Local render coverage and multi-part preview improvements | - | complete | `render-coverage`, `plan-renders`. |
| 10 | Preview board action suggestions | - | complete | `suggested_actions` on board cards. |
| 11 | Preview board health signals | - | complete | `health_signals` rollup. |
| 12 | Local review gate command | - | complete | `factory review-gate`. |
| 13 | Shared project inspection refactor | - | complete | `factory/project_inspection.py` extracted. |
| 14 | Local example project library foundation | 9de3c3c | complete | `examples/simple-nameplate`, `examples/mechanical-plate`, `examples/future-organic-models/`. |
| 15 | Multipart example project | 9808dcc | complete | `examples/multipart-classroom-sign/`. |
| 16 | Meshy approval/cost gate design | 469e697 | complete | `docs/meshy-approval-gate.md`, `config/future_cloud_tools.json`, `factory check-future-tools`. Design only - no Meshy implementation. |
| 17 | Fix example test side effect | a1b1116 | complete | Stopped `preview-project` tests from mutating committed `examples/`. |
| 18 | Guard tests from mutating committed examples | a5d02c3 | complete | `tests/test_examples_write_safety.py` static guard. |
| 19 | Storage bin lid example project | c1895ad | complete | `examples/storage-bin-lid/`. |
| 20 | Roadmap numbering and phase registry cleanup | 5ed4f1f | complete | This document; roadmap numbering policy; future tracks unnumbered. |
| 21 | Blender local track planning scaffold | 1382d57 | complete | `docs/blender-local-track.md`, `config/future_local_tools.json`, `factory check-local-tools`. Planning only - no Blender implementation. |
| 22 | Connect design quality standard to future gates | a586924 | complete | Cross-references `docs/design-quality-standard.md` into `docs/meshy-approval-gate.md` and `docs/blender-local-track.md`. Docs only - no implementation. |
| 23 | Human review quality checklist | deb28fb | complete | `docs/review-gate.md`'s "Human review quality checklist"; matching updates to `docs/slicer-review-workflow.md`, `docs/preview-board.md`, `docs/visual-preview-package.md`, `README.md`. Docs only - `review-gate` behavior unchanged. |
| 24 | Design intent brief schema planning | (this phase) | complete | `docs/design-intent-brief.md`; additive `design_intent` shape; two concept examples illustrate it. Docs/planning only - no schema or product code changed. |

## Future tracks (not phase-numbered)

See `docs/roadmap.md`'s "Future tracks, not yet phase-numbered" section
for the full write-up of each. Listed here only so this registry shows
what's *not* yet a numbered phase, at a glance:

- Meshy approval/cost-gated implementation track
- Blender local repair/render track
- 3MF packaging experiments track
- Advanced slicer review automation track
- Rich organic examples track
- Custom Design Quality Pipeline
- Mac launcher/dashboard track

## Maintaining this file

When a phase completes: add one row above with its number, title, commit
hash (if this session captured one), `complete`, and a one-line note.
Never reuse or renumber an existing row. When a future track above is
actually started, move it out of "Future tracks" and into the numbered
table with the next available number - not a number that may have been
informally associated with it earlier.

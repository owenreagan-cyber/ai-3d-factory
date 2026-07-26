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
| 24 | Design intent brief schema planning | 2826680 | complete | `docs/design-intent-brief.md`; additive `design_intent` shape; two concept examples illustrate it. Docs/planning only - no schema or product code changed. |
| 25 | Design intent manufacturability check | 1ee322a | complete | `factory/design_intent_check.py`, `factory check-design-intent`. Read-only advisory `max_size_mm` vs. known printer build volumes; no approval/print-readiness behavior. |
| 26 | Design intent visibility in project reports | 8e3efaf | complete | `summarize_design_intent()`; `factory report`'s `Design Intent:` section; `design_intent_summary` field on preview-board project entries. Visibility only - `review-gate` unchanged, no approval/scoring/print-readiness behavior. |
| 27 | Design intent preview board visualization | ca8df64 | complete | `describe_design_intent_for_board()`; `design_intent_detail` field on preview-board project entries; a per-project "Design Intent" HTML card (design intent, manufacturing overview, artifact/review badges). Visualization only - JSON/report compatibility preserved, no approval/scoring/print-readiness behavior. |
| 28 | Source discovery and reference board planning | 94f3176 | complete | `factory/reference_board.py`; `reference_board_summary` field on preview-board project entries; a compact "Reference Board" HTML card. Planning/data-model only - no web crawling, scraping, search, downloading, or API integration; every `source_url` is inert metadata, never fetched. |
| 29 | Reference Board CLI management | 2ed579f | complete | `factory reference-board init/show/validate/add/list`; `init_reference_board()`/`add_reference()`/`normalize_references()` in `factory/reference_board.py`. Local-only CLI on top of Phase 28's model - no search/scraping/downloading/API calls; advisory validation never fails on incomplete data, only on malformed JSON. |
| 30 | Intelligent project intake engine | 17e40f9 | complete | `factory/project_intake.py`; `factory intake analyze`; `intake_summary` field on preview-board project entries; a "Project Intake" HTML card; `examples/intake-benchmarks/teacher-nameplate.md`. Fully deterministic keyword/regex heuristics only - no AI, no LLM, no network, no CAD generation. |
| 31 | Intake-to-brief draft generation | 270acb9 | complete | `factory/brief_generator.py`; `factory intake suggest-brief [--json] [--write] [--force]`; `draft_brief_summary` field on preview-board project entries; a "Draft Brief" HTML card. Confidence-gated draft generation only - never re-parses free text, never writes without explicit `--write`, never overwrites an existing `brief.json` without `--force`. |
| 32 | Brief update / merge workflow | 1c3c2a3 | complete | `merge_draft_brief()`/`apply_merge()`/`write_merged_brief()` in `factory/brief_generator.py`; `factory intake suggest-brief --update [--write]`; `brief_update_summary` field on preview-board project entries; a compact "Brief Update" HTML card. Safe merge only - never overwrites existing human-authored content, `--force`/`--update` mutually exclusive, malformed existing brief refused rather than guessed. |
| 33 | Project readiness dashboard & design orchestrator | (this phase) | complete | `factory/design_orchestrator.py`; `factory readiness [--json]`; `design_orchestrator_summary` field on preview-board project entries; a "Project Readiness" HTML dashboard (summarizes, doesn't replace, existing cards). Deterministic readiness scoring + engine recommendation only - no CAD generation, no engine execution, reuses `factory.router.recommend_tool()` rather than a second keyword table. |
| 34 | Readiness-Gated CAD Generation Router | 724a81d | complete | `factory/generation_gate.py`; `factory generate-from-readiness [--confirm-generate] [--json]`; `generation_gate_summary`/`generation_execution_summary` fields on preview-board project entries; a "Generation Gate" HTML card section (Decision/Engine/Ready/Reason/Receipt available/Last execution). Execution receipts (`generated/generation_receipt.json`, confirmed runs only) and normalized artifact tracking, reusing existing OpenSCAD/CadQuery generators and manifest/validation infrastructure rather than duplicating them - no CAD backend of its own, no Blender/Meshy/FreeCAD execution. |
| 35 | Guided Export, Validation, Preview, and Artifact Finalization | 266796c | complete | `factory/export_pipeline.py`; `factory export-from-cad [--confirm-export] [--json] [--source ...] [--output-dir ...] [--overwrite-stl] [--validate] [--render] [--all] [--resume]`; `export_pipeline_summary` field on preview-board project entries; a "Post-Generation Pipeline" HTML card section. First automated subprocess execution in this repo (OpenSCAD CLI export only, argument-list, timeout-bounded, full post-exit verification) - CadQuery source remains manual-only by existing policy. Execution receipts (`generated/export_receipt.json`, upserted per source file, a sibling of Phase 34's receipt) and an artifact registry, reusing the existing mesh validator/renderer/manifest checks rather than duplicating them. |
| 36 | Slicer Review Readiness Promotion and Review Package | aa54f53 | complete | `factory/slicer_readiness.py`; `factory slicer-readiness <project> [--json] [--create-package] [--confirm-package] [--output-dir ...] [--approve] [--approval-note ...] [--refresh] [--include-warnings] [--force-package]`; `slicer_readiness_summary` field on preview-board project entries (wired via `preview_board.gather_board_data()`, not `project_inspection.summarize_project()` - see "Architectural note" in `docs/slicer-readiness.md`); a "Slicer Review Readiness" HTML card section. A deterministic, weighted (never blocker-overriding) readiness score; a separate human-approval lifecycle with fingerprint-based invalidation; a local review package (`slicer_review/slicer_review_manifest.json`, conforming to the pre-existing `schemas/slicer_review.schema.json`) referencing existing STL/validation/render artifacts rather than copying them. Reuses `factory.review_gate`, `factory.export_pipeline`'s receipts, `factory.manufacturing.manifest`, and `factory.slicer.local_slicer_probe` rather than duplicating any of them - never slices, uploads, queues, or prints anything; `auto_print_allowed` is always `false`. |
| 37 | Slicer Profile Inspection & Manual Review Workspace | (this phase) | complete | `factory/manual_review_workspace.py`; `factory review-workspace <project> [--json] [--create-workspace] [--confirm-workspace] [--output-dir ...] [--force-workspace]`; `manual_review_summary` field on preview-board project entries (wired via `preview_board.gather_board_data()`, same architectural pattern as Phase 36 - see "Architectural note" in `docs/manual-review-workspace.md`); a "Manual Review Workspace" HTML card section. Organizes everything a human needs before opening a slicer on top of Phase 36's already-computed readiness: local printer/material profile inspection (never inventing an unknown value, e.g. layer height, which this repo's knowledge base never records), a structured multi-category review checklist, and a deterministic review_confidence/remaining_risk pair. Reuses `factory.slicer_readiness.assess_slicer_readiness()` and `factory.manufacturing.knowledge` rather than duplicating either - never slices, generates G-code, or prints anything. |

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

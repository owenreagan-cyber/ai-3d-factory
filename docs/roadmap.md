# Roadmap

Automatic printing is never a default behavior in any phase below. Every
phase adds capability up through "ready for human slicer review" — the
human-approval and print-initiation boundary in `AGENT.md` does not move.

## Roadmap numbering policy (Phase 20)

Several early phases assigned fixed numbers to not-yet-started future work
(Meshy, Blender, 3MF, slicer-review automation). As soon as an ad hoc
phase actually needed one of those numbers, the placeholder had to be
renumbered - which then broke every doc/README that had already cited the
old number. This happened repeatedly (Phase 15, Phase 16, and Phase 19 each
displaced an already-numbered placeholder). The policy below exists to
stop that churn:

1. **Completed (or in-progress/"started") phases keep their assigned
   number, permanently.** Never renumber a phase that has already been
   implemented, even partially - see "Completed phases" below. Cross-references
   to a completed phase's number (e.g. "see Phase 16") are stable and safe
   to keep.
2. **A new ad hoc phase uses the next integer after the highest number in
   "Completed phases" below** - not a number "reserved" for a future idea.
   Check `docs/phase-registry.md` (or the bottom of "Completed phases"
   here) for the current highest number before assigning a new one.
3. **Future work that has no scheduled start does not get a phase number
   at all.** It goes in "Future tracks, not yet phase-numbered" below,
   named as a track (e.g. "Blender local repair/render track"), and is
   only promoted to a numbered phase once someone actually starts it - at
   which point it takes the next available number per rule 2, not a number
   pre-reserved for it earlier.
4. **Docs referencing a future track use the track's name, not a phase
   number.** Only cite a phase number for work that has actually started
   (rule 1).

See `docs/phase-registry.md` for a flat, at-a-glance list of every
completed phase (number, title, commit, status) kept in sync with the
"Completed phases" section below.

## Completed phases

## Phase 0/1 (this repo, current)

Foundation: CLI (`factory`), JSON schemas, local mesh validation, local
preview rendering, read-only slicer discovery, project scaffolding.

## Phase 2 — CAD generation helpers (started)

OpenSCAD and CadQuery generation helpers: turn a build plan / part
manifest into starter parametric CAD source under `cad/`, and export it to
`stl/`. Still fully local; no AI call required to export geometry, though
an AI-assisted authoring step may propose the CAD source for human review.

**Started:** `factory generate-openscad` writes local, parametric `.scad`
source for four templates (`test-cube`, `nameplate`, `sign`,
`multipart-nameplate`) into a project's `cad/`, keeps
`slicer_review/openscad_export_instructions.md` and `part_manifest.json`
in sync, and advances `brief.json` status to `cad_generated`. See
`docs/openscad-generation.md`. STL export itself is still a manual,
human-run step (no automatic OpenSCAD invocation yet).

**Not yet started:** any automated, locally-validated OpenSCAD export
command. (CadQuery generation helpers were implemented later, in Phase 7 —
see below.)

## Phase 3 — manufacturing knowledge & printer-aware planning (started)

A local manufacturing knowledge base (`config/manufacturing/`: printers,
materials, accessories, planning rules) and a deterministic decision engine
that turn `factory plan` into a manufacturing advisor, not just a tool
router. See `docs/manufacturing-knowledge-base.md` for the full write-up.

**Started:** `factory plan` now resolves `brief.json`'s `intended_printer`
against a multi-printer fleet (`config/manufacturing/printers.json`),
explains every manufacturing option (single-piece, multipart for build
volume/color/detail/painting/strength, replaceable components) with
advantages/disadvantages and a non-binding recommendation
(`factory.manufacturing.decision_engine`), and seeds `part_manifest.json`
with planning-time placeholders (`factory.manufacturing.manifest`) without
ever overwriting a human edit or a later phase's real values.
`factory.validators.multipart_check` gained duplicate-name, duplicate-output,
missing-CAD-source, invalid-quantity, and shared-origin-consistency checks.
`factory report` now surfaces target printer/accessories/build volume,
every manufacturing option, the recommendation, manifest/multipart/
validation summaries, and every remaining human decision.

**Not yet started (at the time):** `factory add-printer` / `factory
add-accessory` commands (the knowledge base is hand-edited JSON for now),
automatically proposing a `required_parts` breakdown once a human confirms
a multi-part option, and reconciling the Phase 0/1 single-printer
`config/printers.json` with the Phase 3 fleet-aware
`config/manufacturing/printers.json` (resolved in Phase 5 - see below).

## Phase 4 — human manufacturing decision workflow + product vision foundations (started)

The human-in-the-loop half of Phase 3's decision engine: a workflow for
Owen to explicitly choose one of the manufacturing options `factory plan`
already explains, plus long-term product vision documentation for a future
visual/launcher experience (not built yet). See `docs/product-vision.md`.

**Started:** `factory list-options <project_dir>` prints every
manufacturing option from `build_plan.json` (advantages, disadvantages,
availability, recommendation, current selection) plus every unanswered
question. `factory choose-option <project_dir> <option_id>` records an
explicit human choice into `build_plan.json`'s `selected_manufacturing_option`
- typing a specific option id *is* the human confirmation that option
requires - without touching any other build_plan field, and advances
`brief.json`'s status forward-only to the new `manufacturing_option_selected`
status (never past it automatically; never to `human_approved`/`print_ready`).
`factory.manufacturing.manifest.compute_assembly_intent()` reflects the
selected option in `part_manifest.json` as a computed `assembly_intent`
summary - if the option implies a multi-part approach but `required_parts`
is still just a placeholder, it says so plainly ("Selected option implies
multipart planning, but detailed required_parts are still incomplete")
instead of fabricating a part breakdown. `factory report` now shows the
selected option (or the unresolved-decision state), that assembly-intent
summary, and whether CAD generation can proceed safely.
`docs/product-vision.md` documents the intended long-term visual
app/launcher direction and reserves (but does not implement) `factory
serve`/`open`/`preview-project`/`launcher-info`. (`preview-project` was
later implemented in Phase 6 - see below.)

**Not yet started:** any actual UI/launcher/dashboard code, automatically
proposing a `required_parts` breakdown once multipart is confirmed (still a
manual follow-up by design - see Phase 3's "not yet started" list), and
`factory add-printer`/`factory add-accessory`.

## Phase 5 — manufacturing knowledge maintenance (started)

Makes the manufacturing knowledge base inspectable, validated, and ready for
future UI/launcher workflows - no CadQuery, no UI, no printer control or
hardware discovery. See `docs/manufacturing-knowledge-base.md`.

**Started:** `config/manufacturing/printers.json` is now the sole canonical
printer source - the old Phase 0/1 `config/printers.json` was removed once
`factory validate`'s build-volume-fit check was redirected to read from the
canonical fleet via `factory.manufacturing.knowledge`. Seven new read-only
commands make the knowledge base directly inspectable: `factory
list-printers`/`show-printer <id>`, `list-accessories`/`show-accessory <id>`,
`list-materials`/`show-material <id>`, and `fleet-summary` (a compact view of
all four printers). `factory check-manufacturing` validates
`config/manufacturing/*.json` for internal consistency (unique/consistent
ids, required printer fields, positive build volumes/nozzle sizes, known
accessory/material references, planning-rule option ids) with PASS/WARN/FAIL
output - see `factory.manufacturing.check`. All of the above are read-only:
no file writes, no project-state changes, no hardware discovery, no network.
`config/manufacturing/fleet_state.example.json` documents (as an example
only, not live data) a future structure for tracking each printer's current
setup (installed nozzle/build plate, loaded materials, spool slots) as
distinct from its fixed capabilities - not read by any command yet.

**Not yet started:** `factory add-printer` / `factory add-accessory`
commands; wiring `fleet_state`/current-setup data into the planner or
decision engine; reconciling `config/materials.json` with
`config/manufacturing/materials.json`; any UI/launcher code (still the
Future track below). (CadQuery generation helpers were implemented later,
in Phase 7.)

## Phase 6 — visual preview package foundation (started)

Strengthens the visual review workflow without building the full UI: a
project-level preview package that aggregates existing CAD/STL/render/
manifest state for a human (and a future dashboard) to review. See
`docs/visual-preview-package.md`.

**Started:** `factory preview-index <project_dir>` (read-only) and
`factory preview-project <project_dir>` (writes) build/refresh
`preview_package/index.json` + `preview_package/preview_report.md` -
project name/status, target printer, selected manufacturing option, CAD/
mesh/render file lists, manifest parts, multipart state, missing visual
artifacts, stale-preview detection (by comparing a render's file mtime
against its source STL's), and a static, advisory human visual inspection
checklist (`factory.preview_package`). Neither command renders a new image,
invokes OpenSCAD, exports an STL, or contacts a printer/slicer/network; the
package only references existing files by relative path, never copies a
render. `factory report` now shows whether a preview package exists and its
CAD/mesh/render/missing-item counts. Every preview command/report ends with
"Human visual inspection required." in addition to the existing "Human
slicer review required."/"Project is NOT print-ready." lines.

**Not yet started:** any UI/dashboard actually rendering `index.json`
(still the Future track below); CAD-source-to-image or manufacturing-option
visual rendering (still speculative Future-track requirements); wiring
staleness/missing-artifact detection into a blocking gate (it stays
advisory-only by design).

## Phase 7 — CAD backend routing & CadQuery starter (started)

A small, deterministic CAD-backend registry (`factory.cad.backend`) and a
read-only routing command that explains which CAD backend a project's
description points to — today's implemented backends (OpenSCAD, CadQuery)
versus reserved future ones (Blender, Meshy) — without generating anything.
See `docs/cad-backends.md`.

**Started:** `factory route-cad <project_dir>` (`factory.cad.router`) reuses
`factory.router.recommend_tool()` (the existing OpenSCAD/CadQuery/Blender/
Meshy keyword categories) so routing logic isn't duplicated, and reports a
primary recommendation, implementable-now backend(s), and any future-only
needs. `factory generate-cadquery --template mechanical-plate`
(`factory.cad.cadquery_backend`) is a CadQuery starter backend: a
parametric rectangular plate with optional corner fillets, mounting holes,
and an engraved label, written as local `.py` source into `cad/` — mirroring
`factory generate-openscad`'s shape (export instructions in
`slicer_review/`, `part_manifest.json` upsert, forward-only `brief.json`
status advance to `cad_generated`). CadQuery is an optional dependency:
this repo never installs it, and the command fails with a clear,
non-crashing error if it isn't already importable in the environment. Like
OpenSCAD, it writes source only — exporting to STL is a manual, human-run
step; nothing here imports or executes the CadQuery source it writes.

**Not yet started:** any CadQuery template beyond `mechanical-plate`;
automated, locally-validated CadQuery export.

## Phase 8 — local visual preview board foundation (started)

A local, static, multi-project preview board that helps Owen visually
inspect project state across the whole workspace before trusting generated
CAD/STL output - one step short of the full Future-track visual
workspace/launcher, and deliberately not a server or cloud app. See
`docs/preview-board.md`.

**Started:** `factory preview-board <projects_root>` (`factory.preview_board`)
scans every project subdirectory under `projects_root` and writes a static
`preview_board/index.json` + `preview_board/index.html` (self-contained:
inline CSS only, no external JS/CDN/remote assets/tracking). It reuses
`factory.preview_package` for the per-project file scan (reads an existing
`preview_package/index.json` when present, otherwise computes an
equivalent summary on the fly via `gather_preview_data()` without writing
into that project) instead of duplicating the scan, and classifies each
project into one of six deterministic visual-readiness states
(`needs_brief`, `cad_source_ready`, `needs_stl_export`, `needs_render`,
`slicer_review_ready`, `blocked_or_incomplete`). It never writes to a
project's `brief.json`/`build_plan.json`/`part_manifest.json`, never
generates CAD, renders, or exports geometry, never invokes OpenSCAD,
CadQuery, a slicer, or Blender, and never contacts a printer/network. The
highest state it reports is `slicer_review_ready` - it never computes or
implies `human_approved`/`print_ready`.

**Not yet started:** wiring the board into any UI/dashboard beyond the
static HTML file itself (still the Future track below); a `--watch`/
auto-refresh mode (deliberately out of scope - static-only by design).

## Phase 9 — local render coverage and multi-part preview improvements (started)

Improves local visual trust for projects with multiple STL files: a
read-only comparison of `stl/*.stl` against `renders/*.png` so it's
immediately clear which meshes are missing a preview, which previews are
stale, and which render files are orphaned - without generating or
rendering anything itself. See `docs/render-coverage.md`.

**Started:** `factory.render_coverage.compute_render_coverage()` is the
single shared implementation both `factory render-coverage <project_dir>`
(human-readable report, or `--json` for machine-readable output) and
`factory plan-renders <project_dir>` (lists suggested `factory render
<stl_path>` commands - never runs them) are built on. It's deterministic
(pure `Path.glob`/`Path.stat`, no writes) and reused - not duplicated - by
`factory.preview_package.gather_preview_data()` (three new additive
fields: `render_coverage`, `missing_renders`, `all_meshes_have_renders`;
every pre-Phase-9 field is unchanged) and by `factory preview-board`
(each project's card gets a `render_coverage` field, always freshly
computed). The board's visual-readiness classification was refined:
partial render coverage (some, not all, meshes missing a render) now
correctly resolves to `needs_render` rather than being missed; a stale
render moves a project to `blocked_or_incomplete`; an orphan render never
blocks readiness by itself (advisory warning only). `human_approved`/
`print_ready` are never computed or implied anywhere in this phase - the
highest automatic status remains `slicer_review_ready`.

**Not yet started:** any UI/dashboard rendering this data beyond the
existing static preview board and CLI text/JSON output. (Suggested
next-step commands were added later, in Phase 10 - see below.)

## Phase 10 — preview board action suggestions (started)

Makes the static preview board actionable, not just informational: each
project card gets a deterministic `suggested_actions` list of safe,
copyable local commands for the human to consider running next. See
`docs/preview-board.md`'s "Suggested next steps" section.

**Started:** `factory.preview_board.build_suggested_actions()` maps a
project's already-computed `visual_readiness_state` to exactly one set of
structured suggestions (`kind`, `label`, `command`, `safety:
"manual_only"`, `reason`) - `create_brief_missing`, `generate_cad_source`,
`export_stl_manual`, one `render_missing_mesh` per gap (built on
`factory.render_coverage.missing_and_stale_mesh_paths()`, the same
function `factory plan-renders` uses, so the two never drift),
`review_slicer_manually` (explicitly "do not slice-and-send or print
yet"), or `inspect_blocked_project` (reason names the actual cause -
corrupt JSON, a stale render, or a flagged artifact). The board's HTML
gained a "Suggested next steps" section rendering each command in a
`<pre><code>` block - plain text only, no JavaScript, no copy button, no
automatic execution of anything. No action ever suggests printing,
slicing-and-sending, uploading, or calling a cloud/paid API, Meshy, or
Blender; none set `human_approved`/`print_ready`.

**Not yet started:** any richer UI around these suggestions (still the
Future track below) - the board stays a single static HTML file. (Health
signals - a rollup summary plus validation-coverage awareness - were
added later, in Phase 11 - see below.)

## Phase 11 — preview board health signals (started)

Rolls up everything worth flagging about a project into one deterministic
`health_signals` field per board card - missing/unreadable `brief.json`/
`part_manifest.json`, an unselected manufacturing option, a stale/missing/
unreadable `preview_package/index.json`, render coverage gaps, and (new)
local `validation/` report coverage - so Owen can scan many projects at a
glance instead of reading every warning individually. See
`docs/preview-board.md`'s "Health signals" section.

**Started:** `factory.preview_board.build_health_signals()` returns
`{"summary": "ok"|"attention_needed"|"blocked", "items": [...]}`, each
item carrying a `kind`, `severity` (`info`/`warning`/`blocked`/`ready`),
`message`, and an optional `suggested_action_kind` hint. Severities are
built to always agree with `classify_visual_readiness()`'s own precedence
(e.g. a stale render is `"blocked"` because that's exactly the condition
that resolves the project to `blocked_or_incomplete`; a missing brief is
`"warning"`, matching its own distinct, non-blocked `needs_brief` state).
The only `"ready"` signal (`slicer_review_ready`) explicitly means "ready
for human slicer review, not print-ready" - never an approval. This phase
also adds local, read-only validation-report-coverage checking (mirroring
`factory validate`'s own `validation/<name>_validation.json` naming
convention, never running validation itself) and extends
`build_suggested_actions()` with one orthogonal `validate_mesh_manual`
suggestion (`factory validate <path>`) per un-validated STL, applied
regardless of visual-readiness state. The board's HTML gained a "Health
signals" section (severity-colored badges, plain text, no JavaScript) and
a compact "Health" column in the summary table. `human_approved`/
`print_ready` are never computed or implied.

**Not yet started:** deeply parsing validation report contents beyond
presence/absence (deliberately out of scope - `factory report` already
does PASS/WARN/FAIL rollup for a single project).

## Phase 12 — local review gate command (started)

A deterministic local pre-flight check: is a project ready for a
**human** to review it in a slicer? See `docs/review-gate.md`.

**Started:** `factory review-gate <project_dir>` (`--json` for
machine-readable output; `factory.review_gate.evaluate_review_gate()`)
reuses `factory.preview_board.summarize_project()` rather than
re-deriving brief/manifest/render/validation state - it reads the
already-computed `health_signals` items by `kind` and applies its own
pass/warn/fail policy, deliberately stricter in one place than the
board's general-purpose health check: a missing render is only a
"warning" on the board (the fix is simple, `factory render`), but is a
hard blocker for this gate, since there's nothing to visually review in a
slicer without one yet. Everything else (missing/unreadable brief,
unreadable manifest, stale renders, an unreadable preview package, orphan
renders, missing validation, an unselected manufacturing option) keeps
the same blocking/warning split the health signals already use; "no STL
files at all" is checked directly. `pass` means only "ready for human
slicer review" - the status ceiling stays `slicer_review_ready`, and
`human_approved`/`print_ready` are never computed or implied. Exit code
is `0` for pass/warn, `1` for fail.

**Not yet started (at the time):** wiring a compact `review_gate` field
back into `factory preview-board`'s per-project cards - at Phase 12,
doing so would have needed `preview_board.py` to import from
`review_gate.py` while `review_gate.py` already imported
`summarize_project` from `preview_board.py`, a circular module import.
(Resolved in Phase 13 - see below - though the board integration itself
remains a deliberate scope decision, not yet done.)

## Phase 13 — shared project inspection refactor (started)

An internal architecture cleanup: extracts the shared, read-only,
single-project classification logic out of `preview_board.py` into its
own module, so `review_gate.py` no longer needs to import
`preview_board.py` at all - removing the circular-import pressure noted
in Phase 12. No user-facing behavior change; existing CLI output and
JSON shapes are unchanged (verified by tests). See `docs/architecture.md`'s
"Shared inspection layer" note.

**Started:** `factory/project_inspection.py` now owns
`summarize_project()`, `classify_visual_readiness()`,
`build_suggested_actions()`, `build_health_signals()`, and the
`VISUAL_READINESS_STATES`/`HEALTH_SEVERITIES`/`ACTION_SAFETY` constants -
moved out of `preview_board.py` unchanged (same logic, same behavior).
`preview_board.py` now imports these from `project_inspection.py` (and
re-exports them for backward compatibility with existing
`from factory.preview_board import ...` call sites - the literal same
function/constant objects, not copies) and keeps only project discovery,
board aggregation, and JSON/HTML rendering. `review_gate.py` now imports
`summarize_project` from `project_inspection.py` directly and no longer
imports `preview_board.py` at all. The dependency graph is one-directional
and acyclic: `render_coverage`/`preview_package` → `project_inspection` →
{`preview_board`, `review_gate`}.

**Not yet started:** actually wiring a compact `review_gate` field into
board cards - the circular-import blocker that prevented it is gone, but
that integration remains a separate, deliberate future decision.

## Phase 14 — local example project library foundation (started)

A permanent local `examples/` library demonstrating the `ai-3d-factory`
workflow with safe, committed sample projects — deliberately inserted
ahead of Meshy (Phase 16 below) as a safe, dependency-free detour: it
exercises the existing CAD/preview/review-gate/preview-board commands
against real committed examples before any organic-generation backend
exists. See `docs/examples-library.md`.

**Started:** `examples/simple-nameplate/` and `examples/mechanical-plate/`
are real, runnable workflow examples — the first built with `factory
generate-openscad --template nameplate`, the second a hand-authored
OpenSCAD file mirroring the built-in CadQuery `mechanical-plate`
template's parameters (CadQuery isn't installed in this environment).
Both stop at the CAD-source stage (`cad_generated`, no STL committed) and
are compatible with `factory preview-index`/`preview-project`/
`review-gate`/`preview-board` (`review-gate` correctly `FAIL`s on both —
there's no STL yet). `examples/future-organic-models/{car-concept,
animal-concept,human-figure-study}/` are concept-only roadmap placeholders
(`concept_brief.json`, not `brief.json`, so existing commands don't treat
them as real projects) for the organic-modeling directions the Meshy
approval/cost-gated implementation track and the Blender local
repair/render track (both below, neither phase-numbered yet) will
eventually implement — no CAD, mesh, render, or generated asset exists
for any of them. `factory list-examples`/`show-example <name>`
(`factory/examples_library.py`) is a small, read-only, statically
registered inspection command for the whole library. No example sets
`human_approved`/`print_ready`; the highest status any example reaches
automatically is `cad_generated` (a human can locally advance a working
example to `slicer_review_ready` — see each example's own `README.md`).

**Not yet started (at the time):** growing the library further (richer 3D
models, Blender workflows once the Blender local repair/render track is
scheduled, Meshy-gated concepts once the Meshy approval/cost-gated
implementation track is scheduled, multipart classroom/manufacturing
demos) — this phase was deliberately just the structure and first two
working examples. (A multipart example was added later, in Phase 15 —
see below.)

## Phase 15 — multipart example project (started)

Extends the Phase 14 examples library with a richer local demo: a
multi-part assembly (base + text + accent badge, sharing one origin) as an
explicit baseline pattern for future richer multi-part models (cars,
animals, people, classroom/manufacturing demos). Still no STL/PNG/binary
asset committed anywhere. See `docs/examples-library.md`.

**Started:** `examples/multipart-classroom-sign/` — a 3-part assembly
(`cad/base.scad`, `cad/text_layer.scad`, `cad/badge.scad`), hand-authored
since no built-in `factory generate-openscad` template covers more than
the existing 2-part `multipart-nameplate` shape. `base.scad` also has 4
optional corner mounting holes. `part_manifest.json` lists all 3 parts
with `shared_origin: true` and matching `transform_notes` on every part
(the badge marked `required_for_assembly: false`, since it's an optional
accent) — the same shared-origin convention `docs/slicer-review-workflow.md`
already documents. Like the other two working examples, it stops at the
CAD-source stage (`cad_generated`, no STL/PNG committed) and is compatible
with `factory preview-index`/`preview-project`/`review-gate`/
`preview-board` (`review-gate` correctly `FAIL`s — no STL yet;
`preview-project` correctly reports `multipart_state.multi_part: true`).
`factory/examples_library.py`'s registry gained a `multipart-classroom-sign`
entry (`status: "cad_generated"`, a new registry status value alongside
Phase 14's three) and `ExampleInfo.status`'s allowed values were extended
to include it.

**Not yet started (at the time):** any further growth of the library
(richer 3D models, Blender workflows once the Blender local repair/render
track is scheduled, Meshy-gated concepts once the Meshy approval/cost-gated
implementation track is scheduled) — this phase was deliberately just the
one new multipart example. (A second multipart example, a practical
household/classroom utility object, was added later, in Phase 19 - see
below.)

## Phase 16 — Meshy approval/cost gate design (started)

Designs (but does not implement) the approval/cost gate a future,
not-yet-scheduled Meshy integration for organic concept generation would
have to satisfy - gated behind an explicit per-use human approval step and
a visible cost/credit estimate before any call is made, off by default.
See `docs/licensing-policy.md` and `docs/tool-routing.md`. The actual
Meshy-calling implementation is tracked as the (unnumbered) "Meshy
approval/cost-gated implementation track" below, not as a future numbered
phase - see "Roadmap numbering policy" above.

**Started (design only - no Meshy implementation):** `docs/meshy-approval-gate.md`
documents the full required future gate checklist (explicit human
approval, a cost/budget cap, per-run confirmation, input review before
upload, output review after generation, a local storage policy for
generated assets, license/ownership notes, student/privacy/data notes, a
local-only fallback if Meshy is unavailable/too expensive, and a
restatement that generated output still needs `factory validate`/
`render`/`review-gate`/human slicer review). `config/future_cloud_tools.json`
is a local, non-secret policy scaffold recording Meshy's gate state
(`enabled: false`, `status: "future_gate_required"`, and which of the
above requirements are still outstanding) - no API key, URL, or provider
SDK config. `factory check-future-tools` (`factory/future_cloud_tools.py`)
is a small, read-only, additive command that reports this state; it never
reads `.env`, validates credentials, makes a network call, or enables
anything. `examples/future-organic-models/{car-concept,animal-concept,
human-figure-study}/` (Phase 14) now each reference this gate directly
from their `README.md` and `concept_brief.json`.

**Not yet started:** any actual Meshy call, SDK dependency, API key,
upload, generation, or mesh-acceptance logic - none of the approvals the
checklist requires have been granted, and this phase deliberately grants
none of them. `config/future_cloud_tools.json`'s `enabled` flag stays
`false` until a human edits it as a separate, explicit, reviewed decision.

## Phase 17 — fix example test side effect (started)

Test hygiene: `tests/test_examples_library.py`'s `preview-project` CLI
test had been invoking the real `factory preview-project` command
directly against the committed `examples/multipart-classroom-sign/`
path, regenerating that example's `preview_package/{index.json,
preview_report.md}` `generated_at`/`Generated:` timestamp on every test
run and leaving the working tree dirty. No product behavior changed.

**Started:** the offending test now copies the example into `tmp_path`
first (`shutil.copytree`) and runs `factory preview-project` against that
copy - never against the committed path directly. A companion regression
test hashes the committed `preview_package/` files before/after to prove
they're untouched.

**Not yet started (at the time):** a repo-wide guard preventing the same
mistake elsewhere in the test suite - added next, in Phase 18.

## Phase 18 — guard tests from mutating committed examples (started)

Test hygiene: a lightweight, repo-wide static guard so no future test can
accidentally repeat Phase 17's mistake. No product behavior changed.

**Started:** `tests/test_examples_write_safety.py` scans every
`tests/test_*.py` file's source text for the call shape `runner.invoke(
app, ["<write-capable-command>", "examples/...")` (also catching
f-strings) - a write-capable `factory` CLI command (`plan`,
`choose-option`, `generate-openscad`, `generate-cadquery`, `validate`,
`render`, `preview-project`, `preview-board`) invoked directly against a
literal committed `examples/...` path. Read-only commands
(`list-examples`, `show-example`, `review-gate`, `preview-index`,
`check-future-tools`, ...) are always allowed against `examples/` and
never flagged. The module's own self-tests exercise the detector against
sample source strings, including the exact Phase 17 bug pattern.

**Not yet started:** semantic (non-regex) analysis - the guard can't see
through variable indirection, and only guards `CliRunner`-level
invocations, not a test calling a write function directly. Accepted gaps
for a lightweight, explainable guard.

## Phase 19 — storage bin lid example project (started)

Extends the Phase 14/15 examples library with a second multi-part
example, this time a practical household/classroom utility object rather
than signage - a labeled storage-bin lid. Still no STL/PNG/binary asset
committed anywhere; still no CAD backend beyond OpenSCAD. See
`docs/examples-library.md`.

**Started:** `examples/storage-bin-lid/` - a 3-part assembly
(`cad/lid_panel.scad`, `cad/raised_label.scad`, `cad/pull_tab.scad`),
hand-authored since no built-in `factory generate-openscad` template
covers a bin-lid shape. `lid_panel.scad` includes a downward-facing
friction-fit lip inset from the outer edge (sized to sit inside a bin's
opening), demonstrating that the multi-part shared-origin pattern
`multipart-classroom-sign/` (Phase 15) introduced generalizes beyond flat
signage. `part_manifest.json` lists all 3 parts with `shared_origin: true`
and matching `transform_notes` (the label and pull tab marked
`required_for_assembly: false`, since a bare lid is still functional).
Like every other working example, it stops at the CAD-source stage
(`cad_generated`, no STL/PNG committed) and is compatible with `factory
preview-index`/`preview-project`/`review-gate`/`preview-board`
(`review-gate` correctly `FAIL`s - no STL yet). `factory/examples_library.py`'s
registry gained a `storage-bin-lid` entry (`status: "cad_generated"`,
same shape as `multipart-classroom-sign`'s entry). Phase 18's write-safety
guard (`tests/test_examples_write_safety.py`) continues to pass
unmodified - no test invokes a write-capable command against this
example's committed path directly.

**Not yet started:** any further growth of the library (richer 3D models,
Blender workflows once the Blender local repair/render track is
scheduled, Meshy-gated concepts once the Meshy approval/cost-gated
implementation track is scheduled) - this phase is deliberately just the
one new practical-utility example.

## Phase 20 — roadmap numbering and phase registry cleanup (started)

Documentation/test-hygiene only - no product behavior changes. Several
recent phases collided with already-numbered placeholder phases for
not-yet-started future work (Meshy, Blender, 3MF, slicer-review
automation), forcing repeated renumbering. See "Roadmap numbering policy"
near the top of this document.

**Started:** added the roadmap numbering policy above; converted every
not-yet-started, not-yet-scheduled placeholder phase (previously fixed
numbers) into named, unnumbered entries under "Future tracks, not yet
phase-numbered" below; added `docs/phase-registry.md`, a flat manually
maintained list of every completed phase; updated cross-references
throughout `docs/`, `README.md`, and `examples/future-organic-models/` to
cite completed-phase numbers only where a phase actually started, and
track names (not numbers) for unscheduled future work.

**Not yet started:** any actual Meshy, Blender, 3MF, or slicer-automation
implementation - this phase only changes how future work is *labeled*,
not what exists.

## Phase 21 — Blender local track planning scaffold (started)

Plans (but does not implement) the "Blender local repair/render track" -
mirroring how Phase 16 planned the Meshy approval/cost gate before any
Meshy code existed. No Blender execution, automation, add-ons, or MCP.
See `docs/blender-local-track.md`.

**Started:** `docs/blender-local-track.md` documents the full required
future gate checklist (explicit human approval to enable Blender
automation, a local Blender path/version check, dry-run mode, output
directory isolation, no overwriting original meshes, repaired-mesh
provenance metadata, before/after validation reports, before/after
render previews, continued `review-gate`/human slicer review, and no
slicer/printer communication) and the intended future uses (local mesh
repair planning, higher-quality local renders, exploded/multipart
assembly views, organic-model cleanup after a future Meshy pass -
always local, never cloud). `config/future_local_tools.json` is a local,
non-secret policy scaffold recording Blender's gate state (`enabled:
false`, `status: "future_track_required"`, `local_blender_path: null` -
this repo never reads or stores the user's actual installed Blender
path) - no subprocess call, no `/Applications` scan, no add-on/MCP
config. `factory check-local-tools` (`factory/future_local_tools.py`) is
a small, read-only, additive command that reports this state; it never
launches Blender, never searches for an installed Blender, and never
enables anything. `examples/future-organic-models/{car-concept,
animal-concept,human-figure-study}/` (Phase 14) now each reference this
gate directly from their `README.md` and `concept_brief.json`, alongside
the existing Meshy references.

**Not yet started:** any actual Blender invocation, add-on, MCP
configuration, mesh repair, or render logic - none of the approvals the
checklist requires have been granted, and this phase deliberately grants
none of them. `config/future_local_tools.json`'s `enabled` flag stays
`false` until a human edits it as a separate, explicit, reviewed
decision. The "Blender local repair/render track" below remains
unscheduled - this phase only wrote its required gate down in advance.

## Phase 22 — connect design quality standard to future gates (started)

Docs/planning only - no product behavior changes. Connects
`docs/design-quality-standard.md` (the "Etsy-worthy" quality bar) to the
two existing future-gate docs, so a future Meshy or Blender
implementation must explicitly satisfy it, not merely produce a
technically valid mesh.

**Started:** `docs/meshy-approval-gate.md` gained a "Design-quality gate"
section - Meshy output must not be accepted merely because it generated a
mesh; the existing output-review requirement must explicitly check
intentional style direction, strong silhouette, recognizable reference
interpretation, clean proportions, no blobby/generic/artifact look,
manufacturable geometry, and functional adaptation, with the piggy-bank
example spelled out explicitly ("a pig reference should not become a
pig-shaped blob"). `docs/blender-local-track.md` gained a "Design-quality
review for Blender outputs" section with the same spirit for repair/render
work (cleanup should improve shape clarity, not erase character; organic
and functional outputs each checked against their respective
`docs/design-quality-standard.md` track). Both future-track paragraphs
above (Meshy, Blender) now cross-reference their respective new sections.
The piggy-bank and chip-bag-clip concept study READMEs
(`examples/future-organic-models/piggy-bank-design-study/`,
`examples/future-functional-designs/chip-bag-clip-study/`) each gained one
sentence linking to the relevant future gate doc.

**Not yet started:** any actual Meshy or Blender implementation - this
phase only adds a cross-reference between two already-existing planning
docs and the design-quality standard; it grants no new approval and
changes no `factory` command's behavior.

## Phase 23 — human review quality checklist (started)

Docs/planning only - no product behavior changes, no `review-gate`
behavior changes. Connects `docs/design-quality-standard.md` to the
existing human slicer review / `review-gate` documentation: `review-gate`
is intentionally artifact/geometry-presence based, so this phase clarifies
that passing it only means "ready for human slicer review" - the actual
human review must separately weigh design quality, usefulness, style,
manufacturability, and iteration before any approval.

**Started:** `docs/review-gate.md` gained a "Human review quality
checklist" section spelling out what `pass` does *not* mean
(`human_approved`, `print_ready`, Etsy-worthy, safe/durable/food-safe/
child-safe, ready to sell, ready to print) and the full human review
checklist (design intent, silhouette/proportions, Etsy-worthy quality,
artifact quality, functional fit, manufacturability, material
suitability, multipart assembly fit, tension/flex risk, safety, slicer
preview, prototype/iteration plan). `docs/slicer-review-workflow.md`
gained a matching "Human review checklist, before any approval" section
(visual design review, functional review, manufacturing review, slicer
review, final human decision) and a fix for a stale "Phase 6" reference
in its 3MF section (corrected to the unnumbered 3MF packaging
experiments track). `docs/preview-board.md` and
`docs/visual-preview-package.md` each gained a section clarifying that
the readiness signals/previews they show are presence checks, not a
design-quality score, and should prompt (not replace) the human review
checklist. `README.md` gained a pointer from the `review-gate` paragraph
to the same checklist.

**Not yet started:** any change to what `factory review-gate` actually
computes or reports - this phase only documents what a human should do
once it reports `pass`.

## Phase 24 — design intent brief schema planning (started)

Docs/planning only - no breaking schema changes, no product behavior
changes. Documents and lightly scaffolds how a future `brief.json` could
capture design intent (style direction, functional intent, quality bar,
constraints, iteration goals) so `docs/design-quality-standard.md`'s
"Etsy-worthy" checklist and `docs/review-gate.md`'s "Human review quality
checklist" (Phase 23) have something concrete to compare against instead
of only a free-text `description`.

**Started:** `docs/design-intent-brief.md` proposes an additive, optional
`design_intent` object (`quality_standard`, `audience_or_user`,
`use_case`, `style_direction`, `reference_inputs`, `visual_goals`,
`functional_goals` including a closed `mechanical_behavior` enum,
`manufacturability_constraints`, `iteration_plan`) - validated already by
`schemas/project_brief.schema.json`'s existing `additionalProperties: true`,
no schema file changed. `docs/design-quality-standard.md`,
`docs/review-gate.md`, `docs/slicer-review-workflow.md`, and
`docs/file-lifecycle.md` each gained a cross-reference clarifying the
checklist should compare output against `design_intent` when a brief has
one, and that `factory review-gate` remains artifact/readiness-based -
it does not read, parse, or score `design_intent`. Two concept-only
examples show the shape filled in:
`examples/future-organic-models/piggy-bank-design-study/concept_brief.json`
and `examples/future-functional-designs/chip-bag-clip-study/concept_brief.json`
each gained a `design_intent` block; none of the four working examples
were required to change.

**Not yet started (at the time):** any `factory` command reading,
writing, requiring, or validating `design_intent`; any schema change
requiring it; any UI for filling it in. This phase was planning and two
illustrative examples only. (A small, read-only, advisory check reading
one field of `design_intent` was added later, in Phase 25 - see below.)

## Phase 25 — design intent manufacturability check (started)

A small read-only advisory command that makes Phase 24's `design_intent`
planning immediately useful, without changing generation, approval,
`review-gate`, or print-readiness behavior: compares the optional
`design_intent.manufacturability_constraints.max_size_mm` against known
local printer build volumes.

**Started:** `factory/design_intent_check.py`
(`check_design_intent_manufacturability()`) reads a `brief.json`/
`concept_brief.json`, reads `design_intent.manufacturability_constraints.max_size_mm`
if present, and checks it against every printer in `config/manufacturing/
printers.json` (`factory.manufacturing.knowledge.load_printers()`) in
every axis orientation - the same any-orientation technique
`factory.validators.dimension_check.check_build_volume_fit()` already
uses for a real mesh's bounding box, generalized to the whole fleet
rather than one target printer. Reports one of seven advisory results
(`no_design_intent`, `no_max_size`, `fits_some_printers`,
`fits_no_known_printers`, `invalid_max_size`, `missing_printer_config`,
`unreadable_file`) plus which printers fit/don't and advisory warnings
(e.g. unverified printer specs). `factory check-design-intent <file>
[--json]` is the new CLI command - read-only, human or
machine-readable output, exit code `1` only for `unreadable_file`
(a genuine input error), `0` otherwise since every other result is
informational, not a failure. Both concept examples from Phase 24
(`piggy-bank-design-study/`, `chip-bag-clip-study/`) resolve
deterministically to `fits_some_printers` against the current fleet.
Never contacts a printer, discovers printers, contacts a slicer, makes a
network call, writes a file, or sets `human_approved`/`print_ready`.

**Not yet started:** reading any other `design_intent` field
(`style_direction`, `functional_goals`, etc.) - only
`manufacturability_constraints.max_size_mm` is consumed by anything so
far; real mesh-geometry-aware manufacturability checking (still
`factory validate`'s job); wiring this check into `review-gate` or any
other command (`check-design-intent` remains a separate, optional,
read-only command by design).

## Phase 26 — design intent visibility in project reports (started)

A small, purely presentational follow-on to Phase 25: surfaces the
`design_intent` a brief already has (and Phase 25's manufacturability
advisory) inside the local reporting workflows Owen already runs, so
seeing it doesn't require a separate `factory check-design-intent` call.
Visibility only - no new approval, scoring, or gate semantics.

**Started:** `factory.design_intent_check.summarize_design_intent(file_path)`
- a new read-only helper that reads `quality_standard`/`use_case`/
`style_direction` for display and reuses Phase 25's
`check_design_intent_manufacturability()` unchanged for `max_size_mm` and
the manufacturability advisory, so no parsing/fit logic is duplicated.
Returns `None` (not an error) whenever `design_intent` is absent,
unreadable, or malformed. Two consumers:

- **`factory report <project_dir>`** now prints a `Design Intent:` section
  (quality standard, use case, style direction, declared max size, and
  the manufacturability advisory result/fitting printers) whenever
  `brief.json` has a `design_intent` block, ending with an explicit
  "advisory only" line. Prints nothing extra when `design_intent` is
  absent or malformed - no error either way.
- **`factory.project_inspection.summarize_project()`** (the shared layer
  both `factory preview-board` and, transitively, `factory review-gate`
  build on) gained one new field, `design_intent_summary` - a compact
  `{quality_standard, use_case, manufacturability_result}` object or
  `None`. Purely additive to the board's JSON shape; never read by
  `classify_visual_readiness()`, `build_health_signals()`, or
  `build_suggested_actions()`, so it cannot change a project's
  `visual_readiness_state`, health signals, or suggested actions.

**Explicitly unchanged:** `factory.review_gate.evaluate_review_gate()` -
still builds its JSON output from the same fixed key set as before Phase
26, still never reads `design_intent`, and `design_intent_summary` never
appears in a `review-gate` result. `review-gate` remains a pure artifact/
readiness check - "ready for human slicer review," never "design
approved." See `docs/design-intent-brief.md`'s "Visibility in `factory
report` and the preview board" and `docs/review-gate.md`.

Never contacts a printer, discovers printers, contacts a slicer, makes a
network call, writes any file, or sets `human_approved`/`print_ready`.
Never approves, scores, or replaces the Etsy-worthy/slicer/human review
described in `docs/review-gate.md`'s "Human review quality checklist."

**Not yet started (at the end of Phase 26):** displaying any other
`design_intent` field (`functional_goals`, `visual_goals`, `iteration_plan`,
etc.) beyond `quality_standard`, `use_case`, `style_direction`, and the
Phase 25 manufacturability advisory; a `design_intent` section in the
preview board's static HTML (the board's JSON gained `design_intent_summary`,
but the HTML table/health-signals/suggestions sections were left unchanged
to keep this phase small) - both picked up by Phase 27 below.

## Phase 27 — design intent preview board visualization (started)

A small, purely presentational follow-on to Phase 26: gives the
`design_intent` data the board's JSON already carries a first-class visual
home in the Preview Board's static HTML, instead of requiring a human to
open `index.json` or run `factory report` separately to see it.
Visualization only - no schema change, no new approval/scoring/gate
semantics, and every existing HTML section (summary table, health signals,
suggested next steps) is preserved unchanged.

**Started:**
`factory.design_intent_check.describe_design_intent_for_board(file_path)` -
a new read-only helper alongside Phase 26's `summarize_design_intent()`,
reusing `check_design_intent_manufacturability()` the same way so no
parsing/fit logic is duplicated. Adds three fields
`summarize_design_intent()` intentionally doesn't read: `reference_input_count`
(length of the optional `design_intent.reference_inputs` list),
`design_notes` (the optional `design_intent.iteration_plan.acceptance_notes`),
and `warnings` (the same advisory warnings
`check_design_intent_manufacturability()` already computes). Returns `None`
under the same conditions as `summarize_design_intent()`. Two consumers:

- **`factory.project_inspection.summarize_project()`** gained a second,
  additive field, `design_intent_detail` - a superset of Phase 26's
  `design_intent_summary`, which keeps its exact three-field shape
  unchanged. Same `None`-when-absent semantics, same non-classifying
  guarantee (never read by `classify_visual_readiness()`,
  `build_health_signals()`, or `build_suggested_actions()`).
- **`factory.preview_board.build_board_html()`** now renders a per-project
  overview card - right after the state-count summary and before the
  existing table - covering Project Header, Design Intent (Quality/
  Purpose/Style/Design notes), Manufacturing Overview (manufacturing
  status, selected option, design-intent manufacturability fit, reference
  input count, warnings/advisories), Artifacts (CAD/STL/Render
  present-or-missing badges), Health Signals (a compact pointer to the
  existing detailed section further down the page), and Review Readiness
  (a Review Ready / Review Not Ready badge from `visual_readiness_state`).
  Every field renders a clear fallback ("Not specified"/"None"/"Unknown")
  rather than ever being left blank. Static HTML/CSS only - no JavaScript,
  no external assets, no CDN, no tracking.

**Explicitly unchanged:** `design_intent_summary`'s shape (still exactly
`{quality_standard, use_case, manufacturability_result}`); the board's
existing summary table, "Health signals" section, and "Suggested next
steps" section (all still present, unchanged, and still follow the new
cards); `factory.review_gate.evaluate_review_gate()`'s JSON output shape
(still never includes `design_intent_summary` or `design_intent_detail`).
See `docs/design-intent-brief.md`'s "Preview Board visualization
(Phase 27)" and `docs/preview-board.md`.

Never contacts a printer, discovers printers, contacts a slicer, makes a
network call, writes any file, or sets `human_approved`/`print_ready`.
Never approves, scores, or replaces the Etsy-worthy/slicer/human review
described in `docs/review-gate.md`'s "Human review quality checklist."

**Not yet started (at the end of Phase 27):** displaying `functional_goals`/
`visual_goals` (mechanical behavior, silhouette/proportions/surface-detail
goals) anywhere; a source-discovery or reference-board feature; any
Meshy/Blender-backed workflow - the reference-board planning piece is
picked up by Phase 28 below (Meshy/Blender/functional-visual-goals display
remain out of scope for both phases).

## Phase 28 — source discovery and reference board planning (started)

**Planning/data-model scaffolding, the same spirit as Phase 24's
`design_intent` shape** - not a Source Discovery *feature*. Defines a
structured, local record of where a project's design intent came from (a
photo, an existing STL, a MakerWorld/Thingiverse/Reddit/Pinterest/
DeviantArt page, a sketch, a classroom/product photo, a remixable source
file) and gives it a read-only, advisory summary, wired into the same
`summarize_project()`/preview-board layers Phase 26/27 extended. No web
crawling, no scraping, no external search, no downloading, and no API
integration exist anywhere in this phase - a recorded `source_url` is
inert metadata, never fetched.

**Started:** `factory.reference_board` - a new module, read-only and
local-filesystem-only, reading an optional `<project_dir>/reference_board.json`
(a flat `references` list). Defines the closed vocabularies for
`source_type`, `license`, `usage_intent`, and `attached_to`, and two
functions:

- `read_reference_board(project_dir)` - raw, unvalidated read. Returns
  `{"references": []}` (not an error) whenever the file is missing,
  unreadable, or malformed - most projects won't have one.
- `summarize_reference_board(project_dir)` - validated, advisory summary:
  `reference_count`, `by_license`/`by_source_type`/`by_usage_intent`
  breakdowns, `attached_to_design_intent_count`, and a list of plain-text
  advisory `warnings` (missing/unknown/proprietary license, missing
  `source_url`, a `remix_candidate` with an unsafe license, an unsupported
  field value, a malformed entry, or no references attached to
  `design_intent.reference_inputs`). Always a dict, never `None` - "clean
  empty result" whenever no reference board exists. Every condition here
  is advisory, never a hard failure.

Two consumers, both additive:

- **`factory.project_inspection.summarize_project()`** gained a third
  additive field, `reference_board_summary`, computed unconditionally
  (independent of `brief_status` - a project can have a reference board
  before it even has a `brief.json`). `design_intent_summary` and
  `design_intent_detail` are completely unchanged by this phase. Same
  non-classifying guarantee as those two fields.
- **`factory.preview_board.build_board_html()`** gained a compact
  "Reference Board" card section, right after "Design Intent" (references
  feed design intent) and before "Manufacturing Overview" - reference
  count, a license-status breakdown, a usage-intent breakdown, and any
  advisory warnings. Compact by design: counts and warnings, not a full
  per-reference listing. A project with zero references renders a single
  explanatory line instead of empty rows. Static HTML/CSS only - no
  JavaScript, no external assets, no CDN, no tracking, and no
  `source_url` is ever rendered as a clickable link.

One committed, safe local example:
`examples/storage-bin-lid/reference_board.json` (no copyrighted assets, no
downloaded files - a URL string is present only as inert metadata). See
`docs/reference-board.md` for the full field/vocabulary reference.

**Explicitly unchanged:** `design_intent_summary`'s and
`design_intent_detail`'s shapes; the board's existing summary table,
"Health signals" section, and "Suggested next steps" section; the preview
board's JSON top-level shape (`reference_board_summary` is additive on
each project entry, not a new top-level key);
`factory.review_gate.evaluate_review_gate()`'s JSON output shape (still
never includes `reference_board_summary`). See `docs/reference-board.md`
and `docs/preview-board.md`.

Never contacts a printer, discovers printers, contacts a slicer, makes a
network call of any kind, writes any file, or sets
`human_approved`/`print_ready`. Never fetches, downloads, scrapes, or
searches anything - a `source_url` is read and echoed back in warnings/
summaries, never opened.

**Not yet started (at the end of Phase 28):** the actual Source Discovery
feature (crawling, scraping, external search, downloading) - this phase is
the data model and local advisory layer it would eventually populate, not
the feature itself; automatically copying a reference into `brief.json`'s
`design_intent.reference_inputs`; a way to create/add references without
hand-editing JSON; per-reference detail in the HTML card (currently
counts/breakdowns/warnings only, by design, to stay compact); any
Meshy/Blender/slicer integration - the CLI-management piece is picked up
by Phase 29 below (Source Discovery itself, per-reference HTML detail, and
Meshy/Blender/slicer remain out of scope for both phases).

## Phase 29 — Reference Board CLI management (started)

Makes Phase 28's `reference_board.json` usable without hand-editing JSON.
Still completely local - no internet access, no search, no scraping, no
downloading, no APIs. Business logic lives entirely in
`factory.reference_board` (extended, not duplicated); `factory.cli`'s new
`reference-board` command group is a thin wrapper around it.

**Started:** `factory reference-board`, a Typer sub-app with five
subcommands:

- **`init <project_dir> [--force]`** - creates a documented starter
  `reference_board.json` (an explanatory `notes` list plus an empty
  `references` list). Never overwrites an existing file unless `--force`
  is given. Raises a clear error if `project_dir` itself doesn't exist -
  never creates the project directory, only the file inside an existing
  one.
- **`show <project_dir> [--json]`** - a compact human-readable summary
  (reference count, warning count, license-status breakdown, usage-intent
  breakdown), or `summarize_reference_board()`'s dict directly with
  `--json`.
- **`validate <project_dir> [--json]`** - runs the same advisory checks
  `summarize_reference_board()` already computes, always under a
  `✓ Valid reference board` header - incomplete information is never a
  failure. The one real error is `reference_board.json` existing but not
  being parseable JSON.
- **`list <project_dir> [--json]`** - a compact, numbered, per-reference
  listing (title, source type, license, usage intent) via a new
  `normalize_references()` function, or that list directly with `--json`.
- **`add --project <project_dir> --title <title> [--url ...] [--type ...]
  [--license ...] [--usage ...] [--attached-to ...] [--notes ...]`** -
  appends one new reference (creating the file first if needed). Always
  appends - never overwrites or removes an existing entry. An unrecognized
  `--type`/`--license`/`--usage`/`--attached-to` value is still saved
  exactly as given (never rejected) - the resulting advisory warning(s)
  about the new entry print immediately for feedback.

`factory.reference_board` gained two new local write operations
(`init_reference_board()`, `add_reference()`, both via
`project_store.save_json()` - no network, no printer/slicer contact) and
one new read operation (`normalize_references()`, the per-reference
counterpart to `summarize_reference_board()`'s aggregate counts). Every
subcommand reads through - or, for `add`, reuses internally only for
warning text - the same single `_normalize_reference()` implementation
Phase 28 already built; no validation logic is duplicated in `factory.cli`.

**Explicitly unchanged:** `reference_board.json`'s shape/vocabulary (the
CLI writes the exact same shape a human would hand-author); the Preview
Board's HTML layout and `reference_board_summary`'s shape (Phase 29 is
CLI-only - no board changes); `factory review-gate`'s JSON output shape
(still never includes `reference_board_summary`).

Never contacts a printer, discovers printers, contacts a slicer, makes a
network call of any kind, or sets `human_approved`/`print_ready`. Never
fetches, downloads, scrapes, or searches anything - `--url` is stored as
plain text, never opened. Never performs automated license detection -
`--license` is exactly what a human passes (or omits), classified
advisory-only exactly like Phase 28's hand-authored entries.

**Not yet started (at the end of Phase 29):** the actual Source Discovery
feature; a `factory reference-board remove`/`edit` command (only `add`
exists - removing or editing an entry still means hand-editing the JSON,
or `init --force` to start over); attaching a reference to
`design_intent.reference_inputs` automatically from the CLI
(`--attached-to design_intent.reference_inputs` records the *declared*
intent, same as Phase 28 - nothing copies it into `brief.json`);
per-reference detail in the HTML card; any Meshy/Blender/CAD-generation/
AI-ranking integration; a way to go from a free-form idea to a structured
brief without hand-authoring `brief.json` - the last piece is picked up by
Phase 30 below (Meshy/Blender/CAD generation remain out of scope for both
phases).

## Phase 30 — intelligent project intake engine (started)

The first step in this repo's pipeline gets its own module:

```
User Idea -> Project Intake -> Project Brief -> Design Intent ->
Reference Board -> Manufacturing Planning -> CAD Generation ->
Preview Board -> Review Gate -> Slicer Review -> (never automatic printing)
```

Converts a free-form natural-language product idea (plain text, Markdown,
or an existing project's `brief.json` description) into structured intake
metadata. **Fully deterministic, no AI/LLM/network of any kind** - closed
keyword tables and regexes only, checked in a fixed order, so the same
input always produces the same output. This phase does not generate CAD
and does not perform AI reasoning beyond structured extraction - it
prepares every downstream system, it doesn't replace any of them.

**Started:** `factory.project_intake`, a new module with one core function
and three read-only entry points:

- `extract_intake_fields(text)` - the heuristic engine itself. Extracts
  `project_name`, `category`, `purpose`, `audience`, `environment`,
  `material_assumptions`, `printer_assumptions`, `quality_target`,
  `manufacturing_style`, `functional_goals`, `visual_goals`,
  `dimensional_constraints`, and `commercial_intent` - each
  `{"value": ..., "confidence": "high"|"medium"|"low"|"unknown"}` - plus
  advisory `warnings`. See `docs/project-intake.md` for the full
  heuristic/confidence reference.
- `analyze_text_file(path)` - reads a `.txt`/`.md` file (Markdown heading
  becomes the project name) and runs the engine over it.
- `analyze_project(project_dir)` - reads `<project_dir>/brief.json`'s
  `project_name`/`description`/`constraints` free text (only those three -
  deliberately not every structured field elsewhere in the same file) and
  runs the engine over it; the brief's own literal `project_name` always
  wins over any inferred guess.
- `analyze(path)` - the single dispatch entry point `factory intake
  analyze` uses: directory -> `analyze_project()`, file ->
  `analyze_text_file()`.

All keyword matching is **word-boundary matching, not substring
matching** - fixed during this phase's own development after an early
draft matched "de**sign**" against the `sign` category keyword and
"b**rack**et" against the `organizer` keyword `rack`; every match is now a
whole word/phrase, never a fragment.

Two consumers, both additive:

- **`factory.project_inspection.summarize_project()`** gained a fourth
  additive field, `intake_summary`, computed unconditionally (independent
  of `brief_status`, same reasoning as Phase 28's
  `reference_board_summary`). `design_intent_summary`, `design_intent_detail`,
  and `reference_board_summary` are completely unchanged by this phase.
- **`factory.preview_board.build_board_html()`** gained a compact "Project
  Intake" card section, placed *first* in each project's card (upstream of
  "Design Intent" in the pipeline above) - category, audience,
  environment, quality target, material assumptions, and advisory
  warnings. Deliberately compact: confidence levels and less commonly
  needed fields stay in `--json` output, not the card.

**New CLI:** `factory intake analyze <project_dir_or_text_or_markdown_file>
[--json]` - a thin wrapper around `analyze()`. Sample output against the
committed benchmark:

```
$ factory intake analyze examples/intake-benchmarks/teacher-nameplate.md
Project Intake Analysis
source: markdown_file

Project name: Mr. Reagan Classroom Nameplate  (confidence: high)
Category: Sign  (confidence: medium)
...
Quality target: Etsy-worthy  (confidence: medium)
Manufacturing style: Multi-part, AMS, Multi-color  (confidence: high)
...
Dimensional constraints: 48-inch  (confidence: high)
Commercial intent: No  (confidence: unknown)

advisory warnings:
  - Reference images recommended - see `factory reference-board add`.
```

One committed benchmark: `examples/intake-benchmarks/teacher-nameplate.md`
- a shortened "Mr. Reagan" classroom-nameplate concept (modular teacher
desk nameplate, premium/Etsy-worthy/gift-quality, anime-inspired
lettering, AMS on a Bambu printer, a 48-inch desk, PLA) written to exercise
most of this engine's heuristics in one file. Exists only to validate
intake parsing - never generates CAD, a brief, or any other artifact.

**Explicitly unchanged:** `design_intent_summary`'s, `design_intent_detail`'s,
and `reference_board_summary`'s shapes; the board's existing summary
table, "Health signals", "Suggested next steps", "Design Intent", and
"Reference Board" sections; `factory.review_gate.evaluate_review_gate()`'s
JSON output shape (still never includes `intake_summary`).

Never contacts a printer, discovers printers, contacts a slicer, makes a
network call of any kind, or sets `human_approved`/`print_ready`. Never
calls an AI/LLM API, never performs a web search, never scrapes a website,
never downloads anything, never performs OCR or computer vision. Writes
nothing - `factory intake analyze` is entirely read-only.

**Not yet started (at the end of Phase 30):** using `intake_summary` to
auto-generate or auto-populate a `brief.json`/`design_intent` (a human
still authored the actual brief entirely by hand - the last piece is
picked up by Phase 31 below, still always draft-only and human-approved
before saving); multi-language keyword support; negation/context
understanding (documented limitation, not a bug - see
`docs/project-intake.md`); any AI/LLM-backed extraction; CAD generation of
any kind; Meshy/Blender/slicer integration (out of scope for both phases).

## Phase 31 — intake-to-brief draft generation (started)

The second step in this repo's pipeline gets its own module:

```
User Idea -> Project Intake -> Draft Brief -> Design Intent ->
Reference Board -> Manufacturing Planning -> CAD Generation ->
Preview Board -> Review Gate -> Slicer Review -> (never automatic printing)
```

Converts an already-computed `intake_summary` (Phase 30) into a
human-reviewable draft `brief.json`/`design_intent`/manufacturing-notes.
**Never re-parses free text** - the keyword/regex heuristics stay entirely
in `factory.project_intake`; this module only shapes what Phase 30 already
extracted. **Never writes automatically** - a draft is printed, not saved,
unless `--write` is explicitly given, and even then an existing
`brief.json` is never silently overwritten.

**Started:** `factory.brief_generator`, a new module:

- `generate_draft(intake_summary)` - the top-level function. Returns
  `{readiness, brief, design_intent, manufacturing_notes, advisories}`.
  Every field in `brief`/`design_intent`/`manufacturing_notes` is
  confidence-gated: populated only when the matching `intake_summary`
  field's confidence is `"high"`/`"medium"`, else `None`/`[]` - "unknown"/
  "not specified" once rendered, never a guessed value. `readiness` reports
  percent-populated/unknown-field counts over 13 tracked fields - the
  benchmark below lands at exactly 85% populated / 2 unknown, matching the
  worked example this phase's brief specified.
- `build_brief_json(draft)` - converts a draft into an actual, schema-valid
  `brief.json` dict (validated against
  `schemas/project_brief.schema.json` in this phase's own tests, for both
  a fully-populated and a completely empty draft). Every unresolvable
  required field is written as the literal string `"unknown"` - not even
  `factory.project_store.default_brief()`'s own conventional defaults
  (`"Owen"`, `"Bambu H2D"`) are borrowed, since those are appropriate when
  nothing was ever attempted, not when extraction was attempted and came
  up empty. `design_intent.manufacturability_constraints.max_size_mm` is
  never synthesized from a raw `dimensional_constraints` match like
  `"48-inch"` - that names one axis, not a confirmed `[x, y, z]` triple.
- `write_draft_brief(project_dir, draft, force=False)` - the **only**
  write path in this entire module, and the only way anything from this
  phase ever reaches disk. Raises `ProjectDirectoryNotFoundError` if
  `project_dir` doesn't exist (never creates it) and
  `BriefAlreadyExistsError` if `brief.json` already exists and `force` is
  `False` (never silently overwrites).
- `summarize_draft_brief(intake_summary)` - the compact `{readiness,
  advisories}` view for project inspection / the preview board.
- `load_intake_summary_from_path(path)` - the one function allowed to call
  `factory.project_intake.analyze()` (reused, not duplicated) for a
  project directory or text/Markdown file; a `.json` path is read directly
  as an already-computed `intake_summary`.

Two consumers, both additive:

- **`factory.project_inspection.summarize_project()`** gained a fifth
  additive field, `draft_brief_summary`, derived from the project's own
  `intake_summary` (no re-parsing). `design_intent_summary`,
  `design_intent_detail`, `reference_board_summary`, and `intake_summary`
  are completely unchanged by this phase.
- **`factory.preview_board.build_board_html()`** gained a compact "Draft
  Brief" card section, right after "Project Intake" and before "Design
  Intent" - readiness status, percent populated, unknown-field count, and
  a standing "Human review required" reminder. The board itself never
  calls `write_draft_brief()` - the card is read-only, same as every other
  section on it.

**New CLI:** `factory intake suggest-brief
<project_dir_or_text_or_markdown_or_intake_json> [--json] [--write]
[--force]` - a thin wrapper around `generate_draft()`/`write_draft_brief()`.
Sample output against the committed Phase 30 benchmark:

```
$ factory intake suggest-brief examples/intake-benchmarks/teacher-nameplate.md
Draft Brief Suggestion
source: markdown_file

Status: Ready   Populated: 85%   Unknown fields: 2

Brief
  Project name: Mr. Reagan Classroom Nameplate
  Category: Sign
  ...
  Quality target: Etsy-worthy
  Manufacturing style: Multi-part, AMS, Multi-color
  ...
  Commercial intent: unknown

Advisories
  - Reference board recommended - see `factory reference-board add`.
  - Human approval required before save.

This is a DRAFT only - nothing has been written. ...
```

**Explicitly unchanged:** `intake_summary`'s,
`design_intent_summary`'s/`design_intent_detail`'s, and
`reference_board_summary`'s shapes; the board's existing summary table,
"Health signals", "Suggested next steps", "Project Intake", "Design
Intent", and "Reference Board" sections;
`factory.review_gate.evaluate_review_gate()`'s JSON output shape (still
never includes `draft_brief_summary`).

Never contacts a printer, discovers printers, contacts a slicer, makes a
network call of any kind. Never calls an AI/LLM API, never performs a web
search, never scrapes a website, never downloads anything. Never generates
CAD or OpenSCAD, never calls Meshy or Blender, never creates a project
directory, never sets `human_approved`/`print_ready`. Writes **at most
one file** (`<project_dir>/brief.json`, only with explicit `--write`,
only after confirming the project exists and the file doesn't already
exist unless `--force`).

**Not yet started (at the end of Phase 31):** a `factory intake
suggest-brief --update` that merges a fresh draft into an existing brief
rather than replacing it wholesale - picked up by Phase 32 below; writing
a separate `reference_board.json` from detected reference-worthy signals
(still always `[]` - a human still runs `factory reference-board add` by
hand); any AI/LLM-backed drafting; CAD generation of any kind;
Meshy/Blender/slicer integration (out of scope for both phases).

## Phase 32 — brief update / merge workflow (started)

Makes Phase 31's draft system useful for **real, already-started**
projects, not just brand new ones - most projects have a `brief.json` with
some real, human-authored content by the time anyone thinks to run
`factory intake suggest-brief` on them; a full draft `--write` would
overwrite all of it. Phase 32 adds a safe *merge*: fill in only what's
genuinely missing or still a placeholder, leave everything else untouched.

**Started:** `merge_draft_brief(existing_brief, draft_brief)` in
`factory.brief_generator` - compares a draft (Phase 31's
`generate_draft_brief()` output) against an existing `brief.json`, field
by field, over exactly the 8 fields `build_brief_json()` already knows how
to write. A field already holding real content in `existing_brief` is
**always preserved**, regardless of what the draft has; a field that's
genuinely empty or placeholder-looking (blank, the literal `"unknown"`, or
a `factory.project_store.default_brief()`-style `"TODO: ..."` string) is
eligible to be filled - but only from a draft value that *isn't itself*
placeholder-looking, a real edge case this phase's own testing surfaced
(re-analyzing a project's own still-unedited `"TODO: ..."` description
would otherwise get proposed right back as a "new" value). `category`,
`audience`, `environment`, `functional_goals`, and `commercial_intent`
have no home in a real `brief.json` (Phase 31 never wrote them as
top-level keys either), so they're never merge candidates.

Supporting functions: `load_existing_brief()` (raises
`MalformedExistingBriefError` for unreadable JSON - the one real error
condition, same treatment as Phase 29's `reference_board.json` validation),
`apply_merge()` (turns a merge result into the actual dict to write - only
`fields_to_add` is touched, everything else passes through byte-for-byte),
`write_merged_brief()` (the merge-mode write path, validated against
`schemas/project_brief.schema.json` in this phase's own tests),
`build_merge_preview()` (the one-call CLI entry point), and
`summarize_brief_update()` (the compact summary for project inspection/the
board).

**Extended CLI:** `factory intake suggest-brief <path> [--json] [--write]
[--force] [--update]`:

- **`--update` alone** - prints a merge preview (Fields to add / Fields
  preserved / Warnings), writes nothing.
- **`--update --write`** - applies the merge, writing only the safe
  additions.
- **`--force` and `--update` together are rejected** with a clear error -
  they're different operations (full replace vs. safe merge) and the CLI
  never silently picks one.
- **No existing `brief.json`** - `--update` has nothing to merge into, so
  it falls back to plain `--write` behavior exactly as specified: "if no
  brief.json exists, behave like normal draft write."
- **A malformed existing `brief.json`** - `--update` refuses with a clear
  error rather than guessing what to preserve; `--force` (which never
  needs to read the existing file) is unaffected and remains the escape
  hatch.

Sample merge preview:

```
$ factory intake suggest-brief projects/my-nameplate --update
Brief Merge Preview

Fields to add:
  - material: PLA
  - printer: Bambu
  - quality_target: Etsy-worthy

Fields preserved:
  - project_name: existing value kept
  - purpose: existing value kept

Warnings:
  - Dimensions incomplete.
  - Human approval required before save.

This is a preview only - nothing has been written.
Re-run with --write --update to apply this merge.
```

`--json` gains four new top-level keys (`merge_preview`, `fields_to_add`,
`fields_preserved`, `would_write`, `wrote_file` - alongside the existing
`draft`) **only** when `--update` finds an existing brief to merge into;
plain `--json` (no `--update`, or nothing to merge into) keeps Phase 31's
exact original shape unchanged - a deliberate backward-compatibility
guarantee, tested directly.

Two consumers, both additive:

- **`factory.project_inspection.summarize_project()`** gained a sixth
  additive field, `brief_update_summary` - a compact `{merge_available,
  fields_to_add_count, fields_preserved_count, human_review_required}`
  view. `design_intent_summary`, `design_intent_detail`,
  `reference_board_summary`, `intake_summary`, and `draft_brief_summary`
  are completely unchanged by this phase.
- **`factory.preview_board.build_board_html()`** gained a compact "Brief
  Update" card section, right after "Draft Brief" and before "Design
  Intent" - deliberately terser than every other card: when nothing's
  meaningful to merge (the common case), it renders one line ("Up to date
  - nothing to merge.") instead of a whole block, per this phase's own
  "keep it compact, don't make the board noisy" requirement. The board
  itself never merges or writes anything - the only write path (`--write
  --update`) is a separate, explicit, human-run CLI command.

**Explicitly unchanged:** every Phase 26-31 field's shape; the board's
existing summary table, "Health signals", "Suggested next steps", "Project
Intake", "Draft Brief", "Design Intent", and "Reference Board" sections;
`factory.review_gate.evaluate_review_gate()`'s JSON output shape (still
never includes `brief_update_summary`); plain (non-`--update`) `--json`
output.

Never contacts a printer, discovers printers, contacts a slicer, makes a
network call of any kind. Never calls an AI/LLM API, never performs a web
search, never scrapes a website, never downloads anything. Never generates
CAD or OpenSCAD, never calls Meshy or Blender, never creates a project
directory, never edits `design_intent` on an already-advanced project
beyond what an explicit merge/replace was asked to do, never auto-generates
`reference_board.json` content, never sets `human_approved`/`print_ready`.
Writes **at most one file** (`<project_dir>/brief.json`), and only with
explicit `--write` (with `--force`, `--update`, or neither - never
automatically).

**Not yet started (at the end of Phase 32):** field-scoped merge
(`--only material`, or similar - `--update` always evaluates every
candidate field together); merging `reference_board.json` content (still
a completely separate, hand-managed file - Phase 28/29); any AI/LLM-backed
conflict resolution when a field is ambiguous; CAD generation of any kind;
Meshy/Blender/slicer integration; a way to evaluate whether a project is
*ready to proceed at all* and which engine it should proceed with - picked
up by Phase 33 below (CAD generation, Meshy/Blender/slicer execution
remain out of scope for both phases).

## Phase 33 — project readiness dashboard & design orchestrator (started)

The first "decision brain" in this repo's pipeline:

```
User Idea -> Project Intake -> Draft Brief -> Brief Merge ->
Design Intent -> Reference Board -> Project Readiness ->
Design Orchestrator -> CAD Engine -> Preview -> Review ->
Slicer Review -> (never automatic printing)
```

Evaluates whether a project is sufficiently defined to proceed, and
recommends the most appropriate downstream design engine (OpenSCAD,
CadQuery, Blender, Meshy, FreeCAD, a hybrid workflow, manual design, or
"unknown"). **No CAD generation occurs in this phase** - every
recommendation is a string a human reads and acts on themselves. Fully
deterministic: reuses the six summaries every earlier phase already
computed (Phase 26-32) without re-parsing any of them, plus
`factory.router.recommend_tool()` (an existing keyword-based router from
an earlier phase) as a text-based fallback, rather than inventing a
second, divergent keyword table.

**Started:** `factory.design_orchestrator`, a new module:

- `compute_readiness_score(...)` - a weighted 0-100 score across five
  categories (Intake 20%, Brief 20%, Design Intent 25%, Reference Board
  15%, Manufacturing 20% - weights sum to 1.0, documented as
  `CATEGORY_WEIGHTS`). Each category percent is read directly off an
  already-computed summary field (e.g. Intake reuses Phase 31's own
  `readiness.percent_populated` outright) - see
  `docs/design-orchestrator.md` "Readiness scoring" for the full
  per-category derivation and the reasoning behind each weight.
- `compute_design_signals(...)` - shared organic-vs-mechanical signal
  detection, reused by both the state and engine functions below so they
  can never disagree. Category (Phase 30's closed vocabulary) counts as a
  weight-2 vote for its family; each `style_direction`/`visual_goals`
  keyword hit is a weight-1 vote. A "mixed" (hybrid) signal only fires
  when *both* sides reach weight >= 2 - a real, comparable split, not one
  confident category vote against a single incidental style word. This
  threshold was tuned against a real case this phase's own testing
  surfaced: the committed Phase 30 benchmark
  (`examples/intake-benchmarks/teacher-nameplate.md`) has category `sign`
  plus a lone `"anime"` style keyword among otherwise sign-typical
  keywords (`"raised"`, `"lettering"`) - without the threshold, a plain
  classroom nameplate would incorrectly read as a "mixed" design.
- `determine_readiness_state(...)` - the seven-state decision tree
  (`Not Ready`, `Needs Information`, `Ready For Mechanical CAD`,
  `Ready For Organic Modeling`, `Ready For Mixed Workflow`,
  `Ready For Manufacturing Review`, `Blocked`), checked in a fixed
  priority order - a hard manufacturability block always wins; see
  `docs/design-orchestrator.md` "Readiness states" for the full order and
  reasoning.
- `recommend_engine(...)` - category-first, refined by style keywords,
  falling back to `factory.router.recommend_tool()`'s free-text matching
  only when neither gives a usable signal. An organic signal with a low
  overall score recommends `Meshy (Concept Only)` rather than `Blender` -
  echoing this repo's own established treatment of concept-only organic
  ideas (`examples/future-organic-models/`, gated behind
  `docs/meshy-approval-gate.md`) - and upgrades to `Blender` once the
  project has enough real definition. `FreeCAD` is a recognized
  recommendation value with **no current rule that selects it** -
  reserved for a future, more sophisticated complex-assembly rule rather
  than an invented, unvalidated heuristic today.
- `generate_readiness_advisories(...)` - a consolidated, orchestrator-level
  advisory list (`Dimensions missing`, `Material unspecified`, `Printer
  unspecified`, `Reference images recommended`, `Design intent
  incomplete`, `Commercial review recommended`, `Manufacturing review
  required`, always ending with `Human approval required`) - read directly
  off already-parsed data fields, never re-scanned text.
- `evaluate_project_readiness(...)` - the core, pure function combining
  all of the above from exactly the six summaries
  `factory.project_inspection.summarize_project()` produces.
- `evaluate_readiness_for_path(path)` - the convenience entry point
  `factory readiness` uses for a single project directory or a plain-text/
  Markdown idea file, computing the same six summaries via the same leaf
  functions those phases already expose (never re-implementing their
  parsing, never importing `factory.project_inspection` - that would be
  circular, since `project_inspection` imports *this* module).

Two consumers, both additive:

- **`factory.project_inspection.summarize_project()`** gained a seventh
  additive field, `design_orchestrator_summary`. Every earlier field
  (`design_intent_summary`, `design_intent_detail`,
  `reference_board_summary`, `intake_summary`, `draft_brief_summary`,
  `brief_update_summary`) is completely unchanged by this phase.
- **`factory.preview_board.build_board_html()`** gained a "Project
  Readiness" dashboard section, placed *first* in each project's card -
  overall score, recommended engine, readiness state, and the top
  remaining advisories. **Summarizes the existing detail cards below it
  without removing or replacing any of them** - Project Intake, Draft
  Brief, Brief Update, Design Intent, Reference Board, Manufacturing
  Overview, Artifacts, Health Signals, and Review Readiness are all
  unchanged and still follow it.

**New CLI:** `factory readiness <path> [--json]` - accepts a single
project directory (has its own `brief.json`/`concept_brief.json`), a
directory of multiple projects (e.g. `examples/` or `projects/` - scanned
the same way `factory preview-board` does), or a plain-text/Markdown idea
file. Sample output:

```
$ factory readiness examples/storage-bin-lid
examples/storage-bin-lid
  Overall: 36%   Ready for: OpenSCAD   Status: Needs Information
  Score breakdown:
    Intake: 54%
    Brief: 50%
    Design intent: 0%
    Reference board: 33%
    Manufacturing: 50%
  Remaining:
    - Material unspecified
    - Printer unspecified
    - Design intent incomplete
    - Manufacturing review required
    - Human approval required
  Engine rationale: Category 'sign' matches OpenSCAD's parametric plate/sign/organizer strengths.
```

**Explicitly unchanged:** every Phase 26-32 field's shape; the board's
existing summary table, "Health signals", "Suggested next steps", and
every existing card section; `factory.review_gate.evaluate_review_gate()`'s
JSON output shape (still never includes `design_orchestrator_summary`).

Never contacts a printer, discovers printers, contacts a slicer, makes a
network call of any kind. Never calls an AI/LLM API, never performs a web
search, never scrapes a website, never downloads anything. **Never
generates CAD, never invokes OpenSCAD/CadQuery/Blender/Meshy/FreeCAD** -
every recommendation is a string a human reads and acts on themselves.
Never creates a project, a brief, a design_intent block, or a reference.
Never sets `human_approved`/`print_ready`. Writes nothing, ever - `factory
readiness` is entirely read-only.

**Not yet started:** actually wiring engine execution to any recommendation
(this phase is the decision layer, not the dispatcher - `factory.cad.router`
already exists as the local OpenSCAD/CadQuery backend router this module
partially reuses via `factory.router.recommend_tool()`, but nothing
automatically routes a recommendation into a generation call); a rule that
ever actually selects `FreeCAD`; cross-project readiness history/trends;
any AI/LLM-backed decision-making; CAD generation of any kind;
Meshy/Blender/slicer execution - all explicitly out of scope for this
phase.

## Phase 34 — Readiness-Gated CAD Generation Router (complete)

The first gated bridge between Design Orchestrator readiness (Phase 33)
and this repo's *existing* local CAD generation backends:

```
Project Readiness -> Design Orchestrator -> Readiness-Gated CAD Router ->
CAD Engine -> Preview -> Review -> Slicer Review -> (never automatic printing)
```

**An adapter/gate around existing local generation, not a second CAD
backend.** It never generates geometry itself - it only decides *whether*
`factory.openscad.generate.generate_openscad()` or
`factory.cad.cadquery_backend.generate_cadquery()` (both already
implemented, in earlier phases) are allowed to run, and if so, with which
template/parameters. Only engines with a real, already-implemented local
backend can ever be generated - today that's OpenSCAD and CadQuery; any
other recommended engine (Blender, `Meshy (Concept Only)`, FreeCAD, Hybrid
Workflow, Manual Design, Unknown) always resolves to `"Unsupported
Engine"`. **Dry run by default** - every entry point defaults to
`confirm_generate=False`, always computing and returning a full
generation plan without ever calling a generation backend, unless
`confirm_generate=True` is explicitly passed *and* every readiness gate
independently passes.

**New module:** `factory.generation_gate`:

- `evaluate_generation_gate(...)` - the core, pure gate decision, in a
  fixed priority order (see `docs/generation-gate.md` "Decision states"
  for the full reasoning): a `Blocked` readiness state always wins;
  an unsupported/unavailable engine always resolves to `"Unsupported
  Engine"`; a readiness state that isn't one of the four `"Ready For ..."`
  states, a score below the gate's own conservative threshold (60%,
  matching the Design Orchestrator's own boundary), a critical advisory
  (`Dimensions missing`/`Material unspecified`/`Printer unspecified`), or
  no confident local template all resolve to `"Dry Run Only"` (even
  `--confirm-generate` cannot force generation past this); otherwise
  `"Needs Confirmation"` or `"Allowed"` depending on `confirm_generate`.
- `plan_generation(...)` - deterministic local template selection: `"sign"`
  for OpenSCAD, `"mechanical-plate"` for CadQuery, `None` (no guess) for
  anything else.
- `run_generation(...)` - the one, explicit write path. Only ever called
  when the gate says `"Allowed"`; calls the existing
  `generate_openscad()`/`generate_cadquery()` directly rather than
  re-implementing CAD generation. Writes CAD *source* only
  (`cad/*.scad`/`cad/*.py`) - STL export remains a separate, manual,
  human-run step, unchanged from every earlier phase.
- `build_execution_receipt(...)` / `write_generation_receipt(...)` -
  **execution receipts**: after a successful confirmed generation (never
  for a dry run), writes `<project_dir>/generated/generation_receipt.json`
  - project, engine, backend, template, readiness score/state, execution
  decision, files generated, artifact sizes, a normalized artifact-
  tracking breakdown, validation status, warnings, errors, success, and
  timestamp. One receipt reflects the most recent confirmed run, not a
  history. Writing it never triggers an automatic console confirmation.
- `build_artifact_tracking(...)` - **artifact tracking**: normalizes CAD
  source, STL, manifest, validation, preview, and review state for a
  confirmed run, reusing existing manifest/validator infrastructure
  wherever possible (reads `part_manifest.json` entries `run_generation()`
  itself already upserted; reads - never re-runs - any existing
  `validation/*.json` report or `renders/*.png` file) rather than
  duplicating mesh/multipart/dimension validation or manufacturing
  inspection.
- `read_last_execution_receipt(...)` / `summarize_generation_execution(...)`
  - read-only lookups over a project's most recent receipt, if any.
- `evaluate_generation_gate_for_path(path, confirm_generate=...)` - the
  convenience entry point `factory generate-from-readiness` uses,
  computing the same `intake_summary`/`design_orchestrator_summary` every
  other Phase 30-33 path-based entry point does.

**New CLI:** `factory generate-from-readiness <path> [--confirm-generate]
[--json]` - dry run by default; only writes with `--confirm-generate`, and
only if the gate allows it. A write conflict from the underlying generator
(most commonly re-running confirmed generation on a project that already
has that template's CAD source) is caught and reported as a clear,
non-crashing `generation_error` (exit code 1) rather than an unhandled
traceback - no receipt is written on that path. `--json` includes
`receipt_path` only when a receipt was actually written; the
human-readable mode never prints a special receipt confirmation line.

Two consumers, both additive:

- **`factory.project_inspection.summarize_project()`** gained an eighth
  additive field, `generation_gate_summary` (compact `{decision,
  recommended_engine, ready, reason}`, always a dry run), and a ninth,
  `generation_execution_summary` (compact `{receipt_available,
  last_execution, last_execution_engine}` - deliberately a separate field
  rather than added keys on `generation_gate_summary`, so that field's
  shape stays exactly as every Generation Gate test already pins it).
  Every earlier field is completely unchanged.
- **`factory.preview_board.build_board_html()`** gained a compact
  "Generation Gate" card section, placed right after "Project Readiness"
  - decision, recommended engine, a Ready Yes/No badge, the top reason why
  (if not ready), and (from `generation_execution_summary`) whether a
  receipt is available and when the last confirmed execution happened
  (`"Never"` if none). Every existing detail card is unchanged and still
  follows it.

**Explicitly unchanged:** every Phase 26-33 field's shape;
`summarize_generation_gate()`'s own return shape
(`{"decision", "recommended_engine", "ready", "reason"}`); the board's
existing summary table and every existing card section;
`factory.review_gate.evaluate_review_gate()`'s JSON output shape (still
never includes `generation_gate_summary` or `generation_execution_summary`).

Never contacts a printer, discovers printers, contacts a slicer, makes a
network call of any kind. Never calls an AI/LLM API, never performs a web
search, never scrapes a website, never downloads anything. Never launches
Blender, never calls Meshy, never generates FreeCAD source, never installs
anything (not `cadquery`, not OpenSCAD). Never exports an STL, never
slices, never prints. Never sets `human_approved`/`print_ready`. Never
re-scores readiness - every score/state/engine value is read from the
Design Orchestrator's already-computed summary, never recomputed here.
Never duplicates mesh validation, multipart validation, dimension
validation, or manufacturing inspection - existing reports are read from,
never re-implemented.

**Not yet started (at the end of Phase 34):** per-category template
selection within an engine (OpenSCAD always generates `"sign"`, CadQuery
always generates `"mechanical-plate"`, regardless of finer-grained
category); multi-part generation plans in one confirmed run; an
append-only execution-receipt history (one receipt reflects only the most
recent confirmed run); any AI/LLM-backed decision-making; Blender/Meshy/
slicer execution - all explicitly out of scope for this phase.

## Phase 35 — Guided Export, Validation, Preview, and Artifact Finalization (complete)

The first complete, explicitly confirmed, local post-generation workflow -
guides Phase 34's CAD source through export, verification, validation,
preview, and artifact finalization, still stopping well short of any
slicer or printer:

```
CAD Source Generation -> Guided Export Pipeline -> STL Verification ->
Validation and Preview -> Artifact Finalization -> Human Review Gate ->
Slicer Review -> (never automatic printing)
```

**This orchestrates existing local commands - it never re-implements CAD
generation, STL export, mesh validation, or preview rendering.** Its one
new capability - actually invoking the OpenSCAD CLI to export an STL - is
the first automated subprocess execution in this repo. **Dry run by
default**, same convention as every gated phase before it: every entry
point defaults to `confirm_export=False`, always computing and returning a
full export plan without ever invoking a subprocess, unless
`confirm_export=True` is explicitly passed *and* every gate independently
passes.

**New module:** `factory.export_pipeline`:

- `plan_export(...)` - the core, pure planning decision, in a fixed
  priority order (see `docs/export-pipeline.md` "Decision states"):
  an unsafe `--source`/`--output-dir` or no recognized CAD source resolves
  to `"blocked"`; an unrecognized source type to `"unsupported_source"`;
  both OpenSCAD and CadQuery source present with no `--source` given to
  `"ambiguous_source"`; CadQuery source always to `"manual_export_required"`
  (this repo's existing manual-only CadQuery policy is unchanged - see
  "OpenSCAD only for automatic export" in `docs/export-pipeline.md`); a
  missing local `openscad` executable to `"export_tool_missing"`; an
  un-overridden existing output STL to `"output_collision"`; otherwise
  `"needs_confirmation"`/`"allowed"` depending on confirmation.
- `resolve_openscad_executable()` - read-only local discovery (a known
  macOS `.app` bundle path, then `PATH` via `shutil.which()`), mirroring
  `factory.slicer.local_slicer_probe.probe_slicers()`'s exact style.
  Never installs, downloads, or launches anything.
- **Freshness/stale detection** - never treats file existence alone as
  currentness. Prefers a `sha256` fingerprint comparison against a prior
  export receipt entry (immune to a modification-time reset); falls back
  to the same epsilon-guarded mtime comparison
  `factory.render_coverage.compute_render_coverage()` already uses.
- `run_export(...)` - the one, explicit subprocess/write path. Only ever
  called when the plan says `"allowed"`; uses argument-list subprocess
  execution (never a shell string), a 120-second timeout, and full
  post-exit verification (output exists, is non-empty, has a `.stl`
  extension) - **a zero exit code alone is never treated as success**.
  Rejects if the source's fingerprint changed since planning (a race).
- `run_validation(...)` / `run_multipart_check(...)` / `run_render(...)` -
  thin wrappers reusing `factory.validators.mesh_validate.validate_mesh()`,
  `factory.validators.multipart_check.check_manifest()`, and
  `factory.previews.render_preview.render_preview()` directly - never
  re-implemented, never reinterpreted (only the PASS/WARN/FAIL label is
  normalized into this phase's own vocabulary). A renderer that reports
  success but produced no non-empty file is never trusted at face value.
- `build_execution_receipt`-equivalent `write_export_receipt(...)` /
  `read_export_receipt(...)` - **execution receipts**:
  `<project_dir>/generated/export_receipt.json`, a **sibling** of Phase
  34's `generation_receipt.json` (never merged into it, so that file's
  shape stays exactly as every current Generation Gate test pins it).
  Upserted **by source file** - the same upsert-by-key pattern
  `factory.openscad.generate._upsert_manifest_parts()` already uses for
  `part_manifest.json` - so a failed or partial run never destroys a
  prior successful record for a different (or untouched) source file.
  Written only after a confirmed run actually attempts something; never
  for a dry run.
- `build_artifact_registry(...)` - normalizes CAD source, STL, validation,
  preview, review, and both receipts into one read-only structure, reusing
  the plan and both receipts rather than re-deriving anything. `"review"`
  is a pointer string, not a computed result, since this module must stay
  a leaf the same way `factory.generation_gate` does.
- `--resume` support - skips a source file's export/validate/render step
  when the receipt already records it as current for that exact source
  fingerprint; reruns only what's missing, failed, or stale.

**New CLI:** `factory export-from-cad <path> [--confirm-export] [--json]
[--source ...] [--output-dir ...] [--overwrite-stl] [--validate] [--render]
[--all] [--resume]` - dry run by default; only writes/executes with
`--confirm-export` and only if the plan allows it. `--json` output is the
entire stdout on every path, including errors (missing project, an unsafe
path) - no plain text is ever printed before or after the JSON payload.
Writing the receipt itself triggers no console confirmation message in
human-readable mode; `--json` surfaces `receipt.path` as data instead.

Two consumers, both additive:

- **`factory.project_inspection.summarize_project()`** gained a tenth
  additive field, `export_pipeline_summary` (source engine/count, exporter
  availability, expected/current/stale STL counts, aggregate validation/
  preview status, last completed stage, `pipeline_complete`, blockers).
  Read-only - never exports, validates, renders, or invokes a subprocess.
  Every earlier field is completely unchanged.
- **`factory.preview_board.build_board_html()`** gained a compact
  "Post-Generation Pipeline" card section, placed right after "Generation
  Gate" - CAD source/STL/validation/preview status, and either the next
  suggested step or (once complete) a "Pending human approval" reminder.
  Every existing detail card is unchanged and still follows it.

**Explicitly unchanged:** every Phase 26-34 field's shape;
`factory.generation_gate`'s own receipt file and its exact schema; the
board's existing summary table and every existing card section;
`factory.review_gate.evaluate_review_gate()`'s JSON output shape (still
never includes `export_pipeline_summary`); `factory generate-openscad`/
`generate-cadquery`/`validate`/`render` all unchanged and still fully
functional on their own.

Never contacts a printer, discovers printers, contacts a slicer, makes a
network call of any kind. Never calls an AI/LLM API, never performs a web
search, never scrapes a website, never downloads anything. Never invokes
Blender, Meshy, or FreeCAD. Never installs anything (not OpenSCAD, not
`cadquery`). **Never executes CadQuery source automatically** - this
repo's existing manual-export policy for CadQuery is unchanged. Never
slices, never prints, never sets `human_approved`/`print_ready`. Never
re-scores project readiness or the Generation Gate decision - those are
read from Phase 30-34's own already-computed summaries where relevant,
never recomputed here. Never duplicates mesh validation, multipart
validation, dimension validation, or manufacturing inspection - existing
validators/checks are called directly, never re-implemented.

**Not yet started (at the end of Phase 35):** a configurable export
timeout (fixed at 120 seconds); an append-only execution-receipt history
across every past run (one receipt entry per source file reflects only
its most recent attempt); automatic CadQuery script execution (remains an
explicit, out-of-scope policy decision, not a technical gap); any AI/LLM-
backed decision-making; Blender/Meshy/slicer/printer execution - all
explicitly out of scope for this phase.

## Phase 36 — Slicer Review Readiness Promotion and Review Package (complete)

The formal bridge between Phase 35's completed export/validate/render
pipeline and human slicer review:

```
Guided Export Pipeline -> STL Validation and Preview -> Artifact
Finalization -> Slicer Review Readiness -> Human Approval -> Manual
Slicer Review -> (never automatic printing)
```

**This is a thin assessment/promotion layer over already-computed
state - it never re-implements mesh validation, render-freshness
checking, review-gate logic, slicer detection, artifact fingerprinting,
manifest-completeness checks, or manufacturing checks.** It reads
`factory.project_inspection.summarize_project()` (already reusing Phase
8-35's own logic), `factory.review_gate.evaluate_review_gate()` (the
existing pass/warn/fail gate, never rewritten), and
`factory.slicer.local_slicer_probe.probe_slicers()` (existing read-only
slicer discovery) - and combines them into one deterministic readiness
assessment, score, and (only with explicit confirmation) a local review
package conforming to the pre-existing `schemas/slicer_review.schema.json`.

**Read-only unless explicitly creating an approved package or recording
approval.** `assess_slicer_readiness()` never writes anything. Only
`record_approval()` and `create_review_package()` write, and only when
explicitly called - the CLI gates both behind explicit flags (`--approve`
and `--create-package --confirm-package` respectively).

**Technical readiness and human approval are separate states, never
conflated.** A project can be `ready_for_review_package`-eligible on
every technical signal and still have no approval recorded - approval is
always a separate, explicit, human-recorded action, invalidated
automatically the moment a relevant artifact's fingerprint changes.

**New module:** `factory.slicer_readiness`:

- `assess_slicer_readiness(project_dir)` - the core, read-only assessment.
  Computes 11 machine-readable `readiness_status` values in a fixed
  priority order (first match wins; see `docs/slicer-readiness.md`
  "Decision states"): `unsupported_project_state`, `blocked` (Review Gate
  fail, a validation failure, or multipart-incomplete manifest),
  `not_ready` (missing STL), `stale_artifacts`, `needs_validation`,
  `needs_preview`, `needs_manifest_completion`, `needs_information`
  (Design Orchestrator "Not Ready" - a much rarer, lower bar than its
  common "Needs Information" resting state, which is folded into
  `warnings` only, never a blocker), `needs_human_approval`,
  `ready_for_review_package`, `review_package_created`.
- A documented, weighted **readiness score** (STL 25% / validation 25% /
  preview 15% / manifest 15% / manufacturing 10% / receipts 5% / review
  gate 5%, summing to 1.0) - purely informational. `readiness_status` is
  computed entirely independently of the score, so a high score can never
  bypass a hard blocker (e.g. a failed validation still reports `blocked`
  regardless of how well everything else scores).
- **Review Gate's own documented semantics are honored exactly**: a
  `"warn"` result is folded into `warnings` only, never treated as a
  blocker - re-interpreting it as blocking would contradict
  `docs/review-gate.md`'s own stated policy.
- A separate **human-approval lifecycle**: `record_approval(project_dir,
  note=..., approved_by=...)` - raises `ApprovalNotAllowedError` unless
  `readiness_status` is already `needs_human_approval` or better. Snapshots
  `sha256:`-fingerprints of every relevant artifact (source CAD, current
  STL, validation reports, renders, `part_manifest.json`,
  `build_plan.json`) at approval time; `assess_slicer_readiness()`
  automatically reports `approval_status: "invalidated"` the moment any
  fingerprint no longer matches, never silently trusting a stale approval.
- **Review package creation**: `create_review_package(project_dir,
  output_dir=..., overwrite=...)` - raises `PackageNotAllowedError` unless
  technically ready *and* approved, `PackageCollisionError` if a package
  already exists and `overwrite=False`. Writes
  `slicer_review/slicer_review_manifest.json` (validated against the
  pre-existing `schemas/slicer_review.schema.json` - not a new, invented
  shape) plus a human-readable `slicer_review/README.md` checklist.
  **References existing STL/validation/render files by relative path -
  never copies them**, mirroring `factory.preview_package`'s own
  established convention. `auto_print_allowed` is always `false`.
- `build_review_checklist(...)` - a tailored (never invented) human review
  checklist: identity, geometry, orientation, material, printer,
  print-strategy, and risk items, plus extra multi-material/AMS-mapping
  items only when the project's own manifest data says it's multi-part.
- Sibling **execution receipt**: `generated/slicer_readiness_receipt.json`
  - a third sibling of Phase 34's generation receipt and Phase 35's export
  receipt, holding only approval and package state (never the technical
  assessment itself, which is always recomputed fresh on every call).
- `summarize_slicer_readiness(project_dir)` - a compact summary for the
  Preview Board (status, score, approval/package status, blocker/warning
  counts, next action).

**New CLI:** `factory slicer-readiness <project_dir> [--json]
[--create-package] [--confirm-package] [--output-dir ...] [--approve]
[--approval-note ...] [--refresh] [--include-warnings] [--force-package]`
- read-only by default; `--approve` and `--create-package
--confirm-package` are the only write paths, each gated behind its own
explicit flag. `--json` output is the entire stdout on every path,
including errors - no plain text is ever printed before or after the JSON
payload. Human-readable output ends with an explicit "No slicer was
opened." / "No file was uploaded." / "No print was started." trailer.

**Architectural discovery reported before implementing around it:** the
task's suggested placement for the board's new field was an additive
`slicer_readiness_summary` field on
`factory.project_inspection.summarize_project()`, matching every prior
phase's pattern. This is not possible here: `factory.slicer_readiness`
must call `factory.review_gate.evaluate_review_gate()` directly (per the
task's own requirement to reuse Review Gate rather than rewrite it), and
`review_gate.py` already imports `summarize_project()` - adding the field
inside `project_inspection.py` would create a genuine circular import
(`project_inspection -> slicer_readiness -> review_gate ->
project_inspection`), confirmed empirically while building this phase.
Resolution: `summarize_slicer_readiness()` lives in `factory.slicer_readiness`
instead, and `factory.preview_board.gather_board_data()` calls it per
project and merges the result in at the aggregation point - the same
visible per-project field, from a layer above `project_inspection.py`
rather than below it. See `docs/slicer-readiness.md` "Architectural note".

Two consumers, both additive:

- **`factory.preview_board.gather_board_data()`** merges
  `slicer_readiness_summary` into each project's dict (see the
  architectural note above for why it isn't on `summarize_project()`
  itself).
- **`factory.preview_board.build_board_html()`** gained a compact "Slicer
  Review Readiness" card section, placed right after "Post-Generation
  Pipeline" - status/score/approval/package status, blocker and warning
  counts, and the next suggested action. Every existing detail card is
  unchanged and still follows it.

**Explicitly unchanged:** every Phase 26-35 field's shape;
`factory.review_gate.evaluate_review_gate()`'s own logic and JSON output
shape (still never includes `slicer_readiness_summary`);
`factory.export_pipeline`'s receipts and CLI; the board's existing summary
table and every existing card section.

Never contacts a printer, discovers printers, contacts a slicer, makes a
network call of any kind. Never calls an AI/LLM API, never performs a web
search, never scrapes a website, never downloads anything. Never invokes
Blender, Meshy, or FreeCAD, and never installs anything. Never slices,
uploads, queues, or submits a print job - `auto_print_allowed` is always
`false` and the CLI always prints an explicit no-automatic-print trailer.
Never re-implements mesh validation, render-freshness checking,
review-gate logic, slicer detection, or manufacturing checks - each is
read directly from its existing module.

**Not yet started (at the end of Phase 36):** copying (rather than only
referencing) artifacts into a portable review package - deliberately
deferred, since the task's own guidance preferred references over
unnecessary duplication unless a portable package is a deliberate future
goal; an append-only approval/package history across every past run (the
receipt reflects only the current approval/package state); any AI/LLM-
backed decision-making; Blender/Meshy/slicer/printer execution - all
explicitly out of scope for this phase.

## Phase 37 — Slicer Profile Inspection & Manual Review Workspace (complete)

The Factory's first true pre-slicer review workspace - organizes
everything a human needs before opening Bambu Studio, OrcaSlicer, or
another slicer:

```
Guided Export Pipeline -> STL Validation and Preview ->
Slicer Review Readiness -> Human Approval -> Review Package ->
Manual Review Workspace -> Human Slicer Review ->
(never automatic printing)
```

Phase 36 determines that a project is technically ready; Phase 37
organizes everything a human needs on top of that - it does not slice,
does not generate G-code, and does not print.

**This is a thin organizing layer over already-computed state - it never
re-implements mesh validation, the artifact registry, the preview
package, Review Gate logic, slicer discovery, or receipt tracking.** It
reuses `factory.slicer_readiness.assess_slicer_readiness()` directly for
every technical/approval/package signal, and
`factory.manufacturing.knowledge` for local printer/material reference
data. It adds two genuinely new things: printer/material profile
inspection (always reporting `"Unknown"` rather than inventing a value
that isn't actually known) and a structured, multi-category human review
checklist plus a deterministic `review_confidence`/`remaining_risk` pair.

**New module:** `factory.manual_review_workspace`:

- `assess_manual_review_workspace(project_dir)` - the core, read-only
  assessment. `workspace_status` is a fixed 5-state ladder
  (`not_ready`/`needs_approval`/`ready_to_create`/`stale_workspace`/
  `workspace_created`) mirroring `factory.slicer_readiness`'s own state
  machine style, computed from the underlying Phase 36
  `readiness_status`/`approval_status` (never re-derived) plus the
  workspace file's own fingerprint-based staleness check.
- `_printer_profile(build_plan)` - reuses
  `factory.manufacturing.knowledge.get_printer()`/`printer_capabilities()`.
  Reports display name, nozzle size, build volume, and AMS availability
  from the local printer knowledge base; **layer height is always
  `"Unknown"`** since this repo's printer knowledge base never records it
  (a per-print slicer-profile choice, not a printer hardware attribute) -
  reported honestly rather than guessed.
- `_material_summary(manifest_json)` - per-part material/color state from
  `part_manifest.json`, cross-referenced against
  `factory.manufacturing.knowledge.load_materials()` via an **exact**
  (case-insensitive) match only - never fuzzy-matched, never invented for
  an unmatched value.
- `build_structured_review_checklist(...)` - a structured, multi-category
  checklist (Geometry, Scale, Orientation, Supports, Walls, Top/Bottom,
  Infill, Material, Color, AMS, Multipart Assembly, Moving Parts,
  Tolerances, Clearances, Fragile Features, Build Volume, Estimated Risks,
  Human Approval) - richer than Phase 36's flat list, with AMS/Multipart
  Assembly/Build Volume categories included only when the project's own
  printer/manifest data actually supports them.
- `_review_confidence(...)`/`_remaining_risk(...)` - purely deterministic,
  derived from the already-computed Phase 36 assessment plus
  printer/material resolution; never a re-score of readiness itself.
- `create_manual_review_workspace(...)` - the one write path. Writes
  `manual_review/review_manifest.json` plus a human-readable
  `manual_review/README.md` (checklist + warnings + a Human sign-off
  section) - only once the underlying Phase 36 assessment is both
  technically ready and approved (the same gate `create_review_package()`
  uses - a workspace is never more permissive than the package it
  organizes). **References existing STL/validation/render/package files
  by relative path - never copies them.** Does not strictly require a
  Phase 36 review package to already exist (references one if present, a
  deliberate scope decision - see `docs/manual-review-workspace.md`
  "Limitations").
- Sibling **execution receipt**: `generated/manual_review_workspace_receipt.json`
  - a fourth sibling of Phase 34/35/36's own receipts, holding only
  workspace creation state; its fingerprint set includes the Phase 36
  review package file itself, so recreating the package also invalidates
  a previously created workspace.
- `summarize_manual_review_workspace(project_dir)` - a compact summary for
  the Preview Board.

**New CLI:** `factory review-workspace <project_dir> [--json]
[--create-workspace] [--confirm-workspace] [--output-dir ...]
[--force-workspace]` - read-only by default; `--create-workspace
--confirm-workspace` is the only write path (both required together).
Human-readable output ends with an explicit "No slicer was opened." /
"No G-code was generated." / "No print was started." trailer.

**Bug found and fixed during this phase:** the initial `workspace_status`
ladder gated `needs_approval` vs. `not_ready` on `readiness_status in
("ready_for_review_package", "review_package_created")` alone - missing
that `needs_human_approval` represents the *same* underlying
"everything technical is satisfied" condition, just before approval is
recorded (Phase 36's own ladder ties `readiness_status` and
`approval_status` together: unapproved always resolves to exactly
`needs_human_approval`). This made every unapproved-but-otherwise-ready
project incorrectly report `not_ready` instead of `needs_approval`.
Caught during this phase's own manual end-to-end lifecycle verification
and fixed by broadening the gate to `_TECHNICALLY_READY_STATES`
(`needs_human_approval` plus both approved-adjacent states). See
`docs/manual-review-workspace.md` "Workspace status".

Two consumers, both additive:

- **`factory.preview_board.gather_board_data()`** merges
  `manual_review_summary` into each project's dict (same architectural
  reasoning as Phase 36's `slicer_readiness_summary` - see
  `docs/manual-review-workspace.md` "Architectural note").
- **`factory.preview_board.build_board_html()`** gained a compact "Manual
  Review Workspace" card section, placed right after "Slicer Review
  Readiness" - workspace status, printer, material, review confidence,
  remaining risk, and package availability. Every existing detail card is
  unchanged and still follows it.

**Explicitly unchanged:** every Phase 26-36 field's shape;
`factory.slicer_readiness`'s own assessment/approval/package logic and
CLI; `factory.review_gate.evaluate_review_gate()`'s own logic and JSON
output shape (still never includes `manual_review_summary`); the board's
existing summary table and every existing card section.

Never contacts a printer, discovers printers, contacts a slicer, makes a
network call of any kind. Never calls an AI/LLM API, never performs a web
search, never scrapes a website, never downloads anything. Never invokes
Blender, Meshy, or FreeCAD, and never installs anything. Never slices,
generates G-code, queues a print job, or submits a print - the CLI always
prints an explicit no-automatic-print trailer. Never re-implements mesh
validation, the artifact registry, the preview package, Review Gate
logic, slicer detection, or receipt tracking - each is read directly from
its existing module.

**Not yet started (at the end of Phase 37):** copying (rather than only
referencing) artifacts into the workspace - deliberately deferred, same
reasoning as Phase 36's own package; requiring a Phase 36 review package
to exist before workspace creation (a deliberate scope decision, not a
technical gap); fuzzy/approximate material matching against the local
knowledge base (exact match only, by design); an append-only workspace
history across every past run; any AI/LLM-backed decision-making;
Blender/Meshy/slicer/printer execution - all explicitly out of scope for
this phase.

## Future tracks, not yet phase-numbered

Named so future docs can cite them without a number that might collide
with a later ad hoc phase (see "Roadmap numbering policy" above). None of
these have a scheduled start; each will take the next available phase
number, per the policy above, once someone actually begins it.

### Meshy approval/cost-gated implementation track

The actual Meshy-calling implementation - uploads, generation calls,
mesh acceptance - gated behind everything `docs/meshy-approval-gate.md`
(written in Phase 16) requires: explicit human approval, a cost/budget
cap, per-run confirmation, input review before upload, output review
after generation, a local storage policy, license/ownership notes,
student/privacy/data notes, and a local-only fallback. `config/
future_cloud_tools.json`'s `meshy.enabled` stays `false` until a human
flips it as a separate, explicit, reviewed decision - not as part of
starting this track. Output review is also a design-quality gate, not
just a geometry check - see `docs/meshy-approval-gate.md`'s
"Design-quality gate" (Phase 22) and `docs/design-quality-standard.md`:
"generated a mesh" and "worth keeping" are different questions.

### Blender local repair/render track

Scripted (non-interactive) Blender invocations for mesh repair (fixing
non-manifold geometry flagged by `factory validate`) and higher-fidelity
preview renders, as a local subprocess call — no Blender add-ons, no
Blender MCP. The full required gate this track must satisfy before
implementation was written down in advance in Phase 21
(`docs/blender-local-track.md`); `config/future_local_tools.json`'s
`blender.enabled` stays `false` until a human flips it as a separate,
explicit, reviewed decision - not as part of starting this track. Repairs
and renders must also preserve or improve design quality, not just fix
geometry - see `docs/blender-local-track.md`'s "Design-quality review for
Blender outputs" (Phase 22) and `docs/design-quality-standard.md`.

### 3MF packaging experiments track

Experimental packaging of multi-part projects into a single `.3mf` with
embedded per-part color/material assignments, as an alternative to the
separate-aligned-STL workflow in `docs/slicer-review-workflow.md`.

### Advanced slicer review automation track

Richer slicer-review package generation (e.g. auto-populated checklists
from validation reports, plate-layout suggestions) — still ending at
human review, never at auto-slice or auto-print.

### Rich organic examples track

Real (not concept-only) car/animal/human-figure examples under
`examples/future-organic-models/` - blocked on the Meshy and/or Blender
tracks above actually being implemented first.

### Custom Design Quality Pipeline

A planning layer for high-quality custom designs: style direction,
reference interpretation, artistic intent, functional requirements,
manufacturability constraints, and iteration loops. Defines the "Etsy-worthy"
quality bar (see `docs/design-quality-standard.md`) that the Meshy,
Blender, and Rich organic examples tracks above should aim for once they
exist - not a generation pipeline itself, and not a relaxation of any
existing safety gate. Blocked on the Meshy and/or Blender tracks above for
any real (non-planning) implementation. Phase 22 connected this standard
into both future-gate docs' review checklists (`docs/meshy-approval-gate.md`'s
"Design-quality gate", `docs/blender-local-track.md`'s "Design-quality
review for Blender outputs") - still planning only, still no
implementation.

### Mac launcher/dashboard track

The Mac app launcher, Dock icon, Shortcuts/Automator wrapper, "Chief of
Staff" command, local visual dashboard, and the visual preview requirements
(mesh preview, CAD source preview, manufacturing option preview,
multipart/exploded preview, planning board) described in
`docs/product-vision.md` are a long-term direction layered on top of the
CLI engine above, not a specific numbered phase yet. They will be assigned
phase numbers once a concrete implementation is scoped.

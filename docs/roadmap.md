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

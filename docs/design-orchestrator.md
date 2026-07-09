# Design Orchestrator (Phase 33)

`factory.design_orchestrator` is the first "decision brain" in this
repo's pipeline:

```
User Idea -> Project Intake -> Draft Brief -> Brief Merge ->
Design Intent -> Reference Board -> Project Readiness ->
Design Orchestrator -> CAD Engine -> Preview -> Review ->
Slicer Review -> (never automatic printing)
```

It evaluates whether a project is **sufficiently defined to proceed**, and
- if so - recommends the most appropriate downstream design engine
(OpenSCAD, CadQuery, Blender, Meshy, FreeCAD, a hybrid workflow, manual
design, or "not enough information to say"). **It does not generate CAD.**
Nothing downstream is ever invoked automatically - every recommendation is
a string a human reads and acts on themselves.

## Why deterministic

Same reasoning as every heuristic layer in this pipeline
(`factory.project_intake`, `factory.brief_generator`): a small, closed set
of rules, checked in a fixed, documented order, so the same six input
summaries always produce the exact same readiness state, score, and engine
recommendation - no model, no randomness, no network call, and (crucially)
a rule a human can read, question, and override. This matters more here
than anywhere else in the pipeline so far, because this module's output
- "go use OpenSCAD" vs "go use Blender" - is the highest-leverage decision
in the whole system: get it wrong and a human wastes real time in the
wrong tool.

## Never re-parses, never duplicates extraction

Every function here takes **already-computed summaries** as input:
`intake_summary` (Phase 30), `draft_brief_summary` (Phase 31),
`brief_update_summary` (Phase 32), `design_intent_summary`/
`design_intent_detail` (Phase 26/27), and `reference_board_summary`
(Phase 28). It only reads their already-parsed fields (confidence levels,
counts, structured values) - it never re-runs Phase 30's keyword/regex
extraction, never re-reads `brief.json`'s free text directly, and never
imports `factory.project_inspection` (that would be circular -
`project_inspection` imports *this* module, not the other way around).

Where a text-based recommendation is still useful (no structured category
signal at all), it reuses `factory.router.recommend_tool()` - the
existing, single source of truth for OpenSCAD/CadQuery/Blender/Meshy
keyword categories (`docs/tool-routing.md`, built in an earlier phase)
- rather than inventing a second, divergent keyword table that could drift
out of sync with it.

## Readiness scoring

`compute_readiness_score()` returns a weighted overall score (0-100) plus
a per-category breakdown. **Weights** (sum to 1.0, documented as
`CATEGORY_WEIGHTS` in code - the single source of truth):

| Category | Weight | What it measures |
|---|---|---|
| Intake | 20% | Reuses Phase 31's own `readiness.percent_populated` directly - how much of `intake_summary`'s 13 tracked fields have high/medium confidence. |
| Brief | 20% | `fields_preserved_count / 8` - how many of the 8 fields `merge_draft_brief()` can ever touch already hold real (non-placeholder) content in the existing `brief.json`. |
| Design Intent | 25% | 4 sub-checks on `design_intent_detail`: `quality_standard` set, `use_case` set, `style_direction` non-empty, and the manufacturability check landing on a definite "fits some configured printer" result. |
| Reference Board | 15% | 3 sub-checks on `reference_board_summary`: has at least one reference, every reference is attached to `design_intent.reference_inputs`, and no advisory warnings were raised. |
| Manufacturing | 20% | 4 sub-checks directly on `intake_summary`'s own confidence fields: printer/material/manufacturing-style/dimensional-constraints assumptions each independently confident. |

**Why these weights specifically**: Design Intent gets the largest single
weight (25%) because it's the field most directly tied to *what a human
actually wants the object to be* - category, environment, quality target,
material, printer all matter, but design intent (quality standard, use
case, style, a manufacturability check that's actually passed) is the
closest thing this pipeline has to "has a human articulated a real
design." Reference Board gets the smallest weight (15%) because it's
genuinely optional for many well-defined projects (a simple parametric
sign never needs a reference image) - a low reference-board score
shouldn't tank an otherwise well-defined mechanical part's readiness.
Intake, Brief, and Manufacturing are weighted equally (20% each) as the
three "is there enough raw material to work with" categories.

Every category score is computed by reading fields an earlier phase
already parsed - see the table above for exactly which field. None of the
five `_score_*()` functions ever re-run text extraction; all of them
defensively coerce a malformed/wrong-type input (e.g. a hand-edited
`.json` intake-summary file with the wrong shape) to a clean `0`/empty
result rather than raising.

## Readiness states

Checked in this exact priority order (see `determine_readiness_state()`):

1. **`Blocked`** - always wins, regardless of score. Fires when
   `design_intent_detail["manufacturability_result"] == "fits_no_known_printers"`
   - the declared design intent doesn't fit *any* locally configured
   printer. This is the one condition serious enough to override
   everything else: no amount of intake/brief/reference-board completeness
   makes an unbuildable size buildable.
2. **`Not Ready`** - overall score < 25%.
3. **`Needs Information`** - overall score in [25%, 60%), or (having
   passed the score gate) no organic or mechanical signal at all to
   recommend an engine from.
4. **`Ready For Mixed Workflow`** - score >= 60% and `is_mixed` (see
   "Organic vs. mechanical signal" below) - checked *before* either pure
   state, since a genuinely mixed design shouldn't be forced into one
   family.
5. **`Ready For Manufacturing Review`** - score >= 90%, Design Intent
   category >= 75%, Reference Board category >= 60% - a "graduation"
   state for a project complete enough that the next real decision is
   manufacturing planning, not more design work.
6. **`Ready For Organic Modeling`** / **`Ready For Mechanical CAD`** -
   score >= 60% with a clear single-family signal.

## Organic vs. mechanical signal, and why a single style word isn't enough

`compute_design_signals()` is the shared signal-detection function both
`determine_readiness_state()` and `recommend_engine()` call (once,
reused - they can never disagree about the same evidence).

**Category is the strongest signal** (Phase 30's closed vocabulary) and
counts as a **weight-2 vote** for its family:
- `sign`/`organizer`/`storage`/`educational` -> OpenSCAD-leaning
  (parametric plates/signs/labels/organizers - matches
  `factory.router._OPENSCAD_KEYWORDS`).
- `fixture`/`replacement part`/`accessory`/`mechanical` -> CadQuery-leaning
  (precision fits, brackets, mounts, mechanisms - matches
  `factory.router._CADQUERY_KEYWORDS`).
- `toy`/`décor` -> organic-leaning.

Each `style_direction`/`visual_goals` keyword hit is a **weight-1 vote**.
`is_mixed` only fires when **both sides reach at least weight-2** -
comparable, real signal on both sides, not one confident category vote
against a single incidental style word.

**This threshold exists because of a real case found during this phase's
own testing.** The committed Phase 30 benchmark
(`examples/intake-benchmarks/teacher-nameplate.md`) declares category
`"sign"` (weight 2, mechanical) and its own `visual_goals` include
`"anime"` (organic) alongside `"raised"`/`"lettering"` (mechanical). A
naive "any organic keyword + any mechanical keyword = mixed" rule would
call a plain classroom nameplate "mixed" just because its lettering style
is anime-inspired - clearly wrong; it's still fundamentally a flat,
parametric sign. With the weight-2 threshold: mechanical strength = 2
(category) + 2 (raised, lettering) = 4; organic strength = 1 (anime); not
mixed; mechanical wins -> `OpenSCAD`. A genuinely mixed design (e.g. "a
mechanical mount with an ornate, decorative organic section") needs *two*
organic keyword hits (or an organic-leaning category) to reach weight 2
and register as mixed.

## Engine recommendation

`recommend_engine()`, in order:

1. **Blocked** -> `"Manual Design"` (a human needs to resize/split the
   design before any engine, automated or not, can help).
2. **`is_mixed`** -> `"Hybrid Workflow"`.
3. **Organic signal wins or ties** -> `"Blender"` if there's enough
   definition (`overall score >= 60`), else `"Meshy (Concept Only)"` - see
   "Meshy vs. Blender" below.
4. **Mechanical signal wins**, category-leaning known -> `"CadQuery"` or
   `"OpenSCAD"` directly from the category.
5. **Mechanical signal from style keywords only**, no category match ->
   deferred to `factory.router.recommend_tool()` on the best available
   description text (reused, not duplicated).
6. **No structured signal at all** -> the same shared text router as a
   last resort; if that also comes back `"unspecified"` (or there's no
   text at all) -> `"Unknown"`.

`"FreeCAD"` is a recognized value in `RECOMMENDED_ENGINES` with **no
current rule that selects it** - reserved for a future, more sophisticated
complex-assembly-detection rule this phase deliberately doesn't invent
without a concrete worked example to validate it against (see
"Limitations" below).

### Meshy vs. Blender

An organic/sculptural signal alone doesn't automatically mean "ready for
Blender." If the overall readiness score is still low (`< 60`), the
project reads as **too conceptual for local modeling to be worth starting
yet** - the recommendation is `"Meshy (Concept Only)"` instead, echoing
this repo's own established treatment of concept-only organic ideas (see
`examples/future-organic-models/`, all `concept_only`, all gated behind
`docs/meshy-approval-gate.md`'s explicit human-approval-and-cost-review
requirement - Meshy is **never called automatically** by this or any other
module). Once a project has enough real definition (a populated
`design_intent`, maybe a reference or two, some dimensional/material
signal - pushing the score past 60), the same organic signal recommends
`"Blender"` instead - there's now enough to justify local modeling time.

## Advisories

Consolidated, orchestrator-level phrasing (deliberately different wording
from the underlying phases' own advisories, since these are read directly
off already-computed *data* fields, not re-scanned text - see
`generate_readiness_advisories()`):

```
Dimensions missing              - intake_summary.dimensional_constraints not confident
Material unspecified            - intake_summary.material_assumptions not confident
Printer unspecified             - intake_summary.printer_assumptions not confident
Reference images recommended    - high quality bar (premium/etsy-worthy/gift/presentation), zero references
Design intent incomplete        - Design Intent category score < 100%
Commercial review recommended   - intake_summary.commercial_intent is True with high confidence
Manufacturing review required   - Manufacturing category score < 100%
Human approval required         - always the last entry, unconditionally
```

## The `factory readiness` CLI

```bash
factory readiness <project_dir>                              # one project's full report
factory readiness <projects_root>                             # e.g. examples/ or projects/ - a table across every project found
factory readiness <text_or_markdown_file>                     # a pre-project idea, analyzed the same way `factory intake analyze` would read it
factory readiness <path> --json                                # machine-readable
```

Dispatch: `path` is treated as a **single project** if it directly
contains its own `brief.json` or `concept_brief.json`; otherwise, if it's
a directory, it's treated as a **projects root** (scanned the same way
`factory preview-board`/`discover_projects()` does - every immediate
subdirectory is one project); otherwise it's a **file**, analyzed the same
way `factory intake analyze`/`factory intake suggest-brief` would (no
`design_intent`/`reference_board` possible yet, since there's no
`brief.json` to read them from - those two categories score `0`
naturally, no special-casing needed).

Sample output (single project):

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

This is a deterministic, local-only recommendation - no AI, no LLM, no network, and no engine was invoked.
```

Never writes any file, never invokes any engine, never contacts a
network/printer/slicer - purely read-only, purely advisory.

## Connected to project inspection and the preview board

`factory.project_inspection.summarize_project()` gained a seventh
additive field, `design_orchestrator_summary` -
`evaluate_project_readiness()`'s full result, computed from the six
summaries above (never re-parses anything). Always a dict, never `None`.
Purely additive: none of the earlier six fields are read or modified, and
`design_orchestrator_summary` is never read by
`classify_visual_readiness()`, `build_health_signals()`, or
`build_suggested_actions()`.

The preview board's **HTML** gained a "Project Readiness" dashboard
section, placed **first** in each project's card - overall score,
recommended engine, readiness state, and the top remaining advisories.
**This dashboard summarizes the existing detail cards below it; it
replaces none of them** - Project Intake, Draft Brief, Brief Update,
Design Intent, Reference Board, Manufacturing Overview, Artifacts, Health
Signals, and Review Readiness are all unchanged and still follow it. Same
guarantees as every other card section: purely presentational, no
JavaScript, no external assets, and (same guarantee as the module itself)
this card never generates CAD or invokes any engine.

## Limitations

- **Keyword/category-based, not geometric.** This module never inspects
  actual mesh geometry, part count, or CAD complexity - "mechanical" vs.
  "organic" is inferred entirely from Phase 30's category classification
  and style keywords, the same limitations documented in
  `docs/project-intake.md` apply here too (English-only, no negation
  understanding, no context/coreference resolution).
- **The weight-2 mixed-signal threshold is a deliberate, tunable
  trade-off**, not a law of nature - it was chosen specifically to get the
  committed teacher-nameplate benchmark right (not "mixed" from one
  incidental style word) while still correctly detecting a genuinely mixed
  design with two-or-more organic keyword hits. A different, more
  sophisticated project might need a different threshold; this one is
  simple, documented, and testable, not claimed to be optimal.
- **`FreeCAD` is never actually recommended by any current rule** - it's a
  recognized value in `RECOMMENDED_ENGINES`, reserved for a future,
  more-sophisticated complex-assembly-detection rule once there's a
  concrete worked example to build and test it against, rather than an
  invented, unvalidated heuristic today.
- **The "Ready For Manufacturing Review" graduation thresholds (score
  >= 90%, Design Intent >= 75%, Reference Board >= 60%) are also
  deliberately chosen constants**, not derived from any formula - same
  "simple, documented, testable, not claimed optimal" caveat.
- **No cross-project comparison or history.** Each readiness evaluation is
  computed fresh from that project's current state; there's no trend,
  no "readiness went up/down since last time."

## Non-goals

- **No AI, no LLM, no machine learning of any kind** - every function here
  is a pure function over already-structured dicts (plus one call to
  `factory.router.recommend_tool()`'s own closed keyword table); there is
  no model anywhere in this module.
- **No network calls, no web search, no scraping.**
- **No CAD generation of any kind** - OpenSCAD, CadQuery, FreeCAD source
  is never generated, never even templated; this module only names an
  engine.
- **No Blender, Meshy, or FreeCAD execution** - `"Blender"`/
  `"Meshy (Concept Only)"`/`"FreeCAD"` are strings a human reads and acts
  on; nothing in this module (or anything it calls) launches, imports, or
  contacts any of them.
- **No automatic design creation** - this module recommends, it never
  creates a project, a brief, a design_intent block, or a reference.
- **No automatic manufacturing** - `Manufacturing review required` is an
  advisory string, not a trigger for anything in
  `factory.manufacturing`.
- **Does not set `human_approved` or `print_ready`** on anything, ever.

## Future engine integrations

This module's `RECOMMENDED_ENGINES` vocabulary (`OpenSCAD`, `Blender`,
`Meshy (Concept Only)`, `CadQuery`, `FreeCAD`, `Hybrid Workflow`, `Manual
Design`, `Unknown`) is the intended dispatch target list for a future
phase that actually *wires up* engine execution - `factory.cad.router`
already exists as the local OpenSCAD/CadQuery backend router this module
partially reuses (`factory.router.recommend_tool()`); a Blender local
track and a Meshy cost/approval-gated track are both already planned (see
`docs/blender-local-track.md`, `docs/meshy-approval-gate.md`) but not yet
implemented. This phase's job was narrowly to build the decision layer
those future integrations will read from - not to build them.

See also `docs/project-intake.md` (Phase 30), `docs/brief-generator.md`
(Phase 31/32), `docs/design-intent-brief.md`, `docs/reference-board.md`,
`docs/tool-routing.md` (the shared `factory.router` keyword tables this
module reuses), `docs/cad-backends.md`, `docs/preview-board.md`, and
`docs/roadmap.md` Phase 33.

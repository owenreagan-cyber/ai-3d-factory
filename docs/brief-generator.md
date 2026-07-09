# Intake-to-Brief Draft Generation (Phase 31) and Safe Merge/Update (Phase 32)

`factory.brief_generator` is the second and third steps in this repo's
pipeline:

```
User Idea -> Project Intake -> Draft Brief -> Brief Merge/Update ->
Design Intent -> Reference Board -> Manufacturing Planning ->
CAD Generation -> Preview Board -> Review Gate -> Slicer Review ->
(never automatic printing)
```

It converts an already-computed `intake_summary` (Phase 30,
`factory.project_intake`) into a **human-reviewable draft**: a proposed
`brief.json`, a proposed `design_intent` block, and a set of manufacturing
notes (Phase 31) - and, since Phase 32, can safely **merge** that draft
onto a real project's *existing* `brief.json` without ever overwriting
whatever a human already wrote there. Neither phase writes anything by
itself, and neither re-parses free text - the keyword/regex heuristics
that produced `intake_summary` live entirely in `factory.project_intake`
and are never duplicated here. This module's only job is *shaping*
already-extracted data into draft/merge artifacts.

## Purpose

Phase 30 tells you *what a human's idea seems to contain*. Phase 31 turns
that into *what a project's files could look like* - without ever
committing to it. Phase 32 makes that useful for **real, already-started**
projects, not just brand new ones: most projects aren't blank slates by
the time someone thinks to run `factory intake suggest-brief` on them -
they already have a `brief.json`, maybe with a real `project_name` and
`description` a human already wrote, but missing `design_intent` or
`manufacturing_notes`. A full draft *write* would blow all of that away;
Phase 32's *merge* fills in only what's actually missing. The gap between
"here's what I think you meant" and "here's what's now saved to disk" is
deliberate and permanent either way: a draft (or a merge preview) is
always a suggestion, never a decision.

## Human approval model

- **Nothing is written unless `--write` is explicitly given.**
  `factory intake suggest-brief <path>` alone is entirely read-only - it
  prints a draft (or, with `--update`, a merge preview) and exits.
- **`--write` writes exactly one file**: `<project_dir>/brief.json`. It
  never touches `design_intent.json` (there is no such file - Phase 24's
  `design_intent` lives *inside* `brief.json`, and this module follows
  that same convention), never touches `reference_board.json`, and never
  touches any other project file. This is true for both `--write` (full
  draft) and `--write --update` (safe merge).
- **An existing `brief.json` is never silently overwritten.** Plain
  `--write` checks first; if the file already exists, it prints `Brief
  already exists. Use --force to replace.` and exits without touching
  anything. Only an explicit `--force` (a second, deliberate flag) permits
  a full replacement - or `--update` (a *different*, deliberate flag) to
  safely merge instead. `--force` and `--update` together are rejected as
  incompatible (see "Merge mode (Phase 32)" below) - the CLI never has to
  guess which one you meant.
- **`--write` requires the project directory to already exist.** This
  module never creates a project directory - only, with explicit
  permission, a file inside one that's already there.
- **Every draft/merge preview says "Human approval required before save"**
  as its last advisory, unconditionally - not because a check failed, but
  because that's this module's standing position: a generated draft or
  merge, however complete, is not itself an approval.
- **A written `brief.json` still isn't `human_approved` or `print_ready`.**
  `required_human_approval` is always written as `true`; nothing in this
  module ever sets `human_approved` or `print_ready` on anything.

## Confidence gating, not invention

**A field is only populated in the draft when its `intake_summary`
confidence is `"high"` or `"medium"`.** `"low"`/`"unknown"` fields degrade
to `None` (scalars) or `[]` (lists) in the draft's JSON shape, rendered as
"unknown"/"not specified" text by whatever reads it (CLI, HTML). This
module never guesses, never fills a gap with a plausible-sounding default,
and never invents a value a human didn't (indirectly, via their own
written idea text) provide.

The one field this matters most for: `commercial_intent`. Its
`intake_summary` value is a boolean that defaults to `False` whenever no
explicit commercial keyword was found - but a low-confidence `False`
doesn't mean "confirmed no commercial intent," it means "no signal either
way." The draft never silently promotes that `False` into
`draft["brief"]["commercial_intent"]` - it stays `None` ("unknown")
exactly like every other low-confidence field, and only becomes `True`
when `intake_summary` found an explicit, high-confidence commercial
keyword.

## Draft artifacts

`generate_draft(intake_summary)` returns:

```jsonc
{
  "readiness": { "status": "Ready", "percent_populated": 85, "populated_count": 11,
                 "unknown_count": 2, "total_fields": 13, "human_review_required": true },
  "brief": {
    "project_name": "...", "category": "sign", "purpose": "...", "audience": "Students",
    "environment": "classroom", "printer": ["Bambu"], "material": ["PLA"],
    "quality_target": "etsy-worthy", "manufacturing_style": ["multi-part", "AMS", "multi-color"],
    "dimensional_constraints": ["48-inch"], "visual_goals": ["anime", "raised", "lettering"],
    "functional_goals": [], "commercial_intent": null, "review_notes": ["...", "..."]
  },
  "design_intent": {
    "purpose": "...", "quality_target": "etsy-worthy", "style": ["anime", "raised", "lettering"],
    "manufacturing_notes": ["multi-part", "AMS", "multi-color"], "reference_inputs": [],
    "warnings": ["..."], "design_notes": [], "review_required": true,
    "confidence_summary": {"category": "medium", "environment": "medium", "...": "..."}
  },
  "manufacturing_notes": {
    "printer": ["Bambu"], "material": ["PLA"],
    "manufacturing_style": ["multi-part", "AMS", "multi-color"], "dimensional_constraints": ["48-inch"]
  },
  "advisories": ["Reference board recommended - see `factory reference-board add`.",
                 "Human approval required before save."]
}
```

### `readiness`

`percent_populated`/`unknown_count`/`populated_count` are computed over
exactly **13 tracked fields** (`project_name`, `category`, `purpose`,
`audience`, `environment`, `printer_assumptions`, `material_assumptions`,
`quality_target`, `manufacturing_style`, `dimensional_constraints`,
`visual_goals`, `functional_goals`, `commercial_intent`) - a field counts
as "populated" exactly when its own `intake_summary` confidence is
`"high"`/`"medium"`, the same gate the draft itself uses, so the
percentage and the draft it describes never disagree. `status` is always
the literal string `"Ready"` - "ready to review," never "ready to
auto-save" (the same non-approval meaning `slicer_review_ready` carries
elsewhere in this repo).

### `brief`

The 13 tracked fields above, confidence-gated, plus `review_notes` (a
copy of the top-level `advisories` list, repeated here for a human
reading only the brief section). This is **not** literally
`schemas/project_brief.schema.json`'s shape - it's a richer,
review-oriented view. `build_brief_json()` (below) is what converts it
into an actual schema-valid `brief.json`.

### `design_intent`

A subset of `docs/design-intent-brief.md`'s proposed shape - only what can
be honestly derived: `quality_standard` (from `quality_target`),
`use_case` (from `purpose`), `style_direction` (from `visual_goals`).
**`reference_inputs` is always `[]`** - this phase never invents or
auto-populates reference inputs; a human adds them via `factory
reference-board add` (Phase 28/29). **`manufacturability_constraints.max_size_mm`
is never synthesized** from `dimensional_constraints` - a raw match like
`"48-inch"` names one axis of an object, not a confirmed `[x, y, z]`
triple; guessing the other two would be inventing data this module has no
basis for.

### `manufacturing_notes`

A focused subset (printer/material/manufacturing-style/dimensional-
constraints only) - a separate "view" of the same underlying data, for a
future manufacturing-planning consumer that only cares about this slice.

### `advisories`

```
Material not specified.
Printer not specified.
Dimensions incomplete.
Reference board recommended - see `factory reference-board add`.
Commercial review recommended - see docs/licensing-policy.md.
Mechanical review recommended - functional/moving parts detected.
Human approval required before save.
```

Conditions, in order: no `material`; no `printer`; no
`dimensional_constraints`; `quality_target` is
`premium`/`etsy-worthy`/`gift`/`presentation`; `commercial_intent` is
`True`; `functional_goals` non-empty. `"Human approval required before
save."` is always the last entry, unconditionally.

## `build_brief_json()`: from draft to schema-valid `brief.json`

`build_brief_json(draft)` produces the actual dict `write_draft_brief()`
writes - validated against `schemas/project_brief.schema.json` in this
phase's own test suite, for both a fully-populated draft and a completely
empty one. Every schema-required field with no confident signal is
written as the literal string `"unknown"` (`constraints` as `[]`) rather
than a guessed system default - **not even `factory.project_store.default_brief()`'s
own conventional defaults** (`owner: "Owen"`, `intended_printer: "Bambu
H2D"`). Those defaults are appropriate when a human runs `factory
init-project` with genuinely no other information; here, this module *did*
attempt extraction and came up empty, so writing a specific person's name
or printer model would misrepresent an actual absence of signal as a
confirmed fact.

- `status`: always `"brief_created"` (matches
  `factory.project_store.default_brief()`'s own convention: the moment a
  `brief.json` exists, that's what its status means).
- `required_human_approval`: always `true`.
- `intended_printer`: the first entry of `brief["printer"]` if any,
  else `"unknown"`.
- `description`: `brief["purpose"]` if known, else `"unknown"`.
- `constraints`: `brief["dimensional_constraints"]` (may be `[]`).
- `design_intent`: included only if at least one of
  `quality_standard`/`use_case`/`style_direction` has real signal -
  omitted entirely for an all-unknown draft (matches `design_intent`'s own
  "every field optional, whole block optional" philosophy).
- `manufacturing_notes`: included only if non-empty - a purely additive
  extra key `schemas/project_brief.schema.json`'s `additionalProperties:
  true` already allows.

## The `factory intake suggest-brief` CLI

```bash
factory intake suggest-brief <project_dir_or_text_or_markdown_or_intake_json> [--json] [--write] [--force] [--update]
```

Accepts the same three input kinds `factory intake analyze` does (a
project directory, a plain-text file, a Markdown file), plus a fourth: a
`.json` file containing a previously-saved `intake_summary` (e.g. from
`factory intake analyze --json > my_intake.json`) - read directly and used
as-is, never re-analyzed.

- **No flags** - prints the human-readable draft (status/populated/unknown
  header, Brief section, Design Intent section, Advisories) and exits.
  Nothing is written.
- **`--json`** - prints `generate_draft()`'s dict directly. Nothing is
  written. **Unchanged from Phase 31** whenever `--update` isn't also
  given - this exact shape is a stable, backward-compatible contract.
- **`--write`** - writes `<path>/brief.json` (`path` must be a project
  *directory* for this to succeed - a text/Markdown file path fails
  cleanly, since there's no directory to write into). Refuses if
  `brief.json` already exists; add `--force` to intentionally replace it
  (full replacement), or `--update` to safely merge instead (see below).
  Every `--write` (with or without `--force`/`--update`) prints a closing
  reminder that a human should still review the result.
- **`--update`** (Phase 32) - see "Merge mode (Phase 32)" below.

## Merge mode (Phase 32)

```bash
factory intake suggest-brief <project_dir> --update            # merge preview only, nothing written
factory intake suggest-brief <project_dir> --update --write     # apply the safe merge
factory intake suggest-brief <project_dir> --update --json      # merge preview as JSON
```

### What counts as "already present" (protected)

A field in the existing `brief.json` is **protected** - never overwritten,
regardless of what the draft has - unless it's genuinely empty or looks
like a placeholder:

- Blank (`""`, `None`, or an empty list `[]`).
- The literal word `"unknown"` (this module's own "no confident value"
  marker, from a prior plain `--write`).
- A `"TODO: ..."`-prefixed string, or a single-item list whose one entry is
  such a string (`factory.project_store.default_brief()`'s own starter
  text, e.g. `"TODO: describe the part(s) this project will produce."`).

Anything else - a real project name, a real sentence of description, a
real printer model, a real constraint - is protected. This also means: if
`factory init-project`'s own default `intended_printer: "Bambu H2D"` is
still sitting there untouched, merge treats it as real content (there's no
way to distinguish "a human deliberately kept the default" from "a human
never looked at this field" from the text alone) - it will never be
silently replaced by a differently-detected printer from the draft. This
is a deliberate, documented trade-off in favor of safety.

**The reverse also matters**: a *draft* value that itself looks like a
placeholder is never proposed as an addition, even when the existing field
is empty. This handles a real edge case found during this phase's own
testing - `factory intake suggest-brief <project_dir>` (no separate idea
file) re-reads that same project's own `brief.json` for its intake text,
so a still-unedited `"TODO: describe the part(s) this project will
produce."` description gets extracted by Phase 30 as a plausible
`"purpose"` sentence. Without this check, merge would propose replacing
one placeholder with an equally useless one; with it, that field is
correctly left alone (not "to add," not "preserved" - just still empty,
same as before).

### Which fields merge can touch

Only the fields `build_brief_json()` (Phase 31) already knows how to write
- `project_name`, `purpose`→`description`, `printer`→`intended_printer`,
`dimensional_constraints`→`constraints`, `quality_target`→
`design_intent.quality_standard`, `visual_goals`→`design_intent.style_direction`,
`material`→`manufacturing_notes.material`,
`manufacturing_style`→`manufacturing_notes.manufacturing_style`.
`category`, `audience`, `environment`, `functional_goals`, and
`commercial_intent` have no home in a real `brief.json` (Phase 31 never
writes them as top-level keys either), so they never appear in a merge
preview or a merged file - they stay visible only via `intake_summary`/the
full draft (`factory intake suggest-brief` without `--update`).

`status`, `owner`, and `required_human_approval` are never merge
candidates at all - `status` in particular is never changed by a merge,
under any circumstances; this module has no concept of a project's
lifecycle and makes no attempt to advance it.

### `merge_draft_brief(existing_brief, draft_brief)`

Returns:

```jsonc
{
  "fields_to_add": {"material": ["PLA"], "printer": ["Bambu"], "quality_target": "etsy-worthy"},
  "fields_preserved": ["project_name", "purpose"],
  "advisories": ["Dimensions incomplete.", "Human approval required before save."]
}
```

`apply_merge(existing_brief, merge_result)` turns that into the actual
`brief.json` dict to write - a deep copy of `existing_brief` with only
`fields_to_add` layered on top (mapped to their real schema homes); every
other key, including ones this module doesn't even know about, passes
through completely untouched.

### `--force` and `--update` are mutually exclusive

They mean genuinely different things - a full replacement vs. a safe
merge - and `factory intake suggest-brief` **rejects `--force --update`
together** with a clear error rather than picking one silently. If you
want a clean slate, use `--force`. If you want to fill gaps without
touching what's already there, use `--update`.

### If there's nothing to merge into

If `<project_dir>/brief.json` doesn't exist yet, `--update` has nothing to
compare against - it falls back to plain `--write` behavior (Phase 31),
exactly per this phase's own requirement: "if no brief.json exists,
behave like normal draft write; create `brief.json` only if `--write` is
present." A `.json`/text/Markdown *file* path (not a directory) behaves
the same way, since there's no brief.json location associated with it
either.

### A broken existing `brief.json`

If `<project_dir>/brief.json` exists but isn't valid JSON, `--update`
refuses with a clear error (`MalformedExistingBriefError`) rather than
guessing what to preserve - merging into something unreadable risks
silently discarding whatever's actually there. `--force` is unaffected by
this (a full replacement never needs to read the existing file first), so
it remains the escape hatch for a genuinely broken `brief.json`.

### Example: merge preview

```
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

### `--json` with `--update`

Adds four keys beyond plain `--json`'s `generate_draft()` shape:

```jsonc
{
  "draft": { "readiness": {...}, "brief": {...}, "design_intent": {...}, "manufacturing_notes": {...}, "advisories": [...] },
  "merge_preview": { "fields_to_add": {...}, "fields_preserved": [...], "advisories": [...] },
  "fields_to_add": {...},        // same as merge_preview.fields_to_add, duplicated at the top level for convenience
  "fields_preserved": [...],     // same as merge_preview.fields_preserved
  "advisories": [...],           // same as merge_preview.advisories
  "would_write": false,          // true only when --write was also given
  "wrote_file": null             // the written path (string) once --write --update succeeds, else null
}
```

This shape only appears when `--update` finds an existing `brief.json` to
merge into. Plain `--json` (no `--update`, or `--update` with nothing to
merge into) keeps Phase 31's exact original shape - see "backward
compatible" above.

## Connected to project inspection and the preview board

`factory.project_inspection.summarize_project()` gained a fifth additive
field alongside Phase 26-30's `design_intent_summary`/`design_intent_detail`/
`reference_board_summary`/`intake_summary`: `draft_brief_summary` - a
compact `{readiness, advisories}` view, derived from the project's own
`intake_summary` (never re-parses `brief.json`'s free text a second time).
Always a dict, never `None`. Purely additive: none of the earlier four
fields are read or modified, and `draft_brief_summary` is never read by
`classify_visual_readiness()`, `build_health_signals()`, or
`build_suggested_actions()`.

The preview board's **HTML** gained a compact "Draft Brief" card section,
placed right after "Project Intake" (a draft brief is the next pipeline
step) and before "Design Intent" - readiness status, percent populated,
unknown-field count, and a standing "Human review required" reminder.
Deliberately compact: the full brief/design_intent/manufacturing_notes
draft stays in `factory intake suggest-brief`'s output, not duplicated in
the card. Static HTML/CSS only - no JavaScript, no external assets, and
(same guarantee as the module itself) this card never writes anything -
the only write path (`factory intake suggest-brief --write`) is a
separate, explicit, human-run CLI command the board itself never invokes.

`factory.project_inspection.summarize_project()` gained a sixth additive
field, `brief_update_summary` - a compact `{merge_available,
fields_to_add_count, fields_preserved_count, human_review_required}` view
of `merge_draft_brief()`, comparing the project's own existing
`brief.json` (read fresh and safely - missing/unreadable degrades to
"everything would be an addition," never an error) against its
`intake_summary`. Always a dict, never `None`. Purely additive: none of
the earlier five fields (`design_intent_summary`, `design_intent_detail`,
`reference_board_summary`, `intake_summary`, `draft_brief_summary`) are
read or modified, and `brief_update_summary` is never read by
`classify_visual_readiness()`, `build_health_signals()`, or
`build_suggested_actions()`.

The preview board's **HTML** gained a compact "Brief Update" card section,
right after "Draft Brief" and before "Design Intent." Deliberately
terser than every other card: when there's nothing meaningful to merge
(the common case for a fully human-authored brief - most real projects
already have real content in every field merge cares about), it renders
one line, `"Up to date - nothing to merge."`, instead of a whole block, so
the board doesn't get noisy with a mostly-empty section on every single
project. Only when a safe merge genuinely *is* available does the fuller
block appear (`Merge available` badge, fields-to-add count, preserved
count, the standing "Human review required" reminder). Static HTML/CSS
only - no JavaScript, no external assets - and this card never merges or
writes anything; the only write path (`factory intake suggest-brief
--write --update`) is a separate, explicit, human-run CLI command the
board itself never invokes.

## Limitations

- **Inherits every Phase 30 limitation** - English-only keyword matching,
  no negation understanding, a naive `project_name`/`purpose` fallback for
  unstructured input. A weak intake analysis produces a weak (low
  percent-populated) draft; this module doesn't compensate for that, it
  just reports it honestly via `readiness`.
- **`dimensional_constraints` are raw text, not structured geometry.**
  `"48-inch"` in `constraints` is a note for a human to interpret, not a
  parsed, axis-assigned measurement - this module never tries to guess
  which axis, or convert units.
- **`owner` is never derivable.** Phase 30 has no keyword table for who a
  project's owner is - every written `brief.json`'s `owner` field is
  `"unknown"` when written fresh, and merge never touches an existing
  `owner` either way (it's not a merge candidate at all).
- **Merge can only tell "empty/placeholder" from "not," not "good" from
  "bad."** A human-authored field with a typo, a stale value, or
  deliberately-terse content is still "present" and therefore protected -
  merge has no way to judge quality, only presence. If a field genuinely
  needs replacing, that's still a manual edit or an explicit `--force`
  full-replace, never something merge will do for you.
- **`--update`'s intake source and merge target are the same `path`
  argument.** There's no separate "analyze this idea file, merge into that
  project" mode - `factory intake suggest-brief <project_dir> --update`
  re-reads that same project's own `brief.json` for intake text. For a
  project with real content already, this is exactly the point (fill
  gaps from what's already there); for a nearly-empty project, it mostly
  echoes back what little is already there (see the placeholder-filtering
  behavior above, which specifically exists to keep that echo from
  becoming a spurious "field to add").
- **No merge/edit for a single field.** `--update` always evaluates every
  merge-candidate field together; there's no `--only material` or similar
  to scope a merge to one field at a time.

## Non-goals

- **No AI, no LLM, no machine learning of any kind** - `generate_draft()`
  and everything it calls are pure functions over an already-structured
  dict; there is no model anywhere in this module.
- **No network calls, no web search, no scraping.**
- **No CAD generation, no OpenSCAD generation** - this phase produces
  metadata only, never geometry.
- **No Meshy, no Blender integration.**
- **No automatic project creation** - `write_draft_brief()` requires an
  already-existing project directory; it never runs the equivalent of
  `factory init-project` for you.
- **No automatic brief overwrite** - covered above; `--force` is the one,
  explicit, opt-in exception, and even that never runs without a human
  typing the flag.
- **No automatic `design_intent` editing on an already-`human_approved`
  or otherwise-advanced project** - `write_draft_brief()` treats "does
  `brief.json` exist" as the only gate; it has no concept of a project's
  current lifecycle status and makes no attempt to protect an in-progress
  project beyond the existing-file check. Don't run `--write --force` on
  a project you don't intend to fully replace the brief for.
- **No automatic reference generation** - `design_intent.reference_inputs`
  is always `[]`; a human still runs `factory reference-board add` by
  hand.
- **No automatic overwrite of human-authored values, ever, in merge mode**
  - this is Phase 32's entire reason to exist; see "What counts as
  'already present' (protected)" above for the exact rule.
- **Does not set `human_approved` or `print_ready`** on anything, ever.

See also `docs/project-intake.md` (Phase 30, this module's sole input
source), `docs/design-intent-brief.md`, `docs/reference-board.md`,
`docs/preview-board.md`, `docs/design-quality-standard.md`,
`docs/licensing-policy.md`, and `docs/roadmap.md` Phase 31 / Phase 32.

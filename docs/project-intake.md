# Project Intake Engine (Phase 30)

The **Project Intake Engine** (`factory.project_intake`) is the first
step in this repo's pipeline:

```
User Idea -> Project Intake -> Project Brief -> Design Intent ->
Reference Board -> Manufacturing Planning -> CAD Generation ->
Preview Board -> Review Gate -> Slicer Review -> (never automatic printing)
```

It converts a free-form natural-language product idea - plain text,
Markdown, or an existing project's `brief.json` description - into
structured **intake metadata**: category, audience, environment, material/
printer assumptions, quality target, manufacturing style, functional/
visual goals, dimensional constraints, and commercial intent, each with a
`confidence` level, plus advisory `warnings`.

## Fully deterministic - no AI, no LLM, no network

**This is not an AI feature.** There is no model, no embedding, no
similarity search, no API call. Every field is extracted with a small,
closed keyword table or a regular expression, checked in a fixed,
documented order - the exact same input text always produces the exact
same output, every time, on any machine, with no network connection. This
module never generates CAD, never runs OpenSCAD/CadQuery, never launches
Blender, never calls Meshy, never performs a web search, never scrapes a
website, never downloads anything, and never performs OCR or computer
vision - it only reads text a human already wrote and looks for known
words and patterns in it. See "Non-goals" below.

## Supported inputs

```bash
factory intake analyze examples/storage-bin-lid                       # a project directory
factory intake analyze examples/intake-benchmarks/teacher-nameplate.md # a Markdown file
factory intake analyze my_brief.txt                                    # a plain-text file
```

- **A project directory** - reads `<dir>/brief.json`'s `project_name` +
  `description` + `constraints` (only those three free-text fields; see
  "Non-goals" below for what it deliberately does *not* also read from the
  same file). Missing/unreadable/malformed `brief.json` degrades to a
  clean "no signal" result, not an error.
- **A Markdown file** (`.md`/`.markdown`) - the first `# Heading` becomes
  the inferred project name; the rest is scanned the same way as any other
  text (Markdown syntax like `#`/`*`/`-` is never stripped before keyword
  matching, only before purpose/project-name sentence extraction).
- **A plain-text file** (any other extension) - read and analyzed
  directly.
- A missing file, an unreadable/non-UTF-8 file, or an empty file all
  degrade to a clean "no signal" result (a single advisory warning, not an
  error).

## Supported fields

Every field is `{"value": ..., "confidence": "high"|"medium"|"low"|"unknown"}`.

| Field | Shape | Closed vocabulary |
|---|---|---|
| `project_name` | string or `null` | free text (Markdown heading, brief's own `project_name`, or a short first line) |
| `category` | one string | `sign`, `organizer`, `toy`, `décor`, `fixture`, `mechanical`, `educational`, `storage`, `replacement part`, `accessory`, `unknown` |
| `purpose` | string or `null` | free text - the first sentence of the (non-heading) body |
| `audience` | string or `null` | free text label (`Students`, `Teachers`, `Gift recipient`, `Customers`, `Self`) |
| `environment` | one string | `classroom`, `office`, `home`, `garage`, `outdoor`, `unknown` |
| `material_assumptions` | list of strings | `PLA`, `PETG`, `ABS`, `TPU` |
| `printer_assumptions` | list of strings | `Bambu`, `Prusa`, `Voron`, `generic FDM` |
| `quality_target` | one string | `prototype`, `functional`, `premium`, `etsy-worthy`, `presentation`, `gift`, `unknown` |
| `manufacturing_style` | list of strings | `single-part`, `multi-part`, `AMS`, `single-color`, `multi-color`, `support-free preferred` |
| `functional_goals` | list of strings | free-text keyword matches (hold, mount, hinge, snap-fit, flex, ...) |
| `visual_goals` | list of strings | free-text keyword matches (anime, minimalist, engraved, lettering, ...) |
| `dimensional_constraints` | list of strings | raw matched number+unit substrings (e.g. `"48-inch"`, `"120mm"`) |
| `commercial_intent` | boolean | `true`/`false` |

Plus a top-level `warnings` (list of strings, advisory only) and `source`
(`"brief_description"`, `"text_file"`, `"markdown_file"`, or `"none"`).

## Heuristics

All keyword matching is **word-boundary matching, not substring
matching** - "de**sign**" does not match the `sign` category keyword, and
"b**rack**et" does not match the `organizer` keyword `rack`; every match
is a whole word or whole phrase. Matching is case-insensitive
(text is lowercased before comparison, except where the original casing is
preserved for display, e.g. a dimensional-constraint match or a Markdown
heading).

- **`category`/`environment`** - a fixed, ordered keyword table is
  scanned; the *first* category/environment whose keywords appear wins.
  `category`'s priority order matches this document's own listed order
  above (`sign` before `educational`, so "a teacher's nameplate" resolves
  to `sign`, not `educational` - environment/audience separately still
  pick up "classroom"/"teacher").
- **`quality_target`** - all matching quality keywords are collected, then
  resolved by a fixed priority (`etsy-worthy` > `gift` > `premium` >
  `presentation` > `functional` > `prototype`) - "etsy-worthy" is this
  repo's own quality standard (`docs/design-quality-standard.md`) and
  always wins when present alongside a weaker signal like "premium".
- **`material_assumptions`/`printer_assumptions`/`manufacturing_style`** -
  every matching keyword is collected (not just the first) - a design can
  legitimately use two materials or target two printer brands.
- **`functional_goals`/`visual_goals`** - a looser, open-ended keyword scan
  (not a strict enum) - any of a curated list of theme words found in the
  text is included.
- **`dimensional_constraints`** - a regex for a number immediately
  followed by a unit token (`mm`, `cm`, `inch(es)`, `in`, `ft`, `feet`,
  `foot`), e.g. `"48-inch"`, `"120mm"`, `"30 cm"`. Bare prepositions like
  "hang **in** a classroom" never match - a unit token must be immediately
  preceded by a digit.
- **`commercial_intent`** - a fixed keyword list ("sell", "selling", "for
  sale", "customers", "my shop", "commission", ...). Deliberately disjoint
  from the `etsy-worthy` quality keyword, so "this should be etsy-worthy
  quality" is never mistaken for "I'm selling this."
- **`purpose`** - the first sentence of the text, with any Markdown
  heading lines stripped first (so purpose reads actual prose, not a
  title).
- **`project_name`** - a Markdown `# Heading`, else the brief's own
  literal `project_name` (for a project directory - always wins,
  `"high"` confidence, since it's a structured field, not inferred),
  else a short (≤ 80 char) first line, else `null`.

## Confidence levels

Always exactly one of `"high"`, `"medium"`, `"low"`, `"unknown"` - never a
probability or a model score (there is no model). The rule differs by
field *shape*, not by field identity:

- **Single-value classification fields** (`category`, `environment`,
  `quality_target`, `audience`) - `"high"` when exactly one distinct
  candidate matched (unambiguous), `"medium"` when more than one distinct
  candidate matched (the field still has *a* value, chosen by priority,
  but the input was ambiguous), `"unknown"` when nothing matched.
- **Closed-vocabulary list fields** (`material_assumptions`,
  `printer_assumptions`, `manufacturing_style`) - `"high"` whenever
  *anything* matched (each match is a specific, low-ambiguity term - "PLA"
  is not something you say by accident), `"unknown"` when nothing matched.
  Finding two materials isn't more or less confident than finding one -
  it's just more information.
- **Open-ended theme-scan fields** (`functional_goals`, `visual_goals`) -
  `"unknown"` for zero matches, `"medium"` for exactly one (could be a
  coincidental single word), `"high"` for two or more (reinforcing
  evidence of a real theme).
- **`dimensional_constraints`** - `"high"` whenever at least one
  number+unit match is found (a precise regex match is inherently
  low-false-positive), `"unknown"` otherwise.
- **`commercial_intent`** - `"high"` when an explicit commercial keyword is
  found, `"unknown"` (defaulting to `false`) otherwise - absence of a
  keyword isn't strong proof of absence of intent, just absence of signal.
- **`project_name`/`purpose`** - `"high"` for a Markdown heading or a
  brief's own literal `project_name`, `"medium"` for a heuristic guess
  (first sentence / short first line), `"unknown"` when there's nothing to
  work with.

`"low"` is a reserved value in `CONFIDENCE_LEVELS` for future heuristics
that need a middle ground between `"medium"` and `"unknown"` - no current
field emits it, by design (every existing rule above only needed three of
the four levels to be honest about its own certainty).

## Advisory conditions

Never hard failures - always warnings, exactly like
`factory.design_intent_check`/`factory.reference_board`:

- **Dimensions not specified.**
- **Printer not specified.**
- **Material not specified.**
- **Reference images recommended** - whenever `quality_target` is
  `premium`/`etsy-worthy`/`gift`/`presentation` and the text doesn't
  mention "photo"/"picture"/"image"/"reference" - a nudge toward
  `factory reference-board add` (Phase 28/29).
- **Mechanical testing recommended** - whenever any `functional_goals`
  keyword matched.
- **Commercial intent detected** - whenever `commercial_intent` is `true`
  - points at `docs/licensing-policy.md`.
- **Gift-quality target detected** - whenever `quality_target` is `gift` -
  points at `docs/design-quality-standard.md`.
- **Human review recommended** - whenever at least three of
  (`category`, `environment`, `quality_target`, `material_assumptions`,
  `printer_assumptions`) came back `"unknown"`/`"low"` confidence - the
  input gave the heuristics almost nothing to work with.

An empty/blank input short-circuits to exactly one warning ("No project
description text found to analyze") rather than piling on every
field-specific warning above, which would just be noise for a truly empty
input.

## Connected to project inspection and the preview board

`factory.project_inspection.summarize_project()` gained a fourth additive
field alongside Phase 26-28's `design_intent_summary`/`design_intent_detail`/
`reference_board_summary`: `intake_summary` - computed unconditionally
(independent of `brief_status`, same reasoning as `reference_board_summary`).
Always a dict, never `None`. Purely additive: none of the earlier three
fields are read or modified, and `intake_summary` is never read by
`classify_visual_readiness()`, `build_health_signals()`, or
`build_suggested_actions()`.

The preview board's **HTML** gained a compact "Project Intake" card
section, placed *first* in each project's card (upstream of "Design
Intent" in this repo's pipeline) - category, audience, environment,
quality target, material assumptions, and advisory warnings. Deliberately
compact: per-field confidence levels and the less commonly needed fields
(printer assumptions, manufacturing style, functional/visual goals,
dimensional constraints, commercial intent) are available via `factory
intake analyze --json` and are not duplicated in the card. Static
HTML/CSS only - no JavaScript, no external assets.

## The `factory intake analyze` CLI

```bash
factory intake analyze <project_dir_or_text_or_markdown_file> [--json]
```

A thin wrapper around `factory.project_intake.analyze()` - it dispatches
on whether the given path is a directory (reads `brief.json`) or a file
(reads it directly), prints every field with its confidence, then any
advisory warnings. `--json` prints the `intake_summary` dict directly.
Never writes any file. See "Sample output" in `docs/roadmap.md`'s Phase 30
entry.

## Benchmark example

`examples/intake-benchmarks/teacher-nameplate.md` is a committed benchmark
- a shortened version of the "Mr. Reagan" classroom-nameplate concept
(see `examples/mr_reagan_nameplate/`), written to exercise most of this
engine's heuristics in one file: a modular teacher desk nameplate,
premium/Etsy-worthy/gift-quality expectations, anime-inspired lettering,
AMS compatibility on a Bambu printer, a 48-inch desk, and PLA material.
**This benchmark exists only to validate intake parsing** - it does not
generate CAD, a brief, or any other project artifact, and running `factory
intake analyze` on it never writes anything.

## Limitations

- **No negation understanding.** "not a functional/mechanical part" still
  contains no `functional_goals` keywords in practice (that keyword set is
  disjoint from "mechanical"/"functional" as used elsewhere), but a
  sentence like "this is not a toy" would still match the `toy` category
  keyword - there is no grammar/semantics layer, only keyword presence.
- **English only.** Keyword tables have no multi-language support - a
  French/Spanish/German description of the same idea will detect
  significantly less (or nothing).
- **No context/coreference resolution.** "the teacher's nameplate, which
  students will read" splits credit between `audience` candidates the same
  way any two matching keywords do for any single-value field - it can't
  tell you *whose* nameplate it "really" is.
- **A naive `project_name`/`purpose` fallback.** With no Markdown heading
  and no structured `brief.json`, project name/purpose extraction is just
  "first short line" / "first sentence" - a poorly-punctuated or
  single-sentence input can produce a `project_name` that's just the whole
  sentence restated.
- **Doesn't read every structured `brief.json` field.** Only
  `project_name`/`description`/`constraints` (free text) are read - fields
  like `intended_printer` or `selected_manufacturing_option` are already
  structured elsewhere and intentionally not duplicated here (see
  "Non-goals"). A "Printer not specified" advisory can still appear even
  when `intended_printer` is set elsewhere in the same `brief.json` - this
  is expected, not a bug: this engine's job is mining *free text*, not
  re-scanning fields other systems already own.

## Non-goals

- **No AI, no LLM, no machine learning of any kind** - closed keyword
  tables and regexes only, fully deterministic.
- **No network calls, no web search, no scraping** - not MakerWorld, not
  Thingiverse, not Reddit, not Pinterest, not DeviantArt, not Google
  Images, not any other site.
- **No automatic reference discovery** - this engine never populates
  `reference_board.json` itself; a human still runs `factory
  reference-board add` (Phase 28/29) by hand.
- **No OCR, no computer vision** - only text a human already wrote is
  read, never an image.
- **No external API calls of any kind.**
- **No CAD generation, no OpenSCAD generation** - this phase produces
  metadata only, never geometry.
- **No Meshy, no Blender integration.**
- **No `brief.json` writing** - `factory intake analyze` is entirely
  read-only; nothing here creates or edits a project's `brief.json`,
  `design_intent`, or `reference_board.json`. A future phase could use
  `intake_summary` to *suggest* a starter `brief.json`/`design_intent`,
  but that write path does not exist yet.
- **Does not read already-structured `brief.json` fields** beyond
  `project_name`/`description`/`constraints` - see "Limitations" above.
- **Does not set `human_approved` or `print_ready`** on anything, ever.

See also `docs/design-intent-brief.md`, `docs/reference-board.md`,
`docs/preview-board.md`, `docs/design-quality-standard.md`,
`docs/licensing-policy.md`, and `docs/roadmap.md` Phase 30.

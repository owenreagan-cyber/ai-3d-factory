# Reference Board (Phase 28 — planning and local data support; Phase 29 — CLI management)

**This is a planning/data-model phase (28), extended by a local CLI
management phase (29)** - the same spirit as `docs/design-intent-brief.md`
(Phase 24/25/26/27). It defines a structured, local record of where a
project's design intent came from - a photo, an existing STL, a
MakerWorld/Thingiverse/Reddit/Pinterest/DeviantArt page, a sketch, a
classroom or product photo, a remixable source file - gives that record a
read-only, advisory summary surfaced in `factory.project_inspection`, the
preview board's JSON, and a compact card in the preview board's HTML
(Phase 28), and makes it usable without hand-editing JSON via `factory
reference-board init/show/validate/add/list` (Phase 29).

**It does not fetch, download, scrape, search, or otherwise contact
anything.** A `source_url` recorded on a reference is inert metadata - a
human wrote it down, the way they'd jot a URL on a sticky note - never a
target `factory.reference_board` (or anything downstream of it) opens. No
web crawling, no scraping, no external search, no downloading, and no API
integration exists anywhere in this phase, including the CLI added in
Phase 29. See "What Phase 28 does not do" and "What Phase 29 does not do"
below.

## What a Reference Board is

Each project may have an optional `reference_board.json` in its project
directory (alongside `brief.json`, `build_plan.json`, `part_manifest.json`).
It's a flat list of **references** - structured records describing an
inspiration source, an existing file, or a piece of prior art that informed
(or could inform) the project's `design_intent`
(`docs/design-intent-brief.md`). A project with no file, an empty
`references` list, or an unreadable file is treated identically: a clean,
empty result, not an error - most projects won't have one, especially
early on.

```jsonc
// <project_dir>/reference_board.json
{
  "references": [
    {
      "title": "Classroom storage inspiration",
      "source_url": "https://example.com/classroom-storage-reference",
      "source_type": "inspiration",
      "license": "unknown",
      "usage_intent": "design_reference_only",
      "attached_to": "design_intent.reference_inputs",
      "notes": "Used only as a style and organization reference."
    }
  ]
}
```

## Supported fields

Every field is optional and every value is validated against a closed
vocabulary (below) - an unrecognized or missing value never raises an
error, it degrades to a safe default (usually `"unknown"`) plus an advisory
warning. A reference entry that isn't even a JSON object is skipped with a
warning rather than crashing the whole board.

| Field | Type | Notes |
|---|---|---|
| `title` | string | Falls back to `"Reference #<n>"` (1-indexed) if missing/blank. |
| `source_url` | string | Inert metadata only - **never fetched**. Missing/blank triggers an advisory warning. |
| `source_type` | enum (below) | Falls back to `"unknown"` if missing or not one of the supported values. |
| `license` | enum (below) | Falls back to `"unknown"` if missing or not one of the supported values. |
| `usage_intent` | enum (below) | `None` if missing or not one of the supported values (no default value is implied). |
| `attached_to` | enum (below) | Falls back to `"unknown"` if missing or not one of the supported values. |
| `notes` | string | Free text. `None` if missing/blank. |

## Supported source types

```
inspiration | reference | remixable | user_uploaded | sketch | image | stl | step | vector | unknown
```

Covers everything Phase 28's brief listed as an example future reference:
a photo, an existing STL inspiration, a MakerWorld/Thingiverse/Reddit/
Pinterest/DeviantArt page (`inspiration` or `reference`), a vector file, a
sketch, a classroom/product photo, a user-uploaded image
(`user_uploaded`), or a remixable source file (`remixable`).

## Supported license values

```
unknown | personal_use | commercial_allowed | cc_by | cc_by_sa | cc_by_nc | public_domain | proprietary | custom
```

`unknown` and `proprietary` are treated as advisory-risk licenses (see
"Advisory conditions" below) - not hard failures, but flagged so a human
notices before treating the reference as safe to reuse or remix.

## Supported usage intent values

```
design_reference_only | remix_candidate | dimensional_reference | style_reference | functional_reference | manufacturing_reference
```

`remix_candidate` is the one usage intent this phase treats as
higher-stakes: combined with an `unknown` or `proprietary` license, it
triggers a specific "do not remix without confirming rights" warning
(see below) - the same standard `docs/design-intent-brief.md`'s
`reference_inputs[].local_only` flag and `docs/meshy-approval-gate.md`'s
"Explicit input review before upload" already apply elsewhere in this
repo.

## `attached_to` values

```
design_intent.reference_inputs | project | part | unknown
```

Names *where* a reference conceptually belongs. `design_intent.reference_inputs`
is the natural bridge to the `reference_inputs` list already documented in
`docs/design-intent-brief.md`'s proposed `design_intent` shape - a
reference board entry with this value is meant to be the same reference a
human would eventually copy into `brief.json`'s `design_intent.reference_inputs`
once they're ready to commit to a design direction, though this phase does
not write that automatically (see below).

## Advisory conditions (never hard failures)

`factory.reference_board.summarize_reference_board()` produces a list of
plain-text warnings - always advisory, never a blocking failure, exactly
like `factory.design_intent_check`'s manufacturability warnings:

- **Missing or unknown license** - "commercial use unclear."
- **Proprietary license** - "confirm rights before reuse."
- **Missing `source_url`.**
- **`remix_candidate` usage intent with an unknown/proprietary license** -
  "do not remix without confirming rights."
- **No references attached to `design_intent.reference_inputs`** - a
  board-level warning shown only when at least one reference exists but
  none of them declare that `attached_to` value.
- **Unsupported `source_type`/`license`/`usage_intent` value** - the field
  falls back to a safe default and the original (invalid) value is named
  in the warning.
- **Malformed reference entry** (not a JSON object) - skipped, named by
  position (`Reference #<n>`).

## Reading a project's Reference Board

```python
from factory.reference_board import read_reference_board, summarize_reference_board

read_reference_board(project_dir)       # raw {"references": [...]}, unvalidated
summarize_reference_board(project_dir)  # validated, advisory summary (see below)
```

`summarize_reference_board()`'s shape:

```jsonc
{
  "reference_count": 1,
  "by_license": {"unknown": 1},
  "by_source_type": {"inspiration": 1},
  "by_usage_intent": {"design_reference_only": 1},
  "attached_to_design_intent_count": 1,
  "warnings": ["Classroom storage inspiration: license is unknown - commercial use unclear."]
}
```

Always a dict, never `None` - a missing/absent `reference_board.json`
returns `reference_count: 0` with every breakdown empty and no warnings,
the "clean empty result" the same way `design_intent_summary`/
`design_intent_detail` return `None` for a brief with no `design_intent`.

`normalize_references(project_dir)` returns the same per-reference
normalization as a flat list (`title`, `source_url`, `source_type`,
`license`, `usage_intent`, `attached_to`, `notes` - every field always
present, unsupported values already degraded to a safe default) - for
anything that needs per-reference detail rather than
`summarize_reference_board()`'s aggregate counts (`factory reference-board
list` below is its only consumer so far).

## CLI management (Phase 29)

`reference_board.json` never has to be hand-edited. Five subcommands under
`factory reference-board` cover the full local workflow - still no
network, no search, no scraping, no downloading, no API calls:

```bash
factory reference-board init <project_dir> [--force]
factory reference-board show <project_dir> [--json]
factory reference-board validate <project_dir> [--json]
factory reference-board list <project_dir> [--json]
factory reference-board add --project <project_dir> --title <title> \
    [--url <url>] [--type <source_type>] [--license <license>] \
    [--usage <usage_intent>] [--attached-to <attached_to>] [--notes <notes>]
```

- **`init`** creates `<project_dir>/reference_board.json` with a documented
  starter shape (an explanatory `notes` list plus an empty `references`
  list) - **never overwrites an existing file** unless `--force` is given,
  so re-running it on a project that already has references is always
  safe. Raises a clear error (exit code 1) if `project_dir` itself doesn't
  exist - it never creates the project directory, only the file inside an
  existing one.
- **`show`** prints a compact human-readable summary - reference count,
  warning count, a license-status breakdown, and a usage-intent breakdown
  (`--json` prints `summarize_reference_board()`'s dict directly).
- **`validate`** runs the same advisory checks `summarize_reference_board()`
  already computes and prints them as a warning list, always under a
  `✓ Valid reference board` header - **advisory conditions are never
  failures**. The one real error is `reference_board.json` existing but not
  being parseable JSON (`✗ invalid reference_board.json`, exit code 1) -
  everything else (missing fields, unsupported values, zero references) is
  a warning, never a failure.
- **`list`** prints a compact, numbered, per-reference listing (title,
  source type, license, usage intent) via `normalize_references()`
  (`--json` prints that list directly).
- **`add`** appends one new reference via `--title`/`--url`/`--type`/
  `--license`/`--usage`/`--attached-to`/`--notes` flags, creating the file
  first (same starter shape as `init`) if it doesn't exist yet. **Always
  appends - never overwrites or removes an existing entry**, and an
  unrecognized `--type`/`--license`/`--usage`/`--attached-to` value is
  still saved exactly as given (never rejected) - the same "advisory over
  restrictive" principle as everywhere else in this phase - with the
  resulting advisory warning(s) about that new entry printed immediately
  for feedback.

All five subcommands are thin wrappers: none of them re-implement
`_normalize_reference()`'s validation/fallback logic - `show`/`validate`/
`list` all read through `summarize_reference_board()`/`normalize_references()`,
and `add` reuses the same private normalization function internally only to
compute the just-added entry's advisory warnings for CLI feedback, never to
decide what gets written to disk.

## Connected to project inspection and the preview board (Phase 28)

`factory.project_inspection.summarize_project()` gained a third additive
field alongside Phase 26/27's `design_intent_summary`/`design_intent_detail`:
`reference_board_summary` - computed unconditionally (independent of
`brief_status`, since a project can have a reference board before it even
has a `brief.json`). Purely additive: `design_intent_summary` and
`design_intent_detail` are completely unchanged by this phase, and
`reference_board_summary` is never read by `classify_visual_readiness()`,
`build_health_signals()`, or `build_suggested_actions()`.

The preview board's **JSON** (`preview_board/index.json`) carries
`reference_board_summary` on every project entry, for free, since it's
just a field on `summarize_project()`'s output. The preview board's
**HTML** gained a compact "Reference Board" card section, placed right
after "Design Intent" (references feed design intent) and before
"Manufacturing Overview":

```
REFERENCE BOARD

References:
3

License status:
2 unknown, 1 CC BY

Usage:
3 design reference only

Warnings:
Classroom storage inspiration: license is unknown - commercial use unclear.
```

Compact by design - it shows counts and advisory warnings, not a full
per-reference listing (no titles, no URLs rendered individually). A
project with zero references renders a single explanatory line instead of
empty rows. Static HTML/CSS only - no JavaScript, no external assets, no
CDN, no tracking, and (same guarantee as the module itself) no `source_url`
is ever rendered as a clickable link or fetched.

## Example data

`examples/storage-bin-lid/reference_board.json` is a committed, safe,
local example (no copyrighted assets, no downloaded files - a URL string
is present only as inert metadata, never fetched by anything that reads
this file). See that file for the worked example this document's field
tables above describe.

## What Phase 28 does not do

- **Does not implement Source Discovery.** No web crawling, no scraping of
  MakerWorld, Thingiverse, Reddit, Pinterest, DeviantArt, Google Images, or
  any other website. No internet search of any kind.
- **Does not download anything.** A `source_url` is a string field, read
  and echoed back in warnings/summaries, never opened, fetched, or
  resolved by any code in this phase.
- **Does not add any API integration** - no Meshy, no third-party search
  API, no scraping library dependency.
- **Does not change `design_intent_summary` or `design_intent_detail`'s
  shape** - both are exactly as Phase 26/27 left them.
- **Does not automatically copy a reference into
  `brief.json`'s `design_intent.reference_inputs`** - `attached_to:
  "design_intent.reference_inputs"` is a declared *intent*, read and
  counted for the "no references attached" advisory, never written back
  anywhere. Phase 28 itself writes nothing - it's exactly as read-only as
  `factory.design_intent_check` (Phase 29 later added exactly two local
  write operations on top of this same module - see "What Phase 29 does
  not do" below).
- **Does not enforce or automate copyright/licensing decisions** beyond
  local, advisory classification (unknown/proprietary license flagged,
  remix-with-unsafe-license flagged) - a human still has to actually check
  a source's real license and rights before reusing or remixing anything.
- **Does not change `factory review-gate`'s JSON output shape** - it still
  never includes `reference_board_summary` (or `design_intent_summary`/
  `design_intent_detail`).
- **Does not change `visual_readiness_state`, `health_signals`, or
  `suggested_actions`** - `reference_board_summary` is purely additive and
  display-only, exactly like `design_intent_summary`/`design_intent_detail`.
- **Does not start organic model generation, a Meshy/Blender integration,
  or slicer integration** - entirely out of scope for this phase.
- **Does not set `human_approved` or `print_ready`** on anything, ever.

## What Phase 29 does not do

- **Does not implement automatic search, web crawling, or any integration**
  with MakerWorld, Thingiverse, Reddit, Pinterest, DeviantArt, or Google
  Images - `factory reference-board add` only writes exactly what a human
  typed on the command line.
- **Does not download anything** - `--url` is stored as a plain string,
  never fetched, opened, or resolved by any `reference-board` subcommand.
- **Does not add license detection** - `--license` is whatever the human
  passes (or omits); this phase never inspects a file, a URL, or any
  external source to infer a license. "Advisory classification of a
  human-declared value" (Phase 28) is not "automated license detection."
- **Does not add Meshy, Blender, CAD generation, or AI ranking** of any
  kind - entirely out of scope.
- **Does not change `reference_board.json`'s shape or vocabulary** -
  `factory reference-board add` writes the exact same shape a human would
  hand-author (see "Supported fields" above); no new fields were
  introduced for the CLI's sake.
- **Does not change the Preview Board's layout** - `reference_board_summary`,
  the HTML Reference Board card, and everything else Phase 28 wired up are
  completely unchanged; Phase 29 is CLI-only.
- **Does not duplicate validation logic** - every `reference-board`
  subcommand reads through (or, for `add`, reuses internally)
  `_normalize_reference()`, the same single implementation
  `summarize_reference_board()`/`normalize_references()`/the preview board
  already use. See "CLI management (Phase 29)" above.
- **Does not overwrite data.** `init` never overwrites an existing
  `reference_board.json` without `--force`; `add` never overwrites or
  removes an existing entry, and refuses (with a clear error, not a
  silent clobber) to append onto a `reference_board.json` that already
  exists but isn't valid JSON.
- **Does not set `human_approved` or `print_ready`** on anything, ever.

## How this prepares for future Source Discovery

A future Source Discovery feature (not started, not scheduled - see
`docs/roadmap.md`'s "Roadmap numbering policy" for how a real
implementation phase would get its own number) would need exactly the
structured record this phase defines: a place to *record* what a human
found, where, under what license, and what they intend to do with it -
before any fetching, scraping, or automated search is anywhere near in
scope. By building the data model, the advisory validation, the
project-inspection/preview-board wiring (Phase 28), and now a full local
CLI to populate it by hand (Phase 29) first, a future Source Discovery
phase's actual job shrinks to one thing: populating `reference_board.json`
entries *automatically instead of by hand* (still under explicit human
review, the same "explicit input review before upload" standard
`docs/meshy-approval-gate.md` already requires) - not inventing a new
schema, a new advisory-warning taxonomy, new board plumbing, or a new CLI
surface under time pressure. Same reasoning as
`docs/design-intent-brief.md`'s relationship to Phase 25's
`check-design-intent` and Phase 26/27's visibility work.

See also `docs/design-intent-brief.md`, `docs/design-quality-standard.md`,
`docs/meshy-approval-gate.md` (the "Explicit input review before upload"
standard this phase's advisory warnings echo), `docs/preview-board.md`,
`docs/roadmap.md` Phase 28 / Phase 29, and `AGENT.md`.

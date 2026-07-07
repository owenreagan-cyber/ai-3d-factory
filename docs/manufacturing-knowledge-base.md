# Manufacturing knowledge base (Phase 3/4)

`config/manufacturing/` is a local, hand-maintained reference database that
`factory plan` and `factory report` read to give printer-aware, explained
manufacturing advice. It is configuration data only: nothing in this repo
uses it to discover, connect to, configure, or communicate with a printer.
See `AGENT.md` and `docs/safety-gates.md` for the boundaries this respects.

## Files

| File | Contents |
|---|---|
| `config/manufacturing/printers.json` | The printer fleet: one entry per physical printer, its build volume, supported nozzles/build plates/materials, and which accessories are currently installed on it. |
| `config/manufacturing/materials.json` | Planning-relevant material data (paintability, strength class, `good_for` tags) beyond the simpler `config/materials.json`. |
| `config/manufacturing/accessories.json` | The accessory catalog: AMS/AMS 2 Pro, build plates, nozzle sizes. Each accessory declares the capabilities it *adds* (e.g. AMS adds `multicolor`). |
| `config/manufacturing/planning_rules.json` | The manufacturing-option catalog (single-piece, multipart variants, replaceable components) with advantages/disadvantages and keyword hints, plus the list of decision factors the engine considers. |

`config/printers.json` and `config/materials.json` (no `manufacturing/`
subdirectory) still exist unchanged from Phase 0/1 and are still used by
`factory validate`'s build-volume-fit check against a single "primary
printer". The two systems aren't merged yet - see **Future extensibility**
below.

## Printer profiles

Each printer entry has a stable `printer_id`, a `display_name`/`unit_label`
(so two units of the same model, e.g. two P1S printers, stay distinguishable),
capability fields (`build_volume_mm`, `multicolor_supported`,
`ams_supported`, `default_nozzle_mm`, `supported_nozzle_sizes_mm`,
`supported_materials`, ...), and `installed_accessories` - a list of
accessory IDs currently attached, hand-maintained by a human as hardware
changes. Every printer also carries a `verified: false/true` flag with a
`verification_note`, the same pattern Phase 0/1 used in `config/printers.json`:
treat unverified numbers as advisory placeholders, not a hard go/no-go.

The fleet as configured today: a Bambu Lab H2D (with AMS 2 Pro), two Bambu
Lab P1S units (each with an original AMS), and an Elegoo Centauri Carbon (no
AMS currently installed). This list is expected to change - add, remove, or
edit entries directly in the JSON as hardware changes.

## Accessory model

Accessories (`config/manufacturing/accessories.json`) are pure configuration:
attaching a real accessory to a printer never happens through this repo. A
human physically installs the hardware, then updates that printer's
`installed_accessories` list to match. Each accessory declares
`adds_capabilities` (e.g. AMS adds `["multicolor", "automatic_material_switching",
"multi_material_single_plate"]`); `factory.manufacturing.knowledge.printer_capabilities()`
merges a printer's own fields with the capabilities its installed accessories
add, so planning logic never has to special-case "does this printer have an
AMS" - it just checks the merged capability set.

## Planning workflow

`factory plan <brief.json>`:

1. Resolves `brief.json`'s `intended_printer` (free text) against known
   printers by token match (e.g. "Bambu H2D" matches "Bambu Lab H2D").
   Ambiguous or unmatched text (e.g. "Bambu P1S" when there are two) resolves
   to `null`, never a guess, and is added to `unanswered_questions`.
2. Runs the manufacturing decision engine (below) against the brief
   description and the resolved printer's capabilities.
3. Recommends candidate materials from `config/manufacturing/materials.json`
   `good_for` tags, matched against the brief description - again a
   non-binding suggestion.
4. Writes all of this into `build_plan.json`'s new fields (`target_printer`,
   `manufacturing_goal`, `assembly`, `materials`, `colors`,
   `manufacturing_options`, `unanswered_questions`,
   `selected_manufacturing_option`), and seeds `part_manifest.json` with
   planning-time placeholders (see **Multipart workflow** below).

## Decision engine

`factory.manufacturing.decision_engine.evaluate_manufacturing_options()` is a
deterministic, local, keyword-based heuristic - no AI/LLM call - mirroring
the existing `factory/router.py` tool-routing pattern. It always explains
every option from `planning_rules.json` (single-piece, multipart for build
volume/color/detail/painting/strength, replaceable components) with its
advantages and disadvantages, marks `multipart_color` unavailable when the
target printer has no multicolor capability, and recommends exactly one
option as a non-binding suggestion.

**The engine never selects an option.** `manufacturing_options.selected_manufacturing_option`
and the top-level `build_plan.json` field of the same name are always `null`
from `factory plan` - only a human, explicitly running `factory choose-option`
(below), sets that field. `factory report` always shows the recommendation as
"non-binding" next to whatever is actually selected.

## Human decision workflow (Phase 4)

`factory plan` explains options; it never picks one. Two commands close that
loop:

- **`factory list-options <project_dir>`** reads `build_plan.json` and prints
  every manufacturing option - id, title, description, advantages,
  disadvantages, availability for the resolved target printer, and whether
  it's currently the recommendation and/or the current selection - plus
  every `unanswered_questions` entry. Purely read-only; it writes nothing.
- **`factory choose-option <project_dir> <option_id>`** records Owen's
  explicit choice: it validates `option_id` against the option ids
  `list-options` just showed, then sets `build_plan.json`'s
  `selected_manufacturing_option` (top-level, and mirrored inside
  `manufacturing_options`), leaving every other field untouched. Typing a
  specific `option_id` *is* the explicit human confirmation an option
  requires - the command doesn't ask a second time. It also advances
  `brief.json`'s status forward-only to `manufacturing_option_selected` (see
  **Status progression** below) and calls
  `factory.manufacturing.manifest.apply_selected_option_to_manifest()` to
  reflect the choice in `part_manifest.json` (see **Multipart workflow**).
  It never generates or modifies CAD, exports an STL, invokes OpenSCAD, or
  contacts a printer/slicer/network - see `factory.manufacturing.selection`.

Choosing an option marked `available: false` for the resolved target printer
(e.g. `multipart_color` with no multicolor-capable printer configured) is
still allowed - `choose-option` prints the same availability warning
`list-options` showed, but doesn't block the choice. Owen may be planning to
swap printers or accessories before printing; this repo doesn't second-guess
an explicit, informed choice.

## Multipart workflow

`factory.manufacturing.manifest.seed_manifest_from_plan()` runs at the end of
`factory plan`, before any CAD or STL exists. For each part in
`build_plan.json`'s `required_parts`, it upserts a `part_manifest.json` entry
with `source_scad`, `intended_material`, `intended_color`, `quantity`,
`shared_origin`, and `export_expected` placeholders. It is purely additive:
it only ever fills in a key that isn't already present on that `part_name`'s
entry, so it never overwrites a human edit and never overwrites the real
values `factory generate-openscad` sets once CAD is actually generated
(`cad_source`, `file_path`, `material`, `color`, `role`, ...). Re-running
`factory plan` after `factory generate-openscad` (or vice versa) is safe and
idempotent.

`factory.validators.multipart_check.check_manifest()` validates the resulting
manifest: duplicate `part_name`s, duplicate `file_path` outputs, missing
`cad_source`/`source_scad`, invalid `quantity` (< 1 or non-integer),
inconsistent `shared_origin` flags across a multi-part project, and - when
given `build_plan.json`'s `required_parts` - planned parts that don't have a
manifest entry yet. It never fuses, aligns, or exports geometry; it only
reads local JSON/files.

**`factory.manufacturing.manifest.compute_assembly_intent()`** (Phase 4) turns
a selected `manufacturing_option` plus `required_parts` into a plain status,
without ever inventing a part breakdown:

| `status` | Meaning |
|---|---|
| `no_option_selected` | Nothing chosen yet - run `factory choose-option`. |
| `multipart_incomplete` | Selected option implies multiple parts, but `required_parts` still only describes the single placeholder part `factory plan` seeds by default. The system says so plainly instead of fabricating detailed geometry/parts. |
| `multipart_ready` | Selected option implies multiple parts, and `required_parts` already lists more than one. |
| `single_piece_ready` | Selected option is `single_piece`. |

`apply_selected_option_to_manifest()` writes this as a computed top-level
`assembly_intent` block in `part_manifest.json` (never touching the `parts`
array), and `factory report` recomputes/shows it live so it always reflects
the current `build_plan.json`, not a stale cached copy.

## Status progression

`factory choose-option` is the one addition to the status ceiling in Phase
4: it may advance `brief.json`'s `status` forward-only to
`manufacturing_option_selected` (inserted between `plan_approved` and
`cad_generated` in `project_store.PROJECT_STATUSES` and the
`project_brief.schema.json` enum). Like every other status, this is
forward-only (`project_store.advance_status`) and can never be
`human_approved` or `print_ready`. `factory report`'s computed "current safe
status" still tops out at `slicer_review_ready` and always ends with "Human
slicer review required." / "Project is NOT print-ready." - see
`docs/safety-gates.md`.

## Future extensibility

New printers, accessories, and materials can be added by editing the JSON
files in `config/manufacturing/` directly - no code changes required, since
`factory.manufacturing.knowledge` reads whatever is present. Planned, not yet
implemented (see `docs/roadmap.md`):

- `factory add-printer` / `factory add-accessory` - CLI commands to add
  entries without hand-editing JSON.
- Additional accessory categories (filament dryers, cameras, laser/cutter
  modules) and additional printer models, as the fleet changes.
- Reconciling `config/printers.json`/`config/materials.json` (Phase 0/1,
  single-printer) with `config/manufacturing/` (Phase 3, fleet-aware) into
  one system.
- Automatically proposing a `required_parts` breakdown once a human confirms
  a multi-part `manufacturing_option`, instead of leaving that as a manual
  follow-up step.

None of this involves hardware communication, printer discovery, or
automatic printing in any future phase - see `AGENT.md`.

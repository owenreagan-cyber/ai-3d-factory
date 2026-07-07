# Safety gates

This document is the human-readable companion to `config/agent_policy.json`.
If the two ever disagree, treat both as wrong until reconciled — file an
issue with yourself (or ask the assisting agent to fix both together).

## Allowed

- Read/write files inside this repo (mainly `projects/`, `config/`, and
  scratch output).
- Run local mesh validation (`trimesh`) and local preview rendering
  (`trimesh` + `matplotlib`).
- Discover local slicer installations by checking `/Applications` and
  `PATH` — never by launching or configuring them.
- Validate JSON files against the schemas in `schemas/`.
- Scaffold new project directories under `projects/`.
- Inspect and validate the local manufacturing knowledge base
  (`config/manufacturing/*.json`) via `factory list-printers`/`show-printer`/
  `list-accessories`/`show-accessory`/`list-materials`/`show-material`/
  `fleet-summary`/`check-manufacturing` — all read-only, never hardware
  discovery.
- Build a project's visual preview package (`preview_package/index.json` +
  `preview_report.md`) via `factory preview-index` (read-only) /
  `factory preview-project` (writes only those two files) — referencing
  existing CAD/STL/render files, never rendering new images, invoking
  OpenSCAD, or exporting an STL. See `docs/visual-preview-package.md`.
- Use OpenSCAD/CadQuery/Blender/Bambu/Orca **discovery or generation
  helpers** added in later phases — not printing.

## Blocked (no exceptions without explicit human approval)

| Action | Why |
|---|---|
| Calling Meshy | Paid generative-mesh API; explicit approval required per use. |
| Calling OpenAI / Claude API / Gemini API / any paid API | This tool must work without ongoing API spend or cloud dependency. |
| Creating or using real secrets / a real `.env` | Nothing here needs live credentials in Phase 0/1. |
| Uploading files anywhere | Local-first means local-only. |
| Connecting to Bambu cloud | No cloud printer connection, ever, from this repo. |
| Sending print jobs | A human always initiates printing, outside this tool. |
| Controlling printer hardware | No LAN/USB/Bluetooth printer control. |
| Running slicer print commands | Slicer discovery is read-only; no invocation. |
| Configuring MCP | Out of scope for this repo. |
| Installing Blender add-ons | Out of scope for this repo. |
| Using `sudo` | This repo never needs elevated privileges. |
| Changing macOS system settings | Out of scope for this repo. |
| Auto-marking anything `print_ready` | Requires explicit human approval, always. |
| Claiming "print-ready" from geometry checks alone | Watertight/manifold ≠ print-ready. Say "geometry sanity check passed; human slicer review required." |
| Generating copyrighted/franchise/anime character assets, logos, or protected symbols | See `docs/licensing-policy.md`. |

## Human approval gates

Two status values require an explicit, human-initiated action and are
never set automatically by any `factory` command:

- **`human_approved`** — a human has reviewed the slicer-review package
  (plate layout, colors/materials, scale, orientation, supports) and
  signed off.
- **`print_ready`** — reserved for a future phase; not implemented, not
  automatically derivable from any local check in this repo.

`factory report` will never print `print_ready` as a project's current
status, even if a brief or other file has been hand-edited to claim it.

### `manufacturing_option_selected` is not a third approval gate

Phase 4 added a `manufacturing_option_selected` status, set by
`factory choose-option <project_dir> <option_id>`. This is an ordinary
forward-only status (like `cad_generated` or `preview_rendered`), not a
third entry in the two gates above: typing a specific `option_id` is itself
the explicit human decision this status records, so the CLI command is
allowed to set it directly - unlike `human_approved`/`print_ready`, which no
`factory` command may ever set regardless of what the human typed. See
`docs/manufacturing-knowledge-base.md`.

### The visual inspection checklist is not an approval gate

`preview_report.md`'s human visual inspection checklist (Phase 6, see
`docs/visual-preview-package.md`) is plain Markdown text - checking a box
there does not change any file, status, or field, and no `factory` command
reads or acts on it. It is advisory only, same spirit as the two gates
above: only a human's actual review in a slicer (`human_approved`) or
explicit sign-off (`print_ready`) can ever move a project past
`slicer_review_ready`.

## If a task asks for a blocked action

Stop and ask for explicit, scoped approval before proceeding. Prefer the
smallest possible relaxation (e.g. "just this one time, for this one file")
over a blanket policy change, and document the decision if it's granted.

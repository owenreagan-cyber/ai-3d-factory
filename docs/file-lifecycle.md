# File lifecycle

Each project lives at `projects/<slug>/` with a fixed set of subfolders,
created by `factory init-project`:

```
projects/<slug>/
├── brief.json           # intent: what/why/owner/constraints (optionally
│                         #   a design_intent block - see below)
├── build_plan.json      # factory plan output: tool routing, required parts, gates
├── part_manifest.json   # one entry per physical part: file, material, color, origin, license
├── cad/                 # parametric CAD source (OpenSCAD/CadQuery scripts)
├── stl/                 # exported meshes, one file per part/color
├── renders/             # preview PNGs from `factory render`
├── validation/          # validation reports from `factory validate`
├── slicer_review/       # slicer-review package data/checklists (see slicer-review-workflow.md)
└── final_candidate/     # files a human has promoted after slicer review
```

## When files move

- **`cad/` → `stl/`**: when a CAD script is exported to a mesh. Keep the
  source in `cad/` so the part can be re-parameterized later. For OpenSCAD
  source, `factory export-from-cad <project_dir> --confirm-export` (Phase
  35, `docs/export-pipeline.md`) can do this export for you - dry run by
  default, only writes with explicit confirmation, and only if a local
  `openscad` executable is found; never overwrites an existing STL without
  `--overwrite-stl`. CadQuery source (`cad/*.py`) remains a manual step -
  run `python cad/<name>.py` yourself, exactly as before this phase.
- **`generated/`**: `generation_receipt.json` (Phase 34),
  `export_receipt.json` (Phase 35), and `slicer_readiness_receipt.json`
  (Phase 36) - machine-readable execution history for confirmed CAD
  generation, export/validate/render, and slicer-review approval/package
  runs, respectively. Never written by a dry run - `slicer_readiness_receipt.json`
  specifically is only ever written by `factory slicer-readiness --approve`
  or `--create-package --confirm-package`, never by the plain read-only
  assessment. Not one of the fixed `factory init-project` subfolders above
  - all three files are created lazily, only after a real confirmed run.
  **Phase 45 note:** a future real Blender project-generation workflow
  would write to its own `<project>/generated/blender/` subdirectory
  (never mixed into `stl/`/`renders/`) and its own additive receipt -
  documented in `docs/blender-adapter.md`, not implemented yet. Phase 45
  itself never writes anywhere under `projects/` at all; its one
  qualification fixture lives entirely in a `tempfile.TemporaryDirectory()`.
  **Phase 49 implements exactly this**, narrowly, for one workflow - see
  the Phase 49 addendum below.
- **`stl/` → `validation/` + `renders/`**: `factory validate` and
  `factory render` write their outputs into these folders automatically
  when the input mesh lives under a project's `stl/` directory (or
  anywhere else under `projects/<slug>/`). `factory export-from-cad
  --validate --render` (or `--all`) calls these same two commands for you
  right after a confirmed export.
- **`stl/` → `validation/` + `renders/`**: `factory validate` and
  `factory render` write their outputs into these folders automatically
  when the input mesh lives under a project's `stl/` directory (or
  anywhere else under `projects/<slug>/`).
- **`stl/` + `renders/` + `validation/` → `slicer_review/`**: once a part
  has a clean-enough validation report and a preview render, it's ready
  for a human to review it in a slicer. `slicer_review/` holds the
  human-facing checklist/record of that review (see
  `docs/slicer-review-workflow.md`), not new geometry. `factory
  slicer-readiness <project> --create-package --confirm-package` (Phase
  36, `docs/slicer-readiness.md`) can populate `slicer_review/
  slicer_review_manifest.json` (+ a README checklist) for you - only once
  every technical signal is satisfied and a separate `--approve` step has
  already been recorded - **referencing** the STL/validation/render files
  above by relative path rather than copying them into `slicer_review/`.
- **`slicer_review/` → `final_candidate/`**: only after a human has
  explicitly approved a part in `slicer_review/` (i.e. recorded
  `human_approval.approved: true`) should its files be copied into
  `final_candidate/`. This is a manual, human-initiated move in Phase 0/1
  — no `factory` command does this automatically.

## Design intent in `brief.json` (optional, additive)

`brief.json` may optionally include a structured `design_intent` block -
style direction, visual/functional goals, manufacturability constraints,
an iteration plan - see `docs/design-intent-brief.md` (Phase 24) for the
proposed shape. This is planning-only: `schemas/project_brief.schema.json`
already allows it (`additionalProperties: true`), no `factory` command
requires, reads, or validates it today, and every existing `brief.json`
without one remains fully valid. When present, it's what a human review
(see `docs/review-gate.md`'s "Human review quality checklist") should
compare the finished part against.

## Reused by Phase 41's artifact history

`factory.artifact_history` (Phase 41, `docs/artifact-history.md`)
classifies a fingerprinted relative path into an artifact category using
exactly the directory/filename conventions above - `cad/` → `cad`,
`stl/` → `stl`, `validation/` → `validation`, `renders/` → `preview`,
`part_manifest.json` → `manifest`, `build_plan.json` → `build_plan`,
`slicer_review/`/`manual_review/` → `review_package`, `generated/meshy/*.stl`
→ `stl` (Phase 47B.7), `generated/blender/*.stl` → `stl` (Phase 49), and
`generated/cad_augmentation/*.stl` → `stl` (Phase 50) -
never a second classification scheme. It introduces no new folder or
file of its own; it is entirely read-only.

## Reused by Phase 42's project health dashboard

`factory.project_health` (Phase 42, `docs/project-health.md`) reads
every project file listed above only indirectly, through the existing
summary/assessment functions (`factory.project_inspection`,
`factory.slicer_readiness`, `factory.manual_review_workspace`,
`factory.slicer_intelligence`, `factory.project_timeline`,
`factory.artifact_history`) - it never reads a project file directly and
introduces no new folder or file of its own; it is entirely read-only.

## Phase 46's `config/meshy_policy.json` is repo-level, not project-level

Unlike every file above, `config/meshy_policy.json` (Phase 46,
`docs/meshy-policy.md`) lives outside any project directory entirely -
one committed, non-secret policy file for the whole repo, mirroring
`config/future_cloud_tools.json`'s existing pattern. It is never created,
read, or written per-project, never appears in a project's `cad/`/`stl/`/
`part_manifest.json`, and is touched by exactly two explicit CLI writes
(`factory meshy approve-policy`/`revoke-policy`) - never automatically,
never as a side effect of any project-scoped command above.

**Phase 47A addendum:** `factory meshy mock-run --confirm-mock` writes
nothing at all unless a caller passes an explicit `--project <dir>`, in
which case exactly two files are written under that project:
`generated/meshy_receipt.json` and `generated/meshy/mock_concept.stl` -
both clearly labeled mock artifacts (`mock_execution: true`,
`live_api_used: false`), never written into `examples/` unless a caller
explicitly targets an `examples/...` path themselves. Without
`--project`, the entire mocked run happens inside one
`tempfile.TemporaryDirectory()`, verified cleaned after the command
returns.

**Phase 47B addendum:** two new machine-local, gitignored state files -
`state/meshy_spend_ledger.json` (persistent credit spend, never a
project or a config file) and `state/meshy_live_approvals.json`
(one-shot live-call approval records) - live alongside `config/`/
`projects/`, added via `.gitignore`'s `state/*` / `!state/.gitkeep`
pattern (matching `projects/*` / `!projects/.gitkeep`'s existing
convention). Neither ever contains a secret. `factory meshy live-run
--confirm-live` writes a real project artifact only when every gate
passes and `--project <dir>` is given: `generated/meshy/raw/<task_id>.stl`
(the preserved provider artifact), `generated/meshy/processed/<task_id>.stl`
(the Factory-facing copy), and `generated/meshy_receipt.json` -
collision-protected, never overwriting an existing artifact. Without
every gate passing, nothing is written at all.

**Phase 48 addendum:** `factory workflow plan`/`factory workflow assess`
write **nothing at all**, ever - no new file, no new directory, no
receipt. `factory.hybrid_workflow` only reads existing receipts
(`generated/meshy_receipt.json`, `generated/generation_receipt.json`,
`generated/export_receipt.json`) and an optional `design_intent` block
already in `brief.json`. There is no `hybrid_workflow_receipt` yet -
nothing here executes, so there is nothing to persist. See
`docs/hybrid-workflow.md`.

**Phase 49 addendum:** `factory blender-adapt plan <artifact>` writes
**nothing at all**, ever - same dry-run-by-default convention as every
planning-only command in this repo. `factory blender-adapt execute
<artifact> --target-max-mm N --confirm` writes a real project artifact
only when every gate passes (Blender detected, a fresh fixture-
qualification proof, and explicit human confirmation on that exact
call): `generated/blender/adapted/<stem>_adapted.stl` (the child
artifact - the original input artifact is never modified, moved, or
overwritten) and `generated/blender_adaptation_receipt.json` (a sibling
of `generated/meshy_receipt.json`/`generated/export_receipt.json`,
collision-protected - refuses to overwrite an existing receipt or output
file). Without every gate passing, nothing is written at all. See
`docs/blender-adaptation.md`.

**Phase 50 addendum:** `factory cad-augment plan <artifact>` writes
**nothing at all**, ever - same convention. `factory cad-augment execute
<artifact> --base-width-mm N --base-length-mm N --base-height-mm N
--confirm` writes a real project artifact only when every gate passes
(a valid plan with every required parameter provided, an executable CAD
engine, and explicit human confirmation on that exact call):
`generated/cad_augmentation/<stem>_feature.scad` and `.stl` (the new,
separate mechanical-feature part - the organic input artifact is never
modified, moved, or overwritten, and never boolean-merged with the new
part) and `generated/cad_augmentation_receipt.json` (a sibling of
`generated/blender_adaptation_receipt.json`, collision-protected -
refuses to overwrite an existing receipt, feature source, or output
file). Without every gate passing, nothing is written at all. See
`docs/cad-augmentation.md`.

**Phase 51 addendum:** `factory design-review <project>` writes
**nothing at all** by default - exactly like `factory health`, it
computes a fresh, read-only analysis on every call. Only
`factory design-review <project> --save` additionally writes
`generated/design_review_report.json` - a versioned, fingerprinted
**analysis snapshot**, never an execution receipt (a distinct filename
from every `*_receipt.json` in this repo), always safely overwritable on
the next `--save`. See `docs/design-review.md`.

## What never happens automatically

No file is ever moved into `final_candidate/`, and no project status is
ever set to `human_approved` or `print_ready`, by a `factory` command.
`factory report` reflects what's on disk; it does not promote anything.

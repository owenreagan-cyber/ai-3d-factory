# File lifecycle

Each project lives at `projects/<slug>/` with a fixed set of subfolders,
created by `factory init-project`:

```
projects/<slug>/
├── brief.json           # intent: what/why/owner/constraints
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
  source in `cad/` so the part can be re-parameterized later.
- **`stl/` → `validation/` + `renders/`**: `factory validate` and
  `factory render` write their outputs into these folders automatically
  when the input mesh lives under a project's `stl/` directory (or
  anywhere else under `projects/<slug>/`).
- **`stl/` + `renders/` + `validation/` → `slicer_review/`**: once a part
  has a clean-enough validation report and a preview render, it's ready
  for a human to review it in a slicer. `slicer_review/` holds the
  human-facing checklist/record of that review (see
  `docs/slicer-review-workflow.md`), not new geometry.
- **`slicer_review/` → `final_candidate/`**: only after a human has
  explicitly approved a part in `slicer_review/` (i.e. recorded
  `human_approval.approved: true`) should its files be copied into
  `final_candidate/`. This is a manual, human-initiated move in Phase 0/1
  — no `factory` command does this automatically.

## What never happens automatically

No file is ever moved into `final_candidate/`, and no project status is
ever set to `human_approved` or `print_ready`, by a `factory` command.
`factory report` reflects what's on disk; it does not promote anything.

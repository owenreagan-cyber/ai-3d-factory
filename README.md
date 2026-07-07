# ai-3d-factory

`ai-3d-factory` is a local-first CLI that helps create, organize, validate,
preview, and package 3D print projects for human slicer review. It is not
an auto-printer; see `AGENT.md` for the full philosophy and safety rules.

## What this repo is not

- Not an auto-printer. Nothing here sends a print job, slices with intent
  to print, or controls a printer.
- Not connected to Meshy or any paid generative-mesh/AI API.
- Not connected to Bambu cloud or any printer over LAN/USB.
- Not something that marks a project `print_ready` automatically.

## Before you start

Make sure the toolchain foundation is installed and verified. This repo
does not install system packages itself:

```bash
cd ~/Projects/ai-3d-factory-installer
./install.sh --dry-run
./install.sh --install
./verify.sh
```

## Setup

```bash
cd ~/Projects/ai-3d-factory
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

Copy `.env.example` to `.env` only if and when you have a specific,
approved, local-only use for one of the currently optional and unused
variables. Do not fill in real API keys; this project does not call paid
APIs. See `AGENT.md`.

## CLI usage

```bash
factory status                       # environment + safety status
factory init-project my-part         # scaffold projects/my-part/
factory plan projects/my-part/brief.json   # printer-aware plan + manufacturing options
factory list-options projects/my-part      # explain every manufacturing option
factory choose-option projects/my-part <option_id>   # record your explicit choice
factory list-printers                # inspect the printer fleet (read-only)
factory show-printer bambu_h2d
factory list-accessories             # inspect the accessory catalog (read-only)
factory list-materials                # inspect materials (read-only)
factory fleet-summary                 # compact view of all printers
factory check-manufacturing           # validate config/manufacturing/*.json
factory generate-openscad projects/my-part --template test-cube
factory validate path/to/model.stl
factory render path/to/model.stl
factory inspect-slicer               # read-only slicer discovery
factory report projects/my-part      # includes manufacturing summary + open decisions
```

`factory plan` reads a local manufacturing knowledge base
(`config/manufacturing/`: printers, materials, accessories, planning rules)
to resolve the target printer, explain every manufacturing option (single
piece vs. various multi-part approaches) with pros/cons, and recommend one -
non-bindingly, always requiring explicit human confirmation via
`factory choose-option`. `config/manufacturing/printers.json` is the sole
canonical printer source; `factory list-printers`/`show-printer`/
`list-accessories`/`show-accessory`/`list-materials`/`show-material`/
`fleet-summary` inspect it directly (all read-only), and
`factory check-manufacturing` validates it for internal consistency. See
`docs/manufacturing-knowledge-base.md`.

This CLI is the local engine, not the final intended user experience - see
`docs/product-vision.md` for the (not-yet-built) future visual/launcher
direction.

## Workflow

idea/brief -> build plan -> part manifest -> CAD/assets later phase
  -> mesh validation -> preview rendering -> slicer review package
  -> human approval -> future print-ready status

Phase 0/1 stops at `slicer_review_ready`. Human approval is always required
beyond that point; see `docs/safety-gates.md`.

## Repo layout

```
ai-3d-factory/
├── config/          # printers, materials, tolerances, agent policy
│   └── manufacturing/  # printer fleet, accessories, materials, planning rules
├── docs/            # architecture, safety, tool routing, workflows
├── schemas/         # JSON Schemas for briefs/plans/manifests/reports
├── src/factory/     # the factory CLI package
├── prompts/         # reference prompts for AI-assisted design steps
├── examples/        # example project briefs
├── projects/        # your actual projects (contents gitignored)
└── tests/           # pytest suite
```

## Safety

See `AGENT.md`, `docs/safety-gates.md`, and `config/agent_policy.json` for
the full allowed/blocked list: printing, cloud upload, printer control,
paid APIs, MCP, Blender add-ons, and copyrighted assets. This repo carries
forward the same boundaries as `ai-3d-factory-installer` and does not
relax any of them by default.

# Factory Engine Registry (Phase 43)

`factory.engine_registry` is the Factory's one canonical answer to:
"what tools exist, what are they good at, are they installed, and are
they qualified for Factory use?" It is a registry, not an executor:

```
Feature Modules -> domain summaries -> Engine Registry -> CLI / Preview Board
```

## Purpose

Before this phase, tool knowledge was scattered: `factory.cad.backend`
knew about OpenSCAD/CadQuery/Blender/Meshy as CAD *backends*;
`factory.slicer.local_slicer_probe` knew how to find local slicers;
`factory.future_local_tools`/`factory.future_cloud_tools` knew Blender's
and Meshy's approval-gate configs. None of them had ever heard of
FreeCAD, Plasticity, Autodesk Fusion, Onshape, or Bambu Connect, and
there was no single place to ask "what's the full tool landscape, and
where does each tool stand?" `factory.engine_registry` answers that
question by aggregating all of the above (never replacing any of it)
plus adding registry-only entries for the five tools nothing else
tracked yet.

**This phase is architecture and read-only discovery only.** It does
not install anything, does not launch a GUI application, does not
execute Blender/FreeCAD/a slicer/Meshy, does not contact a printer or a
cloud service, and does not generate G-code. See "Safety rules" below.

## Specialized modules remain authoritative

```
factory.cad.backend                  still owns CAD backend routing/status
factory.slicer.local_slicer_probe    still owns local slicer detection
factory.future_local_tools           still owns the Blender approval gate
factory.future_cloud_tools           still owns the Meshy approval gate
engine_registry                      aggregates and normalizes all of the above,
                                      plus tools none of them track yet
```

`engine_registry` never re-implements a detection technique those
modules already have - see `factory/engine_registry.py`'s module
docstring for the full reuse list (`is_cadquery_available()`,
`resolve_openscad_executable()`, `probe_slicers()`,
`list_future_local_tools()`/`list_future_cloud_tools()`).

## Canonical tool list

| Tool | `tool_id` | Category | Display group |
|---|---|---|---|
| OpenSCAD (stable) | `openscad_stable` | design_cad | design_cad |
| OpenSCAD (snapshot/development) | `openscad_snapshot` | design_cad | design_cad |
| CadQuery | `cadquery` | design_cad | design_cad |
| Blender | `blender` | organic_mesh_modeling | design_cad |
| FreeCAD | `freecad` | design_cad | design_cad |
| Meshy | `meshy` | cloud_design | cloud |
| Plasticity | `plasticity` | design_cad | future |
| Autodesk Fusion | `autodesk_fusion` | design_cad | future |
| Onshape | `onshape` | cloud_design | future |
| Bambu Studio | `bambu_studio` | slicer_review | slicers |
| OrcaSlicer | `orcaslicer` | slicer_review | slicers |
| PrusaSlicer | `prusaslicer` | slicer_review | slicers |
| Bambu Connect | `bambu_connect` | printing_adjacent | future |

These 13 entries are permanent per this phase's roadmap amendment - none
may be silently dropped from a future phase's documentation or registry
without an explicit, approved removal.

`category`/`subcategory` describe what a tool *is*; `display_group` is
presentation-only grouping for the CLI/Preview Board (matches the
example `factory engines` layout below) and carries no other meaning.

## Status vocabularies

Closed, stable vocabularies (`factory.engine_registry.*`, asserted on
every record by `_tool()`):

- **`roadmap_status`**: `core_supported`, `installed_unqualified`,
  `qualified_local`, `near_term`, `future`, `experimental`,
  `cloud_gated`, `human_only`, `printing_adjacent_disabled`.
- **`execution_status`**: `implemented`, `planned`, `manual_only`,
  `unsupported`, `future`, `disabled`, `approval_required`.
- **`qualification_status`**: `qualified`, `unqualified`, `not_tested`,
  `not_installed`, `not_applicable`. **No tool may claim `qualified` in
  this phase** - formal qualification testing is Phase 44's job (see
  "Detection is not qualification" below).
- **`local_or_cloud`**: `local`, `cloud`, `hybrid`.
- Qualitative suitability fields (`mechanical_design_suitability`,
  `organic_modeling_suitability`, etc.): `high`, `moderate`, `low`,
  `not_applicable`, `unknown`.

Unknown is always spelled out explicitly (`"unknown"`, `not_detected`,
`not_applicable`, ...) - never a blank string, never `None` for a
required field, never a guessed value.

## Detection is not qualification, and qualification is not execution approval

Three separate facts, never collapsed into one:

1. **Detected** - a filesystem/PATH/package-metadata check found the
   tool locally. Says nothing about whether it works correctly.
2. **Qualified** - a formal test (Phase 44's job) confirmed the tool
   behaves correctly for Factory use. Every tool's `qualification_status`
   stays `not_tested`/`not_applicable`/`not_installed` in this phase -
   never `qualified`.
3. **Approved for execution** - a human has explicitly turned on
   automation for that tool (the Blender/Meshy approval-gate configs
   already model this for those two; every other tool has no execution
   path at all yet).

## Capability matrix is qualitative, not calibrated

The suitability fields (`mechanical_design_suitability`,
`organic_modeling_suitability`, `parametric_design_suitability`,
`dimensional_precision_suitability`, `mesh_cleanup_suitability`,
`assembly_suitability`, `slicer_suitability`) are qualitative labels
(`high`/`moderate`/`low`/`not_applicable`/`unknown`) written by hand from
each tool's well-known, documented characteristics - never a
scientifically calibrated benchmark, never derived from measuring an
actual local installation. Example:

```
OpenSCAD    Mechanical: High   Organic: Low    Parametric: High   Precision: High
CadQuery    Mechanical: High   Organic: Low    Parametric: High   STEP: Yes
Blender     Mechanical: Low    Organic: High   Procedural: High   Precision: Moderate
FreeCAD     Mechanical: High   Assembly: High  STEP: High         Organic: Low
Meshy       Organic concept: High   Mechanical precision: Low   Cloud: Yes
```

## OpenSCAD: stable vs. snapshot

The registry deliberately keeps two separate records
(`openscad_stable`/`openscad_snapshot`) rather than one opaque OpenSCAD
entry. Today, `factory.export_pipeline.resolve_openscad_executable()`
(the pipeline's own binary resolver) does not distinguish channels - it
resolves whichever `openscad` binary it finds and this registry always
attributes that result to `openscad_stable`. `openscad_snapshot` stays
`not_detected`/`not_applicable` permanently in this phase; no Homebrew
cask token for a separate snapshot build could be verified locally, so
none is recorded (see "Homebrew metadata policy" below). Building an
actual snapshot-channel detection path and deciding its qualification is
explicitly a Phase 44 concern.

## CadQuery

Reuses `factory.cad.backend.is_cadquery_available()` directly (never a
second importability check) and, when available, reads the installed
package's version via `importlib.metadata.version("cadquery")` - package
metadata only, never an import of the package's own code. This repo
never installs or upgrades `cadquery`.

## Blender and FreeCAD: local, near-term, never executed

Both are detected by path only (a known `.app` bundle location, then a
`PATH` binary - the same technique
`factory.slicer.local_slicer_probe.probe_slicers()` and
`factory.export_pipeline.resolve_openscad_executable()` already use) and
their version (if available at all) is read from the `.app` bundle's
`Info.plist` - a plain file read (`plistlib`), never process execution.
**Neither is ever passed to `subprocess`** - `docs/blender-local-track.md`'s
existing "no subprocess call, no headless invocation" rule for Blender is
preserved in full, and this registry applies the same rule to FreeCAD by
symmetry (the spec explicitly says "do not execute FreeCAD" too). This is
a deliberate, narrowly-scoped amendment to `docs/blender-local-track.md`'s
prior "never even a read-only `/Applications` scan" note - see that
document's own "Phase 43 amendment" section for the precise boundary:
`engine_registry` may look, but still never launches, still never calls
subprocess for either tool, and this registry is a different module from
`factory.future_local_tools`/`check-local-tools`, whose own read-only
scope is unchanged.

Both are `roadmap_status: "near_term"` - Blender is owned by the Phase 45
"Blender Local Execution Gate & Adapter" track (complete - see
`docs/blender-adapter.md`; it adds exactly two real, bounded Blender
invocations against one throwaway qualification fixture, never against a
project, and this registry's own static Blender record is unchanged by
it); FreeCAD has no scheduled adapter phase yet.

## Meshy: cloud-gated, never contacted

This registry never calls Meshy, never authenticates, never reads a
credential, and never contacts the network for it. `meshy`'s record is
built entirely from `config/future_cloud_tools.json` (via
`factory.future_cloud_tools.list_future_cloud_tools()`) plus hand-written
capability metadata reflecting Meshy's publicly documented feature set
(text/image concept generation, Image-to-3D, Multi-Image-to-3D, the
Meshy 7 family, Smart Topology, separated/native parts, target polygon
count, 3MF output, Multi-Color Print, Analyze Printability, Repair
Printability, Auto Split) - none of that metadata is fetched live from
Meshy; it is static, documented capability description only.

**Meshy-generated or Meshy-repaired output != Factory validated != human
approved** - three separate facts, never collapsed into one. See
`docs/meshy-approval-gate.md` for the full checklist a future
implementation (Phase 46 cloud/cost/license gate, then Phase 47
concept/print-preparation gateway) must satisfy before Meshy is ever
actually called.

## Plasticity, Autodesk Fusion, Onshape: permanent future entries

Recorded permanently per this phase's roadmap amendment so they cannot
silently vanish from future documentation:

- **Plasticity** - `future`/GUI-only direct/NURBS modeling. Detected by
  path only, best-effort; never executed, never installed.
- **Autodesk Fusion** - `future`/hybrid local-cloud professional
  mechanical CAD. No Autodesk API integration, no authentication, no
  launch.
- **Onshape** - `future`/cloud-only parametric mechanical CAD. Purely a
  web application - there is no local binary to detect at all;
  `detected` stays `False` permanently, and no network contact is ever
  made.

## Slicers: Bambu Studio, OrcaSlicer, PrusaSlicer

Detected entirely via `factory.slicer.local_slicer_probe.probe_slicers()`
- never re-implemented here. `roadmap_status: "human_only"`,
`execution_status: "manual_only"`: this repo never launches a slicer,
never slices, and never generates G-code. A human opens the existing
slicer-review package themselves, per `docs/slicer-review-workflow.md`.

## Bambu Connect: registry only, disabled

`category: "printing_adjacent"`, `roadmap_status:
"printing_adjacent_disabled"`. Out of scope for every phase through this
one - no integration, no launch, no printer communication, no
authentication. `automatic_print_permission` is `False`, exactly like
every other tool, with no exception.

## Homebrew metadata policy

`homebrew_token` is recorded as static, documented metadata only (a
well-known public cask/formula name) - this repo **never invokes
`brew`** (no `brew install`/`upgrade`/`update`/`info`/`list`, read-only
or otherwise) anywhere in `engine_registry.py`. There was no existing
safe local-shell convention for querying Homebrew in this codebase
before this phase, and introducing one wasn't judged worth the added
subprocess surface for what static metadata already covers adequately.
CadQuery, Onshape, and Meshy are deliberately `homebrew_token: None` -
CadQuery is a Python package (`install_method: "python_package"`), and
Onshape/Meshy are cloud services with no local install at all. No
speculative/unverifiable cask token is recorded for the OpenSCAD
snapshot channel (see "OpenSCAD: stable vs. snapshot" above).

## Probe behavior

`get_tool_registry()` (no arguments) returns the static registry only -
every `detected*` field stays at its safe default, and no I/O beyond the
two existing optional-dependency checks (`is_cadquery_available()`,
which the CAD backend registry already performs on every call) happens
at all.

`probe_all_tools()`/`get_tool_registry(probe=True)` additionally runs
safe, read-only local detection:

- Filesystem path checks and `PATH` lookups (`shutil.which`) for every
  local `.app`/binary tool.
- `importlib.metadata.version()` for the optional `cadquery` package.
- A single, narrowly-scoped, timeout-bounded `openscad --version`
  subprocess call - identical in technique to the pre-existing
  `factory.export_pipeline._probe_tool_version()` - **only** when
  `include_version_subprocess=True` (reserved for the explicit `factory
  engines probe` CLI command; Preview Board and Project Health
  aggregation always pass `False`, so board/health generation never
  spawns a subprocess).

A single tool's probe failure is informational only
(`probe_status: "probe_failed"`) and never aborts the rest of the
registry - each tool's probe runs inside its own `try/except` in
`probe_all_tools()`.

Meshy and Onshape are never probed at all (`probe_status:
"not_applicable"`) - they are cloud-only, and there is nothing local to
detect.

## Safety rules

- No install, no upgrade, ever (`brew install`/`upgrade`/`update` never
  appear in this module).
- No GUI application launch, ever - Blender, FreeCAD, Plasticity,
  Autodesk Fusion, Bambu Studio, OrcaSlicer, PrusaSlicer, and Bambu
  Connect are all detected by path only, never executed.
- No AppleScript/`osascript`, no `open`, no `pkill`, no GUI automation of
  any kind.
- No slicer execution, no G-code generation, no printer communication.
- No Meshy/Onshape network contact, no credential reads, no
  authentication.
- No Homebrew mutation (and, as documented above, no Homebrew subprocess
  call of any kind in this phase).
- `automatic_print_permission` is `False` on every single record, with no
  exception and no override path.

See `tests/test_engine_registry_probe.py`'s safety-guard tests (mirroring
`tests/test_slicer_probe.py`'s source-inspection pattern) for the
automated enforcement of the above.

## Limitations

- `detected_architecture` stays `"unknown"` for every tool in this phase
  - determining CPU architecture from a binary without executing it
    would require a further, separately-reviewed technique (e.g. `file`/
    `lipo` inspection); deliberately out of scope here to keep the
    detection surface minimal.
- `detected_version` for GUI-only local apps depends entirely on that
  app's `Info.plist` carrying `CFBundleShortVersionString` - some
  installs may not, in which case `"unknown"` is reported honestly
  rather than guessed.
- The OpenSCAD stable/snapshot distinction still cannot actually be
  probed differently - both channels resolve through the same
  `resolve_openscad_executable()` path today; see `docs/tool-qualification.md`
  (Phase 44) for the current qualification-side treatment of this same
  limitation.
- Qualitative suitability labels reflect each tool's well-documented
  public characteristics, not a benchmark run in this repo.

## Phase 44 cross-reference

`factory.tool_qualification` (Phase 44, `docs/tool-qualification.md`) is
a **different module**, layered above this one, that answers a question
this registry deliberately does not: whether a detected tool actually
works. It reuses `probe_all_tools()`/`get_tool_registry()` directly
rather than re-implementing any detection here, and never writes back
into this module's static registry - qualification results are joined at
runtime by the caller, never persisted into a tool's registry record.

## No-authority rule

This registry never overrides, recalculates, or replaces any decision an
existing module already makes - `factory.cad.backend`'s backend
`status`, `factory.design_orchestrator.recommend_engine()`'s
recommendation, and every approval-gate config stay exactly as
authoritative as before this phase. `engine_registry` only aggregates and
normalizes what already exists, plus adds registry-only entries for
tools nothing tracked yet.

## CLI

```
factory engines                # static registry view (no local detection)
factory engines --json
factory engines probe          # + safe read-only local detection
factory engines probe --json
```

See `factory engines --help` for the full option list.

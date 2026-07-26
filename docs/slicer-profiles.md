# Slicer-Aware Review Profiles (Phase 39, Part 1/2)

`factory.slicer_profiles` customizes human review guidance based on the
detected local slicer environment - never requiring any of these
applications to actually be installed, never inventing which one is
installed, and never editing, launching, or configuring any of them.

```
Slicer Readiness -> Manual Review Workspace -> Slicer Review Intelligence
-> Slicer-Aware Review Profiles -> Analysis History -> Human Slicer Review
-> (never automatic printing)
```

## Reuses detection, adds guidance content only

This module never re-implements slicer detection.
`factory.slicer.local_slicer_probe.probe_slicers()` (the single, existing
local slicer-detection module) is reused directly. Phase 39 extended that
module **in place** with a `PrusaSlicer` candidate (macOS `.app` bundle +
`prusa-slicer` PATH binary, mirroring the existing Bambu Studio/OrcaSlicer
entries exactly) rather than creating a second, competing slicer registry -
`SUPPORTED_SLICER_NAMES = ("Bambu Studio", "OrcaSlicer", "PrusaSlicer")`
in `factory.slicer_profiles` is just the subset of `probe_slicers()`'s
candidates this module has review-guidance content for.

## Never invents an installed profile

`get_slicer_review_profile()` only ever reports a slicer as `"detected"`
if `probe_slicers()` actually found it locally. If none of the three
supported slicers is detected, `profile_status` is `"not_detected"` and
the profile falls back to a **generic, slicer-agnostic checklist** -
never a guess at which slicer a human might be using.

## Profile model

`SlicerReviewProfile` (the dict `get_slicer_review_profile()` returns):

| Field | Meaning |
|---|---|
| `slicer_name` | `"Bambu Studio"` / `"OrcaSlicer"` / `"PrusaSlicer"` / `"Unknown"` (or any name explicitly passed in, even if unsupported). |
| `profile_status` | `"detected"` or `"not_detected"`. |
| `known_capabilities` | A short list of what that slicer is known for (e.g. AMS support) - informational only, never a settings recommendation. |
| `review_categories` | High-level review category names for that slicer. |
| `printer_questions` | Printer-profile review questions. |
| `material_questions` | Filament-profile review questions. |
| `multi_material_questions` | AMS/MMU/multi-color review questions - only populated when `multi_material=True` is passed. |
| `warnings` | e.g. more than one supported slicer detected locally, or an unsupported/unrecognized name was requested. |
| `limitations` | Always includes the standing note that this profile never reads that slicer's actual saved settings. |
| `confidence` | `High` (a supported slicer was actually detected) / `Low` (an explicitly-named but unsupported slicer) / `Unknown` (nothing detected). |

## Supported profiles

### Bambu Studio

```
Review:
- AMS assignments
- filament mapping
- build plate choice
- support settings
- wall count
- strength settings
```

### OrcaSlicer

```
Review:
- filament profile
- calibration profile
- pressure advance awareness
- supports
- adaptive layers
```

### PrusaSlicer

```
Review:
- filament profile
- printer profile
- support settings
- layer settings
```

### Unknown / unsupported slicer

A generic, slicer-agnostic checklist only: filament profile, printer
profile, support settings, layer settings. `confidence` is `"Unknown"`.

## Profile-aware review checklist (Part 2)

`factory.slicer_intelligence.evaluate_slicer_intelligence()` (Phase 38)
gained two additive fields, built from this module - **the existing
geometry/manufacturing checklist content is never replaced, only
extended**:

- `slicer_profile` - the full `SlicerReviewProfile` above, auto-detected;
  `multi_material=True` is passed automatically whenever
  `multi_material_considerations` (Phase 38's own AMS-relevance check) is
  non-empty - never a second relevance test.
- `slicer_specific_checks` - `build_slicer_specific_checks()`'s flattened
  `printer_questions` + `material_questions` + `multi_material_questions`,
  in that order - the CLI's "Additional Review Items" list.

Example (Bambu Studio detected, multi-material relevant):

```
SLICER PROFILE
Bambu Studio

Additional Review Items:
☐ Confirm the correct Bambu printer profile is selected.
☐ Confirm build plate type matches the physical plate installed.
☐ Confirm nozzle size matches the physical nozzle installed.
☐ Confirm filament profile matches the actual filament loaded.
☐ Confirm filament drying/prep matches this material's requirements.
☐ Confirm AMS filament mapping - each AMS slot assigned to the correct filament.
☐ Confirm plate selection for multi-plate projects.
☐ Confirm multi-color assignment per part/region.
☐ Confirm purge/prime tower expectations for this color count.
```

## Limitations

- **Detection is local application presence only** - this module (like
  `local_slicer_probe.py` itself) never reads a slicer's actual saved
  profiles/settings, never queries its version, and never launches it to
  check anything.
- **Priority order, not "all detected"** - if more than one supported
  slicer is detected locally, only the first in `SUPPORTED_SLICER_NAMES`
  priority order (Bambu Studio, then OrcaSlicer, then PrusaSlicer) is
  profiled; the others are noted in `warnings`, not silently dropped.
- **No fuzzy slicer-name matching** - an explicitly-passed name must
  exactly match a supported name (case-sensitively) to get that slicer's
  profile content; anything else falls back to generic.

## Non-goals

- **Never edits, launches, or configures any slicer.**
- **Never invents a specific setting value** - only what to *review*, per
  this repo's standing "no invented manufacturing decisions" principle.
- **Never installs a slicer.**
- **No network calls.**

See also `docs/slicer-intelligence.md` (Phase 38, this module's
consumer), `docs/slicer-analysis-history.md` (Phase 39, the sibling
history module), and `docs/roadmap.md` Phase 39.

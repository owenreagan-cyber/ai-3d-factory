"""Phase 43: Design, Manufacturing, Slicer & Tool Registry.

The Factory's canonical, single answer to "what tools exist, what are
they good at, are they installed, and are they qualified for Factory
use?" - a registry, not an executor. **This module never installs,
upgrades, or launches anything; never executes Blender/FreeCAD/Meshy/a
slicer; never contacts a printer or cloud service; never generates
G-code.** Detection is not qualification, and qualification is not
execution approval - `qualification_status` for every tool stays
`"not_tested"`/`"not_applicable"` in this phase; formal qualification
testing is Phase 44's job (see `docs/roadmap.md`).

    Feature Modules -> domain summaries -> Engine Registry -> CLI / Preview Board

Reuses rather than duplicates:

- `factory.cad.backend.is_cadquery_available()` (Phase 7) - the existing
  "is `cadquery` importable" check, never re-implemented here.
- `factory.export_pipeline.resolve_openscad_executable()` (Phase 35) -
  the existing OpenSCAD binary discovery (`.app` bundle, then `PATH`),
  never a second lookup table.
- `factory.slicer.local_slicer_probe.probe_slicers()` (Phase 0/1) - the
  existing Bambu Studio/OrcaSlicer/PrusaSlicer local discovery, never
  re-implemented; this module only re-shapes its result into registry
  records.
- `factory.future_local_tools`/`factory.future_cloud_tools` (Phases 16,
  21) - the existing Blender/Meshy approval-gate config
  (`config/future_local_tools.json`/`config/future_cloud_tools.json`);
  this module's `human_approval_required`/`cloud_gate_required` fields
  for those two tools restate those configs' own gate flags, never a
  second gate.

Specialized modules remain authoritative for their own domain - this
module is a read-only aggregation layer above them, not a replacement:

    factory.cad.backend            still owns CAD backend routing/status
    factory.slicer.local_slicer_probe   still owns local slicer detection
    factory.future_local_tools/future_cloud_tools  still own the approval gates
    engine_registry                 aggregates and normalizes all of the above,
                                     plus tools none of them track yet
                                     (FreeCAD, Plasticity, Fusion, Onshape,
                                     Bambu Connect, the OpenSCAD snapshot channel)

**Detection technique, and why it's safe:**

- Filesystem path checks (`Path.is_dir()` on a known `.app` bundle,
  `shutil.which()` on `PATH`) - the same read-only technique
  `factory.slicer.local_slicer_probe.probe_slicers()` and
  `factory.export_pipeline.resolve_openscad_executable()` already use.
  Never launches the application.
- `importlib.metadata.version()` for the optional `cadquery` Python
  package - reads installed package metadata, never imports or executes
  the package's own code.
- A single, narrowly-scoped, timeout-bounded `openscad --version`
  subprocess call - the *exact* safe pattern
  `factory.export_pipeline._probe_tool_version()` already uses in this
  repo today (argument-list, `capture_output=True`, a hard timeout,
  broad exception handling so a failure is informational only). OpenSCAD
  documents `--version` as a read-only, non-GUI flag. This module never
  does the equivalent for Blender/FreeCAD/any slicer/Plasticity/Fusion -
  see `docs/blender-local-track.md`'s explicit "no subprocess call, no
  headless invocation" rule for Blender, which this module preserves in
  full: those tools are detected by path only, and their
  `detected_version` reads (if available at all) a `.app` bundle's
  `Info.plist` - a plain file read (`plistlib`), never process
  execution.
- No AppleScript, no `osascript`, no `open`, no `pkill`, no GUI
  automation, no Homebrew subprocess of any kind (`brew` is never
  invoked here - see `docs/engine-registry.md` "Homebrew metadata
  policy").

`get_tool_registry()` never does any of the above (all `detected*`
fields stay their safe defaults) - only `probe_all_tools()`/
`get_tool_registry(probe=True)` do, and only when a caller (the
`factory engines probe` CLI command, or a Preview Board/Project Health
aggregation - both read-only, both bounded, neither launches a GUI)
explicitly asks for it.

See `docs/engine-registry.md`.
"""

from __future__ import annotations

import importlib.metadata
import plistlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

from factory.cad.backend import is_cadquery_available
from factory.export_pipeline import resolve_openscad_executable
from factory.future_cloud_tools import load_future_cloud_tools
from factory.future_local_tools import load_future_local_tools
from factory.slicer.local_slicer_probe import probe_slicers

# ---------------------------------------------------------------------------
# Vocabulary - stable, closed, documented in docs/engine-registry.md
# ---------------------------------------------------------------------------

REGISTRY_VERSION = "1.0.0"

ROADMAP_STATUSES = (
    "core_supported",
    "installed_unqualified",
    "qualified_local",
    "near_term",
    "future",
    "experimental",
    "cloud_gated",
    "human_only",
    "printing_adjacent_disabled",
)

EXECUTION_STATUSES = (
    "implemented",
    "planned",
    "manual_only",
    "unsupported",
    "future",
    "disabled",
    "approval_required",
)

QUALIFICATION_STATUSES = ("qualified", "unqualified", "not_tested", "not_installed", "not_applicable")

LOCAL_OR_CLOUD_VALUES = ("local", "cloud", "hybrid")

# Qualitative only (see docs/engine-registry.md "Capability matrix is
# qualitative, not calibrated") - never a numeric score, never compared
# across tools as if it were one.
SUITABILITY_LEVELS = ("high", "moderate", "low", "not_applicable", "unknown")

# Presentation-only grouping for CLI/Preview Board rendering - distinct
# from the semantic `category`/`subcategory` fields on each record.
DISPLAY_GROUPS = ("design_cad", "cloud", "slicers", "future")

TOOL_IDS = (
    "openscad_stable",
    "openscad_snapshot",
    "cadquery",
    "blender",
    "freecad",
    "meshy",
    "plasticity",
    "autodesk_fusion",
    "onshape",
    "bambu_studio",
    "orcaslicer",
    "prusaslicer",
    "bambu_connect",
)

_VERSION_PROBE_TIMEOUT_SECONDS = 10


# ---------------------------------------------------------------------------
# Static registry - deterministic, hand-authored, no I/O except the two
# already-existing "is this optional dependency importable" checks below
# (never a subprocess, never a filesystem app-bundle scan at this layer).
# ---------------------------------------------------------------------------


def _tool(
    *,
    tool_id: str,
    display_name: str,
    category: str,
    subcategory: str,
    vendor: str,
    display_group: str,
    roadmap_status: str,
    execution_status: str,
    qualification_status: str,
    local_or_cloud: str,
    install_method: str,
    homebrew_token: str | None,
    package_name: str | None,
    cli_available: bool,
    headless_capable: bool,
    gui_only: bool,
    automation_suitability: str,
    network_required: bool,
    account_required: bool,
    possible_monetary_cost: bool,
    capabilities: tuple[str, ...],
    strengths: tuple[str, ...],
    limitations: tuple[str, ...],
    input_types: tuple[str, ...],
    output_types: tuple[str, ...],
    mechanical_design_suitability: str,
    organic_modeling_suitability: str,
    parametric_design_suitability: str,
    dimensional_precision_suitability: str,
    mesh_cleanup_suitability: str,
    assembly_suitability: str,
    slicer_suitability: str,
    validation_requirements: str,
    review_requirements: str,
    licensing_or_provenance_concerns: str,
    cloud_gate_required: bool,
    human_approval_required: bool,
    notes: tuple[str, ...],
) -> dict[str, Any]:
    assert roadmap_status in ROADMAP_STATUSES, roadmap_status
    assert execution_status in EXECUTION_STATUSES, execution_status
    assert qualification_status in QUALIFICATION_STATUSES, qualification_status
    assert local_or_cloud in LOCAL_OR_CLOUD_VALUES, local_or_cloud
    assert display_group in DISPLAY_GROUPS, display_group
    for level in (
        mechanical_design_suitability,
        organic_modeling_suitability,
        parametric_design_suitability,
        dimensional_precision_suitability,
        mesh_cleanup_suitability,
        assembly_suitability,
        slicer_suitability,
    ):
        assert level in SUITABILITY_LEVELS, level

    return {
        "tool_id": tool_id,
        "display_name": display_name,
        "category": category,
        "subcategory": subcategory,
        "vendor": vendor,
        "display_group": display_group,
        "status": roadmap_status,
        "roadmap_status": roadmap_status,
        "execution_status": execution_status,
        "qualification_status": qualification_status,
        "local_or_cloud": local_or_cloud,
        "install_method": install_method,
        "homebrew_token": homebrew_token,
        "package_name": package_name,
        # Dynamic fields - always "unknown"/not-detected until a probe
        # layer (`probe_all_tools()`) explicitly runs and merges its
        # result in. Never guessed here.
        "detected": False,
        "detected_path": None,
        "detected_version": "unknown",
        "detected_channel": "unknown",
        "detected_architecture": "unknown",
        "cli_available": cli_available,
        "headless_capable": headless_capable,
        "gui_only": gui_only,
        "automation_suitability": automation_suitability,
        "network_required": network_required,
        "account_required": account_required,
        "possible_monetary_cost": possible_monetary_cost,
        "capabilities": list(capabilities),
        "strengths": list(strengths),
        "limitations": list(limitations),
        "input_types": list(input_types),
        "output_types": list(output_types),
        "mechanical_design_suitability": mechanical_design_suitability,
        "organic_modeling_suitability": organic_modeling_suitability,
        "parametric_design_suitability": parametric_design_suitability,
        "dimensional_precision_suitability": dimensional_precision_suitability,
        "mesh_cleanup_suitability": mesh_cleanup_suitability,
        "assembly_suitability": assembly_suitability,
        "slicer_suitability": slicer_suitability,
        "validation_requirements": validation_requirements,
        "review_requirements": review_requirements,
        "licensing_or_provenance_concerns": licensing_or_provenance_concerns,
        "cloud_gate_required": cloud_gate_required,
        "human_approval_required": human_approval_required,
        # Always false. Never set true by any code path in this repo.
        "automatic_print_permission": False,
        "notes": list(notes),
        "probe_method": None,
        "probe_status": "not_probed",
        "probe_warnings": [],
    }


def _build_tool_registry() -> dict[str, dict[str, Any]]:
    """Recomputed each call (matching `factory.cad.backend.get_backend_registry()`'s
    own convention) so `cadquery`'s install-state-dependent fields stay
    accurate if the environment changes within a process, and so tests can
    monkeypatch `is_cadquery_available()`."""
    cadquery_available = is_cadquery_available()
    future_local = {t["tool_id"]: t for t in _safe_list_future_local_tools()}
    future_cloud = {t["tool_id"]: t for t in _safe_list_future_cloud_tools()}
    blender_gate = future_local.get("blender", {})
    meshy_gate = future_cloud.get("meshy", {})

    registry = {
        "openscad_stable": _tool(
            tool_id="openscad_stable",
            display_name="OpenSCAD (stable)",
            category="design_cad",
            subcategory="parametric_mechanical",
            vendor="OpenSCAD (open source)",
            display_group="design_cad",
            roadmap_status="core_supported",
            execution_status="implemented",
            qualification_status="not_tested",
            local_or_cloud="local",
            install_method="homebrew_cask",
            homebrew_token="openscad",
            package_name=None,
            cli_available=True,
            headless_capable=True,
            gui_only=False,
            automation_suitability="high",
            network_required=False,
            account_required=False,
            possible_monetary_cost=False,
            capabilities=("scad_source_generation", "cli_stl_export", "parametric_templates"),
            strengths=("measured/parametric parts", "signs/plates/labels/organizers", "scriptable, reproducible geometry"),
            limitations=("no native organic/sculptural modeling", "no assemblies", "text-based CSG can be slow for complex boolean chains"),
            input_types=("scad",),
            output_types=("stl", "off", "csg"),
            mechanical_design_suitability="high",
            organic_modeling_suitability="low",
            parametric_design_suitability="high",
            dimensional_precision_suitability="high",
            mesh_cleanup_suitability="low",
            assembly_suitability="moderate",
            slicer_suitability="not_applicable",
            validation_requirements="factory validate after export, same as every other backend",
            review_requirements="factory review-gate, then human slicer review, before human_approved",
            licensing_or_provenance_concerns="none - open source, no generated-content provenance concern",
            cloud_gate_required=False,
            human_approval_required=False,
            notes=(
                "Implemented since Phase 2 - see `factory generate-openscad` and docs/openscad-generation.md.",
                "This is the channel `factory.export_pipeline.resolve_openscad_executable()` actually resolves today - "
                "it does not distinguish stable vs. snapshot; whichever `openscad` binary is found is treated as this record.",
            ),
        ),
        "openscad_snapshot": _tool(
            tool_id="openscad_snapshot",
            display_name="OpenSCAD (snapshot/development)",
            category="design_cad",
            subcategory="parametric_mechanical",
            vendor="OpenSCAD (open source)",
            display_group="design_cad",
            roadmap_status="experimental",
            execution_status="unsupported",
            qualification_status="not_applicable",
            local_or_cloud="local",
            install_method="homebrew_cask",
            homebrew_token=None,
            package_name=None,
            cli_available=True,
            headless_capable=True,
            gui_only=False,
            automation_suitability="unknown",
            network_required=False,
            account_required=False,
            possible_monetary_cost=False,
            capabilities=("experimental_scad_language_features",),
            strengths=("early access to new OpenSCAD language/manifold-engine features",),
            limitations=("not qualified for Factory use", "not distinguished from stable by this repo's export pipeline today"),
            input_types=("scad",),
            output_types=("stl", "off", "csg"),
            mechanical_design_suitability="unknown",
            organic_modeling_suitability="low",
            parametric_design_suitability="unknown",
            dimensional_precision_suitability="unknown",
            mesh_cleanup_suitability="low",
            assembly_suitability="unknown",
            slicer_suitability="not_applicable",
            validation_requirements="not applicable - no Factory execution path targets this channel yet",
            review_requirements="not applicable - not an execution backend in this phase",
            licensing_or_provenance_concerns="none - open source, same project as stable",
            cloud_gate_required=False,
            human_approval_required=False,
            notes=(
                "No known Homebrew cask token for a separate snapshot build could be verified locally in this phase - "
                "left unset rather than guessed (see docs/engine-registry.md \"Homebrew metadata policy\").",
                "`factory.export_pipeline.resolve_openscad_executable()` has no separate snapshot-channel lookup - "
                "whatever `openscad` binary it finds is always attributed to the `openscad_stable` record, never this one.",
                "Snapshot qualification (a distinct detection path, and a distinct qualification decision) is a Phase 44 concern.",
            ),
        ),
        "cadquery": _tool(
            tool_id="cadquery",
            display_name="CadQuery",
            category="design_cad",
            subcategory="parametric_mechanical",
            vendor="CadQuery (open source)",
            display_group="design_cad",
            roadmap_status="core_supported",
            execution_status="implemented",
            qualification_status="not_tested",
            local_or_cloud="local",
            install_method="python_package",
            homebrew_token=None,
            package_name="cadquery",
            cli_available=False,
            headless_capable=True,
            gui_only=False,
            automation_suitability="high",
            network_required=False,
            account_required=False,
            possible_monetary_cost=False,
            capabilities=("cadquery_source_generation", "step_export", "stl_export"),
            strengths=("fillets/chamfers", "dimensioned mechanical solids", "brackets/adapters/mounts/clips/hinges/enclosures"),
            limitations=("no native organic/sculptural modeling", "optional dependency - this repo never installs it"),
            input_types=("cadquery_py",),
            output_types=("step", "stl"),
            mechanical_design_suitability="high",
            organic_modeling_suitability="low",
            parametric_design_suitability="high",
            dimensional_precision_suitability="high",
            mesh_cleanup_suitability="low",
            assembly_suitability="moderate",
            slicer_suitability="not_applicable",
            validation_requirements="factory validate after export, same as every other backend",
            review_requirements="factory review-gate, then human slicer review, before human_approved",
            licensing_or_provenance_concerns="none - open source, no generated-content provenance concern",
            cloud_gate_required=False,
            human_approval_required=False,
            notes=(
                "Implemented since Phase 7 - see `factory generate-cadquery` and docs/cad-backends.md.",
                "Optional dependency: this repo never installs or upgrades it; commands fail with a clear "
                "message if it isn't already present (see `factory.cad.backend.is_cadquery_available()`).",
                "Writes CadQuery `.py` source (and, on request, STEP) only - STL export from CadQuery source remains a manual, human-run step.",
                f"Currently importable in this environment: {cadquery_available}.",
            ),
        ),
        "blender": _tool(
            tool_id="blender",
            display_name="Blender",
            category="organic_mesh_modeling",
            subcategory="organic_procedural_mesh",
            vendor="Blender Foundation (open source)",
            display_group="design_cad",
            roadmap_status="near_term",
            execution_status="planned",
            qualification_status="not_applicable",
            local_or_cloud="local",
            install_method="homebrew_cask",
            homebrew_token="blender",
            package_name=None,
            cli_available=True,
            headless_capable=True,
            gui_only=False,
            automation_suitability="moderate",
            network_required=False,
            account_required=False,
            possible_monetary_cost=False,
            capabilities=("organic_modeling", "sculpting", "procedural_geometry", "mesh_repair_planning", "modifiers", "rendering"),
            strengths=("organic modeling", "sculptural forms", "characters/collectibles", "procedural geometry", "mesh cleanup/repair", "modifier-based workflows"),
            limitations=(
                "mechanical tolerance/engineering-precision work is a poor fit compared with OpenSCAD/CadQuery/FreeCAD",
                "Python execution inside Blender is an arbitrary-code surface - a future integration must treat scripts as untrusted input",
            ),
            input_types=("blend", "mesh_import"),
            output_types=("stl", "render_image"),
            mechanical_design_suitability="low",
            organic_modeling_suitability="high",
            parametric_design_suitability="moderate",
            dimensional_precision_suitability="moderate",
            mesh_cleanup_suitability="high",
            assembly_suitability="low",
            slicer_suitability="not_applicable",
            validation_requirements="before/after factory validate on any repaired mesh (docs/blender-local-track.md required gate #7)",
            review_requirements="before/after factory render + factory review-gate + human slicer review; never an automatic human_approved (docs/blender-local-track.md)",
            licensing_or_provenance_concerns="none for the tool itself (open source); any Blender-touched part still needs part_manifest.json provenance, per docs/licensing-policy.md",
            cloud_gate_required=False,
            human_approval_required=bool(blender_gate.get("requires_explicit_human_approval", True)),
            notes=(
                "Owned by the (not yet scheduled) Phase 45 'Blender Local Adapter' track - see docs/roadmap.md and docs/blender-local-track.md.",
                "This registry entry only detects a local installation by path (`.app` bundle / PATH binary) - "
                "it never launches Blender, never calls subprocess for it, and never reads a version by executing it "
                "(docs/blender-local-track.md's 'no subprocess call, no headless invocation' rule, preserved in full).",
                f"config/future_local_tools.json gate status: {blender_gate.get('status', 'unknown')!r}, enabled={blender_gate.get('enabled', False)}.",
            ),
        ),
        "freecad": _tool(
            tool_id="freecad",
            display_name="FreeCAD",
            category="design_cad",
            subcategory="parametric_mechanical",
            vendor="FreeCAD (open source)",
            display_group="design_cad",
            roadmap_status="near_term",
            execution_status="unsupported",
            qualification_status="not_applicable",
            local_or_cloud="local",
            install_method="homebrew_cask",
            homebrew_token="freecad",
            package_name=None,
            cli_available=True,
            headless_capable=True,
            gui_only=False,
            automation_suitability="moderate",
            network_required=False,
            account_required=False,
            possible_monetary_cost=False,
            capabilities=("parametric_mechanical_cad", "assemblies", "step_export", "possible_cam_fem_workflows"),
            strengths=("parametric mechanical CAD", "assemblies", "STEP import/export", "engineering workflows"),
            limitations=("not yet integrated as a Factory execution backend", "headless/CLI support not empirically verified by this repo"),
            input_types=("fcstd", "step"),
            output_types=("step", "stl"),
            mechanical_design_suitability="high",
            organic_modeling_suitability="low",
            parametric_design_suitability="high",
            dimensional_precision_suitability="high",
            mesh_cleanup_suitability="moderate",
            assembly_suitability="high",
            slicer_suitability="not_applicable",
            validation_requirements="not applicable - no Factory execution path exists yet",
            review_requirements="not applicable - no Factory execution path exists yet",
            licensing_or_provenance_concerns="none - open source, no generated-content provenance concern",
            cloud_gate_required=False,
            human_approval_required=True,
            notes=(
                "Recognized as a near-term local mechanical/engineering engine per this phase's roadmap amendment - "
                "not yet implemented as a Factory execution backend.",
                "Detected by path only (`.app` bundle / PATH binary) - never executed; headless-CLI capability is a "
                "documented fact about FreeCAD's own architecture, not something this repo has empirically probed.",
                "Execution, qualification, and any gate checklist analogous to docs/blender-local-track.md are future-phase work.",
            ),
        ),
        "meshy": _tool(
            tool_id="meshy",
            display_name="Meshy",
            category="cloud_design",
            subcategory="cloud_generative_mesh",
            vendor="Meshy (third-party, paid, cloud)",
            display_group="cloud",
            roadmap_status="cloud_gated",
            execution_status="approval_required",
            qualification_status="not_applicable",
            local_or_cloud="cloud",
            install_method="cloud_api",
            homebrew_token=None,
            package_name=None,
            cli_available=False,
            headless_capable=False,
            gui_only=False,
            automation_suitability="low",
            network_required=True,
            account_required=True,
            possible_monetary_cost=True,
            capabilities=(
                "text_to_3d_concept",
                "image_to_3d",
                "multi_image_to_3d",
                "meshy_7_family",
                "smart_topology",
                "separated_native_parts",
                "target_polygon_count",
                "3mf_output",
                "multi_color_print",
                "analyze_printability",
                "repair_printability",
                "auto_split",
            ),
            strengths=("organic concept generation", "rapid sculptural/organic concepting from text or reference images"),
            limitations=(
                "mechanical/dimensional precision is low compared with parametric CAD",
                "cloud/paid/API-backed - a fundamentally different trust boundary than any local backend",
                "\"printable\"/repaired output from Meshy is never Factory-validated or human-approved by that fact alone",
            ),
            input_types=("text_prompt", "reference_image"),
            output_types=("mesh_concept", "3mf"),
            mechanical_design_suitability="low",
            organic_modeling_suitability="high",
            parametric_design_suitability="low",
            dimensional_precision_suitability="low",
            mesh_cleanup_suitability="moderate",
            assembly_suitability="low",
            slicer_suitability="not_applicable",
            validation_requirements="factory validate + factory render, same as any other mesh source, before any further step",
            review_requirements="factory review-gate, then human slicer review, before human_approved - Meshy output is never pre-approved",
            licensing_or_provenance_concerns=(
                "commercial-use licensing, asset ownership, and reference-image privacy all require review before use - "
                "see docs/meshy-approval-gate.md's full checklist"
            ),
            cloud_gate_required=True,
            human_approval_required=bool(meshy_gate.get("requires_explicit_human_approval", True)),
            notes=(
                "Not called, authenticated to, or contacted by this registry - `enabled` is read from "
                "config/future_cloud_tools.json only.",
                f"config/future_cloud_tools.json gate status: {meshy_gate.get('status', 'unknown')!r}, enabled={meshy_gate.get('enabled', False)}.",
                "Meshy-generated or Meshy-repaired output != Factory validated != human approved - three separate facts, "
                "never collapsed into one (see docs/meshy-approval-gate.md).",
                "Execution is Phase 47 ('Meshy Concept & Print-Preparation Gateway'); the cloud/cost/license approval gate "
                "itself is Phase 46 - both strictly after this registry phase.",
            ),
        ),
        "plasticity": _tool(
            tool_id="plasticity",
            display_name="Plasticity",
            category="design_cad",
            subcategory="direct_nurbs_modeling",
            vendor="Plasticity (commercial, local desktop app)",
            display_group="future",
            roadmap_status="future",
            execution_status="future",
            qualification_status="not_applicable",
            local_or_cloud="local",
            install_method="homebrew_cask",
            homebrew_token="plasticity",
            package_name=None,
            cli_available=False,
            headless_capable=False,
            gui_only=True,
            automation_suitability="low",
            network_required=False,
            account_required=False,
            possible_monetary_cost=True,
            capabilities=("direct_nurbs_modeling", "hard_surface_concept_modeling"),
            strengths=("direct/NURBS modeling", "hard-surface product-design concepting"),
            limitations=("GUI-only, human-oriented tool - not automatable", "not implemented, integrated, or scheduled in this repo"),
            input_types=("gui_only",),
            output_types=("step", "obj"),
            mechanical_design_suitability="moderate",
            organic_modeling_suitability="moderate",
            parametric_design_suitability="low",
            dimensional_precision_suitability="moderate",
            mesh_cleanup_suitability="low",
            assembly_suitability="low",
            slicer_suitability="not_applicable",
            validation_requirements="not applicable - no Factory execution path exists or is planned yet",
            review_requirements="not applicable - permanent future/experimental, human-oriented entry only",
            licensing_or_provenance_concerns="commercial license required for use; not reviewed in this phase",
            cloud_gate_required=False,
            human_approval_required=True,
            notes=(
                "Permanent future/experimental registry entry per this phase's roadmap amendment - never automated, "
                "never installed, never launched by this repo.",
                "Detected by path only (`.app` bundle / PATH binary); never executed.",
            ),
        ),
        "autodesk_fusion": _tool(
            tool_id="autodesk_fusion",
            display_name="Autodesk Fusion",
            category="design_cad",
            subcategory="professional_mechanical_cad",
            vendor="Autodesk (commercial, hybrid local/cloud)",
            display_group="future",
            roadmap_status="future",
            execution_status="future",
            qualification_status="not_applicable",
            local_or_cloud="hybrid",
            install_method="vendor_installer",
            homebrew_token=None,
            package_name=None,
            cli_available=False,
            headless_capable=False,
            gui_only=True,
            automation_suitability="low",
            network_required=True,
            account_required=True,
            possible_monetary_cost=True,
            capabilities=("professional_mechanical_cad", "assemblies", "cam", "cae"),
            strengths=("professional mechanical CAD", "assemblies", "CAM/CAE ecosystem"),
            limitations=("requires an Autodesk account/subscription", "cloud-dependent for full functionality", "significant automation complexity for any future integration"),
            input_types=("gui_only",),
            output_types=("step", "f3d"),
            mechanical_design_suitability="high",
            organic_modeling_suitability="low",
            parametric_design_suitability="high",
            dimensional_precision_suitability="high",
            mesh_cleanup_suitability="low",
            assembly_suitability="high",
            slicer_suitability="not_applicable",
            validation_requirements="not applicable - no Factory execution path exists or is planned yet",
            review_requirements="not applicable - permanent future external engine entry only",
            licensing_or_provenance_concerns="commercial account/subscription and cloud data-handling terms apply; not reviewed in this phase",
            cloud_gate_required=True,
            human_approval_required=True,
            notes=(
                "Permanent future external-engine registry entry per this phase's roadmap amendment - no Autodesk API "
                "integration, no authentication, no launch anywhere in this repo.",
                "Detected by path only (`.app` bundle / PATH binary), best-effort; never executed.",
            ),
        ),
        "onshape": _tool(
            tool_id="onshape",
            display_name="Onshape",
            category="cloud_design",
            subcategory="cloud_parametric_mechanical",
            vendor="PTC/Onshape (commercial, cloud-only)",
            display_group="future",
            roadmap_status="future",
            execution_status="future",
            qualification_status="not_applicable",
            local_or_cloud="cloud",
            install_method="cloud_api",
            homebrew_token=None,
            package_name=None,
            cli_available=False,
            headless_capable=False,
            gui_only=True,
            automation_suitability="low",
            network_required=True,
            account_required=True,
            possible_monetary_cost=True,
            capabilities=("cloud_parametric_mechanical_cad", "collaboration", "rest_api_potential"),
            strengths=("cloud CAD", "real-time collaboration", "parametric mechanical design", "a documented REST API for a possible future integration"),
            limitations=("cloud-only - no local/offline mode", "requires an account/subscription", "no local installation to detect at all"),
            input_types=("web_only",),
            output_types=("step", "parasolid"),
            mechanical_design_suitability="high",
            organic_modeling_suitability="low",
            parametric_design_suitability="high",
            dimensional_precision_suitability="high",
            mesh_cleanup_suitability="low",
            assembly_suitability="high",
            slicer_suitability="not_applicable",
            validation_requirements="not applicable - no Factory execution path exists or is planned yet",
            review_requirements="not applicable - permanent future cloud CAD engine entry only",
            licensing_or_provenance_concerns="commercial account/subscription and cloud data-handling terms apply; not reviewed in this phase",
            cloud_gate_required=True,
            human_approval_required=True,
            notes=(
                "Permanent future cloud-CAD registry entry per this phase's roadmap amendment - no network contact, "
                "no authentication, anywhere in this repo.",
                "Purely a web application - there is no local binary or `.app` bundle for this entry to detect; "
                "`detected` stays `False` and `qualification_status` stays `not_applicable` permanently.",
            ),
        ),
        "bambu_studio": _tool(
            tool_id="bambu_studio",
            display_name="Bambu Studio",
            category="slicer_review",
            subcategory="fdm_slicer",
            vendor="Bambu Lab",
            display_group="slicers",
            roadmap_status="human_only",
            execution_status="manual_only",
            qualification_status="not_tested",
            local_or_cloud="local",
            install_method="homebrew_cask",
            homebrew_token="bambu-studio",
            package_name=None,
            cli_available=False,
            headless_capable=False,
            gui_only=True,
            automation_suitability="low",
            network_required=False,
            account_required=False,
            possible_monetary_cost=False,
            capabilities=("slicing", "ams_multi_material", "printer_profile_management", "plate_layout"),
            strengths=("first-party Bambu Lab printer profiles", "AMS/multi-material color mapping", "the slicer this Factory's example printer profiles target"),
            limitations=("GUI-only human tool - this repo never automates it", "Bambu-printer-focused profile ecosystem"),
            input_types=("stl", "3mf"),
            output_types=("gcode",),
            mechanical_design_suitability="not_applicable",
            organic_modeling_suitability="not_applicable",
            parametric_design_suitability="not_applicable",
            dimensional_precision_suitability="not_applicable",
            mesh_cleanup_suitability="not_applicable",
            assembly_suitability="not_applicable",
            slicer_suitability="high",
            validation_requirements="not applicable - this repo never invokes a slicer",
            review_requirements="the destination of the existing manual slicer-review workflow (docs/slicer-review-workflow.md); a human opens the review package here themselves",
            licensing_or_provenance_concerns="none tracked - free, vendor-distributed slicer",
            cloud_gate_required=False,
            human_approval_required=False,
            notes=(
                "Detected via `factory.slicer.local_slicer_probe.probe_slicers()` - never re-implemented here.",
                "This repo never launches Bambu Studio, never slices, and never generates G-code; a human opens the "
                "existing slicer-review package themselves, per docs/slicer-review-workflow.md.",
            ),
        ),
        "orcaslicer": _tool(
            tool_id="orcaslicer",
            display_name="OrcaSlicer",
            category="slicer_review",
            subcategory="fdm_slicer",
            vendor="OrcaSlicer (open source, Bambu Studio fork)",
            display_group="slicers",
            roadmap_status="human_only",
            execution_status="manual_only",
            qualification_status="not_tested",
            local_or_cloud="local",
            install_method="homebrew_cask",
            homebrew_token="orcaslicer",
            package_name=None,
            cli_available=False,
            headless_capable=False,
            gui_only=True,
            automation_suitability="low",
            network_required=False,
            account_required=False,
            possible_monetary_cost=False,
            capabilities=("slicing", "calibration_profiles", "multi_material", "printer_profile_management"),
            strengths=("broad printer-profile support", "advanced calibration tooling", "multi-material support", "active open-source development"),
            limitations=("GUI-only human tool - this repo never automates it",),
            input_types=("stl", "3mf"),
            output_types=("gcode",),
            mechanical_design_suitability="not_applicable",
            organic_modeling_suitability="not_applicable",
            parametric_design_suitability="not_applicable",
            dimensional_precision_suitability="not_applicable",
            mesh_cleanup_suitability="not_applicable",
            assembly_suitability="not_applicable",
            slicer_suitability="high",
            validation_requirements="not applicable - this repo never invokes a slicer",
            review_requirements="the destination of the existing manual slicer-review workflow (docs/slicer-review-workflow.md); a human opens the review package here themselves",
            licensing_or_provenance_concerns="none tracked - free, open-source slicer",
            cloud_gate_required=False,
            human_approval_required=False,
            notes=(
                "Detected via `factory.slicer.local_slicer_probe.probe_slicers()` - never re-implemented here.",
                "This repo never launches OrcaSlicer, never slices, and never generates G-code.",
            ),
        ),
        "prusaslicer": _tool(
            tool_id="prusaslicer",
            display_name="PrusaSlicer",
            category="slicer_review",
            subcategory="fdm_slicer",
            vendor="Prusa Research",
            display_group="slicers",
            roadmap_status="human_only",
            execution_status="manual_only",
            qualification_status="not_tested",
            local_or_cloud="local",
            install_method="homebrew_cask",
            homebrew_token="prusaslicer",
            package_name=None,
            cli_available=False,
            headless_capable=False,
            gui_only=True,
            automation_suitability="low",
            network_required=False,
            account_required=False,
            possible_monetary_cost=False,
            capabilities=("slicing", "printer_profile_management", "filament_profile_management"),
            strengths=("broad generic printer/filament compatibility", "long-established FDM review workflow", "large community profile ecosystem"),
            limitations=("GUI-only human tool - this repo never automates it",),
            input_types=("stl", "3mf"),
            output_types=("gcode",),
            mechanical_design_suitability="not_applicable",
            organic_modeling_suitability="not_applicable",
            parametric_design_suitability="not_applicable",
            dimensional_precision_suitability="not_applicable",
            mesh_cleanup_suitability="not_applicable",
            assembly_suitability="not_applicable",
            slicer_suitability="high",
            validation_requirements="not applicable - this repo never invokes a slicer",
            review_requirements="the destination of the existing manual slicer-review workflow (docs/slicer-review-workflow.md); a human opens the review package here themselves",
            licensing_or_provenance_concerns="none tracked - free slicer",
            cloud_gate_required=False,
            human_approval_required=False,
            notes=(
                "Detected via `factory.slicer.local_slicer_probe.probe_slicers()` - never re-implemented here.",
                "This repo never launches PrusaSlicer, never slices, and never generates G-code.",
            ),
        ),
        "bambu_connect": _tool(
            tool_id="bambu_connect",
            display_name="Bambu Connect",
            category="printing_adjacent",
            subcategory="printer_link_utility",
            vendor="Bambu Lab",
            display_group="future",
            roadmap_status="printing_adjacent_disabled",
            execution_status="disabled",
            qualification_status="not_applicable",
            local_or_cloud="local",
            install_method="homebrew_cask",
            homebrew_token=None,
            package_name=None,
            cli_available=False,
            headless_capable=False,
            gui_only=True,
            automation_suitability="low",
            network_required=True,
            account_required=False,
            possible_monetary_cost=False,
            capabilities=("printer_link_utility",),
            strengths=("bridges a slicer's print job to a local-network Bambu printer",),
            limitations=("printing-adjacent only - out of scope for every phase through this one", "not integrated, not authenticated to, not launched"),
            input_types=("gcode", "3mf"),
            output_types=("printer_job",),
            mechanical_design_suitability="not_applicable",
            organic_modeling_suitability="not_applicable",
            parametric_design_suitability="not_applicable",
            dimensional_precision_suitability="not_applicable",
            mesh_cleanup_suitability="not_applicable",
            assembly_suitability="not_applicable",
            slicer_suitability="not_applicable",
            validation_requirements="not applicable - registry-only entry, no execution path",
            review_requirements="not applicable - printing_adjacent_disabled permanently in this phase",
            licensing_or_provenance_concerns="none reviewed - out of scope",
            cloud_gate_required=False,
            human_approval_required=True,
            notes=(
                "Registry-only, future/disabled entry - no integration, no launch, no printer communication, no "
                "authentication, anywhere in this repo.",
                "`automatic_print_permission` is `False`, exactly like every other tool here, with no exception.",
                "Detected by path only, best-effort, if a known local app bundle exists; never executed.",
            ),
        ),
    }
    assert set(registry.keys()) == set(TOOL_IDS)
    return registry


def _safe_list_future_local_tools() -> list[dict[str, Any]]:
    try:
        from factory.future_local_tools import list_future_local_tools

        return list_future_local_tools()
    except Exception:
        return []


def _safe_list_future_cloud_tools() -> list[dict[str, Any]]:
    try:
        from factory.future_cloud_tools import list_future_cloud_tools

        return list_future_cloud_tools()
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Probing - read-only local environment discovery. Every probe function
# is wrapped so one tool's probe failure can never abort the others (see
# `probe_all_tools()`).
# ---------------------------------------------------------------------------


def _read_app_bundle_version(app_path: str) -> str | None:
    """Read `CFBundleShortVersionString` from a `.app` bundle's `Info.plist`.

    A plain file read (`plistlib`) - never executes, launches, or even
    opens the application itself. Returns `None` on any error (missing
    file, malformed plist, missing key) - never raises.
    """
    plist_path = Path(app_path) / "Contents" / "Info.plist"
    try:
        with open(plist_path, "rb") as f:
            data = plistlib.load(f)
    except Exception:
        return None
    version = data.get("CFBundleShortVersionString") or data.get("CFBundleVersion")
    return str(version) if version else None


def _probe_app_or_path_binary(app_paths: tuple[str, ...], path_binary: str | None) -> dict[str, Any]:
    """Same read-only technique as `factory.slicer.local_slicer_probe.probe_slicers()`
    and `factory.export_pipeline.resolve_openscad_executable()`: a known
    `.app` bundle path, then a `PATH` binary. Never launches anything."""
    for app_path in app_paths:
        if Path(app_path).is_dir():
            return {
                "detected": True,
                "detected_path": app_path,
                "detected_version": _read_app_bundle_version(app_path) or "unknown",
                "probe_method": "applications_folder",
                "probe_status": "detected",
                "probe_warnings": [],
            }
    if path_binary:
        found = shutil.which(path_binary)
        if found:
            return {
                "detected": True,
                "detected_path": found,
                "detected_version": "unknown",
                "probe_method": "path_binary",
                "probe_status": "detected",
                "probe_warnings": [],
            }
    return {
        "detected": False,
        "detected_path": None,
        "detected_version": "unknown",
        "probe_method": None,
        "probe_status": "not_installed",
        "probe_warnings": [],
    }


_APP_BUNDLE_CANDIDATES: dict[str, tuple[tuple[str, ...], str | None]] = {
    "blender": (("/Applications/Blender.app",), "blender"),
    "freecad": (("/Applications/FreeCAD.app",), "freecad"),
    "plasticity": (("/Applications/Plasticity.app",), None),
    "autodesk_fusion": (("/Applications/Autodesk Fusion.app", "/Applications/Autodesk Fusion 360.app"), None),
    "bambu_connect": (("/Applications/Bambu Connect.app",), None),
}


def _probe_openscad(include_version_subprocess: bool) -> dict[str, Any]:
    """Reuses `factory.export_pipeline.resolve_openscad_executable()` for
    path discovery - never a second lookup table. Only calls `openscad
    --version` (the exact safe, timeout-bounded pattern
    `factory.export_pipeline._probe_tool_version()` already uses) when
    `include_version_subprocess` is `True` - i.e. only from the explicit
    `factory engines probe` CLI command, never from Preview Board or
    Project Health aggregation."""
    executable = resolve_openscad_executable()
    if not executable:
        return {
            "detected": False,
            "detected_path": None,
            "detected_version": "unknown",
            "detected_channel": "unknown",
            "probe_method": None,
            "probe_status": "not_installed",
            "probe_warnings": [],
        }

    version = "unknown"
    warnings: list[str] = []
    if include_version_subprocess:
        try:
            completed = subprocess.run(
                [executable, "--version"],
                capture_output=True,
                text=True,
                timeout=_VERSION_PROBE_TIMEOUT_SECONDS,
            )
            text = (completed.stdout or completed.stderr or "").strip()
            version = text or "unknown"
        except (OSError, subprocess.TimeoutExpired) as exc:
            warnings.append(f"version probe failed: {exc}")
    else:
        warnings.append("version not probed (path-detection-only mode) - see docs/engine-registry.md")

    return {
        "detected": True,
        "detected_path": executable,
        "detected_version": version,
        "detected_channel": "stable",
        "probe_method": "applications_folder_or_path",
        "probe_status": "detected",
        "probe_warnings": warnings,
    }


def _probe_cadquery() -> dict[str, Any]:
    """Reuses `factory.cad.backend.is_cadquery_available()` - never a
    second importability check. `importlib.metadata.version()` reads
    installed package metadata only; it never imports or executes the
    `cadquery` package itself."""
    if not is_cadquery_available():
        return {
            "detected": False,
            "detected_path": None,
            "detected_version": "unknown",
            "probe_method": None,
            "probe_status": "not_installed",
            "probe_warnings": [],
        }
    try:
        version = importlib.metadata.version("cadquery")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    return {
        "detected": True,
        "detected_path": None,
        "detected_version": version,
        "probe_method": "importlib_metadata",
        "probe_status": "detected",
        "probe_warnings": [],
    }


_SLICER_TOOL_ID_BY_NAME = {
    "Bambu Studio": "bambu_studio",
    "OrcaSlicer": "orcaslicer",
    "PrusaSlicer": "prusaslicer",
}


def _probe_slicer_results() -> dict[str, dict[str, Any]]:
    """Reuses `factory.slicer.local_slicer_probe.probe_slicers()` verbatim -
    never a second slicer-detection implementation."""
    by_tool_id: dict[str, dict[str, Any]] = {}
    for result in probe_slicers():
        tool_id = _SLICER_TOOL_ID_BY_NAME.get(result["name"])
        if not tool_id:
            continue
        by_tool_id[tool_id] = {
            "detected": result["found"],
            "detected_path": result["path"],
            "detected_version": "unknown",
            "probe_method": result["method"],
            "probe_status": "detected" if result["found"] else "not_installed",
            "probe_warnings": [],
        }
    return by_tool_id


def probe_all_tools(*, include_version_subprocess: bool = False) -> dict[str, dict[str, Any]]:
    """Read-only local environment discovery for every tool in
    `TOOL_IDS`. Never installs, upgrades, launches a GUI application,
    executes Blender/FreeCAD/Plasticity/Fusion/any slicer, calls Meshy or
    Onshape, or contacts a network/printer.

    A per-tool probe failure is informational only and never aborts the
    rest of the registry (each tool's probe runs inside its own
    `try/except`).

    `include_version_subprocess=True` additionally runs the single
    OpenSCAD `--version` probe described in `_probe_openscad()`'s
    docstring - reserved for the explicit `factory engines probe` CLI
    command. Preview Board and Project Health aggregation always pass
    `False` (the default) so board/health generation never spawns a
    subprocess.
    """
    slicer_results = _probe_slicer_results()
    results: dict[str, dict[str, Any]] = {}

    for tool_id in TOOL_IDS:
        try:
            if tool_id == "openscad_stable":
                results[tool_id] = _probe_openscad(include_version_subprocess)
            elif tool_id == "openscad_snapshot":
                results[tool_id] = {
                    "detected": False,
                    "detected_path": None,
                    "detected_version": "unknown",
                    "detected_channel": "snapshot",
                    "probe_method": None,
                    "probe_status": "not_applicable",
                    "probe_warnings": ["no separate snapshot-channel detection path exists yet - see docs/engine-registry.md"],
                }
            elif tool_id == "cadquery":
                results[tool_id] = _probe_cadquery()
            elif tool_id in slicer_results:
                results[tool_id] = slicer_results[tool_id]
            elif tool_id == "onshape":
                results[tool_id] = {
                    "detected": False,
                    "detected_path": None,
                    "detected_version": "unknown",
                    "probe_method": None,
                    "probe_status": "not_applicable",
                    "probe_warnings": ["cloud-only tool - no local application exists to detect"],
                }
            elif tool_id == "meshy":
                results[tool_id] = {
                    "detected": False,
                    "detected_path": None,
                    "detected_version": "unknown",
                    "probe_method": None,
                    "probe_status": "not_applicable",
                    "probe_warnings": ["cloud-only tool - never contacted; no local application exists to detect"],
                }
            elif tool_id in _APP_BUNDLE_CANDIDATES:
                app_paths, path_binary = _APP_BUNDLE_CANDIDATES[tool_id]
                results[tool_id] = _probe_app_or_path_binary(app_paths, path_binary)
            else:
                results[tool_id] = {
                    "detected": False,
                    "detected_path": None,
                    "detected_version": "unknown",
                    "probe_method": None,
                    "probe_status": "not_applicable",
                    "probe_warnings": [],
                }
        except Exception as exc:  # a single tool's probe must never abort the rest
            results[tool_id] = {
                "detected": False,
                "detected_path": None,
                "detected_version": "unknown",
                "probe_method": None,
                "probe_status": "probe_failed",
                "probe_warnings": [f"probe raised {type(exc).__name__}: {exc}"],
            }

    return results


def get_tool_registry(*, probe: bool = False, include_version_subprocess: bool = False) -> dict[str, dict[str, Any]]:
    """The canonical tool registry, optionally merged with a fresh probe result.

    `probe=False` (the default): the static registry only - every
    `detected*` field stays at its safe "not probed yet" default. Never
    invokes a subprocess, never scans the filesystem for an installed
    application, never contacts a network. `probe=True`: also runs
    `probe_all_tools()` and merges its result into each record's
    `detected*`/`probe_*` fields (and downgrades `qualification_status`
    from `not_tested` to `not_installed` when a tool that should be
    locally installed for Factory use was not detected - never upgrades
    it to `qualified`, which stays exclusively Phase 44's decision).
    """
    registry = _build_tool_registry()
    if not probe:
        return registry

    probe_results = probe_all_tools(include_version_subprocess=include_version_subprocess)
    for tool_id, record in registry.items():
        result = probe_results.get(tool_id, {})
        record.update({k: v for k, v in result.items() if k in record})
        if record["qualification_status"] == "not_tested" and result.get("probe_status") == "not_installed":
            record["qualification_status"] = "not_installed"
    return registry


# ---------------------------------------------------------------------------
# Aggregation - compact summaries for CLI/Preview Board/Project Health.
# Never recomputes readiness, never duplicates any of the summaries it
# consumes elsewhere in the Factory pipeline.
# ---------------------------------------------------------------------------


def _build_summary(registry: dict[str, dict[str, Any]]) -> dict[str, Any]:
    core_local = [t for t in registry.values() if t["roadmap_status"] == "core_supported" and t["local_or_cloud"] == "local"]
    slicers = [t for t in registry.values() if t["category"] == "slicer_review"]
    near_term = [t for t in registry.values() if t["roadmap_status"] == "near_term"]
    cloud = [t for t in registry.values() if t["local_or_cloud"] == "cloud"]
    future = [t for t in registry.values() if t["roadmap_status"] in ("future", "printing_adjacent_disabled", "experimental")]

    return {
        "tool_count": len(registry),
        "core_local_tools_total": len(core_local),
        "core_local_tools_detected": sum(1 for t in core_local if t["detected"]),
        "slicers_total": len(slicers),
        "slicers_detected": sum(1 for t in slicers if t["detected"]),
        "near_term_tools_total": len(near_term),
        "near_term_tools_detected": sum(1 for t in near_term if t["detected"]),
        "cloud_tools_total": len(cloud),
        "cloud_tools_gated": sum(1 for t in cloud if t["cloud_gate_required"]),
        "future_tools_total": len(future),
    }


def summarize_engine_registry(*, probe: bool = False, include_version_subprocess: bool = False) -> dict[str, Any]:
    """The full `{registry_version, categories, tools, summary, safety}`
    JSON contract `factory engines [--json]`/`factory engines probe
    [--json]` returns. Deterministic given the same local environment;
    parses cleanly; contains no console text.
    """
    registry = get_tool_registry(probe=probe, include_version_subprocess=include_version_subprocess)
    return {
        "registry_version": REGISTRY_VERSION,
        "categories": list(DISPLAY_GROUPS),
        "tools": registry,
        "summary": _build_summary(registry),
        "safety": {
            "installed_or_modified_tools": False,
            "launched_gui_apps": False,
            "network_used": False,
            "printer_contacted": False,
            "automatic_print_allowed": False,
        },
    }


def summarize_tool_environment(*, probe: bool = True) -> dict[str, Any]:
    """Compact, read-only tool-environment summary for `factory.project_health`'s
    additive `tool_environment_summary` field and
    `factory.preview_board`'s "Tool Environment" section - both consume
    this instead of re-deriving anything from `get_tool_registry()`
    themselves.

    `probe=True` uses `probe_all_tools(include_version_subprocess=False)`
    (path/importlib detection only - never a subprocess), matching this
    phase's "no probing that launches GUI, and no unnecessary subprocess"
    rule for automatic board/health generation.
    """
    registry = get_tool_registry(probe=probe, include_version_subprocess=False)
    summary = _build_summary(registry)
    return {
        "core_local_tools_available": f"{summary['core_local_tools_detected']}/{summary['core_local_tools_total']}",
        "slicers_detected": summary["slicers_detected"],
        "near_term_engines_unqualified": summary["near_term_tools_total"],
        "cloud_engines_gated": summary["cloud_tools_gated"],
    }

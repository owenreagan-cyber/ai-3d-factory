"""factory CLI - local-first 3D print project assistant.

Phase 0/1: create, organize, validate, preview, and package projects for
human slicer review. Phase 2: local OpenSCAD source generation helpers.
No printing, no cloud calls. See AGENT.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.markup import escape as _rich_escape

from factory import project_store
from factory.cad import cadquery_backend
from factory.cad.router import route_cad
from factory.design_intent_check import check_design_intent_manufacturability, summarize_design_intent
from factory.examples_library import UnknownExampleError, get_example, list_examples
from factory.future_cloud_tools import list_future_cloud_tools
from factory.future_local_tools import list_future_local_tools
from factory.manufacturing import knowledge
from factory.manufacturing.check import check_manufacturing_knowledge_base
from factory.manufacturing.inspect import (
    UnknownAccessoryError,
    UnknownMaterialError,
    UnknownPrinterError,
    fleet_summary,
    get_accessory_or_raise,
    get_material_or_raise,
    get_printer_or_raise,
    list_accessories,
    list_materials,
    list_printers,
)
from factory.manufacturing.manifest import compute_assembly_intent
from factory.manufacturing.selection import (
    NEW_STATUS_AFTER_SELECTION,
    BuildPlanNotFoundError,
    UnknownManufacturingOptionError,
    choose_manufacturing_option,
    list_manufacturing_options,
)
from factory.openscad.generate import GeneratedFileExistsError, ProjectNotInitializedError, generate_openscad
from factory.openscad.templates import ALLOWED_TEMPLATES
from factory.planner import plan_from_brief_path
from factory.design_orchestrator import evaluate_readiness_for_path
from factory.generation_gate import evaluate_generation_gate_for_path, run_generation, write_generation_receipt
from factory.export_pipeline import (
    UnsafePathError,
    build_artifact_registry,
    evaluate_export_pipeline_for_path,
    run_export_pipeline,
)
from factory.slicer_readiness import (
    ApprovalNotAllowedError,
    PackageCollisionError,
    PackageNotAllowedError,
    create_review_package,
    evaluate_slicer_readiness_for_path,
    record_approval,
)
from factory.manual_review_workspace import (
    WorkspaceCollisionError,
    WorkspaceNotAllowedError,
    create_manual_review_workspace,
    evaluate_manual_review_workspace_for_path,
)
from factory.slicer_intelligence import evaluate_slicer_intelligence_for_path
from factory.slicer_history import compare_slicer_analysis, read_analysis_history, save_analysis_snapshot
from factory.project_timeline import get_project_timeline_for_path
from factory.artifact_history import (
    UnknownVersionError,
    build_rollback_plan,
    diff_artifact_versions,
    get_artifact_history_for_path,
)
from factory.project_health import evaluate_project_health_for_path
from factory import engine_registry
from factory.engine_registry import summarize_engine_registry
from factory.tool_qualification import build_qualification_report, UnknownToolError
from factory.blender_adapter import build_blender_report
from factory.blender_gate import evaluate_blender_execution_gate
from factory.blender_adaptation import (
    build_adaptation_execution_plan,
    build_safety_block as build_blender_adaptation_safety_block,
    run_organic_cleanup_workflow as run_blender_organic_cleanup_workflow,
)
from factory.hybrid_workflow import assess_artifact_file, build_adaptation_plan
from factory.cad_augmentation import (
    build_augmentation_plan,
    build_safety_block as build_cad_augmentation_safety_block,
    run_organic_mechanical_augmentation,
)
from factory.design_review import (
    build_safety_block as build_design_review_safety_block,
    evaluate_design_review,
    save_design_review_report,
)
from factory.manufacturing_readiness import (
    build_safety_block as build_manufacturing_readiness_safety_block,
    evaluate_manufacturing_readiness,
)
from factory.meshy_approval import (
    MeshyPolicyError,
    build_meshy_approval_plan,
    evaluate_meshy_gate,
    evaluate_meshy_phase47_readiness,
    record_meshy_policy_approval,
    revoke_meshy_policy_approval,
)
from factory.meshy_adapter import (
    build_safety_block as build_meshy_adapter_safety_block,
    plan_text_to_3d_request,
    run_mock_text_to_3d_request,
    summarize_mock_adapter_state,
)
from factory.meshy_models import DEFAULT_AI_MODEL, KNOWN_AI_MODELS, REQUEST_MODES, compute_prompt_hash
from factory.meshy_live_adapter import plan_live_text_to_3d_request, run_live_text_to_3d_request
from factory.meshy_live_approval import (
    ApprovalError,
    create_one_shot_approval,
    load_approvals,
    revoke_approval,
)
from factory.meshy_ledger import LedgerError, SpendLedger
from factory.preview_board import VISUAL_READINESS_STATES, discover_projects, write_preview_board
from factory.project_inspection import summarize_project
from factory.preview_package import gather_preview_data, preview_package_paths, write_preview_package
from factory.previews.render_preview import render_preview
from factory.brief_generator import (
    BriefAlreadyExistsError,
    MalformedExistingBriefError,
    MalformedIntakeSummaryError,
    ProjectDirectoryNotFoundError as DraftProjectDirectoryNotFoundError,
    generate_draft,
    load_existing_brief,
    load_intake_summary_from_path,
    merge_draft_brief,
    write_draft_brief,
    write_merged_brief,
)
from factory.project_intake import analyze as analyze_intake
from factory.reference_board import (
    ATTACHED_TO_VALUES,
    LICENSES,
    SOURCE_TYPES,
    USAGE_INTENTS,
    MalformedReferenceBoardError,
    ProjectDirectoryNotFoundError,
    add_reference,
    check_reference_board_json_is_valid,
    init_reference_board,
    normalize_references,
    summarize_reference_board,
)
from factory.render_coverage import build_text_report, compute_render_coverage, plan_render_commands
from factory.review_gate import evaluate_review_gate
from factory.slicer.local_slicer_probe import probe_slicers
from factory.validators.mesh_validate import validate_mesh
from factory.validators.multipart_check import check_manifest

app = typer.Typer(
    name="factory",
    help="Local-first assistant for creating, validating, previewing, and packaging 3D print projects for human slicer review.",
    no_args_is_help=True,
)
console = Console()

AVAILABLE_COMMANDS = (
    "status",
    "init-project <name>",
    "plan <brief.json>",
    "list-options <project_dir>",
    "choose-option <project_dir> <option_id>",
    "route-cad <project_dir>",
    "list-printers",
    "show-printer <printer_id>",
    "list-accessories",
    "show-accessory <accessory_id>",
    "list-materials",
    "show-material <material_id>",
    "fleet-summary",
    "check-manufacturing",
    "generate-openscad <project_dir> --template <name> [--text ...] [--force]",
    "generate-cadquery <project_dir> --template <name> [--length-mm ...] [--force]",
    "validate <mesh_file>",
    "render <mesh_file>",
    "render-coverage <project_dir> [--json]",
    "plan-renders <project_dir>",
    "preview-index <project_dir>",
    "preview-project <project_dir>",
    "preview-board <projects_root> [--output <path>] [--format json|html|both]",
    "review-gate <project_dir> [--json]",
    "inspect-slicer",
    "report <project_dir>",
    "list-examples",
    "show-example <example_name>",
    "check-future-tools",
    "check-local-tools",
    "check-design-intent <brief_or_concept_brief_json> [--json]",
    "reference-board init <project_dir> [--force]",
    "reference-board show <project_dir> [--json]",
    "reference-board validate <project_dir> [--json]",
    "reference-board list <project_dir> [--json]",
    "reference-board add --project <project_dir> --title <title> [--url ...] [--type ...] [--license ...] [--usage ...] [--attached-to ...] [--notes ...]",
    "intake analyze <project_dir_or_text_or_markdown_file> [--json]",
    "intake suggest-brief <project_dir_or_text_or_markdown_or_intake_json> [--json] [--write] [--force] [--update]",
    "readiness <project_dir_or_projects_root_or_text_or_markdown_file> [--json]",
    "generate-from-readiness <project_dir_or_text_or_markdown_file> [--confirm-generate] [--json]",
    "export-from-cad <project_dir> [--confirm-export] [--json] [--source ...] [--output-dir ...] "
    "[--overwrite-stl] [--validate] [--render] [--all] [--resume]",
    "slicer-readiness <project_dir> [--json] [--create-package] [--confirm-package] [--output-dir ...] "
    "[--approve] [--approval-note ...] [--refresh] [--include-warnings] [--force-package]",
    "review-workspace <project_dir> [--json] [--create-workspace] [--confirm-workspace] [--output-dir ...] "
    "[--force-workspace]",
    "slicer-inspect <project_dir> [--json] [--history] [--compare] [--save-analysis]",
    "timeline <project_dir> [--json]",
    "artifact-history <project_dir> [--json]",
    "artifact-diff <project_dir> --from VERSION --to VERSION [--json]",
    "artifact-rollback-plan <project_dir> --to VERSION [--json]",
    "health <project_dir> [--json] [--verbose]",
    "engines [--json]",
    "engines probe [--json]",
    "engines qualify [<tool_id>] [--json] [--verbose]",
    "blender inspect [--json]",
    "blender qualify [--confirm-fixture] [--json] [--verbose]",
    "meshy status [--json]",
    "meshy policy [--json]",
    "meshy approval-status [--json]",
    "meshy approve-policy --ack-cost --ack-license --ack-privacy --ack-provenance [--approved-by NAME]",
    "meshy revoke-policy [--reason TEXT]",
    "meshy approval-plan [--json]",
    "meshy plan --prompt TEXT [--model MODEL] [--mode preview|refine] [--project PATH] [--json]",
    "meshy mock-run --prompt TEXT --confirm-mock [--model MODEL] [--scenario NAME] [--project PATH] [--json]",
    "meshy live-plan --prompt TEXT [--model MODEL] [--mode preview|refine] [--project PATH] [--json]",
    "meshy approve-live-once --prompt TEXT --max-credits N [--model MODEL] [--project PATH] [--expires-in SECONDS] [--json]",
    "meshy revoke-live-approval APPROVAL_ID [--reason TEXT]",
    "meshy live-run --prompt TEXT --confirm-live [--model MODEL] [--mode preview|refine] [--project PATH] [--json]",
    "meshy reconcile-ledger-entry RESERVATION_ID --reason TEXT [--json]",
    "workflow plan <project_dir> [--json]",
    "workflow assess <artifact_path> [--json]",
    "blender-adapt plan <artifact_path> [--target-max-mm N] [--json]",
    "blender-adapt execute <artifact_path> --target-max-mm N --confirm [--confirmed-by NAME] [--json]",
    "cad-augment plan <artifact_path> [--base-width-mm N] [--base-length-mm N] [--base-height-mm N] "
    "[--coin-slot-width-mm N] [--coin-slot-length-mm N] [--coin-slot-depth-mm N] "
    "[--coin-slot-position-x-mm N] [--coin-slot-position-y-mm N] "
    "[--mounting-hole-diameter-mm N] [--mounting-hole-margin-mm N] [--json]",
    "cad-augment execute <artifact_path> --base-width-mm N --base-length-mm N --base-height-mm N "
    "[--coin-slot-width-mm N] [--coin-slot-length-mm N] [--coin-slot-depth-mm N] "
    "[--coin-slot-position-x-mm N] [--coin-slot-position-y-mm N] "
    "[--mounting-hole-diameter-mm N] [--mounting-hole-margin-mm N] --confirm [--confirmed-by NAME] [--json]",
    "design-review <project_dir> [--json] [--save]",
    "manufacturing-readiness <project_dir> [--json] [--verbose]",
)

STATUS_ICON = {"PASS": "[green]PASS[/green]", "WARN": "[yellow]WARN[/yellow]", "FAIL": "[red]FAIL[/red]"}


def _icon(status: str) -> str:
    return STATUS_ICON.get(status, status)


def _load_primary_printer() -> dict | None:
    """Return the manufacturing knowledge base's primary printer, if configured.

    config/manufacturing/printers.json is the sole canonical printer source
    (see docs/manufacturing-knowledge-base.md); there is no separate
    config/printers.json to fall back to.
    """
    primary_id = knowledge.get_primary_printer_id()
    if not primary_id:
        return None
    return knowledge.get_printer(primary_id)


@app.command()
def status() -> None:
    """Print repo/environment status and safety posture."""
    config_files = ["materials.json", "tolerances.json", "agent_policy.json"]
    manufacturing_config_files = ["printers.json", "materials.json", "accessories.json", "planning_rules.json"]
    schema_files = [
        "project_brief.schema.json",
        "build_plan.schema.json",
        "part_manifest.schema.json",
        "validation_report.schema.json",
        "slicer_review.schema.json",
    ]

    console.print(f"[bold]repo path[/bold]: {project_store.REPO_ROOT}")
    console.print(f"[bold]python version[/bold]: {sys.version.split()[0]}")

    console.print("[bold]config files[/bold]:")
    for name in config_files:
        exists = (project_store.CONFIG_DIR / name).is_file()
        console.print(f"  {_icon('PASS') if exists else _icon('FAIL')}  config/{name}")

    console.print("[bold]manufacturing config files[/bold]:")
    for name in manufacturing_config_files:
        exists = (project_store.MANUFACTURING_CONFIG_DIR / name).is_file()
        console.print(f"  {_icon('PASS') if exists else _icon('FAIL')}  config/manufacturing/{name}")

    console.print("[bold]schema files[/bold]:")
    for name in schema_files:
        exists = (project_store.SCHEMAS_DIR / name).is_file()
        console.print(f"  {_icon('PASS') if exists else _icon('FAIL')}  schemas/{name}")

    projects_ok = project_store.PROJECTS_DIR.is_dir()
    console.print(f"[bold]projects dir[/bold]: {_icon('PASS') if projects_ok else _icon('FAIL')}  {project_store.PROJECTS_DIR}")

    console.print("[bold]safety status[/bold]: local-only. no printer control. no cloud/paid API calls. no auto-print.")

    console.print("[bold]available commands[/bold]:")
    for cmd in AVAILABLE_COMMANDS:
        console.print(f"  factory {cmd}")


@app.command(name="init-project")
def init_project_cmd(name: str = typer.Argument(..., help="Project name, e.g. 'mr-reagan-nameplate'")) -> None:
    """Scaffold a new project under projects/<safe-slug>/."""
    try:
        root = project_store.init_project(name)
    except FileExistsError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)
    except ValueError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)

    console.print(f"[green]created[/green] project at {root}")
    for sub in project_store.PROJECT_SUBDIRS:
        console.print(f"  {root.name}/{sub}/")
    console.print("  brief.json, build_plan.json, part_manifest.json")
    console.print("\nNext: edit brief.json, then run `factory plan <path to brief.json>`.")


@app.command()
def plan(brief_path: Path = typer.Argument(..., help="Path to a project's brief.json")) -> None:
    """Read a brief.json and draft build_plan.json next to it (local, deterministic stub)."""
    try:
        build_plan_path = plan_from_brief_path(brief_path)
    except FileNotFoundError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)

    build_plan = project_store.load_json(build_plan_path)
    console.print(f"[green]wrote[/green] {build_plan_path}")
    console.print(f"  status: {build_plan['status']}")
    console.print(f"  primary_tool: {build_plan['tool_routing_recommendation']['primary_tool']}")
    console.print(f"  human_review_required: {build_plan['human_review_required']}")

    target_printer = build_plan.get("target_printer") or {}
    printer_label = target_printer.get("display_name") or "(unresolved)"
    console.print(f"  target_printer: {printer_label} (resolved: {target_printer.get('resolved', False)})")

    manufacturing_options = build_plan.get("manufacturing_options") or {}
    if manufacturing_options:
        console.print(
            f"  manufacturing_options: {len(manufacturing_options.get('options', []))} explained, "
            f"recommended: {manufacturing_options.get('recommended_option')!r} (not yet confirmed)"
        )
    for question in build_plan.get("unanswered_questions", []):
        console.print(f"  [yellow]open question[/yellow]: {question}")


@app.command(name="list-options")
def list_options_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory under projects/"),
) -> None:
    """List every manufacturing option from build_plan.json for human review."""
    try:
        result = list_manufacturing_options(project_dir)
    except BuildPlanNotFoundError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)

    selected = result["selected_manufacturing_option"]
    console.print(f"[bold]selected_manufacturing_option[/bold]: {selected!r}")
    console.print(f"[bold]recommended[/bold]: {result['recommended_option']!r} (non-binding)")
    console.print(f"  {result['recommendation_rationale']}")

    console.print(f"\n[bold]manufacturing options[/bold] ({len(result['options'])}):")
    for option in result["options"]:
        markers = []
        if option["option_id"] == result["recommended_option"]:
            markers.append("RECOMMENDED")
        if option["option_id"] == selected:
            markers.append("SELECTED")
        if not option.get("available", True):
            markers.append("NOT AVAILABLE for target printer")
        marker_text = f"  [{', '.join(markers)}]" if markers else ""

        console.print(f"\n  [bold]{option['option_id']}[/bold] - {option['display_name']}{marker_text}")
        console.print(f"    {option['description']}")
        console.print("    advantages:")
        for advantage in option["advantages"]:
            console.print(f"      + {advantage}")
        console.print("    disadvantages / risks:")
        for disadvantage in option["disadvantages"]:
            console.print(f"      - {disadvantage}")
        if option.get("availability_note"):
            console.print(f"    [yellow]note[/yellow]: {option['availability_note']}")

    console.print(f"\n[bold]requires human confirmation[/bold]: {result['requires_human_confirmation']}")
    if result["unanswered_questions"]:
        console.print("\n[bold]unanswered questions[/bold]:")
        for question in result["unanswered_questions"]:
            console.print(f"  [yellow]-[/yellow] {question}")

    console.print(f"\nTo select an option, run: factory choose-option {project_dir} <option_id>")


@app.command(name="choose-option")
def choose_option_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory under projects/"),
    option_id: str = typer.Argument(..., help="A manufacturing option id from `factory list-options`"),
) -> None:
    """Record an explicit human choice of manufacturing option into build_plan.json."""
    try:
        result = choose_manufacturing_option(project_dir, option_id)
    except BuildPlanNotFoundError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)
    except UnknownManufacturingOptionError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)

    console.print(f"[green]selected[/green] manufacturing option: {option_id!r} ({result['option']['display_name']})")
    if not result["available"]:
        console.print(f"[yellow]warning[/yellow]: {result['availability_note']}")
    if result["status_advanced"]:
        console.print(f"  brief.json status advanced to {NEW_STATUS_AFTER_SELECTION!r}")
    console.print(f"  {result['assembly_intent']['note']}")
    console.print(
        "\nThis only recorded your choice in build_plan.json/part_manifest.json - it did not generate or "
        "modify CAD, export an STL, invoke OpenSCAD, or contact any printer/slicer/network."
    )


@app.command(name="route-cad")
def route_cad_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory under projects/"),
) -> None:
    """Recommend a CAD backend for a project's brief. Read-only; generates nothing."""
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        console.print(f"[red]error[/red]: not a directory: {project_dir}")
        raise typer.Exit(code=1)

    brief = _safe_load(project_dir / "brief.json") or {}
    build_plan = _safe_load(project_dir / "build_plan.json") or {}
    description = brief.get("description", "")
    selected_option = build_plan.get("selected_manufacturing_option")

    result = route_cad(description, selected_manufacturing_option=selected_option)

    console.print(f"[bold]primary recommendation[/bold]: {result['primary_recommendation']!r}")
    console.print(f"  {result['rationale']}")
    console.print(f"[bold]recommended backend(s)[/bold]: {', '.join(result['recommended_backends'])}")
    console.print(f"  cadquery available in this environment: {result['cadquery_available']}")
    if result["selected_manufacturing_option"]:
        console.print(f"  selected manufacturing option: {result['selected_manufacturing_option']!r}")

    if result["future_only_needs"]:
        console.print("\n[yellow]future-only needs[/yellow] (not implementable as a generation backend today):")
        for need in result["future_only_needs"]:
            console.print(f"  - {need['display_name']} ({need['backend_id']}): {need['reason']}")
    else:
        console.print("\nfuture-only needs: none detected")

    for note in result["notes"]:
        console.print(f"\n{note}")
    console.print(
        "\nThis command only read brief.json/build_plan.json - it did not generate CAD, write any file, "
        "or contact any printer/slicer/network."
    )


def _print_printer_detail(printer: dict) -> None:
    capabilities = knowledge.printer_capabilities(printer)
    console.print(f"[bold]{printer.get('printer_id')}[/bold] - {printer.get('display_name')}")
    console.print(f"  manufacturer/model: {printer.get('manufacturer')} / {printer.get('model')}")
    build_volume = printer.get("build_volume_mm") or {}
    console.print(
        f"  build volume: {build_volume.get('x')} x {build_volume.get('y')} x {build_volume.get('z')} mm "
        f"(verified: {printer.get('verified', False)})"
    )
    accessory_names = [a.get("display_name", "?") for a in capabilities["installed_accessories"]]
    console.print(f"  installed accessories: {', '.join(accessory_names) if accessory_names else 'none'}")
    console.print(
        f"  AMS supported: {printer.get('ams_supported', False)}  |  "
        f"multicolor capable: {capabilities['multicolor_supported']}"
    )
    console.print(f"  supported materials: {', '.join(printer.get('supported_materials', [])) or 'none listed'}")
    console.print(f"  preferred job types: {', '.join(printer.get('preferred_job_types', [])) or 'none listed'}")
    if printer.get("notes"):
        console.print(f"  notes: {printer['notes']}")


@app.command(name="list-printers")
def list_printers_cmd() -> None:
    """List every printer in the manufacturing knowledge base (read-only)."""
    printers = list_printers()
    console.print(f"[bold]printers[/bold] ({len(printers)}):")
    for printer in printers:
        console.print("")
        _print_printer_detail(printer)
    console.print("\nThis command only reads config/manufacturing/printers.json - no hardware was contacted.")


@app.command(name="show-printer")
def show_printer_cmd(printer_id: str = typer.Argument(..., help="A printer id from `factory list-printers`")) -> None:
    """Show full detail for one printer (read-only)."""
    try:
        printer = get_printer_or_raise(printer_id)
    except UnknownPrinterError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)
    _print_printer_detail(printer)


@app.command(name="list-accessories")
def list_accessories_cmd() -> None:
    """List every accessory in the manufacturing knowledge base (read-only)."""
    accessories = list_accessories()
    console.print(f"[bold]accessories[/bold] ({len(accessories)}):")
    for accessory in accessories:
        console.print(f"\n[bold]{accessory.get('accessory_id')}[/bold] - {accessory.get('display_name')}")
        console.print(f"  type: {accessory.get('category', 'unknown')}")
        console.print(f"  adds capabilities: {', '.join(accessory.get('adds_capabilities', [])) or 'none listed'}")
        compatible = accessory.get("compatible_models") or accessory.get("compatible_manufacturers")
        if compatible:
            console.print(f"  compatible: {', '.join(compatible)}")
        if accessory.get("notes"):
            console.print(f"  notes: {accessory['notes']}")
    console.print("\nThis command only reads config/manufacturing/accessories.json - no hardware was contacted.")


@app.command(name="show-accessory")
def show_accessory_cmd(
    accessory_id: str = typer.Argument(..., help="An accessory id from `factory list-accessories`"),
) -> None:
    """Show full detail for one accessory (read-only)."""
    try:
        accessory = get_accessory_or_raise(accessory_id)
    except UnknownAccessoryError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)

    console.print(f"[bold]{accessory.get('accessory_id')}[/bold] - {accessory.get('display_name')}")
    console.print(f"  type: {accessory.get('category', 'unknown')}")
    console.print(f"  manufacturer: {accessory.get('manufacturer', 'unspecified')}")
    console.print(f"  adds capabilities: {', '.join(accessory.get('adds_capabilities', [])) or 'none listed'}")
    compatible = accessory.get("compatible_models") or accessory.get("compatible_manufacturers")
    console.print(f"  compatible: {', '.join(compatible) if compatible else 'not specified'}")
    if accessory.get("notes"):
        console.print(f"  notes: {accessory['notes']}")


@app.command(name="list-materials")
def list_materials_cmd() -> None:
    """List every material in the manufacturing knowledge base (read-only)."""
    materials = list_materials()
    console.print(f"[bold]materials[/bold] ({len(materials)}):")
    for material in materials:
        console.print(f"\n[bold]{material.get('material_id')}[/bold] - {material.get('display_name')}")
        console.print(f"  type: {material.get('category', 'unknown')}")
        console.print(f"  recommended use (good_for): {', '.join(material.get('good_for', [])) or 'none listed'}")
        if material.get("notes"):
            console.print(f"  notes: {material['notes']}")
    console.print("\nThis command only reads config/manufacturing/materials.json - no hardware was contacted.")


@app.command(name="show-material")
def show_material_cmd(
    material_id: str = typer.Argument(..., help="A material id from `factory list-materials`"),
) -> None:
    """Show full detail for one material (read-only)."""
    try:
        material = get_material_or_raise(material_id)
    except UnknownMaterialError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)

    console.print(f"[bold]{material.get('material_id')}[/bold] - {material.get('display_name')}")
    console.print(f"  type: {material.get('category', 'unknown')}")
    console.print(f"  recommended use (good_for): {', '.join(material.get('good_for', [])) or 'none listed'}")
    console.print(f"  paintable: {material.get('paintable', 'unspecified')}")
    console.print(f"  strength class: {material.get('strength_class', 'unspecified')}")
    if material.get("surface_finish_notes"):
        console.print(f"  surface finish: {material['surface_finish_notes']}")
    if material.get("notes"):
        console.print(f"  notes (cautions): {material['notes']}")


@app.command(name="fleet-summary")
def fleet_summary_cmd() -> None:
    """Compact summary of every printer in the fleet (read-only)."""
    summaries = fleet_summary()
    console.print(f"[bold]fleet summary[/bold] ({len(summaries)} printer(s)):")
    for summary in summaries:
        build_volume = summary["build_volume_mm"] or {}
        label = summary["unit_label"] or summary["display_name"]
        accessories = ", ".join(summary["installed_accessories"]) or "none"
        console.print(
            f"  - {label}  [{summary['printer_id']}]  "
            f"{build_volume.get('x')}x{build_volume.get('y')}x{build_volume.get('z')}mm  "
            f"accessories: {accessories}  "
            f"multicolor: {summary['multicolor_supported']}  "
            f"(verified: {summary['verified']})"
        )
    console.print("\nThis command only reads config/manufacturing/printers.json - no hardware was contacted.")


@app.command(name="check-manufacturing")
def check_manufacturing_cmd() -> None:
    """Validate config/manufacturing/*.json for internal consistency (read-only)."""
    checks = check_manufacturing_knowledge_base()
    for check in checks:
        console.print(f"{_icon(check['status'])}  {check['name']}: {check['detail']}")

    fail_count = sum(1 for c in checks if c["status"] == "FAIL")
    warn_count = sum(1 for c in checks if c["status"] == "WARN")
    console.print(f"\n{len(checks)} check(s): {fail_count} FAIL, {warn_count} WARN")
    console.print("This command only reads config/manufacturing/*.json - no hardware was contacted.")

    if fail_count:
        raise typer.Exit(code=1)


@app.command(name="generate-openscad")
def generate_openscad_cmd(
    project_dir: Path = typer.Argument(..., help="Path to an initialized project directory (see factory init-project)"),
    template: str = typer.Option(..., "--template", help=f"One of: {', '.join(ALLOWED_TEMPLATES)}"),
    text: Optional[str] = typer.Option(None, "--text", help="Text for templates that need it (nameplate, sign, multipart-nameplate)"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing .scad files for this template"),
) -> None:
    """Generate local, parametric OpenSCAD source into <project_dir>/cad/. Does not run OpenSCAD or export STLs."""
    try:
        result = generate_openscad(project_dir, template, text, force=force)
    except (ValueError, ProjectNotInitializedError) as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)
    except GeneratedFileExistsError as exc:
        console.print(f"[red]error[/red]: {exc}")
        console.print("Re-run with --force to overwrite.")
        raise typer.Exit(code=1)

    console.print(f"[green]generated[/green] template '{result.template}' in {result.project_dir}")
    for path in result.written_files:
        console.print(f"  {path}")
    console.print(f"  updated manifest: {result.manifest_path}")
    console.print(f"  export instructions: {result.export_instructions_path}")
    console.print(
        "\nThis only wrote local .scad source and instructions - it did not run OpenSCAD, "
        "export an STL, or contact any printer/network/API."
    )


@app.command(name="generate-cadquery")
def generate_cadquery_cmd(
    project_dir: Path = typer.Argument(..., help="Path to an initialized project directory (see factory init-project)"),
    template: str = typer.Option(..., "--template", help=f"One of: {', '.join(cadquery_backend.ALLOWED_TEMPLATES)}"),
    length_mm: float = typer.Option(80.0, "--length-mm"),
    width_mm: float = typer.Option(50.0, "--width-mm"),
    thickness_mm: float = typer.Option(5.0, "--thickness-mm"),
    corner_radius_mm: float = typer.Option(4.0, "--corner-radius-mm", help="Set to 0 for square corners"),
    hole_diameter_mm: Optional[float] = typer.Option(None, "--hole-diameter-mm", help="Set to add 4 corner mounting holes"),
    hole_margin_mm: float = typer.Option(8.0, "--hole-margin-mm"),
    label_text: Optional[str] = typer.Option(None, "--label-text", help="Text to engrave centered on the top face"),
    label_size_mm: float = typer.Option(8.0, "--label-size-mm"),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing .py file for this template"),
) -> None:
    """Generate local CadQuery source into <project_dir>/cad/. Requires cadquery to already be
    installed in this environment; never installs it, runs it, or exports an STL."""
    try:
        result = cadquery_backend.generate_cadquery(
            project_dir,
            template,
            length_mm=length_mm,
            width_mm=width_mm,
            thickness_mm=thickness_mm,
            corner_radius_mm=corner_radius_mm,
            hole_diameter_mm=hole_diameter_mm,
            hole_margin_mm=hole_margin_mm,
            label_text=label_text,
            label_size_mm=label_size_mm,
            force=force,
        )
    except (ValueError, cadquery_backend.ProjectNotInitializedError) as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)
    except cadquery_backend.GeneratedFileExistsError as exc:
        console.print(f"[red]error[/red]: {exc}")
        console.print("Re-run with --force to overwrite.")
        raise typer.Exit(code=1)
    except cadquery_backend.CadQueryNotAvailableError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)

    console.print(f"[green]generated[/green] template '{result.template}' in {result.project_dir}")
    for path in result.source_files:
        console.print(f"  {path}")
    for note in result.human_actions_required:
        console.print(f"  action required: {note}")
    for note in result.safety_notes:
        console.print(f"\n{note}")


@app.command()
def validate(mesh_file: Path = typer.Argument(..., help="Path to a mesh file (.stl, .obj, .ply, ...)")) -> None:
    """Run local geometry sanity checks on a mesh file and write a validation report."""
    printer = _load_primary_printer()
    report = validate_mesh(mesh_file, printer)

    project_root = project_store.find_project_root(mesh_file)
    if project_root is not None:
        out_path = project_root / "validation" / f"{mesh_file.stem}_validation.json"
    else:
        out_path = mesh_file.parent / f"{mesh_file.stem}_validation.json"

    project_store.save_json(out_path, report)

    console.print(f"overall: {_icon(report['overall_status'])}")
    for check in report["checks"]:
        console.print(f"  {_icon(check['status'])}  {check['name']}: {check['detail']}")
    console.print(f"\n{report['summary_message']}")
    console.print(f"[green]wrote[/green] {out_path}")

    if report["overall_status"] == "FAIL":
        raise typer.Exit(code=1)


@app.command()
def render(mesh_file: Path = typer.Argument(..., help="Path to a mesh file to render a preview of")) -> None:
    """Render a simple local isometric preview PNG of a mesh file."""
    project_root = project_store.find_project_root(mesh_file)
    if project_root is not None:
        out_path = project_root / "renders" / f"{mesh_file.stem}_preview.png"
    else:
        out_path = mesh_file.parent / f"{mesh_file.stem}_preview.png"

    result = render_preview(mesh_file, out_path)
    console.print(f"{_icon(result['status'])}  {result['detail']}")

    if result["status"] == "FAIL":
        raise typer.Exit(code=1)


@app.command(name="render-coverage")
def render_coverage_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory under projects/"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Read-only comparison of stl/*.stl against renders/*.png. Never renders, exports, or contacts anything."""
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        console.print(f"[red]error[/red]: not a directory: {project_dir}")
        raise typer.Exit(code=1)

    coverage = compute_render_coverage(project_dir)

    if as_json:
        print(json.dumps(coverage, indent=2, sort_keys=False))
        return

    for line in build_text_report(coverage):
        console.print(line)
    console.print(
        "\nThis command only read existing stl/renders files under this project - it did not render, "
        "generate, export, or contact anything."
    )


@app.command(name="plan-renders")
def plan_renders_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory under projects/"),
) -> None:
    """List local `factory render` commands a human could run. Never runs them."""
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        console.print(f"[red]error[/red]: not a directory: {project_dir}")
        raise typer.Exit(code=1)

    coverage = compute_render_coverage(project_dir)
    commands = plan_render_commands(coverage)

    if not commands:
        console.print("No missing or stale renders detected - nothing to plan.")
    else:
        console.print(f"[bold]suggested commands[/bold] ({len(commands)}) - none of these are run automatically:")
        for cmd in commands:
            console.print(f"  {cmd}")

    console.print(
        "\nThis command only read existing stl/renders files under this project - it did not render, "
        "generate, export, or run any of the commands listed above."
    )


def _print_preview_index_summary(index: dict) -> None:
    console.print(f"[bold]project[/bold]: {index['project_name']} ({index['project_dir']})")
    console.print(f"  status: {index['project_status']}")
    target_printer = index.get("target_printer") or {}
    console.print(f"  target printer: {target_printer.get('display_name') or '(not planned yet)'}")
    console.print(f"  selected manufacturing option: {index['selected_manufacturing_option']!r}")
    console.print(f"  CAD source files: {len(index['cad_files'])}")
    console.print(f"  mesh/STL files: {len(index['mesh_files'])}")
    console.print(f"  render/preview images: {len(index['render_files'])}")
    console.print(
        f"  manifest parts: {len(index['manifest_parts'])} "
        f"(multi-part: {index['multipart_state']['multi_part']})"
    )

    if index["missing_visual_artifacts"]:
        console.print(f"  [yellow]missing visual artifacts[/yellow] ({len(index['missing_visual_artifacts'])}):")
        for item in index["missing_visual_artifacts"]:
            console.print(f"    - {item}")
    else:
        console.print("  missing visual artifacts: none")

    if index["stale_previews"]:
        console.print(f"  [yellow]stale previews[/yellow] ({len(index['stale_previews'])}):")
        for item in index["stale_previews"]:
            console.print(f"    - {item}")
    else:
        console.print("  stale previews: none detected")

    console.print("\n[bold]human visual inspection checklist[/bold] (advisory only):")
    for item in index["human_visual_inspection_checklist"]:
        console.print(f"  - [ ] {item}")

    console.print("\nHuman visual inspection required.")
    console.print("Human slicer review required.")
    console.print("Project is NOT print-ready.")


@app.command(name="preview-index")
def preview_index_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory under projects/"),
) -> None:
    """Print a read-only visual-artifact summary. Never renders, writes, or exports anything."""
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        console.print(f"[red]error[/red]: not a directory: {project_dir}")
        raise typer.Exit(code=1)

    index = gather_preview_data(project_dir)
    _print_preview_index_summary(index)
    console.print(
        "\nThis command only read existing project files - it did not render, generate, export, "
        "or write anything."
    )


@app.command(name="preview-project")
def preview_project_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory under projects/"),
) -> None:
    """Build/refresh preview_package/index.json and preview_report.md from existing project files."""
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        console.print(f"[red]error[/red]: not a directory: {project_dir}")
        raise typer.Exit(code=1)

    result = write_preview_package(project_dir)
    _print_preview_index_summary(result["index"])
    console.print(f"\n[green]wrote[/green] {result['index_path']}")
    console.print(f"[green]wrote[/green] {result['report_path']}")
    console.print(
        "\nThis only used existing cad/stl/render files already on disk - it did not render new images, "
        "invoke OpenSCAD, export an STL, or contact any printer/slicer/network."
    )


@app.command(name="preview-board")
def preview_board_cmd(
    projects_root: Path = typer.Argument(..., help="Directory containing project subdirectories (e.g. this repo's projects/)"),
    output: Optional[Path] = typer.Option(None, "--output", help="Output directory for the board (default: <projects_root>/preview_board/)"),
    fmt: str = typer.Option("both", "--format", help="One of: json, html, both"),
) -> None:
    """Build/refresh a local static preview board summarizing every project under projects_root."""
    projects_root = Path(projects_root)
    if not projects_root.is_dir():
        console.print(f"[red]error[/red]: not a directory: {projects_root}")
        raise typer.Exit(code=1)

    try:
        result = write_preview_board(projects_root, output_dir=output, fmt=fmt)
    except ValueError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)

    board = result["board"]
    console.print(f"[bold]preview board[/bold]: {board['project_count']} project(s) under {board['projects_root']}")
    for state in VISUAL_READINESS_STATES:
        console.print(f"  {state}: {board['state_counts'][state]}")

    if result["index_path"]:
        console.print(f"\n[green]wrote[/green] {result['index_path']}")
    if result["html_path"]:
        console.print(f"[green]wrote[/green] {result['html_path']}")

    console.print(
        "\nThis only read existing project files under projects_root - it did not render new images, "
        "export STLs, run OpenSCAD/CadQuery, invoke a slicer, launch Blender, or contact any "
        "printer/network."
    )
    console.print("Local static preview only. Not an approval. Not a print-readiness signal.")


def _is_single_project_dir(path: Path) -> bool:
    return (path / "brief.json").is_file() or (path / "concept_brief.json").is_file()


def _print_readiness_report(name: str, orchestrator: dict) -> None:
    score = orchestrator["score"]
    console.print(f"[bold]{name}[/bold]")
    console.print(
        f"  Overall: {score['overall']}%   Ready for: {orchestrator['recommended_engine']}   "
        f"Status: {orchestrator['readiness_state']}"
    )
    console.print("  Score breakdown:")
    for category, value in score["categories"].items():
        console.print(f"    {_capitalize_first(category.replace('_', ' '))}: {value}%")
    console.print("  Remaining:")
    for advisory in orchestrator["advisories"]:
        console.print(f"    - {advisory}")
    console.print(f"  Engine rationale: {orchestrator['engine_rationale']}")


@app.command(name="readiness")
def readiness_cmd(
    path: Path = typer.Argument(
        ...,
        help="A project directory, a directory of multiple projects (e.g. examples/ or projects/), or a plain-text/Markdown idea file",
    ),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Design Orchestrator readiness check (Phase 33) - evaluates whether a project
    is sufficiently defined to proceed and recommends the most appropriate downstream
    design engine (OpenSCAD, CadQuery, Blender, Meshy, FreeCAD, a hybrid workflow,
    manual design, or unknown). Never generates CAD, never invokes any engine - purely
    a deterministic, read-only recommendation for a human to act on. Accepts a single
    project directory (has its own brief.json/concept_brief.json), a directory of
    multiple projects (e.g. examples/ or projects/), or a plain-text/Markdown idea
    file. See docs/design-orchestrator.md."""
    if path.is_dir() and not _is_single_project_dir(path):
        project_dirs = discover_projects(path)
        results = [(p.name, summarize_project(p, projects_root=path)["design_orchestrator_summary"]) for p in project_dirs]

        if as_json:
            payload = {
                "projects_root": str(path),
                "project_count": len(results),
                "projects": {name: orchestrator for name, orchestrator in results},
            }
            print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False))
            return

        console.print(f"[bold]Project Readiness[/bold] - {len(results)} project(s) under {path}\n")
        for name, orchestrator in results:
            _print_readiness_report(name, orchestrator)
            console.print()
        return

    if path.is_dir():
        orchestrator = summarize_project(path)["design_orchestrator_summary"]
    else:
        orchestrator = evaluate_readiness_for_path(path)

    if as_json:
        print(json.dumps(orchestrator, indent=2, sort_keys=False, ensure_ascii=False))
        return

    _print_readiness_report(str(path), orchestrator)
    console.print(
        "\nThis is a deterministic, local-only recommendation - no AI, no LLM, no network, and no engine "
        "was invoked. See docs/design-orchestrator.md."
    )


@app.command(name="generate-from-readiness")
def generate_from_readiness_cmd(
    path: Path = typer.Argument(
        ...,
        help="Path to a project directory (see factory init-project) or a plain-text/Markdown idea file",
    ),
    confirm_generate: bool = typer.Option(
        False,
        "--confirm-generate",
        help="Actually generate local CAD artifacts if the readiness gate allows it; without this flag, only a dry-run plan is shown and nothing is written",
    ),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Readiness-Gated CAD Generation Router (Phase 34) - the first gated bridge between
    Design Orchestrator readiness (Phase 33) and this repo's *existing* local CAD generation
    backends (OpenSCAD, CadQuery). Dry run by default: always computes and shows a full
    generation plan (recommended engine, template, what's still missing) but writes nothing.
    Pass --confirm-generate to actually generate - only happens if the gate allows it:
    recognized supported engine (OpenSCAD, or CadQuery if installed), readiness state not
    Blocked, readiness score at or above the gate's conservative threshold, and no critical
    information missing. Never generates for Blender, Meshy, FreeCAD, or any other
    unsupported/future engine; never installs anything; never contacts a network. On a
    successful confirmed generation, also writes an execution receipt to
    <project_dir>/generated/generation_receipt.json (dry runs never produce one - see
    docs/generation-gate.md "Execution receipts"). This is an adapter around existing
    generation, not a second CAD backend. See docs/generation-gate.md."""
    gate = evaluate_generation_gate_for_path(path, confirm_generate=confirm_generate)

    generation_result: dict | None = None
    generation_error: str | None = None
    receipt_path: Path | None = None
    if confirm_generate and gate["decision"] == "Allowed":
        if not path.is_dir():
            generation_error = "cannot generate CAD artifacts into a non-directory path"
        else:
            try:
                generation_result = run_generation(path, gate)
            except (
                GeneratedFileExistsError,
                ProjectNotInitializedError,
                cadquery_backend.GeneratedFileExistsError,
                cadquery_backend.ProjectNotInitializedError,
                cadquery_backend.CadQueryNotAvailableError,
            ) as exc:
                generation_error = str(exc)
            else:
                # Execution receipts (Phase 34): only ever written after a real,
                # confirmed, successful generation - never for a dry run. No
                # automatic console confirmation is printed for this write; the
                # path is only surfaced via --json (see docs/generation-gate.md).
                receipt_path = write_generation_receipt(path, gate, generation_result)

    if as_json:
        payload = dict(gate)
        payload["project"] = str(path)
        if generation_result is not None:
            payload["generation_result"] = generation_result
        if generation_error is not None:
            payload["generation_error"] = generation_error
        if receipt_path is not None:
            payload["receipt_path"] = str(receipt_path)
        print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False))
        if generation_error is not None:
            raise typer.Exit(code=1)
        return

    console.print("[bold]Generation Plan[/bold]\n")
    console.print("[bold]Project:[/bold]")
    console.print(path.name if path.is_dir() else str(path))
    console.print()
    console.print("[bold]Readiness:[/bold]")
    console.print(f"{gate['readiness_score']}%")
    console.print()
    console.print("[bold]Status:[/bold]")
    console.print(gate["readiness_state"])
    console.print()
    console.print("[bold]Recommended Engine:[/bold]")
    console.print(gate["recommended_engine"])
    console.print()
    console.print("[bold]Decision:[/bold]")
    console.print(gate["decision"])
    console.print()
    console.print("[bold]Would Generate:[/bold]")
    if gate["plan"]:
        console.print(f"{gate['plan']['engine']} CAD artifacts ({gate['plan']['human_summary']})")
    else:
        console.print("Nothing - no local template available for this engine/category")
    console.print()

    if gate["required_before_generation"]:
        console.print("[bold]Required Before Generation:[/bold]")
        for item in gate["required_before_generation"]:
            console.print(f"- {item}")
        console.print()

    if generation_result is not None:
        console.print(f"[green]generated[/green] {len(generation_result['written_files'])} file(s):")
        for written in generation_result["written_files"]:
            console.print(f"  {written}")
        if generation_result["warnings"]:
            console.print("[yellow]warnings[/yellow]:")
            for warning in generation_result["warnings"]:
                console.print(f"  {warning}")
    elif generation_error is not None:
        console.print(f"[red]error[/red]: {generation_error}")
        console.print("No files written.")
    elif confirm_generate and gate["decision"] != "Allowed":
        console.print(f"[yellow]not generated[/yellow]: decision is {gate['decision']!r}, not 'Allowed'.")
        console.print("No files written.")
    else:
        console.print("No files written.")

    console.print(
        "\nThis only inspected existing project files and, if --confirm-generate was passed and the "
        "gate allowed it, ran this repo's existing local OpenSCAD/CadQuery generator - it never invoked "
        "Blender, never called Meshy, never installed anything, and never contacted any printer/network."
    )

    if generation_error is not None:
        raise typer.Exit(code=1)


@app.command(name="export-from-cad")
def export_from_cad_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory (see factory init-project)"),
    confirm_export: bool = typer.Option(
        False,
        "--confirm-export",
        help="Actually run the OpenSCAD CLI to export STL(s), if the plan allows it; without this flag, only "
        "a dry-run plan is shown and no subprocess is ever invoked",
    ),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
    source: Optional[str] = typer.Option(
        None, "--source", help="Project-relative CAD source file, to disambiguate when more than one exists"
    ),
    output_dir: Optional[str] = typer.Option(
        None, "--output-dir", help="Project-relative output directory for exported STLs (default: stl/)"
    ),
    overwrite_stl: bool = typer.Option(
        False, "--overwrite-stl", help="Allow overwriting an existing STL at the expected output path"
    ),
    validate: bool = typer.Option(
        False, "--validate", help="After a successful export, run the existing mesh validator (factory.validators.mesh_validate)"
    ),
    render: bool = typer.Option(False, "--render", help="After a successful export, render a preview image"),
    all_steps: bool = typer.Option(False, "--all", help="Equivalent to --validate --render"),
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Skip export/validate/render steps the prior export receipt already records as current for "
        "this exact source; only re-run what's missing, failed, or stale",
    ),
) -> None:
    """Guided Export Pipeline (Phase 35) - the next gated step after Phase 34's Readiness-Gated CAD
    Generation Router. Dry run by default: always computes and shows a full export plan (which CAD
    source, which exporter, expected outputs, collisions/staleness) but invokes no subprocess and writes
    nothing. Pass --confirm-export to actually export - only happens for OpenSCAD source, only if a local
    `openscad` executable is found, and only if there's no unresolved output collision (pass
    --overwrite-stl to allow one). CadQuery source always resolves to 'manual_export_required' - this repo's
    existing policy of never executing generated CadQuery scripts automatically is unchanged; the exact
    manual command is shown instead. --validate/--render/--all optionally run the existing validator/
    renderer against the resulting STL (or an already-existing one) and update the execution receipt
    (<project_dir>/generated/export_receipt.json - dry runs never produce one). Never invokes Blender,
    Meshy, a slicer, or a printer; never installs anything. See docs/export-pipeline.md."""
    if not project_dir.is_dir():
        message = f"not a directory: {project_dir}"
        if as_json:
            print(json.dumps({"errors": [message], "no_automatic_print": True}, indent=2, sort_keys=False))
        else:
            console.print(f"[red]error[/red]: {message}")
        raise typer.Exit(code=1)

    try:
        plan = evaluate_export_pipeline_for_path(
            project_dir,
            source=source,
            output_dir=output_dir,
            overwrite_stl=overwrite_stl,
            confirm_export=confirm_export,
        )
    except UnsafePathError as exc:
        if as_json:
            print(json.dumps({"errors": [str(exc)], "no_automatic_print": True}, indent=2, sort_keys=False))
        else:
            console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)

    pipeline_result: dict | None = None
    want_action = confirm_export or validate or render or all_steps or resume
    if want_action:
        pipeline_result = run_export_pipeline(
            project_dir, plan, validate=validate, render=render, all_steps=all_steps, resume=resume
        )

    errors: list[str] = []
    if pipeline_result:
        for record in pipeline_result["per_source"]:
            export_record = record.get("export") or {}
            errors.extend(export_record.get("errors") or [])

    if as_json:
        payload = {
            "export_plan": plan,
            "dry_run": plan["dry_run"],
            "decision": plan["decision"],
            "source": {
                "engine": plan["source_engine"],
                "backend": plan["source_backend"],
                "files": plan["source_files"],
                "selected": plan["selected_source"],
            },
            "exporter": {"tool": plan["export_tool"], "available": plan["export_tool_available"]},
            "expected_outputs": plan["expected_stl_files"],
            "freshness": {"existing": plan["existing_stl_files"], "stale": plan["stale_stl_files"]},
            "collisions": plan["output_collisions"],
            "blockers": plan["blocking_reasons"],
            "advisories": plan["advisories"],
            "execution": pipeline_result["per_source"] if pipeline_result else None,
            "validation": (
                [r["validation"] for r in pipeline_result["per_source"]] if pipeline_result else None
            ),
            "preview": [r["render"] for r in pipeline_result["per_source"]] if pipeline_result else None,
            "artifact_registry": build_artifact_registry(project_dir),
            "receipt": {
                "path": plan["receipt_path"],
                "pipeline_state": pipeline_result["pipeline_state"] if pipeline_result else None,
            },
            "errors": errors,
            "no_automatic_print": True,
        }
        print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        if errors:
            raise typer.Exit(code=1)
        return

    console.print("[bold]Guided Export Plan[/bold]\n")
    console.print("[bold]Project:[/bold]")
    console.print(plan["project_name"])
    console.print()
    console.print("[bold]Source engine:[/bold]")
    console.print(plan["source_engine"] or "None")
    console.print()
    console.print("[bold]CAD source:[/bold]")
    console.print(", ".join(plan["source_files"]) if plan["source_files"] else "(none found)")
    console.print()
    console.print("[bold]Exporter:[/bold]")
    console.print(plan["export_tool"] or "N/A")
    console.print()
    console.print("[bold]Exporter available:[/bold]")
    console.print("Yes" if plan["export_tool_available"] else "No")
    console.print()
    console.print("[bold]Expected output:[/bold]")
    console.print(", ".join(plan["expected_stl_files"]) if plan["expected_stl_files"] else "(none)")
    console.print()
    console.print("[bold]Decision:[/bold]")
    console.print(plan["decision"])
    console.print()

    if plan["blocking_reasons"]:
        console.print("[bold]Blocking Reasons:[/bold]")
        for reason in plan["blocking_reasons"]:
            console.print(f"- {reason}")
        console.print()

    if plan["advisories"]:
        console.print("[bold]Advisories:[/bold]")
        for advisory in plan["advisories"]:
            console.print(f"- {advisory}")
        console.print()

    console.print("[bold]Post-export checks:[/bold]")
    console.print("- Verify output exists")
    console.print("- Verify output is non-empty")
    console.print("- Validate mesh")
    console.print("- Render preview")
    console.print("- Update artifact tracking")
    console.print("- Update execution receipt")
    console.print()

    if pipeline_result is None:
        console.print("No files written.")
        console.print("Re-run with --confirm-export to begin export.")
    else:
        for record in pipeline_result["per_source"]:
            export_record = record.get("export") or {}
            if export_record.get("success"):
                console.print(f"[green]exported[/green] {record['output_stl']}")
            elif export_record.get("errors"):
                console.print(f"[red]export error[/red] ({record['source_file']}): {'; '.join(export_record['errors'])}")
            validation = record.get("validation", {})
            if validation.get("status") not in (None, "not_run"):
                console.print(f"  validation: {validation['status']} ({validation.get('report_path')})")
            render_info = record.get("render", {})
            if render_info.get("status") not in (None, "not_run"):
                console.print(f"  render: {render_info['status']} ({render_info.get('render_path')})")
        console.print(f"\npipeline state: {pipeline_result['pipeline_state']}")

    console.print(
        "\nThis only inspected/exported existing local CAD source and, if requested, ran this repo's "
        "existing local validator/renderer - it never invoked Blender, never called Meshy, never sliced, "
        "and never contacted any printer/network. No automatic printing."
    )

    if errors:
        raise typer.Exit(code=1)


@app.command(name="slicer-readiness")
def slicer_readiness_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory (see factory init-project)"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
    create_package: bool = typer.Option(False, "--create-package", help="Create a local slicer review package (requires --confirm-package)"),
    confirm_package: bool = typer.Option(False, "--confirm-package", help="Explicit confirmation required alongside --create-package"),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", help="Project-relative output directory for the review package (default: slicer_review/)"),
    approve: bool = typer.Option(False, "--approve", help="Explicitly record human approval for slicer review"),
    approval_note: Optional[str] = typer.Option(None, "--approval-note", help="Optional free-text note to record with --approve"),
    refresh: bool = typer.Option(False, "--refresh", help="Accepted for explicitness; the assessment is always freshly computed regardless"),
    include_warnings: bool = typer.Option(False, "--include-warnings", help="Print every warning message in full (default: a count only)"),
    force_package: bool = typer.Option(False, "--force-package", help="Allow --create-package to overwrite an existing review package"),
) -> None:
    """Slicer Review Readiness Promotion (Phase 36) - the bridge between a completed Phase 35
    export/validate/render pipeline and human slicer review. Read-only by default: always computes
    a full readiness assessment (technical readiness, score, blockers, warnings) but never writes
    anything, never records approval, never creates a package, and never invokes a slicer. Reuses
    factory.review_gate (unchanged), factory.export_pipeline's receipt, and factory.slicer's local
    slicer discovery - never re-implements any of them. --approve explicitly records human approval
    (only once every technical signal is satisfied); approval is automatically invalidated the moment
    a relevant artifact's fingerprint changes. --create-package --confirm-package writes
    slicer_review/slicer_review_manifest.json (conforming to schemas/slicer_review.schema.json) plus
    a human-readable checklist README - only once approved and technically ready, and only overwriting
    an existing package with --force-package. Never slices, uploads, queues, or prints anything -
    auto_print_allowed is always false. See docs/slicer-readiness.md."""
    if not project_dir.is_dir():
        message = f"not a directory: {project_dir}"
        if as_json:
            print(json.dumps({"errors": [message], "no_automatic_print": True}, indent=2, sort_keys=False))
        else:
            console.print(f"[red]error[/red]: {message}")
        raise typer.Exit(code=1)

    if create_package and not confirm_package:
        message = "--create-package requires --confirm-package"
        if as_json:
            print(json.dumps({"errors": [message], "no_automatic_print": True}, indent=2, sort_keys=False))
        else:
            console.print(f"[red]error[/red]: {message}")
        raise typer.Exit(code=1)

    errors: list[str] = []
    approval_result: dict | None = None
    package_result: dict | None = None

    if approve:
        try:
            approval_result = record_approval(project_dir, note=approval_note)
        except ApprovalNotAllowedError as exc:
            errors.append(str(exc))

    if create_package and confirm_package and not errors:
        try:
            package_result = create_review_package(project_dir, output_dir=output_dir, overwrite=force_package)
        except (PackageNotAllowedError, PackageCollisionError) as exc:
            errors.append(str(exc))

    assessment = evaluate_slicer_readiness_for_path(project_dir)

    if as_json:
        payload = dict(assessment)
        payload["approval_result"] = approval_result
        payload["package_result"] = {"package_path": package_result["package_path"]} if package_result else None
        payload["errors"] = errors
        print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        if errors:
            raise typer.Exit(code=1)
        return

    console.print("[bold]Slicer Review Readiness[/bold]\n")
    console.print("[bold]Project:[/bold]")
    console.print(assessment["project_name"])
    console.print()
    console.print("[bold]Technical readiness:[/bold]")
    console.print(assessment["readiness_status"])
    console.print()
    console.print("[bold]Readiness score:[/bold]")
    console.print(f"{assessment['readiness_score']}%")
    console.print()
    console.print("[bold]STL files:[/bold]")
    console.print(f"{assessment['current_stl_count']} current / {assessment['stl_count']} required")
    console.print()
    console.print("[bold]Validation:[/bold]")
    console.print(f"{assessment['validation_pass_count']} passed")
    console.print(f"{assessment['validation_warning_count']} passed with warnings")
    console.print(f"{assessment['validation_failure_count']} failed")
    console.print()
    console.print("[bold]Previews:[/bold]")
    console.print(f"{assessment['current_preview_count']} current")
    console.print()
    console.print("[bold]Manifest:[/bold]")
    console.print("Complete" if assessment["manifest_complete"] else "Incomplete")
    console.print()
    console.print("[bold]Export receipts:[/bold]")
    console.print("Current" if assessment["export_receipt_status"] == "present" else "Missing")
    console.print()
    console.print("[bold]Local slicer:[/bold]")
    found = [s["name"] for s in assessment["detected_slicers"] if s["found"]]
    console.print(f"{found[0]} detected" if found else "None detected")
    console.print()
    console.print("[bold]Human approval:[/bold]")
    console.print("Recorded" if assessment["approval_recorded"] else "Required")
    console.print()
    console.print("[bold]Review package:[/bold]")
    console.print(assessment["package_status"].replace("_", " ").title())
    console.print()

    if assessment["blockers"]:
        console.print("[bold]Blocking reasons:[/bold]")
        for reason in assessment["blockers"]:
            console.print(f"- {reason}")
        console.print()

    if assessment["warnings"]:
        if include_warnings:
            console.print("[bold]Warnings:[/bold]")
            for warning in assessment["warnings"]:
                console.print(f"- {warning}")
        else:
            console.print(f"[bold]Warnings:[/bold] {len(assessment['warnings'])} (pass --include-warnings to list them)")
        console.print()

    if assessment["next_actions"]:
        console.print("[bold]Next actions:[/bold]")
        for action in assessment["next_actions"]:
            console.print(f"- {action}")
        console.print()

    if approval_result is not None:
        console.print("[green]approved[/green] - human approval recorded.")
    if package_result is not None:
        console.print(f"[green]package created[/green]: {package_result['package_path']}")
    for error in errors:
        console.print(f"[red]error[/red]: {error}")

    console.print("\nNo slicer was opened.")
    console.print("No file was uploaded.")
    console.print("No print was started.")

    if errors:
        raise typer.Exit(code=1)


@app.command(name="review-workspace")
def review_workspace_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory (see factory init-project)"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
    create_workspace: bool = typer.Option(False, "--create-workspace", help="Create a local manual review workspace (requires --confirm-workspace)"),
    confirm_workspace: bool = typer.Option(False, "--confirm-workspace", help="Explicit confirmation required alongside --create-workspace"),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", help="Project-relative output directory for the workspace (default: manual_review/)"),
    force_workspace: bool = typer.Option(False, "--force-workspace", help="Allow --create-workspace to overwrite an existing workspace"),
) -> None:
    """Manual Review Workspace (Phase 37) - organizes everything a human needs before opening
    Bambu Studio, OrcaSlicer, or another slicer. Read-only by default: always computes a full
    workspace assessment (printer/material profile, STL/validation/preview/receipt summaries, a
    structured multi-category review checklist, review_confidence/remaining_risk) but never writes
    anything and never invokes a slicer. Reuses factory.slicer_readiness.assess_slicer_readiness()
    (Phase 36, unchanged) for every technical/approval/package signal, and
    factory.manufacturing.knowledge for local printer/material reference data - never re-implements
    either. --create-workspace --confirm-workspace writes manual_review/review_manifest.json plus a
    human-readable checklist README - only once the underlying Phase 36 assessment is both
    technically ready and approved, and only overwriting an existing workspace with
    --force-workspace. This command does not slice, does not generate G-code, and does not print.
    See docs/manual-review-workspace.md."""
    if not project_dir.is_dir():
        message = f"not a directory: {project_dir}"
        if as_json:
            print(json.dumps({"errors": [message], "no_automatic_print": True}, indent=2, sort_keys=False))
        else:
            console.print(f"[red]error[/red]: {message}")
        raise typer.Exit(code=1)

    if create_workspace and not confirm_workspace:
        message = "--create-workspace requires --confirm-workspace"
        if as_json:
            print(json.dumps({"errors": [message], "no_automatic_print": True}, indent=2, sort_keys=False))
        else:
            console.print(f"[red]error[/red]: {message}")
        raise typer.Exit(code=1)

    errors: list[str] = []
    workspace_result: dict | None = None

    if create_workspace and confirm_workspace:
        try:
            workspace_result = create_manual_review_workspace(project_dir, output_dir=output_dir, overwrite=force_workspace)
        except (WorkspaceNotAllowedError, WorkspaceCollisionError) as exc:
            errors.append(str(exc))

    workspace = evaluate_manual_review_workspace_for_path(project_dir)

    if as_json:
        payload = dict(workspace)
        payload["workspace_result"] = {"workspace_path": workspace_result["workspace_path"]} if workspace_result else None
        payload["errors"] = errors
        print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        if errors:
            raise typer.Exit(code=1)
        return

    console.print("[bold]Manual Review Workspace[/bold]\n")
    console.print("[bold]Project:[/bold]")
    console.print(workspace["project"])
    console.print()
    console.print("[bold]Workspace status:[/bold]")
    console.print(workspace["workspace_status"])
    console.print()
    console.print("[bold]Technical readiness:[/bold]")
    console.print(workspace["technical_readiness"])
    console.print()
    console.print("[bold]Printer:[/bold]")
    console.print(workspace["printer_summary"]["display_name"])
    console.print(f"  nozzle (mm): {workspace['printer_summary']['nozzle_mm']}")
    console.print(f"  layer height (mm): {workspace['printer_summary']['layer_height_mm']}")
    console.print(f"  AMS available: {workspace['printer_summary']['ams_available']}")
    console.print()
    console.print("[bold]Material:[/bold]")
    for part in workspace["material_summary"]["parts"]:
        console.print(f"  {part['part_name']}: material={part['material']}, color={part['color']}")
    if not workspace["material_summary"]["parts"]:
        console.print("  (no parts in part_manifest.json)")
    console.print()
    console.print("[bold]Current STL files:[/bold]")
    console.print(f"{workspace['stl_summary']['current']} current / {workspace['stl_summary']['expected']} required")
    console.print()
    console.print("[bold]Validation summary:[/bold]")
    console.print(f"{workspace['validation_summary']['passed']} passed")
    console.print(f"{workspace['validation_summary']['passed_with_warnings']} passed with warnings")
    console.print(f"{workspace['validation_summary']['failed']} failed")
    console.print()
    console.print("[bold]Preview summary:[/bold]")
    console.print(f"{workspace['preview_summary']['current']} current")
    console.print()
    console.print("[bold]Receipts:[/bold]")
    console.print(f"  generation receipt: {workspace['receipt_summary']['generation_receipt_status']}")
    console.print(f"  export receipt: {workspace['receipt_summary']['export_receipt_status']}")
    console.print(f"  review package: {workspace['receipt_summary']['review_package_status']}")
    console.print()
    console.print("[bold]Review confidence:[/bold]")
    console.print(workspace["review_confidence"])
    console.print()
    console.print("[bold]Remaining risk:[/bold]")
    console.print(workspace["remaining_risk"])
    console.print()

    console.print("[bold]Review checklist:[/bold]")
    for category in workspace["review_checklist"]:
        console.print(f"  {category['category']}:")
        for item in category["items"]:
            console.print(f"    - {item}")
    console.print()

    if workspace["warnings"]:
        console.print(f"[bold]Outstanding warnings:[/bold] {len(workspace['warnings'])}")
        for warning in workspace["warnings"]:
            console.print(f"- {warning}")
        console.print()

    if workspace["recommended_actions"]:
        console.print("[bold]Recommended next actions:[/bold]")
        for action in workspace["recommended_actions"]:
            console.print(f"- {action}")
        console.print()

    if workspace_result is not None:
        console.print(f"[green]workspace created[/green]: {workspace_result['workspace_path']}")
    for error in errors:
        console.print(f"[red]error[/red]: {error}")

    console.print("\nNo slicer was opened.")
    console.print("No G-code was generated.")
    console.print("No print was started.")

    if errors:
        raise typer.Exit(code=1)


@app.command(name="slicer-inspect")
def slicer_inspect_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory (see factory init-project)"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
    history: bool = typer.Option(False, "--history", help="Show every previously-saved analysis snapshot (read-only)"),
    compare: bool = typer.Option(False, "--compare", help="Compare the current live analysis against the most recently saved snapshot (read-only)"),
    save_analysis: bool = typer.Option(False, "--save-analysis", help="Explicitly save the current analysis as a new history snapshot"),
) -> None:
    """Slicer Review Intelligence & Print Risk Analysis (Phase 38/39) - a deterministic analysis
    layer that identifies potential slicer-review concerns before a human opens a slicer. This
    does not slice, does not generate G-code, does not control a printer, and does not replace
    human slicer judgment. Reuses factory.manual_review_workspace (Phase 37) for every
    printer/material/technical-readiness signal, each current STL's already-written validation
    report for build-volume-fit and geometry-risk analysis, and factory.slicer_profiles (Phase 39)
    for slicer-aware review guidance - never re-implements mesh validation, dimension checks, or
    slicer detection. Only reports risks supported by existing measurable data - always phrased as
    a possible risk, never a claimed print failure. risk_level is purely informational and never
    blocks anything; hard blockers remain controlled by factory.slicer-readiness/factory.review-gate.
    Default remains entirely read-only. --history/--compare are also read-only. Only
    --save-analysis writes anything - a single, explicit, append-only snapshot to
    generated/slicer_analysis_history.json; never written automatically by this command, by
    factory preview-board, or by any readiness/approval check. See docs/slicer-intelligence.md,
    docs/slicer-profiles.md, docs/slicer-analysis-history.md."""
    if not project_dir.is_dir():
        message = f"not a directory: {project_dir}"
        if as_json:
            print(json.dumps({"errors": [message], "no_automatic_print": True}, indent=2, sort_keys=False))
        else:
            console.print(f"[red]error[/red]: {message}")
        raise typer.Exit(code=1)

    if history:
        snapshots = read_analysis_history(project_dir)
        if as_json:
            print(json.dumps({"snapshots": snapshots, "errors": [], "no_automatic_print": True}, indent=2, sort_keys=False, default=str))
            return
        console.print("[bold]Slicer Analysis History[/bold]\n")
        if not snapshots:
            console.print("No saved analysis snapshots yet - run `factory slicer-inspect --save-analysis` to start tracking history.")
        else:
            for i, snapshot in enumerate(snapshots, start=1):
                console.print(f"{i}. {snapshot.get('timestamp')} - risk: {snapshot.get('risk_level')}, confidence: {snapshot.get('confidence')}")
        console.print("\nNo slicer was opened.")
        console.print("No G-code was generated.")
        console.print("No print was started.")
        return

    if compare:
        comparison = compare_slicer_analysis(project_dir)
        if as_json:
            payload = dict(comparison)
            payload["errors"] = []
            payload["no_automatic_print"] = True
            print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False, default=str))
            return
        console.print("[bold]Slicer Intelligence Comparison[/bold]\n")
        if not comparison["history_available"]:
            console.print(comparison["recommendation"])
        else:
            console.print("[bold]Previous:[/bold]")
            console.print(f"Risk: {comparison['previous'].get('risk_level')}")
            console.print()
            console.print("[bold]Current:[/bold]")
            console.print(f"Risk: {comparison['current'].get('risk_level')}")
            console.print()
            console.print("[bold]Changes:[/bold]")
            if comparison["changes"]:
                for change in comparison["changes"]:
                    console.print(f"⚠ {change}")
            else:
                console.print("None detected.")
            console.print()
            console.print(f"[bold]Recommendation:[/bold]\n{comparison['recommendation']}")
        console.print("\nNo slicer was opened.")
        console.print("No G-code was generated.")
        console.print("No print was started.")
        return

    analysis = evaluate_slicer_intelligence_for_path(project_dir)

    save_result: dict | None = None
    if save_analysis:
        save_result = save_analysis_snapshot(project_dir, analysis=analysis)

    if as_json:
        payload = dict(analysis)
        payload["save_result"] = (
            {"history_path": save_result["history_path"], "snapshot_count": save_result["snapshot_count"]}
            if save_result
            else None
        )
        payload["errors"] = []
        print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return

    console.print("[bold]Slicer Review Intelligence[/bold]\n")
    console.print("[bold]Project:[/bold]")
    console.print(analysis["project"])
    console.print()
    console.print("[bold]Printer:[/bold]")
    console.print(analysis["printer"]["display_name"])
    console.print()
    console.print("[bold]Build Volume:[/bold]")
    console.print(analysis["build_volume_analysis"]["fit_status"].replace("_", " ").title())
    margin = analysis["build_volume_analysis"]["remaining_margin_mm"]
    if margin:
        console.print(f"  remaining margin - x: {margin['x']}mm, y: {margin['y']}mm, z: {margin['z']}mm")
    console.print()
    console.print("[bold]Slicer Profile:[/bold]")
    console.print(analysis["slicer_profile"]["slicer_name"])
    if analysis["slicer_specific_checks"]:
        console.print("Additional Review Items:")
        for item in analysis["slicer_specific_checks"]:
            console.print(f"  ☐ {item}")
    console.print()
    console.print("[bold]Risk:[/bold]")
    console.print(analysis["risk_level"])
    console.print()

    if analysis["review_priority"]:
        console.print("[bold]Review Priorities:[/bold]")
        for i, item in enumerate(analysis["review_priority"], start=1):
            console.print(f"{i}.")
            console.print(item)
        console.print()

    if analysis["warnings"]:
        console.print("[bold]Warnings:[/bold]")
        for warning in analysis["warnings"]:
            console.print(f"- {warning}")
        console.print()

    if analysis["advisories"]:
        console.print("[bold]Advisories:[/bold]")
        for advisory in analysis["advisories"]:
            console.print(f"- {advisory}")
        console.print()

    console.print(f"[bold]Confidence:[/bold] {analysis['confidence']}")
    console.print()

    if save_result is not None:
        console.print(f"[green]analysis snapshot saved[/green]: {save_result['history_path']} (snapshot {save_result['snapshot_count']})")
        console.print()

    console.print("No slicer was opened.")
    console.print("No G-code was generated.")
    console.print("No print was started.")


def _timeline_icon(event: dict) -> str:
    if event["status"] == "unavailable":
        return "?"
    return "⚠" if event["severity"] in ("warning", "blocked") else "✓"


def _timeline_day_heading(date_str: str) -> str:
    from datetime import datetime

    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d")
    except ValueError:
        return date_str


@app.command(name="timeline")
def timeline_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory (see factory init-project)"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Unified Project Timeline (Phase 40) - the Factory's project memory: a read-only,
    chronological event log derived entirely from systems that already exist
    (generation/export/slicer-readiness/manual-review-workspace receipts and the Phase 39
    slicer analysis history) - never a new receipt or history format of its own. Entirely
    read-only - there is no write flag. Never re-derives readiness, approval, or risk; it only
    normalizes timestamps and facts those systems already computed into one chronological view.
    A stage a project has clearly reached but has no recorded timestamp for (any project created
    before this phase shipped) is shown explicitly as date-unavailable, never silently omitted.
    See docs/project-timeline.md."""
    if not project_dir.is_dir():
        message = f"not a directory: {project_dir}"
        if as_json:
            print(json.dumps({"errors": [message], "no_automatic_print": True}, indent=2, sort_keys=False))
        else:
            console.print(f"[red]error[/red]: {message}")
        raise typer.Exit(code=1)

    events = get_project_timeline_for_path(project_dir)

    if as_json:
        print(json.dumps({"events": events, "errors": [], "no_automatic_print": True}, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return

    console.print("[bold]Project Timeline[/bold]\n")

    undated = [e for e in events if e["date"] is None]
    if undated:
        console.print("[bold]Date unavailable[/bold]\n")
        for e in undated:
            console.print(f"{_timeline_icon(e)} {e['label']}")
        console.print()

    last_date = None
    for e in events:
        if e["date"] is None:
            continue
        if e["date"] != last_date:
            console.print(f"[bold]{_timeline_day_heading(e['date'])}[/bold]\n")
            last_date = e["date"]
        console.print(f"{_timeline_icon(e)} {e['label']}")

    if not events:
        console.print("No timeline events recorded yet for this project.")

    console.print("\nThis is a read-only view of existing receipts - it never writes, generates, exports,")
    console.print("validates, invokes a slicer, or contacts a printer/network.")


@app.command(name="artifact-history")
def artifact_history_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory (see factory init-project)"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Artifact History (Phase 41) - a derived, read-only artifact version history built
    directly on Phase 40's unified timeline. Entirely read-only - there is no write flag.
    Version numbers are the 1-based ordinal of each artifact-relevant timeline event
    (CAD/export/validation/preview/approval/package/workspace), in chronological order -
    never a stored counter, never a second fingerprinting system. Artifact History is a VIEW
    over existing receipts; if it ever disagrees with one, the receipt is correct. See
    docs/artifact-history.md."""
    if not project_dir.is_dir():
        message = f"not a directory: {project_dir}"
        if as_json:
            print(json.dumps({"errors": [message], "no_automatic_print": True}, indent=2, sort_keys=False))
        else:
            console.print(f"[red]error[/red]: {message}")
        raise typer.Exit(code=1)

    history = get_artifact_history_for_path(project_dir)

    if as_json:
        print(json.dumps({"versions": history, "errors": [], "no_automatic_print": True}, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return

    console.print("[bold]Artifact History[/bold]\n")
    console.print("[bold]Project:[/bold]")
    console.print(project_dir.name)
    console.print()

    if not history:
        console.print("No artifact versions recorded yet for this project.")
    for version in history:
        console.print(f"[bold]Version {version['version_id']}[/bold]\n")
        console.print(version["source_event_label"])
        console.print()
        for category, paths in version["artifacts"].items():
            console.print(f"[bold]{category.replace('_', ' ').title()}:[/bold]")
            for p in paths:
                console.print(p)
            console.print()
        console.print(f"[bold]Validation:[/bold] {version['validation_state']}")
        console.print(f"[bold]Preview:[/bold] {version['preview_state']}")
        console.print(f"[bold]Review:[/bold] {version['review_state']}")
        console.print()

    console.print("This is a read-only view - it never writes, restores, copies, or deletes a file,")
    console.print("and never invokes a slicer or contacts a printer/network.")


@app.command(name="artifact-diff")
def artifact_diff_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory (see factory init-project)"),
    from_version: int = typer.Option(..., "--from", help="The earlier version number to compare from"),
    to_version: int = typer.Option(..., "--to", help="The later version number to compare to"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Artifact Diff (Phase 41) - compares two artifact versions (see `factory
    artifact-history`). Entirely read-only - never recomputes a fingerprint, never re-runs
    validation/rendering, never invokes a slicer. Reuses each version's already-derived
    fingerprint set and Phase 39/40's own already-detected material/printer/risk/warning
    changes rather than duplicating comparison logic. See docs/artifact-history.md."""
    if not project_dir.is_dir():
        message = f"not a directory: {project_dir}"
        if as_json:
            print(json.dumps({"errors": [message], "no_automatic_print": True}, indent=2, sort_keys=False))
        else:
            console.print(f"[red]error[/red]: {message}")
        raise typer.Exit(code=1)

    try:
        diff = diff_artifact_versions(project_dir, from_version, to_version)
    except UnknownVersionError as exc:
        message = str(exc)
        if as_json:
            print(json.dumps({"errors": [message], "no_automatic_print": True}, indent=2, sort_keys=False))
        else:
            console.print(f"[red]error[/red]: {message}")
        raise typer.Exit(code=1)

    if as_json:
        payload = dict(diff)
        payload["errors"] = []
        print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return

    console.print("[bold]Artifact Difference[/bold]\n")
    console.print("[bold]Changed:[/bold]")
    for item in diff["changed"]:
        console.print(f"⚠ {item}")
    if not diff["changed"]:
        console.print("None.")
    console.print()
    console.print("[bold]Unchanged:[/bold]")
    for item in diff["unchanged"]:
        console.print(f"✓ {item}")
    console.print()
    console.print("[bold]Impact:[/bold]")
    console.print(diff["impact"])
    console.print()
    console.print("This is a read-only comparison - it never writes, restores, copies, or deletes a file,")
    console.print("and never invokes a slicer or contacts a printer/network.")


@app.command(name="artifact-rollback-plan")
def artifact_rollback_plan_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory (see factory init-project)"),
    to_version: int = typer.Option(..., "--to", help="The version number a rollback plan would target"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Rollback Plan (Phase 41) - a REPORT ONLY of what a rollback to an earlier artifact
    version would affect. It does NOT restore, copy, or delete any file, and does NOT modify
    any manifest - there is no write path in this command at all. Actual file restoration
    would be a future, separately-approved capability. See docs/artifact-history.md."""
    if not project_dir.is_dir():
        message = f"not a directory: {project_dir}"
        if as_json:
            print(json.dumps({"errors": [message], "no_automatic_print": True}, indent=2, sort_keys=False))
        else:
            console.print(f"[red]error[/red]: {message}")
        raise typer.Exit(code=1)

    try:
        plan = build_rollback_plan(project_dir, to_version)
    except UnknownVersionError as exc:
        message = str(exc)
        if as_json:
            print(json.dumps({"errors": [message], "no_automatic_print": True}, indent=2, sort_keys=False))
        else:
            console.print(f"[red]error[/red]: {message}")
        raise typer.Exit(code=1)

    if as_json:
        payload = dict(plan)
        payload["errors"] = []
        print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return

    console.print("[bold]Rollback Plan[/bold]\n")
    console.print("[bold]Current:[/bold]")
    console.print(f"Version {plan['current_version']}")
    console.print()
    console.print("[bold]Target:[/bold]")
    console.print(f"Version {plan['target_version']}")
    console.print()
    console.print("[bold]Would affect:[/bold]")
    for item in plan["would_affect"]:
        console.print(f"⚠ {item}")
    if not plan["would_affect"]:
        console.print("None.")
    console.print()
    console.print("[bold]Would not affect:[/bold]")
    for item in plan["would_not_affect"]:
        console.print(f"✓ {item}")
    console.print()
    console.print("[bold]Action:[/bold]")
    console.print(plan["action"])
    console.print()
    console.print("No files were restored. No files were copied. No files were deleted.")
    console.print("No manifest was modified. No slicer was opened. No print was started.")


@app.command(name="health")
def health_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory (see factory init-project)"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
    verbose: bool = typer.Option(False, "--verbose", help="Show category score breakdown, full blocker/warning/risk detail, and recent activity"),
) -> None:
    """Project Health Dashboard (Phase 42) - one unified, read-only view of a project's
    current state, aggregating existing Factory intelligence (Phases 13, 26-41). This
    command never recalculates readiness, never duplicates risk/validation/artifact
    logic, and never overrides an existing blocker - `health_score` is purely
    informational and can never mask a `Status: Blocked` result. Entirely read-only -
    there is no write flag; never invokes a slicer, generates G-code, or contacts a
    printer/network. See docs/project-health.md."""
    if not project_dir.is_dir():
        message = f"not a directory: {project_dir}"
        if as_json:
            print(json.dumps({"errors": [message], "no_automatic_print": True}, indent=2, sort_keys=False))
        else:
            console.print(f"[red]error[/red]: {message}")
        raise typer.Exit(code=1)

    health = evaluate_project_health_for_path(project_dir)

    if as_json:
        payload = dict(health)
        payload["errors"] = []
        print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return

    console.print("[bold]PROJECT HEALTH[/bold]\n")
    console.print(f"[bold]{health['project']}[/bold]\n")
    console.print("[bold]Status:[/bold]")
    console.print(health["overall_status"])
    console.print()
    console.print("[bold]Health:[/bold]")
    console.print(f"{health['health_score']}% ({health['health_level']})")
    console.print()
    console.print("[bold]Lifecycle:[/bold]")
    console.print(health["lifecycle_stage"])
    console.print()
    console.print("[bold]Completion:[/bold]")
    console.print(f"{health['completion_percentage']}%")
    console.print()
    console.print("[bold]Blockers:[/bold]")
    console.print(str(len(health["blockers"])))
    console.print()
    console.print("[bold]Warnings:[/bold]")
    console.print(str(len(health["warnings"])))
    console.print()
    console.print("[bold]Risks:[/bold]")
    console.print(str(len(health["risks"])))
    console.print()
    console.print("[bold]Next Action:[/bold]")
    console.print(health["next_action"])
    console.print()

    if verbose:
        console.print("[bold]Health score breakdown:[/bold]")
        for category, score in health["health_score_categories"].items():
            console.print(f"  {category.replace('_', ' ').title()}: {score}%")
        console.print()

        if health["blockers"]:
            console.print("[bold]Blocker detail:[/bold]")
            for item in health["blockers"]:
                console.print(_rich_escape(f"⚠ ({item['source']}) {item['message']}"))
            console.print()

        if health["warnings"]:
            console.print("[bold]Warning detail:[/bold]")
            for item in health["warnings"]:
                console.print(_rich_escape(f"⚠ ({item['source']}) {item['message']}"))
            console.print()

        if health["risks"]:
            console.print("[bold]Risk detail:[/bold]")
            for item in health["risks"]:
                console.print(_rich_escape(f"⚠ ({item['category']}) {item['message']}"))
            console.print()

        if health["strengths"]:
            console.print("[bold]Strengths:[/bold]")
            for message in health["strengths"]:
                console.print(f"✓ {message}")
            console.print()

        console.print("[bold]Recent Activity:[/bold]")
        if health["recent_activity"]:
            for event in health["recent_activity"]:
                icon = "⚠" if event["severity"] in ("warning", "blocked") else "✓"
                console.print(f"{icon} {event['label']}")
        else:
            console.print("No dated timeline events recorded yet for this project.")
        console.print()

        artifact = health["artifact_summary"]
        console.print("[bold]Artifact History:[/bold]")
        if artifact.get("history_available"):
            console.print(f"  Latest version: v{artifact['latest_version']}")
            changed = artifact.get("changed_since_previous")
            if changed:
                console.print(f"  Recent changes: {', '.join(changed)}")
            elif changed is not None:
                console.print("  Recent changes: None")
        else:
            console.print("  No artifact versions recorded yet.")
        console.print()

    console.print(f"Confidence: {health['confidence']}")
    console.print()
    console.print("This is a read-only aggregation of existing Factory intelligence - it never")
    console.print("recalculates readiness, never overrides a blocker, and never writes anything.")
    console.print("Human approval required. No automatic printing.")


_ENGINE_DISPLAY_GROUP_LABELS = {
    "design_cad": "DESIGN / CAD",
    "cloud": "CLOUD",
    "slicers": "SLICERS",
    "future": "FUTURE",
}

_ENGINE_SAFETY_TRAILER = (
    "No tools were installed, upgraded, launched, or executed.",
    "No slicer was run. No G-code was created. No printer was contacted.",
    "Automatic printing remains disabled.",
)


def _render_engines_human(data: dict[str, Any], *, probed: bool) -> None:
    console.print("[bold]FACTORY ENGINE REGISTRY[/bold]\n")
    tools = data["tools"]
    for group in data["categories"]:
        console.print(f"[bold]{_ENGINE_DISPLAY_GROUP_LABELS.get(group, group.upper())}[/bold]\n")
        for tool in tools.values():
            if tool["display_group"] != group:
                continue
            console.print(f"[bold]{_rich_escape(tool['display_name'])}[/bold]")
            console.print(f"  Status: {tool['roadmap_status']}")
            if probed:
                console.print(f"  Detected: {'yes' if tool['detected'] else 'no'}")
                if tool["detected"]:
                    console.print(f"  Path: {tool['detected_path'] or 'unknown'}")
                    console.print(f"  Version: {tool['detected_version']}")
                    if tool["detected_channel"] != "unknown":
                        console.print(f"  Channel: {tool['detected_channel']}")
            console.print(f"  Execution: {tool['execution_status']}")
            console.print(f"  Qualification: {tool['qualification_status']}")
            if tool["network_required"]:
                console.print("  Network: required")
            if tool["possible_monetary_cost"]:
                console.print("  Cost: possible")
            if tool["human_approval_required"]:
                console.print("  Human approval: required")
            console.print()

    summary = data["summary"]
    console.print("[bold]Summary:[/bold]")
    console.print(
        f"  Core local tools detected: {summary['core_local_tools_detected']}/{summary['core_local_tools_total']}"
    )
    console.print(f"  Slicers detected: {summary['slicers_detected']}/{summary['slicers_total']}")
    console.print(f"  Near-term engines detected: {summary['near_term_tools_detected']}/{summary['near_term_tools_total']}")
    console.print(f"  Cloud engines gated: {summary['cloud_tools_gated']}/{summary['cloud_tools_total']}")
    console.print()

    for line in _ENGINE_SAFETY_TRAILER:
        console.print(line)


engines_app = typer.Typer(
    name="engines",
    help=(
        "Factory Engine Registry (Phase 43) - the canonical, read-only inventory of local/cloud "
        "design, CAD, slicer, and future tool integrations. `factory engines` shows the static "
        "registry (no local detection); `factory engines probe` additionally runs safe, read-only "
        "local detection (filesystem/PATH checks, package metadata, and a single bounded `openscad "
        "--version` call). Never installs, upgrades, or launches anything; never executes Blender/"
        "FreeCAD/a slicer/Meshy; never contacts a printer or cloud service. See docs/engine-registry.md."
    ),
    invoke_without_command=True,
)
app.add_typer(engines_app, name="engines")


@engines_app.callback(invoke_without_command=True)
def engines_default_cmd(
    ctx: typer.Context,
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Registry view only - does not probe the local environment (see `factory engines probe`)."""
    if ctx.invoked_subcommand is not None:
        return
    data = summarize_engine_registry(probe=False)
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return
    _render_engines_human(data, probed=False)


@engines_app.command(name="probe")
def engines_probe_cmd(
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Registry view plus safe, read-only local detection: known `.app` bundle paths, `PATH`
    binaries, Python package metadata, and a single bounded `openscad --version` call. Never
    installs, upgrades, or launches a GUI application; never executes Blender/FreeCAD/a slicer;
    never contacts a network. See docs/engine-registry.md."""
    data = summarize_engine_registry(probe=True, include_version_subprocess=True)
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return
    _render_engines_human(data, probed=True)


_QUALIFICATION_CHECK_ICONS = {"pass": "[green]OK[/green]", "warn": "[yellow]WARN[/yellow]", "fail": "[red]FAIL[/red]", "skip": "-"}

_QUALIFICATION_SAFETY_TRAILER = (
    "No software was installed or upgraded.",
    "No GUI application was launched.",
    "No slicer was executed and no G-code was generated.",
    "No printer was contacted. No network call was made.",
    "Automatic printing remains disabled.",
)


def _render_qualification_human(report: dict[str, Any], *, verbose: bool) -> None:
    console.print("[bold]LOCAL TOOL QUALIFICATION[/bold]\n")
    for result in report["results"]:
        console.print(f"[bold]{_rich_escape(result['display_name'])}[/bold]\n")
        console.print("Detected:")
        console.print("Yes" if result["detected"] else "No")
        console.print()
        if result["detected"] and result["detected_version"] != "unknown":
            console.print("Version:")
            console.print(result["detected_version"])
            console.print()

        if verbose and result["checks"]:
            console.print("Checks:")
            for check in result["checks"]:
                icon = _QUALIFICATION_CHECK_ICONS.get(check["status"], "?")
                evidence = f" - {_rich_escape(check['evidence'])}" if check["evidence"] else ""
                console.print(f"{icon} {_rich_escape(check['label'])}{evidence}")
            console.print()

        console.print("Qualification:")
        console.print(result["qualification_status"].replace("_", " ").title())
        console.print("Level:")
        console.print(result["qualification_level"].replace("_", " ").title())
        console.print()

        console.print("Execution:")
        console.print("Approved" if result["execution_approved"] else "Not Approved")
        console.print()

        if verbose:
            for warning in result["warnings"]:
                console.print(f"[yellow]warning[/yellow]: {_rich_escape(warning)}")
            for error in result["errors"]:
                console.print(f"[red]error[/red]: {_rich_escape(error)}")
            if result["warnings"] or result["errors"]:
                console.print()

    summary = report["summary"]
    console.print("[bold]Summary:[/bold]")
    console.print(f"  Total tools: {summary['total_tools']}")
    console.print(f"  Qualification scope: {summary['qualification_scope']}")
    console.print(f"  Qualified: {summary['qualified']}")
    console.print(f"  Partially qualified: {summary['partially_qualified']}")
    console.print(f"  Unqualified: {summary['unqualified']}")
    console.print(f"  Not installed: {summary['not_installed']}")
    console.print(f"  Manual required: {summary['manual_required']}")
    console.print(f"  Cloud gated: {summary['cloud_gated']}")
    console.print(f"  Unsupported (deferred): {summary['unsupported']}")
    console.print(f"  Failed: {summary['failed']}")
    console.print(f"  Execution approved: {summary['execution_approved']}")
    console.print()
    for line in _QUALIFICATION_SAFETY_TRAILER:
        console.print(line)


@engines_app.command(name="qualify")
def engines_qualify_cmd(
    tool_id: Optional[str] = typer.Argument(
        None, help="Qualify only this tool_id (see `factory engines` for the full list); omit to qualify every registered tool"
    ),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
    verbose: bool = typer.Option(False, "--verbose", help="Show every recorded check and any warnings/errors"),
) -> None:
    """Phase 44: safe, evidence-based local tool qualification. Detection (Phase 43) is not
    qualification, and qualification is not execution approval - `execution_approved` stays
    `false` on every result, regardless of qualification level. OpenSCAD is the only tool
    qualified end-to-end (a temporary SCAD fixture exported to STL and validated by the
    existing Factory mesh validator, in a `tempfile.TemporaryDirectory()` that is always
    cleaned up); Blender/FreeCAD/every slicer stop at metadata-only (no subprocess is ever
    invoked for them - see docs/tool-qualification.md); Meshy/Plasticity/Fusion/Onshape/Bambu
    Connect are never qualified in this phase. Never installs, upgrades, or launches a GUI
    application; never contacts a printer or network. See docs/tool-qualification.md."""
    if tool_id is not None and tool_id not in engine_registry.TOOL_IDS:
        message = f"unknown tool_id: {tool_id!r}. Known tool ids: {', '.join(engine_registry.TOOL_IDS)}"
        if as_json:
            print(json.dumps({"errors": [message]}, indent=2))
        else:
            console.print(f"[red]error[/red]: {message}")
        raise typer.Exit(code=1)

    try:
        report = build_qualification_report(tool_id=tool_id)
    except UnknownToolError as exc:
        if as_json:
            print(json.dumps({"errors": [str(exc)]}, indent=2))
        else:
            console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)

    if as_json:
        print(json.dumps(report, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return
    _render_qualification_human(report, verbose=verbose)


_BLENDER_SAFETY_TRAILER = (
    "No Blender GUI was launched. No add-on was installed. No project file was modified.",
    "No slicer was contacted. No G-code was generated. No printer was contacted. No print was started.",
    "This is fixture-qualification evidence only - it is not project execution approval. See docs/blender-adapter.md.",
)


def _render_blender_human(report: dict[str, Any], *, verbose: bool) -> None:
    gate = report["gate"]
    qualification = report["qualification"]
    console.print("[bold]BLENDER EXECUTION GATE[/bold]\n")

    console.print("[bold]Detected:[/bold]")
    console.print("Yes" if qualification["detected"] else "No")
    console.print()

    if qualification["detected"]:
        console.print("[bold]Version:[/bold]")
        console.print(qualification["detected_version"])
        console.print()

    console.print("[bold]Headless runtime:[/bold]")
    console.print(qualification["headless_runtime_status"].replace("_", " ").title())
    console.print()

    console.print("[bold]Fixture execution:[/bold]")
    console.print(qualification["fixture_execution_status"].replace("_", " ").title())
    console.print()

    console.print("[bold]Adapter:[/bold]")
    console.print(qualification["adapter_qualification_status"].replace("_", " ").title())
    console.print()

    console.print("[bold]Execution approval:[/bold]")
    console.print("No")
    console.print()

    if qualification["adapter_qualification_status"] != "qualified":
        console.print("[bold]Next:[/bold]")
        if not qualification["detected"]:
            console.print("Install Blender is a human decision this repo never makes; not detected locally.")
        elif qualification["fixture_execution_status"] == "not_run":
            console.print("Run explicit temporary fixture qualification: `factory blender qualify --confirm-fixture`.")
        else:
            console.print("Review the errors/warnings below before retrying.")
        console.print()

    if verbose:
        console.print("[bold]Checks:[/bold]")
        for check in qualification["fixture_checks"]:
            icon = {"pass": "[green]OK[/green]", "warn": "[yellow]WARN[/yellow]", "fail": "[red]FAIL[/red]", "skip": "[dim]SKIP[/dim]"}[check["status"]]
            console.print(f"  {icon}  {_rich_escape(check['label'])} - {_rich_escape(check['evidence'])}")
        console.print()

        if qualification["warnings"]:
            console.print("[bold]Warnings:[/bold]")
            for warning in qualification["warnings"]:
                console.print(f"  - {_rich_escape(warning)}")
            console.print()

        if qualification["errors"]:
            console.print("[bold]Errors:[/bold]")
            for error in qualification["errors"]:
                console.print(f"  - {_rich_escape(error)}")
            console.print()

        console.print("[bold]Gate checklist:[/bold]")
        for item in gate["gate_checklist"]:
            marker = {"satisfied": "[green]OK[/green]", "partially_satisfied": "[yellow]PARTIAL[/yellow]", "deferred": "[dim]DEFERRED[/dim]", "unsatisfied": "[red]UNSATISFIED[/red]"}.get(item["status"], item["status"])
            console.print(f"  {marker}  {_rich_escape(item['item'])}")
            console.print(f"      {_rich_escape(item['note'])}")
        console.print()

    for line in _BLENDER_SAFETY_TRAILER:
        console.print(line)


blender_app = typer.Typer(
    name="blender",
    help=(
        "Blender Local Execution Gate & Adapter (Phase 45) - the first controlled local Blender "
        "execution path, narrowly scoped to one Factory-owned qualification fixture "
        "(`fixture_organic_model`). `factory blender inspect` is fully read-only (zero subprocess "
        "calls). `factory blender qualify` runs one bounded, real, Python-free `blender --background "
        "--version` headless check; only `factory blender qualify --confirm-fixture` additionally "
        "runs the full fixture pipeline (a fixed sphere exported to a temporary STL, validated by "
        "the existing Factory mesh validator, and previewed by the existing Factory preview "
        "renderer). Never installs, upgrades, or GUI-launches Blender; never installs an add-on; "
        "never contacts a slicer, printer, or network. `project_execution_approved` is always "
        "`false` - qualifying the adapter is evidence, never approval to generate real project "
        "geometry. See docs/blender-adapter.md."
    ),
)
app.add_typer(blender_app, name="blender")


@blender_app.command(name="inspect")
def blender_inspect_cmd(
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Fully read-only: Blender detection (Phase 43), the Phase 45 gate checklist reconciliation,
    and the dry-run fixture-execution plan. Never calls subprocess, never launches anything."""
    gate = evaluate_blender_execution_gate()

    if as_json:
        print(json.dumps(gate, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return

    console.print("[bold]BLENDER GATE INSPECTION[/bold]\n")
    console.print(f"[bold]Detected:[/bold] {'Yes' if gate['detected'] else 'No'}")
    if gate["detected"]:
        console.print(f"[bold]Path:[/bold] {gate['detected_path']}")
        console.print(f"[bold]Version:[/bold] {gate['detected_version']}")
    console.print(f"[bold]Gate status:[/bold] {gate['gate_status']}")
    console.print(f"[bold]Supported workflows:[/bold] {', '.join(gate['supported_workflows'])}")
    console.print()

    console.print("[bold]Gate checklist:[/bold]")
    for item in gate["gate_checklist"]:
        marker = {"satisfied": "[green]OK[/green]", "partially_satisfied": "[yellow]PARTIAL[/yellow]", "deferred": "[dim]DEFERRED[/dim]", "unsatisfied": "[red]UNSATISFIED[/red]"}.get(item["status"], item["status"])
        console.print(f"  {marker}  {_rich_escape(item['item'])}")
        console.print(f"      {_rich_escape(item['note'])}")
    console.print()

    for line in _BLENDER_SAFETY_TRAILER:
        console.print(line)


@blender_app.command(name="qualify")
def blender_qualify_cmd(
    confirm_fixture: bool = typer.Option(
        False, "--confirm-fixture", help="Explicit confirmation to actually run the one-shot, temp-dir-only Blender fixture pipeline"
    ),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
    verbose: bool = typer.Option(False, "--verbose", help="Show every recorded check, warning/error, and the gate checklist"),
) -> None:
    """Phase 45: Blender local execution gate + adapter qualification. Without --confirm-fixture,
    runs one bounded, real, Python-free `blender --background --version` headless check only - no
    fixture is created. With --confirm-fixture, additionally runs the full bounded fixture pipeline
    (temp dir only, one Blender invocation running exactly one Factory-owned script, Factory
    validator/preview reuse, verified cleanup). `project_execution_approved` is always `false`
    regardless of outcome - see docs/blender-adapter.md."""
    report = build_blender_report(confirm_fixture=confirm_fixture)

    if as_json:
        print(json.dumps(report, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return
    _render_blender_human(report, verbose=verbose)


workflow_app = typer.Typer(
    name="workflow",
    help=(
        "Hybrid Design Workflow Manager (Phase 48) - the planning layer between a generative-AI "
        "concept (Meshy) or CAD-generated artifact and manufacturing-ready Factory output. "
        "Read-only and fully offline: never calls Meshy, never launches Blender or a CAD backend, "
        "never invokes a slicer, never rescales or repairs a mesh. `automatic_execution_allowed` is "
        "always `false` on every plan. See docs/hybrid-workflow.md."
    ),
)
app.add_typer(workflow_app, name="workflow")


@workflow_app.command(name="plan")
def workflow_plan_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory under projects/"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Phase 48: the full adaptation plan for one project's existing input artifact (a Meshy
    receipt or a CAD generation/export receipt) - workflow classification, tool routing, scale
    assessment, manufacturing intent, and required human confirmations. Read-only: re-runs the
    existing Factory mesh validator against the already-recorded artifact path, never a new one.
    Never modifies anything; never contacts Meshy, Blender, a CAD backend, a slicer, or a printer."""
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        console.print(f"[red]error[/red]: not a directory: {project_dir}")
        raise typer.Exit(code=1)
    plan = build_adaptation_plan(project_dir)

    if as_json:
        print(json.dumps(plan, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return

    console.print("[bold]HYBRID WORKFLOW PLAN[/bold]\n")
    console.print(f"[bold]Artifact type:[/bold] {plan['artifact_type']}")
    console.print(f"[bold]Workflow type:[/bold] {plan['workflow_type']}")
    console.print(f"[bold]Recommended engine:[/bold] {plan['recommended_engine'] or '(none)'}")
    console.print(f"[bold]Manufacturing readiness:[/bold] {plan['manufacturing_readiness']}\n")
    if plan["issues_found"]:
        console.print("[bold]Issues found:[/bold]")
        for issue in plan["issues_found"]:
            console.print(f"  - {_rich_escape(issue)}")
        console.print()
    if plan["adaptation_steps"]:
        console.print("[bold]Adaptation steps (planned, not executed):[/bold]")
        for step in plan["adaptation_steps"]:
            console.print(f"  - {step['step']} (tool: {step.get('tool') or step.get('candidate_tools')})")
        console.print()
    console.print("Automatic execution is impossible. Human confirmation required for every step above.")


@workflow_app.command(name="assess")
def workflow_assess_cmd(
    artifact_path: Path = typer.Argument(..., help="Path to a mesh file (.stl, .obj, .ply, ...)"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Phase 48: a lightweight, standalone assessment of one mesh file - validation status, mesh
    stats, and a scale-plausibility read - without needing a project or receipt. Read-only; never
    modifies the file."""
    result = assess_artifact_file(artifact_path)

    if as_json:
        print(json.dumps(result, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return

    console.print("[bold]ARTIFACT ASSESSMENT[/bold]\n")
    if result["error"]:
        console.print(f"[red]error[/red]: {result['error']}")
        raise typer.Exit(code=1)
    console.print(f"[bold]Validation:[/bold] {_icon(result['validation_overall_status'])}")
    scale = result["scale_assessment"]
    console.print(f"[bold]Current dimensions (mm):[/bold] {scale['current_dimensions_mm']}")
    console.print(f"[bold]Scale confidence:[/bold] {scale['confidence']} - {scale['reason']}")
    console.print("\nA human must confirm any target dimensions before scaling. Automatic execution is impossible.")


_BLENDER_ADAPT_SAFETY_TRAILER = (
    "This is a Blender adaptation execution gate, not manufacturing approval.",
    "AI output != manufacturing ready. Blender output != approved product. Validation != human approval.",
    "Human approval != print approval. Automatic printing remains impossible.",
)


blender_adapt_app = typer.Typer(
    name="blender-adapt",
    help=(
        "Blender Adaptation Execution Gate & Controlled Organic Cleanup Workflow (Phase 49) - the first "
        "real Blender execution against a real project artifact in this repo, narrowly scoped to exactly "
        "one workflow (`organic_cleanup_workflow`: import a Meshy/CAD-origin STL, apply one explicit "
        "uniform scale factor, export a new child STL - never mesh repair, remeshing, decimation, or "
        "smoothing). `factory blender-adapt plan` is fully read-only. `factory blender-adapt execute "
        "--confirm` re-checks Blender detection, runs a FRESH full fixture-qualification proof, and "
        "requires explicit human confirmation on every single call - nothing is cached or persisted "
        "between calls. Never overwrites the input artifact or an existing output; never contacts a "
        "slicer, printer, or network. See docs/blender-adaptation.md."
    ),
)
app.add_typer(blender_adapt_app, name="blender-adapt")


def _render_blender_adapt_plan_human(plan: dict[str, Any]) -> None:
    console.print("[bold]BLENDER ADAPTATION PLAN[/bold]\n")
    console.print(f"[bold]Input artifact:[/bold] {plan['input_artifact']}")
    console.print(f"[bold]Project:[/bold] {plan['project'] or '(none - not under projects/<slug>/)'}")
    console.print(f"[bold]Source engine:[/bold] {plan['source_engine']}")
    console.print(f"[bold]Workflow:[/bold] {plan['workflow_type']}")
    console.print(f"[bold]Blender gate status:[/bold] {plan['blender_gate_status']}")
    console.print(f"[bold]Operations (planned, not executed):[/bold] {', '.join(plan['adaptation_operations'])}")
    console.print(f"[bold]Current dimensions (mm):[/bold] {plan['current_dimensions_mm']}")
    console.print(f"[bold]Proposed scale factor:[/bold] {plan['proposed_scale_factor']}")
    console.print(f"[bold]Output artifact (would create):[/bold] {plan['output_artifact']}")
    console.print(f"[bold]Execution allowed:[/bold] {plan['execution_allowed']}\n")
    if plan["issues_found"]:
        console.print("[bold]Issues found:[/bold]")
        for issue in plan["issues_found"]:
            console.print(f"  - {_rich_escape(issue)}")
        console.print()
    for line in _BLENDER_ADAPT_SAFETY_TRAILER:
        console.print(line)


@blender_adapt_app.command(name="plan")
def blender_adapt_plan_cmd(
    artifact_path: Path = typer.Argument(..., help="Path to a mesh file (.stl) - typically an existing generated/meshy/processed/<id>.stl artifact"),
    target_max_mm: float = typer.Option(None, "--target-max-mm", help="Optional: the desired largest bounding-box dimension (mm) after adaptation"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Phase 49: a fully read-only dry-run plan for adapting one artifact via `organic_cleanup_workflow`
    - never launches Blender, never writes anything. Reuses `factory.hybrid_workflow.assess_scale()` and
    `factory.blender_gate.plan_organic_cleanup_execution()` rather than a second scale/gate model."""
    plan = build_adaptation_execution_plan(artifact_path, target_max_dimension_mm=target_max_mm)

    if as_json:
        payload = {"plan": plan, "safety": build_blender_adaptation_safety_block()}
        print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return
    _render_blender_adapt_plan_human(plan)


@blender_adapt_app.command(name="execute")
def blender_adapt_execute_cmd(
    artifact_path: Path = typer.Argument(..., help="Path to a mesh file (.stl) under an existing projects/<slug>/ directory"),
    target_max_mm: float = typer.Option(..., "--target-max-mm", help="Required: the desired largest bounding-box dimension (mm) after adaptation - never inferred automatically"),
    confirm: bool = typer.Option(False, "--confirm", help="Explicit, per-invocation human confirmation - required to actually execute"),
    confirmed_by: str = typer.Option(None, "--confirmed-by", help="Optional: who confirmed this execution, recorded in the receipt"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Phase 49: the gated, real execution of `organic_cleanup_workflow` against one project artifact.
    Without --confirm, always blocked (same dry-run-by-default convention as every other confirmed-write
    command in this repo). With --confirm, re-verifies Blender detection, runs a FRESH full
    fixture-qualification proof (never trusts a prior run), then imports the input STL, applies one
    explicit uniform scale factor, and exports a new child STL under generated/blender/adapted/ - never
    overwriting the input artifact or an existing output. Writes generated/blender_adaptation_receipt.json
    only on success. See docs/blender-adaptation.md."""
    result = run_blender_organic_cleanup_workflow(
        artifact_path, target_max_dimension_mm=target_max_mm, confirm=confirm, confirmed_by=confirmed_by
    )

    if as_json:
        payload = {"result": result, "safety": build_blender_adaptation_safety_block()}
        print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        if result["organic_cleanup_status"] != "succeeded":
            raise typer.Exit(code=1)
        return

    console.print("[bold]BLENDER ADAPTATION EXECUTION[/bold]\n")
    console.print(f"[bold]Status:[/bold] {result['organic_cleanup_status']}")
    if result.get("errors"):
        console.print("[bold]Errors:[/bold]")
        for error in result["errors"]:
            console.print(f"  - {_rich_escape(error)}")
    if result["organic_cleanup_status"] == "succeeded":
        console.print(f"[bold]Output artifact:[/bold] {result['output_artifact']}")
        console.print(f"[bold]Receipt:[/bold] {result['receipt_path']}")
    console.print()
    for line in _BLENDER_ADAPT_SAFETY_TRAILER:
        console.print(line)
    if result["organic_cleanup_status"] != "succeeded":
        raise typer.Exit(code=1)


_CAD_AUGMENT_SAFETY_TRAILER = (
    "This is a CAD augmentation execution gate, not engineering approval.",
    "AI concept != engineering design. CAD output != manufacturing approved. Validation != human approval.",
    "Human approval != print approval. Automatic printing remains impossible.",
)


def _cad_augment_params(
    base_width_mm, base_length_mm, base_height_mm,
    coin_slot_width_mm, coin_slot_length_mm, coin_slot_depth_mm,
    coin_slot_position_x_mm, coin_slot_position_y_mm,
    mounting_hole_diameter_mm, mounting_hole_margin_mm,
) -> dict[str, float | None]:
    return {
        "base_width_mm": base_width_mm,
        "base_length_mm": base_length_mm,
        "base_height_mm": base_height_mm,
        "coin_slot_width_mm": coin_slot_width_mm,
        "coin_slot_length_mm": coin_slot_length_mm,
        "coin_slot_depth_mm": coin_slot_depth_mm,
        "coin_slot_position_x_mm": coin_slot_position_x_mm,
        "coin_slot_position_y_mm": coin_slot_position_y_mm,
        "mounting_hole_diameter_mm": mounting_hole_diameter_mm,
        "mounting_hole_margin_mm": mounting_hole_margin_mm,
    }


cad_augment_app = typer.Typer(
    name="cad-augment",
    help=(
        "CAD Augmentation Execution Gate & Organic-Mechanical Hybrid Workflow (Phase 50) - the "
        "controlled bridge from an already-adapted organic artifact to a manufacturing-ready hybrid "
        "product, narrowly scoped to exactly one workflow (`organic_mechanical_augmentation`: generate "
        "a parametric functional-feature part - a coin slot, mounting holes, a base plate - and export "
        "it as a new, separate STL, never a boolean-merge with the organic mesh). `factory cad-augment "
        "plan` is fully read-only. `factory cad-augment execute --confirm` requires every critical "
        "dimension explicitly, re-checks routing, and requires explicit human confirmation on every "
        "single call - nothing is cached or persisted between calls. Executes OpenSCAD only (the one "
        "engine in this repo with an existing, bounded, already-tested local execution path) - never "
        "executes CadQuery (this repo's standing policy) or FreeCAD (no execution path exists). Never "
        "overwrites the input artifact or an existing output; never contacts a slicer, printer, or "
        "network. See docs/cad-augmentation.md."
    ),
)
app.add_typer(cad_augment_app, name="cad-augment")


def _render_cad_augment_plan_human(plan: dict[str, Any]) -> None:
    console.print("[bold]CAD AUGMENTATION PLAN[/bold]\n")
    console.print(f"[bold]Input (organic) artifact:[/bold] {plan['input_artifact']}")
    console.print(f"[bold]Project:[/bold] {plan['project'] or '(none - not under projects/<slug>/)'}")
    console.print(f"[bold]Workflow:[/bold] {plan['workflow_type']}")
    console.print(f"[bold]Recommended CAD engine:[/bold] {plan['recommended_cad_engine'] or '(none)'}")
    console.print(f"[bold]Candidate engines:[/bold] {', '.join(plan['candidate_engines']) or '(none)'}")
    console.print(f"[bold]Operations (planned, not executed):[/bold] {', '.join(plan['cad_operations'])}")
    console.print(f"[bold]Output artifact (would create):[/bold] {plan['output_artifact']}")
    console.print(f"[bold]Execution allowed:[/bold] {plan['execution_allowed']}\n")
    if plan["requires_human_input"]:
        console.print("[bold]Missing required parameter(s):[/bold]")
        for name in plan["requires_human_input"]:
            console.print(f"  - {name}")
        console.print()
    if plan["issues_found"]:
        console.print("[bold]Issues found:[/bold]")
        for issue in plan["issues_found"]:
            console.print(f"  - {_rich_escape(issue)}")
        console.print()
    for line in _CAD_AUGMENT_SAFETY_TRAILER:
        console.print(line)


@cad_augment_app.command(name="plan")
def cad_augment_plan_cmd(
    artifact_path: Path = typer.Argument(..., help="Path to a mesh file (.stl) - typically an existing generated/blender/adapted/<name>_adapted.stl artifact"),
    base_width_mm: float = typer.Option(None, "--base-width-mm", help="Critical dimension: functional base plate width (mm)"),
    base_length_mm: float = typer.Option(None, "--base-length-mm", help="Critical dimension: functional base plate length (mm)"),
    base_height_mm: float = typer.Option(None, "--base-height-mm", help="Critical dimension: functional base plate height (mm)"),
    coin_slot_width_mm: float = typer.Option(None, "--coin-slot-width-mm", help="Optional coin slot: width (mm) - required together with length/depth if any is given"),
    coin_slot_length_mm: float = typer.Option(None, "--coin-slot-length-mm", help="Optional coin slot: length (mm)"),
    coin_slot_depth_mm: float = typer.Option(None, "--coin-slot-depth-mm", help="Optional coin slot: depth (mm) - >= base height cuts fully through"),
    coin_slot_position_x_mm: float = typer.Option(None, "--coin-slot-position-x-mm", help="Optional coin slot center X position (mm) - defaults to centered"),
    coin_slot_position_y_mm: float = typer.Option(None, "--coin-slot-position-y-mm", help="Optional coin slot center Y position (mm) - defaults to centered"),
    mounting_hole_diameter_mm: float = typer.Option(None, "--mounting-hole-diameter-mm", help="Optional: add 4 corner mounting holes of this diameter (mm)"),
    mounting_hole_margin_mm: float = typer.Option(8.0, "--mounting-hole-margin-mm", help="Distance of mounting hole centers from each edge (mm) - a placement convenience, not a critical dimension"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Phase 50: a fully read-only dry-run plan for augmenting one artifact via `organic_mechanical_augmentation`
    - never generates CAD source, never invokes OpenSCAD, never writes anything. Reuses
    `factory.engine_registry` for CAD routing rather than a second selector. Never guesses a critical
    dimension - any missing required parameter is reported in requires_human_input."""
    params = _cad_augment_params(
        base_width_mm, base_length_mm, base_height_mm,
        coin_slot_width_mm, coin_slot_length_mm, coin_slot_depth_mm,
        coin_slot_position_x_mm, coin_slot_position_y_mm,
        mounting_hole_diameter_mm, mounting_hole_margin_mm,
    )
    plan = build_augmentation_plan(artifact_path, **params)

    if as_json:
        payload = {"plan": plan, "safety": build_cad_augmentation_safety_block()}
        print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return
    _render_cad_augment_plan_human(plan)


@cad_augment_app.command(name="execute")
def cad_augment_execute_cmd(
    artifact_path: Path = typer.Argument(..., help="Path to a mesh file (.stl) under an existing projects/<slug>/ directory"),
    base_width_mm: float = typer.Option(..., "--base-width-mm", help="Required: functional base plate width (mm) - never inferred automatically"),
    base_length_mm: float = typer.Option(..., "--base-length-mm", help="Required: functional base plate length (mm) - never inferred automatically"),
    base_height_mm: float = typer.Option(..., "--base-height-mm", help="Required: functional base plate height (mm) - never inferred automatically"),
    coin_slot_width_mm: float = typer.Option(None, "--coin-slot-width-mm", help="Optional coin slot: width (mm) - required together with length/depth if any is given"),
    coin_slot_length_mm: float = typer.Option(None, "--coin-slot-length-mm", help="Optional coin slot: length (mm)"),
    coin_slot_depth_mm: float = typer.Option(None, "--coin-slot-depth-mm", help="Optional coin slot: depth (mm) - >= base height cuts fully through"),
    coin_slot_position_x_mm: float = typer.Option(None, "--coin-slot-position-x-mm", help="Optional coin slot center X position (mm) - defaults to centered"),
    coin_slot_position_y_mm: float = typer.Option(None, "--coin-slot-position-y-mm", help="Optional coin slot center Y position (mm) - defaults to centered"),
    mounting_hole_diameter_mm: float = typer.Option(None, "--mounting-hole-diameter-mm", help="Optional: add 4 corner mounting holes of this diameter (mm)"),
    mounting_hole_margin_mm: float = typer.Option(8.0, "--mounting-hole-margin-mm", help="Distance of mounting hole centers from each edge (mm)"),
    confirm: bool = typer.Option(False, "--confirm", help="Explicit, per-invocation human confirmation - required to actually execute"),
    confirmed_by: str = typer.Option(None, "--confirmed-by", help="Optional: who confirmed this execution, recorded in the receipt"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Phase 50: the gated, real execution of `organic_mechanical_augmentation` against one project
    artifact. Without --confirm, always blocked. With --confirm, generates parametric OpenSCAD source
    for the requested functional feature, exports it via the existing, bounded
    factory.export_pipeline.run_scad_source_to_stl() (never a second subprocess mechanism), validates
    and previews the result, and writes generated/cad_augmentation_receipt.json only on success - never
    overwriting the organic input artifact or an existing output. See docs/cad-augmentation.md."""
    params = _cad_augment_params(
        base_width_mm, base_length_mm, base_height_mm,
        coin_slot_width_mm, coin_slot_length_mm, coin_slot_depth_mm,
        coin_slot_position_x_mm, coin_slot_position_y_mm,
        mounting_hole_diameter_mm, mounting_hole_margin_mm,
    )
    result = run_organic_mechanical_augmentation(artifact_path, confirm=confirm, confirmed_by=confirmed_by, **params)

    if as_json:
        payload = {"result": result, "safety": build_cad_augmentation_safety_block()}
        print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        if result["augmentation_status"] != "succeeded":
            raise typer.Exit(code=1)
        return

    console.print("[bold]CAD AUGMENTATION EXECUTION[/bold]\n")
    console.print(f"[bold]Status:[/bold] {result['augmentation_status']}")
    if result.get("errors"):
        console.print("[bold]Errors:[/bold]")
        for error in result["errors"]:
            console.print(f"  - {_rich_escape(error)}")
    if result["augmentation_status"] == "succeeded":
        console.print(f"[bold]Output artifact:[/bold] {result['output_artifact']}")
        console.print(f"[bold]Receipt:[/bold] {result['receipt_path']}")
    console.print()
    for line in _CAD_AUGMENT_SAFETY_TRAILER:
        console.print(line)
    if result["augmentation_status"] != "succeeded":
        raise typer.Exit(code=1)


_DESIGN_REVIEW_SAFETY_TRAILER = (
    "This is a design quality/manufacturing readiness review, not an approval.",
    "Generated artifact != good design. Validated mesh != manufacturing ready. Manufacturing ready != human approved.",
    "Human approved != print approved. Automatic printing remains impossible.",
)

_READINESS_STATE_ICON = {
    "not_reviewed": "[dim]NOT REVIEWED[/dim]",
    "blocked": "[red]BLOCKED[/red]",
    "needs_information": "[yellow]NEEDS INFORMATION[/yellow]",
    "design_review_ready": "[cyan]DESIGN REVIEW READY[/cyan]",
    "manufacturing_review_ready": "[cyan]MANUFACTURING REVIEW READY[/cyan]",
    "approved_for_slicer_review": "[green]APPROVED FOR SLICER REVIEW[/green]",
}


def _render_design_review_human(review: dict[str, Any]) -> None:
    console.print("[bold]HYBRID DESIGN QUALITY REVIEW[/bold]\n")
    console.print(f"[bold]Project:[/bold] {review['project']}")
    console.print(f"[bold]Workflow type:[/bold] {review['workflow_type']}")
    console.print(f"[bold]Design quality score:[/bold] {review['design_quality_score']}%")
    state = review["manufacturing_readiness"]
    console.print(f"[bold]Manufacturing readiness:[/bold] {_READINESS_STATE_ICON.get(state, state)}")
    console.print(f"[bold]Confidence:[/bold] {review['confidence']}\n")

    console.print("[bold]Score by category:[/bold]")
    for name, entry in review["score_categories"].items():
        weight = review["score_weights"][name]
        console.print(f"  {name} ({int(weight * 100)}%): {entry['score']}% - {_rich_escape(entry['reasoning'])}")
    console.print()

    if review["blockers"]:
        console.print("[bold red]Blockers:[/bold red]")
        for b in review["blockers"]:
            console.print(f"  - [{b['source']}] {_rich_escape(b['message'])}")
        console.print()

    if review["required_human_confirmations"]:
        console.print("[bold]Required human confirmations:[/bold]")
        for c in review["required_human_confirmations"]:
            mark = "[green]OK[/green]" if c["confirmed"] else "[yellow]MISSING[/yellow]"
            console.print(f"  {mark}  {c['item']}")
        console.print()

    if review["recommended_actions"]:
        console.print("[bold]Recommended actions:[/bold]")
        for action in review["recommended_actions"]:
            console.print(f"  - {_rich_escape(action)}")
        console.print()

    for line in _DESIGN_REVIEW_SAFETY_TRAILER:
        console.print(line)


@app.command(name="design-review")
def design_review_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory under projects/"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
    save: bool = typer.Option(False, "--save", help="Additionally write a versioned, fingerprinted snapshot to generated/design_review_report.json (never an execution receipt, always overwritable)"),
) -> None:
    """Phase 51: the Hybrid Design Quality Review & Manufacturing Readiness Gate - evaluates whether a
    completed Meshy -> Blender -> CAD artifact chain is ready for human manufacturing review. Fully
    read-only by default: never calls Meshy, never launches Blender, never executes CAD, never invokes a
    slicer, never contacts a printer or network, never modifies geometry. Reuses
    factory.hybrid_workflow/factory.blender_adaptation/factory.cad_augmentation/factory.slicer_intelligence/
    factory.slicer_readiness directly - never a second validator or lineage system. `manufacturing_readiness`
    never reaches `approved_for_print` - automatic printing remains impossible. With --save, additionally
    writes a read-only analysis snapshot (never an execution receipt)."""
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        console.print(f"[red]error[/red]: not a directory: {project_dir}")
        raise typer.Exit(code=1)

    review = evaluate_design_review(project_dir)
    report_path = save_design_review_report(project_dir) if save else None

    if as_json:
        payload = {"review": review, "safety": build_design_review_safety_block()}
        if report_path:
            payload["report_path"] = str(report_path)
        print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return
    _render_design_review_human(review)
    if report_path:
        console.print(f"\nSaved snapshot: {report_path}")


_MANUFACTURING_READINESS_SAFETY_TRAILER = (
    "Manufacturing readiness is not printing approval. Automatic printing remains impossible.",
    "This report never contacts Meshy/Blender/CAD/a slicer/a printer/a network, and never modifies geometry.",
)

_MANUFACTURING_READINESS_STATE_ICON = {
    "not_ready": "[dim]NOT READY[/dim]",
    "needs_information": "[yellow]NEEDS INFORMATION[/yellow]",
    "design_review_complete": "[cyan]DESIGN REVIEW COMPLETE[/cyan]",
    "manufacturing_review_ready": "[cyan]MANUFACTURING REVIEW READY[/cyan]",
    "human_approval_required": "[yellow]HUMAN APPROVAL REQUIRED[/yellow]",
    "slicer_preparation_ready": "[green]SLICER PREPARATION READY[/green]",
    "blocked": "[red]BLOCKED[/red]",
}


def _render_manufacturing_readiness_human(report: dict[str, Any], *, verbose: bool) -> None:
    console.print("[bold]MANUFACTURING READINESS[/bold]\n")
    console.print(f"[bold]Project:[/bold] {report['project']}")
    console.print(f"[bold]Pipeline:[/bold] {report['pipeline']}")
    state = report["readiness_state"]
    console.print(f"[bold]Readiness state:[/bold] {_MANUFACTURING_READINESS_STATE_ICON.get(state, state)}")
    console.print(f"[bold]Readiness score:[/bold] {report['readiness_score']}% (source: {report['readiness_score_source']})")
    console.print(f"[bold]Confidence:[/bold] {report['confidence']}\n")

    console.print("[bold]Status by category:[/bold]")
    for label in (
        "artifact_status", "design_status", "geometry_status", "scale_status",
        "manufacturing_status", "printer_status", "material_status", "slicer_status", "human_review_status",
    ):
        console.print(f"  {label}: {report[label]}")
    console.print()

    if report["blockers"]:
        console.print("[bold red]Blockers:[/bold red]")
        for b in report["blockers"]:
            console.print(f"  - [{b['pipeline']}/{b['source']}] {_rich_escape(b['message'])}")
        console.print()

    if verbose and report["warnings"]:
        console.print("[bold yellow]Warnings:[/bold yellow]")
        for w in report["warnings"]:
            console.print(f"  - [{w['pipeline']}/{w['source']}] {_rich_escape(w['message'])}")
        console.print()

    console.print("[bold]Human confirmation checklist:[/bold]")
    for c in report["human_confirmation_checklist"]:
        mark = "[green]OK[/green]" if c["confirmed"] else "[yellow]MISSING[/yellow]"
        console.print(f"  {mark}  {c['item']}")
    console.print()

    if report["recommended_next_steps"]:
        console.print("[bold]Recommended next steps:[/bold]")
        for step in report["recommended_next_steps"]:
            console.print(f"  - {_rich_escape(step)}")
        console.print()

    for line in _MANUFACTURING_READINESS_SAFETY_TRAILER:
        console.print(line)


@app.command(name="manufacturing-readiness")
def manufacturing_readiness_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory under projects/"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
    verbose: bool = typer.Option(False, "--verbose", help="Also print warnings in the human-readable report (JSON output always includes them)"),
) -> None:
    """Phase 52: the Manufacturing Readiness Intelligence & Final Production Gate - a pipeline-agnostic
    aggregation over factory.design_review (hybrid pipeline) and factory.project_health (traditional
    pipeline), plus factory.slicer_intelligence/factory.artifact_history/factory.project_timeline. Answers
    "is this project ready to enter manufacturing preparation" - never "should the printer automatically
    start." Fully read-only: never calls Meshy, never launches Blender, never executes CAD, never invokes a
    slicer, never contacts a printer or network, never modifies geometry. Reuses every existing readiness
    signal directly - never a second scoring/validation system. `readiness_state` never reaches
    `approved_for_print`/`automatic_manufacture_ready` - automatic printing remains impossible."""
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        console.print(f"[red]error[/red]: not a directory: {project_dir}")
        raise typer.Exit(code=1)

    report = evaluate_manufacturing_readiness(project_dir)

    if as_json:
        payload = {"report": report, "safety": build_manufacturing_readiness_safety_block()}
        print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return
    _render_manufacturing_readiness_human(report, verbose=verbose)


_MESHY_SAFETY_TRAILER = (
    "No Meshy API call was made. No credentials were read. No data left this machine. No money was spent.",
    "This is policy/approval infrastructure only - it never contacts Meshy or any cloud service. See docs/meshy-policy.md.",
)


def _render_meshy_human(gate: dict[str, Any], readiness: dict[str, Any]) -> None:
    console.print("[bold]MESHY CLOUD APPROVAL GATE[/bold]\n")

    console.print("[bold]Registry:[/bold]")
    console.print("Known future cloud tool (Phase 43)")
    console.print()

    console.print("[bold]Network:[/bold]")
    console.print("Required in future. Not used now.")
    console.print()

    console.print("[bold]Credentials:[/bold]")
    console.print("Not read.")
    console.print()

    console.print("[bold]Cost policy:[/bold]")
    console.print("Configured" if gate["gate_status"] not in ("needs_cost_policy",) else "Incomplete")
    console.print()

    console.print("[bold]License policy:[/bold]")
    console.print("Reviewed" if gate["license_policy"].get("terms_reviewed") else "Requires review")
    console.print()

    console.print("[bold]Privacy policy:[/bold]")
    console.print("Configured conservatively")
    console.print()

    console.print("[bold]Reference upload:[/bold]")
    console.print("Blocked by default")
    console.print()

    console.print("[bold]Human approval:[/bold]")
    console.print("Recorded" if gate["approval_recorded"] else "Not recorded")
    console.print()

    console.print("[bold]Kill switch:[/bold]")
    console.print("Cloud execution disabled")
    console.print()

    console.print("[bold]Phase 47 readiness:[/bold]")
    console.print("Ready" if readiness["ready_for_phase47"] else "Not ready")
    console.print()

    adapter_state = summarize_mock_adapter_state()
    console.print("[bold]Mock adapter (Phase 47A):[/bold]")
    console.print("Implemented - see `factory meshy plan`/`factory meshy mock-run`" if adapter_state["mock_adapter_implemented"] else "Not implemented")
    console.print()

    console.print("[bold]Live transport:[/bold]")
    console.print("Not implemented" if not adapter_state["live_transport_implemented"] else "Implemented")
    console.print()

    if gate["blockers"]:
        console.print("[bold]Blockers:[/bold]")
        for item in gate["blockers"]:
            console.print(f"- {_rich_escape(item)}")
        console.print()

    for line in _MESHY_SAFETY_TRAILER:
        console.print(line)


meshy_app = typer.Typer(
    name="meshy",
    help=(
        "Meshy Cloud / Cost / License / Privacy Approval Gate (Phase 46) - policy and approval "
        "infrastructure only. Zero Meshy network calls, zero credential reads, zero data upload, "
        "zero paid API calls - no exceptions. `factory meshy status`/`policy`/`approval-status` are "
        "fully read-only. `factory meshy approve-policy`/`revoke-policy` write only to the local, "
        "non-secret config/meshy_policy.json - never to config/future_cloud_tools.json's kill "
        "switch, and can never set execution_enabled=true. See docs/meshy-policy.md."
    ),
    no_args_is_help=True,
)
app.add_typer(meshy_app, name="meshy")


@meshy_app.command(name="status")
def meshy_status_cmd(
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Read-only Meshy cloud approval gate status. Never contacts a network, never reads a credential."""
    gate = evaluate_meshy_gate()
    readiness = evaluate_meshy_phase47_readiness(gate)
    if as_json:
        print(json.dumps({"tool": "meshy", "gate": gate, "phase47_readiness": readiness, "adapter": summarize_mock_adapter_state(), "safety": _meshy_safety_block()}, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return
    _render_meshy_human(gate, readiness)


def _meshy_safety_block() -> dict[str, bool]:
    return {
        "network_used": False,
        "credentials_read": False,
        "data_uploaded": False,
        "money_spent": False,
        "printer_contacted": False,
        "automatic_print_allowed": False,
    }


@meshy_app.command(name="policy")
def meshy_policy_cmd(
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Read-only full Meshy policy detail: cost, license, privacy, provenance, and approval state.
    Never contacts a network, never reads a credential."""
    gate = evaluate_meshy_gate()
    readiness = evaluate_meshy_phase47_readiness(gate)
    if as_json:
        print(json.dumps({"tool": "meshy", "gate": gate, "cost_policy": gate["cost_policy"], "license_policy": gate["license_policy"], "privacy_policy": gate["privacy_policy"], "provenance_policy": gate["provenance_policy"], "approval": gate["approval"], "phase47_readiness": readiness, "adapter": summarize_mock_adapter_state(), "safety": _meshy_safety_block()}, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return
    _render_meshy_human(gate, readiness)


@meshy_app.command(name="approval-status")
def meshy_approval_status_cmd(
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Read-only view of just the recorded approval state (never the whole policy)."""
    gate = evaluate_meshy_gate()
    if as_json:
        print(json.dumps({"tool": "meshy", "approval": gate["approval"], "approval_recorded": gate["approval_recorded"], "gate_status": gate["gate_status"], "safety": _meshy_safety_block()}, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return
    console.print("[bold]MESHY APPROVAL STATUS[/bold]\n")
    console.print(f"Approval recorded: {'Yes' if gate['approval_recorded'] else 'No'}")
    console.print(f"Approval scope: {gate['approval']['approval_scope'] or 'None'}")
    console.print(f"Execution enabled: {gate['kill_switch']['execution_enabled']}")
    console.print()
    for line in _MESHY_SAFETY_TRAILER:
        console.print(line)


@meshy_app.command(name="approve-policy")
def meshy_approve_policy_cmd(
    ack_cost: bool = typer.Option(False, "--ack-cost", help="Acknowledge the configured cost policy"),
    ack_license: bool = typer.Option(False, "--ack-license", help="Acknowledge the reviewed license policy"),
    ack_privacy: bool = typer.Option(False, "--ack-privacy", help="Acknowledge the privacy/data policy"),
    ack_provenance: bool = typer.Option(False, "--ack-provenance", help="Acknowledge the provenance requirements"),
    approved_by: str = typer.Option(None, "--approved-by", help="Name/identifier of the human recording this approval"),
    note: str = typer.Option(None, "--note", help="Optional free-text note appended to approval.notes (e.g. research date/plan context this approval was based on)"),
) -> None:
    """Explicit write: records human approval of the Meshy policy scaffold (approval_scope=policy_only).
    Requires all four --ack-* flags. Requires a cost cap and a reviewed license policy to already be set
    in config/meshy_policy.json. Can NEVER enable Meshy execution - execution_enabled stays false always."""
    try:
        gate = record_meshy_policy_approval(ack_cost=ack_cost, ack_license=ack_license, ack_privacy=ack_privacy, ack_provenance=ack_provenance, approved_by=approved_by, note=note)
    except MeshyPolicyError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)
    console.print(f"[green]recorded[/green]: Meshy policy approval (scope: policy_only), execution_enabled={gate['kill_switch']['execution_enabled']}")
    for line in _MESHY_SAFETY_TRAILER:
        console.print(line)


@meshy_app.command(name="revoke-policy")
def meshy_revoke_policy_cmd(
    reason: str = typer.Option(None, "--reason", help="Optional reason recorded in the revocation history"),
) -> None:
    """Explicit write: revokes any previously recorded Meshy policy approval. Local file only - no network,
    no remote revocation. Preserves the prior approval as history rather than discarding it."""
    try:
        gate = revoke_meshy_policy_approval(reason=reason)
    except MeshyPolicyError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)
    console.print(f"[green]revoked[/green]: Meshy policy approval. gate_status={gate['gate_status']}")
    for line in _MESHY_SAFETY_TRAILER:
        console.print(line)


@meshy_app.command(name="approval-plan")
def meshy_approval_plan_cmd(
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Phase 46.5: read-only Meshy human approval decision package. Writes nothing, records nothing,
    and selects no decision on the human's behalf - every proposed default is labeled PROPOSED - NOT
    APPROVED. Lists the outstanding decisions, conservative proposed defaults, the cost fields that
    still need real human-supplied values, and the exact commands to run afterward. Never contacts
    Meshy or any network, never reads a credential. See docs/meshy-policy.md "Phase 46.5"."""
    plan = build_meshy_approval_plan()

    if as_json:
        print(json.dumps(plan, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return

    console.print("[bold]MESHY HUMAN APPROVAL PLAN[/bold]\n")

    console.print("[bold]Current State[/bold]")
    for label, value in (
        ("Policy infrastructure", plan["current_state"]["policy_infrastructure"]),
        ("Policy approval", plan["current_state"]["policy_approval"]),
        ("Execution", plan["current_state"]["execution"]),
        ("Network access", plan["current_state"]["network_access"]),
    ):
        console.print(f"{label}: {value}")
    console.print()

    for decision in plan["decisions"]:
        console.print(f"[bold]DECISION {decision['id']} - {_rich_escape(decision['title'])}[/bold]")
        if decision["choices"]:
            for choice in decision["choices"]:
                console.print(f"[ ] {choice}")
        current = decision.get("current")
        console.print(f"Current: {current if current not in (None, {}) else 'Not specified'}")
        if decision.get("proposed_default"):
            console.print(f"Proposed (NOT APPROVED): {decision['proposed_default']}")
        if decision.get("note"):
            console.print(_rich_escape(decision["note"]))
        console.print()

    console.print("[bold]Recommended Phase 47 scope (proposed - not approved):[/bold]")
    console.print(_rich_escape(plan["phase47_scope_proposal"]["recommended_initial_scope"]))
    console.print()

    console.print("[bold]Phase 47 implementation approval:[/bold]", plan["phase47_implementation_approval"]["status"])
    console.print("[bold]Phase 47 live-call approval:[/bold]", plan["phase47_live_call_approval"]["status"])
    console.print()

    console.print("[bold]Exact commands you could run after making these decisions:[/bold]")
    for command in plan["exact_commands_after_decisions"]:
        console.print(f"  {_rich_escape(command)}")
    console.print()

    console.print("No Meshy API call was made. No credentials were read. No decision was recorded on your behalf.")
    for line in _MESHY_SAFETY_TRAILER:
        console.print(line)


_MESHY_MOCK_SAFETY_TRAILER = (
    "No Meshy API call was made. No credentials were read. No credits were spent. No money was spent.",
    "This is a MOCK artifact - it did not come from Meshy. See docs/meshy-adapter.md.",
)


def _render_meshy_plan_human(plan: dict[str, Any]) -> None:
    console.print("[bold]MESHY REQUEST PLAN[/bold]\n")
    console.print("[bold]Mode:[/bold]\nMocked Only\n")
    console.print(f"[bold]Request:[/bold]\nText-to-3D ({plan['model']}, {plan['mode']})\n")
    console.print(f"[bold]Estimated credits:[/bold]\n{plan['estimated_credits'] if plan['estimated_credits'] is not None else 'unknown'}\n")
    cap = plan["provenance"].get("configured_cost_cap")
    console.print(f"[bold]Request cap:[/bold]\n{cap if cap is not None else 'not configured'}\n")
    console.print(f"[bold]Policy:[/bold]\n{plan['policy_check']['policy_gate_status']}\n")
    console.print(f"[bold]Budget:[/bold]\n{'Allowed' if plan['budget_check']['allowed'] else 'Blocked - ' + (plan['budget_check']['reason'] or '')}\n")
    console.print("[bold]Live Meshy:[/bold]\nDisabled\n")
    console.print("[bold]Network:[/bold]\nWill not be used\n")
    console.print(f"[bold]Mock execution allowed:[/bold]\n{plan['mock_execution_allowed']}\n")
    if plan["blockers"]:
        console.print("[bold]Blockers:[/bold]")
        for item in plan["blockers"]:
            console.print(f"- {_rich_escape(item)}")
        console.print()
    if plan["warnings"]:
        console.print("[bold]Warnings:[/bold]")
        for item in plan["warnings"]:
            console.print(f"- {_rich_escape(item)}")
        console.print()
    console.print("[bold]Confirmation:[/bold]\nRequired for mock artifact workflow\n")
    for line in _MESHY_MOCK_SAFETY_TRAILER:
        console.print(line)


@meshy_app.command(name="plan")
def meshy_plan_cmd(
    prompt: str = typer.Option(..., "--prompt", help="Text-to-3D prompt (Phase 47A supports text_to_3d only)"),
    model: str = typer.Option(DEFAULT_AI_MODEL, "--model", help=f"Meshy ai_model - one of {KNOWN_AI_MODELS!r}"),
    mode: str = typer.Option("preview", "--mode", help=f"Text-to-3D mode - one of {REQUEST_MODES!r}"),
    target_polygon_count: int = typer.Option(None, "--target-polygon-count", help="Optional target_polycount"),
    project: Path = typer.Option(None, "--project", help="Optional project directory - used only for provenance/budget-ledger purposes, never written to by this command"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Phase 47A: dry-run Meshy Text-to-3D request plan. Read-only - never contacts Meshy, never
    spends credits, never writes anything. Reuses Phase 46's policy gate and cost caps directly.
    See docs/meshy-adapter.md."""
    plan = plan_text_to_3d_request(prompt=prompt, ai_model=model, mode=mode, target_polygon_count=target_polygon_count, project_id=str(project) if project else None)
    if as_json:
        payload = dict(plan)
        payload["safety"] = build_meshy_adapter_safety_block()
        print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return
    _render_meshy_plan_human(plan)


def _render_meshy_mock_run_human(result: dict[str, Any]) -> None:
    console.print("[bold]MESHY MOCK EXECUTION[/bold]\n")
    console.print(f"[bold]Task:[/bold]\n{result['task_id'] or '(none - blocked before submission)'}\n")
    console.print(f"[bold]Lifecycle:[/bold]\n{' -> '.join(result['lifecycle']) if result['lifecycle'] else '(none)'}\n")
    console.print(f"[bold]Artifact:[/bold]\n{result['artifact_path'] or '(none)'}\n")
    console.print(f"[bold]Validation:[/bold]\n{result['validation_state'] or 'not run'}\n")
    console.print(f"[bold]Preview:[/bold]\n{result['preview_state'] or 'not run'}\n")
    console.print(f"[bold]Provenance:[/bold]\n{'Recorded' if result['receipt'] else 'Not recorded'}\n")
    console.print("[bold]Live API:[/bold]\nNot used\n")
    console.print(f"[bold]Credits:[/bold]\n{result['credits_spent']} spent\n")
    console.print("[bold]Network:[/bold]\nNot used\n")
    console.print("[bold]Human review:[/bold]\nRequired\n")
    if result["errors"]:
        console.print("[bold]Errors:[/bold]")
        for item in result["errors"]:
            console.print(f"- ({item['error_code']}) {_rich_escape(item['message'])}")
        console.print()
    if result["warnings"]:
        console.print("[bold]Warnings:[/bold]")
        for item in result["warnings"]:
            console.print(f"- {_rich_escape(item)}")
        console.print()
    if result.get("receipt_path"):
        console.print(f"Receipt written to: {result['receipt_path']}\n")
    console.print("This is a MOCK artifact.")
    console.print("It did not come from Meshy.\n")
    for line in _MESHY_MOCK_SAFETY_TRAILER:
        console.print(line)


@meshy_app.command(name="mock-run")
def meshy_mock_run_cmd(
    prompt: str = typer.Option(..., "--prompt", help="Text-to-3D prompt (Phase 47A supports text_to_3d only)"),
    model: str = typer.Option(DEFAULT_AI_MODEL, "--model", help=f"Meshy ai_model - one of {KNOWN_AI_MODELS!r}"),
    mode: str = typer.Option("preview", "--mode", help=f"Text-to-3D mode - one of {REQUEST_MODES!r}"),
    scenario: str = typer.Option("success", "--scenario", help="Mock lifecycle scenario: success, failure, rate_limited, server_error, expired_artifact"),
    project: Path = typer.Option(None, "--project", help="Optional project directory - if given, writes generated/meshy/mock_concept.stl and generated/meshy_receipt.json there; otherwise runs entirely in a temporary directory that is cleaned up"),
    confirm_mock: bool = typer.Option(False, "--confirm-mock", help="Explicit confirmation to actually run the mocked lifecycle (submit/poll/download/validate/preview)"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Phase 47A: run the full MOCKED Meshy Text-to-3D lifecycle (submit -> poll -> mock artifact ->
    Factory validation -> Factory preview -> receipt). Without --confirm-mock, only builds and shows
    the dry-run plan (same as `factory meshy plan`) - nothing executes. Never contacts Meshy, never
    reads a credential, never spends credits/money. The artifact is always a fixed, local, synthetic
    mock STL - never Meshy output. See docs/meshy-adapter.md."""
    plan = plan_text_to_3d_request(prompt=prompt, ai_model=model, mode=mode, project_id=str(project) if project else None)

    if not confirm_mock:
        if as_json:
            payload = dict(plan)
            payload["safety"] = build_meshy_adapter_safety_block()
            payload["note"] = "Dry-run only - pass --confirm-mock to actually execute the mocked lifecycle."
            print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False, default=str))
            return
        _render_meshy_plan_human(plan)
        console.print("\nPass --confirm-mock to actually execute the mocked lifecycle.")
        return

    result = run_mock_text_to_3d_request(plan, scenario=scenario, project_dir=project)
    if as_json:
        payload = dict(result)
        payload["safety"] = build_meshy_adapter_safety_block()
        print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return
    _render_meshy_mock_run_human(result)


_MESHY_LIVE_SAFETY_TRAILER = (
    "No credential is read unless every local gate (policy, budget, kill switch, one-shot approval, "
    "--confirm-live) has already passed - see docs/meshy-live-transport.md.",
)


def _render_meshy_live_plan_human(plan: dict[str, Any]) -> None:
    console.print("[bold]MESHY LIVE PLAN[/bold]\n")
    console.print(f"[bold]Request:[/bold]\nText-to-3D ({plan['model']}, {plan['mode']})\n")
    console.print(f"[bold]Estimated credits:[/bold]\n{plan['estimated_credits'] if plan['estimated_credits'] is not None else 'unknown'}\n")
    credit_policy = plan["budget_check"]
    console.print(f"[bold]Budget:[/bold]\n{'Allowed' if credit_policy['allowed'] else 'Blocked - ' + (credit_policy['reason'] or '')}\n")
    console.print(f"[bold]Policy:[/bold]\n{'Approved' if plan['policy_approved'] else 'Not approved'}\n")
    console.print(f"[bold]Execution kill switch:[/bold]\n{'Enabled (both flags)' if plan['kill_switch']['both_enabled'] else 'Disabled'}\n")
    console.print(f"[bold]One-shot approval:[/bold]\n{'Eligible (' + plan['approval_id'] + ')' if plan['approval_id'] else 'Missing'}\n")
    console.print("[bold]Credential:[/bold]\nNot checked\n")
    console.print("[bold]Network:[/bold]\nNot used\n")
    console.print(f"[bold]Live execution:[/bold]\n{'Ready (pending --confirm-live)' if plan['every_gate_satisfied'] else 'Blocked'}\n")
    if plan["blockers"]:
        console.print("[bold]Blockers:[/bold]")
        for item in plan["blockers"]:
            console.print(f"- {_rich_escape(item)}")
        console.print()
    for line in _MESHY_LIVE_SAFETY_TRAILER:
        console.print(line)


@meshy_app.command(name="live-plan")
def meshy_live_plan_cmd(
    prompt: str = typer.Option(..., "--prompt", help="Text-to-3D prompt"),
    model: str = typer.Option(DEFAULT_AI_MODEL, "--model", help=f"Meshy ai_model - one of {KNOWN_AI_MODELS!r}"),
    mode: str = typer.Option("preview", "--mode", help=f"Text-to-3D mode - one of {REQUEST_MODES!r}"),
    project: Path = typer.Option(None, "--project", help="Disposable project directory this live call would target"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Phase 47B: fully offline live-call readiness plan. Never reads a credential, never reserves
    budget, never consumes a one-shot approval - only reports whether each local gate (policy, budget,
    kill switch, one-shot approval) currently passes. See docs/meshy-live-transport.md."""
    plan = plan_live_text_to_3d_request(prompt=prompt, model=model, mode=mode, project=str(project) if project else None)
    if as_json:
        print(json.dumps(plan, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return
    _render_meshy_live_plan_human(plan)


@meshy_app.command(name="approve-live-once")
def meshy_approve_live_once_cmd(
    prompt: str = typer.Option(..., "--prompt", help="The exact prompt this one-shot approval is pinned to"),
    model: str = typer.Option(DEFAULT_AI_MODEL, "--model", help="Meshy ai_model this approval is pinned to"),
    max_credits: int = typer.Option(..., "--max-credits", help="Maximum credits this one-shot approval permits (must be a positive integer)"),
    project: Path = typer.Option(None, "--project", help="Optional disposable project this approval is pinned to"),
    expires_in: int = typer.Option(3600, "--expires-in", help="Seconds until this approval expires unused (max 86400 = 24h)"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Phase 47B: explicit write - creates ONE local, single-use, short-lived live-call approval record
    (state/meshy_live_approvals.json). This is NOT blanket execution permission: it is scoped to this
    exact prompt/model/credit-cap/project, and is consumed automatically the first time `factory meshy
    live-run --confirm-live` reaches it. Never contacts Meshy, never enables the kill switch."""
    try:
        record = create_one_shot_approval(prompt_hash=compute_prompt_hash(prompt), model=model, max_credits=max_credits, project=str(project) if project else None, expires_in_seconds=expires_in)
    except ApprovalError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)
    if as_json:
        print(json.dumps(record, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return
    console.print(f"[green]recorded[/green]: one-shot approval {record['approval_id']} (expires {record['expires_at']})")
    console.print("This approval is single-use and does not itself enable Meshy execution.")


@meshy_app.command(name="revoke-live-approval")
def meshy_revoke_live_approval_cmd(
    approval_id: str = typer.Argument(..., help="The approval_id to revoke"),
    reason: str = typer.Option(None, "--reason", help="Optional reason recorded with the revocation"),
) -> None:
    """Phase 47B: explicit write - revokes one local one-shot approval record. Local file only."""
    try:
        record = revoke_approval(approval_id, reason=reason)
    except ApprovalError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)
    console.print(f"[green]revoked[/green]: {record['approval_id']}")


@meshy_app.command(name="reconcile-ledger-entry")
def meshy_reconcile_ledger_entry_cmd(
    reservation_id: str = typer.Argument(..., help="The ledger reservation_id to reconcile"),
    reason: str = typer.Option(..., "--reason", help="Why this entry is confirmed to have consumed zero credits"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Phase 47B.7: explicit write - reconciles one `"unknown"` spend-ledger entry to
    `"confirmed_zero_rejected_before_submission"` (state/meshy_spend_ledger.json). Only valid for an
    entry with no task_id (no evidence a task was ever created) - e.g. an HTTP 401/403 credential
    rejection, which Meshy's auth layer returns before any task exists. Never contacts Meshy, never
    deletes ledger history - the original entry's timestamp/unknown_reason are preserved alongside the
    new reconciled_at/reconciled_reason fields."""
    try:
        entry = SpendLedger().reconcile_rejected_before_submission(reservation_id, reason=reason)
    except LedgerError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)
    if as_json:
        print(json.dumps(entry, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return
    console.print(f"[green]reconciled[/green]: {entry['reservation_id']} -> {entry['status']} (actual_credits=0)")


def _render_meshy_live_run_human(result: dict[str, Any]) -> None:
    console.print("[bold]MESHY LIVE EXECUTION[/bold]\n")
    console.print(f"[bold]Task:[/bold]\n{result['task_id'] or '(none - blocked before submission)'}\n")
    console.print(f"[bold]Final status:[/bold]\n{result['final_status'] or '(none)'}\n")
    console.print(f"[bold]Artifact:[/bold]\n{result['artifact_path'] or '(none)'}\n")
    console.print(f"[bold]Validation:[/bold]\n{result['validation_status'] or 'not run'}\n")
    console.print(f"[bold]Preview:[/bold]\n{result['preview_status'] or 'not run'}\n")
    console.print(f"[bold]Credits spent:[/bold]\n{result['credits_spent']}\n")
    if result.get("receipt_path"):
        console.print(f"Receipt written to: {result['receipt_path']}\n")
    if result["errors"]:
        console.print("[bold]Errors:[/bold]")
        for item in result["errors"]:
            console.print(f"- ({item['error_code']}) {_rich_escape(item['message'])}")
        console.print()
    console.print("Human review required. Automatic printing remains impossible.")


@meshy_app.command(name="live-run")
def meshy_live_run_cmd(
    prompt: str = typer.Option(..., "--prompt", help="Text-to-3D prompt - must match an eligible one-shot approval's pinned prompt"),
    model: str = typer.Option(DEFAULT_AI_MODEL, "--model", help="Meshy ai_model"),
    mode: str = typer.Option("preview", "--mode", help="Text-to-3D mode"),
    project: Path = typer.Option(None, "--project", help="Disposable project directory to persist the artifact/receipt into (required for a real download)"),
    confirm_live: bool = typer.Option(False, "--confirm-live", help="Explicit confirmation to actually make one real, budget-checked, approved live Meshy call"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Phase 47B: the gated live Meshy Text-to-3D call. Blocked unless policy is approved, budget is
    available, BOTH kill-switch flags are enabled, an eligible one-shot approval exists, and
    --confirm-live is passed - in that order. Only then is MESHY_API_KEY read and a real network call
    made. Exactly one submission, ever, per approval - no automatic retry. See
    docs/meshy-live-transport.md."""
    result = run_live_text_to_3d_request(prompt=prompt, model=model, mode=mode, project=str(project) if project else None, confirm_live=confirm_live)
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=False, ensure_ascii=False, default=str))
        return
    _render_meshy_live_run_human(result)


@app.command(name="review-gate")
def review_gate_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory under projects/"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Read-only pass/warn/fail gate for whether a project is ready for HUMAN slicer review.

    Never renders, validates, exports, generates CAD, invokes a slicer, or contacts a printer/network.
    Passing this gate is not an approval and not a print-readiness signal.
    """
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        console.print(f"[red]error[/red]: not a directory: {project_dir}")
        raise typer.Exit(code=1)

    gate = evaluate_review_gate(project_dir)

    if as_json:
        print(json.dumps(gate, indent=2, sort_keys=False))
    else:
        result_icon = _icon(gate["result"].upper())
        console.print(f"{result_icon}  gate: {gate['gate']}  (status ceiling: {gate['status_ceiling']})")
        console.print(gate["summary"])

        if gate["blocking_items"]:
            console.print(f"\n[red]blocking[/red] ({len(gate['blocking_items'])}):")
            for item in gate["blocking_items"]:
                console.print(f"  - {item['message']}")
        if gate["warning_items"]:
            console.print(f"\n[yellow]warnings[/yellow] ({len(gate['warning_items'])}):")
            for item in gate["warning_items"]:
                console.print(f"  - {item['message']}")
        if gate["ready_items"]:
            console.print(f"\n[green]ready[/green] ({len(gate['ready_items'])}):")
            for item in gate["ready_items"]:
                console.print(f"  - {item['message']}")

        if gate["suggested_actions"]:
            console.print("\n[bold]suggested next steps[/bold] (manual only - none of these are run automatically):")
            for action in gate["suggested_actions"]:
                console.print(f"  {action['label']}: {action['command']}")

        console.print()
        for note in gate["notes"]:
            console.print(note)
        console.print(
            "\nThis command only read existing project files - it did not render, validate, export, "
            "generate CAD, invoke a slicer, or contact any printer/network."
        )

    if gate["result"] == "fail":
        raise typer.Exit(code=1)


@app.command(name="inspect-slicer")
def inspect_slicer() -> None:
    """Read-only discovery of locally installed slicers. Never launches or slices."""
    results = probe_slicers()
    for entry in results:
        status_label = _icon("PASS") if entry["found"] else _icon("WARN")
        location = entry["path"] or "not found in /Applications or on PATH"
        console.print(f"{status_label}  {entry['name']}: {location}")
    console.print("\nThis command never launches a slicer, slices, prints, or uploads anything.")


@app.command()
def report(project_dir: Path = typer.Argument(..., help="Path to a project directory under projects/")) -> None:
    """Summarize a project's current state across brief/plan/manifest/validation/renders/review."""
    project_dir = Path(project_dir)
    if not project_dir.is_dir():
        console.print(f"[red]error[/red]: not a directory: {project_dir}")
        raise typer.Exit(code=1)

    brief = _safe_load(project_dir / "brief.json")
    build_plan = _safe_load(project_dir / "build_plan.json")
    manifest = _safe_load(project_dir / "part_manifest.json")

    stl_files = sorted((project_dir / "stl").glob("*.stl")) if (project_dir / "stl").is_dir() else []
    render_files = sorted((project_dir / "renders").glob("*.png")) if (project_dir / "renders").is_dir() else []
    validation_files = (
        sorted((project_dir / "validation").glob("*.json")) if (project_dir / "validation").is_dir() else []
    )
    slicer_review_files = (
        sorted((project_dir / "slicer_review").glob("*.json")) if (project_dir / "slicer_review").is_dir() else []
    )

    validation_reports = [project_store.load_json(p) for p in validation_files]
    any_validation_fail = any(r.get("overall_status") == "FAIL" for r in validation_reports)
    has_clean_validation = bool(validation_reports) and not any_validation_fail

    human_approved = False
    for p in slicer_review_files:
        data = project_store.load_json(p)
        if data.get("human_approval", {}).get("approved"):
            human_approved = True

    safe_status = _compute_safe_status(
        brief=brief,
        has_clean_validation=has_clean_validation,
        has_renders=bool(render_files),
        human_approved=human_approved,
    )

    console.print(f"[bold]project[/bold]: {project_dir}")
    console.print(f"  brief status: {brief.get('status', '(missing brief.json)') if brief else '(missing brief.json)'}")
    console.print(f"  build plan status: {build_plan.get('status', '(not planned)') if build_plan else '(missing build_plan.json)'}")

    _print_target_printer_summary(build_plan)
    _print_manufacturing_options_summary(build_plan)
    _print_assembly_intent_summary(build_plan)

    manifest_checks = []
    console.print(f"  manifest parts: {len(manifest.get('parts', [])) if manifest else '(missing part_manifest.json)'}")
    if manifest:
        required_part_names = (
            [p.get("part_name") for p in build_plan.get("required_parts", []) if p.get("part_name")]
            if build_plan
            else None
        )
        manifest_checks = check_manifest(manifest, project_dir, required_part_names=required_part_names)
        for check in manifest_checks:
            console.print(f"    {_icon(check['status'])}  {check['name']}: {check['detail']}")

    _print_manifest_and_multipart_summary(manifest, manifest_checks)

    console.print(f"  STL files: {len(stl_files)}")
    console.print(f"  renders: {len(render_files)}")
    console.print(f"  validation reports: {len(validation_files)} (clean: {has_clean_validation})")
    _print_validation_summary(validation_reports)
    console.print(f"  slicer review packages: {len(slicer_review_files)}")
    console.print(f"  human approval on record: {human_approved}")
    _print_preview_package_summary(project_dir)
    _print_design_intent_summary(summarize_design_intent(project_dir / "brief.json"))
    console.print(f"\n[bold]current safe status[/bold]: {safe_status}")

    _print_remaining_human_decisions(build_plan)

    console.print("\nHuman slicer review required.")
    console.print("Project is NOT print-ready.")


@app.command(name="list-examples")
def list_examples_cmd() -> None:
    """List every example project under examples/ (read-only, static local registry)."""
    examples = list_examples()
    console.print(f"[bold]examples[/bold] ({len(examples)}):")
    for example in examples:
        missing_marker = "" if example["exists"] else "  [red]MISSING ON DISK[/red]"
        console.print(f"\n[bold]{example['name']}[/bold]  ({example['path']}){missing_marker}")
        console.print(f"  type: {example['type']}")
        console.print(f"  backend: {example['backend']}")
        console.print(f"  status: {example['status']}")

    console.print(
        "\nThis command only reads a small static local registry and checks whether each path "
        "exists on disk - it did not generate, render, export, validate, or contact anything."
    )


@app.command(name="show-example")
def show_example_cmd(
    example_name: str = typer.Argument(..., help="An example name from `factory list-examples`"),
) -> None:
    """Show full detail for one example (read-only)."""
    try:
        example = get_example(example_name)
    except UnknownExampleError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)

    console.print(f"[bold]{example['name']}[/bold]  ({example['path']})")
    console.print(f"  exists on disk: {example['exists']}")
    console.print(f"  type: {example['type']}")
    console.print(f"  backend: {example['backend']}")
    console.print(f"  status: {example['status']}")
    console.print("  safety notes:")
    for note in example["safety_notes"]:
        console.print(f"    - {note}")

    if example["type"] == "working":
        console.print("\n[bold]try it[/bold] (read-only, none of these write anything except preview-project):")
        console.print(f"  factory preview-index {example['path']}")
        console.print(f"  factory preview-project {example['path']}")
        console.print(f"  factory review-gate {example['path']}")

    console.print(
        "\nThis command only reads a small static local registry and checks whether this path "
        "exists on disk - it did not generate, render, export, validate, or contact anything."
    )


@app.command(name="check-future-tools")
def check_future_tools_cmd() -> None:
    """Read-only report of future cloud/paid tool gates (e.g. Meshy). Never contacts a network,
    reads .env, validates credentials, or enables anything. See docs/meshy-approval-gate.md."""
    tools = list_future_cloud_tools()
    console.print(f"[bold]future cloud tools[/bold] ({len(tools)}):")
    for tool in tools:
        enabled = tool.get("enabled", False)
        gate_marker = "[red]ENABLED[/red]" if enabled else "[green]disabled (gated - safe default)[/green]"
        console.print(f"\n[bold]{tool['tool_id']}[/bold]  {gate_marker}")
        console.print(f"  status: {tool.get('status')}")
        console.print(f"  requires_explicit_human_approval: {tool.get('requires_explicit_human_approval')}")
        console.print(f"  requires_cost_cap: {tool.get('requires_cost_cap')}")
        console.print(f"  requires_per_run_confirmation: {tool.get('requires_per_run_confirmation')}")
        console.print(f"  allows_uploads: {tool.get('allows_uploads')}")
        console.print(f"  allows_api_calls: {tool.get('allows_api_calls')}")
        for note in tool.get("notes", []):
            console.print(f"  note: {note}")

    console.print(
        "\nThis command only reads config/future_cloud_tools.json - it did not contact any network, "
        "read .env, validate credentials, install a dependency, or enable anything. See "
        "docs/meshy-approval-gate.md."
    )


@app.command(name="check-local-tools")
def check_local_tools_cmd() -> None:
    """Read-only report of future local (non-cloud) tool gates (e.g. Blender). Never launches a
    tool, never searches for an installed application, never calls subprocess, never installs or
    enables anything. See docs/blender-local-track.md."""
    tools = list_future_local_tools()
    console.print(f"[bold]future local tools[/bold] ({len(tools)}):")
    for tool in tools:
        enabled = tool.get("enabled", False)
        gate_marker = "[red]ENABLED[/red]" if enabled else "[green]disabled (gated - safe default)[/green]"
        console.print(f"\n[bold]{tool['tool_id']}[/bold]  {gate_marker}")
        console.print(f"  status: {tool.get('status')}")
        console.print(f"  local_blender_path: {tool.get('local_blender_path')}")
        console.print(f"  requires_explicit_human_approval: {tool.get('requires_explicit_human_approval')}")
        console.print(f"  requires_local_path_review: {tool.get('requires_local_path_review')}")
        console.print(f"  allows_automation: {tool.get('allows_automation')}")
        console.print(f"  allows_addons: {tool.get('allows_addons')}")
        console.print(f"  allows_mcp: {tool.get('allows_mcp')}")
        console.print(f"  allows_printer_or_slicer_calls: {tool.get('allows_printer_or_slicer_calls')}")
        for note in tool.get("notes", []):
            console.print(f"  note: {note}")

    console.print(
        "\nThis command only reads config/future_local_tools.json - it did not launch a tool, "
        "search for an installed application, call subprocess, install a dependency, or enable "
        "anything. See docs/blender-local-track.md."
    )


@app.command(name="check-design-intent")
def check_design_intent_cmd(
    brief_path: Path = typer.Argument(..., help="Path to a brief.json or concept_brief.json"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Read-only advisory check: does design_intent.manufacturability_constraints.max_size_mm
    (if present) fit any locally configured printer's build volume? Never contacts a printer,
    slicer, or network; never writes a file; never sets human_approved or print_ready.
    See docs/design-intent-brief.md."""
    result = check_design_intent_manufacturability(brief_path)

    if as_json:
        print(json.dumps(result, indent=2, sort_keys=False))
    else:
        console.print(f"[bold]file[/bold]: {result['file']}")
        console.print(f"[bold]result[/bold]: {result['result']}")
        console.print(f"  quality standard: {result['quality_standard'] or '(not set)'}")
        console.print(f"  requested max size (mm): {result['max_size_mm'] or '(not set)'}")

        if result["fitting_printers"]:
            console.print(f"\n[green]fits[/green] ({len(result['fitting_printers'])} known printer(s)):")
            for printer in result["fitting_printers"]:
                bv = printer["build_volume_mm"]
                verified_note = "" if printer["verified"] else "  [yellow](UNVERIFIED spec)[/yellow]"
                console.print(
                    f"  - {printer['display_name']}  ({bv.get('x')}x{bv.get('y')}x{bv.get('z')}mm)"
                    f"{verified_note}"
                )
        if result["non_fitting_printers"]:
            console.print(f"\n[red]does not fit[/red] ({len(result['non_fitting_printers'])} known printer(s)):")
            for printer in result["non_fitting_printers"]:
                bv = printer["build_volume_mm"]
                console.print(f"  - {printer['display_name']}  ({bv.get('x')}x{bv.get('y')}x{bv.get('z')}mm)")

        if result["warnings"]:
            console.print("\n[yellow]advisory warnings[/yellow]:")
            for warning in result["warnings"]:
                console.print(f"  - {warning}")

        console.print()
        for note in result["notes"]:
            console.print(note)
        console.print(
            "\nThis command only read the given file and config/manufacturing/printers.json - "
            "it did not contact a printer, slicer, or network, and did not write anything."
        )

    if result["result"] == "unreadable_file":
        raise typer.Exit(code=1)


reference_board_app = typer.Typer(
    name="reference-board",
    help=(
        "Create, view, validate, and add to a project's local Reference Board (Phase 28/29). "
        "Fully local - no search, scraping, downloading, or network/API calls of any kind. "
        "See docs/reference-board.md."
    ),
    no_args_is_help=True,
)
app.add_typer(reference_board_app, name="reference-board")


def _humanize(value: str | None) -> str:
    """Display-only formatting for an enum value, e.g. 'style_reference' ->
    'Style Reference'. Not used for anything read back by this program -
    purely cosmetic CLI text."""
    if not value:
        return "Not specified"
    return value.replace("_", " ").title()


@reference_board_app.command(name="init")
def reference_board_init_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory (e.g. projects/<slug> or examples/<name>)"),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing reference_board.json with a fresh starter file"),
) -> None:
    """Create <project_dir>/reference_board.json with a documented starter shape,
    if one doesn't already exist. Never overwrites an existing file unless --force
    is given. Local only - writes exactly one JSON file, nothing else."""
    try:
        path, created = init_reference_board(project_dir, force=force)
    except ProjectDirectoryNotFoundError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)

    if created:
        console.print(f"[green]created[/green] {path}")
    else:
        console.print(f"[yellow]already exists[/yellow]: {path} (use --force to overwrite with a fresh starter file)")
    console.print(
        "Local only - nothing in a Reference Board is fetched, downloaded, scraped, or searched "
        "automatically. See docs/reference-board.md."
    )


@reference_board_app.command(name="show")
def reference_board_show_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable summary"),
) -> None:
    """Print a human-readable summary of a project's Reference Board: reference
    count, warning count, a license-status breakdown, and a usage-intent
    breakdown. Read-only - never fetches or contacts anything."""
    if not Path(project_dir).is_dir():
        console.print(f"[red]error[/red]: {project_dir} is not a directory - check the path.")
        raise typer.Exit(code=1)

    summary = summarize_reference_board(project_dir)

    if as_json:
        print(json.dumps(summary, indent=2, sort_keys=False))
        return

    console.print("[bold]Reference Board[/bold]")
    console.print(f"\n[bold]References[/bold]: {summary['reference_count']}")
    console.print(f"[bold]Warnings[/bold]: {len(summary['warnings'])}")

    if not summary["reference_count"]:
        console.print("\nNo references recorded for this project yet - run `factory reference-board init` "
                      "or `factory reference-board add` to get started.")
        return

    console.print("\n[bold]License Status[/bold]")
    for license_value, count in sorted(summary["by_license"].items()):
        console.print(f"  {_humanize(license_value)}: {count}")

    console.print("\n[bold]Usage[/bold]")
    if summary["by_usage_intent"]:
        for usage_value, count in sorted(summary["by_usage_intent"].items()):
            console.print(f"  {_humanize(usage_value)}: {count}")
    else:
        console.print("  Not specified")


@reference_board_app.command(name="validate")
def reference_board_validate_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable report"),
) -> None:
    """Advisory validation of a project's Reference Board. Never fails just because
    information is incomplete (missing license, missing URL, unsupported value,
    a remix candidate with an unclear license, ...) - those are always warnings.
    The only error condition is reference_board.json existing but not being valid
    JSON."""
    try:
        check_reference_board_json_is_valid(project_dir)
    except MalformedReferenceBoardError as exc:
        if as_json:
            print(json.dumps({"result": "invalid_json", "error": str(exc)}, indent=2))
        else:
            console.print(f"[red]✗ invalid reference_board.json[/red]: {exc}")
        raise typer.Exit(code=1)

    summary = summarize_reference_board(project_dir)

    if as_json:
        print(json.dumps({"result": "valid", **summary}, indent=2, sort_keys=False))
        return

    console.print("[green]✓[/green] Valid reference board")
    if summary["warnings"]:
        console.print("\n[bold]Warnings[/bold]")
        for warning in summary["warnings"]:
            console.print(f"  - {warning}")
    else:
        console.print("\nNo warnings.")


@reference_board_app.command(name="list")
def reference_board_list_cmd(
    project_dir: Path = typer.Argument(..., help="Path to a project directory"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable listing"),
) -> None:
    """Compact, per-reference listing (title, source type, license, usage intent)
    for a project's Reference Board. Read-only - never fetches or contacts
    anything."""
    if not Path(project_dir).is_dir():
        console.print(f"[red]error[/red]: {project_dir} is not a directory - check the path.")
        raise typer.Exit(code=1)

    references = normalize_references(project_dir)

    if as_json:
        print(json.dumps(references, indent=2, sort_keys=False))
        return

    if not references:
        console.print("No references recorded for this project.")
        return

    for i, reference in enumerate(references):
        if i:
            console.print("-" * 20)
        console.print(f"\n[bold]{i + 1}[/bold]")
        console.print(reference["title"])
        console.print("\n[bold]Type[/bold]:")
        console.print(_humanize(reference["source_type"]))
        console.print("\n[bold]License[/bold]:")
        console.print(_humanize(reference["license"]))
        console.print("\n[bold]Usage[/bold]:")
        console.print(_humanize(reference["usage_intent"]))


@reference_board_app.command(name="add")
def reference_board_add_cmd(
    project_dir: Path = typer.Option(..., "--project", help="Path to a project directory"),
    title: str = typer.Option(..., "--title", help="Reference title"),
    url: Optional[str] = typer.Option(None, "--url", help="Source URL - stored as inert metadata only, never fetched"),
    source_type: Optional[str] = typer.Option(None, "--type", help=f"One of: {', '.join(SOURCE_TYPES)}"),
    license_value: Optional[str] = typer.Option(None, "--license", help=f"One of: {', '.join(LICENSES)}"),
    usage: Optional[str] = typer.Option(None, "--usage", help=f"One of: {', '.join(USAGE_INTENTS)}"),
    attached_to: Optional[str] = typer.Option(None, "--attached-to", help=f"One of: {', '.join(ATTACHED_TO_VALUES)}"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Free-text notes"),
) -> None:
    """Append one new reference to <project>/reference_board.json (creating the
    file first, with a documented starter shape, if it doesn't exist yet).
    Always appends - never overwrites or removes an existing entry. An
    unrecognized --type/--license/--usage/--attached-to value is still saved
    (never rejected) and reported back as an advisory warning."""
    try:
        entry, warnings = add_reference(
            project_dir,
            title=title,
            source_url=url,
            source_type=source_type,
            license=license_value,
            usage_intent=usage,
            attached_to=attached_to,
            notes=notes,
        )
    except ProjectDirectoryNotFoundError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)
    except MalformedReferenceBoardError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)

    path = Path(project_dir) / "reference_board.json"
    console.print(f"[green]added[/green] {entry['title']!r} to {path}")
    if warnings:
        console.print("\n[yellow]advisory warnings[/yellow]:")
        for warning in warnings:
            console.print(f"  - {warning}")
    console.print(
        "\nLocal only - this reference's source_url (if any) was saved as plain text, never fetched, "
        "downloaded, scraped, or searched."
    )


intake_app = typer.Typer(
    name="intake",
    help=(
        "Analyze a free-form project idea (plain text, Markdown, or an existing project's brief.json) "
        "into structured intake metadata (Phase 30). Fully local and fully deterministic - no AI, no LLM, "
        "no network, no search. See docs/project-intake.md."
    ),
    no_args_is_help=True,
)
app.add_typer(intake_app, name="intake")


def _capitalize_first(value: str) -> str:
    return value[0].upper() + value[1:] if value else value


def _print_intake_field(label: str, field: dict, *, humanize: bool = True) -> None:
    value = field.get("value")
    if isinstance(value, list):
        display = ", ".join(_capitalize_first(v) if humanize else v for v in value) if value else "(none detected)"
    elif isinstance(value, bool):
        display = "Yes" if value else "No"
    elif value is None:
        display = "(not detected)"
    elif humanize:
        display = _capitalize_first(value)
    else:
        display = value
    console.print(f"[bold]{label}[/bold]: {display}  [dim](confidence: {field.get('confidence')})[/dim]")


@intake_app.command(name="analyze")
def intake_analyze_cmd(
    path: Path = typer.Argument(..., help="A project directory, or a plain-text/Markdown file describing the idea"),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable summary"),
) -> None:
    """Analyze a project idea into structured intake metadata: category, audience,
    environment, material/printer assumptions, quality target, manufacturing style,
    functional/visual goals, dimensional constraints, and commercial intent - each
    with a confidence level, plus advisory warnings. Accepts a project directory
    (reads brief.json's project_name/description/constraints) or a plain-text/
    Markdown file. Fully local, fully deterministic (no AI, no LLM, no network, no
    search) - see docs/project-intake.md."""
    summary = analyze_intake(path)

    if as_json:
        print(json.dumps(summary, indent=2, sort_keys=False, ensure_ascii=False))
        return

    console.print("[bold]Project Intake Analysis[/bold]")
    console.print(f"source: {summary['source']}\n")

    _print_intake_field("Project name", summary["project_name"], humanize=False)
    _print_intake_field("Category", summary["category"])
    _print_intake_field("Purpose", summary["purpose"], humanize=False)
    _print_intake_field("Audience", summary["audience"], humanize=False)
    _print_intake_field("Environment", summary["environment"])
    _print_intake_field("Material assumptions", summary["material_assumptions"], humanize=False)
    _print_intake_field("Printer assumptions", summary["printer_assumptions"], humanize=False)
    _print_intake_field("Quality target", summary["quality_target"])
    _print_intake_field("Manufacturing style", summary["manufacturing_style"])
    _print_intake_field("Functional goals", summary["functional_goals"], humanize=False)
    _print_intake_field("Visual goals", summary["visual_goals"])
    _print_intake_field("Dimensional constraints", summary["dimensional_constraints"], humanize=False)
    _print_intake_field("Commercial intent", summary["commercial_intent"])

    if summary["warnings"]:
        console.print("\n[yellow]advisory warnings[/yellow]:")
        for warning in summary["warnings"]:
            console.print(f"  - {warning}")
    else:
        console.print("\nNo advisory warnings.")

    console.print(
        "\nThis is a fully local, deterministic heuristic analysis - no AI, no LLM, no network, and no "
        "search were used. See docs/project-intake.md."
    )


def _print_draft_field(label: str, value: Any, *, humanize: bool = True) -> None:
    if isinstance(value, list):
        display = ", ".join(_capitalize_first(v) if humanize else v for v in value) if value else "not specified"
    elif isinstance(value, bool):
        display = "Yes" if value else "unknown"
    elif value is None:
        display = "unknown"
    elif humanize:
        display = _capitalize_first(value)
    else:
        display = value
    console.print(f"  [bold]{label}[/bold]: {display}")


def _format_merge_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_capitalize_first(v) for v in value) if value else "not specified"
    if isinstance(value, str):
        return _capitalize_first(value)
    return str(value)


def _print_merge_preview(merge_result: dict) -> None:
    console.print("\n[bold]Fields to add[/bold]:")
    if merge_result["fields_to_add"]:
        for field_key, value in merge_result["fields_to_add"].items():
            console.print(f"  - {field_key}: {_format_merge_value(value)}")
    else:
        console.print("  (none)")

    console.print("\n[bold]Fields preserved[/bold]:")
    if merge_result["fields_preserved"]:
        for field_key in merge_result["fields_preserved"]:
            console.print(f"  - {field_key}: existing value kept")
    else:
        console.print("  (none)")

    console.print("\n[bold]Warnings[/bold]:")
    for advisory in merge_result["advisories"]:
        console.print(f"  - {advisory}")


@intake_app.command(name="suggest-brief")
def intake_suggest_brief_cmd(
    path: Path = typer.Argument(
        ...,
        help="A project directory, a plain-text/Markdown idea file, or a saved `factory intake analyze --json` output file",
    ),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON instead of the human-readable draft"),
    write: bool = typer.Option(
        False, "--write", help="Write the draft as <project_dir>/brief.json (path must be a project directory)"
    ),
    force: bool = typer.Option(False, "--force", help="With --write, replace an existing brief.json"),
    update: bool = typer.Option(
        False,
        "--update",
        help=(
            "Preview (or, with --write, apply) a safe merge onto an existing brief.json instead of a full "
            "replace - never overwrites a field that already has real content. Incompatible with --force."
        ),
    ),
) -> None:
    """Generate a deterministic, human-reviewable draft brief/design_intent/
    manufacturing-notes from an intake_summary (Phase 30) - never re-parses free
    text itself, only shapes what `factory intake analyze` already extracted, and
    only populates a field when its confidence is high/medium (an absent/unclear
    field stays explicitly unknown - never invented). Without --write, this is
    entirely read-only: nothing is saved.

    With --write alone, writes exactly one file, <project_dir>/brief.json, and
    only after confirming the project directory exists and brief.json doesn't
    already exist (use --force to replace it intentionally - a full, wholesale
    replacement).

    With --update, previews (or, combined with --write, applies) a safe MERGE
    onto an existing brief.json instead: every field that already holds real,
    non-placeholder content is preserved untouched; only genuinely missing/
    placeholder fields are filled from a confident draft value. --force and
    --update are mutually exclusive (full replace vs. safe merge - pick one).
    If no brief.json exists yet, --update has nothing to merge into and this
    falls back to the plain --write behavior above.

    Human review and approval are always required before saving - see
    docs/brief-generator.md."""
    if update and force:
        console.print(
            "[red]error[/red]: --force and --update are incompatible - --force fully replaces an existing "
            "brief.json, --update safely merges into one. Choose one."
        )
        raise typer.Exit(code=1)

    try:
        intake = load_intake_summary_from_path(path)
    except MalformedIntakeSummaryError as exc:
        console.print(f"[red]error[/red]: {exc}")
        raise typer.Exit(code=1)

    draft = generate_draft(intake)

    existing_brief = None
    if update and path.is_dir():
        try:
            existing_brief = load_existing_brief(path)
        except MalformedExistingBriefError as exc:
            console.print(f"[red]error[/red]: {exc}")
            raise typer.Exit(code=1)

    if update and existing_brief is not None:
        merge_result = merge_draft_brief(existing_brief, draft["brief"])
        wrote_file: str | None = None

        if write:
            try:
                written_path = write_merged_brief(path, existing_brief, merge_result)
            except DraftProjectDirectoryNotFoundError as exc:
                console.print(f"[red]error[/red]: {exc}")
                raise typer.Exit(code=1)
            wrote_file = str(written_path)

        if as_json:
            payload = {
                "draft": draft,
                "merge_preview": merge_result,
                "fields_to_add": merge_result["fields_to_add"],
                "fields_preserved": merge_result["fields_preserved"],
                "advisories": merge_result["advisories"],
                "would_write": write,
                "wrote_file": wrote_file,
            }
            print(json.dumps(payload, indent=2, sort_keys=False, ensure_ascii=False))
            return

        if wrote_file:
            console.print(f"[green]merged and wrote[/green] {wrote_file}")
        else:
            console.print("[bold]Brief Merge Preview[/bold]")
        _print_merge_preview(merge_result)

        if wrote_file:
            console.print(
                "\nThis brief.json was updated by a safe merge - every 'preserved' value above was left "
                "untouched. A human should still review every newly added field before treating this "
                "project as ready to plan or build."
            )
        else:
            console.print("\nThis is a preview only - nothing has been written.")
            console.print("Re-run with --write --update to apply this merge.")
        return

    if update and not as_json:
        console.print(
            "[dim]--update requested but no existing brief.json was found to merge into - generating a "
            "plain draft instead.[/dim]\n"
        )

    if write:
        try:
            written_path = write_draft_brief(path, draft, force=force)
        except DraftProjectDirectoryNotFoundError as exc:
            console.print(f"[red]error[/red]: {exc}")
            raise typer.Exit(code=1)
        except BriefAlreadyExistsError:
            console.print("[yellow]Brief already exists.[/yellow] Use --force to replace.")
            raise typer.Exit(code=1)
        console.print(f"[green]wrote[/green] {written_path}")
        console.print(
            "\nThis brief.json was generated from a deterministic draft - a human should still review "
            "every field (especially anything marked 'unknown') before treating this project as ready "
            "to plan or build."
        )
        return

    if as_json:
        print(json.dumps(draft, indent=2, sort_keys=False, ensure_ascii=False))
        return

    readiness = draft["readiness"]
    brief = draft["brief"]
    design_intent = draft["design_intent"]

    console.print("[bold]Draft Brief Suggestion[/bold]")
    console.print(f"source: {intake.get('source', 'unknown')}")
    console.print(
        f"\n[bold]Status[/bold]: {readiness['status']}   "
        f"[bold]Populated[/bold]: {readiness['percent_populated']}%   "
        f"[bold]Unknown fields[/bold]: {readiness['unknown_count']}"
    )

    console.print("\n[bold]Brief[/bold]")
    _print_draft_field("Project name", brief["project_name"], humanize=False)
    _print_draft_field("Category", brief["category"])
    _print_draft_field("Purpose", brief["purpose"], humanize=False)
    _print_draft_field("Audience", brief["audience"], humanize=False)
    _print_draft_field("Environment", brief["environment"])
    _print_draft_field("Printer", brief["printer"], humanize=False)
    _print_draft_field("Material", brief["material"], humanize=False)
    _print_draft_field("Quality target", brief["quality_target"])
    _print_draft_field("Manufacturing style", brief["manufacturing_style"])
    _print_draft_field("Dimensional constraints", brief["dimensional_constraints"], humanize=False)
    _print_draft_field("Visual goals", brief["visual_goals"])
    _print_draft_field("Functional goals", brief["functional_goals"], humanize=False)
    _print_draft_field("Commercial intent", brief["commercial_intent"])

    console.print("\n[bold]Design Intent[/bold]")
    _print_draft_field("Quality standard", design_intent["quality_target"])
    _print_draft_field("Use case", design_intent["purpose"], humanize=False)
    _print_draft_field("Style", design_intent["style"])
    _print_draft_field("Manufacturing notes", design_intent["manufacturing_notes"])
    console.print("  [bold]Reference inputs[/bold]: none - add via `factory reference-board add`")
    console.print(f"  [bold]Review required[/bold]: {'Yes' if design_intent['review_required'] else 'No'}")

    console.print("\n[bold]Advisories[/bold]")
    for advisory in draft["advisories"]:
        console.print(f"  - {advisory}")

    console.print(
        "\nThis is a DRAFT only - nothing has been written. Re-run with --write to save as "
        "<project_dir>/brief.json after reviewing (never overwrites an existing brief.json unless "
        "--force is also given). See docs/brief-generator.md."
    )


def _print_preview_package_summary(project_dir: Path) -> None:
    index_path, report_path = preview_package_paths(project_dir)
    index = _safe_load(index_path)
    if not index:
        console.print(
            "  preview package: missing - run `factory preview-project <project_dir>` to build it"
        )
        return

    console.print(f"  preview package: {index_path}")
    console.print(f"    preview report: {report_path}")
    console.print(
        f"    CAD files: {len(index.get('cad_files', []))}  |  "
        f"mesh files: {len(index.get('mesh_files', []))}  |  "
        f"renders: {len(index.get('render_files', []))}"
    )
    missing_count = len(index.get("missing_visual_artifacts", []))
    stale_count = len(index.get("stale_previews", []))
    console.print(f"    missing preview items: {missing_count}  |  stale previews: {stale_count}")


_DESIGN_INTENT_RESULT_LABELS = {
    "fits_some_printers": "fits configured printers",
    "fits_no_known_printers": "does not fit any configured printer",
    "no_max_size": "no size declared - nothing to check",
    "invalid_max_size": "declared size is invalid - check skipped",
    "missing_printer_config": "no printers configured - check skipped",
    "no_design_intent": "no design intent recorded",
    "unreadable_file": "brief could not be read",
}


def _print_design_intent_summary(summary: dict | None) -> None:
    """Print a project's `design_intent`, if present. Read-only, display-only:
    visibility for an existing brief field, not a new judgment, score, or gate.
    Prints nothing (not an error) when `summary` is None - most briefs won't
    have a `design_intent` block."""
    if summary is None:
        return

    console.print("\n[bold]Design Intent[/bold]:")
    console.print(f"  Quality standard: {summary['quality_standard'] or '(not set)'}")
    console.print(f"  Use case: {summary['use_case'] or '(not set)'}")
    style = ", ".join(summary["style_direction"]) if summary["style_direction"] else "(not set)"
    console.print(f"  Style: {style}")
    console.print(f"  Declared max size (mm): {summary['max_size_mm'] or '(not set)'}")

    check = summary["manufacturability_check"]
    result_text = _DESIGN_INTENT_RESULT_LABELS.get(check["result"], check["result"])
    console.print(f"  Size check: {result_text}")
    if check["fitting_printers"]:
        console.print(f"    Fits: {', '.join(check['fitting_printers'])}")

    console.print(
        "  (Design intent visibility is advisory only - it does not judge creativity, approve this "
        "design, or replace Etsy-worthy/slicer/human review.)"
    )


def _print_target_printer_summary(build_plan: dict | None) -> None:
    target_printer = (build_plan or {}).get("target_printer") or {}
    if not target_printer:
        console.print("  target printer: (not planned yet - run `factory plan`)")
        return

    display_name = target_printer.get("display_name") or "(unresolved)"
    console.print(f"  target printer: {display_name} (resolved: {target_printer.get('resolved', False)})")

    capabilities = target_printer.get("capabilities")
    if not capabilities:
        return

    build_volume = capabilities.get("build_volume_mm") or {}
    if build_volume:
        console.print(
            f"    build volume: {build_volume.get('x')} x {build_volume.get('y')} x {build_volume.get('z')} mm"
            f" (verified: {capabilities.get('verified', False)})"
        )
    accessories = capabilities.get("installed_accessories") or []
    if accessories:
        names = ", ".join(a.get("display_name", "?") for a in accessories)
        console.print(f"    installed accessories: {names}")
    else:
        console.print("    installed accessories: none")
    console.print(f"    multicolor supported: {capabilities.get('multicolor_supported', False)}")


def _print_manufacturing_options_summary(build_plan: dict | None) -> None:
    manufacturing_options = (build_plan or {}).get("manufacturing_options") or {}
    if not manufacturing_options:
        return

    options = manufacturing_options.get("options", [])
    console.print(f"  manufacturing options ({len(options)} explained):")
    for option in options:
        availability = "" if option.get("available", True) else "  [not available for target printer]"
        console.print(f"    - {option.get('display_name')}{availability}")

    recommended = manufacturing_options.get("recommended_option")
    selected = (build_plan or {}).get("selected_manufacturing_option")
    console.print(f"  recommended option: {recommended!r} (non-binding; selected: {selected!r})")
    if selected:
        console.print(f"  selected manufacturing option: {selected!r}")
    else:
        console.print(
            "  [yellow]unresolved decision[/yellow]: no manufacturing option selected yet - run "
            "`factory list-options` then `factory choose-option`."
        )


def _print_assembly_intent_summary(build_plan: dict | None) -> None:
    if not build_plan:
        return
    assembly_intent = compute_assembly_intent(build_plan)
    console.print(f"  manifest readiness: {assembly_intent['status']}")
    console.print(f"    {assembly_intent['note']}")
    console.print(f"  CAD generation can proceed safely: {assembly_intent['cad_generation_safe']}")
    console.print(f"  multipart planning incomplete: {assembly_intent['multipart_incomplete']}")


def _print_manifest_and_multipart_summary(manifest: dict | None, manifest_checks: list[dict]) -> None:
    parts = (manifest or {}).get("parts", [])
    fail_count = sum(1 for c in manifest_checks if c["status"] == "FAIL")
    warn_count = sum(1 for c in manifest_checks if c["status"] == "WARN")
    console.print(
        f"  manifest completeness: {len(manifest_checks)} check(s) run, {fail_count} FAIL, {warn_count} WARN"
    )
    console.print(f"  multipart summary: {len(parts)} part(s), multi-part: {len(parts) > 1}")


def _print_validation_summary(validation_reports: list[dict]) -> None:
    if not validation_reports:
        return
    fail_count = sum(1 for r in validation_reports if r.get("overall_status") == "FAIL")
    warn_count = sum(1 for r in validation_reports if r.get("overall_status") == "WARN")
    pass_count = len(validation_reports) - fail_count - warn_count
    console.print(
        f"    validation summary: {pass_count} PASS, {warn_count} WARN, {fail_count} FAIL "
        f"across {len(validation_reports)} report(s)"
    )


def _print_remaining_human_decisions(build_plan: dict | None) -> None:
    build_plan = build_plan or {}
    questions = build_plan.get("unanswered_questions", [])
    if build_plan.get("selected_manufacturing_option"):
        # This question is resolved by `factory choose-option`; stale build_plan.json
        # text from `factory plan` shouldn't be presented as still-open.
        questions = [q for q in questions if "selected_manufacturing_option" not in q]

    console.print(f"\n[bold]remaining human decisions[/bold]: {len(questions)}")
    for question in questions:
        console.print(f"  [yellow]-[/yellow] {question}")
    console.print("Human approval is required before anything may be treated as print-ready. See AGENT.md.")


def _safe_load(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return project_store.load_json(path)
    except Exception:  # noqa: BLE001
        return None


def _compute_safe_status(brief: dict | None, has_clean_validation: bool, has_renders: bool, human_approved: bool) -> str:
    if human_approved:
        return "human_approved"
    if has_clean_validation and has_renders:
        return "slicer_review_ready"
    if brief:
        recorded = brief.get("status", "idea")
        if recorded in ("print_ready",):
            return "brief_created"  # never surface print_ready automatically
        return recorded
    return "idea"


if __name__ == "__main__":
    app()

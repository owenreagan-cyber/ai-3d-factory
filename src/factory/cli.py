"""factory CLI - local-first 3D print project assistant.

Phase 0/1: create, organize, validate, preview, and package projects for
human slicer review. Phase 2: local OpenSCAD source generation helpers.
No printing, no cloud calls. See AGENT.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from factory import project_store
from factory.cad import cadquery_backend
from factory.cad.router import route_cad
from factory.examples_library import UnknownExampleError, get_example, list_examples
from factory.future_cloud_tools import list_future_cloud_tools
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
from factory.preview_board import VISUAL_READINESS_STATES, write_preview_board
from factory.preview_package import gather_preview_data, preview_package_paths, write_preview_package
from factory.previews.render_preview import render_preview
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

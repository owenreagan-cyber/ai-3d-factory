"""factory CLI - local-first 3D print project assistant.

Phase 0/1: create, organize, validate, preview, and package projects for
human slicer review. No printing, no cloud calls. See AGENT.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console

from factory import project_store
from factory.planner import plan_from_brief_path
from factory.previews.render_preview import render_preview
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
    "validate <mesh_file>",
    "render <mesh_file>",
    "inspect-slicer",
    "report <project_dir>",
)

STATUS_ICON = {"PASS": "[green]PASS[/green]", "WARN": "[yellow]WARN[/yellow]", "FAIL": "[red]FAIL[/red]"}


def _icon(status: str) -> str:
    return STATUS_ICON.get(status, status)


def _load_primary_printer() -> dict | None:
    printers_path = project_store.CONFIG_DIR / "printers.json"
    if not printers_path.is_file():
        return None
    data = project_store.load_json(printers_path)
    primary = data.get("primary_printer")
    return data.get("printers", {}).get(primary)


@app.command()
def status() -> None:
    """Print repo/environment status and safety posture."""
    config_files = ["printers.json", "materials.json", "tolerances.json", "agent_policy.json"]
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
    console.print(f"  manifest parts: {len(manifest.get('parts', [])) if manifest else '(missing part_manifest.json)'}")
    if manifest:
        for check in check_manifest(manifest, project_dir):
            console.print(f"    {_icon(check['status'])}  {check['name']}: {check['detail']}")
    console.print(f"  STL files: {len(stl_files)}")
    console.print(f"  renders: {len(render_files)}")
    console.print(f"  validation reports: {len(validation_files)} (clean: {has_clean_validation})")
    console.print(f"  slicer review packages: {len(slicer_review_files)}")
    console.print(f"  human approval on record: {human_approved}")
    console.print(f"\n[bold]current safe status[/bold]: {safe_status}")
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

"""Orchestrates writing generated OpenSCAD source into a project.

Local filesystem only: writes .scad files under <project>/cad/, writes
human-facing export instructions under <project>/slicer_review/, and
updates <project>/part_manifest.json. Never invokes OpenSCAD, never
exports an STL, never touches a network or a printer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from factory import project_store
from factory.openscad.templates import TemplateOutput, render_template

EXPORT_INSTRUCTIONS_FILENAME = "openscad_export_instructions.md"
CAD_README_FILENAME = "README.md"


class ProjectNotInitializedError(Exception):
    pass


class GeneratedFileExistsError(Exception):
    def __init__(self, conflicts: list[Path]):
        self.conflicts = conflicts
        joined = ", ".join(str(p) for p in conflicts)
        super().__init__(f"refusing to overwrite existing file(s) without --force: {joined}")


@dataclass(frozen=True)
class GenerateResult:
    template: str
    project_dir: Path
    written_files: tuple[Path, ...]
    manifest_path: Path
    export_instructions_path: Path


def _require_initialized_project(project_dir: Path) -> None:
    required = ("cad", "stl", "slicer_review")
    missing = [sub for sub in required if not (project_dir / sub).is_dir()]
    if missing or not (project_dir / "part_manifest.json").is_file():
        raise ProjectNotInitializedError(
            f"{project_dir} does not look like an initialized factory project "
            f"(missing: {missing or ['part_manifest.json']}). Run `factory init-project` first."
        )


def _write_cad_readme(cad_dir: Path, output: TemplateOutput) -> None:
    readme_path = cad_dir / CAD_README_FILENAME
    file_list = "\n".join(f"- `{f.filename}`" for f in output.files)
    content = (
        f"# cad/\n\n"
        f"Generated OpenSCAD source. Most recent generation: template `{output.template}` "
        f"(via `factory generate-openscad --template {output.template}`).\n\n"
        f"Files from that run:\n{file_list}\n\n"
        "These are plain, human-editable OpenSCAD (.scad) files - feel free to open and "
        "adjust the parameters at the top of each file. After editing, re-export to STL "
        "and re-run `factory validate` / `factory render` before treating the part as done.\n\n"
        "This repo does not run OpenSCAD automatically. See "
        f"`../slicer_review/{EXPORT_INSTRUCTIONS_FILENAME}` for the exact export commands.\n"
    )
    readme_path.write_text(content, encoding="utf-8")


def _write_export_instructions(project_dir: Path) -> Path:
    cad_dir = project_dir / "cad"
    scad_files = sorted(p.name for p in cad_dir.glob("*.scad"))

    lines = [
        "# OpenSCAD export instructions",
        "",
        "This file lists the local commands to export each generated .scad file to an STL.",
        "**Nothing in this repo runs these commands automatically.** Run them yourself, in a",
        "terminal, only after you've reviewed the .scad source. This requires OpenSCAD to be",
        "installed locally (see ai-3d-factory-installer).",
        "",
        "```bash",
    ]
    for name in scad_files:
        stem = Path(name).stem
        lines.append(f"openscad -o stl/{stem}.stl cad/{name}")
    lines.append("```")
    lines.append("")
    lines.append(
        "After exporting, run `factory validate stl/<name>.stl` and `factory render "
        "stl/<name>.stl` on each exported file, then update `part_manifest.json` with the "
        "real material/color choices before requesting human slicer review. See "
        "`docs/slicer-review-workflow.md`."
    )
    lines.append("")
    lines.append(
        "This repo never slices, prints, or uploads anything - exporting to STL is the last "
        "step this documentation covers."
    )
    lines.append("")

    out_path = project_dir / "slicer_review" / EXPORT_INSTRUCTIONS_FILENAME
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _upsert_manifest_parts(project_dir: Path, output: TemplateOutput) -> Path:
    manifest_path = project_dir / "part_manifest.json"
    manifest = project_store.load_json(manifest_path) if manifest_path.is_file() else {"parts": []}
    parts = manifest.setdefault("parts", [])
    by_name = {p.get("part_name"): p for p in parts}

    for generated_part in output.parts:
        stem = Path(generated_part.cad_filename).stem
        entry = {
            "part_name": generated_part.part_name,
            "file_path": f"stl/{stem}.stl",
            "material": generated_part.material_hint,
            "color": generated_part.color_hint,
            "transform_notes": generated_part.transform_notes,
            "export_units": "mm",
            "source": f"ai-3d-factory OpenSCAD template: {output.template}",
            "license": "original",
            "role": generated_part.role,
            "required_for_assembly": True,
            "cad_source": f"cad/{generated_part.cad_filename}",
        }
        if generated_part.part_name in by_name:
            by_name[generated_part.part_name].update(entry)
        else:
            parts.append(entry)
            by_name[generated_part.part_name] = entry

    project_store.save_json(manifest_path, manifest)
    return manifest_path


def generate_openscad(project_dir: Path, template: str, text: str | None, force: bool = False) -> GenerateResult:
    project_dir = Path(project_dir)
    _require_initialized_project(project_dir)

    output = render_template(template, text)

    cad_dir = project_dir / "cad"
    target_paths = [cad_dir / f.filename for f in output.files]

    if not force:
        conflicts = [p for p in target_paths if p.exists()]
        if conflicts:
            raise GeneratedFileExistsError(conflicts)

    for generated_file, target_path in zip(output.files, target_paths):
        target_path.write_text(generated_file.content, encoding="utf-8")

    _write_cad_readme(cad_dir, output)
    export_instructions_path = _write_export_instructions(project_dir)
    manifest_path = _upsert_manifest_parts(project_dir, output)

    brief_path = project_dir / "brief.json"
    if brief_path.is_file():
        brief = project_store.load_json(brief_path)
        if project_store.advance_status(brief, "cad_generated"):
            project_store.save_json(brief_path, brief)

    return GenerateResult(
        template=template,
        project_dir=project_dir,
        written_files=tuple(target_paths),
        manifest_path=manifest_path,
        export_instructions_path=export_instructions_path,
    )

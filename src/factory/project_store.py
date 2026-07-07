"""Repo layout, project scaffolding, and JSON read/write helpers.

Everything here is local filesystem only. No network calls, no printer
control, no cloud upload.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
MANUFACTURING_CONFIG_DIR = CONFIG_DIR / "manufacturing"
SCHEMAS_DIR = REPO_ROOT / "schemas"
PROJECTS_DIR = REPO_ROOT / "projects"

PROJECT_SUBDIRS = (
    "cad",
    "stl",
    "renders",
    "validation",
    "slicer_review",
    "final_candidate",
)

PROJECT_STATUSES = (
    "idea",
    "brief_created",
    "plan_drafted",
    "plan_approved",
    "cad_generated",
    "mesh_exported",
    "geometry_validated",
    "dimension_validated",
    "preview_rendered",
    "slicer_review_ready",
    "human_approved",
    "print_ready",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(name: str) -> str:
    """Turn a project name into a filesystem-safe slug."""
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    if not slug:
        raise ValueError(f"project name {name!r} produces an empty slug")
    return slug


def load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write("\n")


def project_dir(slug: str) -> Path:
    return PROJECTS_DIR / slug


def find_project_root(path: Path) -> Path | None:
    """If `path` lives under projects/<slug>/..., return that project's root dir."""
    try:
        resolved = path.resolve()
        projects_resolved = PROJECTS_DIR.resolve()
    except OSError:
        return None
    if projects_resolved not in resolved.parents:
        return None
    relative = resolved.relative_to(projects_resolved)
    if not relative.parts:
        return None
    return projects_resolved / relative.parts[0]


def status_index(status: str) -> int:
    try:
        return PROJECT_STATUSES.index(status)
    except ValueError:
        return -1


def advance_status(brief: dict, new_status: str) -> bool:
    """Move brief['status'] forward to new_status, but never backward.

    Returns True if the status changed. Never advances to print_ready or
    human_approved - those require an explicit human action, not a
    `factory` command.
    """
    if new_status in ("print_ready", "human_approved"):
        raise ValueError(f"{new_status!r} may not be set by advance_status(); it requires explicit human action.")
    current = brief.get("status", "idea")
    if status_index(new_status) > status_index(current):
        brief["status"] = new_status
        return True
    return False


def default_brief(project_name: str) -> dict:
    return {
        "project_name": project_name,
        "status": "brief_created",
        "owner": "Owen",
        "intended_printer": "Bambu H2D",
        "description": "TODO: describe the part(s) this project will produce.",
        "constraints": [
            "TODO: list real-world measurement constraints, if any.",
        ],
        "required_human_approval": True,
    }


def init_project(name: str) -> Path:
    """Scaffold projects/<slug>/ with its standard subfolders and starter JSON files.

    Never overwrites an existing project directory.
    """
    slug = slugify(name)
    root = project_dir(slug)
    if root.exists():
        raise FileExistsError(f"project already exists at {root}")

    root.mkdir(parents=True)
    for sub in PROJECT_SUBDIRS:
        (root / sub).mkdir()

    save_json(root / "brief.json", default_brief(name))
    save_json(
        root / "build_plan.json",
        {
            "status": "brief_created",
            "note": "Not yet planned. Run `factory plan` on this project's brief.json to populate this file.",
        },
    )
    save_json(root / "part_manifest.json", {"parts": []})

    return root

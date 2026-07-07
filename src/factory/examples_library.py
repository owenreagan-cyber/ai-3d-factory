"""Read-only local inspection of the `examples/` library.

A small, static, hand-maintained registry describing each example project
under `examples/` - never scans arbitrary directories, never generates,
renders, exports, validates, or contacts anything. See
`docs/examples-library.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from factory import project_store

EXAMPLES_DIR = project_store.REPO_ROOT / "examples"

_SAFETY_NOTES_WORKING = (
    "Local only - no network, cloud API, printer, or slicer automation was used to build this example.",
    "No human_approved or print_ready field anywhere in this example. Not print-ready.",
    "Stops at the CAD-source stage (no STL committed) - see this example's own README.md to continue it locally.",
)

_SAFETY_NOTES_MULTIPART_WORKING = (
    "Local only - no network, cloud API, printer, or slicer automation was used to build this example.",
    "No human_approved or print_ready field anywhere in this example. Demo only - not print-ready.",
    "Multi-part assembly demo (3 parts sharing one origin) - stops at the CAD-source stage (no STL/PNG "
    "committed for any part) - see this example's own README.md to continue it locally.",
)

_SAFETY_NOTES_CONCEPT = (
    "Concept-only - no CAD, mesh, render, or generated asset exists for this example.",
    "Requires a future Blender local-automation phase and/or a Meshy safety/cost approval gate before any generation may occur.",
    "Not expected to pass `factory review-gate` - excluded from working-example expectations by design.",
)


@dataclass(frozen=True)
class ExampleInfo:
    name: str
    relative_path: str
    type: str  # "working" | "future-concept"
    backend: str  # "openscad" | "cadquery" | "future_blender" | "future_meshy" | "mixed"
    status: str  # "demo_only" | "concept_only" | "slicer_review_ready_possible" | "cad_generated"
    safety_notes: tuple[str, ...]


_REGISTRY: tuple[ExampleInfo, ...] = (
    ExampleInfo(
        name="simple-nameplate",
        relative_path="examples/simple-nameplate",
        type="working",
        backend="openscad",
        status="slicer_review_ready_possible",
        safety_notes=_SAFETY_NOTES_WORKING,
    ),
    ExampleInfo(
        name="mechanical-plate",
        relative_path="examples/mechanical-plate",
        type="working",
        backend="openscad",
        status="slicer_review_ready_possible",
        safety_notes=_SAFETY_NOTES_WORKING,
    ),
    ExampleInfo(
        name="multipart-classroom-sign",
        relative_path="examples/multipart-classroom-sign",
        type="working",
        backend="openscad",
        status="cad_generated",
        safety_notes=_SAFETY_NOTES_MULTIPART_WORKING,
    ),
    ExampleInfo(
        name="future-organic-models/car-concept",
        relative_path="examples/future-organic-models/car-concept",
        type="future-concept",
        backend="mixed",
        status="concept_only",
        safety_notes=_SAFETY_NOTES_CONCEPT,
    ),
    ExampleInfo(
        name="future-organic-models/animal-concept",
        relative_path="examples/future-organic-models/animal-concept",
        type="future-concept",
        backend="mixed",
        status="concept_only",
        safety_notes=_SAFETY_NOTES_CONCEPT,
    ),
    ExampleInfo(
        name="future-organic-models/human-figure-study",
        relative_path="examples/future-organic-models/human-figure-study",
        type="future-concept",
        backend="mixed",
        status="concept_only",
        safety_notes=_SAFETY_NOTES_CONCEPT,
    ),
)


class UnknownExampleError(Exception):
    pass


def _to_dict(info: ExampleInfo) -> dict[str, Any]:
    path = project_store.REPO_ROOT / info.relative_path
    return {
        "name": info.name,
        "path": info.relative_path,
        "exists": path.is_dir(),
        "type": info.type,
        "backend": info.backend,
        "status": info.status,
        "safety_notes": list(info.safety_notes),
    }


def list_examples() -> list[dict[str, Any]]:
    """Return every registered example's metadata. Read-only: only checks whether each path
    exists on disk - never generates, renders, exports, validates, or contacts anything."""
    return [_to_dict(info) for info in _REGISTRY]


def get_example(name: str) -> dict[str, Any]:
    """Return one registered example's metadata by name. Read-only, same guarantees as list_examples()."""
    for info in _REGISTRY:
        if info.name == name:
            return _to_dict(info)
    known = ", ".join(info.name for info in _REGISTRY)
    raise UnknownExampleError(f"Unknown example {name!r}. Known examples: {known}")

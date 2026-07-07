"""Shared CAD generation backend model.

Defines a common result shape (`GeneratedCadResult`) and a small backend
registry (`BACKENDS`) so future CAD engines describe themselves the same
way without forcing their internals into one shared implementation. The
existing OpenSCAD generator (`factory.openscad`) and the CadQuery starter
(`factory.cad.cadquery_backend`) both populate this shape; neither is
rewritten to depend on the other. See docs/cad-backends.md.

Nothing here generates geometry, writes files, or contacts a network,
printer, or slicer - it is pure data and a local availability check.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CadBackendInfo:
    """Describes one CAD backend for routing/reporting purposes."""

    backend_id: str
    display_name: str
    supported_categories: tuple[str, ...]
    status: str  # "available" | "not_installed" | "future" | "future_gated"
    notes: str


@dataclass(frozen=True)
class GeneratedCadResult:
    """Common shape for what a CAD backend produced in one project.

    `expected_mesh_files` may not exist on disk yet - STL export is always a
    manual, human-run step in this repo (see AGENT.md); this only records
    where that export is expected to land.
    """

    backend_id: str
    template: str
    project_dir: Path
    source_files: tuple[Path, ...]
    expected_mesh_files: tuple[Path, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
    human_actions_required: tuple[str, ...] = field(default_factory=tuple)
    safety_notes: tuple[str, ...] = field(default_factory=tuple)


def is_cadquery_available() -> bool:
    """Check whether the `cadquery` package is importable, without importing it.

    Never installs anything. A pure local environment check.
    """
    return importlib.util.find_spec("cadquery") is not None


def get_backend_registry() -> dict[str, CadBackendInfo]:
    """Return the CAD backend registry, recomputed each call.

    Recomputing (rather than caching at import time) keeps `cadquery`'s
    `status` accurate if the environment changes within a process (and lets
    tests exercise both states via monkeypatching `is_cadquery_available`).
    """
    return _build_backends()


def _build_backends() -> dict[str, CadBackendInfo]:
    return {
        "openscad": CadBackendInfo(
            backend_id="openscad",
            display_name="OpenSCAD",
            supported_categories=(
                "sign",
                "plate",
                "text",
                "label",
                "frame",
                "organizer",
                "tile",
                "flat_decorative",
                "simple_parametric",
            ),
            status="available",
            notes=(
                "Implemented since Phase 2 - see `factory generate-openscad` and "
                "docs/openscad-generation.md. Writes .scad source only; STL export is manual."
            ),
        ),
        "cadquery": CadBackendInfo(
            backend_id="cadquery",
            display_name="CadQuery",
            supported_categories=(
                "bracket",
                "adapter",
                "mount",
                "clip",
                "hinge",
                "mechanical_fixture",
                "enclosure",
                "box_with_fillets_or_chamfers",
                "dimensioned_functional_solid",
            ),
            status="available" if is_cadquery_available() else "not_installed",
            notes=(
                "Implemented since Phase 7 - see `factory generate-cadquery` and "
                "docs/cad-backends.md. Optional dependency: this repo never installs it; "
                "the command fails with a clear message if it isn't already present. "
                "Writes CadQuery .py source only; STL export is manual."
            ),
        ),
        "blender": CadBackendInfo(
            backend_id="blender",
            display_name="Blender",
            supported_categories=("organic_cleanup", "sculptural_form", "mesh_repair", "advanced_render"),
            status="future",
            notes=(
                "Reserved for organic mesh cleanup, sculptural forms, mesh repair, and "
                "higher-fidelity rendering. Not implemented as a generation backend yet - "
                "see docs/roadmap.md."
            ),
        ),
        "meshy": CadBackendInfo(
            backend_id="meshy",
            display_name="Meshy",
            supported_categories=("organic_concept_generation",),
            status="future_gated",
            notes=(
                "Reserved for organic concept generation only, gated behind explicit "
                "per-use human approval and a visible cost estimate. Not implemented in "
                "this repo - see docs/roadmap.md and docs/licensing-policy.md."
            ),
        ),
    }

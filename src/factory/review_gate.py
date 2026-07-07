"""Local, read-only "ready for human slicer review" gate for one project.

Deterministically answers one narrow question: does this project have
everything a human needs on disk to sit down and review it in a slicer?
This reuses `factory.project_inspection.summarize_project()` (which itself
reuses `factory.preview_package` and `factory.render_coverage`) instead of
re-deriving brief/manifest/render/validation state - the gate reads the
already-computed `health_signals` items by `kind` and applies its own
pass/warn/fail policy on top, tailored specifically to "is this ready to
put in front of a human in a slicer" (stricter about renders than
`factory.preview_board`'s general-purpose health check, since a missing
render means there's nothing to look at yet). This module depends only on
`factory.project_inspection`, not on `factory.preview_board` - the two
surfaces (single-project gate, multi-project board) share the inspection
layer without either depending on the other.

This module never renders, validates, exports, generates CAD, invokes a
slicer, contacts a printer, or contacts a network - it only reads files
`summarize_project()` already reads. Passing this gate ("result": "pass")
means only "ready for human slicer review" - it never sets, implies, or
computes `human_approved` or `print_ready`. The highest status ceiling
this gate ever names is `slicer_review_ready`. See docs/review-gate.md,
docs/architecture.md, and AGENT.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory.project_inspection import summarize_project

GATE_NAME = "human_slicer_review"
STATUS_CEILING = "slicer_review_ready"

REQUIRED_SAFETY_LINES = (
    "This gate only determines readiness for HUMAN slicer review.",
    "Passing this gate is not an approval and not a print-readiness signal.",
    "Human visual inspection required.",
    "Human slicer review required.",
    "This project is NOT print-ready.",
)

# Health-signal `kind`s (see factory.project_inspection.build_health_signals) that
# this gate treats as hard blockers ("fail"), regardless of the severity
# build_health_signals itself assigned - the two modules serve different
# purposes and are allowed to disagree. Notably `render_missing` is only a
# "warning" on the board (it's just "run factory render") but is a hard
# blocker here: there's nothing to visually review yet without a render.
_BLOCKING_KINDS = frozenset(
    {
        "brief_missing",
        "brief_unreadable",
        "manifest_unreadable",
        "render_missing",
        "render_stale",
        "missing_visual_artifacts",
        "stale_preview_artifacts",
        "preview_package_unreadable",
    }
)

# Advisory - present but not blocking review.
_WARNING_KINDS = frozenset(
    {
        "manifest_missing",
        "manufacturing_option_not_selected",
        "validation_missing",
        "render_orphan",
        "preview_package_missing",
    }
)

# Positive/informational - kept from health_signals as-is (already "info"/"ready").
_READY_KINDS = frozenset({"validation_present", "slicer_review_ready"})


def _gate_item(kind: str, severity: str, message: str, suggested_action_kind: str | None) -> dict[str, Any]:
    return {"kind": kind, "severity": severity, "message": message, "suggested_action_kind": suggested_action_kind}


def evaluate_review_gate(project_dir: Path) -> dict[str, Any]:
    """Read one project's local artifacts and return a deterministic gate result.

    Read-only: never writes, renders, validates, exports, generates CAD,
    or contacts anything. See module docstring for the pass/warn/fail
    policy and docs/review-gate.md for the full field reference.
    """
    project_dir = Path(project_dir)
    summary = summarize_project(project_dir)

    blocking_items: list[dict[str, Any]] = []
    warning_items: list[dict[str, Any]] = []
    ready_items: list[dict[str, Any]] = []

    for item in summary["health_signals"]["items"]:
        kind = item["kind"]
        if kind in _BLOCKING_KINDS:
            blocking_items.append(_gate_item(kind, "blocked", item["message"], item["suggested_action_kind"]))
        elif kind in _WARNING_KINDS:
            warning_items.append(_gate_item(kind, "warning", item["message"], item["suggested_action_kind"]))
        elif kind in _READY_KINDS:
            ready_items.append(_gate_item(kind, item["severity"], item["message"], item["suggested_action_kind"]))
        # Any other/future kind is intentionally ignored here rather than
        # silently blocking or passing - this gate only acts on kinds it
        # explicitly knows how to classify.

    mesh_files = summary["mesh_files"]
    if not mesh_files:
        blocking_items.insert(
            0,
            _gate_item(
                "no_stl_files",
                "blocked",
                "No STL files exist yet - there is nothing to visually review in a slicer.",
                None,
            ),
        )
    else:
        ready_items.insert(0, _gate_item("stl_files_present", "info", f"{len(mesh_files)} STL file(s) present.", None))

    coverage = summary["render_coverage"]
    if mesh_files and not coverage["missing_renders"] and not coverage["stale_renders"]:
        ready_items.append(
            _gate_item(
                "all_renders_fresh",
                "info",
                "Every STL file has a matching, up-to-date render.",
                None,
            )
        )

    preview_package_unreadable = any(i["kind"] == "preview_package_unreadable" for i in blocking_items)
    if not preview_package_unreadable:
        ready_items.append(
            _gate_item(
                "preview_package_computed",
                "info",
                "preview_package/index.json data is available (persisted or computed live).",
                None,
            )
        )

    if blocking_items:
        result = "fail"
    elif warning_items:
        result = "warn"
    else:
        result = "pass"

    if result == "fail":
        summary_text = (
            f"{len(blocking_items)} blocking issue(s) found - this project is NOT ready for human "
            "slicer review yet."
        )
    elif result == "warn":
        summary_text = (
            f"No blocking issues, but {len(warning_items)} advisory item(s) should be addressed before "
            "human slicer review."
        )
    else:
        summary_text = (
            "This project appears ready for human slicer review. This is not an approval and not a "
            "print-readiness signal."
        )

    return {
        "project_dir": str(project_dir),
        "gate": GATE_NAME,
        "result": result,
        "status_ceiling": STATUS_CEILING,
        "summary": summary_text,
        "blocking_items": blocking_items,
        "warning_items": warning_items,
        "ready_items": ready_items,
        "suggested_actions": summary["suggested_actions"],
        "notes": list(REQUIRED_SAFETY_LINES),
    }

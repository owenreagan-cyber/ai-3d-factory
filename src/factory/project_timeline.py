"""Phase 40: Unified Project Timeline & Event Model.

The Factory's project memory - a read-only, chronological event log
derived entirely from systems that already exist:

    generation_receipt.json -> export_receipt.json ->
    slicer_readiness_receipt.json -> manual_review_workspace_receipt.json
    -> slicer_analysis_history.json -> brief.json's status_history
    -> Unified Project Timeline

**This module stores nothing new for derived events.** Every event is
computed fresh, on every call, by reading whatever receipts already
exist - it never writes a receipt of its own, never becomes a second
history format, and can never disagree with the systems it reads (if it
ever does, that's a bug in this module, never a correction to make in
the underlying receipt). The only thing that persists across calls is
`brief.json["status_history"]` (see `factory.project_store.advance_status()`),
which is itself an additive extension of a file this repo already owns,
not a new store.

Reuses rather than duplicates:

- `factory.generation_gate.read_last_execution_receipt()` (Phase 34)
- `factory.export_pipeline.read_export_receipt()` (Phase 35)
- `factory.slicer_readiness.read_slicer_readiness_receipt()` (Phase 36)
- `factory.manual_review_workspace.read_workspace_receipt()` (Phase 37)
- `factory.slicer_history.read_analysis_history()`/`detect_changes()`
  (Phase 39)
- `factory.project_inspection.HEALTH_SEVERITIES` (Phase 13) - the exact
  existing `info`/`warning`/`blocked`/`ready` vocabulary, reused verbatim
  as this module's own `severity` field rather than inventing a second
  one.

**"Unavailable" is never "empty."** `brief.json`'s early pipeline stages
(brief created, manufacturing plan drafted/approved/option-selected, CAD
generated) predate `status_history` for any project created before this
phase shipped. When a project has clearly reached a stage (per its
current `status`) but has no timestamped `status_history` entry for it,
this module emits an explicit event with `status: "unavailable"` - it
never silently omits the stage as if it hadn't happened, and never
invents a timestamp for it.

See `docs/project-timeline.md`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from factory import project_store
from factory.export_pipeline import read_export_receipt
from factory.generation_gate import read_last_execution_receipt
from factory.manual_review_workspace import read_workspace_receipt
from factory.project_inspection import HEALTH_SEVERITIES
from factory.slicer_history import detect_changes, read_analysis_history
from factory.slicer_readiness import read_slicer_readiness_receipt

EVENT_CATEGORIES = (
    "brief",
    "manufacturing_plan",
    "cad",
    "export",
    "validation",
    "preview",
    "approval",
    "package",
    "workspace",
    "slicer_analysis",
    "material_change",
    "printer_change",
    "risk_change",
    "warning_change",
)

EVENT_STATUSES = ("completed", "changed", "recorded", "unavailable")

# Reused verbatim from factory.project_inspection - never a second
# severity vocabulary.
EVENT_SEVERITIES = HEALTH_SEVERITIES

# Early-pipeline status_history stages this module derives events from,
# in project_store.PROJECT_STATUSES order. Later stages (mesh_exported,
# geometry_validated, dimension_validated, preview_rendered,
# slicer_review_ready) are deliberately excluded here - they're already
# covered by the richer, more precise export_receipt/slicer_readiness
# adapters below, and duplicating them from status_history alone would
# either conflict or add a redundant, less detailed second event for the
# same underlying fact.
_EARLY_STAGES = ("brief_created", "plan_drafted", "plan_approved", "manufacturing_option_selected", "cad_generated")

_EARLY_STAGE_CATEGORY = {
    "brief_created": "brief",
    "plan_drafted": "manufacturing_plan",
    "plan_approved": "manufacturing_plan",
    "manufacturing_option_selected": "manufacturing_plan",
    "cad_generated": "cad",
}

_EARLY_STAGE_LABEL = {
    "brief_created": "Brief created",
    "plan_drafted": "Manufacturing plan drafted",
    "plan_approved": "Manufacturing plan approved",
    "manufacturing_option_selected": "Manufacturing option selected",
    "cad_generated": "CAD generated",
}

_VALIDATION_STATUS_LABEL = {
    "passed": "Validation completed",
    "passed_with_warnings": "Validation completed with warnings",
    "failed": "Validation failed",
    "unavailable": "Validation unavailable",
}
_VALIDATION_STATUS_SEVERITY = {
    "passed": "ready",
    "passed_with_warnings": "warning",
    "failed": "warning",
    "unavailable": "info",
}

_RENDER_STATUS_LABEL = {
    "passed": "Preview rendered",
    "failed": "Preview render failed",
}
_RENDER_STATUS_SEVERITY = {"passed": "ready", "failed": "warning"}

_RISK_LEVEL_SEVERITY = {"Low": "ready", "Moderate": "warning", "High": "warning", "Unknown": "info"}

_CHANGE_CATEGORY_MAP = {
    "STL changed": ("export", "warning", "STL changed (detected since last saved analysis)"),
    "CAD changed": ("cad", "warning", "CAD changed (detected since last saved analysis)"),
    "Printer changed": ("printer_change", "info", "Target printer changed"),
    "Material changed": ("material_change", "warning", "Material changed"),
    "Validation changed": ("validation", "info", "Validation status changed"),
    "Slicer environment changed": ("slicer_analysis", "info", "Detected slicer environment changed"),
    "Warnings changed": ("warning_change", "warning", "Warnings changed"),
    # "Risk changed" is handled separately below (its label needs the
    # actual before/after values, not a fixed string).
}


def _event_id(source: str, timestamp: str | None, label: str) -> str:
    """A deterministic id for one event - the same underlying fact always
    produces the same id across repeated `factory timeline` calls, so a
    future diff/version-history consumer (Phase 41) can compare event
    identity across calls without re-deriving this hashing scheme."""
    key = f"{source}|{timestamp or 'unavailable'}|{label}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _date_from_timestamp(timestamp: str | None) -> str | None:
    if not timestamp:
        return None
    return timestamp.split("T", 1)[0]


def _make_event(
    *,
    timestamp: str | None,
    category: str,
    status: str,
    severity: str,
    label: str,
    source: str,
    detail: str | None = None,
    fingerprints: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "event_id": _event_id(source, timestamp, label),
        "timestamp": timestamp,
        "date": _date_from_timestamp(timestamp),
        "category": category,
        "status": status,
        "severity": severity,
        "label": label,
        "source": source,
        "detail": detail,
        # Phase 41 addendum: whatever artifact fingerprint data the
        # underlying receipt already recorded alongside this event -
        # never a new hash, never re-derived, always a direct passthrough
        # of a field that already existed in that receipt. Empty for
        # sources that never carried fingerprint data in the first place
        # (status_history, generation_receipt) - `factory.artifact_history`
        # (Phase 41) carries these forward across versions rather than
        # re-scanning receipts independently. See docs/artifact-history.md.
        "fingerprints": dict(fingerprints) if fingerprints else {},
    }


# ---------------------------------------------------------------------------
# Adapters - one per existing source, each read-only. None of these write
# anything or re-derive logic the source system already computed.
# ---------------------------------------------------------------------------


def _events_from_status_history(project_dir: Path) -> list[dict[str, Any]]:
    """Reads `brief.json`'s `status`/`status_history` only - never calls
    `advance_status()` or writes anything. `cad_generated` is skipped here
    whenever a `generation_receipt.json` exists (the richer source, see
    `_events_from_generation_receipt()`), to avoid a duplicate, less
    detailed event for the same fact.
    """
    project_dir = Path(project_dir)
    brief_path = project_dir / "brief.json"
    if not brief_path.is_file():
        return []
    try:
        brief = project_store.load_json(brief_path)
    except (OSError, ValueError):
        return []

    current_status = brief.get("status", "idea")
    current_index = project_store.status_index(current_status)
    history_by_status = {e.get("status"): e.get("at") for e in (brief.get("status_history") or [])}

    has_generation_receipt = read_last_execution_receipt(project_dir) is not None

    events: list[dict[str, Any]] = []
    for stage in _EARLY_STAGES:
        if stage == "cad_generated" and has_generation_receipt:
            continue
        if current_index < project_store.status_index(stage):
            continue  # this stage hasn't been reached yet - correctly absent, not "unavailable"

        category = _EARLY_STAGE_CATEGORY[stage]
        label = _EARLY_STAGE_LABEL[stage]
        timestamp = history_by_status.get(stage)
        if timestamp:
            events.append(
                _make_event(
                    timestamp=timestamp, category=category, status="completed", severity="ready",
                    label=label, source="status_history",
                )
            )
        else:
            events.append(
                _make_event(
                    timestamp=None, category=category, status="unavailable", severity="info",
                    label=f"{label} (date unavailable - project predates history tracking)",
                    source="status_history",
                    detail="This project reached this stage before status_history tracking began.",
                )
            )
    return events


def _events_from_generation_receipt(project_dir: Path) -> list[dict[str, Any]]:
    receipt = read_last_execution_receipt(project_dir)
    if not receipt:
        return []
    timestamp = receipt.get("timestamp")
    engine = receipt.get("engine") or "Unknown"
    return [
        _make_event(
            timestamp=timestamp, category="cad", status="completed", severity="ready",
            label=f"CAD generated ({engine})", source="generation_receipt",
        )
    ]


def _events_from_export_receipt(project_dir: Path) -> list[dict[str, Any]]:
    receipt = read_export_receipt(project_dir)
    events: list[dict[str, Any]] = []
    for record in (receipt or {}).get("exports", []):
        export = record.get("export") or {}
        timestamp = export.get("completed_at") or export.get("started_at")
        output_stl = record.get("output_stl") or record.get("source_file") or "STL"

        if export:
            severity = "ready" if export.get("success") else "warning"
            export_fingerprints = {}
            if record.get("source_file") and export.get("source_fingerprint"):
                export_fingerprints[record["source_file"]] = export["source_fingerprint"]
            if output_stl and export.get("output_fingerprint"):
                export_fingerprints[output_stl] = export["output_fingerprint"]
            events.append(
                _make_event(
                    timestamp=timestamp, category="export", status="completed", severity=severity,
                    label=f"STL exported: {output_stl}", source="export_receipt",
                    fingerprints=export_fingerprints,
                )
            )

        validation = record.get("validation") or {}
        validation_status = validation.get("status")
        if validation_status:
            events.append(
                _make_event(
                    timestamp=timestamp, category="validation", status="completed",
                    severity=_VALIDATION_STATUS_SEVERITY.get(validation_status, "info"),
                    label=_VALIDATION_STATUS_LABEL.get(validation_status, f"Validation: {validation_status}"),
                    source="export_receipt",
                )
            )

        render = record.get("render") or {}
        render_status = render.get("status")
        if render_status:
            events.append(
                _make_event(
                    timestamp=timestamp, category="preview", status="completed",
                    severity=_RENDER_STATUS_SEVERITY.get(render_status, "info"),
                    label=_RENDER_STATUS_LABEL.get(render_status, f"Preview: {render_status}"),
                    source="export_receipt",
                )
            )
    return events


def _events_from_slicer_readiness_receipt(project_dir: Path) -> list[dict[str, Any]]:
    receipt = read_slicer_readiness_receipt(project_dir)
    if not receipt:
        return []
    events: list[dict[str, Any]] = []

    approval = receipt.get("approval") or {}
    if approval.get("approved"):
        events.append(
            _make_event(
                timestamp=approval.get("approved_at"), category="approval", status="recorded", severity="ready",
                label="Human approval recorded", source="slicer_readiness_receipt", detail=approval.get("note"),
                fingerprints=receipt.get("artifact_fingerprints"),
            )
        )

    package = receipt.get("package") or {}
    if package.get("package_path"):
        events.append(
            _make_event(
                timestamp=package.get("created_at"), category="package", status="recorded", severity="ready",
                label="Review package created", source="slicer_readiness_receipt",
                fingerprints=package.get("artifact_fingerprints"),
            )
        )
    return events


def _events_from_workspace_receipt(project_dir: Path) -> list[dict[str, Any]]:
    receipt = read_workspace_receipt(project_dir)
    if not receipt:
        return []
    workspace = receipt.get("workspace") or {}
    if not workspace.get("workspace_path"):
        return []
    return [
        _make_event(
            timestamp=workspace.get("created_at"), category="workspace", status="recorded", severity="ready",
            label="Manual review workspace created", source="manual_review_workspace_receipt",
            fingerprints=workspace.get("artifact_fingerprints"),
        )
    ]


def _events_from_slicer_history(project_dir: Path) -> list[dict[str, Any]]:
    snapshots = read_analysis_history(project_dir)
    events: list[dict[str, Any]] = []
    for snapshot in snapshots:
        risk_level = snapshot.get("risk_level")
        events.append(
            _make_event(
                timestamp=snapshot.get("timestamp"), category="slicer_analysis", status="recorded",
                severity=_RISK_LEVEL_SEVERITY.get(risk_level, "info"),
                label=f"Slicer analysis saved (risk: {risk_level})", source="slicer_analysis_history",
                fingerprints=snapshot.get("artifact_fingerprints"),
            )
        )

    for previous, current in zip(snapshots, snapshots[1:]):
        changes = detect_changes(previous, current)
        timestamp = current.get("timestamp")
        for change in changes:
            if change == "Risk changed":
                events.append(
                    _make_event(
                        timestamp=timestamp, category="risk_change", status="changed", severity="warning",
                        label=f"Risk level changed ({previous.get('risk_level')} -> {current.get('risk_level')})",
                        source="slicer_analysis_history",
                    )
                )
                continue
            mapping = _CHANGE_CATEGORY_MAP.get(change)
            if mapping is None:
                continue
            category, severity, label = mapping
            events.append(
                _make_event(
                    timestamp=timestamp, category=category, status="changed", severity=severity,
                    label=label, source="slicer_analysis_history",
                )
            )
    return events


# ---------------------------------------------------------------------------
# Public aggregation
# ---------------------------------------------------------------------------


def get_project_timeline(project_dir: Path) -> list[dict[str, Any]]:
    """The full, read-only, chronological event list for one project.
    Never writes anything, never invokes a subprocess, never contacts a
    printer/slicer/network. Undated ("unavailable") events sort first, in
    early-pipeline stage order; dated events follow, sorted by timestamp.
    """
    project_dir = Path(project_dir)
    events: list[dict[str, Any]] = []
    events.extend(_events_from_status_history(project_dir))
    events.extend(_events_from_generation_receipt(project_dir))
    events.extend(_events_from_export_receipt(project_dir))
    events.extend(_events_from_slicer_readiness_receipt(project_dir))
    events.extend(_events_from_workspace_receipt(project_dir))
    events.extend(_events_from_slicer_history(project_dir))

    undated = [e for e in events if e["timestamp"] is None]
    dated = sorted((e for e in events if e["timestamp"] is not None), key=lambda e: e["timestamp"])
    return undated + dated


def get_project_timeline_for_path(path: Path) -> list[dict[str, Any]]:
    """Convenience entry point `factory timeline <path>` uses."""
    return get_project_timeline(path)


def summarize_project_timeline(project_dir: Path) -> dict[str, Any]:
    """Compact, read-only summary for the Preview Board's "Project
    Timeline" card. Never writes, never invokes a subprocess.

    **Architectural note - same reasoning as every Phase 36-39 summary
    field:** this module reads receipts written by
    `factory.slicer_readiness`/`factory.manual_review_workspace`, which
    transitively import `factory.review_gate`, which already imports
    `factory.project_inspection.summarize_project()`. Adding a
    `timeline_summary` field computed via this module *inside*
    `project_inspection.py` would recreate the same circular import Phase
    36 discovered - see the standing "Aggregation Layer Convention" in
    `docs/architecture.md`. `factory.preview_board.gather_board_data()`
    calls this function directly per project instead.
    """
    events = get_project_timeline(project_dir)
    dated = [e for e in events if e["timestamp"] is not None]
    undated = [e for e in events if e["timestamp"] is None]
    latest = dated[-1] if dated else None
    return {
        "event_count": len(events),
        "dated_event_count": len(dated),
        "unavailable_event_count": len(undated),
        "latest_event": (
            {"label": latest["label"], "date": latest["date"], "category": latest["category"]} if latest else None
        ),
    }

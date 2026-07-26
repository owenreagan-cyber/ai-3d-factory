"""Phase 39 Part 3/4: Slicer Analysis History and Change Comparison.

A lightweight, local, append-only history of explicitly-saved Slicer
Review Intelligence snapshots, answering one question:

    "What changed since the last review?"

**History is observational. It does not control workflow. It does not
approve anything.** It never affects `factory.slicer_readiness`'s
readiness_status, never affects approval, never triggers slicing, and
never triggers printing.

**Persistence is explicit only.** `save_analysis_snapshot()` is the only
function that writes anything, and it is only ever called by
`factory slicer-inspect --save-analysis` - never automatically during
`factory preview-board`, `factory slicer-inspect` (without the flag), or
any readiness/approval check. Reading history
(`read_analysis_history()`/`compare_slicer_analysis()`/
`summarize_slicer_history()`) is always safe and side-effect-free.

Reuses rather than duplicates:

- `factory.slicer_intelligence.evaluate_slicer_intelligence()` (Phase 38)
  for the live analysis a snapshot captures.
- `factory.slicer_readiness.summarize_slicer_readiness()` (Phase 36) for
  the readiness summary embedded in each snapshot.
- `factory.slicer_readiness.file_fingerprint()`/`relative_path()` (public
  aliases added in Phase 37) for the same `sha256:<hex digest>` artifact
  fingerprint convention every prior phase's receipt already uses - never
  a new hashing scheme.
- `factory.export_pipeline.read_export_receipt()` for the current set of
  source/output files to fingerprint.

See `docs/slicer-analysis-history.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import project_store
from factory.export_pipeline import GENERATED_DIRNAME, read_export_receipt
from factory.slicer_intelligence import evaluate_slicer_intelligence
from factory.slicer_readiness import file_fingerprint, relative_path, summarize_slicer_readiness

HISTORY_FILENAME = "slicer_analysis_history.json"

ANALYSIS_TYPE = "slicer_intelligence"

CHANGE_CATEGORIES = (
    "STL changed",
    "CAD changed",
    "Printer changed",
    "Material changed",
    "Validation changed",
    "Risk changed",
    "Slicer environment changed",
    "Warnings changed",
)


def _snapshot_fingerprints(project_dir: Path, export_receipt: dict[str, Any] | None) -> dict[str, str]:
    """Fingerprint every current source CAD file and STL the export
    receipt knows about, plus `part_manifest.json`/`build_plan.json` -
    reuses `factory.slicer_readiness.file_fingerprint()`/`relative_path()`
    directly rather than re-deriving the hashing scheme."""
    project_dir = Path(project_dir)
    fingerprints: dict[str, str] = {}
    for record in (export_receipt or {}).get("exports", []):
        for rel in (record.get("source_file"), record.get("output_stl")):
            if rel:
                path = project_dir / rel
                if path.is_file():
                    fingerprints[rel] = file_fingerprint(path)

    manifest_path = project_dir / "part_manifest.json"
    if manifest_path.is_file():
        fingerprints["part_manifest.json"] = file_fingerprint(manifest_path)
    build_plan_path = project_dir / "build_plan.json"
    if build_plan_path.is_file():
        fingerprints["build_plan.json"] = file_fingerprint(build_plan_path)

    return fingerprints


def _build_snapshot(project_dir: Path, analysis: dict[str, Any] | None) -> dict[str, Any]:
    project_dir = Path(project_dir)
    analysis = analysis if analysis is not None else evaluate_slicer_intelligence(project_dir)
    export_receipt = read_export_receipt(project_dir)

    materials = [entry["material"] for entry in analysis["material"]]
    detected_slicer_names = sorted(s["name"] for s in analysis["detected_slicers"] if s["found"])

    return {
        "timestamp": project_store.utc_now_iso(),
        "project": analysis["project"],
        "analysis_type": ANALYSIS_TYPE,
        "artifact_fingerprints": _snapshot_fingerprints(project_dir, export_receipt),
        "readiness_summary": summarize_slicer_readiness(project_dir),
        "slicer_intelligence_summary": {
            "risk_level": analysis["risk_level"],
            "build_volume_fit": analysis["build_volume_analysis"]["fit_status"],
            "confidence": analysis["confidence"],
        },
        "printer_id": analysis["printer"].get("printer_id"),
        "printer_display_name": analysis["printer"].get("display_name"),
        "materials": materials,
        "detected_slicer_names": detected_slicer_names,
        "slicer_profile_name": analysis["slicer_profile"]["slicer_name"],
        "risk_level": analysis["risk_level"],
        "confidence": analysis["confidence"],
        "warnings": list(analysis["warnings"]),
    }


# ---------------------------------------------------------------------------
# Read/write - the only write path in this module (and this phase).
# ---------------------------------------------------------------------------


def _history_path(project_dir: Path) -> Path:
    return Path(project_dir) / GENERATED_DIRNAME / HISTORY_FILENAME


def read_analysis_history(project_dir: Path) -> list[dict[str, Any]]:
    """Read-only: every previously-saved snapshot, oldest first. Returns
    `[]` if no history file exists yet, or if it exists but is malformed -
    never raises, never triggers a write."""
    history_path = _history_path(project_dir)
    if not history_path.is_file():
        return []
    try:
        data = project_store.load_json(history_path)
    except (OSError, ValueError):
        return []
    snapshots = data.get("snapshots") if isinstance(data, dict) else None
    return snapshots if isinstance(snapshots, list) else []


def save_analysis_snapshot(project_dir: Path, *, analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    """Explicitly append one snapshot of the current Slicer Review
    Intelligence analysis to `generated/slicer_analysis_history.json`.
    Never called automatically - only `factory slicer-inspect
    --save-analysis` (or an equivalent explicit caller) should invoke
    this. Pass `analysis` to reuse an already-computed result rather than
    evaluating twice; if omitted, a fresh `evaluate_slicer_intelligence()`
    call is made.
    """
    project_dir = Path(project_dir)
    snapshot = _build_snapshot(project_dir, analysis)

    history_path = _history_path(project_dir)
    existing = read_analysis_history(project_dir)
    existing.append(snapshot)

    project_store.save_json(history_path, {"project": snapshot["project"], "snapshots": existing})
    return {"snapshot": snapshot, "history_path": str(history_path), "snapshot_count": len(existing)}


# ---------------------------------------------------------------------------
# Change comparison - "what's different now vs. the last saved snapshot."
# ---------------------------------------------------------------------------


def _detect_changes(previous: dict[str, Any], current_snapshot: dict[str, Any]) -> list[str]:
    changes: list[str] = []
    prev_fp = previous.get("artifact_fingerprints", {})
    curr_fp = current_snapshot.get("artifact_fingerprints", {})

    stl_changed = any(
        (path.endswith(".stl") or "stl/" in path) and (prev_fp.get(path) != curr_fp.get(path))
        for path in set(prev_fp) | set(curr_fp)
    )
    cad_changed = any(
        (path.endswith(".scad") or path.endswith(".py") or "cad/" in path) and (prev_fp.get(path) != curr_fp.get(path))
        for path in set(prev_fp) | set(curr_fp)
    )
    if stl_changed:
        changes.append("STL changed")
    if cad_changed:
        changes.append("CAD changed")

    if previous.get("printer_id") != current_snapshot.get("printer_id"):
        changes.append("Printer changed")
    if previous.get("materials") != current_snapshot.get("materials"):
        changes.append("Material changed")
    if previous.get("readiness_summary", {}).get("validation_status") != current_snapshot.get("readiness_summary", {}).get(
        "validation_status"
    ):
        changes.append("Validation changed")
    if previous.get("risk_level") != current_snapshot.get("risk_level"):
        changes.append("Risk changed")
    if set(previous.get("detected_slicer_names", [])) != set(current_snapshot.get("detected_slicer_names", [])):
        changes.append("Slicer environment changed")
    if set(previous.get("warnings", [])) != set(current_snapshot.get("warnings", [])):
        changes.append("Warnings changed")

    return changes


# Public alias (Phase 40): factory.project_timeline sits directly above
# this module (the same "top-level consumer" relationship
# manual_review_workspace.py/slicer_intelligence.py already have with
# slicer_readiness.py) and reuses this exact change-detection logic
# between consecutive saved snapshots rather than re-deriving it - see
# that module's own docstring. Kept as a plain alias (not a rename) so
# every existing internal call site and test in this module is untouched.
detect_changes = _detect_changes


def compare_slicer_analysis(project_dir: Path, *, current: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compare a fresh, live Slicer Review Intelligence analysis against
    the most recently *saved* snapshot (never two historical snapshots
    against each other - this answers "what's different right now", not
    "what changed between two past saves"). Read-only: never writes,
    never triggers a save.
    """
    project_dir = Path(project_dir)
    history = read_analysis_history(project_dir)
    previous = history[-1] if history else None

    current_analysis = current if current is not None else evaluate_slicer_intelligence(project_dir)
    current_snapshot = _build_snapshot(project_dir, current_analysis)

    if previous is None:
        return {
            "history_available": False,
            "previous": None,
            "current": current_snapshot,
            "changes": [],
            "recommendation": "No previous analysis snapshot found - run `factory slicer-inspect --save-analysis` to start tracking history.",
        }

    changes = _detect_changes(previous, current_snapshot)
    recommendation = (
        "Human review recommended - re-check the change(s) above before proceeding."
        if changes
        else "No changes detected since the last saved analysis."
    )
    return {
        "history_available": True,
        "previous": previous,
        "current": current_snapshot,
        "changes": changes,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# Compact summary for project_inspection/Preview Board - compares only the
# two most recent *saved* snapshots (never a live analysis), so reading it
# is always cheap and never recomputes anything.
# ---------------------------------------------------------------------------


def _compact_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": snapshot.get("timestamp"),
        "risk_level": snapshot.get("risk_level"),
        "confidence": snapshot.get("confidence"),
    }


def summarize_slicer_history(project_dir: Path) -> dict[str, Any]:
    """Compact, read-only summary for `factory.project_inspection`/the
    Preview Board - compares only the two most recent *saved* snapshots
    (never triggers a live analysis or a write). `changes_detected` and
    `risk_change` are `None` whenever fewer than two snapshots exist yet.
    """
    history = read_analysis_history(project_dir)
    if not history:
        return {
            "history_available": False,
            "latest_analysis": None,
            "previous_analysis": None,
            "changes_detected": None,
            "risk_change": None,
        }

    latest = history[-1]
    if len(history) < 2:
        return {
            "history_available": True,
            "latest_analysis": _compact_snapshot(latest),
            "previous_analysis": None,
            "changes_detected": None,
            "risk_change": None,
        }

    previous = history[-2]
    changes = _detect_changes(previous, latest)
    risk_change = None
    if previous.get("risk_level") != latest.get("risk_level"):
        risk_change = f"{previous.get('risk_level')} -> {latest.get('risk_level')}"

    return {
        "history_available": True,
        "latest_analysis": _compact_snapshot(latest),
        "previous_analysis": _compact_snapshot(previous),
        "changes_detected": len(changes),
        "risk_change": risk_change,
    }

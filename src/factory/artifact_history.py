"""Phase 41: Artifact History & Diff Planning.

A safe, read-only artifact version history and comparison system built
directly on Phase 40's unified timeline - never a second event parser,
never a second fingerprinting system, never a mutable counter file.

    Receipts -> Phase 40 project_timeline.py -> Phase 41 artifact_history.py
    -> Diff Reports -> Rollback Plans (report only, never executed)

**This phase is about understanding change - not restoring files.** It
answers "what changed, when, and what would a rollback affect" without
ever modifying anything. There is no write path anywhere in this module.

**Artifact History is a VIEW over existing evidence. It never becomes
authoritative.** The hierarchy is:

    Source Artifact -> Receipt/Manifest/Snapshot -> Timeline ->
    Artifact History View -> Diff Reports

If this module's rendering of a version or diff ever disagrees with the
receipt/timeline event it came from, the receipt/timeline is correct -
this module has a bug, never grounds to "correct" the underlying record.

Reuses rather than duplicates:

- `factory.project_timeline.get_project_timeline()` (Phase 40) - the
  single source of event ordering, identity, and (additively, Phase 41)
  per-event artifact fingerprints. This module never re-scans a receipt
  independently; every fingerprint it uses was already attached to a
  timeline event by Phase 40's own adapters, each of which already reused
  the underlying receipt's own already-recorded fingerprint field.
- `factory.slicer_history.detect_changes()` (Phase 39) indirectly - the
  `material_change`/`printer_change`/`risk_change`/`warning_change`
  timeline events Phase 40 already derived from it are reused directly
  here (by timestamp range), never re-invoked a second time.
- The exact `sha256:<hex digest>` fingerprint convention established in
  Phase 35/37 - no new hash function, no new path normalization, no new
  artifact identity rule.

**Version numbers are derived, never stored.** A version is simply the
1-based ordinal of an artifact-relevant timeline event, in chronological
order - there is no `artifact_versions.json` counter file and no hidden
mutable state. Re-running `factory.project_timeline.get_project_timeline()`
and this module's own derivation always reproduces the exact same version
numbering for the exact same underlying receipts.

See `docs/artifact-history.md`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory.project_timeline import get_project_timeline

# Timeline event categories that represent a genuine artifact-state
# milestone worth its own version number. Categories like "brief"/
# "manufacturing_plan" (Phase 40) and "slicer_analysis"/"material_change"/
# "printer_change"/"risk_change"/"warning_change" are deliberately
# excluded - they're either pipeline milestones with no artifact
# fingerprint of their own, or already-detected *changes* (reused
# directly in diffs below, not re-versioned).
VERSION_EVENT_CATEGORIES = ("cad", "export", "validation", "preview", "approval", "package", "workspace")

ARTIFACT_CATEGORIES = ("cad", "stl", "validation", "preview", "manifest", "build_plan", "review_package")

_ARTIFACT_CATEGORY_LABELS = {
    "cad": "CAD source",
    "stl": "STL file",
    "validation": "Validation report",
    "preview": "Preview render",
    "manifest": "Part manifest",
    "build_plan": "Build plan",
    "review_package": "Review package/workspace",
}

# Timeline event categories that are themselves already-detected changes
# (Phase 39/40) - reused directly by diff_artifact_versions() rather than
# re-deriving change detection a second time.
_CHANGE_EVENT_LABELS = {
    "material_change": "Material changed",
    "printer_change": "Printer changed",
    "risk_change": "Risk changed",
    "warning_change": "Warnings changed",
}

# Project-level records this module never tracks fingerprints for at all
# - always reported as unaffected by any rollback plan, since artifact
# history's scope is strictly the CAD/STL/validation/preview/review
# pipeline, never the upstream idea/brief/design-intent record.
_NEVER_TRACKED_LABELS = ("Brief", "Design Intent", "Reference Board")


def _artifact_category_for_path(rel_path: str) -> str:
    """Classify a relative path into an artifact category using the exact
    directory/filename conventions this repo already established
    (`docs/file-lifecycle.md`) - never a new classification scheme."""
    if rel_path.startswith("cad/"):
        return "cad"
    if rel_path.startswith("stl/"):
        return "stl"
    if rel_path.startswith("validation/"):
        return "validation"
    if rel_path.startswith("renders/"):
        return "preview"
    if rel_path == "part_manifest.json":
        return "manifest"
    if rel_path == "build_plan.json":
        return "build_plan"
    if rel_path.startswith("slicer_review/") or rel_path.startswith("manual_review/"):
        return "review_package"
    return "other"


def _latest_state_label(version_events: list[dict[str, Any]], category: str, up_to_index: int) -> str:
    """The most recent event's own label for `category`, at or before
    `up_to_index` in `version_events` - reused verbatim from the timeline,
    never re-derived. `"Not yet reached"` if the category never occurred
    up to this point."""
    latest = None
    for event in version_events[: up_to_index + 1]:
        if event["category"] == category:
            latest = event["label"]
    return latest or "Not yet reached"


# ---------------------------------------------------------------------------
# Public entry point: artifact version history
# ---------------------------------------------------------------------------


def get_artifact_history(project_dir: Path) -> list[dict[str, Any]]:
    """The full, read-only, derived artifact version history for one
    project. Never writes anything, never invokes a subprocess, never
    contacts a printer/slicer/network. Version numbers are the 1-based
    ordinal of each artifact-relevant timeline event, in chronological
    order - always reproducible from the same underlying receipts, never
    stored anywhere.
    """
    project_dir = Path(project_dir)
    events = get_project_timeline(project_dir)
    version_events = [e for e in events if e["category"] in VERSION_EVENT_CATEGORIES]

    snapshots: list[dict[str, Any]] = []
    cumulative_fingerprints: dict[str, str] = {}

    for index, event in enumerate(version_events):
        cumulative_fingerprints.update(event["fingerprints"])

        artifacts: dict[str, list[str]] = {category: [] for category in ARTIFACT_CATEGORIES}
        for rel_path in cumulative_fingerprints:
            category = _artifact_category_for_path(rel_path)
            if category in artifacts:
                artifacts[category].append(rel_path)
        for category in artifacts:
            artifacts[category].sort()

        snapshots.append(
            {
                "version_id": index + 1,
                "timestamp": event["timestamp"],
                "date": event["date"],
                "source_event_id": event["event_id"],
                "source_event_category": event["category"],
                "source_event_label": event["label"],
                "artifacts": {k: v for k, v in artifacts.items() if v},
                "fingerprints": dict(cumulative_fingerprints),
                "artifact_count": len(cumulative_fingerprints),
                "validation_state": _latest_state_label(version_events, "validation", index),
                "preview_state": _latest_state_label(version_events, "preview", index),
                "review_state": _latest_state_label(version_events, "approval", index)
                if any(e["category"] in ("approval", "package", "workspace") for e in version_events[: index + 1])
                else "Pending",
            }
        )

    return snapshots


def get_artifact_history_for_path(path: Path) -> list[dict[str, Any]]:
    """Convenience entry point `factory artifact-history <path>` uses."""
    return get_artifact_history(path)


def get_artifact_snapshot(project_dir: Path, version_id: int) -> dict[str, Any] | None:
    """One specific version, or `None` if `version_id` doesn't exist for
    this project. Read-only."""
    for snapshot in get_artifact_history(project_dir):
        if snapshot["version_id"] == version_id:
            return snapshot
    return None


# ---------------------------------------------------------------------------
# Diff planning - version -> version comparison
# ---------------------------------------------------------------------------


class UnknownVersionError(Exception):
    """Raised when a requested version_id doesn't exist for this project."""

    def __init__(self, version_id: int, known_versions: list[int]):
        self.version_id = version_id
        self.known_versions = known_versions
        super().__init__(f"Unknown version {version_id} - known versions: {known_versions or '(none yet)'}")


def diff_artifact_versions(project_dir: Path, from_version: int, to_version: int) -> dict[str, Any]:
    """Compare two artifact versions - read-only, never writes, never
    recomputes fingerprints (reuses each version's own already-derived
    fingerprint dict from `get_artifact_history()`). Raises
    `UnknownVersionError` for a version_id that doesn't exist rather than
    silently comparing against `None`.
    """
    project_dir = Path(project_dir)
    snapshots = get_artifact_history(project_dir)
    by_version = {s["version_id"]: s for s in snapshots}
    known_versions = sorted(by_version)

    if from_version not in by_version:
        raise UnknownVersionError(from_version, known_versions)
    if to_version not in by_version:
        raise UnknownVersionError(to_version, known_versions)

    from_snap = by_version[from_version]
    to_snap = by_version[to_version]

    changed: list[str] = []
    unchanged: list[str] = []

    all_paths = set(from_snap["fingerprints"]) | set(to_snap["fingerprints"])
    changed_categories: set[str] = set()
    seen_categories: set[str] = set()
    for rel_path in all_paths:
        category = _artifact_category_for_path(rel_path)
        seen_categories.add(category)
        if from_snap["fingerprints"].get(rel_path) != to_snap["fingerprints"].get(rel_path):
            changed_categories.add(category)

    for category in ARTIFACT_CATEGORIES:
        if category not in seen_categories:
            continue
        label = _ARTIFACT_CATEGORY_LABELS[category]
        (changed if category in changed_categories else unchanged).append(label)

    # Reuse Phase 39/40's own already-detected changes (material/printer/
    # risk/warnings) by timestamp range - never re-derived independently.
    lo_ts, hi_ts = sorted((from_snap["timestamp"] or "", to_snap["timestamp"] or ""))
    all_events = get_project_timeline(project_dir)
    for event in all_events:
        if event["category"] not in _CHANGE_EVENT_LABELS or not event["timestamp"]:
            continue
        if lo_ts <= event["timestamp"] <= hi_ts:
            label = _CHANGE_EVENT_LABELS[event["category"]]
            if label not in changed:
                changed.append(label)

    if _approval_invalidated_between(all_events, from_snap, to_snap):
        if "Approval invalidated" not in changed:
            changed.append("Approval invalidated")

    unchanged.extend(label for label in _NEVER_TRACKED_LABELS if label not in unchanged)

    impact = "Requires slicer review." if changed else "No re-review needed - artifacts are identical."

    return {
        "from_version": from_version,
        "to_version": to_version,
        "changed": changed,
        "unchanged": unchanged,
        "impact": impact,
        "dry_run": True,
        "no_automatic_print": True,
    }


def _approval_invalidated_between(all_events: list[dict[str, Any]], from_snap: dict, to_snap: dict) -> bool:
    """An approval recorded at or before `from_snap` is considered
    invalidated by `to_snap` if no *newer* approval event exists in that
    range and at least one tracked artifact's fingerprint differs between
    the two versions - mirroring `factory.slicer_readiness`'s own
    invalidation rule (a fingerprint mismatch invalidates approval),
    applied here to two historical versions rather than live files.
    """
    lo_ts, hi_ts = sorted((from_snap["timestamp"] or "", to_snap["timestamp"] or ""))
    had_prior_approval = any(
        e["category"] == "approval" and e["timestamp"] and e["timestamp"] <= (from_snap["timestamp"] or "")
        for e in all_events
    )
    if not had_prior_approval:
        return False
    newer_approval_exists = any(
        e["category"] == "approval" and e["timestamp"] and lo_ts < e["timestamp"] <= hi_ts for e in all_events
    )
    if newer_approval_exists:
        return False
    all_paths = set(from_snap["fingerprints"]) | set(to_snap["fingerprints"])
    return any(from_snap["fingerprints"].get(p) != to_snap["fingerprints"].get(p) for p in all_paths)


# ---------------------------------------------------------------------------
# Rollback planning - report only, never executed
# ---------------------------------------------------------------------------


def build_rollback_plan(project_dir: Path, to_version: int) -> dict[str, Any]:
    """A **report only** - never restores, copies, or deletes a file, and
    never modifies a manifest. Reuses `diff_artifact_versions()` directly
    (the "what would change" question is identical whether framed as a
    forward diff or a rollback plan) rather than a second comparison
    implementation.
    """
    project_dir = Path(project_dir)
    snapshots = get_artifact_history(project_dir)
    if not snapshots:
        raise UnknownVersionError(to_version, [])

    current_version = snapshots[-1]["version_id"]
    diff = diff_artifact_versions(project_dir, to_version, current_version)

    return {
        "current_version": current_version,
        "target_version": to_version,
        "would_affect": diff["changed"],
        "would_not_affect": diff["unchanged"],
        "action": "Manual review required. No files changed.",
        "dry_run": True,
        "no_files_restored": True,
        "no_files_copied": True,
        "no_files_deleted": True,
        "no_manifest_modified": True,
        "no_automatic_print": True,
    }


# ---------------------------------------------------------------------------
# Compact summary for Preview Board / project inspection
# ---------------------------------------------------------------------------


def summarize_artifact_history(project_dir: Path) -> dict[str, Any]:
    """Compact, read-only summary for the Preview Board's "Artifact
    History" card. Never writes, never invokes a subprocess.

    **Architectural note - same reasoning as every Phase 36-40 summary
    field:** this module calls `factory.project_timeline.get_project_timeline()`,
    which reads receipts written by `factory.slicer_readiness`/
    `factory.manual_review_workspace`, which transitively import
    `factory.review_gate`, which already imports
    `factory.project_inspection.summarize_project()`. Adding an
    `artifact_history_summary` field computed via this module *inside*
    `project_inspection.py` would recreate the same circular import Phase
    36 discovered - see the standing "Aggregation Layer Convention" in
    `docs/architecture.md`. `factory.preview_board.gather_board_data()`
    calls this function directly per project instead.
    """
    snapshots = get_artifact_history(project_dir)
    if not snapshots:
        return {
            "history_available": False,
            "version_count": 0,
            "latest_version": None,
            "changed_since_previous": None,
            "current_artifact_state": None,
        }

    latest = snapshots[-1]
    changed_since_previous: list[str] | None = None
    if len(snapshots) > 1:
        diff = diff_artifact_versions(project_dir, snapshots[-2]["version_id"], latest["version_id"])
        changed_since_previous = diff["changed"]

    return {
        "history_available": True,
        "version_count": len(snapshots),
        "latest_version": latest["version_id"],
        "changed_since_previous": changed_since_previous,
        "current_artifact_state": {
            "validation": latest["validation_state"],
            "preview": latest["preview_state"],
            "review": latest["review_state"],
        },
    }

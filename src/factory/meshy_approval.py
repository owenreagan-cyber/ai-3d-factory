"""Phase 46: Meshy Cloud / Cost / License / Privacy Approval Gate.

**This module is policy and approval infrastructure only. It never calls
Meshy, never imports a Meshy SDK, never contacts any network endpoint,
never reads or validates a Meshy credential, and never uploads anything
anywhere.** Phase 16 (`docs/meshy-approval-gate.md`) wrote down, in
advance, the checklist a future Meshy implementation must satisfy. Phase
43 (`factory.engine_registry`) recorded Meshy as a permanent, cloud-gated
registry entry. Phase 44 (`factory.tool_qualification`) explicitly never
qualifies it. This phase turns that scaffold into one concrete,
machine-readable, auditable policy/approval model - still without adding
a single line of code that could ever contact Meshy.

    Meshy availability != Meshy approval != API execution approval

A project can be `approved_for_future_api_integration` here and Meshy
execution can *still* be completely impossible, because:

- `config/future_cloud_tools.json`'s `tools.meshy.enabled` stays `false`
  forever in this phase (the actual kill switch Phase 43/44 already read;
  this module never writes to that file),
- this module's own `approval.execution_enabled` field is hardcoded
  `False` in every code path here - there is no flag, no CLI option, and
  no combination of `--ack-*` acknowledgements in this phase that can set
  it `True`. Flipping it is explicitly out of scope for Phase 46; see
  `docs/meshy-policy.md`'s "What Phase 46 does not do".

`evaluate_meshy_phase47_readiness()`'s `ready_for_phase47 = True` means
only "the policy scaffold Phase 47 needs to build the actual adapter
against now exists" - never "safe to call Meshy now." Every future Meshy
result, regardless of how complete this policy becomes, must still pass:

    provenance -> artifact receipt -> cleanup/manufacturing adaptation ->
    Factory validation -> preview -> human review -> slicer review ->
    human print decision

Automatic printing remains impossible - see `no_automatic_print` on every
model this module returns.

**Architectural note - same reasoning as every Phase 36-45 aggregation
field:** this module reads `factory.future_cloud_tools` (the existing
kill-switch/gate config, Phase 16) and `factory.engine_registry` (the
canonical Meshy registry record, Phase 43) directly; neither of those
modules imports this one back, so there is no circular-import risk.
`factory.preview_board` calls `summarize_meshy_policy_for_board()`
directly, the same "top-level consumer" pattern every prior phase's
summary field uses.
"""

from __future__ import annotations

from typing import Any

from factory import project_store
from factory.future_cloud_tools import get_future_cloud_tool
from factory.reference_board import LICENSES

MESHY_POLICY_PATH = project_store.CONFIG_DIR / "meshy_policy.json"

POLICY_VERSION = 1

# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------

# "disabled" and "blocked" are reserved for a future explicit admin action
# (e.g. explicitly disabling a previously-approved policy without a full
# revocation) and a genuine structural failure (a corrupted/missing policy
# file), respectively - neither is reachable from this phase's own default
# state, but both remain part of the closed vocabulary `gate_status` draws
# from, per this phase's spec. See docs/meshy-policy.md "Gate states".
GATE_STATES = (
    "disabled",
    "policy_incomplete",
    "needs_cost_policy",
    "needs_license_policy",
    "needs_privacy_policy",
    "needs_provenance_policy",
    "needs_human_approval",
    "approved_for_future_api_integration",
    "revoked",
    "blocked",
)

# The scope of a recorded human approval. Phase 46 itself only ever
# records (or lets a human record) "policy_only" - the wider scopes exist
# in the vocabulary for a future phase's use, never assumed or defaulted
# to by this one.
APPROVAL_SCOPES = (
    "policy_only",
    "concept_generation",
    "image_upload",
    "mesh_upload",
    "commercial_use",
)

INPUT_CLASSES = ("text_prompt", "single_image", "multi_image", "existing_mesh")

# Per-input-class review posture - policy metadata only, never consulted
# by any upload code path because no upload code path exists yet.
INPUT_CLASS_POLICY: dict[str, dict[str, Any]] = {
    "text_prompt": {
        "privacy_risk": "lowest",
        "requires_license_review": False,
        "requires_provenance": True,
        "note": "Still recorded in request provenance (sanitized/hashed), even though privacy risk is lowest.",
    },
    "single_image": {
        "privacy_risk": "moderate",
        "requires_license_review": True,
        "requires_provenance": True,
        "note": "License/privacy review required before upload - see reference-board integration.",
    },
    "multi_image": {
        "privacy_risk": "moderate_per_image",
        "requires_license_review": True,
        "requires_provenance": True,
        "note": "Every image in a multi-image request requires its own license/privacy review - none inherit approval from another.",
    },
    "existing_mesh": {
        "privacy_risk": "low",
        "requires_license_review": True,
        "requires_provenance": True,
        "note": "Ownership/license review required - an uploaded mesh may itself carry third-party rights.",
    },
}

# Data classes a future Meshy request's inputs might fall into. Privacy
# policy only - this module never scans a file or classifies real content;
# a human (or a future phase's own review step) assigns the class.
DATA_CLASSES = (
    "public_reference",
    "user_created_reference",
    "licensed_reference",
    "private_photo",
    "student_data",
    "student_photo",
    "personal_identifier",
    "confidential_project",
    "commercial_secret",
    "third_party_copyrighted_reference",
    "unknown_source",
)

# Conservative default: allowed for cloud upload only when the class is
# affirmatively one a human would recognize as already fine to leave the
# machine. Everything else - explicitly including every classroom/student/
# private/unknown class this repo's examples/ directory could plausibly
# involve (see examples/multipart-classroom-sign/,
# examples/future-organic-models/) - is forbidden by default.
ALLOWED_DATA_CLASSES_BY_DEFAULT = (
    "public_reference",
    "user_created_reference",
    "licensed_reference",
)

FORBIDDEN_DATA_CLASSES_BY_DEFAULT = (
    "private_photo",
    "student_data",
    "student_photo",
    "personal_identifier",
    "confidential_project",
    "commercial_secret",
    "third_party_copyrighted_reference",
    "unknown_source",
)

assert set(ALLOWED_DATA_CLASSES_BY_DEFAULT) | set(FORBIDDEN_DATA_CLASSES_BY_DEFAULT) == set(DATA_CLASSES)
assert not (set(ALLOWED_DATA_CLASSES_BY_DEFAULT) & set(FORBIDDEN_DATA_CLASSES_BY_DEFAULT))

# `factory.reference_board.LICENSES` values considered - on their own,
# without any further review - safe enough to permit sending the
# referenced asset to a third-party cloud API. Every other license value,
# explicitly including "unknown" and "personal_use" (personal-use rights
# are not the same right as "may hand this to a third-party API"), stays
# blocked by default. Never mutates reference_board.json; this is a pure
# policy mapping consulted by a future phase, not an automatic classifier.
CLOUD_UPLOAD_ALLOWED_LICENSES = ("public_domain", "cc_by", "cc_by_sa", "commercial_allowed")
CLOUD_UPLOAD_NON_COMMERCIAL_ONLY_LICENSES = ("cc_by_nc",)
CLOUD_UPLOAD_BLOCKED_LICENSES = tuple(
    value for value in LICENSES if value not in CLOUD_UPLOAD_ALLOWED_LICENSES and value not in CLOUD_UPLOAD_NON_COMMERCIAL_ONLY_LICENSES
)
assert set(CLOUD_UPLOAD_ALLOWED_LICENSES) | set(CLOUD_UPLOAD_NON_COMMERCIAL_ONLY_LICENSES) | set(CLOUD_UPLOAD_BLOCKED_LICENSES) == set(LICENSES)

REQUIRED_REQUEST_PROVENANCE_FIELDS = (
    "tool",
    "tool_model_version",
    "factory_phase_version",
    "timestamp",
    "request_type",
    "prompt_hash_or_sanitized_record",
    "reference_ids",
    "reference_source_license_metadata",
    "input_fingerprints",
    "human_approver",
    "cost_estimate",
    "configured_cost_cap",
    "execution_confirmation",
)

REQUIRED_OUTPUT_PROVENANCE_FIELDS = (
    "meshy_task_id",
    "output_artifact_paths",
    "output_fingerprints",
    "formats",
    "model_version_if_available",
    "credits_or_cost_if_available",
    "license_posture",
    "warnings",
    "printability_result_if_returned",
    "repair_operations_if_any",
    "human_review_state",
)

# Meshy 7-family capabilities Phase 43's registry already records
# (`factory.engine_registry.get_tool_registry()["meshy"]["capabilities"]`)
# - restated here only as policy-relevant context (each still requires the
# same Factory validation/review downstream), never as a claim that any of
# them is API-accessible from this repo.
KNOWN_MESHY_CAPABILITIES = (
    "text_to_3d_concept",
    "image_to_3d",
    "multi_image_to_3d",
    "meshy_7_family",
    "smart_topology",
    "separated_native_parts",
    "target_polygon_count",
    "3mf_output",
    "multi_color_print",
    "analyze_printability",
    "repair_printability",
    "auto_split",
)

# Locked equivalences (docs/meshy-policy.md "Printability policy lock") -
# restated here as data so `evaluate_meshy_gate()`'s output can carry it
# verbatim into every JSON/CLI rendering, rather than callers having to
# know this prose lives only in a docstring.
PRINTABILITY_POLICY_LOCK = (
    "Meshy printability analysis != Factory validation.",
    "Meshy repair != Factory repair approval.",
    "Meshy Auto Split != Factory multipart approval.",
    "Meshy 3MF output != slicer-ready.",
    "Any future Meshy result must still pass Factory artifact tracking, Factory mesh validation, "
    "Factory dimension checks, Factory manufacturing checks, Factory preview, Factory human review, "
    "and Factory slicer readiness - exactly like every other mesh in this repo.",
)


class MeshyPolicyError(Exception):
    pass


# ---------------------------------------------------------------------------
# Persistence - read-only by every command except the two explicit writers
# ---------------------------------------------------------------------------


def load_meshy_policy() -> dict[str, Any]:
    """Read `config/meshy_policy.json` as-is. No network, no .env, no
    credential access of any kind - this file holds no secrets, only
    human-set policy structure."""
    return project_store.load_json(MESHY_POLICY_PATH)


def _save_meshy_policy(policy: dict[str, Any]) -> None:
    project_store.save_json(MESHY_POLICY_PATH, policy)


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------


def _cost_policy_configured(cost_policy: dict[str, Any]) -> bool:
    """A cost policy counts as "configured" once at least one real cap is
    set - an all-null cost policy (this phase's shipped default) leaves
    `unknown_price_behavior` doing all the work, which is exactly the
    conservative starting point, not a completed policy."""
    return any(
        cost_policy.get(field) is not None
        for field in ("per_request_cap", "per_project_cap", "daily_cap", "monthly_cap")
    )


def _license_policy_reviewed(license_policy: dict[str, Any]) -> bool:
    return bool(license_policy.get("terms_reviewed"))


def _blockers_for_policy(policy: dict[str, Any]) -> list[str]:
    """Every currently-unmet requirement, in the same order `gate_status`
    below walks them - `blockers` lists all of them at once (matching the
    human-output example's multi-item "BLOCKERS" list), while
    `gate_status` names only the next one."""
    blockers: list[str] = []
    cost_policy = policy.get("cost_policy", {})
    license_policy = policy.get("license_policy", {})
    approval = policy.get("approval", {})

    if not _cost_policy_configured(cost_policy):
        blockers.append("Cost cap not configured.")
    if not _license_policy_reviewed(license_policy):
        blockers.append("Commercial-use / terms-of-service posture not reviewed.")
    if not (
        approval.get("cost_policy_acknowledged")
        and approval.get("license_policy_acknowledged")
        and approval.get("privacy_policy_acknowledged")
        and approval.get("provenance_policy_acknowledged")
    ):
        blockers.append("Human cloud approval not recorded.")
    return blockers


def _gate_status_for_policy(policy: dict[str, Any]) -> str:
    approval = policy.get("approval", {})
    if approval.get("revoked_at"):
        return "revoked"

    cost_policy = policy.get("cost_policy", {})
    license_policy = policy.get("license_policy", {})

    if not _cost_policy_configured(cost_policy):
        return "needs_cost_policy"
    if not _license_policy_reviewed(license_policy):
        return "needs_license_policy"
    if not (
        approval.get("cost_policy_acknowledged")
        and approval.get("license_policy_acknowledged")
        and approval.get("privacy_policy_acknowledged")
        and approval.get("provenance_policy_acknowledged")
    ):
        return "needs_human_approval"
    return "approved_for_future_api_integration"


def evaluate_meshy_gate() -> dict[str, Any]:
    """The core, read-only Phase 46 gate evaluation. Never writes
    anything, never contacts a network, never reads a credential value.
    Joins `config/meshy_policy.json` (this phase's own policy structure)
    with `config/future_cloud_tools.json`'s existing kill-switch record
    (Phase 16) - never rewrites either.
    """
    policy = load_meshy_policy()
    future_cloud_gate = get_future_cloud_tool("meshy")
    approval = policy.get("approval", {})

    gate_status = _gate_status_for_policy(policy)
    blockers = _blockers_for_policy(policy)
    warnings: list[str] = []
    if future_cloud_gate.get("enabled"):
        # Not reachable by anything in this repo today, but if it ever
        # were true, this policy gate must not be misread as the reason.
        warnings.append(
            "config/future_cloud_tools.json reports meshy.enabled=true - this policy gate never set that; "
            "investigate before treating Meshy as usable."
        )

    next_actions: list[str] = []
    if gate_status == "needs_cost_policy":
        next_actions.append("Set an explicit cost/credit cap in config/meshy_policy.json's cost_policy.")
    elif gate_status == "needs_license_policy":
        next_actions.append("Review Meshy's terms of service for the intended use and record terms_reviewed=true.")
    elif gate_status == "needs_human_approval":
        next_actions.append(
            "Run `factory meshy approve-policy --ack-cost --ack-license --ack-privacy --ack-provenance` "
            "after reviewing each policy area, once cost/license review above is complete."
        )
    elif gate_status == "approved_for_future_api_integration":
        next_actions.append("Policy scaffold is ready for a future Phase 47 adapter design - this does not authorize any Meshy call.")

    return {
        "tool_id": "meshy",
        "policy_version": policy.get("policy_version", POLICY_VERSION),
        "gate_status": gate_status,
        "cloud_use_allowed": False,
        "api_execution_allowed": False,
        "human_approval_required": True,
        "approval_recorded": bool(approval.get("approval_scope")),
        "cost_policy": policy.get("cost_policy", {}),
        "license_policy": policy.get("license_policy", {}),
        "privacy_policy": {
            "allowed_input_classes": list(ALLOWED_DATA_CLASSES_BY_DEFAULT),
            "forbidden_input_classes": list(FORBIDDEN_DATA_CLASSES_BY_DEFAULT),
            "default_behavior_for_unlisted_class": "forbidden",
        },
        "provenance_policy": {
            "required_request_fields": list(REQUIRED_REQUEST_PROVENANCE_FIELDS),
            "required_output_fields": list(REQUIRED_OUTPUT_PROVENANCE_FIELDS),
        },
        "data_policy": {
            "input_classes": {key: dict(value) for key, value in INPUT_CLASS_POLICY.items()},
        },
        "allowed_input_classes": list(INPUT_CLASSES),
        "forbidden_input_classes": [],
        "allowed_output_classes": ["mesh_concept", "3mf"],
        "required_receipt_fields": list(REQUIRED_OUTPUT_PROVENANCE_FIELDS),
        "approval": approval,
        "blockers": blockers,
        "warnings": warnings,
        "next_actions": next_actions,
        "kill_switch": {
            "source": "config/future_cloud_tools.json",
            "enabled": bool(future_cloud_gate.get("enabled", False)),
            "status": future_cloud_gate.get("status"),
            "policy_approved": gate_status == "approved_for_future_api_integration",
            "execution_enabled": False,
        },
        "printability_policy_lock": list(PRINTABILITY_POLICY_LOCK),
        "known_capabilities": list(KNOWN_MESHY_CAPABILITIES),
        "network_used": False,
        "credentials_read": False,
        "money_spent": False,
        "automatic_print_allowed": False,
        "no_automatic_print": True,
    }


def evaluate_meshy_phase47_readiness(gate: dict[str, Any] | None = None) -> dict[str, Any]:
    """Whether the *policy scaffold* is complete enough for a future Phase
    47 to safely begin *designing* a Meshy adapter against it.
    `ready_for_phase47=True` never means "safe to call Meshy now" - actual
    execution still requires `kill_switch.execution_enabled=True`, which
    no code path in this repo can set."""
    gate = gate if gate is not None else evaluate_meshy_gate()

    requirements = {
        "policy_model_complete": True,
        "cost_cap_configured": _cost_policy_configured(gate["cost_policy"]),
        "unknown_cost_behavior_defined": gate["cost_policy"].get("unknown_price_behavior") is not None,
        "license_posture_reviewed": _license_policy_reviewed(gate["license_policy"]),
        "privacy_policy_defined": bool(gate["privacy_policy"]["forbidden_input_classes"]),
        "provenance_requirements_defined": bool(gate["provenance_policy"]["required_request_fields"]),
        "cloud_upload_categories_defined": bool(gate["data_policy"]["input_classes"]),
        "human_policy_approval_recorded": bool(gate["approval"].get("approval_scope")),
        "kill_switch_design_present": True,
        "execution_remains_disabled_until_phase47": gate["kill_switch"]["execution_enabled"] is False,
    }
    ready = all(requirements.values())
    return {
        "ready_for_phase47": ready,
        "requirements": requirements,
        "note": (
            "ready_for_phase47=True means only that this policy scaffold is complete enough for a future "
            "phase to begin implementing the Meshy adapter against it - it never means Meshy may be called now."
        ),
        "unmet_requirements": [name for name, met in requirements.items() if not met],
    }


# ---------------------------------------------------------------------------
# Reference-board / privacy classification helpers - policy mapping only,
# never consulted by any real upload path (none exists) and never mutating
# reference_board.json.
# ---------------------------------------------------------------------------


def classify_reference_cloud_upload_permission(license_value: str) -> dict[str, Any]:
    """Map one `factory.reference_board` `license` value to a cloud-upload
    policy classification. Pure function - reads nothing, mutates nothing.
    An unrecognized value is treated exactly like `"unknown"` (blocked)."""
    if license_value not in LICENSES:
        license_value = "unknown"
    if license_value in CLOUD_UPLOAD_ALLOWED_LICENSES:
        return {"license": license_value, "cloud_upload_allowed": True, "classification": "uploadable", "reason": "License is unambiguous and permissive enough for third-party cloud processing."}
    if license_value in CLOUD_UPLOAD_NON_COMMERCIAL_ONLY_LICENSES:
        return {
            "license": license_value,
            "cloud_upload_allowed": False,
            "classification": "uploadable_non_commercial_only",
            "reason": "Non-commercial license - conceptually usable for internal/non-commercial study only, and still requires explicit human approval before any real upload.",
        }
    return {
        "license": license_value,
        "cloud_upload_allowed": False,
        "classification": "not_uploadable_to_cloud",
        "reason": "License is unknown, proprietary, personal-use, or custom - upload rights to a third-party API are not assumed from any of these.",
    }


def classify_data_class_cloud_permission(data_class: str) -> dict[str, Any]:
    """Map one privacy data class to a cloud-upload policy classification.
    Policy metadata only - no file scanning, no content inspection."""
    if data_class not in DATA_CLASSES:
        data_class = "unknown_source"
    allowed = data_class in ALLOWED_DATA_CLASSES_BY_DEFAULT
    return {
        "data_class": data_class,
        "cloud_upload_allowed_by_default": allowed,
        "reason": (
            "Recognized as a class this policy already treats as fine to leave the machine."
            if allowed
            else "Forbidden by default - a classroom/private/unknown-source/third-party-copyrighted class, "
            "or a class this policy does not recognize, requires explicit case-by-case human approval."
        ),
    }


# ---------------------------------------------------------------------------
# Approval lifecycle - the only two functions in this module that write
# ---------------------------------------------------------------------------


def record_meshy_policy_approval(
    *,
    ack_cost: bool,
    ack_license: bool,
    ack_privacy: bool,
    ack_provenance: bool,
    approval_scope: str = "policy_only",
    approved_by: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Explicit, human-invoked write. Every acknowledgement flag must be
    passed `True` - there is no default-approve path. This can only ever
    record `approval.execution_enabled=False`; nothing in this function
    can set it `True`, by design (see module docstring). Requires the
    cost/license policy to already be configured/reviewed - approving an
    empty policy is refused, matching "complete policy still requires
    human approval" (approval on top of nothing to approve is not
    meaningful)."""
    if approval_scope not in APPROVAL_SCOPES:
        raise MeshyPolicyError(f"approval_scope {approval_scope!r} is not one of {APPROVAL_SCOPES!r}")
    if not (ack_cost and ack_license and ack_privacy and ack_provenance):
        raise MeshyPolicyError(
            "All four acknowledgements (--ack-cost --ack-license --ack-privacy --ack-provenance) are required "
            "to record Meshy policy approval - partial acknowledgement is not recorded."
        )

    policy = load_meshy_policy()
    if not _cost_policy_configured(policy["cost_policy"]):
        raise MeshyPolicyError(
            "Cannot record approval: no cost cap is configured in config/meshy_policy.json's cost_policy. "
            "Set an explicit cap first."
        )
    if not _license_policy_reviewed(policy["license_policy"]):
        raise MeshyPolicyError(
            "Cannot record approval: license_policy.terms_reviewed is still false in config/meshy_policy.json. "
            "Review Meshy's terms of service and set it to true first."
        )

    approval = policy["approval"]
    approval["approved_at"] = project_store.utc_now_iso()
    approval["approved_by"] = approved_by
    approval["approval_scope"] = approval_scope
    approval["cost_policy_acknowledged"] = True
    approval["license_policy_acknowledged"] = True
    approval["privacy_policy_acknowledged"] = True
    approval["provenance_policy_acknowledged"] = True
    approval["cloud_data_policy_acknowledged"] = True
    approval["execution_enabled"] = False
    approval["revoked_at"] = None
    if note:
        approval.setdefault("notes", []).append(note)

    _save_meshy_policy(policy)
    return evaluate_meshy_gate()


def revoke_meshy_policy_approval(*, reason: str | None = None) -> dict[str, Any]:
    """Explicit, human-invoked write. Marks the current approval revoked
    and disables the future-execution gate; preserves the prior approval
    as history rather than discarding it. Local file only - no network,
    no remote revocation."""
    policy = load_meshy_policy()
    approval = policy["approval"]

    if approval.get("approval_scope") is None and not approval.get("approved_at"):
        raise MeshyPolicyError("No recorded Meshy policy approval exists to revoke.")

    history_entry = {
        "approved_at": approval.get("approved_at"),
        "approved_by": approval.get("approved_by"),
        "approval_scope": approval.get("approval_scope"),
        "revoked_at": project_store.utc_now_iso(),
        "reason": reason,
    }
    policy.setdefault("approval", {}).setdefault("revocation_history", []).append(history_entry)

    approval["revoked_at"] = history_entry["revoked_at"]
    approval["execution_enabled"] = False
    approval["approval_scope"] = None
    approval["cost_policy_acknowledged"] = False
    approval["license_policy_acknowledged"] = False
    approval["privacy_policy_acknowledged"] = False
    approval["provenance_policy_acknowledged"] = False
    approval["cloud_data_policy_acknowledged"] = False

    _save_meshy_policy(policy)
    return evaluate_meshy_gate()


# ---------------------------------------------------------------------------
# Compact summary for Preview Board
# ---------------------------------------------------------------------------


def summarize_meshy_policy_for_board() -> dict[str, Any]:
    """Compact, read-only summary for the Preview Board's global Tool
    Environment section - one line, never a per-project card, never a
    network call. Deliberately separate from
    `factory.engine_registry.summarize_tool_environment()` (consumed by
    `factory.project_health`, which this phase must not touch) - see the
    module docstring's "Architectural note"."""
    gate = evaluate_meshy_gate()
    return {
        "gate_status": gate["gate_status"],
        "cloud_use_allowed": gate["cloud_use_allowed"],
        "human_approval_required": gate["human_approval_required"],
        "approval_recorded": gate["approval_recorded"],
        "blocker_count": len(gate["blockers"]),
    }

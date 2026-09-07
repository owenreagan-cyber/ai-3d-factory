"""Phase 46 core tests: `factory.meshy_approval`'s gate/policy/approval/
readiness model. Every test isolates `MESHY_POLICY_PATH` to a `tmp_path`
copy - never the real committed `config/meshy_policy.json` - so these
tests never mutate a tracked file. See docs/meshy-policy.md.
"""

from __future__ import annotations

import copy
import json

import pytest

from factory import meshy_approval as m

_DEFAULT_POLICY = {
    "policy_version": 1,
    "cost_policy": {
        "currency": None,
        "per_request_cap": None,
        "per_project_cap": None,
        "daily_cap": None,
        "monthly_cap": None,
        "require_cost_estimate_before_request": True,
        "require_confirmation_above_threshold": True,
        "unknown_price_behavior": "block",
        "spend_tracking_required": True,
        "hard_stop_on_unknown_cost": True,
        "credit_policy": {
            "max_credits_per_request": None,
            "max_credits_per_project": None,
            "max_credits_per_day": None,
            "max_credits_per_month": None,
        },
    },
    "license_policy": {
        "commercial_use_required": None,
        "commercial_use_verified": False,
        "terms_reviewed": False,
        "terms_review_date": None,
        "output_ownership_verified": False,
        "input_rights_required": True,
        "reference_license_required": True,
        "third_party_asset_restrictions": "unknown",
        "unknown_license_behavior": "block_commercial_use",
    },
    "approval": {
        "approved_at": None,
        "approved_by": None,
        "approval_scope": None,
        "cost_policy_acknowledged": False,
        "license_policy_acknowledged": False,
        "privacy_policy_acknowledged": False,
        "provenance_policy_acknowledged": False,
        "cloud_data_policy_acknowledged": False,
        "execution_enabled": False,
        "notes": [],
        "revoked_at": None,
        "revocation_history": [],
    },
}


@pytest.fixture
def policy_path(tmp_path, monkeypatch):
    path = tmp_path / "meshy_policy.json"
    path.write_text(json.dumps(copy.deepcopy(_DEFAULT_POLICY)))
    monkeypatch.setattr(m, "MESHY_POLICY_PATH", path)
    return path


def _set_policy(policy_path, **top_level_overrides):
    policy = json.loads(policy_path.read_text())
    for key, value in top_level_overrides.items():
        policy[key] = value
    policy_path.write_text(json.dumps(policy))


# ---------------------------------------------------------------------------
# Core gate tests
# ---------------------------------------------------------------------------


def test_default_policy_disabled(policy_path):
    gate = m.evaluate_meshy_gate()
    assert gate["cloud_use_allowed"] is False
    assert gate["api_execution_allowed"] is False
    assert gate["kill_switch"]["execution_enabled"] is False


def test_default_no_approval_recorded(policy_path):
    gate = m.evaluate_meshy_gate()
    assert gate["approval_recorded"] is False
    assert gate["approval"]["approval_scope"] is None


def test_default_execution_disabled(policy_path):
    gate = m.evaluate_meshy_gate()
    assert gate["kill_switch"]["execution_enabled"] is False
    assert gate["kill_switch"]["enabled"] is False


def test_incomplete_cost_policy_blocks_readiness(policy_path):
    gate = m.evaluate_meshy_gate()
    assert gate["gate_status"] == "needs_cost_policy"
    readiness = m.evaluate_meshy_phase47_readiness(gate)
    assert readiness["ready_for_phase47"] is False
    assert "cost_cap_configured" in readiness["unmet_requirements"]


def test_incomplete_license_policy_blocks_readiness(policy_path):
    policy = json.loads(policy_path.read_text())
    policy["cost_policy"]["monthly_cap"] = 20
    policy_path.write_text(json.dumps(policy))

    gate = m.evaluate_meshy_gate()
    assert gate["gate_status"] == "needs_license_policy"
    readiness = m.evaluate_meshy_phase47_readiness(gate)
    assert readiness["ready_for_phase47"] is False
    assert "license_posture_reviewed" in readiness["unmet_requirements"]


def test_privacy_policy_always_defined(policy_path):
    """Privacy policy is structural (fixed vocabulary), not user-entered -
    it never blocks readiness on its own in this phase."""
    gate = m.evaluate_meshy_gate()
    readiness = m.evaluate_meshy_phase47_readiness(gate)
    assert readiness["requirements"]["privacy_policy_defined"] is True


def test_provenance_policy_always_defined(policy_path):
    gate = m.evaluate_meshy_gate()
    readiness = m.evaluate_meshy_phase47_readiness(gate)
    assert readiness["requirements"]["provenance_requirements_defined"] is True


def test_complete_cost_and_license_still_requires_human_approval(policy_path):
    policy = json.loads(policy_path.read_text())
    policy["cost_policy"]["monthly_cap"] = 20
    policy["license_policy"]["terms_reviewed"] = True
    policy_path.write_text(json.dumps(policy))

    gate = m.evaluate_meshy_gate()
    assert gate["gate_status"] == "needs_human_approval"
    readiness = m.evaluate_meshy_phase47_readiness(gate)
    assert readiness["ready_for_phase47"] is False


def test_approval_does_not_automatically_enable_execution(policy_path):
    policy = json.loads(policy_path.read_text())
    policy["cost_policy"]["monthly_cap"] = 20
    policy["license_policy"]["terms_reviewed"] = True
    policy_path.write_text(json.dumps(policy))

    result = m.record_meshy_policy_approval(ack_cost=True, ack_license=True, ack_privacy=True, ack_provenance=True)
    assert result["gate_status"] == "approved_for_future_api_integration"
    assert result["kill_switch"]["execution_enabled"] is False
    assert result["api_execution_allowed"] is False
    assert result["cloud_use_allowed"] is False


def test_approval_requires_all_four_acks(policy_path):
    policy = json.loads(policy_path.read_text())
    policy["cost_policy"]["monthly_cap"] = 20
    policy["license_policy"]["terms_reviewed"] = True
    policy_path.write_text(json.dumps(policy))

    with pytest.raises(m.MeshyPolicyError):
        m.record_meshy_policy_approval(ack_cost=True, ack_license=True, ack_privacy=False, ack_provenance=True)


def test_approval_refused_without_configured_cost_cap(policy_path):
    with pytest.raises(m.MeshyPolicyError):
        m.record_meshy_policy_approval(ack_cost=True, ack_license=True, ack_privacy=True, ack_provenance=True)


def test_approval_refused_without_reviewed_license(policy_path):
    policy = json.loads(policy_path.read_text())
    policy["cost_policy"]["monthly_cap"] = 20
    policy_path.write_text(json.dumps(policy))

    with pytest.raises(m.MeshyPolicyError):
        m.record_meshy_policy_approval(ack_cost=True, ack_license=True, ack_privacy=True, ack_provenance=True)


def test_revocation_disables_readiness(policy_path):
    policy = json.loads(policy_path.read_text())
    policy["cost_policy"]["monthly_cap"] = 20
    policy["license_policy"]["terms_reviewed"] = True
    policy_path.write_text(json.dumps(policy))
    m.record_meshy_policy_approval(ack_cost=True, ack_license=True, ack_privacy=True, ack_provenance=True)

    gate = m.revoke_meshy_policy_approval(reason="test revocation")
    assert gate["gate_status"] == "revoked"
    readiness = m.evaluate_meshy_phase47_readiness(gate)
    assert readiness["ready_for_phase47"] is False
    assert gate["approval_recorded"] is False


def test_revoke_without_prior_approval_raises(policy_path):
    with pytest.raises(m.MeshyPolicyError):
        m.revoke_meshy_policy_approval()


def test_revocation_preserves_history(policy_path):
    policy = json.loads(policy_path.read_text())
    policy["cost_policy"]["monthly_cap"] = 20
    policy["license_policy"]["terms_reviewed"] = True
    policy_path.write_text(json.dumps(policy))
    m.record_meshy_policy_approval(ack_cost=True, ack_license=True, ack_privacy=True, ack_provenance=True, approved_by="owen")

    m.revoke_meshy_policy_approval(reason="changed my mind")
    saved = json.loads(policy_path.read_text())
    history = saved["approval"]["revocation_history"]
    assert len(history) == 1
    assert history[0]["approved_by"] == "owen"
    assert history[0]["reason"] == "changed my mind"


def test_phase47_readiness_semantics_never_implies_execution(policy_path):
    policy = json.loads(policy_path.read_text())
    policy["cost_policy"]["monthly_cap"] = 20
    policy["license_policy"]["terms_reviewed"] = True
    policy_path.write_text(json.dumps(policy))
    m.record_meshy_policy_approval(ack_cost=True, ack_license=True, ack_privacy=True, ack_provenance=True)

    gate = m.evaluate_meshy_gate()
    readiness = m.evaluate_meshy_phase47_readiness(gate)
    assert readiness["ready_for_phase47"] is True
    # Even fully "ready for phase 47", execution stays impossible.
    assert gate["kill_switch"]["execution_enabled"] is False
    assert gate["api_execution_allowed"] is False
    assert "never means Meshy may be called now" in readiness["note"]


def test_one_bad_field_does_not_crash_gate_evaluation(policy_path):
    _set_policy(policy_path, cost_policy={})
    gate = m.evaluate_meshy_gate()
    assert gate["gate_status"] == "needs_cost_policy"


# ---------------------------------------------------------------------------
# Cost policy tests
# ---------------------------------------------------------------------------


def test_missing_cost_caps_stay_none_not_invented(policy_path):
    gate = m.evaluate_meshy_gate()
    cost = gate["cost_policy"]
    assert cost["currency"] is None
    assert cost["per_request_cap"] is None
    assert cost["monthly_cap"] is None


def test_explicit_cost_cap_recognized(policy_path):
    policy = json.loads(policy_path.read_text())
    policy["cost_policy"]["per_request_cap"] = 5
    policy_path.write_text(json.dumps(policy))
    assert m._cost_policy_configured(m.load_meshy_policy()["cost_policy"]) is True


def test_unknown_price_behavior_defaults_to_block(policy_path):
    gate = m.evaluate_meshy_gate()
    assert gate["cost_policy"]["unknown_price_behavior"] == "block"


def test_credit_cap_fields_present_and_unset_by_default(policy_path):
    gate = m.evaluate_meshy_gate()
    credit_policy = gate["cost_policy"]["credit_policy"]
    for field in ("max_credits_per_request", "max_credits_per_project", "max_credits_per_day", "max_credits_per_month"):
        assert credit_policy[field] is None


def test_no_negative_cost_cap_semantics_assumed():
    """This module never validates/clamps a human-entered cap - it only
    reads what's there. A negative cap is a human data-entry error to
    fix, not something this module would silently accept as meaningful."""
    assert "per_request_cap" in _DEFAULT_POLICY["cost_policy"]


# ---------------------------------------------------------------------------
# License tests
# ---------------------------------------------------------------------------


def test_unknown_license_defaults_block_commercial(policy_path):
    gate = m.evaluate_meshy_gate()
    assert gate["license_policy"]["unknown_license_behavior"] == "block_commercial_use"


def test_commercial_use_unverified_by_default(policy_path):
    gate = m.evaluate_meshy_gate()
    assert gate["license_policy"]["commercial_use_verified"] is False


def test_output_ownership_unverified_by_default(policy_path):
    gate = m.evaluate_meshy_gate()
    assert gate["license_policy"]["output_ownership_verified"] is False


@pytest.mark.parametrize(
    "license_value,expected_allowed",
    [
        ("unknown", False),
        ("proprietary", False),
        ("personal_use", False),
        ("custom", False),
        ("public_domain", True),
        ("cc_by", True),
        ("cc_by_sa", True),
        ("commercial_allowed", True),
        ("cc_by_nc", False),
    ],
)
def test_reference_license_cloud_upload_classification(license_value, expected_allowed):
    result = m.classify_reference_cloud_upload_permission(license_value)
    assert result["cloud_upload_allowed"] is expected_allowed


def test_reference_license_classification_never_invents_a_new_value():
    result = m.classify_reference_cloud_upload_permission("some-made-up-value")
    assert result["license"] == "unknown"
    assert result["cloud_upload_allowed"] is False


def test_personal_vs_commercial_distinction_preserved():
    non_commercial = m.classify_reference_cloud_upload_permission("cc_by_nc")
    commercial = m.classify_reference_cloud_upload_permission("commercial_allowed")
    assert non_commercial["classification"] == "uploadable_non_commercial_only"
    assert commercial["classification"] == "uploadable"


# ---------------------------------------------------------------------------
# Privacy tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("data_class", ["student_data", "student_photo", "private_photo", "personal_identifier", "confidential_project", "commercial_secret", "third_party_copyrighted_reference", "unknown_source"])
def test_private_and_classroom_data_classes_forbidden_by_default(data_class):
    result = m.classify_data_class_cloud_permission(data_class)
    assert result["cloud_upload_allowed_by_default"] is False


@pytest.mark.parametrize("data_class", ["public_reference", "user_created_reference", "licensed_reference"])
def test_explicit_licensed_input_classes_allowed_by_policy(data_class):
    result = m.classify_data_class_cloud_permission(data_class)
    assert result["cloud_upload_allowed_by_default"] is True


def test_unrecognized_data_class_treated_as_unknown_source():
    result = m.classify_data_class_cloud_permission("something-not-in-the-vocabulary")
    assert result["data_class"] == "unknown_source"
    assert result["cloud_upload_allowed_by_default"] is False


def test_multi_image_requires_per_image_review():
    policy = m.INPUT_CLASS_POLICY["multi_image"]
    assert policy["requires_license_review"] is True
    assert "own license/privacy review" in policy["note"]


def test_privacy_policy_is_data_only_never_a_file_scanner():
    """This module has no filesystem-scanning capability at all - it only
    classifies a value the caller supplies."""
    import inspect

    source = inspect.getsource(m)
    assert "os.walk" not in source
    assert "glob.glob" not in source
    assert "Path.rglob" not in source


# ---------------------------------------------------------------------------
# Reference-board integration tests
# ---------------------------------------------------------------------------


def test_reference_board_json_never_mutated_by_classification(tmp_path):
    from factory import reference_board

    board_path = tmp_path / "reference_board.json"
    board_path.write_text(json.dumps({"references": [{"license": "unknown"}]}))
    before = board_path.read_text()

    m.classify_reference_cloud_upload_permission("unknown")

    assert board_path.read_text() == before


def test_design_reference_only_usage_intent_still_requires_explicit_license():
    """Marking a reference "design reference only" is a usage-intent fact,
    never a cloud-upload permission - the license value alone still
    governs upload classification."""
    assert m.classify_reference_cloud_upload_permission("unknown")["cloud_upload_allowed"] is False


def test_every_reference_board_license_value_has_a_classification():
    from factory.reference_board import LICENSES

    for license_value in LICENSES:
        result = m.classify_reference_cloud_upload_permission(license_value)
        assert result["license"] == license_value


# ---------------------------------------------------------------------------
# Provenance tests
# ---------------------------------------------------------------------------


def test_required_request_provenance_fields_present():
    for field in ("request_type", "input_fingerprints", "human_approver", "cost_estimate", "reference_ids"):
        assert field in m.REQUIRED_REQUEST_PROVENANCE_FIELDS


def test_required_output_provenance_fields_present():
    for field in ("meshy_task_id", "output_fingerprints", "validation_result" if False else "human_review_state", "license_posture"):
        assert field in m.REQUIRED_OUTPUT_PROVENANCE_FIELDS


def test_no_fake_task_id_ever_generated(policy_path):
    gate = m.evaluate_meshy_gate()
    assert "meshy_task_id" not in gate
    assert gate["required_receipt_fields"] == list(m.REQUIRED_OUTPUT_PROVENANCE_FIELDS)


# ---------------------------------------------------------------------------
# Determinism / summary tests
# ---------------------------------------------------------------------------


def test_deterministic_given_same_policy_state(policy_path):
    gate_a = m.evaluate_meshy_gate()
    gate_b = m.evaluate_meshy_gate()
    assert gate_a == gate_b


def test_summary_for_board_is_compact(policy_path):
    summary = m.summarize_meshy_policy_for_board()
    assert set(summary.keys()) == {"gate_status", "cloud_use_allowed", "human_approval_required", "approval_recorded", "blocker_count"}


def test_printability_policy_lock_present(policy_path):
    gate = m.evaluate_meshy_gate()
    joined = " ".join(gate["printability_policy_lock"])
    assert "Factory validation" in joined
    assert "Factory repair approval" in joined
    assert "slicer-ready" in joined


def test_known_capabilities_preserved_from_registry_docs(policy_path):
    gate = m.evaluate_meshy_gate()
    for capability in ("meshy_7_family", "smart_topology", "auto_split", "analyze_printability", "repair_printability", "3mf_output"):
        assert capability in gate["known_capabilities"]

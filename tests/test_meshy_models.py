"""Phase 47A tests: `factory.meshy_models` - pure request/response/task-
state model definitions. No I/O in this module, so no fixtures needed."""

from __future__ import annotations

import pytest

from factory import meshy_models as m


def test_request_types_is_text_to_3d_only():
    assert m.REQUEST_TYPES == ("text_to_3d",)


def test_prompt_hash_stable():
    a = m.compute_prompt_hash("A simple rounded piggy bank concept")
    b = m.compute_prompt_hash("A simple rounded piggy bank concept")
    assert a == b
    assert len(a) == 64  # sha256 hex digest


def test_prompt_hash_differs_for_different_prompts():
    assert m.compute_prompt_hash("a") != m.compute_prompt_hash("b")


def test_build_text_to_3d_request_default_model_is_documented_current_model():
    request = m.build_text_to_3d_request(prompt="a rounded concept")
    assert request["model"] == m.DEFAULT_AI_MODEL == "meshy-7"


def test_build_text_to_3d_request_model_is_explicit_overridable_parameter():
    request = m.build_text_to_3d_request(prompt="x", ai_model="meshy-6")
    assert request["model"] == "meshy-6"


def test_build_text_to_3d_request_rejects_unknown_model():
    with pytest.raises(ValueError):
        m.build_text_to_3d_request(prompt="x", ai_model="meshy-99-future-fake")


def test_build_text_to_3d_request_rejects_unknown_mode():
    with pytest.raises(ValueError):
        m.build_text_to_3d_request(prompt="x", mode="turbo")


def test_build_text_to_3d_request_rejects_unsupported_output_format():
    with pytest.raises(ValueError):
        m.build_text_to_3d_request(prompt="x", output_format="obj")


def test_request_never_marks_live_execution_allowed():
    request = m.build_text_to_3d_request(prompt="x")
    assert request["live_execution_allowed"] is False
    assert request["dry_run"] is True


def test_request_reference_ids_empty_for_text_only():
    request = m.build_text_to_3d_request(prompt="x")
    assert request["reference_ids"] == []


# ---------------------------------------------------------------------------
# Credit estimation - grounded in docs/meshy-current-research.md's cost table
# ---------------------------------------------------------------------------


def test_estimate_credits_meshy7_preview():
    assert m.estimate_text_to_3d_credits(ai_model="meshy-7", mode="preview") == 20


def test_estimate_credits_meshy7_preview_ultra_mode_surcharge():
    assert m.estimate_text_to_3d_credits(ai_model="meshy-7", mode="preview", ultra_mode=True) == 25


def test_estimate_credits_smart_topology_cheaper():
    assert m.estimate_text_to_3d_credits(ai_model="meshy-t2", mode="preview") == 5


def test_estimate_credits_refine_requires_texture_resolution():
    assert m.estimate_text_to_3d_credits(ai_model="meshy-7", mode="refine") is None
    assert m.estimate_text_to_3d_credits(ai_model="meshy-7", mode="refine", texture_resolution="4k") == 10
    assert m.estimate_text_to_3d_credits(ai_model="meshy-7", mode="refine", texture_resolution="8k") == 15


def test_estimate_credits_unknown_combination_returns_none_not_a_guess():
    assert m.estimate_text_to_3d_credits(ai_model="meshy-7", mode="refine", texture_resolution="16k") is None


def test_ultra_mode_only_applies_to_meshy7():
    """docs/meshy-current-research.md: ultra_mode is a Meshy-7-family
    surcharge - never silently applied to meshy-6/meshy-t2."""
    assert m.estimate_text_to_3d_credits(ai_model="meshy-6", mode="preview", ultra_mode=True) == 20
    assert m.estimate_text_to_3d_credits(ai_model="meshy-t2", mode="preview", ultra_mode=True) == 5


# ---------------------------------------------------------------------------
# Prompt privacy hook - simple keyword hook, never a PII scanner
# ---------------------------------------------------------------------------


def test_privacy_hook_clean_prompt_no_warnings():
    assert m.check_prompt_privacy_hook("A simple rounded piggy bank concept") == []


def test_privacy_hook_flags_student_keyword():
    warnings = m.check_prompt_privacy_hook("a trophy for my student Jane")
    assert any("student" in w for w in warnings)


def test_privacy_hook_flags_password_keyword():
    warnings = m.check_prompt_privacy_hook("use my password hunter2 for reference")
    assert any("password" in w for w in warnings)


def test_privacy_hook_never_blocks_by_itself():
    """The hook only returns warnings - it is not a policy decision on its
    own; `factory.meshy_adapter` decides whether to proceed."""
    warnings = m.check_prompt_privacy_hook("student project idea")
    assert isinstance(warnings, list)
    # No exception, no blocking return value - just a list.

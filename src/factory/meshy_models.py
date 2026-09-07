"""Phase 47A: Meshy request/response/task-state models.

Pure data definitions - no I/O, no subprocess, no network, no filesystem
access. Every vocabulary and field name here is grounded in
`docs/meshy-current-research.md` (Phase 46.6's researched public Meshy API
contract), never invented: this module's job is to give the mocked
adapter (`factory.meshy_mock_transport`, `factory.meshy_adapter`) a
stable, documented shape to build against - it does not itself decide
whether a request is allowed (that is `factory.meshy_approval`'s job) or
execute anything (that is the mock transport's job).

    Feature module (this file, data only)
        -> factory.meshy_mock_transport (mocked I/O)
        -> factory.meshy_adapter (orchestration: policy + budget + lifecycle)
        -> CLI

Text-to-3D is the only supported request type in this phase - see
`docs/meshy-current-research.md` "Recommended Phase 47A first request
type" for why (best-documented endpoint, fixed/predictable cost, no
upload, lowest privacy risk, simplest provenance).
"""

from __future__ import annotations

import hashlib
from typing import Any

REQUEST_TYPES = ("text_to_3d",)

# Meshy's own real task-status vocabulary, verbatim from the Image-to-3D
# response schema research documented (representative of the task model
# generally) - see docs/meshy-current-research.md "Provenance fields
# Meshy's API actually exposes". Never invented, never lowercased/renamed.
MESHY_TASK_STATUSES = ("PENDING", "IN_PROGRESS", "SUCCEEDED", "FAILED", "CANCELED")

# A Factory-side-only concept layered on top of `expires_at` (a real
# Meshy field) - "expired" is never one of Meshy's own `status` values,
# it's this repo's own interpretation of a SUCCEEDED task whose
# `expires_at` timestamp has passed. See docs/meshy-current-research.md
# "Failure/retry semantics" - re-download is not documented as possible
# without a new (paid) task once a URL expires.
ARTIFACT_STATES = ("available", "expired", "missing")

# Text-to-3D's two documented modes (docs/meshy-current-research.md API
# capability matrix: "preview + refine modes").
REQUEST_MODES = ("preview", "refine")

# The current documented model family (docs/meshy-current-research.md
# "Current Meshy API/model versions": Meshy 7, introduced mid-August
# 2026). Kept as an explicit, overridable parameter (never silently
# hardcoded past a request) precisely because the spec requires "model"
# stay an explicit config/parameter - this is today's real documented
# default, not a speculative future one.
DEFAULT_AI_MODEL = "meshy-7"
KNOWN_AI_MODELS = ("meshy-6", "meshy-7", "meshy-t2")

# The only output format Phase 47A's Factory-facing request model
# produces (STL - the manufacturing handoff format; see
# docs/meshy-current-research.md "Output formats" and the Phase 45/46.6
# precedent of using STL as the one Factory-neutral mesh format). Meshy's
# real `target_formats` parameter is a list; this module's `output_format`
# is a singular Factory-facing choice mapped to `target_formats: [value]`
# internally.
SUPPORTED_OUTPUT_FORMATS = ("stl",)

# Closed error vocabulary this phase must be able to represent and test -
# see the Phase 47A spec's "Error model" section. Represented as
# structured `{"error_code": ..., "message": ...}` dicts throughout this
# module and factory.meshy_adapter, never as a proliferation of custom
# exception classes - matching factory.blender_adapter's own
# checks/errors-list convention.
ERROR_CODES = (
    "policy_blocked",
    "budget_exceeded",
    "unknown_cost",
    "kill_switch_disabled",
    "live_execution_not_approved",
    "invalid_request",
    "task_failed",
    "task_timeout",
    "rate_limited",
    "server_error",
    "artifact_missing",
    "artifact_expired",
    "download_failed",
    "invalid_artifact",
    "validation_failed",
    "preview_failed",
    "receipt_failed",
    # Phase 47B additions - the mocked transport never needed a distinct
    # "the server rejected our credential" or "the connection itself
    # failed" code (it never contacts a network); a real HTTP transport
    # does. Additive only - every Phase 47A code above is unchanged.
    "credential_rejected",
    "network_error",
)

# Text-to-3D's own documented, fixed credit cost table
# (docs/meshy-current-research.md "Pricing/credit findings" -> "Operation
# cost table"). Only the Text-to-3D rows are represented here - Phase 47A
# supports no other request type. `None` means "not found/undocumented" -
# never guessed. Ultra mode (+5 credits, Meshy 7 family) and Smart
# Topology (a distinct, cheaper ai_model/model_type combination) are
# modeled as explicit additive/alternate entries, not silently merged.
_TEXT_TO_3D_PREVIEW_CREDITS: dict[str, int | None] = {
    "meshy-6": 20,
    "meshy-7": 20,
    "meshy-t2": 5,  # Smart Topology
}
_TEXT_TO_3D_REFINE_CREDITS_BY_TEXTURE: dict[str, int | None] = {
    "2k": 10,
    "4k": 10,
    "8k": 15,
}
_ULTRA_MODE_SURCHARGE_CREDITS = 5


def estimate_text_to_3d_credits(*, ai_model: str, mode: str, ultra_mode: bool = False, texture_resolution: str | None = None) -> int | None:
    """Deterministic credit estimate for one Text-to-3D request, reusing
    only the exact figures docs/meshy-current-research.md's pricing table
    documented. Returns `None` (never a guess) when the combination isn't
    in that table - callers (see `factory.meshy_adapter.check_budget()`)
    must treat `None` as "unknown cost", which this repo's policy always
    blocks (`unknown_price_behavior: "block"`)."""
    if mode == "preview":
        base = _TEXT_TO_3D_PREVIEW_CREDITS.get(ai_model)
    elif mode == "refine":
        if texture_resolution is None:
            return None
        base = _TEXT_TO_3D_REFINE_CREDITS_BY_TEXTURE.get(texture_resolution)
    else:
        return None
    if base is None:
        return None
    if ultra_mode and ai_model == "meshy-7":
        return base + _ULTRA_MODE_SURCHARGE_CREDITS
    return base


def compute_prompt_hash(prompt: str) -> str:
    """A stable SHA-256 hash of the prompt text - the
    `prompt_hash_or_sanitized_record` provenance field
    (`factory.meshy_approval.REQUIRED_REQUEST_PROVENANCE_FIELDS`) requires.
    Never logs, stores, or transmits the raw prompt anywhere this hash
    substitutes for it."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


# A simple, explicit policy hook - never a PII scanner. Per the spec:
# "Do not build a full PII scanner. Simple policy hooks only." A match
# here produces a *warning* recommending human review, never a silent
# block and never a claim of certainty about what the prompt contains.
_PROMPT_PRIVACY_REVIEW_KEYWORDS = (
    "student",
    "social security",
    " ssn",
    "password",
    "api key",
    "api_key",
    "credit card",
    "home address",
)


def check_prompt_privacy_hook(prompt: str) -> list[str]:
    """Returns a list of warnings (empty if none) recommending human
    review - never blocks by itself, never scans for anything beyond a
    fixed keyword list. `factory.meshy_adapter` surfaces these warnings in
    the request plan; a human decides whether to proceed."""
    lowered = f" {prompt.lower()} "
    return [
        f"Prompt contains {keyword.strip()!r} - recommend a human review this prompt for private/student data before any real submission."
        for keyword in _PROMPT_PRIVACY_REVIEW_KEYWORDS
        if keyword in lowered
    ]


def build_text_to_3d_request(
    *,
    prompt: str,
    ai_model: str = DEFAULT_AI_MODEL,
    mode: str = "preview",
    target_polygon_count: int | None = None,
    output_format: str = "stl",
    ultra_mode: bool = False,
    texture_resolution: str | None = None,
) -> dict[str, Any]:
    """The deterministic Text-to-3D request-plan dict - see the Phase 47A
    spec's "Request model" section for the field list. Pure function, no
    I/O: never checks policy/budget itself (see
    `factory.meshy_adapter.plan_text_to_3d_request()` for the function
    that joins this with the Phase 46 policy gate and the budget check).
    """
    if mode not in REQUEST_MODES:
        raise ValueError(f"mode {mode!r} is not one of {REQUEST_MODES!r}")
    if ai_model not in KNOWN_AI_MODELS:
        raise ValueError(f"ai_model {ai_model!r} is not one of {KNOWN_AI_MODELS!r}")
    if output_format not in SUPPORTED_OUTPUT_FORMATS:
        raise ValueError(f"output_format {output_format!r} is not one of {SUPPORTED_OUTPUT_FORMATS!r}")

    estimated_credits = estimate_text_to_3d_credits(ai_model=ai_model, mode=mode, ultra_mode=ultra_mode, texture_resolution=texture_resolution)

    return {
        "request_type": "text_to_3d",
        "prompt": prompt,
        "prompt_hash": compute_prompt_hash(prompt),
        "model": ai_model,
        "mode": mode,
        "target_polygon_count": target_polygon_count,
        "output_format": output_format,
        "target_formats": [output_format],
        "ultra_mode": ultra_mode,
        "texture_resolution": texture_resolution,
        "estimated_credits": estimated_credits,
        "reference_ids": [],
        "network_required": True,
        "live_execution_allowed": False,
        "dry_run": True,
    }

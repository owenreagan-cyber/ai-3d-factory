# Mocked Meshy Adapter & API Contract (Phase 47A)

`factory.meshy_models` / `factory.meshy_mock_transport` / `factory.meshy_adapter`
build the complete Meshy integration *architecture* - request planning,
policy/budget gating, an asynchronous task lifecycle, provenance, a
receipt, and a validation/preview handoff - entirely against a mocked
transport. **This phase never calls Meshy, never reads or validates a
credential, never spends money or credits, and never enables live
execution.**

    Policy Approved -> Mocked Adapter -> Mocked Request Planning ->
    Mocked Task Lifecycle -> Mocked Artifact Retrieval ->
    Factory Validation -> Factory Preview -> Human Review ->
    47A Review -> Separate 47B Approval -> One Controlled Real API Call

This phase reaches, at most, "Mocked Artifact Retrieval" / "Factory
Validation" / "Factory Preview" - never further. `live_execution_allowed`
is hardcoded `False` on every result this phase's code returns, with no
code path that ever sets it `True`; `config/future_cloud_tools.json`'s
Meshy kill switch is read (never written) and stays `false`.

    Mock response != real Meshy response
    Meshy response != Factory validated
    Factory validated != human approved
    Human approved != print approved

## Why this phase exists

Phase 46 (`docs/meshy-policy.md`) built the policy/approval gate. Phase
46.5/46.6 turned it into a human decision package and then a
research-informed, human-approved policy
(`config/meshy_policy.json`: credit caps, `terms_reviewed`,
`approval.approval_scope="policy_only"`). None of that proves the
*architecture* a real Meshy integration would need actually works. Phase
47A proves it, entirely offline, so that a future Phase 47B (a single,
separately-approved, real controlled API call) has something concrete to
review rather than a blank slate.

## Existing repository requirement mapping

Every request/response field name and vocabulary value in this phase
traces back to `docs/meshy-current-research.md` (Phase 46.6's researched
public Meshy API contract) - nothing here is invented past what that
document found:

- Task status vocabulary (`PENDING`/`IN_PROGRESS`/`SUCCEEDED`/`FAILED`/
  `CANCELED`) - verbatim from the researched response schema.
- Text-to-3D credit cost table (20/25/5/10/15 credits depending on
  model/mode/ultra-mode/texture resolution) - verbatim from the
  researched pricing table; combinations that table didn't document
  return `None` (never a guess).
- Receipt field names (`meshy_task_id`, `meshy_task_type`, `model_urls`,
  `consumed_credits`, `created_at`/`started_at`/`finished_at`/
  `expires_at`, `status`, `task_error`, ...) - the exact field names
  `docs/meshy-current-research.md`'s "Provenance fields Meshy's API
  actually exposes" section recommended, reused directly rather than
  invented parallel ones.
- No `seed` field exists anywhere in this phase's models - the research
  explicitly found Meshy documents none.
- `factory.meshy_approval.REQUIRED_REQUEST_PROVENANCE_FIELDS`/
  `REQUIRED_OUTPUT_PROVENANCE_FIELDS` (Phase 46) are unchanged; this
  phase's receipt is a superset compatible with them, not a
  parallel/competing schema.

## Architecture

```
factory.meshy_models          - pure request/response/task-state data, no I/O
        |
factory.meshy_mock_transport  - MeshyTransport interface + MockMeshyTransport (only impl)
        |
factory.meshy_adapter         - policy gate + budget gate + lifecycle orchestration
        |
        + factory.meshy_approval (Phase 46 - policy/approval, never re-implemented)
        + factory.validators.mesh_validate (reused directly)
        + factory.previews.render_preview (reused directly)
        |
CLI (factory meshy plan / factory meshy mock-run)
```

`factory.meshy_adapter` imports `factory.meshy_approval` directly (never
the reverse) - no circular import. Nothing in this phase imports CLI or
Preview Board back into a feature module.

## Transport abstraction

```python
class MeshyTransport(ABC):
    def submit_task(self, request: dict) -> dict: ...
    def get_task(self, task_id: str) -> dict: ...
    def download_artifact(self, model_url: str, destination: Path) -> Path: ...
```

`MockMeshyTransport` is the **only** implementation in this repo. There
is deliberately no `HttpMeshyTransport`, not even a non-functional
skeleton - a future, separately-approved Phase 47B would add one as an
entirely new class, not an extension of this one. `MockMeshyTransport`:

- Reads fixed, checked-in JSON fixtures from `tests/fixtures/meshy/`
  (`text_to_3d_submit_success.json`, `text_to_3d_processing.json`,
  `text_to_3d_success.json`, `text_to_3d_failure.json`,
  `expired_artifact.json`, `rate_limit_error.json`,
  `server_error.json`).
- `download_artifact()` never downloads anything - it copies the one
  fixed local STL fixture (`tests/fixtures/meshy/mock_concept.stl`, a
  static, deterministic, watertight 10mm cube - clearly a synthetic
  placeholder, never a real Meshy output). The `model_url` argument is
  accepted only to match the real interface's shape; it is never opened,
  resolved, or contacted.
- Every mock task id is generated as `mock-meshy-<uuid4>` - never
  confusable with (or logged/printed as though it were) a real Meshy
  task id.

## Request model (Text-to-3D only)

```python
{
  "request_type": "text_to_3d",
  "prompt": "...", "prompt_hash": "<sha256>",
  "model": "meshy-7",            # explicit, overridable - see below
  "mode": "preview",              # or "refine"
  "target_polygon_count": None,
  "output_format": "stl", "target_formats": ["stl"],
  "estimated_credits": 20,        # or None if undocumented - never guessed
  "reference_ids": [],            # reserved for a future Phase 47C, empty here
  "network_required": True, "live_execution_allowed": False, "dry_run": True,
}
```

**Why Text-to-3D and not Image-to-3D:** `docs/meshy-current-research.md`
"Recommended Phase 47A first request type" - best-documented endpoint,
fixed/predictable cost, no upload, lowest privacy risk, simplest
provenance, same downstream artifact shape as any other path.

**Why `model` stays an explicit parameter:** the research found Meshy 7
is today's current documented model family, but also found a real,
unresolved version-path ambiguity for a sibling endpoint
(Image-to-3D) - `model`/`ai_model` is therefore always an explicit,
overridable input (`DEFAULT_AI_MODEL = "meshy-7"`, today's real
documented default - never a "speculative future" hardcoded guess).

## Prompt handling

A prompt is hashed (`prompt_hash`, SHA-256) for provenance and never
otherwise transformed. `factory.meshy_models.check_prompt_privacy_hook()`
is a **simple keyword hook, not a PII scanner** - it flags a small,
fixed list of privacy-sensitive keywords ("student", "password", "api
key", "social security", ...) as a *warning* recommending human review,
never a silent block and never a certainty claim about what the prompt
actually contains.

## Budget gate

Reuses `config/meshy_policy.json`'s actual configured
`cost_policy.credit_policy` caps directly - never a second, parallel
budget scheme. `check_budget()`:

- Returns `error_code: "unknown_cost"` (blocked) when the estimate is
  `None` - matching the policy's `unknown_price_behavior: "block"`.
- Compares with `>` against `max_credits_per_request` - a request exactly
  at the cap is allowed, matching the Phase 47A spec's own test list
  ("25-credit request allowed" against a 25-credit cap).
- Optionally checks project/day/month totals against an
  `InMemoryCreditLedger`, if one is supplied.

**`InMemoryCreditLedger`** is deliberately not persisted anywhere - the
Phase 47A spec's own preference ("Prefer no persistence in 47A"). It
lives only as long as one Python process/CLI invocation; a real
multi-request-per-day budget history would need a future, separately
designed persistence layer, not an in-place extension of this class.

## Policy gate

`check_policy_gate()` joins `factory.meshy_approval.evaluate_meshy_gate()`
with one more explicit distinction this phase's spec requires never be
collapsed into one boolean:

```python
{
  "policy_approved": True,          # Phase 46's gate_status == approved_for_future_api_integration
  "mock_execution_allowed": True,   # == policy_approved, exactly
  "live_execution_allowed": False,  # hardcoded - no code path anywhere sets this True
  "kill_switch_enabled": False,     # config/future_cloud_tools.json, read-only, untouched
}
```

## Task lifecycle

Real Meshy statuses (`PENDING -> IN_PROGRESS -> SUCCEEDED` or `FAILED`),
bounded to at most 5 mocked polls (`_MAX_MOCK_POLLS`) - never an
unbounded loop, never a real sleep. `MockMeshyTransport` supports five
scenarios: `success`, `failure`, `rate_limited`, `server_error`,
`expired_artifact`. Rate-limit/server-error advisories are structured
`{"error_code", "message", "retry_allowed"}` dicts - `retry_allowed` is
never surfaced as `True` by the adapter regardless of what a mocked
advisory says, and **no code path in this repo retries automatically**.

## Validation/preview handoff

`factory.validators.mesh_validate.validate_mesh()` and
`factory.previews.render_preview.render_preview()` are called directly on
the mocked STL - no Meshy-specific validator or visual-QA subsystem
exists. **The mocked success fixture carries a
`meshy_printability_claim: {"printable": true}` field on purpose** - this
is never read by the adapter for any decision; Factory validation always
runs and its real result (which can be `FAIL` even when the provider
claims "printable") is what the receipt records. See
`tests/test_meshy_adapter.py::test_mock_printable_claim_does_not_bypass_factory_validation`.

## Artifact containment

Without `--project`, the entire mocked run (download + validate +
preview) happens inside one `tempfile.TemporaryDirectory()`, inventoried
before/after for unexpected-file detection, and verified cleaned via
`Path.exists()` after the run returns - the same pattern
`factory.blender_adapter` established in Phase 45. With `--project
<dir>`, the artifact and receipt are written into
`<project_dir>/generated/meshy/mock_concept.stl` and
`<project_dir>/generated/meshy_receipt.json` respectively - never into
`examples/` unless a caller explicitly passes an `examples/...` path
(the same "explicit human target" pattern every other write-capable
command in this repo already follows).

## Receipt

Built in memory on every mocked run; **persisted to disk only when
`--project` is given** - per the spec's stated preference ("do not write
persistent project receipts during ordinary mocked tests unless
explicitly using a disposable project"). Always carries:

```
mock_execution: true
live_api_used: false
credits_spent: 0
money_spent: 0
meshy_task_id: "mock-meshy-..."
commercial_policy_status: false   # commercial_use_verified, never marked ready by this phase
human_review_state: "required"
no_automatic_print: true
```

## Timeline / artifact-history integration - not implemented this phase

The receipt's field names are deliberately compatible with
`factory.project_timeline`/`factory.artifact_history`'s existing
per-module receipt-reader pattern (`read_last_execution_receipt()`,
`read_export_receipt()`, ...), but **no new reader was added to either
module in this phase**. Adding one would modify a shared core
aggregation module for a capability that remains entirely mocked -
exactly the kind of unnecessary shared-module change every prior phase
in this project has avoided. A future phase (47B, once real receipts
exist) should add a small, additive `_events_from_meshy_receipt()`
reader, the same way every other receipt type already has one.

## Engine Registry / Preview Board / Project Health integration

- `factory.engine_registry`'s canonical Meshy record (Phase 43) is
  unchanged.
- `factory meshy status`/`policy` now also report
  `factory.meshy_adapter.summarize_mock_adapter_state()`: `mock adapter
  implemented`, `live transport not implemented`, `live execution
  disabled` - all visible, never collapsed into one status.
- Preview Board's global Tool Environment section gained one more static
  pointer line (never a per-project card, never a network call, never
  Meshy execution during board generation).
- `factory.project_health`'s `health_score` is entirely untouched by this
  phase.

## CLI

```
factory meshy plan --prompt TEXT [--model ...] [--mode preview|refine]
    [--target-polygon-count N] [--project PATH] [--json]          # read-only, dry-run only

factory meshy mock-run --prompt TEXT [--model ...] [--mode ...]
    [--scenario success|failure|rate_limited|server_error|expired_artifact]
    [--project PATH] --confirm-mock [--json]                      # mocked execution, gated
```

Without `--confirm-mock`, `mock-run` only builds and shows the dry-run
plan (identical to `plan`) - nothing executes. No `factory meshy
generate`/`live`/`upload`/`connect`/`login` command exists, and none will
until a future, separately-approved phase.

## Error model

`policy_blocked`, `budget_exceeded`, `unknown_cost`,
`kill_switch_disabled`, `live_execution_not_approved`, `invalid_request`,
`task_failed`, `task_timeout`, `rate_limited`, `server_error`,
`artifact_missing`, `artifact_expired`, `download_failed`,
`invalid_artifact`, `validation_failed`, `preview_failed`,
`receipt_failed` - represented as `{"error_code", "message"}` dicts
throughout, matching `factory.blender_adapter`'s own checks/errors-list
convention rather than a proliferation of custom exception classes.

## Retry policy

No automatic retry anywhere in this phase, for any error. A rate-limited
or server-error submission fails exactly once; the adapter's result
always carries `automatic_retry_performed: false`. A future Phase 47B
may add a bounded, explicitly human-confirmed retry - not built here.

## No-network rule

No `socket`/`requests`/`httpx`/`aiohttp`/`urllib` import exists anywhere
in `factory.meshy_models`/`factory.meshy_mock_transport`/
`factory.meshy_adapter` (statically verified by
`tests/test_meshy_adapter_safety.py`'s AST scan). Every CLI command and
every mocked lifecycle scenario is additionally proven, at test time, to
still succeed with `socket.socket`/`subprocess.run`/`subprocess.Popen`
monkeypatched to raise.

## Credential deferral

No credential is read anywhere in this phase. There is no
`os.environ.get`/`os.getenv` call for a Meshy API key, no `.env` load,
and no `LiveMeshyCredentialProvider` (it does not exist - a future Phase
47B would add one, separately). A fake `MESHY_API_KEY` environment
variable set during a test is proven never to leak into any command's
output.

## Phase 47B boundary

Nothing in this phase authorizes a real API call. `live_execution_allowed`
is hardcoded `False` everywhere; `config/future_cloud_tools.json`'s
Meshy kill switch stays `false`, untouched by this phase.

**Update - Phase 47B is now complete:** `factory.meshy_http_transport.HttpMeshyTransport`
(built new, never derived from `MockMeshyTransport`), a real
`LiveMeshyCredentialProvider`, a persistent credit ledger
(`factory.meshy_ledger`), and a one-shot approval model
(`factory.meshy_live_approval`) all now exist - see
`docs/meshy-live-transport.md`. This does **not** mean a real call has
happened or is authorized: every Phase 47B test uses a fake transport,
`config/meshy_policy.json`/`config/future_cloud_tools.json` remain
byte-identical, and the first real live call still requires a separate,
explicit human approval (an armed one-shot approval record, both
kill-switch flags flipped, and `--confirm-live`) that no code path in
this repo can grant by itself.

## Limitations

- `InMemoryCreditLedger` has no cross-process persistence - "daily"/
  "monthly" totals are only ever totals within one Python process.
- Timeline/artifact-history integration is designed for, but not wired
  into, `factory.project_timeline`/`factory.artifact_history` this phase.
- Only Text-to-3D is modeled; Image-to-3D/Multi-Image-to-3D/existing-mesh
  upload remain a future Phase 47C, pending the version-path ambiguity
  `docs/meshy-current-research.md` flagged.
- The prompt privacy hook is a fixed keyword list, not a PII scanner -
  it recommends review, it does not guarantee detection.

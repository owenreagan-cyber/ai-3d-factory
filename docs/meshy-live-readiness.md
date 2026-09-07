# Live Transport Readiness Review (Phase 47A.5)

**Research/inspection date: 2026-09-07.** This is architecture and policy
review only - it makes **zero** Meshy API calls, reads **zero**
credentials, and enables **zero** execution. It re-verifies Phase 46.6's
`docs/meshy-current-research.md` (research date 2026-09-06) against
current public Meshy documentation and designs (without implementing) the
exact contract a future, separately-approved Phase 47B would need.

    Policy Approved -> Mocked Adapter (47A) -> Live Transport Readiness
    Review (this checkpoint) -> Separate 47B Approval ->
    One Controlled Real API Call

Nothing here changes `config/meshy_policy.json` or
`config/future_cloud_tools.json` - both remain byte-for-byte as Phase
46.6/47A left them. **Phase 47B remains NOT APPROVED.**

## 1. Existing Phase 47A architecture (as found, before any change)

- **Request model** (`factory.meshy_models.build_text_to_3d_request()`):
  Text-to-3D only; fields `request_type`/`prompt`/`prompt_hash`/`model`/
  `mode`/`target_polygon_count`/`output_format`/`target_formats`/
  `ultra_mode`/`texture_resolution`/`estimated_credits`/`reference_ids`/
  `network_required`/`live_execution_allowed`/`dry_run`.
  `DEFAULT_AI_MODEL = "meshy-7"` is an explicit, overridable parameter,
  never silently hardcoded past a request.
- **Mock transport interface** (`factory.meshy_mock_transport`):
  `MeshyTransport(ABC)` with `submit_task()`/`get_task()`/
  `download_artifact()`; only `MockMeshyTransport` exists - no
  `HttpMeshyTransport`, not even a skeleton.
- **Task-state model**: `MESHY_TASK_STATUSES = ("PENDING", "IN_PROGRESS",
  "SUCCEEDED", "FAILED", "CANCELED")` - Meshy's real vocabulary. A
  Factory-only `ARTIFACT_STATES = ("available", "expired", "missing")`
  layered on top of the real `expires_at` field.
- **Provenance model**: built in `meshy_adapter.plan_text_to_3d_request()`
  - `tool`/`tool_model_version`/`factory_phase_version`/`request_type`/
  `prompt_hash`/`prompt_record`/`reference_ids`/
  `reference_source_license_metadata`/`input_fingerprints`/
  `human_approver`/`cost_estimate`/`configured_cost_cap`/
  `execution_confirmation`/`mock`/`live_api_used`/
  `commercial_policy_status`.
- **Receipt model**: built in `meshy_adapter.run_mock_text_to_3d_request()`
  - `meshy_task_id`/`meshy_task_type`/`ai_model`/`requested_target_formats`/
  `model_urls`/`consumed_credits`/`created_at`/`started_at`/`finished_at`/
  `expires_at`/`status`/`task_error`/`human_approver`/
  `cost_estimate_before_request`/`configured_cost_cap_at_request_time`/
  `execution_confirmation`/`input_fingerprint`/`output_artifact_paths`/
  `output_fingerprints`/`formats`/`validation_state`/`preview_state`/
  `warnings`/`printability_result_if_returned`/`repair_operations_if_any`/
  `human_review_state`/`mock_execution`/`live_api_used`/`credits_spent`/
  `money_spent`/`commercial_policy_status`/`no_automatic_print`. Written
  only with an explicit `project_dir` (`<project>/generated/meshy_receipt.json`
  + `<project>/generated/meshy/mock_concept.stl`), never into `examples/`.
- **Budget gate** (`check_budget()`): reads `config/meshy_policy.json`'s
  real credit caps (25/100/150/500) directly; `estimated_credits is None`
  always blocks (`unknown_price_behavior: "block"`); an `InMemoryCreditLedger`
  exists but is deliberately unpersisted - its totals reset every process.
- **Policy/kill-switch gate** (`check_policy_gate()`): joins
  `meshy_approval.evaluate_meshy_gate()`; keeps `mock_execution_allowed`
  and `live_execution_allowed` as two separate booleans, never one -
  `live_execution_allowed` is hardcoded `False` with no code path to flip
  it.
- **Known gaps for live transport** (all correctly left undone by 47A,
  per its own spec): no `HttpMeshyTransport`, no credential provider/read,
  no persistent ledger, no host allowlist/download-security enforcement,
  no bounded-polling-against-real-time logic (the mock never sleeps), no
  one-shot approval record, no `project_timeline`/`artifact_history`
  integration.

## 2. Text-to-3D live endpoint (re-verified 2026-09-07)

| | Phase 46.6 said | Re-verified today | Changed? |
|---|---|---|---|
| Submit | `POST /openapi/v2/text-to-3d` | **Confirmed**: `POST /openapi/v2/text-to-3d` | No |
| Retrieve | not explicitly captured | **New finding**: `GET /openapi/v2/text-to-3d/:id` | Filled in |
| Submit response body | assumed a full task object | **Correction**: `{"result": "<task_id>"}` only - a bare string, not a task object | **Yes - material** |
| `model_urls` formats | `glb`/`obj`/`fbx`/`stl`/`usdz`/`3mf` | Confirmed, plus `mtl` (companion to `obj`) and per-format keys may be entirely absent for a non-requested format | Refined |
| `expires_at` field | assumed present (inferred from Image-to-3D schema) | **Not found in the Text-to-3D task schema fetched today** - `created_at`/`started_at`/`finished_at` are documented; `expires_at` was not listed among Text-to-3D's core fields | **Flag, not resolved** - see "Remaining blockers" |
| Default `ai_model` | `"meshy-7"` (this repo's own default) | Actual API default is `"latest"`, with `meshy-5`/`meshy-6`/`meshy-7`/`latest` as the documented enum | **Design note**, not a blocker (47A's explicit-parameter policy already avoids relying on any default) |
| `mode` field | preview/refine | Confirmed **two separate API calls to the same endpoint**, distinguished by `mode`; refine requires `preview_task_id` from a completed preview task | Confirmed + refined |

Full request/response field list (required/optional, types, ranges) is
now captured verbatim in this document's source citations below - see
`docs.meshy.ai/en/api/text-to-3d` (fetched 2026-09-07, high confidence).

**Why the `expires_at` gap matters:** Phase 46.6 inferred `expires_at`
from the *Image-to-3D* response schema and called it "representative of
the task model generally." Today's direct fetch of the *Text-to-3D*
schema specifically did not surface it among the core fields listed.
This does not necessarily mean the field is absent (documentation pages
are not always exhaustive), but it means **Phase 47B must verify
`expires_at`'s actual presence in the real Text-to-3D response before
relying on it** for the "expired artifact" failure path - do not assume
it exists just because 47A's mock fixtures include it.

## 3. Authentication contract (re-verified 2026-09-07)

- `Authorization: Bearer <key>` header - confirmed.
- Key format: `msy_<random>` prefix - **new, more precise finding** (Phase
  46.6 did not capture the prefix).
- Keys are created/managed from a dashboard; **shown exactly once** at
  creation ("You will not be able to see this API key value again...
  even Meshy team members cannot view or recover revoked API keys for
  you") - a material operational detail for whoever configures
  `MESHY_API_KEY`: losing it means generating a new key, not recovering
  the old one.
- Multiple keys per account are supported and tracked separately, but
  **no fine-grained (read-only/resource-scoped) permission model was
  found** - every key is effectively account-wide. This resolves one of
  Phase 46.6's 9 unknowns: scoped keys in the sense of "separate keys you
  can create and revoke independently" exist; scoped keys in the sense of
  "limited-permission keys" do not.
- HTTPS enforced; plain HTTP receives a `301 Moved Permanently` redirect
  - confirmed unchanged.
- Revocable at any time from the dashboard - confirmed unchanged.

**Recommended Factory credential strategy (unchanged from Phase 46.6,
now confirmed against current docs):** `MESHY_API_KEY` read from the
environment **only**, and only after every local gate below has already
passed - never from a project file, receipt, log, CLI JSON output, doc,
or git history.

## 4. Recommended `HttpMeshyTransport` design (NOT implemented)

A future, minimal, Meshy-specific transport - never a generic HTTP
client wrapper:

```
class HttpMeshyTransport(MeshyTransport):
    def __init__(self, credential_provider: LiveMeshyCredentialProvider, *, timeout_seconds: float = 30.0): ...
    def submit_task(self, request: dict) -> dict: ...      # POST /openapi/v2/text-to-3d
    def get_task(self, task_id: str) -> dict: ...          # GET  /openapi/v2/text-to-3d/{task_id}
    def download_artifact(self, model_url: str, destination: Path) -> Path: ...
```

- **HTTP client choice**: whichever HTTP library this repo already
  depends on for something else should be preferred over adding a new
  dependency; if none exists, `httpx` (widely used, has first-class
  timeout/redirect controls) is a reasonable minimal choice - **this
  document does not add the dependency**, that decision belongs to
  Phase 47B's own implementation, made with the actual repo state at
  that time.
- **Timeouts**: a short, explicit connect timeout (e.g. 10s) and a
  separate, explicit read timeout (e.g. 30s) for `submit_task`/`get_task`
  (small JSON payloads); a longer, explicit timeout for
  `download_artifact` (mesh files can be tens of MB) - never an
  unbounded/default timeout.
- **TLS**: certificate verification always on (never `verify=False`);
  rely on the HTTP library's default trust store.
- **Headers**: `Authorization: Bearer <key>` (from the credential
  provider, read exactly once per call, never cached to a file) and
  `Content-Type: application/json` on submit; no other headers needed
  per the documented contract.
- **Response validation**: parse the response as JSON and validate it
  against the exact field names in section 2 above before touching
  anything else; a response missing `result` (submit) or `status`/`id`
  (get_task) is a `invalid_request`-class error, not a silent partial
  success.
- **Redirect policy**: do not follow redirects automatically for the API
  calls themselves (the API is documented as always-HTTPS; a redirect
  response from `api.meshy.ai` itself would be unexpected and should be
  treated as an error, not silently followed) - the 301-on-HTTP behavior
  is only relevant if a caller mistakenly uses `http://`, which this
  transport should simply never do (hardcode `https://api.meshy.ai`,
  never accept a caller-supplied base URL).
- **Artifact download policy**: only ever download a URL that appears
  verbatim in a `model_urls`/`texture_urls` value from a `get_task()`
  response for the task this transport itself submitted - never an
  arbitrary caller-supplied URL (see host allowlist, below).
- **Maximum artifact size**: an explicit cap (e.g. 200 MB, comfortably
  above any plausible single-mesh-plus-textures download) enforced via a
  streamed download with a running byte count, aborting if exceeded -
  never trust a `Content-Length` header alone.
- **Allowed hosts / signed URL handling**: see section 5.

## 5. Host allowlist (SSRF-safe design)

Two distinct classes of URL this transport ever contacts:

1. **API calls** - always exactly `https://api.meshy.ai`, hardcoded, never
   parameterized from any request/response field.
2. **Artifact downloads** - the `model_urls`/`texture_urls` values Meshy's
   own API returns. These are very likely **signed CDN URLs on a
   different host than `api.meshy.ai`** (common for object-storage-backed
   asset delivery), so a naive `host == "api.meshy.ai"` allowlist would
   break real downloads. **This document could not determine the exact
   CDN host(s) Meshy uses without a real API response to inspect - `EXTERNAL
   VERIFICATION REQUIRED` before Phase 47B: the first real call's own
   response should be logged (URL host only, never the full signed URL
   with its query-string token) so a real allowlist can be derived from
   an actual example rather than guessed.**

Until that real host is known, the safest **design** (not yet
implementable with certainty) is:

- Only ever download a URL that (a) uses `https://`, and (b) was
  returned by this transport's own immediately-prior `get_task()` call
  for the task this transport itself submitted - never a URL from any
  other source (a receipt, a log, a user-supplied argument, a webhook
  payload from an unverified source).
- No redirect-following during artifact download, or at most one
  redirect hop, re-validated against the same "must it look like a
  Meshy/CDN asset URL" check - never an open-ended redirect chain.
- No `*.com`/arbitrary-HTTPS allowance under any circumstance - this is
  exactly the SSRF-style unsafe-downloader shape the spec prohibits.

## 6. Credential provider design (NOT implemented)

```
class LiveMeshyCredentialProvider:
    def get_api_key(self) -> str: ...   # reads os.environ["MESHY_API_KEY"] lazily, once, in memory only
    def __repr__(self) -> str: return "LiveMeshyCredentialProvider(key=<redacted>)"
```

- Reads `MESHY_API_KEY` from the environment **only when called**, and
  only ever called after every gate in section 8's locked order has
  already passed.
- Never logs, persists, serializes to JSON, or includes the key value in
  any exception message it raises (a wrapping `try/except` at the call
  site must re-raise a redacted error, never let a raw
  `KeyError`/exception carrying the key propagate).
- `MockCredentialProvider` (test-only, already implicit in how 47A's
  tests avoid any real provider) returns a fixed fake string for tests
  that need to prove the *shape* of credential handling without ever
  touching `os.environ["MESHY_API_KEY"]` for real.

## 7. First live request - exact fields

| Field | Value | Reasoning |
|---|---|---|
| `prompt` | `"A simple rounded piggy bank concept with no copyrighted characters, logos, text, or third-party references."` | Neutral, explicitly non-infringing per the spec's own suggested prompt; matches `INPUT_CLASS_POLICY["text_prompt"]`'s lowest-privacy-risk classification |
| `mode` | `"preview"` | Cheapest, simplest terminal artifact; no `refine` (texture) step needed to prove the pipeline |
| `ai_model` | `"meshy-7"` | Latest model family, matches this repo's existing `DEFAULT_AI_MODEL`; **explicitly pinned, never `"latest"`** - a request must be reproducible/auditable, and Meshy's own `"latest"` value is a moving target that would make two "identical" requests silently diverge over time |
| `ultra_mode` | `false` | Keeps cost at 20 credits, not 25 - lowest-cost valid Meshy-7 configuration found |
| `target_formats` | `["stl"]` | STL is directly available as a preview-task output per the documented `model_urls` schema (section 2) - no risky format-conversion pipeline is needed for the very first call, resolving the spec's "output format for first live call" question: **STL is genuinely native, not something Factory would have to convert** |
| `target_polycount` | not set (Meshy default) | No manufacturing-precision requirement for a first architecture-proving call; an explicit value can be added once real output is inspected |
| `model_type` | not set (`"standard"` default) | Smart Topology/lowpoly are not needed to prove the base pipeline |
| `moderation` | left at documented default (`false`) | Not a Factory concern - Meshy's own content-moderation flag, unrelated to Factory's own separate privacy/license policy |

**Estimated first-call credits: 20** (Meshy-7 preview, no ultra mode,
per the re-verified pricing table in section 2/8) - **below** the
approved `max_credits_per_request` cap of 25, with headroom.

## 8. Polling limits (NOT implemented - designed only)

- **Initial poll delay**: 5 seconds after submit (generation is not
  instantaneous; polling immediately would waste a request-per-second
  slot for no benefit).
- **Poll interval**: 5 seconds, fixed (no exponential backoff needed for
  a single bounded first call - backoff matters more under sustained
  load, which a one-shot approval by definition excludes).
- **Maximum polls**: 24 (≈2 minutes of polling at a 5s interval) -
  generous for a single preview-mode Text-to-3D task, which Meshy's own
  marketing describes as a "seconds" operation, while still bounded.
- **Overall deadline**: 2 minutes from first poll (aligned with the poll
  count above) - if not terminal by then, stop polling and report
  `task_timeout`; **do not resubmit** (no idempotency key is documented -
  see section 12 - so a timeout-triggered resubmit could create a second
  billed task for the same request).
- **Terminal success state**: `SUCCEEDED`.
- **Terminal failure states**: `FAILED`, `CANCELED`.
- No unbounded loop under any circumstance; the mock transport's own
  `_MAX_MOCK_POLLS = 5` bound (already implemented in 47A) is the
  architectural precedent this design extends with real wall-clock
  bounds.

## 9. Retry policy (locked, architecturally enforced)

**Exactly one task submission, maximum, per approved request.**

- Submission fails (network error, 4xx other than 429, 5xx) -> stop,
  report the structured error, do not resubmit.
- `429 RateLimitExceeded` / `429 NoMoreConcurrentTasks` -> stop, report
  `rate_limited`, do not resubmit automatically (see section 10).
- Task reaches `FAILED`/`CANCELED` -> stop, report `task_failed`, do not
  resubmit.
- Polling itself fails (network error while polling an already-submitted
  task) -> **keep polling the existing `task_id`** (the task was already
  submitted and may still be billed/running) - only the *submission*
  step is one-shot; polling failures should retry the read-only
  `get_task()` call (bounded by the same overall deadline in section 8),
  since re-reading status costs nothing and creates no duplicate task.
- Artifact download fails -> stop, report `download_failed`; **do not
  resubmit the generation task** to get a new URL - the task already
  succeeded and was billed; a failed download is a Factory-side/network
  problem, not grounds for a second paid generation.
- A human-initiated retry after any of the above requires a **new**
  one-shot approval (section 15) - there is no code path that reuses a
  consumed/failed approval automatically.

This must be architecturally enforced (e.g. the live-run function simply
contains no retry loop around `submit_task()` at all - not a retry loop
with `max_retries=1`, an *absence* of a loop), matching 47A's own
`automatic_retry_performed: False` field, which Phase 47B should keep and
always report `False` for the submission step specifically.

## 10. Rate-limit handling

- `429` (either cause) -> return a structured `rate_limited` result
  immediately. No sleep. No automatic re-request. No second paid
  submission.
- No `Retry-After` header is documented (confirmed today - the rate-limits
  page itself states no retry guidance is given), so there is no reliable
  wait-time to honor even if automatic retry were desired - reinforcing
  why manual, human-re-initiated retry is the only safe design.
- Queue-hit (`NoMoreConcurrentTasks`) only applies to Text-to-3D,
  Image-to-3D, Text-to-Texture, and Remesh (confirmed today) - relevant
  context if a future phase adds more request types, irrelevant to a
  single Text-to-3D call today.

## 11. Persistent budget ledger design (NOT implemented)

**Location recommendation:** a new, gitignored, machine-local
`state/meshy_spend_ledger.json` at the repo root - **not** inside
`config/` (which is committed, non-secret *policy*, not runtime spend
history - mixing the two risks accidentally committing real spend data)
and **not** inside a single project's `generated/` directory (the
`daily_cap`/`monthly_cap` caps are Factory-wide across every project, so
a per-project ledger file would fragment the exact totals `check_budget()`
needs to sum across all projects; `per_project_cap` is already handled by
filtering one global ledger's entries by `project_id`, as 47A's
`InMemoryCreditLedger.total_for_project()` already does in memory).
`projects/*` is already fully gitignored in this repo, and there is no
existing repo-root "machine state" directory - `state/` would be a new,
narrowly-scoped, `.gitignore`d addition alongside `config/`/`projects/`.

**Ledger entry fields** (matching the spec's list, and reusing 47A's
`InMemoryCreditLedger.record()` field names so 47B can be a drop-in
persistent replacement, not a redesign):

```
request_id, task_id, project (id or path), timestamp, request_type,
model, estimated_credits, actual_credits, status, policy_version,
approval_reference
```

**Status vocabulary**: `reserved`, `submitted`, `succeeded`, `failed`,
`unknown` (the spec's own suggested set - no additional states needed for
a single request type).

## 12. Reservation/reconciliation design (NOT implemented)

```
1. check_budget() against current ledger totals (as 47A already does)
2. append a "reserved" entry for estimated_credits, BEFORE any network call
3. submit_task() (the one real network call that can spend money)
4. on success: update the entry to "submitted" with the real task_id
5. poll to a terminal state
6. on SUCCEEDED: reconcile - update actual_credits from consumed_credits,
   status="succeeded"
7. on FAILED/CANCELED/timeout/error: status="failed" or "unknown" -
   NEVER delete the reservation; a human must reconcile it manually if
   the real consumed_credits (if any) can't be confirmed (e.g. a network
   error during polling that leaves the task's real outcome unknown)
```

This ordering - **reserve before submit** - exists specifically to close
the race the spec calls out: without it, two near-simultaneous
`live-run` invocations could both pass `check_budget()` against the same
stale "10/100 credits used" reading before either submission lands,
together exceeding the cap. Reserving synchronously (single-process,
single-writer - see below) before the network call closes that window.

**Why "conservatively retain reservation until manually reconciled"
matters:** per section 2's `expires_at` gap and section 8's "no
idempotency key" finding (section 12 below), an unknown-outcome failure
(e.g. the process crashes between `submit_task()` succeeding and the
reservation being updated) must never silently disappear from the
ledger - an under-counted ledger is exactly how an accidental over-cap
spend would happen on a *second* run that trusts a ledger total that's
missing a real, already-billed task.

## 13. Budget concurrency

- **Recommendation: atomic write via temp-file-then-`os.replace()`**,
  the same pattern `project_store.save_json()` should already use for
  every other write in this repo (confirm at 47B implementation time) -
  never a database. A single-user, single-machine tool with a handful of
  writes per real call does not justify SQLite or a lock daemon.
- **File locking**: not strictly required for a genuinely single-process
  CLI invocation model (the spec's own one-shot-approval design already
  prevents concurrent `live-run` invocations from being a *meaningful*
  attack surface, since a second invocation needs its own separate
  one-shot approval token first) - but a simple advisory lock (e.g.
  `fcntl.flock` on POSIX, guarded by a `try/except` that fails closed -
  "could not acquire the ledger lock" blocks the run rather than
  proceeding unlocked) is cheap insurance worth adding at implementation
  time, given the reservation-race concern in section 12.
- **Corruption recovery**: if `state/meshy_spend_ledger.json` fails to
  parse, **fail closed** - treat it as `budget_exceeded`/blocked rather
  than silently starting from an empty ledger (an empty ledger would
  under-count real spend and could allow an over-cap request).

## 14. Kill-switch evaluation order (locked)

Exactly the order the spec specifies - network/credential access as late
as possible:

```
1. parse request                              (no I/O)
2. local policy check   (meshy_approval.evaluate_meshy_gate())
3. local budget check   (persistent ledger + config/meshy_policy.json)
4. kill-switch check    (config/future_cloud_tools.json AND policy.execution_enabled - BOTH required true)
5. explicit per-run confirmation (--confirm-live)
6. only then: read MESHY_API_KEY (LiveMeshyCredentialProvider.get_api_key())
7. only then: construct HttpMeshyTransport / make the network call
```

Every one of steps 2-5 failing must short-circuit before step 6 - the
credential is never read merely to "check if it's configured" earlier in
the sequence; that check itself belongs at step 6, folded into the first
real attempt to use it (a missing/invalid key surfaces as a
`live_execution_not_approved`-adjacent error at that point, not as an
earlier existence probe).

## 15. One-shot approval design (NOT implemented)

```
{
  "approval_id": "<uuid4>",
  "scope": "first_live_call",
  "prompt_hash": "<sha256 of the exact pinned prompt in section 7>",
  "max_credits": 20,
  "request_type": "text_to_3d",
  "project": null | "<disposable project path>",
  "created_at": "<iso8601>",
  "expires_at": "<iso8601, e.g. created_at + 1 hour>",
  "consumed_at": null
}
```

- Unconsumed and unexpired -> eligible for exactly one `live-run`.
- The *first* submission attempt (step 6/7 above reached) marks
  `consumed_at` in the same atomic write as the ledger reservation
  (section 12/13) - crash-safe: if the process dies after consuming the
  approval but before confirming submission succeeded, the approval
  stays consumed (never silently reusable) and the ledger reservation
  stays "reserved" pending manual reconciliation (section 12) - a human
  reviews both together rather than the system guessing.
- A second call, whether after success or failure, requires a **brand
  new** approval record - there is no "retry with the same approval"
  path, by design, matching the spec's "prevents accidental duplicate
  spend" requirement.
- Pinning `prompt_hash` to the exact section-7 prompt means this
  particular approval record could not silently be reused for a
  different prompt even if the code had a bug that tried - a second
  belt-and-suspenders check, not the primary control (the primary
  control is single-use consumption).

## 16. Artifact destination

- **Disposable project**: `projects/meshy-live-smoke-test/` -
  gitignored (already covered by this repo's blanket `projects/*`
  `.gitignore` rule) - never a committed `examples/` project.
- **Raw provider artifact preserved before any transformation**:
  `projects/meshy-live-smoke-test/generated/meshy/raw/<task_id>.stl`
  (STL is the real native format for this first call - see section 7 -
  so "raw" and "processed" are the same file for this specific first
  call; the `raw/` vs `processed/` split still exists in the directory
  design so a *future* call using a non-STL-native format, or a future
  Blender-cleanup step, has a place to put its own separately-preserved
  original without redesigning the layout).
- **Processed/Factory-facing copy**: `projects/meshy-live-smoke-test/generated/meshy/processed/<task_id>.stl`
  (identical bytes for this first call; the distinction matters once a
  future format needs conversion).
- **Receipt**: `projects/meshy-live-smoke-test/generated/meshy_receipt.json`
  - additive to 47A's existing mock receipt shape (section 17), never a
  competing second schema.

## 17. Real receipt additions (additive only - 47A's mock schema unbroken)

Every 47A mock receipt field stays; these are the only additions:

```
mock_execution: false                (was true for every 47A receipt)
live_api_used: true                  (was false)
estimated_credits                    (already named "cost_estimate_before_request" in 47A - reused, not duplicated)
actual_credits                       (already named "consumed_credits" in 47A - reused)
ledger_entry_request_id              (new - links to the persistent ledger entry, section 11)
provider_model                       (already named "ai_model" in 47A - reused)
api_version                          ("v2" - new, since 47A never needed to record an API version it never called)
submit_status                        (new - "succeeded" | "failed", distinct from final_status which is the terminal task status)
final_status                         (already present as the task's own "status" field - reused)
download_status                      (new - "succeeded" | "failed" | "not_attempted")
artifact_fingerprint                 (already named "output_fingerprints" in 47A - reused)
validation_status                    (already named "validation_state" in 47A - reused)
preview_status                       (already named "preview_state" in 47A - reused)
live_call_approval                   (new - the consumed one-shot approval_id, section 15)
kill_switch_state                    (new - a snapshot of config/future_cloud_tools.json's enabled value AND policy.execution_enabled at call time, for audit)
```

No secret ever appears in any of the above.

## 18. Provenance additions (additive to `factory.meshy_approval`'s field lists)

`REQUIRED_REQUEST_PROVENANCE_FIELDS`/`REQUIRED_OUTPUT_PROVENANCE_FIELDS`
(Phase 46) already anticipate `human_approver`/`cost_estimate`/
`configured_cost_cap`/`execution_confirmation` and the output-side
Meshy-task fields - **no change to those lists is needed**. New fields a
live provenance object specifically needs beyond what mocked provenance
already has:

```
provider = "meshy"
live_api_used = true
endpoint = "https://api.meshy.ai/openapi/v2/text-to-3d"
api_version = "v2"
credential_source = "environment"
credential_value = <NEVER RECORDED, NEVER LOGGED, NEVER SERIALIZED>
live_call_approval_id
ledger_reservation_id
download_timestamp
provider_metadata = {task type, texture_urls if any, thumbnail_url if any}  # sanitized: no signed-URL query tokens persisted past the download step
human_review_required = true
automatic_print_allowed = false
```

## 19. Timeline / artifact-history integration (recommendation only)

Additive `project_timeline` event once a real persistent receipt exists:

```
{"category": "meshy", "label": "Meshy concept generated", "severity": "info" | "warning",
 "date": <receipt's finished_at>, "detail": {"task_id", "artifact_fingerprint", "ai_model", "consumed_credits"}}
```

Severity `"warning"` if `validation_state != "PASS"`, matching every
other timeline event's existing severity convention in this repo (never
a Meshy-specific severity scale). The **receipt remains the source of
truth** - the timeline event is a read/summary of it, never
independently authoritative, exactly like every other Phase 40 event
type already documented in `docs/architecture.md`'s Aggregation Layer
Convention.

## 20. Factory validation path

If STL is the real, natively-returned format (confirmed for this
specific first-call configuration in section 7) -> **validate
immediately** via the existing `factory.validators.mesh_validate.validate_mesh()`,
exactly as 47A's mocked path already does - no new validator, no
conversion step, no risk. If a *future* request configuration only
returns GLB/OBJ (e.g. a texture-only refine result where STL wasn't
requested), Phase 47B/47C must **not** claim "Factory validated" through
an unproven conversion pipeline - it should instead download/preserve the
raw artifact and provenance, and explicitly report
`validation_status: "unavailable_pending_conversion_path"` rather than
silently skip or fake a validation result. This first call's chosen
`target_formats: ["stl"]` avoids that problem entirely for now.

## 21. Blender handoff boundary

Future relationship only, **not built here, not combined with Phase 48**:

```
Meshy raw concept (STL) -> Phase 45's qualified Blender fixture adapter
    (cleanup/organic-mesh repair, still fixture-gated, still no project
     execution approval) -> Factory validation (re-run on the
     Blender-adjusted mesh, never trusting the prior pass)
```

Phase 45 already proved headless Blender execution is architecturally
sound (`docs/blender-adapter.md`); it still requires its own separate
project-execution approval, entirely independent of Meshy's approval
chain. Nothing in this checkpoint changes that.

## 22. Nine research unknowns - status after re-verification

| # | Unknown | Status |
|---|---|---|
| 1 | Whether failed/canceled tasks consume credits | **Still unknown** - not found in the pricing page fetched today either. Does not block 47B (the ledger's "reserve before submit, retain on unknown outcome" design in section 12 already treats this conservatively regardless of the answer). |
| 2 | Whether unused monthly credits roll over or expire | **Still unknown.** Does not block 47B (irrelevant to a single 20-credit test call against a 500-credit monthly cap). |
| 3 | Image-to-3D/Multi-Image-to-3D exact API version path | **Resolved for Image-to-3D**: confirmed `/openapi/v1/image-to-3d` consistently for both create and retrieve - not a mixed v1/v2 inconsistency, just a genuinely different version than Text-to-3D's v2. Multi-Image-to-3D's exact path remains unconfirmed. **Does not block 47B** (Phase 47B uses Text-to-3D only). |
| 4 | Multi-Color Print's exact credit cost | **Resolved**: 10 credits (confirmed today, `docs.meshy.ai/en/api/pricing`). Irrelevant to 47B's scope either way. |
| 5 | Whether the "private" content setting opts out of AI training or only public visibility | **Resolved**: opts out of public visibility only (Terms of Use Section 3.2); training use is governed separately by Section 2.9 and applies to non-Enterprise customers regardless of the private setting. **Does not block 47B** - Phase 46's policy already treats training exposure conservatively regardless of this setting, and a single neutral test prompt has no privacy-sensitive content. |
| 6 | Exact data retention duration for uploads/results | **Still unknown** (no fixed timeframe found; "as long as we deem necessary," with a user-initiated deletion right). **Does not block 47B**'s single test call, but should inform any later decision to route real student/classroom-adjacent content through Meshy (which the Factory's locked privacy rule already forbids regardless). |
| 7 | Physical-object vs. digital-model resale distinction | **Still not found** - re-checked directly against the Terms of Use text today; no distinguishing clause exists. **Does not block 47B** (a first architecture-proving test call has no commercial/resale component at all - see section 7's neutral prompt). **Does block any future commercial-use decision** until resolved by direct human legal review, exactly as Phase 46.6 already flagged. |
| 8 | Whether scoped (limited-permission) API keys exist | **Resolved**: multiple independently-revocable keys exist; no fine-grained permission scoping exists. **Does not block 47B** (the credential-provider design in section 6 does not depend on scoped keys). |
| 9 | Webhook payload exact field shape | **Partially resolved**: payload is "the task object" (same shape as `get_task()`'s response, already documented in section 2) - **but a new, more material finding**: **no signature/HMAC verification mechanism is documented for webhook delivery**, meaning a webhook receiver cannot cryptographically confirm a payload actually came from Meshy. **This is a reason to prefer polling over webhooks for Phase 47B's first call** (polling requires no public-facing endpoint and has no spoofing surface); webhooks remain a possible *later* optimization only after a receiver-side verification strategy (e.g. re-fetching the task by ID via the authenticated GET rather than trusting the webhook body directly) is designed. |

None of the 9 unknowns block the specific, narrow first live call
specified in section 7. The `expires_at` gap discovered in section 2
(not one of the original 9, a new finding from this checkpoint) is the
one genuinely new item that should be resolved by inspecting the real
first response rather than assumed from the mock fixtures.

## 23. Phase 47B readiness checklist

| Item | Status |
|---|---|
| API endpoint verified | **True** (section 2, re-confirmed today) |
| Auth contract verified | **True** (section 3, re-confirmed today, more precise than before) |
| Text-to-3D request contract verified | **True** (section 2/7) |
| Credit estimate known | **True** (20 credits, section 7) |
| Cost caps configured | **True** (25/100/150/500 credits, already approved) |
| Persistent ledger designed | **True** (section 11-13; not implemented) |
| Kill switch designed | **True** (section 14; already exists, both layers) |
| Credential provider designed | **True** (section 6; not implemented) |
| No-retry policy locked | **True** (section 9) |
| Polling bounded | **True** (section 8) |
| Rate-limit policy locked | **True** (section 10) |
| Download allowlist designed | **Partially true** (section 5 - API host is locked; the artifact-CDN host cannot be finalized until a real response is inspected) |
| Artifact containment designed | **True** (section 16) |
| Receipt schema ready | **True** (section 17 - additive, backward-compatible) |
| Provenance schema ready | **True** (section 18 - additive) |
| First prompt selected | **True** (section 7) |
| One-shot approval model ready | **True** (section 15; not implemented) |
| Commercial/privacy policy acceptable | **True for this narrow test call** (neutral prompt, no commercial claim, `commercial_use_verified` stays `false`) |
| **Phase 47B user approval recorded** | **False - and must stay false at this checkpoint** |

## 24. Remaining blockers before 47B implementation begins

1. **`expires_at` presence in the real Text-to-3D response** - verify
   against the first real response rather than the mock fixture's
   assumption (section 2).
2. **Artifact-CDN host** - cannot be allowlisted with certainty until a
   real `model_urls` value is inspected (section 5); this is a
   one-time, low-risk piece of information to capture *from* the first
   call itself, but the transport's host-validation logic should be
   written defensively (documented above) rather than wait-and-see.
3. **Explicit human approval of this document's specific proposal**
   (this exact prompt, this exact 20-credit estimate, this exact
   disposable project path, this exact one-shot approval design) -
   the spec is explicit that completing this review is not that
   approval.
4. **`MESHY_API_KEY` configuration** - must be set by the human in their
   own environment before Phase 47B could ever reach step 6 of section
   14; this document does not check for or request it.
5. **`config/future_cloud_tools.json`'s `tools.meshy.enabled`** and
   `config/meshy_policy.json`'s `approval.execution_enabled` both still
   need an explicit human/administrative action to become `true` - no
   code change proposed by this checkpoint does that.

## 25. Tests

None added - this checkpoint is docs-only. A pure ledger-entry-shape or
one-shot-approval-shape dataclass was considered but not added: the part
of each design that actually carries risk (atomic-write races, crash-safe
consumption, corruption recovery) cannot be meaningfully tested without
also building the real file I/O this checkpoint must not implement, so a
no-I/O pure-shape test now would give false confidence without reducing
Phase 47B's actual implementation risk. The existing 2675-test suite was
re-run unchanged (see verification below) to confirm this checkpoint
introduced no regressions.

## 26. Verification

- `git status --short` was clean before this checkpoint began (only
  `70785a8` at HEAD).
- Full `pytest` re-run: **2675 passed** (unchanged - no code was
  modified).
- `factory meshy status` / `factory meshy policy` / `factory meshy
  approval-status` / `factory meshy plan --prompt "..."` all re-run
  successfully, fully offline.
- `config/meshy_policy.json` and `config/future_cloud_tools.json`
  confirmed byte-for-byte unchanged (empty `git diff`) after this
  checkpoint.
- No `MESHY_API_KEY`/`.env` read at any point (this checkpoint's own
  process never referenced either).
- No Meshy generation/task/upload/download call was made - every fetch
  in this checkpoint targeted a `docs.meshy.ai`/`www.meshy.ai` **public
  documentation** page, never `api.meshy.ai` or an account-specific URL.
- Phase 47B approval remains absent from every config file.

## 27. Exact recommended next action

1. A human reads this document (and, per section 24 item 3 and Phase
   46.6's own recommendation, the full Meshy Terms of Use text directly)
   and decides whether to approve the exact first-call specification in
   section 7.
2. If approved, a **separate** future phase (Phase 47B) implements
   `HttpMeshyTransport`, `LiveMeshyCredentialProvider`, the persistent
   ledger, and the one-shot approval record - per this document's
   designs, reviewed again at implementation time.
3. Only after that implementation is itself reviewed does
   `config/future_cloud_tools.json`'s kill switch and
   `config/meshy_policy.json`'s `execution_enabled` get explicitly
   flipped, and only then does a `--confirm-live` invocation become
   possible.

No command above was executed by this checkpoint. **Phase 47B remains
NOT APPROVED.**

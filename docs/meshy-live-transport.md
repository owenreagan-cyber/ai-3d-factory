# Live Meshy Transport Implementation, No Live Call (Phase 47B)

Phase 47B implements the complete real Meshy HTTP transport path -
`HttpMeshyTransport`, `LiveMeshyCredentialProvider`, a persistent local
spend ledger, and a one-shot live-call approval model - while
**preserving the hard stop before the first real network generation
call.** Every design decision here follows `docs/meshy-live-readiness.md`
(Phase 47A.5), which re-verified Meshy's public API contract and
designed (without implementing) everything this phase now builds.

**Phase 47B implementation completion != first live Meshy call
approval.** Nothing in this phase enables execution, flips either kill
switch, or contacts a real network host. `config/meshy_policy.json` and
`config/future_cloud_tools.json` are unchanged by this phase.

## Locked live-execution order

```
1. parse local request                              (no I/O)
2. local policy check    (factory.meshy_approval.evaluate_meshy_gate())
3. local budget check    (factory.meshy_ledger.SpendLedger + config/meshy_policy.json)
4. kill-switch check     (config/future_cloud_tools.json AND policy.approval.execution_enabled - BOTH required)
5. one-shot approval check (factory.meshy_live_approval.find_eligible_approval())
6. explicit --confirm-live
7. only then: read MESHY_API_KEY (LiveMeshyCredentialProvider.get_api_key())
8. only then: construct HttpMeshyTransport
9. only then: make the network call (submit_task())
```

Every one of steps 2-6 failing short-circuits before step 7 -
architecturally, not just by convention: `factory.meshy_live_adapter.run_live_text_to_3d_request()`
never even constructs a credential provider until every earlier check
has passed. `tests/test_meshy_live_adapter.py` has five dedicated tests,
one per gate, each proving a spy credential provider's `get_api_key()` is
never called when that gate blocks.

`factory.meshy_live_adapter.check_kill_switch()` is the **first** module
in this repo allowed to read `config/meshy_policy.json`'s raw
`approval.execution_enabled` field directly - `factory.meshy_approval.evaluate_meshy_gate()`
deliberately hardcodes that field `False` in its own output (Phase 46's
own invariant, so *that* module can never be tricked into reporting
execution enabled); checking whether a human has manually flipped the
real value is precisely this phase's job.

## Modules

- **`factory.meshy_http_transport`** - the *only* module in this repo
  that may open a real network connection. `HttpMeshyTransport`
  implements `submit_task()`/`get_task()`/`download_artifact()` against
  the real, hardcoded `https://api.meshy.ai` using Python's standard
  library (`urllib.request`) - no new dependency was added (none existed
  in `pyproject.toml`). `LiveMeshyCredentialProvider`/`MockCredentialProvider`
  live here too.
- **`factory.meshy_ledger`** - `SpendLedger`, a persistent, local,
  append-preserving credit ledger at `state/meshy_spend_ledger.json`
  (gitignored). Exposes the same `total_for_project()`/`total_today()`/
  `total_this_month()` interface Phase 47A's in-memory
  `InMemoryCreditLedger` already established, so
  `factory.meshy_adapter.check_budget()` enforces real caps against it
  with zero duplicated budget logic.
- **`factory.meshy_live_approval`** - one-shot, single-use, short-lived
  live-call approval records at `state/meshy_live_approvals.json`
  (gitignored). Pinned to an exact prompt hash/model/credit-cap/project;
  consumed atomically on the first submission attempt; never reusable
  after success or failure.
- **`factory.meshy_live_adapter`** - `plan_live_text_to_3d_request()`
  (fully offline) and `run_live_text_to_3d_request()` (the gated
  orchestrator enforcing the locked order above). Contains **no**
  network-capable code itself - it only ever constructs
  `HttpMeshyTransport`/`LiveMeshyCredentialProvider` after every gate has
  passed, and accepts injectable `credential_provider_factory`/
  `transport_factory`/`sleep_fn` parameters purely for test isolation.

## Host allowlist / SSRF hardening

- API calls always target the hardcoded `https://api.meshy.ai` - never a
  caller-supplied base URL.
- Artifact downloads reject `localhost`/loopback/link-local (including
  the cloud-metadata address `169.254.169.254`)/private RFC1918
  ranges/non-`https` schemes outright (`validate_artifact_url()`). The
  real artifact-CDN host could not be determined without a real API
  response (`docs/meshy-live-readiness.md` section 5), so this is the
  documented, defensive fallback: it rejects known-bad hosts rather than
  guessing a specific allowlisted good one.
- Redirects are never followed automatically for API calls (treated as a
  protocol error); an artifact download follows **at most one** redirect,
  re-validated against the same host checks before being followed.
- Every download is byte-capped (200 MB), written atomically (temp file
  + `os.replace`), and the destination path is always Factory-chosen -
  never derived from a remote filename/`Content-Disposition` header, so
  there is no path-traversal surface from a malicious response.

## Credential handling

`LiveMeshyCredentialProvider.get_api_key()` reads `MESHY_API_KEY` from
the environment lazily - only when called, and only ever called after
every gate above has passed. Never loads `.env`/`dotenv`. Never appears
in `repr()`, an exception message, a receipt, a log, or any CLI JSON
output - `tests/test_meshy_live_safety.py` proves this with a fake env
var set and checked absent from every command's output.

## Persistent spend ledger - reservation before submission

```
1. check_budget() against the ledger's current totals
2. reserve() - append a "reserved" entry, BEFORE any network call
3. submit_task() - the one real network call that can spend money
4. mark_submitted() - real task_id recorded
5. poll to a terminal state
6. on SUCCEEDED: mark_succeeded() - reconcile actual_credits
7. on FAILED/CANCELED/timeout/error: mark_unknown() - NEVER delete the
   reservation; a human reconciles manually if the real outcome is
   uncertain
```

This ordering closes the race an unreserved check would allow: two
near-simultaneous `live-run` invocations could otherwise both pass
`check_budget()` against the same stale total before either submission
lands. `SpendLedger` uses an advisory file lock (`fcntl.flock`, fails
closed if unavailable/contended) plus atomic temp-file-then-`os.replace()`
writes for every mutation.

## One-shot approval

`factory meshy approve-live-once --prompt "..." --max-credits 20
[--project PATH] [--expires-in SECONDS]` creates exactly one local,
single-use record. It is **not** blanket execution permission - it is
scoped to that exact prompt hash, model, credit cap, and (optionally)
project. The first submission attempt consumes it atomically; a second
call, whether after success or failure, requires a brand-new approval.
`factory meshy revoke-live-approval APPROVAL_ID` revokes one explicitly.

## `factory meshy live-plan` / `factory meshy live-run`

`live-plan` is fully offline: it never reads a credential, never
reserves budget, never consumes an approval - it only reports whether
each gate currently passes. `live-run --confirm-live` is the gated call;
without every earlier gate satisfied it is blocked before step 7 above.
Exactly one `submit_task()` call ever happens per approval - there is no
retry loop around it, not even a bounded one. Polling is bounded (24
attempts, 5s interval, ~2 minutes) with an injectable `sleep_fn` so tests
never actually wait.

## Receipt (additive to Phase 47A's mock schema)

Every Phase 47A mock receipt field is preserved; live receipts add
`mock_execution: false`, `live_api_used: true`, `provider`, `api_version`,
`endpoint`, `ledger_reservation_id`, `live_call_approval`,
`submit_status`, `download_status`, `kill_switch_state` - no secret ever
appears in any of them. Written only with an explicit `--project`
(`generated/meshy/raw/<task_id>.stl` + `generated/meshy/processed/<task_id>.stl`
+ `generated/meshy_receipt.json`), with collision protection - never
overwriting an existing artifact.

## Factory validation / preview

Regardless of provider claims (e.g. a mock or real `printability` field),
the real `factory.validators.mesh_validate.validate_mesh()` and
`factory.previews.render_preview.render_preview()` always run against the
downloaded artifact - no Meshy-specific validator or visual-QA subsystem
exists.

## Limitations

- Ledger + approval consumption are each individually atomic (single
  JSON file, temp-write + `os.replace()`), but are **not** a single
  cross-file transaction - a crash between the two writes is handled
  conservatively (the approval, once consumed, stays consumed; the
  ledger reservation, once written, is never silently released) but is
  not a true two-phase commit.
- `_is_blocked_host()` does not perform DNS resolution before validating
  a hostname - it defends against a literal private/loopback IP in the
  URL, not a hostname that itself *resolves* to one.
- The real Meshy artifact-CDN host is still unknown until a real
  response is inspected (`docs/meshy-live-readiness.md` section 24) -
  `validate_artifact_url()` is a defensive rejection of known-bad hosts,
  not a positive allowlist of a specific good one.
- File locking uses `fcntl` (POSIX only); on a platform without it, the
  ledger fails closed (`LedgerLockError`) rather than proceeding
  unlocked.
- No cross-process/cross-run integration test exists against a real
  Meshy endpoint - by design, this phase performs zero real network
  calls.

## Remaining before Phase 47B's first real call

1. Verify `expires_at`'s presence in the real Text-to-3D response.
2. Inspect a real `model_urls` value to learn the actual artifact-CDN
   host.
3. Explicit human approval of the exact first-call specification
   (`docs/meshy-live-readiness.md` section 7).
4. `MESHY_API_KEY` configured by the human in their own environment.
5. Both kill-switch flags (`config/future_cloud_tools.json` and
   `config/meshy_policy.json`) explicitly flipped by a human.

None of the above happened in this phase. **Phase 47B (the first real
live call) is NOT approved.**

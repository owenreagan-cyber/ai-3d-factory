# Meshy Cloud / Cost / License / Privacy Approval Gate (Phase 46)

`factory.meshy_approval` is the Factory's formal approval and policy gate
for future Meshy cloud usage. **This phase is policy and approval
infrastructure only.** It does not implement Meshy, does not call it,
does not import a Meshy SDK, does not contact any network endpoint, does
not read or validate a Meshy credential, and does not upload anything
anywhere - no exception.

    Meshy availability != Meshy approval
    Meshy approval     != API execution approval
    Meshy output       != manufacturing ready
    Meshy printability analysis != Factory validation
    Meshy repaired mesh != human approved
    Meshy-generated artifact != print approved

Every future Meshy artifact must still enter:

    provenance -> artifact receipt -> cleanup/manufacturing adaptation ->
    Factory validation -> preview -> human review -> slicer review ->
    human print decision

Automatic printing remains impossible.

## Why this phase exists

Phase 16 (`docs/meshy-approval-gate.md`) wrote down, in advance, the
checklist a future Meshy implementation must satisfy - a design and
safety scaffold, never code that calls Meshy. Phase 43
(`docs/engine-registry.md`) recorded Meshy as a permanent, cloud-gated
registry entry. Phase 44 (`docs/tool-qualification.md`) explicitly never
qualifies it. Phase 46 turns that scaffold into one concrete,
machine-readable, auditable policy/approval model - a Factory-wide,
deterministic answer to "is Meshy allowed for this Factory, under what
exact conditions, and what must Phase 47 prove before the first real API
call?" - still without adding a single line of code that could ever
contact Meshy.

## What Phase 46 does not do

- Does not call Meshy, `api.meshy.ai`, or any Meshy web endpoint.
- Does not make any HTTP/HTTPS request, open a socket, or use a browser.
- Does not read or validate a Meshy API key (or any other credential).
  It does not even check whether one *exists* - see "Credential policy"
  below.
- Does not upload an image, mesh, or prompt.
- Does not spend money, inspect an account balance, or authenticate
  anywhere.
- Does not install an SDK or dependency.
- Does not flip `config/future_cloud_tools.json`'s `tools.meshy.enabled`
  kill switch, and does not set `execution_enabled=true` in its own
  policy record under any combination of flags.
- Does not begin Phase 47 (the actual Meshy adapter).
- Does not count merely being implemented as human approval - see
  "Approval lifecycle" below.

## Gate model

`factory.meshy_approval.evaluate_meshy_gate()` returns one deterministic
dict, joining three sources - never rewriting any of them:

- `config/future_cloud_tools.json` (Phase 16's kill switch -
  `tools.meshy.enabled`/`status`, read via `factory.future_cloud_tools`).
- `factory.engine_registry`'s Meshy record (Phase 43 - capability
  metadata, `cloud_gate_required=True`).
- `config/meshy_policy.json` (this phase's own new, committed, non-secret
  policy file - cost/credit caps, license posture, and the approval
  record).

```json
{
  "tool_id": "meshy",
  "policy_version": 1,
  "gate_status": "needs_cost_policy",
  "cloud_use_allowed": false,
  "api_execution_allowed": false,
  "human_approval_required": true,
  "approval_recorded": false,
  "cost_policy": {"...": "..."},
  "license_policy": {"...": "..."},
  "privacy_policy": {"...": "..."},
  "provenance_policy": {"...": "..."},
  "blockers": ["Cost cap not configured.", "..."],
  "kill_switch": {"enabled": false, "execution_enabled": false},
  "network_used": false,
  "credentials_read": false,
  "money_spent": false,
  "no_automatic_print": true
}
```

## Gate states

```
disabled | policy_incomplete | needs_cost_policy | needs_license_policy |
needs_privacy_policy | needs_provenance_policy | needs_human_approval |
approved_for_future_api_integration | revoked | blocked
```

`gate_status` walks a fixed priority order - cost, then license, then
human approval - reporting the *next* unmet requirement; `blockers`
lists *every* currently-unmet requirement at once, matching the CLI's
"BLOCKERS" list. `"disabled"` and `"blocked"` are reserved, closed-
vocabulary values for a future explicit admin-disable action and a
genuine structural failure (a corrupted policy file), respectively -
neither is reached by this phase's own default state.

**`approved_for_future_api_integration` means only that Phase 47 may
begin implementing a Meshy adapter against this policy - it never means
Meshy API calls are globally authorized.** Actual execution still
requires `kill_switch.execution_enabled=true`, which no code path in this
repo can set, in any phase up to and including this one.

## Kill switch

Two independent, layered gates, both read-only from this phase's point
of view except the two explicit writers below:

- `config/future_cloud_tools.json`'s `tools.meshy.enabled` (Phase 16) -
  the original, still-authoritative kill switch. Stays `false` forever
  in this phase; nothing here writes to that file.
- `config/meshy_policy.json`'s `approval.execution_enabled` (this phase)
  - a second, independent gate. Hardcoded `false` in every code path
    `factory.meshy_approval` defines; there is no flag, CLI option, or
    combination of `--ack-*` acknowledgements that can set it `true`.
    Flipping it is explicitly out of scope for Phase 46.

## Cost and credit policy

`config/meshy_policy.json`'s `cost_policy` defines the *structure* a
human must fill in - no currency amount is ever invented by this phase.
Every cap starts `null`; `unknown_price_behavior` defaults to `"block"`
(if a future phase can't determine or estimate a request's cost safely,
it must not call Meshy). A `credit_policy` sub-object mirrors the same
null-by-default pattern for credit-based billing
(`max_credits_per_request/project/day/month`). A policy counts as
"configured" once at least one real cap (`per_request_cap`/
`per_project_cap`/`daily_cap`/`monthly_cap`) is set by a human, directly
in the file.

## License and commercial-use policy

`license_policy.unknown_license_behavior` defaults to
`"block_commercial_use"` - Meshy commercial rights are never claimed safe
unless explicitly documented and approved
(`terms_reviewed`/`commercial_use_verified`). This does not block a
purely experimental/internal concept study; the distinction between
concept study, commercial product, personal/gift use, and classroom use
is preserved by `APPROVAL_SCOPES` (`policy_only`, `concept_generation`,
`image_upload`, `mesh_upload`, `commercial_use`) - Phase 46 itself only
ever records `policy_only`.

### Reference-board license -> cloud-upload mapping

`classify_reference_cloud_upload_permission(license_value)` maps each of
`factory.reference_board`'s own `LICENSES` values to a cloud-upload
classification - a pure function, consulted by no real upload path
(none exists yet) and never mutating `reference_board.json`:

| License | Cloud upload |
| --- | --- |
| `public_domain`, `cc_by`, `cc_by_sa`, `commercial_allowed` | allowed |
| `cc_by_nc` | non-commercial concept study only |
| `unknown`, `personal_use`, `proprietary`, `custom` | blocked by default |

An `unknown` license defaults to **`not_uploadable_to_cloud`** - never
inferred as safe from a `design_reference_only` usage intent, which is a
separate permission (what the reference is *for*, not what rights it
carries to leave the machine).

## Privacy and data-class policy

This project may be used in a classroom context (see
`examples/multipart-classroom-sign/`,
`examples/future-organic-models/`). `DATA_CLASSES` and
`classify_data_class_cloud_permission()` model - never scan or infer -
which category a human-supplied input might fall into:

- **Forbidden for cloud upload by default:** `private_photo`,
  `student_data`, `student_photo`, `personal_identifier`,
  `confidential_project`, `commercial_secret`,
  `third_party_copyrighted_reference`, `unknown_source`.
- **Allowed by default:** `public_reference`, `user_created_reference`,
  `licensed_reference`.

This is policy metadata only - `factory.meshy_approval` never opens,
scans, or fingerprints a real file to determine its class; a human (or a
future review step) assigns it.

### Input classes

`INPUT_CLASS_POLICY` covers `text_prompt` (lowest privacy risk, still
requires provenance), `single_image` (license/privacy review required),
`multi_image` (every image requires its own review - none inherits
approval from another), and `existing_mesh` (ownership/license review
required, since an uploaded mesh may itself carry third-party rights).

## Provenance policy

`REQUIRED_REQUEST_PROVENANCE_FIELDS`/`REQUIRED_OUTPUT_PROVENANCE_FIELDS`
define the field lists a future request/result must carry - tool
identity, timestamp, request type, sanitized prompt record, reference
IDs and their license metadata, input fingerprints, human approver, cost
estimate and cap, execution confirmation, and (for output) Meshy task ID,
output paths/fingerprints, formats, cost, license posture, warnings,
printability/repair results, and human review state. This phase defines
the *structure* only - no real task ID or receipt is ever generated,
since no request is ever made.

## Credential policy

No code in `factory.meshy_approval` reads `os.environ`, calls
`os.getenv`, or references the literal string `MESHY_API_KEY` - it
doesn't even check whether a Meshy credential environment variable
*exists*, let alone its value. If a future phase's approval-record model
ever needs to record that a credential exists (never its value), that is
explicitly deferred, not built here. No API key is ever stored in a
project file, written to a receipt, logged, printed, committed, or
included in JSON output - because no code path here reads one at all.

## Printability policy lock

`PRINTABILITY_POLICY_LOCK` restates, as data every gate/CLI output
carries verbatim:

- Meshy printability analysis != Factory validation.
- Meshy repair != Factory repair approval.
- Meshy Auto Split != Factory multipart approval.
- Meshy 3MF output != slicer-ready.
- Any future Meshy result must still pass Factory artifact tracking,
  mesh validation, dimension checks, manufacturing checks, preview,
  human review, and slicer readiness - exactly like every other mesh in
  this repo.

## Approval lifecycle

`factory meshy approve-policy --ack-cost --ack-license --ack-privacy
--ack-provenance [--approved-by NAME]` is the only way to record human
approval. It:

- Requires **all four** acknowledgement flags - partial acknowledgement
  is refused, not partially recorded.
- Requires a cost cap to already be configured and `license_policy.
  terms_reviewed` to already be `true` in `config/meshy_policy.json` -
  approving an empty policy is refused.
- Records `approval_scope="policy_only"` (the only scope this phase ever
  writes) and a UTC timestamp.
- **Cannot set `execution_enabled=true`** - there is no flag for it.

`factory meshy revoke-policy [--reason TEXT]` reverses a recorded
approval - marks it revoked, disables the future-execution gate, and
preserves the prior approval as history (`approval.revocation_history`)
rather than discarding it. Local file only - no network, no remote
revocation.

Merely shipping Phase 46 is **not** human approval:

```
Human Meshy cloud approval:
NOT RECORDED

Cloud execution:
DISABLED
```

## Phase 47 readiness

`evaluate_meshy_phase47_readiness()` checks: policy model complete, cost
cap configured, unknown-cost behavior defined, license posture reviewed,
privacy policy defined, provenance requirements defined, cloud-upload
categories defined, human policy approval recorded, kill-switch design
present, and execution still disabled. `ready_for_phase47=True` means
only "this policy scaffold is complete enough for a future phase to
begin implementing the Meshy adapter against it" - **never** "safe to
call Meshy now."

## Engine registry / Preview Board / Project Health integration

- `factory.engine_registry`'s canonical Meshy record (Phase 43) is
  unchanged; `factory meshy status` joins it with this phase's policy at
  runtime, never rewriting it.
- Preview Board gained one compact global line
  (`meshy_policy_summary` - a field deliberately separate from
  `tool_environment_summary`, which `factory.project_health` also
  consumes) - never a per-project card, never a network call during
  board generation.
- `factory.project_health`'s `health_score` is entirely untouched by this
  phase - a mechanical, OpenSCAD-only project must not become "less
  healthy" because Meshy is ungated.
- No project timeline or artifact history event is created merely
  because this global policy exists - only a future real Meshy project
  execution would create provenance/artifact events.

## CLI

```
factory meshy status                                                    # read-only
factory meshy policy [--json]                                           # read-only, full detail
factory meshy approval-status [--json]                                  # read-only, approval only
factory meshy approve-policy --ack-cost --ack-license --ack-privacy \
  --ack-provenance [--approved-by NAME]                                 # explicit write
factory meshy revoke-policy [--reason TEXT]                             # explicit write
```

No `generate`, `upload`, `connect`, or `login` subcommand exists, and
none will until a future, separately-approved phase.

## JSON contract

`factory meshy status --json` / `factory meshy policy --json` return a
`safety` block proving every claim machine-readably:

```json
{
  "network_used": false,
  "credentials_read": false,
  "data_uploaded": false,
  "money_spent": false,
  "printer_contacted": false,
  "automatic_print_allowed": false
}
```

## Safety proof, not just assertion

`tests/test_meshy_approval_safety.py` monkeypatches `socket.socket`,
`subprocess.run`/`Popen`, and `os.system` to raise an `AssertionError` if
called, then runs every gate/CLI/classification function under that
guard - a passing test suite is direct proof no code path here opens a
socket or spawns a process, not merely a source-text scan. A separate
static scan proves no forbidden import (`socket`, `requests`, `httpx`,
`aiohttp`, `urllib`, `http`) appears anywhere in `factory.meshy_approval`,
and this repo has no HTTP client library installed at all.

## Limitations

- Cost/license policy values require a human to actually edit
  `config/meshy_policy.json` (or a future CLI convenience) - this phase
  builds the structure and the refusal-to-approve-an-empty-policy
  safeguard, not a guided setup wizard.
- No JSON schema file validates `config/meshy_policy.json`'s shape
  (matching `config/future_cloud_tools.json`'s existing schema-less
  convention) - malformed hand-edits are caught only by
  `evaluate_meshy_gate()`'s own defensive `.get()` reads, which degrade
  to `needs_cost_policy` rather than crashing.
- `"disabled"` and `"blocked"` are defined but unreached vocabulary
  values in this phase - reserved for a future explicit admin-disable
  action and a genuine structural failure, respectively.

## No authority, no automatic action

This module never approves a project, never sets `human_approved` or
`print_ready`, never contacts a printer or slicer, and never generates
G-code. It is read-only except for two explicit, human-invoked writes to
one local, non-secret config file. See `docs/meshy-approval-gate.md`,
`docs/engine-registry.md`, `docs/tool-qualification.md`,
`docs/reference-board.md`, `docs/roadmap.md` Phase 46/47,
`docs/architecture.md`, and `AGENT.md`.

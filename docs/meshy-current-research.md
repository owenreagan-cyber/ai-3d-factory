# Meshy Current External Research (Phase 46.6)

**Research date: 2026-09-06.** This document is a snapshot of Meshy's
*public* documentation/pricing/terms/privacy pages as of that date - it is
**not** verified against the live API (no API call, login, credential
read, upload, or spend occurred to produce it) and it **is not** a Meshy
policy approval. See `docs/meshy-policy.md` for the Factory's own gate,
and `docs/meshy-approval-gate.md` for the original Phase 16 checklist.
Nothing in this document changes `config/meshy_policy.json` or
`config/future_cloud_tools.json` - both remain exactly as Phase 46/46.5
left them: cost caps unset, human approval not recorded, execution
disabled.

Re-verify before relying on this for a real integration - pricing/terms
pages change without notice and this repo has no automated way to detect
that drift.

## Source inventory

| # | Source | Title | Confidence |
|---|---|---|---|
| 1 | https://docs.meshy.ai/en/api/pricing | Pricing \| Meshy Docs | High (primary) |
| 2 | https://docs.meshy.ai/en/api/text-to-3d | Text to 3D API \| Meshy Docs | High (primary) |
| 3 | https://docs.meshy.ai/en/api/image-to-3d | Image to 3D API \| Meshy Docs | High (primary) |
| 4 | https://docs.meshy.ai/en/api/authentication | Authentication \| Meshy Docs | High (primary) |
| 5 | https://docs.meshy.ai/en/api/rate-limits | Rate Limits \| Meshy Docs | High (primary) |
| 6 | https://docs.meshy.ai/en/api/quick-start | Quick Start \| Meshy Docs | High (primary) |
| 7 | https://docs.meshy.ai/en/api/changelog | Changelog \| Meshy Docs | High (primary) |
| 8 | https://docs.meshy.ai/en/webapp/guides/3d-model/auto-split | Auto Split \| Meshy Docs | High (primary) |
| 9 | https://www.meshy.ai/pricing | Meshy Official Pricing | High (primary) |
| 10 | https://www.meshy.ai/terms-of-use | Terms of Use | High (primary) |
| 11 | https://www.meshy.ai/privacy-policy | Privacy Policy | High (primary) |
| 12 | https://www.meshy.ai/acceptable-use-policy | Acceptable Use Policy | High (primary) |
| 13 | https://help.meshy.ai/en/articles/15724182-is-meshy-safe-and-private-data-and-training-faq | "Is Meshy safe and private" FAQ | Medium-high (official help center, not the ToS/Privacy Policy itself) |
| 14 | Aggregated web-search snippets (g2.com, various "Meshy pricing 2026" blogs) | Secondary cross-check only | Low - used only to cross-check, superseded by items 1/9 wherever they conflicted |

No Meshy API endpoint, login page, or account page was contacted. No
`MESHY_API_KEY`/`.env` value was read (not even checked for existence).

## Current Meshy API/model versions

- Latest model: **Meshy 7**, introduced mid-August 2026, higher-fidelity
  geometry than Meshy 6; supports `ultra_mode` across Text-to-3D,
  Image-to-3D, Multi-Image-to-3D, and Retexture. (Source: changelog.)
- **Meshy T1 was deprecated September 1, 2026**; Smart Topology is
  offered as `ai_model: "meshy-t2"`. (Source: changelog.)
- API base URL: `https://api.meshy.ai`; versioned paths seen: `/openapi/v2/text-to-3d`
  (current) and `/openapi/v1/image-to-3d` (the Image-to-3D quick-start
  example used a v1 path while Text-to-3D used v2 - **conflict/inconsistency,
  not resolved**: it's unclear whether Image-to-3D also has a v2 path or
  whether v1 is still current for that endpoint specifically. EXTERNAL
  VERIFICATION REQUIRED before Phase 47A implementation.)

## Pricing/credit findings

Meshy API access is **pay-as-you-go on top of a subscription**: a paid
plan (Pro or above) is required for API access at all; Free-plan users
get no API access. (Source: pricing pages 1/9.)

| Plan | Monthly | Credits/mo | API access | Asset ownership |
|---|---|---|---|---|
| Free | $0 | 100 | No | CC BY 4.0 (attribution required) |
| Pro | $20 ($240/yr) | 1,000 | Yes | Own the assets |
| Premium | $40 | not found | not found | Own the assets |
| Ultra | $100 | not found | not found | Own the assets |
| Studio | $70 (1 seat) + $10/mo/seat | not found | not found | Own the assets |
| Enterprise | custom | custom | Yes | Own the assets; contractually excluded from AI training |

**Conflict noted:** an earlier aggregated web-search snippet described
plans as "Free/Pro ($20)/Studio ($60/seat)/Enterprise," while the primary
pricing page (source 9) lists five paid tiers (Pro/Premium/Ultra/Studio/Enterprise)
with different numbers. The primary page (9) is treated as authoritative;
the search-snippet numbers are not used below.

### Operation cost table (source 1, `docs.meshy.ai/en/api/pricing`)

| Operation | API available? | Credits | Notes | Source | Confidence |
|---|---|---|---|---|---|
| Text-to-3D preview, Meshy-6/low-poly | Yes | 20 | | 1 | High |
| Text-to-3D preview, Meshy-7 | Yes | 20 (+5 for `ultra_mode`) | | 1 | High |
| Text-to-3D preview, Smart Topology (Meshy T2) | Yes | 5 | | 1 | High |
| Text-to-3D refine (texture 2k/4k) | Yes | 10 | | 1 | High |
| Text-to-3D refine (texture 8k) | Yes | 15 | | 1 | High |
| Image-to-3D, Meshy-6, no texture | Yes | 20 | | 1 | High |
| Image-to-3D, Meshy-6, with texture | Yes | 30 | | 1 | High |
| Image-to-3D, Meshy-6, 8K texture | Yes | 35 | | 1 | High |
| Image-to-3D, Meshy-7 | Yes | same as Meshy-6 (+5 ultra) | | 1 | High |
| Image-to-3D, Smart Topology | Yes | 5 / 15 / 20 (no/with/8K texture) | | 1 | High |
| Multi-Image-to-3D | Yes | same schedule as Image-to-3D | +5 credits `ultra_mode` (added Sep 1 2026) | 1, 7 | High |
| Remesh | Yes | 5 | | 1 | High |
| UV Unwrap | Yes | 5 | | 1 | High |
| Auto-Rigging | Yes | 5 | | 1 | High |
| Convert | Yes | 1 | | 1 | High |
| Resize | Yes | 1 | | 1 | High |
| Animation | Yes | 3 | | 1 | High |
| Analyze Printability | Yes | **Free (0)** | | 1 | High |
| Repair Printability | Yes | 10 | | 1 | High |
| Multi-Color Print | Yes | not found in source 1's table (endpoint exists - see capability matrix) | | 2? | Low - **EXTERNAL VERIFICATION REQUIRED** |
| Auto Split | **No (web-app only)** | 10 credits per split/re-split (per secondary source; not independently confirmed via a primary Meshy Docs pricing citation) | Not in the API pricing table at all - consistent with it being a web-app-only feature | 6, 8 | Medium |
| Creative Lab Lamp prototype/build | Yes | 30 / 6 (changed Aug 2026) | Unrelated to core manufacturing workflow | 7 | High |

**Not documented anywhere found** (mark `unknown` per spec, do not infer):
whether a **failed** task consumes credits, whether credits expire, and
whether monthly credits roll over. `unknown_price_behavior: "block"` in
the Factory's existing policy is exactly the correct conservative default
given this gap.

### Rate/concurrency limits (source 5)

| Tier | Requests/sec | Max queued/concurrent tasks |
|---|---|---|
| Pro | 20 | 10 |
| Premium | 20 | 30 |
| Ultra | 20 | 100 |
| Studio | 20 | 20 (**conflict**: an earlier aggregated search snippet said 60 for Studio - the primary rate-limits page (source 5) says 20; source 5 is treated as authoritative here since it is the primary documentation page) |
| Enterprise | 100 | 50 (customizable) |

Two distinct 429 conditions: a **request-hit** (`RateLimitExceeded`, too
many req/s) and a **queue-hit** (`NoMoreConcurrentTasks`, too many
concurrent tasks). Queue-counted endpoints: Text-to-3D, Image-to-3D,
Text-to-Texture, Remesh (source 5/quick-start).

Webhooks exist (max 5 active per account) as an alternative to polling
(source: search result citing `docs.meshy.ai/en/api/webhooks` - not
independently re-fetched; **medium confidence**, recommend a primary
re-check before Phase 47 relies on webhook payload shape).

## API capability matrix (web-app vs. API kept distinct)

| Capability | Web app | API | Endpoint/path | Input | Output | Cost | Source | Confidence |
|---|---|---|---|---|---|---|---|---|
| Text-to-3D | Yes | Yes | `POST /openapi/v2/text-to-3d` (preview + refine modes) | prompt (≤800 chars), model_type, ai_model, target_polycount, topology, texture params | glb/obj/fbx/stl/usdz/3mf | see table above | 2 | High |
| Image-to-3D | Yes | Yes | `/openapi/v1/image-to-3d` (version per quick-start example - **verify v2 exists**) | image(s), ai_model, texture params | glb/obj/fbx/stl/usdz/3mf, texture_urls, thumbnails | see table above | 3, 6 | Medium-high |
| Multi-Image-to-3D | Yes | Yes | `/en/api/multi-image-to-3d` (linked, exact REST path not independently confirmed) | multiple images | same as Image-to-3D | same schedule | 6, 7 | Medium |
| Meshy 7 (model family) | Yes | Yes | `ai_model: "meshy-7"` param on Text/Image/Multi-Image/Retexture | - | higher-fidelity geometry | +5 credits ultra_mode | 2, 7 | High |
| Smart Topology | Yes | Yes | `model_type: "smart-topology"`, `ai_model: "meshy-t2"` | target_polycount 100-15,000 | triangle topology, "natively separated parts" | 5 / 15 / 20 credits | 2, 1 | High |
| Remesh | Yes | Yes | `should_remesh` param / dedicated remesh endpoint (linked in quick-start) | target_polycount 100-300,000, topology, decimation_mode | remeshed geometry | 5 credits | 2, 1 | High |
| Target polygon count | Yes | Yes | `target_polycount` param | integer | - | included in above | 2 | High |
| Separated/native parts | Yes | Yes (via Smart Topology only) | as above | - | multi-part mesh | included in Smart Topology cost | 2 | Medium-high |
| Auto Split | Yes | **No - web-app only** | none found; absent from the API quick-start endpoint list entirely | - | STL parts, "assembled" or "on plate" layout | not in API pricing table | 6, 8 | High (absence confirmed by checking the full quick-start endpoint list) |
| 3MF output | Yes | Yes | `target_formats: ["3mf"]` on Text/Image-to-3D | - | 3mf file | included in generation cost; must be explicitly requested (`"3mf is only included when explicitly specified"`) | 2 | High |
| Multi-Color Print | Yes | Yes | `POST` documented at `docs.meshy.ai/en/api/multi-color-print`; accepts `model_url` (glb/fbx) or `input_task_id` | textured mesh | multi-color 3MF | not found in pricing table - EXTERNAL VERIFICATION REQUIRED | search summary (not independently re-fetched at primary source) | Medium |
| Analyze Printability | Yes | Yes | documented at `docs.meshy.ai/en/api/repair-printability`'s sibling page; accepts glb/gltf/obj/fbx/stl via `model_url` | mesh | issue report: non-manifold edges, holes, degenerate faces | **Free** | 1, search summary | Medium-high |
| Repair Printability | Yes | Yes | `docs.meshy.ai/en/api/repair-printability` | mesh (glb/gltf/obj/fbx/stl via `model_url`) | watertight, print-ready mesh | 10 credits | 1, search summary | High |
| Texture generation (Retexture) | Yes | Yes | linked in quick-start ("Retexture") | mesh + texture_prompt/texture_image_url | textured mesh | included in refine-task pricing (10/15 credits) | 2 | High |
| Mesh format conversion | Yes | Yes | "Convert" endpoint (quick-start) | mesh | reformatted mesh | 1 credit | 1 | High |

**Locked interpretation for the Factory (per this checkpoint's mandate,
regardless of what Meshy calls "printable"):** every one of these Meshy
outputs, including a Repair-Printability result or a 3MF from Multi-Color
Print, must still pass Factory's own `mesh_validate`, dimension checks,
manufacturing checks, preview, human review, and slicer readiness before
being treated as usable - this document does not relax that rule.

## Output formats

Confirmed via Text-to-3D/Image-to-3D docs: `glb`, `obj`, `fbx`, `stl`,
`usdz`, `3mf`. **No `.blend` output was found documented anywhere** -
Meshy does not appear to export native Blender files; a `.blend` artifact
in this Factory would have to come from the existing Phase 45 local
Blender adapter, never from Meshy. `target_formats` defaults to "all
formats except 3mf" - 3mf must be explicitly requested.

No documentation found claiming any output format is guaranteed
watertight by default - on the contrary, Analyze Printability's own stated
purpose (checking for "non-manifold edges, holes, degenerate faces")
implies raw generation output is **not** guaranteed watertight, and Repair
Printability is offered specifically to fix that. This directly confirms
the Factory's standing principle: **provider claim ≠ Factory
verification** - Meshy's own docs do not claim otherwise.

Scale/units: not found in any fetched page - `EXTERNAL VERIFICATION
REQUIRED` before assuming any particular real-world unit scale on a
generated model.

## Commercial-use findings (classified per the spec's five categories)

Source: `terms-of-use` (primary, quoted) and `acceptable-use-policy`
(primary, quoted).

- **Ownership of generated output - CLEARLY PERMITTED (paid plans):**
  "Paid plan customers... retain ownership of their generated output";
  Meshy takes only "a non-exclusive, royalty-free, worldwide license to
  reproduce... the User Content" for service-provision purposes (Section
  3.2, terms-of-use).
- **Ownership of generated output - CONDITIONAL (free plan):** Free-plan
  output is licensed to the user under **CC BY 4.0** (attribution
  required); commercial use is allowed under that license, but requires
  crediting Meshy in the listing.
- **Commercial resale of digital models - CLEARLY PERMITTED (paid),
  CONDITIONAL (free, requires attribution):** both quoted and consistent
  across terms-of-use and multiple help-center articles.
- **Resale of physical objects printed from a generated model - NOT
  FOUND / UNCLEAR:** no clause was found distinguishing physical-product
  sale from digital-model sale. The terms only prohibit reselling *the
  Service itself* ("resell or redistribute the Service or access to the
  Service," Section 2.6) - not the generated content. Treat "may a printed
  physical object be sold" as **unclear, not clearly permitted**, until a
  human reviews the full terms text directly (this document's fetches
  were AI-summarized excerpts, not the complete legal text).
- **Third-party IP in uploaded images/prompts - RESTRICTED, user's
  liability:** users must warrant they "have all rights, licenses, and
  permissions needed" for their input and that it "does not infringe...
  any third party rights" (Sections 2.2, 3.4). Generating from copyrighted/
  trademarked material the user doesn't own can void their ability to use
  the output commercially, **regardless of plan**.
- **Warranty on output quality/manufacturability - RESTRICTED (disclaimed):**
  "MESHY DOES NOT REPRESENT OR WARRANT THAT THE SERVICE OR CUSTOMER
  OUTPUT WILL BE ACCURATE, RELIABLE, ERROR-FREE" (Section 7.2) - directly
  supports the Factory's mandatory validation/human-review requirement.
- **AI-training use of input/output - CONDITIONAL, plan-dependent:**
  non-Enterprise (including paid Pro/Premium/Ultra/Studio) content **may**
  be used, anonymized, for future model training "as development
  requires"; **Enterprise** customers are contractually excluded from
  this. A paid-plan "keep content private" option was mentioned in one
  secondary aggregation but **not independently confirmed** against the
  Privacy Policy or Terms of Use text directly - **EXTERNAL VERIFICATION
  REQUIRED** on whether that private toggle actually opts out of training,
  or only controls community-page visibility.

## Generated-output ownership findings

Summarized above - paid-plan ownership is explicit; free-plan is a CC BY
4.0 license, not full ownership. No API-specific ownership carve-out was
found (API-created assets appear to follow the same plan-tier ownership
rule as web-app-created ones, since API access requires a paid plan
anyway).

## Input/reference-rights findings, mapped to the Factory's three-way distinction

The Factory must keep these three permissions distinct - Meshy's own
terms only ever speak to the middle one:

| Permission | What it means | Does Meshy's ToS grant/require it? |
|---|---|---|
| `design_reference_allowed` | May a human look at this image while designing, without uploading it anywhere | Irrelevant to Meshy - purely a Factory-internal permission, unaffected by any Meshy policy |
| `cloud_upload_allowed` | May this specific asset be uploaded to Meshy's servers | Meshy's terms **require** the uploader to already own/be licensed to use the input and warrant no third-party-rights infringement (Sections 2.2/3.4) - Meshy does not grant this permission, it only requires the user to already have it |
| `commercial_derivative_allowed` | May a commercial product be made from Meshy's output on this input | Plan-dependent (paid: yes, subject to the input itself being clean; free: yes under CC BY 4.0 with attribution) - and separately voided if the input itself was infringing, "regardless of plan" |

**Recommendation for Phase 47's representation:** keep these as three
separate boolean/enum fields (never collapse to one), exactly as Phase
46.5 already proposed (`docs/meshy-policy.md` "Phase 46.5"). This
checkpoint does not add them to `reference_board.json` - still a proposal
only.

## Privacy/data findings

- Collected: text/image prompts, "public chats," generated 3D
  models/textures (Privacy Policy, quoted).
- Users "acknowledge and agree" they are authorized by any depicted
  person to have their personal information "publicly displayed" -
  implying Meshy's own privacy posture assumes uploads may become public
  by default in some flows (e.g. a community/discover page), which is a
  meaningfully different risk profile than a private API call. **EXTERNAL
  VERIFICATION REQUIRED**: does an API-created asset default to private,
  or does it require an explicit setting to avoid public listing?
- Retention: **no specific timeframe found** - "as long as we deem
  necessary," with a user-initiated deletion right ("Erase Your Personal
  Data"). Mark retention duration `unknown`.
- Training: plan-dependent, see Commercial-use findings above. Enterprise
  = contractually excluded; everyone else = "may" be used, anonymized.
- Data location: stored on AWS in the United States; EEA transfers use
  "appropriate safeguards (e.g., EU standard contractual clauses)"; PRC
  users' data "would be stored overseas in US." ISO/IEC 27001:2022 and
  SOC 2 certifications claimed (secondary-sourced, not independently
  verified against a certificate).
- No API-specific privacy-policy differences from the general/web-app
  policy were found anywhere.

## Locked Factory privacy rule - unaffected by any of the above

Regardless of anything Meshy's own Privacy Policy or Acceptable Use
Policy permits, the Factory's own policy (`factory.meshy_approval`,
`FORBIDDEN_DATA_CLASSES_BY_DEFAULT`) continues to forbid cloud upload of:
student photographs, student names/identities, student records, private
classroom information, credentials, API secrets, confidential documents,
and unrelated private user files. Meshy's Acceptable Use Policy has **no
special carve-out for classroom/student use** beyond a general prohibition
on sexualized depictions of minors and generic privacy-violation language
- it does not independently protect student data at the level the Factory
already requires, so the Factory's own stricter default remains necessary
and is not weakened by anything found in this research.

## Provenance fields Meshy's API actually exposes

From the Image-to-3D response schema (representative of the task model
generally): `id` (k-sortable UUID), `type`, `model_urls` (per-format),
`texture_urls`, `thumbnail_url(s)`, `created_at`/`started_at`/`finished_at`/`expires_at`
(ms since epoch), `progress` (0-100), `status`
(`PENDING`/`IN_PROGRESS`/`SUCCEEDED`/`FAILED`/`CANCELED`),
`consumed_credits`, `preceding_tasks`, `task_error`. **No `seed` field was
found** - Meshy does not appear to offer reproducible/deterministic
generation via a seed parameter, so provenance cannot record a seed that
doesn't exist.

**Recommended minimum receipt fields for Phase 47A (mocked), reusing
these exact Meshy field names where they exist rather than inventing
parallel ones:**

```
meshy_task_id            (Meshy's "id")
meshy_task_type           (Meshy's "type", e.g. "image-to-3d")
ai_model                  (the requested ai_model, e.g. "meshy-7")
requested_target_formats
model_urls                (as returned - one per format)
consumed_credits
created_at / started_at / finished_at / expires_at   (verbatim from Meshy)
status                   (verbatim Meshy status)
task_error                (verbatim, if present)
human_approver
cost_estimate_before_request
configured_cost_cap_at_request_time
execution_confirmation
input_fingerprint(s)      (Factory-computed, not a Meshy field)
reference_source_license_metadata   (Factory-computed, from reference_board.json)
```

This list already matches `REQUIRED_REQUEST_PROVENANCE_FIELDS`/
`REQUIRED_OUTPUT_PROVENANCE_FIELDS` in `src/factory/meshy_approval.py`
closely - no change to that module is proposed by this checkpoint.

## API limits (restated from above)

Rate limits and queue limits are per the table above; two distinct 429
causes (`RateLimitExceeded` vs `NoMoreConcurrentTasks`). No documented
idempotency-key mechanism was found for POST requests - **retrying a
timed-out request could plausibly create a duplicate paid task**; this is
exactly why the Factory's standing rule ("automatic paid retry disabled
unless explicitly approved") matters and should not be relaxed.

## Failure/retry semantics - recommended Factory handling

No implementation this checkpoint - recommendations only, for a future
Phase 47 to build against:

| Condition | Recommended Factory behavior |
|---|---|
| `429 RateLimitExceeded` | Back off; never auto-retry a paid POST without human confirmation |
| `429 NoMoreConcurrentTasks` | Wait/report; do not queue additional paid requests automatically |
| `5xx` | Treat as failed; do not auto-retry a paid POST; surface to human |
| Timeout while polling | Do not resubmit the generation request (no idempotency key found) - only resume polling the existing `task_id` |
| `status: FAILED` / `task_error` present | Surface verbatim `task_error` to the human; never silently retry |
| `status: CANCELED` | Treat as a deliberate stop, not a failure to retry |
| Partial task (e.g. only some `target_formats` populated) | Treat as incomplete; do not assume missing formats will appear later without checking `status` |
| Expired output URL (`expires_at` passed) | Re-download is not documented as possible without a new task - flag as a data-loss risk if the Factory doesn't archive `model_urls` promptly after `SUCCEEDED` |

## Authentication findings

`Authorization: Bearer <key>` header, keys generated/managed from a
dashboard, non-recoverable after creation, revocable at any time, HTTPS
only (plain HTTP gets a 301 redirect). No scoped/restricted-permission
keys were found documented (keys appear to be account-wide). **Recommended
Factory handling:** environment variable only (e.g. `MESHY_API_KEY`, as
`config/future_cloud_tools.json`'s own notes already say is the only
placeholder that exists); never in project JSON, receipts, artifact
history, logs, CLI JSON output, or git - consistent with Phase 46's
existing credential policy, unchanged by this checkpoint.

## Recommended Phase 47A first request type: **Text-to-3D**

Reasoning:
- **API maturity**: Text-to-3D is the most completely documented endpoint
  found (`/openapi/v2/text-to-3d`, both preview and refine modes fully
  specified); Image-to-3D's exact current path was less clear (v1 example
  vs. Text-to-3D's v2 - see the version conflict noted above).
- **Cost predictability**: fixed, fully-tabulated credit costs (20/5/10/15
  depending on options) with no image-count variability.
- **Privacy**: lowest risk of the input classes (`INPUT_CLASS_POLICY["text_prompt"]`
  in `factory.meshy_approval` already scores it `"privacy_risk": "lowest"`)
  - no image upload, no reference-license review needed for the prompt
  itself (though any *reference imagery a human used to write the prompt*
  is a separate, Factory-internal concern, unaffected by this choice).
- **Provenance**: a text prompt is trivially hashable/sanitizable for
  `prompt_hash_or_sanitized_record`; an uploaded image has more surface
  area to track (fingerprint, license, source).
- **Factory usefulness/validatability**: same downstream artifact shape
  (glb/obj/fbx/stl/3mf) as every other generation path - the Factory's
  existing `mesh_validate`/preview/review pipeline needs no special-casing
  for the input type once a `model_urls.stl` exists.

Image-to-3D remains a reasonable second candidate for a later 47C
capability, once the version-path ambiguity above is resolved and its
image-upload license/privacy review path is designed.

## Proposed cost/credit caps (recommendations only - not written anywhere)

Given: Pro-tier pricing is the cheapest plan with API access ($20/mo,
1,000 credits), and a Text-to-3D preview costs 20-25 credits (Meshy-7,
no ultra mode) or as little as 5 (Smart Topology):

| Field | Current | Proposed (conservative, for initial live testing) | Reasoning | Source |
|---|---|---|---|---|
| `cost_policy.currency` | `null` | `"USD"` | Meshy's own pricing is USD-denominated | 1, 9 |
| `cost_policy.per_request_cap` | `null` | **25 credits** (≈$0.50 at the $20/1,000-credit Pro rate) | Covers one Meshy-7 Text-to-3D preview (20 credits) with headroom; blocks anything larger (e.g. 8K-texture refine) without a separate explicit raise | 1 |
| `cost_policy.per_project_cap` | `null` | **100 credits** (≈$2.00) | Enough for a handful of preview+refine iterations on one project; small enough that an accidental loop can't do real damage before the daily cap also stops it | 1 (derived, not itself documented by Meshy) |
| `cost_policy.daily_cap` | `null` | **150 credits** (≈$3.00) | "Initial live test budget should tolerate only a small number of accidental calls" (spec's own principle) - roughly 6-7 preview-only requests per day | derived from 1, not a Meshy-documented figure |
| `cost_policy.monthly_cap` | `null` | **500 credits** (≈$10.00, half the Pro plan's monthly allotment) | Conservative fraction of the cheapest paid plan's monthly credits, leaving headroom for normal (non-Factory) Meshy account use | derived from 1/9, not Meshy-documented |
| `credit_policy.max_credits_per_request` | `null` | 25 | mirrors `per_request_cap` | - |
| `credit_policy.max_credits_per_day` | `null` | 150 | mirrors `daily_cap` | - |
| `license_policy.unknown_license_behavior` | `block_commercial_use` | **unchanged** | already conservative; nothing in this research argues for loosening it | - |

**These are proposals only - explicitly not written to `config/meshy_policy.json`
by this checkpoint.** All derived-cap numbers (project/daily/monthly) are
this checkpoint's own conservative arithmetic, not figures Meshy itself
publishes - flagged accordingly above. A human should adjust them based on
actual willingness to spend, not treat them as Meshy-mandated minimums.

## Proposed commercial policy: **`commercial_concept_only`**

Not `commercial_disabled` (paid-plan ownership terms are genuinely clear
enough to not need a blanket ban), and not
`commercial_physical_products_allowed_subject_to_terms` (that would be
overstating what was verified - the physical-object-resale question above
is explicitly **unclear**, and this document's fetches were AI-summarized
excerpts, not full legal review of the complete Terms of Use text).
`commercial_concept_only` is the recommended interim category: allow
Meshy-assisted concept generation and internal use immediately, but
require a **separate, explicit case review** (`commercial_requires_case_review`
is a close second choice and arguably more precise - a human should decide
between these two, this checkpoint does not) before treating any
Meshy-derived output as sellable, whether as a digital asset or a printed
physical object.

## Proposed privacy policy: **no change from Phase 46's existing defaults**

Nothing in this research supports loosening `FORBIDDEN_DATA_CLASSES_BY_DEFAULT`.
If anything, the finding that non-Enterprise content "may" train future
models on an unspecified, non-opt-outable basis argues for *keeping*
every classroom/private/unknown-source class blocked, and treating even
`user_created_reference`/`licensed_reference` uploads as things a human
should consciously accept "this may be used to improve Meshy's models"
for, not just "this may be seen by other Meshy users."

## Proposed reference-upload matrix

| Reference class | `design_reference_allowed` | `cloud_upload_allowed` | `commercial_derivative_allowed` | Human review |
|---|---|---|---|---|
| User-created (own photo/drawing) | Yes | Yes, after explicit per-reference approval | Yes, if plan is paid and the reference itself isn't infringing | Required before upload |
| Public-domain | Yes | Yes | Yes | Recommended, not strictly required |
| CC0 | Yes | Yes | Yes | Recommended |
| CC-BY | Yes | Yes, attribution to the *reference's* source still owed independent of Meshy's own CC BY 4.0 (free-plan) terms | Yes, with attribution | Required (verify attribution requirement) |
| Other Creative Commons (CC-BY-SA, CC-BY-NC, etc.) | Yes | Conditional - CC-BY-NC-family licenses likely block `commercial_derivative_allowed` regardless of Meshy's own plan terms | No for NC-family; case-by-case for SA/ND terms | Required |
| Licensed commercial stock | Conditional - only if the stock license itself permits derivative/AI use | Conditional - only if stock license permits third-party service upload | Conditional - per stock license | Required |
| Unknown license | No (blocked by default, matches existing `classify_reference_cloud_upload_permission("unknown")`) | No | No | N/A - blocked |
| Proprietary third-party | No | No | No | N/A - blocked |
| Student/private | No | **No, always** | No | N/A - always forbidden, locked rule |
| Existing owned mesh | Yes | Conditional - only if ownership/no-third-party-rights is confirmed | Conditional - per the same ownership confirmation | Required |

This matrix is consistent with, and does not require changing, the
existing `CLOUD_UPLOAD_ALLOWED_LICENSES`/`CLOUD_UPLOAD_NON_COMMERCIAL_ONLY_LICENSES`/
`CLOUD_UPLOAD_BLOCKED_LICENSES` classification already in
`factory.meshy_approval`.

## Exact `config/meshy_policy.json` diff preview (proposal only - NOT applied)

```
CURRENT                                          PROPOSED
cost_policy.currency: null                    -> "USD"
cost_policy.per_request_cap: null             -> 25          (credits)
cost_policy.per_project_cap: null             -> 100         (credits)
cost_policy.daily_cap: null                   -> 150         (credits)
cost_policy.monthly_cap: null                 -> 500         (credits)
cost_policy.credit_policy.max_credits_per_request: null -> 25
cost_policy.credit_policy.max_credits_per_day: null      -> 150
license_policy.terms_reviewed: false          -> true        (once a human has actually
                                                                read the full Terms of Use /
                                                                Acceptable Use Policy text,
                                                                not just this document's
                                                                AI-summarized excerpts)
license_policy.commercial_use_required: null  -> "commercial_concept_only" (human choice - see
                                                  the two-option note above)
license_policy.third_party_asset_restrictions: "unknown" -> "user_warrants_no_infringement"
                                                              (restates terms-of-use Section 3.4)
```

Reason for every numeric proposal: see "Proposed cost/credit caps" table
above (source: Meshy pricing docs, arithmetic derived by this checkpoint,
not Meshy-published caps). Reason for `terms_reviewed`/`commercial_use_required`:
see "Commercial-use findings"/"Proposed commercial policy" above. **No
field in this diff has been written to the actual file.**

## Approval command preview (NOT executed)

After a human has reviewed the above and hand-edited
`config/meshy_policy.json` with real values (not this checkpoint's
proposed ones, unless the human agrees with them):

```
factory meshy policy --json   # confirm gate_status has advanced past needs_cost_policy/needs_license_policy
factory meshy approve-policy --ack-cost --ack-license --ack-privacy --ack-provenance --approved-by "<name>"
factory meshy approval-status   # confirm approval recorded, execution_enabled still false
```

This records `approval_scope=policy_only` only - it does **not** enable
Phase 47 implementation or any live API call by itself; those remain
separate decisions (see below).

## Remaining unknowns (explicitly not inferred)

- Whether failed/canceled tasks consume credits.
- Whether unused monthly credits roll over, or expire.
- Whether Multi-Image-to-3D/Image-to-3D have current v2 REST paths (quick-start
  only showed a v1 example for Image-to-3D against Text-to-3D's documented v2).
- Multi-Color Print's exact credit cost (not found in the primary pricing
  table fetched).
- Whether a paid-plan "keep content private" setting actually opts an
  asset out of AI-training use, or only out of public/community-page
  visibility - these are different protections and the secondary source
  that mentioned it did not distinguish them.
- Exact data retention duration for uploads/results.
- Whether resale of a *physical* object 3D-printed from Meshy-generated
  output is treated any differently from resale of the *digital* model
  itself - not addressed in any fetched page.
- Real-world unit/scale convention of generated meshes.
- Whether scoped (limited-permission) API keys exist, beyond an unscoped
  account-wide key.
- Webhook payload exact field shape (found via secondary source only;
  recommend a direct primary-source re-check before Phase 47 relies on it).

## Phase 47A recommendation: **RECOMMEND APPROVE**

Reasoning: the Text-to-3D API contract is well-documented (request
parameters, output shape, task states, error codes), the provenance
fields needed are known and already largely represented in
`factory.meshy_approval`'s existing field lists, a cost policy *can* be
represented (even though real values still need human input), and the
Factory's kill switch (`config/future_cloud_tools.json`) and layered
approval model already exist and require zero code changes to keep
gating live execution. A **mocked-only** Phase 47A adapter - no
credentials, no network, no money - can be safely built against this
research without waiting for every remaining unknown above to be
resolved, since none of those unknowns affect a mocked implementation's
correctness; they only need to be resolved before Phase 47B.

## Phase 47B (real API call): **NOT APPROVED**

Nothing in this checkpoint constitutes that approval. Per the spec, this
requires a separate, later, explicit human decision after: real cost caps
are configured (not this checkpoint's proposed placeholders), the license
posture is actually decided (`commercial_concept_only` vs.
`commercial_requires_case_review`), the remaining unknowns above are
resolved to the human's satisfaction, and the kill switch is explicitly
enabled - none of which happened here.

## Test count

2554 passed (unchanged from before this checkpoint - no code was
modified; this checkpoint added only this document).

## Git status after this checkpoint

Only `docs/meshy-current-research.md` is new/untracked. Every other
tracked file, including `config/meshy_policy.json` and
`config/future_cloud_tools.json`, is byte-for-byte unchanged from before
this checkpoint. Nothing committed.

## Exact next command(s) - described only, not executed

1. A human reads this document and the full Meshy Terms of Use/Acceptable
   Use Policy/Privacy Policy text directly (not only this document's
   AI-summarized excerpts) and decides real cost caps and a commercial
   policy category.
2. Hand-edit `config/meshy_policy.json` with the agreed real values.
3. `factory meshy policy --json` (read-only - confirm gate status advanced).
4. `factory meshy approve-policy --ack-cost --ack-license --ack-privacy --ack-provenance --approved-by "<name>"`
   (explicit write, records `approval_scope=policy_only` - still does not
   enable execution).
5. A separate, later decision on Phase 47A implementation approval, and a
   still-later, still-separate decision on Phase 47B live-call approval.

No command above was executed by this checkpoint.

---
type: Spec
id: SPEC-216
title: "Multipart Upload & Part-Level Retry"
description: "Uploads files as presigned multipart parts with part-level retry, sizing parts to finish inside one presigned window on the slowest supported link and capping single-PUT size by the same constant, for users."
spec_status: Completed
depends_on: [SPEC-198, SPEC-196, SPEC-197, SPEC-020, SPEC-172, SPEC-161]
---

**Dependency notes:** SPEC-198 (the presigned upload this supersedes — `objects.uploadUrl`, the `XMLHttpRequest` requirement, the `expiresAt` clamp, and the accepted residual this spec discharges), SPEC-196 (the user credential plane, `signing_client(covering=…)` and the one-hour role-chaining ceiling), SPEC-197 (the route table, the **closed** error enum, the closed type vocabulary, the declared-per-route `idempotent` flag and `Route.plane`), SPEC-020 (the upload queue, which stays in the browser and gains no state), SPEC-172 (`isWriteLockedPrefix` and the archive Deny), SPEC-161 (a cap is computed by a test against the budget that sized it)
## Overview

An upload is **one presigned `PUT`** today, and two things follow that a user feels. A dropped
connection restarts the whole file, because there is no part to retry. And the transfer must fit
inside one presigned window — which SPEC-198 accepted on an **unmeasured premise**, that S3 evaluates
a presigned expiry when it *receives* the request rather than when the transfer completes. If that
premise is false, every upload longer than the window fails at the tail with an opaque 403 **after
the bytes were sent**.

Multipart removes both, but only if the parts are sized for it. A part is its own request under its
own URL, minted immediately before it is sent — so under the *receipt* reading no part depends on a
long transfer, and under the *completion* reading a part still has to finish inside its window. **The
design is only premise-independent if a part is small enough to finish inside one window on the
slowest connection this product supports**, and FR-002 is where that is earned rather than asserted.

**Working that out exposes something the single-`PUT` path already has wrong.** "What fits in one
window on the slowest link" is the same quantity whether it bounds a part or a whole object — so it
is *also* the largest object that can be trusted to upload in one request. Today nothing bounds
that: a 200 MB upload on a 2 Mbps uplink takes thirteen minutes against a fifteen-minute window and
has no part to retry. One constant therefore does both jobs, and the threshold is not a tuning knob
(FR-005).

**This spec buys back what SPEC-198 knowingly gave up.** Its FR-005 named the route trio in as many
words — `create-multipart` / `sign-part` / `complete-multipart` — "so it is added rather than
rediscovered". This is that spec, with a fourth route for abort and one correction to the shape: the
create route eventually **replaces** `objects.uploadUrl` rather than sitting beside it — but not in
the same change, because the three deploys are **unordered** and a same-change retirement breaks
every live upload for the length of a rollout (FR-005).

## Scope

### In Scope

- **Four routes**, added ADDITIVELY beside `objects.uploadUrl`, which is retired only after the
  browser has switched and shipped (FR-001, FR-005).
- **The part plan is computed against TWO budgets**, and the second is what makes the expiry premise
  stop mattering (FR-002).
- **The browser's uploader**: parts in flight, aggregate progress, per-part retry (FR-003).
- **Cancel, and the parts already sent** (FR-004).
- **The single-`PUT` path stays, and the SERVER decides which path an upload takes** (FR-005).
- **The `uploadId` is a capability**, and every call re-authorizes from claims (FR-006).
- **The ETag round trip**, and the CORS premise it rests on — already true (FR-007).
- **Every failure maps onto the closed error enum**, and what a user sees (FR-008).
- **What this discharges, and what it deliberately does not** (FR-009).

### Out of Scope

- **Raising the 5 GiB ceiling.** `maxUploadBytes()` clamps to `S3_SINGLE_PUT_MAX_BYTES`, and
  multipart would technically permit 5 TiB. Not raised here, and the reason is that it is a
  **product decision, not a technical one**: it changes storage cost, upload duration, and what a
  user can do to a shared space by accident. Part-level retry and premise-independence are both
  delivered at the current ceiling, so the ceiling is not load-bearing for this spec's value — and
  FR-005 AC5 pins the clamp with a test so it cannot drift upward by accident.
- **Resume across a page reload.** Deferred, and the reason is **not** the one it first looks like:
  `ListParts` needs only a known `uploadId`, and `s3:ListMultipartUploadParts` **is** granted, so a
  client that persisted its `uploadId` could enumerate its own parts. The blocker is that a browser
  cannot re-acquire the `File` handle across a reload — the bytes are gone — so a resume would work
  until the reload that is the only time anyone wants it. A "you have an unfinished upload" *prompt*
  is reachable and is also out of scope: it would tell a user about something they cannot act on.
- **A server-side uploader, or any route that moves bytes.** Bytes go browser → S3. The API mints
  and never proxies; that is SPEC-198's split and this spec does not touch it.
- **Changing the upload queue's shape.** `UploadQueueProvider`, `uploadQueueReducer`,
  `UPLOAD_CONCURRENCY` and the collision round trip are unchanged (SPEC-198 FR-008 still holds).
- **Multipart for the control planes.** They copy server-side with their own roles; nothing here
  reaches them.
- **Any change to bucket CORS, the bucket policies, the portal role's identity policies, or the
  deploy role's.** This spec provisions **no infrastructure at all** — see the premises. The
  in-scope-IAM rule that applies to any spec adding infra therefore does not apply, and that is
  stated rather than left to be checked.

### Premises — measured 2026-08-29, and independently re-verified in review

Three make the spec smaller than it looks. The fourth bounds the design rather than enabling it.

1. **`ETag` is already exposed by both buckets' CORS.** `expose_headers` on
   `aws_s3_bucket_cors_configuration.user_space` (`infra/modules/data/s3.tf`) and `.shared_space`
   (`infra/modules/shared-spaces/s3.tf`) is
   `["ETag", "x-amz-server-side-encryption", "x-amz-request-id", "x-amz-id-2"]`. Without `ETag` the
   browser cannot read a part's ETag and **cannot complete an upload at all** — and the failure is a
   `null` header, not an error, so it presents as a malformed complete request. No CORS change; an
   assertion instead (FR-007).
2. **`s3:AbortMultipartUpload` and `s3:ListMultipartUploadParts` are already granted** to the portal
   role on both buckets. **And the archive Deny does not bite**: `CreateMultipartUpload`,
   `UploadPart` and `CompleteMultipartUpload` all authorize as `s3:PutObject`, which is already
   denied under `*/archive/*` — so no upload can be *created* there and the `AbortMultipartUpload`
   Deny is unreachable from this path. `protected.assert_replaceable` refuses it in the route first
   in any case. The happy path needs no IAM change.
3. **Orphaned parts are already swept.** Both buckets carry
   `abort_incomplete_multipart_upload { days_after_initiation = 7 }`. That is the net under a browser
   that never aborts — a closed tab, a crash — and it is why FR-004 can be honest about what it does
   not guarantee.
4. **Nothing can ENUMERATE another user's in-progress uploads.**
   `s3:ListBucketMultipartUploads` is ungranted on both buckets because it does not support the
   `s3:prefix` condition key (`infra/modules/data/iam.tf`, verified by policy simulation in
   SPEC-016). This does not forbid resume — see Out of Scope for the reason that does — but it does
   forbid any design that sweeps, reports or reconciles in-progress uploads across users.

**One premise this spec does NOT settle:** whether S3 evaluates a presigned expiry at request receipt
or at completion (SPEC-198 FR-005 AC8, still owed). FR-002's upper bound is what makes the design
correct under **either** reading. The premise still governs a presigned **download** of a large
object, and that owed check stays owed and stays worded as it is.

---

## Functional Requirements

### FR-001: The four routes

#### Description:

The multipart lifecycle, one route per verb, all on SPEC-196's **user** plane so the caller's own
assumed session both authorizes and signs.

#### Acceptance Criteria:

- [ ] Four routes ship, each declaring `plane="user"` on its `Route` — **not a `ROUTE_PLANES`
      entry**, which SPEC-197 removed in favour of the required field. Their ids are
      `objects.upload`, `objects.uploadPart`, `objects.uploadComplete` and `objects.uploadAbort`.
      **The `objects.` prefix is load-bearing**: `test_objects_routes.py`'s user-plane sweep selects
      its population by `route.id.startswith("objects.")`, so an id like `multipart.create` would
      escape it silently.
- [ ] Paths: `POST /v1/objects/upload`, `POST /v1/objects/upload/part`,
      `POST /v1/objects/upload/complete`, `POST /v1/objects/upload/abort`.
- [ ] **`idempotent` is `true` for `objects.uploadPart` alone**, with the reasoning written per
      route. Signing is a local SigV4 operation that changes nothing at S3, so a retry is free.
      **Create is false** — a retried create leaks an upload id nobody will abort, which costs
      storage until the lifecycle rule reaps it. **Complete and abort are false** — a retried
      complete answers against a finished upload and a retried abort answers `NoSuchUpload`, and
      both would surface as a failure for an operation that succeeded. **Stated as declaration
      hygiene, not as protection**: `idempotent` is consumed only by `apiRetryPolicy` for TanStack
      Query, and `uploadFile` calls `apiRequest` imperatively, so nothing retries these today.
- [ ] `objects.upload` takes `{space, key, contentType, overwrite, size}` and returns the
      discriminated shape FR-005 specifies. **`size` is new and it is what makes the plan
      computable** — `partSize` and `partCount` are functions of the object's byte length, and no S3
      call can supply it because the object does not exist yet.
- [ ] **`size` is a PLANNING INPUT, not a limit, and the difference is stated.** It is the caller's
      number and nothing verifies it: a client that under-declares gets a plan with too few parts
      and fails at `UploadPart` number 10,001 or at complete. The real ceiling is `maxUploadBytes()`
      in the browser and S3's own part limits at the far end. The route refuses an unservable
      declared size as a **courtesy** (FR-002 AC5), not as enforcement, and says so.
- [ ] The create route runs **exactly the authorization `objects.uploadUrl` ran**: space from
      claims, key contained, `assert_replaceable`, and the `overwrite: false` collision refusal
      answering **409 `Conflict`** with `params: {name}` and creating **no upload**. Asserted by
      call count: a route that creates first and checks after has already made something that needs
      aborting.
- [ ] `objects.uploadPart` takes `{space, key, uploadId, partNumber}` and returns
      `{url, expiresAt}`. One part per call — FR-003 AC2 says why it is not a batch.
- [ ] `objects.uploadComplete` takes `{space, key, uploadId, parts: [{partNumber, etag}]}` and
      returns `{key, etag}`. `objects.uploadAbort` takes `{space, key, uploadId}` and returns
      `{key}`.
- [ ] **The part list is the browser's, and that is safe for a stated reason.** S3 validates every
      ETag, so a wrong list fails the complete rather than assembling the wrong object. A caller who
      completes with a *subset* truncates their own object in their own prefix, which they could do
      by uploading a shorter file. *(Rationale, not a criterion — it exists so nobody adds a
      server-side part audit costing a `ListParts` per upload.)*
- [ ] Every route resolves its bucket and root prefix from the verified username and the caller's
      membership claims, refusing a foreign space **403 `AccessDenied` with zero AWS calls** — the
      criterion SPEC-198 FR-001 AC7 states, asserted the same way, and easier to get wrong here
      because the `uploadId` looks like authorization (FR-006).
- [ ] **The collision check is re-run at COMPLETE when `overwrite` is false**, with
      `If-None-Match: *`. The create-time `head_object` answers about a moment that can be hours
      before the object is assembled, and completing over what arrived in between reports success
      while destroying it. This repo has already paid for that shape once: the archive restore
      guard "runs **TWICE**, and the second pass is the spec correcting itself", because the billed
      hours are exactly when the user re-creates the file. A long multipart upload is the same
      window.

### FR-002: The part plan, and the one bound that earns the spec's claim

#### Description:

Part size decides whether a part completes inside its window. **That is the only budget that binds**,
and an earlier draft of this FR had a second one — a lower bound stopping signing becoming the
bottleneck — which is removed here because it is arithmetically inert: both bounds were proportional
to the same uplink constant, so the uplink cancelled, they could never conflict for any file size,
and the lower one only overtook S3's own 5 MiB floor above a *minimum* supported uplink of ~42 Mbps.
A constant that cannot change the answer is the vacuous computed cap SPEC-161 exists to prevent.

#### Acceptance Criteria:

- [ ] Three constants are **carried across as published S3 limits**, named as such, not derived:
      `MULTIPART_MIN_PART_BYTES` = 5 MiB (the minimum for every part but the last),
      `MULTIPART_MAX_PART_BYTES` = 5 GiB, and `MULTIPART_MAX_PARTS` = 10,000.
- [ ] `PART_URL_EXPIRY_SECONDS` = **900**, matching the two windows SPEC-198 already ships rather
      than differing for no reason. It must satisfy the relation SPEC-196's guard checks —
      **strictly less than `ASSUME_ROLE_DURATION_SECONDS`** — because a window no session can span
      forces an `AssumeRole` per part, permanently and silently. **That guard's population is a
      hand-written dict naming `upload` and `download`; this constant is added to it, or the guard
      passes over it vacuously** — the same failure class as a code missing from `CLIENT_MINTED`.
- [ ] `MIN_SUPPORTED_UPLINK_BYTES_PER_SEC` = **250,000** (2 Mbps), and it is a **product decision
      stated as one**: it is the slowest connection this product undertakes to upload large files
      over. It is visible, and it is the number to change if that undertaking changes — below it,
      uploads still work, they simply lose the guarantee this FR makes. Chosen conservatively,
      because the cost of being wrong in the generous direction is the tail-403 this spec exists to
      remove, and the cost of being wrong in the cautious direction is more round trips.
- [ ] `PART_WINDOW_SAFETY_FACTOR` = **2**: a part must complete in **half** its window, so a
      transient stall does not turn into an expiry.
- [ ] **`MULTIPART_PART_BYTES` is a CONSTANT, not a function of file size**, computed by a test:
      `clamp(MIN_SUPPORTED_UPLINK_BYTES_PER_SEC × PART_URL_EXPIRY_SECONDS / PART_WINDOW_SAFETY_FACTOR,
      MULTIPART_MIN_PART_BYTES, MULTIPART_MAX_PART_BYTES)`. At the values above that is **107 MiB**,
      and the test states that number so a change to any input is visible as a change to it.
- [ ] **The per-upload plan is one line and it is determinate**: `partSize = MULTIPART_PART_BYTES`
      and `partCount = ceil(size / partSize)`. There is **no range and no choice**: an earlier draft
      left the plan free between two bounds, which made every boundary assertion in this FR
      unwritable. **And there is deliberately no size term.** An earlier draft of *this* criterion
      wrote `partSize = max(MULTIPART_PART_BYTES, ceil(size / MULTIPART_MAX_PARTS))` and explained
      the term as biting "beyond 1 TiB" — but beyond 1 TiB the next criterion **refuses**, and it
      runs first, so the `max` can only ever return the constant. It was a branch no input reaches
      and no test can cover, and it was measured as one: rewriting the return to ignore `partSize`
      entirely passed the whole suite. The two criteria covered the same region and the refusal is
      the correct half, because a larger part is exactly what cannot finish inside its window.
- [ ] **The one real conflict is a REFUSAL, not a tie-break.** When `ceil(size / MULTIPART_MAX_PARTS)`
      exceeds what the window allows, no plan can both stay inside S3's part ceiling and finish each
      part in time — so the route answers **413 `PayloadTooLarge`** with `params: {limit}` before any
      S3 call — and "before any S3 call" is asserted **by call count**, against both the S3 client
      and the identity door, rather than left to the reading order. An earlier draft said "the upper bound wins", which would have produced sub-5-MiB
      parts that S3 refuses at complete with `EntityTooSmall`: shipping the failure rather than
      refusing it. Driven by a test that moves the **constants**, since no file size reaches it at
      the current clamp.
- [ ] The plan is computed **server-side, in the create route**, and returned. The browser does not
      compute it: two implementations produce two part counts for one file, and the complete call
      would then disagree with what was uploaded.
- [ ] A test asserts the plan at four points: one byte below the threshold, exactly the threshold,
      one byte above it, and exactly 5 GiB — with the comparison stated as `size > threshold`
      (FR-005), so an off-by-one is visible rather than arguable. The last part is permitted to be
      below `MULTIPART_MIN_PART_BYTES`, which S3 allows and which the arithmetic produces
      constantly.

### FR-003: The browser's uploader

#### Description:

`uploadFile` gains a multipart path. Its **signature does not change** — the queue, the progress
callback and the abort signal are SPEC-020's and SPEC-198's, and this spec is not entitled to them.

#### Acceptance Criteria:

- [ ] `uploadFile` keeps its exact signature, including `onProgress(loaded, total)` and `signal`.
      Every caller is unchanged.
- [ ] **A part's URL is minted immediately before that part is sent, never in a batch.** The same
      rule as SPEC-198 FR-008's per-file minting and for the same reason: a batch ages while the
      parts ahead of it upload, and the last URL is signed long before it is redeemed. This is half
      of what makes the window stop mattering — FR-002's upper bound is the other half — so a
      batching optimisation would silently undo the spec.
- [ ] Parts go over **`XMLHttpRequest`**, not `fetch` — SPEC-198 FR-005's requirement, unchanged and
      for the unchanged reason.
- [ ] **The `XMLHttpRequest` allowlist stays a NAMED list and gains whatever modules the transport
      actually lives in.** `apiContract.guard.test.ts` exempts `fileBrowser.service.ts` alone and
      asserts `offenders` is empty, so any new module naming `XMLHttpRequest` turns it red. The
      outcome the rule protects is that `XMLHttpRequest` is not an escape hatch from `apiRequest` —
      a named list of two serves that exactly as well as one, and a *pattern* would not. **Where the
      transport lives is not specified**: one shared helper both paths call is a perfectly good
      answer and probably the better one, since otherwise the abort handling, the progress plumbing
      and the 403-versus-expiry mapping are each written twice. The companion assertion — that an
      exemption cannot outlive its subject — applies to whichever modules end up on the list.
- [ ] **`onProgress` reports the AGGREGATE**, and the assertion is on an intermediate value across a
      part boundary: a test uploads a body of three parts, drives progress on part two, and asserts
      `onProgress` is called with `loaded` greater than one part and less than the total. Per-part
      progress that resets at each boundary is the obvious wrong implementation and it looks like a
      working bar.
- [ ] **The aggregate is `sum(max(seen_so_far, latest))` per part** — never a running sum of
      progress events, and **never last-value-wins**. A retried part is a new `XMLHttpRequest` whose
      first progress event reports a small `loaded`, so last-value-wins drops that part's
      contribution to near zero and the bar falls: with three parts in flight and part two failing
      at 4 MiB of 5, the aggregate goes 9.0 MiB → 5.0 MiB. A running sum has the opposite defect,
      over-reporting and then jumping. Taking the per-part maximum is monotonic at every step, and
      nothing downstream would hide a regression — the queue stores `loaded` verbatim with no clamp.
- [ ] **The progress test drives a RETRY, not merely a part boundary.** A test that crosses a
      boundary without a failure passes under all three implementations, so it cannot be the one
      that pins this.
- [ ] **A RETRY RE-MINTS THE PART'S URL, and that is forced rather than chosen.** A part is sized to
      use half its window on the slowest supported uplink, so a second attempt on the *same* URL
      starts with roughly half the window already spent and a third cannot finish inside it at all —
      at 107 MiB, 2 Mbps and 900 s, three attempts need ~1350 s against 900. Reusing the failed URL
      would therefore reintroduce the tail-403 by a different route, on the very path built to
      remove it. Each attempt calls `objects.uploadPart` again.
- [ ] **The retry count is 2, and its budget is makespan.** With re-minting each attempt has a full
      window, so the constraint is how long one part may take before the upload is worse than
      starting over: a test computes the worst-case per-part makespan
      (`(1 + retries) × partSize / MIN_SUPPORTED_UPLINK_BYTES_PER_SEC`) and states it. Two is the
      point where a third attempt against a connection that has failed twice is unlikely to succeed
      while adding half again to that number.
- [ ] A part that exhausts its retries fails the upload. This is the capability the spec exists to
      restore, so a test drives a part failing once then succeeding, and asserts the **whole file
      was not re-sent** — by counting bytes offered to the transport.
- [ ] Parts in flight are bounded by a constant that names its budget. It is **not**
      `UPLOAD_CONCURRENCY`, which bounds files: three files each running four parts is twelve
      concurrent transfers. The budget is the browser's own connection limit per origin, and a test
      states the **product** and the factor, not the product alone.
- [ ] A part's ETag is read from the response's `ETag` header and carried to complete. A missing
      header — FR-007's CORS regression — fails the upload with a named code, never a complete
      request carrying `null`.

### FR-004: Cancel, and the parts already sent

#### Acceptance Criteria:

- [ ] Cancelling calls `objects.uploadAbort` and resolves to code `'Cancelled'` — the same code and
      wording the single-`PUT` path already produces.
- [ ] **The abort call does NOT carry the caller's signal.** The cancel path is entered *because*
      `signal.aborted` is true, so passing it to `apiRequest` aborts the abort — leaving the upload
      to the seven-day lifecycle rule for a cancel the user watched succeed. `uploadFile` already
      carries a comment about this class of mistake on the mint path.
- [ ] The abort is **best effort and never blocks the cancel**. A user who cancels gets an immediate
      `Cancelled`; a failed abort is reported nowhere and logged in dev only. The alternative is a
      cancel that can fail, which is a control that does not work when it is most wanted.
- [ ] **What is NOT guaranteed is written down**: a closed tab, a crash or a dead network leaves the
      upload unaborted, and nothing in the browser will ever abort it. The lifecycle rule (Premise 3)
      is the only sweep, and it is a bucket-level guarantee rather than this feature's. A test
      asserts the rule exists on **both** buckets — it is load-bearing for a feature now rather than
      incidental hygiene. *(That test reads Terraform and belongs beside the existing bucket-policy
      tests under `lambdas/`, not under `lambdas/api/`.)*
- [ ] **No resume, and no unfinished-upload prompt** — Out of Scope carries the reason, which is the
      lost `File` handle rather than a missing grant.
- [ ] The queue's existing cancel semantics are unchanged: `cancel` on a queued item removes it
      without starting; on an in-flight item it aborts and moves to `cancelled`.

### FR-005: The server decides which path an upload takes, and the retirement is not in this change

#### Description:

Multipart costs a create, N sign calls and a complete. For a small file that is worse than one call.
**But the browser must not hold the threshold**, and that constraint decides the route shape.

#### Acceptance Criteria:

- [ ] **`objects.upload` ships ALONGSIDE `objects.uploadUrl`, and the retirement is a later
      change.** The two paths differ (`/v1/objects/upload` vs `/v1/objects/upload-url`), so nothing
      obstructs keeping both. Retiring in the same change would break every live upload for the
      length of an SPA rollout, and the reason is **not** the one an earlier draft gave. It claimed
      `decisions/identity-and-access/`'s "the API deploys before the SPA image" as fact; measured
      over the last real deploys that is **false in the direction that matters** — the three
      workflows fire independently on a push to `main` with **no ordering between them**, and
      `Deploy App` (CloudFront, a live SPA surface) finished *first* every time, beating
      `Deploy Lambdas` by 4m28s on `8a3992b4` and by 4m51s on `696c3fdc`. Only a narrow
      `lambdas/api/**` plan lets the API win. So skew runs in **both** directions: an old bundle can
      meet a new code, **and a new bundle can meet an API that has not got the route yet** — which
      is what makes the add-then-switch seam load-bearing rather than tidy. The operative reason to
      defer the retirement is therefore **already-loaded clients**, which no deploy order fixes, and
      there are **two** live SPA surfaces because CloudFront is still production. SPEC-198 shipped its whole server surface additively
      for exactly this reason; this spec is the arc's first removal and must inherit the discipline
      rather than rediscover it.
- [ ] The order is therefore: **add, switch, then retire** — and the blast radius **splits by SIDE,
      not by phase**, which an earlier draft of this criterion got wrong by filing all of it under
      the retirement. The **browser-side** sites break the moment `uploadFile` is re-pointed, so
      they belong to the SWITCH: `UploadQueueProvider.test.tsx` drives the *real* `uploadFile`
      through `vi.importActual` and asserts literal `objects.uploadUrl:` route ids, and its
      neighbour stubs `apiRequest` with a `{url, expiresAt}` carrying **no `mode`**, which the
      switched fork refuses by design; `fileBrowser.service.test.ts` has five sites. Filing those
      under the retirement leaves the switch's own PR red.
      The **server-side** sites are the retirement's, and are larger than they look —
      `test_presign.py`'s two parameterised suites cover upload *and* download, so deleting "its
      tests" would take the download route's coverage with it; `test_real_request_shapes.py` posts
      to `/v1/objects/upload-url`; the `ROUTES` row and the `HANDLERS` entry; and
      `UploadUrlRequest` plus `UPLOAD_URL_EXPIRY_SECONDS` each need a keep-or-drop decision.
      **Three further server-side sites this list omitted**, found by enumeration rather than by
      review: `test_absence_is_answerable.py`'s `objects_presign.py::upload_url` row, whose
      set-equality reddens loudly and is merely an edit; `test_spaces_and_protection.py`'s
      `"upload"` window entry and its two-windows-agree test, which is where the
      `UPLOAD_URL_EXPIRY_SECONDS` decision actually lands; and — the one whose loss would be
      **silent** — `test_objects_routes.py`'s `test_an_upload_url_is_never_minted_for_a_marker_key`,
      the only assertion that a `DO_NOT_DELETE.txt` upload is refused **with nothing minted**. The
      `objects.`-prefix sweep beside it checks the *plane* and not that. It is **RE-POINTED at
      `objects.upload`, never deleted**; FR-001's `assert_replaceable` is its new home. The
      retirement therefore opens with a grep enumeration, because the risk there is absence.
- [ ] `objects.upload` returns `{mode: 'single' | 'multipart', url?, expiresAt?, uploadId?,
      partSize?, partCount?}`. A file at or below the threshold gets `mode: 'single'` with a
      presigned `PUT` — **one API call, exactly as today** — and a larger one gets the plan.
- [ ] **The browser never learns the threshold, and that is the point.**
      `scripts/generate_api_contract.py` emits types, `API_ERROR_CODES` and `API_ROUTES` — **not
      constants** — so a browser-side fork would need a second copy of a policy number, and a drifted
      copy sends files down the wrong path with nothing failing. The repo's mirror-and-pin pattern
      would catch drift and would still put the decision in two places. **Rejected in favour of one
      decision site.**
- [ ] **The shape is optional members plus a discriminant, and it does NOT narrow in TypeScript.**
      SPEC-197's closed vocabulary has no union other than `X | None`, and widening it for this is
      what the closed-vocabulary rule forbids — so `walk()` emits one object type with
      `url?: string`, and `if (res.mode === 'single')` narrows nothing else. The browser therefore
      **checks each member it needs at runtime** and answers a named code when the route returns a
      shape its branch cannot use. That code is browser-minted and goes in `errorMessages.ts` **and**
      `CLIENT_MINTED` like the other two (FR-008).
- [ ] **`MULTIPART_THRESHOLD_BYTES` IS `MULTIPART_PART_BYTES`** — one constant, because it is one
      quantity: the largest object that can be trusted to finish inside one presigned window on the
      slowest supported uplink. Above it a single `PUT` cannot be trusted, which is the whole reason
      to multipart; below it multipart buys retry granularity that costs more round trips than the
      restart it saves. The comparison is `size > threshold`, so a file of exactly one part still
      takes the single `PUT`.
      *(An earlier draft grounded the threshold as "two parts" and was circular — it is only two
      parts if the plan takes the minimum part size, which it does not. It also missed that the
      single-`PUT` path shares the window problem, which is what makes the two quantities one.)*
- [ ] **Which path an upload took is observable in a test by route id**, and the span already
      carries `route_id` for free. Without the test half, a threshold regression sending every
      upload down one path passes everything that only asserts the upload succeeded.
- [ ] `MAX_UPLOAD_BYTES` still clamps to `S3_SINGLE_PUT_MAX_BYTES` (SPEC-198 FR-005), and a test
      pins it so this spec cannot raise the ceiling by accident.

### FR-006: The `uploadId` is a capability

#### Acceptance Criteria:

- [ ] **Every route re-authorizes from claims and never from the `uploadId`.** Space resolution and
      key containment run on part, complete and abort exactly as on create — the id is not evidence
      of anything. A test submits a valid `uploadId` with a **foreign** space and asserts **403
      `AccessDenied` with zero AWS calls**.
- [ ] **The `(key, uploadId)` pair is checked by S3, and the API keeps no record of it.** A request
      pairing a real id with a different key fails at S3, and the route maps that to a named code
      (FR-008). *(Rationale: the state already lives in S3, and a second copy of it — a table, a
      cache — is a second thing that can be wrong.)*
- [ ] An `uploadId` appears in **no emitted record**, on the same rule as a presigned URL
      (SPEC-198 FR-007): the span carries `route_id`, the space kind, the key's **length** and the
      part number. A test emits from every call site in the four routes and asserts no field value
      contains the id.
- [ ] Each part URL is a bearer token and inherits every FR-007 rule of SPEC-198 unchanged — minted
      through `signing_client(covering=PART_URL_EXPIRY_SECONDS)`, never logged, `Cache-Control:
      no-store` (which `envelope.py` applies centrally, so nothing is owed here).

### FR-007: The ETag round trip

#### Acceptance Criteria:

- [ ] A test asserts `expose_headers` on **both** bucket CORS configurations contains `ETag`. It is
      already there (Premise 1); the test exists because it stops being incidental the day this
      ships — without it `xhr.getResponseHeader('ETag')` returns `null`, the complete request carries
      nulls, and the upload fails with an S3 error that names none of this.
- [ ] The browser fails an upload with a **named code** when a part's ETag is absent, rather than
      sending it.
- [ ] **Live, and owed to this spec's own verification**: a real multi-part upload from the container
      origin with the part ETags read in the browser. Offline this is a stubbed header; only a real
      cross-origin response proves the allowlist.

### FR-008: Every failure maps onto the closed enum, and every code has a sentence

#### Description:

S3's multipart faults have names the API's enum does not carry, and SPEC-197 closed that enum
deliberately.

#### Acceptance Criteria:

- [ ] **No code is added to `ErrorCode`.** S3's multipart faults map onto the existing set:
      `NoSuchUpload` → **404 `NotFound`**, `InvalidPart` and `InvalidPartOrder` → **400
      `InvalidRequest`**, `EntityTooSmall` → **400 `InvalidRequest`**.
- [ ] **The mapping is a per-route `raise ApiError(...)` around each S3 verb, NOT a classifier
      entry.** `errors.DENIAL_CODES` is `{"AccessDenied", "AccessDeniedException"}` and
      `for_exception` maps membership to **403 `AccessDenied` unconditionally** — so adding
      `NoSuchUpload` to it would answer 403 for an expired upload id and tell the user they lack a
      permission. There is no AWS-code → `ErrorCode` table anywhere; the house pattern is the
      thirteen `raise ApiError(...)` sites already in `routes/`, e.g. `objects_content.py`'s
      `raise ApiError("NotFound", "no object at that key") from exc`. *(An earlier draft prescribed
      `DENIAL_CODES`, which would have shipped the wrong status.)*
- [ ] **Without a mapping the fault re-raises and becomes `InternalError`**, which the wording guard
      names as deliberately generic — so the per-route raise is what makes an authored sentence
      possible at all, and that is why FR-008 exists rather than being left to the classifier.
- [ ] **`CompleteMultipartUpload` can answer `200 OK` with an error in the body**, which is this
      repo's `delete_objects` trap in another service. The INSTALLED botocore converts it via
      `_handle_200_error` — which rewrites the status to 500 rather than raising at the parse, so
      the observable is the retried 500 surfacing as a `ClientError`. Asserted as a **tripwire
      against whatever version is installed**, because boto3 is deliberately unpinned here
      (`requirements-dev.txt`: it is the subject of an assertion, not the instrument), and a bump
      that changed this would turn a failed assembly into a reported success.
- [ ] The browser-minted codes this path adds — an absent ETag, a part that exhausted its retries,
      and a create response whose members the chosen branch cannot use (FR-005) — are added to
      `errorMessages.ts` with authored sentences **and** to `apiContract.guard.test.ts`'s
      `CLIENT_MINTED` list, which is hand-maintained: a code left out of it is invisible to the
      "every code has a rule of its own" guard, which is how a service-minted code with no rule
      would reach a user as the generic sentence.
- [ ] A test walks every code the multipart path can produce through `toUserText` and asserts none
      resolves to *"Something went wrong. Contact the Administrator."* This **extends** the walk
      SPEC-198 already ships over 403/500/503 rather than introducing it.
- [ ] A part that exhausts its retries fails the file with wording saying nothing was saved and the
      upload can be tried again — true of multipart, because an incomplete upload assembles no
      object.
- [ ] **The Help correction is two clauses, not one.** `helpContent.ts`'s upload guide reads *"An
      upload is one continuous transfer. If your connection drops partway, the panel marks that file
      Failed — nothing partial is left behind, and dropping it in again starts it from the
      beginning."* Above the threshold **both** the last clause and *"nothing partial is left
      behind"* become false, and the second has a billing consequence: parts live seven days.

### FR-009: What this discharges, and what it does not

#### Acceptance Criteria:

- [ ] SPEC-198 FR-005 AC6's residual — "there is **no part-level retry** any more" — is marked
      superseded **in place** at every site that states it: the spec itself,
      `decisions/storage/`'s *Bytes go to S3 presigned* entry, the CLAUDE.md digest clause, and
      **`architecture.md`'s constraint prose plus ADR row 39**, which the completion ritual names
      explicitly and which an earlier draft of this criterion missed.
- [ ] **`owed.md` is edited across THREE rows, not one, and none is deleted.** The row carrying the
      expiry premise and the multi-GiB check keeps the premise **worded as it is** and re-words the
      check to settle that a multipart upload completes. The row carrying the part-level-retry
      residual *and* the still-live foreign-prefix residual loses only its retry clause — deleting
      the row would take the declined-probe-route reasoning with it. And the "intermediate upload
      percentage, in a real browser" row is **already DISCHARGED** (2026-08-31, seven `xhr.upload`
      events at 19–100 %), so it is **left standing and a NEW row is added** for the aggregate.
      Re-pointing the discharged row — which an earlier draft of this criterion said to do — would
      erase a check that was actually run, which is the discharge-what-was-run error running
      backwards. The aggregate is a different and harder claim than the single-`PUT` one: it must
      hold across a part boundary **and across a retry**.
- [ ] **The expiry premise is not discharged.** FR-002's upper bound makes the design correct under
      either reading, which is not the same as knowing which reading is true — and the premise still
      governs a presigned **download** of a large object, which this spec does not touch. Rounding it
      up to "settled" is exactly the discharge-what-was-run error the testing docs exist to prevent.

---

## Data Model

```python
# lambdas/api/apicommon/contract.py — additions

class CreateUploadRequest(TypedDict):
    space: SpaceRef
    key: str
    contentType: str
    overwrite: bool
    size: int                      # a PLANNING input, not a limit — FR-001 AC5

class CreateUploadResponse(TypedDict):
    # Optional members plus a discriminant, because the closed vocabulary has no union
    # other than `X | None`. The browser narrows on `mode` — FR-005 AC3.
    mode: Literal["single", "multipart"]
    url: NotRequired[str]          # single
    expiresAt: NotRequired[str]    # single
    uploadId: NotRequired[str]     # multipart — a CAPABILITY, never logged (FR-006)
    partSize: NotRequired[int]     # multipart
    partCount: NotRequired[int]    # multipart

class SignPartRequest(TypedDict):
    space: SpaceRef
    key: str
    uploadId: str
    partNumber: int                # 1-based, as S3 numbers them

class UploadedPart(TypedDict):
    partNumber: int
    etag: str

class CompleteUploadRequest(TypedDict):
    space: SpaceRef
    key: str
    uploadId: str
    parts: list[UploadedPart]
    overwrite: bool                # FR-001's complete-time re-check needs its own input: the
                                   #   API keeps NO record of the upload (FR-006 AC2), so the
                                   #   create-time flag is not recoverable server-side

class AbortUploadRequest(TypedDict):
    space: SpaceRef
    key: str
    uploadId: str

# The three RESPONSES are REUSED, not redeclared — they already exist and already match:
#   objects.uploadPart     -> PresignedUrlResponse   {url, expiresAt}
#   objects.uploadComplete -> ObjectWrittenResponse  {key, etag}
#   objects.uploadAbort    -> ObjectDeletedResponse  {key}
```

```python
# lambdas/api/apicommon/s3_config.py — additions
# Three are carried service limits. Two are decisions, stated with their values. One is computed
# from them, and it is also the threshold — one quantity, not two (FR-005).

MULTIPART_MIN_PART_BYTES: int            # 5 MiB — S3's published minimum, carried
MULTIPART_MAX_PART_BYTES: int            # 5 GiB — S3's published maximum per part, carried
MULTIPART_MAX_PARTS: int                 # 10,000 — S3's published maximum, carried

PART_URL_EXPIRY_SECONDS: int             # 900; < ASSUME_ROLE_DURATION_SECONDS, and ADDED to the
                                         #   guard's hand-written dict or it passes vacuously
MIN_SUPPORTED_UPLINK_BYTES_PER_SEC: int  # 250,000 (2 Mbps) — a PRODUCT DECISION, stated as one
PART_WINDOW_SAFETY_FACTOR: int           # 2 — a part completes in half its window

MULTIPART_PART_BYTES: int                # computed: 107 MiB at the values above
MULTIPART_THRESHOLD_BYTES: int           # == MULTIPART_PART_BYTES. One quantity.
```

## API / Interface Contract

```ts
// apps/portal/src/features/file-browser/fileBrowser.service.ts — UNCHANGED signature
export async function uploadFile(params: {bucket: string; key: string; body: Blob | File;
  contentType: string; overwrite?: boolean;
  onProgress?: (loaded: number, total: number) => void;   // now the AGGREGATE — FR-003
  signal?: AbortSignal}): Promise<ServiceResult<UploadResult>>;
```

## File & Folder Structure

```
lambdas/
├── api/
│   ├── apicommon/s3_config.py       # + the six multipart constants
│   ├── routes/objects_upload.py     # NEW — create, sign-part, complete, abort
│   ├── routes/objects_presign.py    # − upload_url; download_url unchanged
│   └── test_multipart.py            # NEW — the plan, its refusal, the capability rules
└── test_multipart_infrastructure.py # NEW — the CORS ETag and lifecycle assertions, beside the
                                     #   existing Terraform-reading bucket tests

apps/portal/src/features/file-browser/
├── fileBrowser.service.ts           # uploadFile forks on the route's answer; signature unchanged
└── multipartUpload.ts               # NEW — the part loop, retry and aggregate progress
```

## Environment Variables

None. No new `VITE_*`, no new runtime-config key, no new Lambda variable, **and no infrastructure**.

## Implementation Phases

### Phase 1: The plan
`s3_config`'s constants with their computing tests, `MULTIPART_PART_BYTES` stating its 107 MiB, the
`PART_URL_EXPIRY_SECONDS` entry added to the window-vs-session guard's dict, FR-002's four boundary
points and its refusal driven by moving the constants. No routes yet.

### Phase 2: The routes, ADDITIVELY
`objects_upload.py`, the contract rows, `Route.plane` and `idempotent`, FR-006 whole
(re-authorization, the zero-call foreign refusal, the field rule), and FR-008's per-route `ApiError`
raises. `objects.uploadUrl` is untouched and still serves the deployed SPA. Regenerate the
TypeScript contract.

### Phase 3: The browser
`multipartUpload.ts`, the fork on the route's answer, per-part minting, aggregate progress with the
across-a-boundary assertion, per-part retry asserted by bytes offered, the ETag round trip, and the
widened `XMLHttpRequest` sweep.

### Phase 4: Verification
A real multi-part upload from the container origin: part ETags read cross-origin (FR-007), the bar
crossing a part boundary without resetting, a cancel leaving no assembled object, and a killed tab
leaving parts the lifecycle rule owns. Added to `e2e.md` §4.2 beside SPEC-198's block.

### Phase 5: Retire `objects.uploadUrl`
Only once the browser has switched and shipped. The blast radius is in FR-005 AC2.

### Phase 6: Completion ritual
`Status: Completed`, the `INDEX.md` row, the delivery doc, FR-009's superseded markers at all four
sites, the `owed.md` edit, the register clause, and the two-clause Help correction.

# Spec: Multipart Upload & Part-Level Retry

**ID:** SPEC-216
**Status:** Draft
**Last Updated:** 2026-08-29
**Depends On:** SPEC-198 (the presigned upload this supersedes — `objects.uploadUrl`, the `XMLHttpRequest` requirement, the `expiresAt` clamp, and the accepted residual this spec discharges), SPEC-196 (the user credential plane, `signing_client(covering=…)` and the one-hour role-chaining ceiling), SPEC-197 (the route table, the **closed** error enum, the closed type vocabulary, the declared-per-route `idempotent` flag and `Route.plane`), SPEC-020 (the upload queue, which stays in the browser and gains no state), SPEC-172 (`isWriteLockedPrefix` and the archive Deny), SPEC-161 (a cap is computed by a test against the budget that sized it)

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
design is only premise-independent if the part size is bounded so that both readings hold**, and
FR-002 is where that is earned rather than asserted.

**This spec buys back what SPEC-198 knowingly gave up.** Its FR-005 named the route trio in as many
words — `create-multipart` / `sign-part` / `complete-multipart` — "so it is added rather than
rediscovered". This is that spec, with a fourth route for abort and one correction to the shape: the
create route **replaces** `objects.uploadUrl` rather than sitting beside it (FR-005).

## Scope

### In Scope

- **Four routes**, one of which supersedes `objects.uploadUrl` (FR-001).
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

### FR-002: The part plan, computed against two budgets

#### Description:

Part size decides whether a part completes inside its window, whether signing becomes the
bottleneck, and how many round trips an upload costs. **One budget is not enough**, and sizing
against the round-trip budget alone grows parts without limit — which reproduces the tail-403 this
spec exists to remove.

#### Acceptance Criteria:

- [ ] Two constants are **carried across as published S3 limits**, named as such, not derived:
      `MULTIPART_MIN_PART_BYTES` = 5 MiB (the minimum for every part but the last) and
      `MULTIPART_MAX_PARTS` = 10,000.
- [ ] `PART_URL_EXPIRY_SECONDS` is declared, and it is the window
      `signing_client(covering=PART_URL_EXPIRY_SECONDS)` asks for. It must satisfy the relation
      SPEC-196's own guard now checks — **strictly less than `ASSUME_ROLE_DURATION_SECONDS`** —
      because a window no session can span forces an `AssumeRole` per part, permanently and
      silently.
- [ ] **The UPPER bound is what makes the expiry premise stop mattering, and it is the one a
      round-trip budget alone would omit.** `partSize` must satisfy
      `partSize ≤ MIN_SUPPORTED_UPLINK_BYTES_PER_SEC × PART_URL_EXPIRY_SECONDS / SAFETY`, so that a
      part sent over the slowest uplink this app supports **completes** inside its own window. Under
      the receipt reading this bound is unnecessary; under the completion reading it is the whole
      design. A test computes it and names the uplink it assumed — **a slow uplink is a product
      decision and the number must be visible**, because choosing it generously is how the bound
      silently stops binding.
- [ ] **The LOWER bound stops signing becoming the bottleneck.**
      `partSize ≥ MIN_SUPPORTED_UPLINK_BYTES_PER_SEC × SIGN_ROUND_TRIP_SECONDS × SAFETY`, so a
      part takes longer to transfer than its URL takes to mint. Below it the uploader spends its
      time waiting on the API rather than on S3, and adding parts-in-flight makes it worse rather
      than better. It is never below `MULTIPART_MIN_PART_BYTES`, which S3 imposes anyway.
- [ ] `ceil(size / partSize) ≤ MULTIPART_MAX_PARTS`, and where the two bounds cannot both be
      satisfied within that ceiling **the upper bound wins** — a slow part that completes is better
      than a fast part that 403s, and the failure the loser produces is the one this spec exists to
      remove. A test drives a size where they conflict and asserts which gave way.
- [ ] The plan is computed **server-side, in the create route**, and returned. The browser does not
      compute it: two implementations of a part plan produce two different part counts for one file,
      and the complete call would then disagree with what was uploaded.
- [ ] A declared size no plan can serve is refused at create with **413 `PayloadTooLarge`** and
      `params: {limit}`, before any S3 call — a courtesy, per FR-001 AC5, and unreachable while
      `maxUploadBytes()` clamps to 5 GiB. Asserted anyway, because that clamp is one line from being
      raised.
- [ ] A test asserts the plan at four boundaries: exactly the threshold, one byte above it, exactly
      5 GiB, and zero bytes — where an off-by-one yields a part count of 0, or a **last part below
      the 5 MiB minimum**, which S3 refuses at complete rather than at upload. *(The zero-byte case
      is unreachable through FR-005's fork and is still a valid direct unit test.)*

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
- [ ] **The `XMLHttpRequest` sweep is widened to name TWO modules, and it stays a NAMED list.**
      `apiContract.guard.test.ts` currently exempts `fileBrowser.service.ts` alone and asserts
      `offenders` is empty; a part loop in a new module turns it red. The rule it protects is that
      `XMLHttpRequest` is not an escape hatch from `apiRequest`, which a two-name allowlist serves
      exactly as well as a one-name one — and a *pattern* would not. Its companion assertion (that
      each named module still uses it) is extended to both, so an exemption cannot outlive its
      subject.
- [ ] **`onProgress` reports the AGGREGATE**, and the assertion is on an intermediate value across a
      part boundary: a test uploads a body of three parts, drives progress on part two, and asserts
      `onProgress` is called with `loaded` greater than one part and less than the total. Per-part
      progress that resets at each boundary is the obvious wrong implementation and it looks like a
      working bar.
- [ ] **The aggregate is computed from per-part bytes-sent, last value wins per part** — never a
      running sum of progress events. A retried part re-sends bytes already counted, so a sum
      over-reports and then jumps backwards, and the bar going backwards is what a user notices.
- [ ] **A failed part is retried, and the retry count names the budget that sized it.** A part that
      exhausts its retries fails the upload. This is the capability the spec exists to restore, so a
      test drives a part failing once then succeeding, and asserts the **whole file was not
      re-sent** — by counting bytes offered to the transport.
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

### FR-005: The server decides which path an upload takes

#### Description:

Multipart costs a create, N sign calls and a complete. For a small file that is worse than one call.
**But the browser must not hold the threshold**, and that constraint decides the route shape.

#### Acceptance Criteria:

- [ ] **`objects.upload` REPLACES `objects.uploadUrl`**, and returns a discriminated shape:
      `{mode: 'single' | 'multipart', url?, expiresAt?, uploadId?, partSize?, partCount?}`. A small
      file gets `mode: 'single'` with a presigned `PUT` — **one API call, exactly as today** — and a
      large one gets the plan. `objects.uploadUrl` and its tests are retired in the same change.
- [ ] **The browser never learns the threshold, and that is the point.**
      `scripts/generate_api_contract.py` emits types, `API_ERROR_CODES` and `API_ROUTES` — **not
      constants** — so a browser-side fork would need a second copy of a policy number, and a drifted
      copy sends files down the wrong path with nothing failing. The repo's mirror-and-pin pattern
      (`API_FUNCTION_TIMEOUT_SECONDS`, `FEATURE_FLAGS_KEY`) would catch drift but would still put a
      policy decision in two places. **Rejected in favour of one decision site.**
- [ ] **The discriminated shape is optional members plus a discriminant, and NOT a union**, because
      SPEC-197's closed type vocabulary has no union other than `X | None`. Widening it for this is
      precisely what the closed-vocabulary rule forbids. The browser narrows on `mode`; a test feeds
      the response type to the generator and asserts the optional members emit as optional.
- [ ] `MULTIPART_THRESHOLD_BYTES` is **two parts**: `2 × MULTIPART_MIN_PART_BYTES`. Grounded, not
      chosen — below two parts multipart buys **no retry granularity at all** (one part failing is
      the whole file, exactly like a single `PUT`) while costing two extra round trips. A test states
      that reasoning as the computation.
      *(A one-part multipart upload is legal at S3 — there is no minimum on the last part — so the
      floor is a cost argument, not a service limit, and the earlier "cannot be multiparted at all"
      reasoning was wrong by a factor of two.)*
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
      `InvalidRequest`**, `EntityTooSmall` → **400 `InvalidRequest`**. Each is added to
      `errors.DENIAL_CODES` (or the equivalent classifier entry) — **without that,
      `errors.for_exception` returns `None`, the fault re-raises and the caller gets
      `InternalError`, which the wording guard names as deliberately generic.** So the mapping is
      what makes an authored sentence possible at all.
- [ ] The browser-minted codes this path adds — an absent ETag, a part that exhausted its retries —
      are added to `errorMessages.ts` with authored sentences **and** to `apiContract.guard.test.ts`'s
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
      `decisions/storage.md`'s *Bytes go to S3 presigned* entry, the CLAUDE.md digest clause, and
      **`architecture.md`'s constraint prose plus ADR row 39**, which the completion ritual names
      explicitly and which an earlier draft of this criterion missed.
- [ ] `owed.md`'s combined row is **edited, not deleted**: it carries the expiry premise, the
      multi-GiB check, the part-level-retry residual *and* the still-live foreign-prefix residual
      with its declined-probe-route reasoning. The retry clause goes; the multi-GiB check is
      re-worded to settle that a multipart upload completes; **the expiry premise stays worded as it
      is**; the foreign-prefix residual is untouched.
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

class AbortUploadRequest(TypedDict):
    space: SpaceRef
    key: str
    uploadId: str
```

```python
# lambdas/api/apicommon/s3_config.py — additions
# Two are carried service limits; the rest are computed, and each names its budget.

MULTIPART_MIN_PART_BYTES: int            # 5 MiB — S3's published minimum, carried
MULTIPART_MAX_PARTS: int                 # 10,000 — S3's published maximum, carried
PART_URL_EXPIRY_SECONDS: int             # < ASSUME_ROLE_DURATION_SECONDS (FR-002)
MIN_SUPPORTED_UPLINK_BYTES_PER_SEC: int  # the product decision the two bounds turn on
SIGN_ROUND_TRIP_SECONDS: float           # the lower bound's budget
MULTIPART_THRESHOLD_BYTES: int           # 2 × MULTIPART_MIN_PART_BYTES (FR-005)
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
│   └── test_multipart.py            # NEW — the plan's two bounds, the capability rules
└── test_multipart_infrastructure.py # NEW — the CORS ETag and lifecycle assertions, beside the
                                     #   existing Terraform-reading bucket tests

apps/portal/src/features/file-browser/
├── fileBrowser.service.ts           # uploadFile forks on the route's answer; signature unchanged
└── multipartUpload.ts               # NEW — the part loop, retry and aggregate progress
```

## Environment Variables

None. No new `VITE_*`, no new runtime-config key, no new Lambda variable, **and no infrastructure**.

## Implementation Phases

### Phase 1: The plan and its two bounds
`s3_config`'s six constants with their computing tests — the upper bound first, since it is the one
the design's claim rests on — and FR-002's conflict case and four boundaries. No routes yet.

### Phase 2: The routes
`objects_upload.py`, the contract rows, `Route.plane` and `idempotent`, the retirement of
`objects.uploadUrl`, FR-006 whole (re-authorization, the zero-call foreign refusal, the field rule),
and FR-008's classifier entries. Regenerate the TypeScript contract.

### Phase 3: The browser
`multipartUpload.ts`, the fork on the route's answer, per-part minting, aggregate progress with the
across-a-boundary assertion, per-part retry asserted by bytes offered, the ETag round trip, and the
widened `XMLHttpRequest` sweep.

### Phase 4: Verification
A real multi-part upload from the container origin: part ETags read cross-origin (FR-007), the bar
crossing a part boundary without resetting, a cancel leaving no assembled object, and a killed tab
leaving parts the lifecycle rule owns. Added to `e2e.md` §4.2 beside SPEC-198's block.

### Phase 5: Completion ritual
`Status: Completed`, the `INDEX.md` row, the delivery doc, FR-009's superseded markers at all four
sites, the `owed.md` edit, the register clause, and the two-clause Help correction.

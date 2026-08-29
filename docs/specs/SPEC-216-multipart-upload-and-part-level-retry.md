# Spec: Multipart Upload & Part-Level Retry

**ID:** SPEC-216
**Status:** Draft
**Last Updated:** 2026-08-29
**Depends On:** SPEC-198 (the presigned upload this replaces, `objects.uploadUrl`, the `XMLHttpRequest` requirement, the `expiresAt` clamp, and the accepted residual this spec discharges), SPEC-196 (the user credential plane, `signing_client(covering=…)` and the one-hour role-chaining ceiling), SPEC-197 (the route table, the closed error enum, the declared-per-route `idempotent` flag), SPEC-020 (the upload queue, which stays in the browser and gains no state), SPEC-172 (`isWriteLockedPrefix` and the archive Deny, which includes `AbortMultipartUpload`), SPEC-161 (a cap is computed by a test against the budget that sized it)

## Overview

An upload is **one presigned `PUT`** today, and two things follow from that which a user feels.
A dropped connection restarts the whole file, because there is no part to retry. And the transfer
must fit inside one presigned window — which SPEC-198 accepted on an **unmeasured premise**, that S3
evaluates a presigned expiry when it *receives* the request rather than when the transfer completes.
If that premise is false, every upload longer than the window fails at the tail with an opaque 403
**after the bytes were sent**.

Multipart removes both. Each part is its own request under its own URL, redeemed within seconds of
being minted, so no part depends on a window outliving a long transfer. And a part that fails is a
part that can be sent again — where today the unit of retry is the file.

**This spec buys back what SPEC-198 knowingly gave up.** Its FR-005 named the route trio in as many
words —`create-multipart` / `sign-part` / `complete-multipart` — "so it is added rather than
rediscovered". This is that spec.

## Scope

### In Scope

- **Four routes**: create, sign one part, complete, abort (FR-001).
- **The part plan is computed, never chosen** — part size and part count against the budgets that
  size them (FR-002).
- **The browser's uploader**: parts in flight, aggregate progress, per-part retry (FR-003).
- **Cancel, and what happens to the parts already sent** (FR-004).
- **The threshold** below which a single `PUT` is still the right answer (FR-005).
- **The `uploadId` is a capability**, and every call re-authorizes from claims (FR-006).
- **The ETag round trip**, and the CORS premise it rests on — already true (FR-007).
- **What a user sees when a part fails, and when the whole upload does** (FR-008).
- **What this discharges**: SPEC-198's accepted residual and one of its owed live checks (FR-009).

### Out of Scope

- **Raising the 5 GiB ceiling.** `maxUploadBytes()` clamps to `S3_SINGLE_PUT_MAX_BYTES`, and
  multipart would technically permit 5 TiB. Not raised here, and the reason is that it is a
  **product decision, not a technical one**: it changes storage cost, upload duration, and what a
  user can do to a shared space by accident. After this spec it is a one-line change to a clamp,
  which is the right shape for a decision someone should take deliberately.
- **Resume across a page reload.** Not deferred — **not possible, and deliberately so.**
  `s3:ListBucketMultipartUploads` is ungranted on both buckets because it does not support the
  `s3:prefix` condition key, so granting it would leak every other user's in-progress upload keys
  (`infra/modules/data/iam.tf`). Nothing can enumerate an in-progress upload, so nothing can offer to
  resume one. FR-004 says what happens instead.
- **A server-side uploader, or any route that moves bytes.** Bytes go browser → S3. The API mints
  and never proxies; that is SPEC-198's split and this spec does not touch it.
- **Changing the upload queue's shape.** `UploadQueueProvider`, `uploadQueueReducer`,
  `UPLOAD_CONCURRENCY` and the collision round trip are unchanged (SPEC-198 FR-008 still holds).
- **Multipart for the control planes.** They copy server-side with their own roles and have their
  own limits; nothing here reaches them.
- **Any change to bucket CORS, the bucket policies, or the portal role's identity policies.** See
  the premises below — the grants this needs are already there, and asserting that is FR-007's job.

### Premises — measured 2026-08-29, not assumed

Three of these make the spec smaller than it looks, and the fourth bounds it.

1. **`ETag` is already exposed by both buckets' CORS.** `expose_headers` on
   `aws_s3_bucket_cors_configuration.user_space` and `.shared_space` is
   `["ETag", "x-amz-server-side-encryption", "x-amz-request-id", "x-amz-id-2"]`. Without `ETag` the
   browser cannot read a part's ETag and **cannot complete an upload at all** — and the failure is
   a `null` header rather than an error, so it presents as a malformed complete request. No CORS
   change; an assertion instead.
2. **`s3:AbortMultipartUpload` and `s3:ListMultipartUploadParts` are already granted** to the portal
   role on both buckets (`portal-role-permissions.json.tftpl`,
   `portal-role-shared-space.json.tftpl`). The happy path needs no IAM change.
3. **Orphaned parts are already swept.** Both buckets carry
   `abort_incomplete_multipart_upload { days_after_initiation = 7 }`. That is the net under a browser
   that never aborts — a closed tab, a crash — and it is why FR-004 can be honest about what it does
   not guarantee.
4. **Nothing can enumerate an in-progress upload** (see Out of Scope). Every design that would need
   to — resume, an orphan report, a "you have an unfinished upload" prompt — is unavailable, and the
   grant that would enable it is one this repo refused for a stated reason.

**One premise this spec does NOT settle and must not pretend to:** whether S3 evaluates a presigned
expiry at request receipt or at completion (SPEC-198 FR-005 AC8, still owed). This spec makes the
question **stop mattering for uploads** — a part is redeemed seconds after its URL is minted, so
neither reading fails it — but the same question still governs a presigned **download** of a large
object, and that owed check stays owed.

---

## Functional Requirements

### FR-001: The four routes

#### Description:

The multipart lifecycle, one route per verb, all on SPEC-196's **user** plane so the caller's own
assumed session both authorizes and signs.

#### Acceptance Criteria:

- [ ] Four routes ship, each with a `ROUTE_PLANES` entry naming `user` and an explicit `idempotent`
      flag: `POST /v1/objects/multipart` (create), `POST /v1/objects/multipart/part` (sign one
      part), `POST /v1/objects/multipart/complete`, `POST /v1/objects/multipart/abort`.
- [ ] **`idempotent` is `true` for sign-part alone**, and the reasoning is written down per route:
      signing is a local SigV4 operation that changes nothing at S3, so a retry is free. **Create is
      false** — a retried create leaks an upload id nobody will ever abort, which then costs storage
      until the lifecycle rule reaps it. **Complete and abort are false** — a retried complete after
      success is a second `CompleteMultipartUpload` against a finished upload, and a retried abort
      answers `NoSuchUpload`; both would surface as a failure for an operation that succeeded.
- [ ] `POST /v1/objects/multipart` takes `{space, key, contentType, overwrite}` — the **same shape**
      as `objects.uploadUrl`, deliberately, so the collision check and the protected-location rules
      are the ones that already exist rather than a second copy. It returns
      `{uploadId, key, partSize, partCount}`.
- [ ] The create route runs **exactly the authorization `objects.uploadUrl` runs**: space from
      claims, key contained, `assert_replaceable`, and the `overwrite: false` collision refusal
      answering **409 `Conflict`** with `params: {name}` and creating **no upload**. Asserted by
      call count: a route that creates first and checks after has already made something that needs
      aborting.
- [ ] `POST /v1/objects/multipart/part` takes `{space, key, uploadId, partNumber}` and returns
      `{url, expiresAt}`. One part per call — see FR-003 AC2 for why it is not a batch.
- [ ] `POST /v1/objects/multipart/complete` takes `{space, key, uploadId, parts: [{partNumber, etag}]}`
      and returns `{key, etag}`. `POST /v1/objects/multipart/abort` takes `{space, key, uploadId}`
      and returns `{key}`.
- [ ] **The part list is the browser's, and that is safe for a stated reason.** S3 validates every
      ETag, so a wrong list fails the complete rather than assembling the wrong object. A caller who
      completes with a *subset* of the parts they uploaded truncates their own object in their own
      prefix, which they could do by uploading a shorter file. Stated so the next reader does not
      add a server-side part audit that costs a `ListParts` per upload and buys nothing.
- [ ] Every route resolves its bucket and root prefix from the verified username and the caller's
      membership claims, refusing a foreign space **403 `AccessDenied` with zero AWS calls** — the
      same criterion SPEC-198 FR-001 AC7 states, asserted the same way, because the `uploadId`
      makes it easier to get wrong here (see FR-006).

### FR-002: The part plan is computed, not chosen

#### Description:

Part size decides how many API round trips an upload costs and whether it can complete at all.
A hard-coded number hides a wrong model (SPEC-161).

#### Acceptance Criteria:

- [ ] `MULTIPART_MIN_PART_BYTES` is **5 MiB**, S3's published minimum for every part but the last,
      carried across as a service limit and named as one — not derived.
- [ ] `MULTIPART_MAX_PARTS` is **10,000**, S3's published maximum, likewise carried.
- [ ] **`partSize` is computed per upload**, by a test, against the budget that sizes it: the number
      of **API round trips** an upload may cost. The plan is the smallest multiple of a base part
      size that keeps `ceil(size / partSize)` inside a **round-trip budget** the test names — and
      that budget, not S3's 10,000, is what binds for every file this app accepts. A 5 GiB file at
      the base size must produce a part count the test states out loud, so a later change to the
      base is visible as a change to that number.
- [ ] The plan is computed **server-side, in the create route**, and returned. The browser does not
      compute it: two implementations of a part plan produce two different part counts for one file,
      and the complete call would then disagree with what was uploaded.
- [ ] A size that no plan can serve — larger than `MULTIPART_MAX_PARTS × the largest permitted part`
      — is refused at create with **413 `PayloadTooLarge`** and `params: {limit}`, before any S3
      call. Unreachable while `maxUploadBytes()` clamps to 5 GiB, and asserted anyway, because the
      clamp is one line from being raised (see Out of Scope).
- [ ] A test asserts the plan for a file of exactly the threshold, one byte above it, exactly
      5 GiB, and a zero-byte file — the four boundaries where an off-by-one produces a part count of
      0, or a last part below the 5 MiB minimum, which S3 refuses at complete rather than at upload.

### FR-003: The browser's uploader

#### Description:

`uploadFile` gains a multipart path. Its **signature does not change** — the queue, the progress
callback and the abort signal are SPEC-020's and SPEC-198's, and this spec is not entitled to them.

#### Acceptance Criteria:

- [ ] `uploadFile` keeps its exact signature, including `onProgress(loaded, total)` and `signal`.
      Every caller and every test of the single-`PUT` path is unchanged.
- [ ] **A part's URL is minted immediately before that part is sent, never in a batch.** The same
      rule as SPEC-198 FR-008's per-file minting and for the same reason: a batch of URLs ages while
      the parts ahead of it upload, and the last one in the batch is signed long before it is
      redeemed. This is the whole reason the window stops mattering, so a batching optimisation
      would silently undo the spec.
- [ ] Parts go over **`XMLHttpRequest`**, not `fetch` — SPEC-198 FR-005's requirement is unchanged
      and for the unchanged reason, and the sweep that confines `XMLHttpRequest` to one module is
      widened only if the uploader moves.
- [ ] **`onProgress` reports the AGGREGATE**, and the assertion is on an intermediate value across a
      part boundary: a test uploads a body of three parts, drives progress on part two, and asserts
      `onProgress` is called with `loaded` greater than one part and less than the total. Per-part
      progress that resets to zero at each boundary is the obvious wrong implementation and it looks
      like a working progress bar.
- [ ] **A failed part is retried, and the retry count is a named constant with a docstring.** A part
      that fails after its retries fails the upload. This is the capability the spec exists to
      restore, so a test drives a part failing once and succeeding on retry, and asserts the
      **whole file was not re-sent** — by counting bytes offered to the transport.
- [ ] Parts in flight are bounded by a named constant. It is **not** `UPLOAD_CONCURRENCY`, which
      bounds files: three files each running four parts is twelve concurrent transfers, and the two
      constants multiply. A test states the product.
- [ ] A part's ETag is read from the response's `ETag` header and carried to complete. A missing
      header — the CORS regression of FR-007 — fails the upload with a **named** code, never a
      complete request carrying `null`.

### FR-004: Cancel, and the parts already sent

#### Description:

An aborted multipart upload leaves parts in S3 that cost storage and are invisible to every listing.

#### Acceptance Criteria:

- [ ] Cancelling calls `POST /v1/objects/multipart/abort` and resolves to code `'Cancelled'` —
      the same code and the same wording the single-`PUT` path already produces.
- [ ] The abort is **best effort and never blocks the cancel**. A user who cancels gets an immediate
      `Cancelled`; a failed abort is reported nowhere and logged in dev only. The alternative is a
      cancel that can fail, which is a control that does not work when it is most wanted.
- [ ] **What is NOT guaranteed is written down**: a closed tab, a crash or a dead network leaves the
      upload unaborted, and nothing in the browser will ever abort it. The lifecycle rule
      (`days_after_initiation = 7`, Premise 3) is the only sweep, and it is a bucket-level guarantee
      rather than this feature's. A test asserts the rule exists on **both** buckets, because it is
      now load-bearing for a feature rather than incidental hygiene.
- [ ] **No resume is offered, in the UI or in the model.** Premise 4 makes it impossible, and a
      partial implementation — remembering an `uploadId` in session state — would work until the
      reload that is the only time anyone would want it.
- [ ] The queue's existing cancel semantics are unchanged: `cancel` on a queued item removes it
      without starting, and on an in-flight item aborts and moves it to `cancelled`.

### FR-005: The threshold, and why the single `PUT` stays

#### Description:

Multipart costs a create, N sign calls and a complete. For a small file that is worse than one call.

#### Acceptance Criteria:

- [ ] Below `MULTIPART_THRESHOLD_BYTES` an upload takes the existing single presigned `PUT`
      unchanged — the same route, the same code path, the same tests.
- [ ] The threshold is **computed by a test**, not chosen: it is the size at which the multipart
      round trips are worth the retry they buy, expressed against the same round-trip budget FR-002
      names. It is at least `MULTIPART_MIN_PART_BYTES`, because a file smaller than one part cannot
      be multiparted at all.
- [ ] **Which path an upload took is observable**, in the span and in a test, by route id. Without
      it a threshold regression — every upload silently taking one path — passes every test that
      only asserts the upload succeeded.
- [ ] `MAX_UPLOAD_BYTES` still clamps to `S3_SINGLE_PUT_MAX_BYTES` (SPEC-198 FR-005). Raising it is
      Out of Scope, and a test pins the clamp so this spec cannot raise it by accident.

### FR-006: The `uploadId` is a capability

#### Description:

An `uploadId` names an upload S3 will accept parts for. It travels to the browser and back.

#### Acceptance Criteria:

- [ ] **Every route re-authorizes from claims and never from the `uploadId`.** Space resolution and
      key containment run on sign-part, complete and abort exactly as they run on create — the id is
      not evidence of anything. A test submits a valid `uploadId` with a **foreign** space and
      asserts **403 `AccessDenied` with zero AWS calls**.
- [ ] **The `(key, uploadId)` pair is checked as a pair by S3, and that is what is relied on** —
      the API keeps no server-side record. A request pairing a real `uploadId` with a different key
      fails at S3 rather than in the route, and the route returns that as a named code. Stated so
      nobody adds a DynamoDB table to track uploads: the state already lives in S3, and a second
      copy of it is a second thing that can be wrong.
- [ ] An `uploadId` appears in **no emitted record**, on the same rule as a presigned URL
      (SPEC-198 FR-007): the span carries `route_id`, the space kind, the key's **length** and the
      part number. A test emits from every call site in the four routes and asserts no field value
      contains the id.
- [ ] Each part URL is a bearer token and inherits every FR-007 rule of SPEC-198 unchanged —
      minted from `signing_client(covering=…)`, never logged, `Cache-Control: no-store`.

### FR-007: The ETag round trip

#### Description:

The browser must read each part's `ETag` response header, and a cross-origin response exposes only
the headers the bucket's CORS names.

#### Acceptance Criteria:

- [ ] A test asserts `expose_headers` on **both** bucket CORS configurations contains `ETag`. It is
      already there (Premise 1) and the test exists because it stops being incidental the day this
      ships: without it `xhr.getResponseHeader('ETag')` returns `null`, the complete request carries
      nulls, and the upload fails with an S3 error that names none of this.
- [ ] The browser fails an upload with a **named code** when a part's ETag is absent, rather than
      sending it. A complete request built from `null` ETags is a request that cannot succeed and
      whose failure names the wrong thing.
- [ ] **Live, and owed to this spec's own verification**: a real multi-part upload from the
      container origin, with the part ETags read in the browser. Offline this is a stubbed header;
      only a real cross-origin response proves the allowlist.

### FR-008: What a user sees

#### Acceptance Criteria:

- [ ] Every new failure resolves to an authored sentence, never the generic one. A test walks each
      code the multipart path can produce through `toUserText` and asserts none of them is
      *"Something went wrong. Contact the Administrator."* — SPEC-198 shipped an `Http${status}`
      code with no rule, and the guard that checks the generated enum could not see it.
- [ ] A part that exhausts its retries fails the file with wording that says nothing was saved and
      the upload can be tried again — which is true of multipart, because an incomplete upload
      assembles no object.
- [ ] The progress bar does not go backwards. A retried part re-sends bytes already counted, so a
      naive accumulator over-reports and then jumps; the aggregate is computed from **per-part
      bytes-sent**, last value wins per part, not a running sum of progress events.
- [ ] The Help guide's upload section is corrected: SPEC-198 added *"an upload is one continuous
      transfer … dropping it in again starts it from the beginning"*, which this spec makes false
      for anything above the threshold.

### FR-009: What this discharges, and what it does not

#### Acceptance Criteria:

- [ ] SPEC-198 FR-005 AC6's accepted residual — "there is **no part-level retry** any more" — is
      marked superseded **in place**, in the spec and in `decisions/storage.md`'s *Bytes go to S3
      presigned* entry, with the CLAUDE.md digest clause updated in the same commit.
- [ ] `owed.md`'s **"part-level retry behaviour — there is none, by design"** row is removed, and
      the multi-GiB upload check is **re-worded rather than deleted**: it now settles that a
      multipart upload completes, which is a different claim from the expiry premise it was written
      for.
- [ ] **The expiry premise stays owed and stays worded as it is.** This spec makes it stop mattering
      for uploads; it still governs a presigned download of a large object, and rounding it up to
      "settled" because uploads no longer depend on it is exactly the discharge-what-was-run error
      the testing docs exist to prevent.
- [ ] The `ARCS.md` residual note that records the single-`PUT` ceiling gains a marker saying which
      half moved.

---

## Data Model

```python
# lambdas/api/apicommon/contract.py — additions

class CreateMultipartRequest(TypedDict):
    space: SpaceRef
    key: str
    contentType: str
    overwrite: bool

class CreateMultipartResponse(TypedDict):
    uploadId: str            # a CAPABILITY — never logged (FR-006)
    key: str
    partSize: int            # computed server-side; the browser does not derive it
    partCount: int

class SignPartRequest(TypedDict):
    space: SpaceRef
    key: str
    uploadId: str
    partNumber: int          # 1-based, as S3 numbers them

class UploadedPart(TypedDict):
    partNumber: int
    etag: str

class CompleteMultipartRequest(TypedDict):
    space: SpaceRef
    key: str
    uploadId: str
    parts: list[UploadedPart]

class AbortMultipartRequest(TypedDict):
    space: SpaceRef
    key: str
    uploadId: str
```

```python
# lambdas/api/apicommon/s3_config.py — additions (computed by tests, never literals)

MULTIPART_MIN_PART_BYTES: int      # 5 MiB — S3's published minimum, carried
MULTIPART_MAX_PARTS: int           # 10,000 — S3's published maximum, carried
MULTIPART_THRESHOLD_BYTES: int     # computed against the round-trip budget (FR-005)
MULTIPART_ROUND_TRIP_BUDGET: int   # the budget partSize is derived from (FR-002)
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
lambdas/api/
├── apicommon/s3_config.py          # + the four multipart constants
├── routes/objects_multipart.py     # NEW — create, sign-part, complete, abort
└── test_multipart.py               # NEW — the plan boundaries, the capability rules

apps/portal/src/features/file-browser/
├── fileBrowser.service.ts          # uploadFile forks on the threshold; signature unchanged
└── multipartUpload.ts              # NEW — the part loop, retry and aggregate progress
```

## Environment Variables

None. No new `VITE_*`, no new runtime-config key, no new Lambda variable.

## Implementation Phases

### Phase 1: The routes and the plan
`s3_config`'s constants with their computing tests, `objects_multipart.py`, the contract rows and
`idempotent` flags, the create route's authorization asserted as a call count, FR-002's four
boundary cases. Regenerate the TypeScript contract.

### Phase 2: The capability rules
FR-006 whole: re-authorization on every route, the foreign-space zero-call refusal, the field rule
asserted from every call site.

### Phase 3: The browser
`multipartUpload.ts`, the fork in `uploadFile`, per-part minting, aggregate progress with the
intermediate-across-a-boundary assertion, per-part retry asserted by bytes offered, the ETag round
trip and its absent-header path.

### Phase 4: Verification
A real multi-part upload from the container origin: the part ETags read cross-origin (FR-007), the
progress bar crossing a part boundary without resetting, a cancel leaving no assembled object, and
a killed tab leaving parts that the lifecycle rule owns. Added to `e2e.md` §4.2 beside SPEC-198's
block.

### Phase 5: Completion ritual
`Status: Completed`, the `INDEX.md` row, the delivery doc, the superseded markers FR-009 requires,
the `owed.md` edits, the register clause, and the Help correction.

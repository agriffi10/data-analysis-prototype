# Completed Spec — SPEC-216: Multipart Upload & Part-Level Retry

An upload was one presigned `PUT`. A dropped connection restarted the whole file, and every
transfer had to fit inside one presigned window — which SPEC-198 accepted on an unmeasured premise
about *when* S3 evaluates that window. Both are gone.

## What was completed?

- **Four routes**, all on the user plane: `objects.upload` (create), `objects.uploadPart` (sign),
  `objects.uploadComplete`, `objects.uploadAbort`. `lambdas/api/routes/objects_upload.py`, with the
  clamp and mint-shaping extracted to `routes/_presign.py` so the two presigning surfaces share one
  implementation of how long a capability lives.
- **The plan is computed, not chosen.** `MULTIPART_PART_BYTES` = 112,500,000 bytes (≈107 MiB) from
  the slowest supported uplink (2 Mbps, a stated product decision), the 900 s window and a safety
  factor of 2. `MULTIPART_THRESHOLD_BYTES` **is** that constant, bound by identity — one quantity,
  because what fits in one window bounds a part *and* the largest trustworthy single `PUT`.
- **The browser's uploader**: `multipartUpload.ts` (part loop, per-part minting, retry with
  re-mint, monotonic aggregate progress, best-effort abort) and `xhrUpload.ts`, now the one module
  naming `XMLHttpRequest` and shared by both paths.
- **Three browser-minted codes** with authored sentences: `UploadPartsExhausted`,
  `UploadUnverifiable`, `UploadPlanUnusable`.
- **`objects.uploadUrl` retired**, after the browser switched and shipped on both live SPA surfaces.

Shipped as three PRs — routes (inert), switchover, retirement — because the three deploy workflows
race and a same-change switch can put a bundle in front of an API that has not got the route yet.

### Deliberate deviations

- **The spec's deploy-ordering premise was inverted, and is corrected in place.** FR-005 AC1 cited
  `decisions/identity-and-access/`'s "the API deploys before the SPA image" as fact. Measured:
  `Deploy App` finished **4m28s** before `Deploy Lambdas` on `8a3992b4` and **4m51s** on `696c3fdc`.
  The deploys are unordered; only a narrow `lambdas/api/**` plan lets the API win. The conclusion
  survives — the operative reason to defer a retirement is **already-loaded clients**.
- **`CompleteUploadRequest` gained `overwrite`.** FR-001 required a complete-time collision re-check
  while the Data Model gave the route nothing to read, and FR-006 forecloses recovering it
  server-side (the API keeps no record of an upload).
- **FR-002's `partSize` formula lost its size term.** `max(PART_BYTES, ceil(size / MAX_PARTS))` could
  only ever return the constant, because the refusal above it runs first — measured by rewriting the
  return to ignore it, which passed the whole suite.
- **"The pinned botocore" became "the installed botocore".** boto3 is deliberately unpinned here, so
  FR-008 AC4's assertion is a tripwire against whatever the runtime supplies.
- **The ceiling gained a server-side refusal** (Andrew's call, 2026-09-01) on the **declared**
  size. It is a courtesy, not enforcement, and weaker than S3's old unforgeable refusal of an
  over-size single `PUT`: nothing verifies the number, because the API keeps no record of an
  upload. It stops the ceiling being silently 209× what the product states; it does not stop a
  client that deliberately under-declares. Closing that needs server-side upload state.
- **`owed.md`'s discharged intermediate-percentage row was left standing** and a new row added for
  the aggregate, rather than re-pointed as FR-009 said. Re-pointing a discharged row erases a check
  that was actually run.

## What changed from earlier specs?

- **SPEC-198's "no part-level retry" residual is discharged** — marked superseded in place at all
  four sites FR-009 names: the spec, `decisions/storage/`, the CLAUDE.md digest clause, and
  `architecture.md`'s constraint prose plus ADR row 39 (which gains a pointer to new row 48).
- **`uploadFile` keeps its exact signature**, but `onProgress` is now the aggregate across parts.
  Every caller is unchanged.
- **`UPLOAD_URL_EXPIRY_SECONDS` is kept**, not retired with its route: the create route's
  single-`PUT` branch uses it.
- The retired route's guards were **re-pointed before deletion** — the marker-key refusal, and the
  window, clamp, content-type and occupied-key assertions. `test_presign.py`'s two parameterised
  suites lost only their upload case; the download coverage they also carry stands.

## Verification

Local, all exit 0: `pytest lambdas/` (2429), portal `format:check` / `lint` / `build` / 2344 tests,
`ruff`, `mypy`, `validate_docs.py`, and `generate_api_contract.py` re-run with an empty diff.

**Live checks are owed, not run** — `e2e.md` §4.2's multipart block needs a signed-in session
against the container origin. Three `owed.md` rows carry what offline cannot settle: the aggregate
bar in a real browser, whether the sign-out abort lands, and a multi-GiB completion.

## What the review found, and why it is worth reading

Four framed reviews. **No frame found a defect the previous one could have.** The three worth
recording, because each names a shape rather than an instance:

1. **A guard can pass while the thing it names is false, and look like coverage.** The part fixture
   recorded slice *sizes* but not offsets, so making every part upload part one's bytes — which S3
   accepts, because the ETags are genuine — passed all 2322 tests. Two more of the same shape
   followed: `it.each` over the list it guarded (deleting entries deleted cases), and a
   three-exit property tested on one exit.
2. **A fix is the highest-risk artifact in the loop.** One fix re-created, on the collision arm, the
   exact defect a sibling fix had just removed from the cancel arm. Another was claimed pinned in a
   commit message when the plant that "caught" it had reddened on array length rather than ordering.
3. **The worst defect was invisible to every test and to the user.** A plan whose parts could not
   cover the file uploaded a prefix of it, assembled successfully, and reported success — with the
   progress bar showing 100%, because the aggregate clamps and the queue pins a finished row.

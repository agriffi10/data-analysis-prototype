# Spec: The S3 Surface & Presigned Bytes

**ID:** SPEC-198
**Status:** Draft
**Last Updated:** 2026-08-28
**Depends On:** SPEC-197 (the transport contract this spec is the first bulk consumer of — the route table, the error envelope, `lib/apiClient.ts`, the generated TS↔Python contract, the declared-per-route retry rule, and the `409`/`413` codes it reserved for exactly this spec), SPEC-196 (the user credential plane — the assumed role that signs both the direct calls and the presigned URLs, and its `DurationSeconds` 3600 which bounds every URL minted), SPEC-195 (the verified bearer and the `error.stack` scrub a route handling presigned URLs inherits), SPEC-192 (`configValue`, and the five dev-unauth `import.meta.env` reads it deliberately left for this spec), SPEC-193 (`spa_origin`, the module output the bucket CORS allowlist gains), SPEC-187/190 (the file-ops plane — folder copy/move/delete belong there and may not reappear here; the single-file synchronous paths this spec ports), SPEC-020 (the upload queue, which stays in the browser), SPEC-106 (`toUserMessage` — and the five `passthrough` codes this surface owns), SPEC-113 (no existence oracle), SPEC-155 (the `abortSignal` guarantee this spec must restate honestly), SPEC-159 (the user-settings quarantine, which stays client-side), SPEC-172 (`isWriteLockedPrefix`, the archive write gate and the IAM Deny behind it), SPEC-173/174/175 (the saved-queries store, its top-level `.sql` filter and `Delimiter: '/'`), SPEC-185 (save-results, a single-object copy)

## Overview

Every remaining S3 call the browser makes moves behind the API, and the file **bytes** stop travelling
through the SDK entirely: an upload becomes a presigned `PUT`, a download a presigned `GET`. This is
the largest of the six ports — four modules import `@aws-sdk/client-s3`, `@aws-sdk/lib-storage` or
`@aws-sdk/s3-request-presigner` today, and between them they serve the file browser, the upload queue,
the download path, the saved-queries store and nine JSON-document reads across eight features.

Three things make it more than mechanical. **`firstFreeName` probes up to 999 keys sequentially**; left
in the browser it becomes 999 browser → API → S3 round trips, which is strictly worse than today, so it
becomes one route. **`fetch` reports no upload progress**, so the progress bar the app already ships
requires `XMLHttpRequest` — a spec that says "presigned PUT" and stops there silently deletes a shipped
feature. And **both buckets' CORS allowlists name `var.app_url` and localhost and nothing else**, so
every presigned redemption from the container origin fails preflight until this spec widens them —
SPEC-194 recorded that as out of its scope and handed it here.

This is also **the first route surface whose reads are scoped to a single user's prefix.** SPEC-197's
first ported route reads `_directory/usernames.json` under an unconditioned grant — identical bytes for
every caller — so it could not demonstrate isolation and said so. FR-013 is where that obligation lands.

## Scope

### In Scope

- **The object routes**: one-page listing, head, exists, single-object copy, move and delete, and the
  small-text read/write that carries every JSON document and every `.sql` file (FR-001, FR-003).
- **The folder-recursive service functions are DELETED, not ported** (FR-002).
- **The free-name route** — one call replacing the 999-probe loop (FR-004).
- **Presigned upload**, with `XMLHttpRequest` for progress, and the three honest consequences of a
  single `PUT` (FR-005).
- **Presigned download**, with `response-content-disposition` and the credential-lifetime clamp
  (FR-006).
- **A presigned URL is a bearer token** — minting authorization, lifetime, and the field rule (FR-007).
- **The SPEC-020 upload queue stays in the browser**; only the bytes change route (FR-008).
- **Behaviour preservation, named** — the saved-queries filter, the SPEC-159 quarantine, the marker
  basename rule, the archive write lock, `no-store` (FR-009).
- **The error codes**, including the five `passthrough` codes this surface owns and why they are minted
  client-side (FR-010).
- **Bucket CORS** for the container origin, on both buckets (FR-011).
- **Retiring the dev-unauth path** and the browser's S3 client (FR-012).
- **The route-layer half of the isolation proof SPEC-196 and SPEC-197 left owed** (FR-013) — the
  credential-layer half stays with SPEC-196's probe and is cited, not re-run.

### Out of Scope

- **Folder copy, move and delete, and multi-item selections.** Arc A owns them. `deleteObjects`,
  `deleteFolder`, `moveFolder` and `copyFolder` are removed by FR-002, not reimplemented server-side —
  a route that lists a subtree is the object-count loop Arc A moved off the browser, one layer down.
- **Athena and Glue.** `catalog/athena.service.ts` and `catalog/glue.service.ts` keep calling AWS
  directly — SPEC-199. The per-user results location stays browser-derived until then.
- **Every queue.** All seven `enqueueFifo` call sites, `sqs:SendMessage` on the portal role, and the
  `{actor, delegated_by, assurance}` contract — SPEC-200.
- **Moving the SPEC-159 read-modify-write server-side.** Settled: the API exposes get, put and copy;
  `classifyDocument`, `quarantineDocument` and the three-way parse stay exactly where they are, in
  `lib/s3Json.ts`. Moving them would re-decide a spec whose whole point was a failure path.
- **Multipart upload, and therefore part-level retry.** Accepted residual, named in FR-005 with the
  route trio a later spec would add.
- **Raising the 5 GiB single-object ceiling.** It does not move: `MAX_UPLOAD_BYTES` already defaults to
  exactly 5 GiB, which is the single-`PUT` cap.
- **Removing `@aws-sdk/*` from the SPA, retiring the Identity Pool, or deleting `lib/awsCredentials.ts`
  or `lib/credentialRetry.ts`.** Those serve Athena, Glue and SQS through SPEC-199/200 and the bearer
  itself; SPEC-202 removes the last of them. This spec removes **three** packages (FR-012 AC5), not the
  dependency class.
- **Any change to the portal role's identity policies, either bucket policy, or any Lake Formation
  grant.** The preservation claim is SPEC-196 FR-008's and this spec asserts it rather than editing it.
- **A server-side listing cache, an `s3:signatureAge` bucket-policy Deny, in-browser preview, S3
  Select, or byte-range downloads.** The `signatureAge` condition was considered and rejected: the
  bucket policy is shared with seven control planes whose own copies are signed by their own roles, and
  a request-age Deny would kill a long-running plane transfer to shorten a browser link.

### What the browser does today, and which spec replaces it

The cheapest defence against a five-spec port silently losing a behaviour. Everything below is in
`apps/portal/src`.

| Behaviour today | Owner |
|---|---|
| `listFiles(bucket, prefix, continuationToken, abortSignal)` → `ListObjectsV2` with `Delimiter: '/'`, `MaxKeys: LISTING_PAGE_SIZE` (25) | **This spec**, FR-001. Stays a synchronous browser-driven listing — SPEC-187's "the listing stays browser-side" means *not on the plane*, not *not through the API* |
| `getObjectMetadata`, `objectExists` → `HeadObject` | **This spec**, FR-001 |
| `createFolder` → `HeadObject` + `PutObject` of the zero-byte `application/x-directory` placeholder | **This spec**, FR-003 — the collision `HeadObject` moves inside the route |
| `ensurePrefixMarker`, `ensureSavedQueriesFolder` → `HeadObject` + `PutObject` of `DO_NOT_DELETE.txt` | **This spec**, FR-003; both keep their module-level "already ensured" caches |
| `copyObject`, `moveObject`, `deleteObject` (single file) | **This spec**, FR-001 |
| `useSaveResults` (SPEC-185) → `copyObject` of the Athena result object | **This spec**, FR-001 — it is a single-object copy and rides the same route |
| `deleteObjects`, `deleteFolder`, `moveFolder`, `copyFolder` | **DELETED**, FR-002. Arc A's plane (SPEC-187 → 191) is the only owner |
| `uploadFile` → `HeadObject` + `lib-storage` `Upload` (auto-multipart above 5 MiB, `PART_CONCURRENCY` 4) | **This spec**, FR-005 — one presigned `PUT` over `XMLHttpRequest` |
| `getDownloadUrl` → `getSignedUrl` in the tab, 900 s, clamped to the credential TTL, `ResponseContentDisposition` | **This spec**, FR-006 — minted server-side, same clamp, same header |
| `firstFreeName` (`useCopy.ts:80`), `for (n = 1; n < 1000)` × `objectExists` | **This spec**, FR-004 — one route. This **deliberately amends** the `ARCS.md` residual note and SPEC-187's "the probe stays in the browser" row |
| `readJsonDocument` × 9 call sites / 8 modules; `writeJsonDocument`, `quarantineDocument` (query history only) | **This spec**, FR-003 — `lib/s3Json.ts`'s four exports keep their signatures and **no caller is edited** |
| `savedQueries.service.ts`'s own `ListObjectsV2` + `PutObject` | **This spec**, FR-001/FR-003 |
| `getS3Client`, `withCredentialRetry`, the expired-credential refresh-and-retry on every S3 path | **This spec**, FR-012 — the retry moves server-side (SPEC-196 FR-006). `credentialRetry.ts` itself stays for Athena/Glue/SQS |
| `s3Client.ts`'s `REQUEST_HANDLER = {cache: 'no-store'}` on every S3 GET | **This spec**, FR-009 — carried by SPEC-197 FR-002's per-API `Cache-Control: no-store`, not lost with the client |
| `VITE_S3_DEV_UNAUTH` in three modules, the read-only test bucket, `ProtectedLayout`'s auth-gate bypass | **DELETED**, FR-012 |
| Both buckets' CORS allowlisting `var.app_url` + localhost | **This spec**, FR-011; SPEC-202 removes the CloudFront entry |
| `HIDDEN_BROWSER_FOLDERS`, `PICKER_LOCKED_FOLDERS`, `UNDELETABLE_ROOT_FOLDERS`, `isMarkerName`, `isWriteLockedPrefix`, `validateLeafName` | **Unchanged, byte for byte.** All pure; none makes an S3 call. That is the claim FR-009 exists to make checkable |

### Premises later specs must honour

1. **The API never lists more than one page.** Every `list_objects_v2` in `lambdas/api/` passes
   `Delimiter='/'` and a bounded `MaxKeys`, and no module imports `get_paginator`. This is the
   thin-API rule made mechanical (FR-002 AC4); SPEC-199 and SPEC-200 inherit it.
2. **Small text goes through the API; bytes go through S3.** The document route's byte cap is what
   holds the line — without it, it is a second upload path that works for every document in the app.
3. **A presigned URL is minted only after exactly the authorization the direct call would have had**,
   and is never logged, never cached and never returned for a key the caller may not reach (FR-007).
4. **A route's prefix is resolved from the verified username and the caller's own membership claims,
   never from a request field naming a user.** SPEC-196 Premise 3 at the route layer.
5. **`lib/s3Json.ts` keeps its four exports and its eight consumers.** A later spec that wants
   per-document routes is proposing to re-decide eight key layouts and must say so.

**AMENDED 2026-08-18 — the presigning design survives the target environment, on one unproven
condition, and the alternative was considered rather than missed.** `transition_plan.md` §3.9 moves
storage in the successor account onto **S3 Access Grants**: the backend calls `GetDataAccess` on the
user's identity-enhanced session and receives prefix-scoped temporary credentials. The client's own
architecture hands *those credentials* to the browser and has it call S3 directly — which is the one
place that design and this arc disagree.

**This spec's shape is kept, and the reason is that it is a superset.** Presigning is a local SigV4
operation, so the API can presign from whichever credential the environment requires — the assumed
portal role today, Access-Grants-vended credentials later — and S3 evaluates the grant's scope at
redemption either way. Nothing above the route changes, the browser still never holds a credential,
and the transfer still never touches compute. Handing credentials to the tab buys nothing here and
costs the negative SPEC-202's live checks are built on.

**The condition is gate G9** (`transition_plan.md` §5.5): presigning from `GetDataAccess` credentials
is *expected* to work and is **unproven**. It runs in Phase 0, long before it is needed. If it fails,
the fallback is the client's shape — scoped credentials to the browser — and two things move:
FR-005/FR-006's route surface gains a credential-vending route, and **SPEC-202's load-bearing
negative must be re-worded before it is run**, because "the browser makes no AWS call other than
presigned S3 bytes" would no longer be the target's truth.

**What this spec must therefore leave behind: the credential is a parameter of presigning, not a
constant of it.** FR-006's clamp already ties a URL's lifetime to the signing credential's remaining
lifetime rather than to a fixed number — keep it stated that way, because an Access-Grants credential
has a different maximum than SPEC-196's `DurationSeconds` 3600 and a hard-coded 3600 would mint URLs
that outlive their own signature.

---

## Functional Requirements

### FR-001: The object routes

#### Description:

The single-object surface, one route per operation, all on SPEC-196's **user** plane so the assumed
role's tags are what authorize every call.

#### Acceptance Criteria:

- [ ] Seven routes ship, each with a `ROUTE_PLANES` entry naming `user` and an explicit `idempotent`
      flag (SPEC-197 FR-008 AC2): `GET /v1/objects` (list), `GET /v1/objects/metadata`,
      `GET /v1/objects/exists`, `POST /v1/objects/copy`, `POST /v1/objects/move`, `DELETE /v1/objects`,
      and FR-004's free-name route. `idempotent` is **true** for the three reads and the free-name
      route, **false** for copy, move and delete.
- [ ] `GET /v1/objects` returns `{items: ObjectEntry[], nextToken: string | null}` — SPEC-197 FR-002's
      paged contract, where **`nextToken` is the universal half and `items` is not**: a page that is a
      bare homogeneous collection names it `items`, and this route's is one (SPEC-199's tabular results
      page carries `columns`/`rows` beside `nextToken` instead, and both are conformant), with `kind: 'folder' | 'file'` on each entry so folders and files travel in one
      array. `nextToken` is S3's `NextContinuationToken` **unmodified**, and SPEC-197 FR-002's
      round-trip test over a token containing `+`, `/` and `=` is what proves it survives the query
      string. The service maps the response back to `FileListPage`, whose type is unchanged.
- [ ] `GET /v1/objects/exists` returns **200** with `{exists: boolean}` for both answers. It does not
      return 404: `objectExists` resolves a missing key to `data: false`, and mapping absence onto the
      error arm would turn every free-name and collision check into a failure the caller must
      re-interpret.
- [ ] `POST /v1/objects/move` is **one** route performing copy-then-delete, not two calls from the
      browser. Two calls put a closed tab between them, which is a lost file rather than a failed move.
- [ ] `POST /v1/objects/copy` and `/move` take `{source: {space, key}, destination: {space, key},
      overwrite: boolean}`. With `overwrite` false and the destination occupied the route returns
      **409 `Conflict`** with typed `params: {name}` — the `HeadObject` that `copyObject` issues today
      moves inside the route, so a collision costs one call rather than two.
- [ ] The copy source is passed to boto3 as a **dict** (`{'Bucket': …, 'Key': …}`), never as a
      hand-built string. `buildCopySource`'s per-segment `encodeURIComponent` is **deleted, not
      ported**: a hand-rolled encoder that is wrong for `+` or `%` copies the wrong object or none, and
      it is right for every key in every fixture anyone would write.
- [ ] Every route resolves its bucket and root prefix from the verified username and the caller's
      membership claims (Premise 4). A request naming a `personal` space whose name is not the verified
      username, or a `shared` space with no matching membership claim, is refused **403 `AccessDenied`
      with zero AWS calls** — asserted by call count, because a refusal issued after a successful
      `AssumeRole` and `ListObjectsV2` looks identical from outside (SPEC-113, and SPEC-197 FR-014's
      own negative control).
- [ ] `abortSignal` is threaded from `listFiles` and `listSavedQueries` into `apiRequest`'s `signal`
      (SPEC-197 FR-007), **and SPEC-155 FR-006's guarantee is restated in place**: aborting now stops
      the browser waiting, it does not stop the request on the wire — a Lambda invocation cannot be
      cancelled, so the S3 listing completes and is discarded. The docstring and the superseded marker
      say so. Silently keeping the old claim is the defect; the behaviour change itself is accepted.

### FR-002: The folder-recursive functions are deleted, not ported

#### Description:

Arc A moved every operation whose cost grows with object count onto a control plane. Porting
`copyFolder` would recreate that loop inside a Lambda with a 29-second integration ceiling above it —
and it would work, for small folders, in every test anyone writes.

#### Acceptance Criteria:

- [ ] `deleteObjects`, `deleteFolder`, `moveFolder` and `copyFolder` are deleted from
      `fileBrowser.service.ts` and from the feature barrel, together with `listAllKeysUnderPrefix`,
      `deleteInBatches`, `BULK_KEY_PAGE_SIZE` and `DELETE_BATCH_SIZE`. A repo grep for each name
      returns nothing outside `docs/`.
- [ ] Their `onProgress(processed, total)` callback shape goes with them. `uploadPercent` and the
      `onProgress(loaded, total)` byte shape stay — two different callbacks with the same name is
      exactly how one gets kept by accident.
- [ ] **No route in `lambdas/api/` lists more than one page.** A test asserts every `list_objects_v2`
      call site passes `Delimiter='/'` and a `MaxKeys` no greater than the listing page size, and that
      no module in the package imports `get_paginator` or contains a pagination loop. Verified by
      committing a deliberate paginating handler and confirming red — a sweep that resolves onto the
      right files and matches nothing is SPEC-176's recorded failure.
- [ ] **They are NOT unreachable, and the deletion is a behaviour change the user has accepted
      (decision 2026-08-28).** `useDelete.ts`, `useMove.ts` and `useCopy.ts` call all four today, and
      `useFileBrowserDialogs.ts`'s `routesToPlane` reaches them on two paths: the
      `asyncFileOperations` flag being off, and a destination resolving to no known space. So after
      this spec, **flag-off means folder operations are unavailable, not synchronous** — the flag stops
      being a fallback and becomes an on/off switch for the capability.
- [ ] That consequence is written where a reader meets it: the `GATED_SURFACES` row for
      `asyncFileOperations`, and the Help guide covering rename/move/copy/delete, which currently
      describes a flag-off path that will no longer exist.
- [ ] The three hooks and their tests are updated in the same phase as the deletion. An earlier draft
      of this criterion assumed SPEC-190 had already made them dead; it had not, and a plan built on
      that assumption would have discovered three hooks mid-deletion.

### FR-003: The document routes — raw bytes, never parsed

#### Description:

One read route and one write route carry every JSON document and every `.sql` file: nine
`readJsonDocument` call sites across eight modules, one `writeJsonDocument`, one `quarantineDocument`,
plus the two marker writes and `createFolder`'s placeholder.

#### Acceptance Criteria:

- [ ] `GET /v1/objects/content` returns `{body: string, etag: string}` — the object's bytes decoded as
      UTF-8 and **not parsed**. `PUT /v1/objects/content` takes `{space, key, body: string,
      contentType: string, overwrite: boolean}` and writes `body` **byte for byte**, with no
      re-serialisation.
- [ ] **UTF-8 is the contract, and it is what the browser already does.** `readJsonDocument` reads
      `response.Body.transformToString()` today, which is a UTF-8 decode, so the route changes nothing
      about what a caller sees. Stated because "raw bytes" and "a JSON string field" cannot both be
      unconditionally true: a body that is not valid UTF-8 cannot survive the envelope, and every one of
      the nine documents on this route is authored by this app. The route refuses an undecodable body
      rather than substituting replacement characters — a silent `errors='replace'` writes corruption
      back on the next read-modify-write.
- [ ] **Parsing server-side is the wrong implementation that looks identical.** It works for every
      healthy document and makes an unparseable one a 500 — which makes SPEC-159's whole quarantine
      path unreachable, because `classifyDocument` never sees the body it must classify as
      `unparseable`. A test stores a deliberately malformed document, reads it through the route, and
      asserts the exact bytes arrive and `classifyDocument` returns `{readable: false, reason:
      'unparseable'}`. **The fixture is valid UTF-8 that is not valid JSON** — that is SPEC-159's actual
      subject: `classifyDocument` runs on the **decoded string** and returns `unparseable` for a failed
      `JSON.parse`, a wrong shape or a below-current version. It is not a byte-level-corruption path, and
      a fixture of invalid UTF-8 would be testing the previous criterion instead of this one.
- [ ] Re-serialising on write is the same defect on the other side: it changes key order and whitespace,
      which breaks nothing visible and breaks byte-identity. A test writes a document with a
      non-alphabetical key order and asserts the stored bytes match the input exactly.
- [ ] **`MAX_DOCUMENT_BYTES` is computed by a test, not asserted** (SPEC-161's rule), naming the
      schedulable unit it measures: the largest document the app authors, against Lambda's 6 MB
      synchronous response payload and API Gateway's 10 MB request payload, whichever binds first. A
      read above the cap returns **413 `PayloadTooLarge`**; a write above it is refused before any S3
      call. Without the cap this route is a second upload path that bypasses FR-005 entirely and works
      perfectly up to 6 MB — which is Premise 2's whole content.
- [ ] `lib/s3Json.ts`'s four exports — `classifyDocument`, `readJsonDocument`, `writeJsonDocument`,
      `quarantineDocument` — keep their exact signatures. `quarantineDocument` goes through
      **`POST /v1/objects/copy`**, not through the content routes, to the same
      `${key}.unreadable-{basicUtcTimestamp}-{8 hex}.json` key — so the bytes still never enter the
      browser, and the random token stays load-bearing against the two-tab race.
- [ ] **None of the consumer modules is edited** — seven import `s3Json` today (measured 2026-08-28) — `queryHistory`, `notifications`,
      `sharedSpaces`, `featureFlags`, `dataQualityReport`, `dataQualityRuns`, `savedQueries` and (from
      SPEC-197) `userDirectory`. Asserted in the diff. This is the cheapest available proof of
      SPEC-197 FR-009's claim that `ServiceResult<T>` is unchanged at the service boundary.
- [ ] `readSavedQuery` reads a `.sql` **text** file through `readJsonDocument<string>` and keeps doing
      so; the route returning a raw string is what makes that continue to work. **`s3Json.ts`'s docblock is left alone.** An
      earlier draft told the builder to correct its "seven services" to eight. Measured: there are
      **seven** importing modules, and the docblock's sentence is about the skeleton those seven
      services had written out — a statement of origin, not a live count. The "correction" would have
      written a new error into a file this spec is otherwise not editing.
- [ ] `createFolder`, `ensurePrefixMarker` and `ensureSavedQueriesFolder` use `PUT
      /v1/objects/content` with `overwrite: false` and their existing bodies and content types
      (`''` + `application/x-directory`; the two marker bodies + `text/plain`). Their module-level
      "already ensured" caches and `__resetPrefixMarkerCache` / `__resetSavedQueriesFolderCache` are
      unchanged.
- [ ] Their separate `objectExists` pre-checks are **deleted** in favour of the route's own 409. A test
      counts the API calls per `ensureSavedQueriesFolder` and asserts one, not two.

### FR-004: The free-name route

#### Description:

`firstFreeName` walks `(1)` … `(999)`, one `HeadObject` per candidate, inside `useCopy`. Behind the API
each probe becomes a browser → API → S3 round trip. One route resolves it server-side.

#### Acceptance Criteria:

- [ ] `POST /v1/objects/free-name` takes `{space, prefix, baseName, kind: 'file' | 'folder'}` and
      returns `{name: string}`. It is declared **`idempotent: true`** — SPEC-197 FR-008 AC2 names this
      exact route as the reason idempotency is declared rather than derived from the method.
- [ ] The browser makes **exactly one** call per gesture. A test asserts one `apiRequest` for a
      same-folder copy, and SPEC-190 FR-001's "the probe runs once" assertion is re-expressed against
      the call count rather than against a probe sequence.
- [ ] `numberedName` moves to Python and the TypeScript copy is **deleted**. A sweep asserts no module
      under `apps/portal/src` constructs a `{name} (N)` candidate. Two implementations of a naming rule
      look identical until one of them changes.
- [ ] **Exhaustion and failure are now distinguishable, and today they are not.** `firstFreeName`
      returns `null` both when 999 names are taken and when a probe errors, and the caller renders one
      message for both. The route returns **409 `Conflict`** with `params: {attempts}` on exhaustion and
      a real failure code otherwise; the client keeps the existing wording for the first and maps the
      second through `toUserMessage`.
- [ ] The 999 bound becomes a named constant with a docstring, replacing the inline `n < 1000` literal.
      It is **not** re-derived: it is the shipped behaviour, carried across.
- [ ] The route issues at most one `HeadObject` per candidate and stops at the first free name — a test
      asserts the head count for a prefix holding `(1)` and `(2)` is exactly three.
- [ ] This **deliberately amends** two written records: `ARCS.md`'s "deliberate residuals, recorded so
      this arc inherits them knowingly", and SPEC-187's table row "the probe stays in the browser". Both
      get a superseded marker saying the probe left the browser for the API, not for the plane.

### FR-005: Presigned upload, and the `XMLHttpRequest` requirement

#### Description:

`uploadFile` stops constructing an SDK `Upload` and instead asks the API for a presigned `PUT`, then
sends the bytes to S3 itself.

#### Acceptance Criteria:

- [ ] `POST /v1/objects/upload-url` takes `{space, key, contentType, overwrite}` and returns
      `{url: string, expiresAt: string}`. With `overwrite: false` and the key occupied it returns
      **409 `Conflict`** with `params: {name}` and mints **no URL** — asserted by the response body
      carrying no `url` field, because a route that mints first and checks after has already handed out
      the capability.
- [ ] **The upload URL is clamped to the signing session's remaining lifetime, exactly as the download
      URL is** (FR-006). `getDownloadUrl` already computes
      `Math.min(requested, remainingCredentialSeconds(client))` today and `uploadFile` has no expiry at
      all to inherit one from, so this clamp is new code on the path where it matters most: an upload
      URL outliving its session 403s **at the tail of a long transfer**, after the bytes were sent, and
      with `UPLOAD_CONCURRENCY` 3 a deep queue puts that failure on the files a user waited longest
      for. A test asserts the returned `expiresAt` is never later than the credentials' own expiry, and
      a second asserts the clamp is read from the **same** helper the download route uses, because two
      copies of one arithmetic is how one of them stops being clamped.
- [ ] **The bytes are sent with `XMLHttpRequest`, not `fetch`.** `fetch` fires no upload-progress event,
      so `onProgress(loaded, total)` — which drives `UploadList`, `uploadPercent` and
      `useFileUpload`'s single-file bar — cannot be produced from it. A `fetch` implementation uploads
      correctly and leaves the bar at 0% until it jumps to 100%, so **the assertion is on the
      intermediate value**: a test asserts `onProgress` is called at least once with `0 < loaded <
      total`. "The upload succeeded" passes over the defect.
- [ ] `uploadFile` keeps its exact signature, including `onProgress` and `signal`. `xhr.abort()`
      replaces `upload.abort()`; the abort still resolves to code `'Cancelled'`, and the listener is
      still removed in `finally`.
- [ ] **`XMLHttpRequest` is confined to this one module**, and SPEC-197 FR-007's sweep is widened
      accordingly: no module under `apps/portal/src` other than `fileBrowser.service.ts` names
      `XMLHttpRequest`. Without the widening the sweep forbids `fetch` and permits the same escape
      hatch under another name.
- [ ] **Three consequences, stated rather than discovered:**
      (1) `lib-storage` auto-multiparts above `MULTIPART_PART_SIZE` (5 MiB) and a single `PUT` caps at
      5 GiB — which is exactly `DEFAULT_MAX_UPLOAD_BYTES`, so **the ceiling does not move**;
      (2) there is **no part-level retry** any more — a dropped connection restarts the whole file,
      where `lib-storage` retried one 5 MiB part. Accepted residual; the multipart route trio a later
      spec would add is `create-multipart` / `sign-part` / `complete-multipart`, named here so it is
      added rather than rediscovered;
      (3) `MULTIPART_PART_SIZE` and `PART_CONCURRENCY` become dead and are deleted.
- [ ] `MAX_UPLOAD_BYTES` is **clamped**: `min(configured, S3_SINGLE_PUT_MAX_BYTES)` where the latter is
      5 GiB, computed by a test against the S3 `PutObject` limit that sizes it. Today an operator who
      raised `VITE_MAX_UPLOAD_BYTES` above 5 GiB got multipart; after this spec they would get an
      `EntityTooLarge` from S3 at the end of a long upload, with no failing test anywhere.
- [ ] **The expiry is evaluated when S3 receives the request, not when the transfer completes** — AWS
      documents that a transfer begun just before expiry continues past it, and that a dropped
      connection retried after expiry fails. That is the premise the whole single-`PUT` design rests
      on, and it is confirmed live in Phase 5 with a real multi-GiB upload; if it were false, every
      large upload would fail at the tail with an opaque 403 after the user waited.

### FR-006: Presigned download

#### Acceptance Criteria:

- [ ] `POST /v1/objects/download-url` takes `{space, key, fileName?}` and returns
      `{url: string, expiresAt: string}`. `getDownloadUrl` keeps its signature and its
      `ServiceResult<DownloadUrl>` return; `triggerBrowserDownload` and `useFileDownload`'s
      `downloadingKey` re-entrancy guard (SPEC-081) are unchanged.
- [ ] `ResponseContentDisposition` is built server-side with the **same** RFC 6266 quoted-string
      escaping — backslashes first, then quotes — because S3 permits `"` in a key and an unescaped one
      closes the quoted string early and lets the rest of the filename be read as parameters. The
      existing TypeScript escaping is deleted; a Python test drives a key containing `"` and `\` and
      asserts the header byte-for-byte.
- [ ] The default expiry stays **900 s** and is **clamped to the remaining lifetime of the assumed
      credentials**, exactly as `getDownloadUrl` clamps it today. SPEC-196 sets `DurationSeconds` to
      3600 and caches credentials per container, so the remaining lifetime is routinely far below
      3600 — and a URL minted for longer than its signing session lives returns **403 at redemption**,
      which reads as a permissions bug and not as an expiry. A test asserts the returned `expiresAt` is
      never later than the credentials' own expiry, and **drives it with a credential whose remaining
      lifetime is below the configured duration** — the clamp must read the credential, never
      `DurationSeconds`. The two agree today and will not later: `transition_plan.md` §3.9 signs from
      Access-Grants-vended credentials in the target, whose maximum differs, and a clamp computed as
      `min(900, DURATION_SECONDS)` passes every test here and mints URLs that outlive their own
      signature there.
- [ ] `expiresAt` is returned so the caller can distinguish an expired link from a denial. It is a
      new field on an existing shape and is additive (SPEC-197 Premise 3).

### FR-007: A presigned URL is a bearer token

#### Description:

AWS's own words: presigned URLs "are bearer tokens that grant access to those who possess them". The
capability is the URL, so everything that would be true of a credential is true of it.

#### Acceptance Criteria:

- [ ] A URL is minted only after **exactly the authorization the direct call would have had** — the same
      space resolution, the same membership check, the same protected-location rules — and it is signed
      with the **caller's own assumed session** (SPEC-196's user plane), never the API's execution role.
      A test asserts the signing credentials come from `user_client`, not `api_client`; the wrong one
      mints a working URL against the wrong identity, which is FR-013's whole subject.
- [ ] **No presigned URL appears in any emitted record.** The field rule (SPEC-127/130) puts a
      credential out of bounds, and a URL that grants object access is one. The span carries `route_id`,
      the space kind, and the key's **length**, never the URL and never the query string. A test emits
      from every call site in the two presign routes and asserts no field value contains
      `X-Amz-Signature`. The obvious wrong implementation is a debug field stamping the response body,
      and it would look like good telemetry.
- [ ] The `error.stack` scrub SPEC-195 FR-007 established covers these routes — **and the assertion is
      a sentinel in an exception MESSAGE or a log FIELD, not a URL-shaped local.**
      `traceback.format_exception` renders each frame's **source line**, never its locals (SPEC-195
      FR-007 measured exactly that), so a test that binds a URL to a local and raises can never fail:
      the URL is not in the stack whatever the code does. The live exposure is this repo's own code
      interpolating a signed URL into a message or stamping it on a span. A test raises inside the
      signer with a sentinel-carrying URL interpolated into the raised message, and asserts the
      sentinel appears in **no byte** of any record, `error.stack` included.
- [ ] A presigned URL is **never returned for a key the caller may not reach**, and a mint for a
      protected location (`archive/` as a write destination, a `DO_NOT_DELETE.txt` key) is refused
      server-side, not only by `isWriteLockedPrefix` in the browser. Verified by **deliberate
      violation**: a Python test submits a request the browser would never send and asserts the refusal;
      a TypeScript test asserts the browser refuses with no network call. Neither runtime can reach the
      other's rule, so neither test can pass by accident (SPEC-163's precedent).
- [ ] The two presign routes emit `Cache-Control: no-store` like every other route (SPEC-197 FR-002). A
      per-route exception here would put a bearer token in a shared cache.

### FR-008: The upload queue stays in the browser

#### Description:

SPEC-020's queue — `UploadQueueProvider`, `uploadQueueReducer`, `UPLOAD_CONCURRENCY`, the collision
resolve/rename round trip, `UploadList`, `UploadDrawer`, `UploadDropzone` — is client state about a
user's session. Nothing about it moves.

#### Acceptance Criteria:

- [ ] `UploadQueueProvider.tsx`, `uploadQueueContext.ts`, `upload.types.ts`, `UploadList.tsx`,
      `UploadDrawer.tsx` and `UploadDropzone.tsx` are **unchanged**, and their tests are unchanged.
      `UPLOAD_CONCURRENCY` stays 3.
- [ ] **URLs are minted per file, at the moment that file starts uploading** — never per batch. A batch
      mint ages while the queue drains: with three files in flight and a 900 s window, the fiftieth
      file's URL would be minted long before it is redeemed and would fail preflight-clean and 403 at
      the end. A test enqueues more files than `UPLOAD_CONCURRENCY` and asserts one `upload-url` call
      per file, each issued after that file's `start` action.
- [ ] The queue's existing collision handling is preserved unchanged: `resolveOverwrite` re-requests
      with `overwrite: true`, `resolveRename` with a new key. Both are new mints, because the first
      URL was signed for the first key and a signature does not survive a rename.
- [ ] `MAX_UPLOAD_BYTES` is still enforced in **both** existing places — `uploadFile` (code `'TooLarge'`)
      and `UploadQueueProvider.enqueue`'s pre-mark — and neither costs an API call. A refusal that
      first asks the API for a URL has already paid for the thing it is refusing.

### FR-009: Behaviour preservation, named

#### Description:

The behaviours a port erodes silently, each with the assertion that catches it.

#### Acceptance Criteria:

- [ ] **The saved-queries store.** `listSavedQueries` keeps `Delimiter: '/'` and
      `MaxKeys: LISTING_PAGE_SIZE`, and `isSavedQueryKey`'s top-level `.sql` filter — `startsWith` the
      prefix, no `/` in the relative part, case-insensitive `.sql`, `!isMarkerName` — stays **in
      TypeScript**. Order stays S3's own lexicographic order, unmodified (SPEC-173). A test asserts a
      `.sql` file one folder down is not listed, which is the case `Delimiter` and the depth check each
      cover and which a server-side "filter for me" convenience would quietly change.
- [ ] **SPEC-159's quarantine.** The three-way parse, the `newer`-version refusal, the quarantine key's
      random 8-character token and the "a failed copy refuses, never silently overwrites" rule are
      unchanged, because `queryHistory.service.ts` and `s3Json.ts`'s logic are unchanged. A test drives
      the full sequence — unreadable body → copy aside → write — through the routes and asserts three
      API calls in that order.
- [ ] **`DO_NOT_DELETE.txt`.** `isMarkerName`'s basename rule and the `useFileBrowser` listing filter are
      unchanged; the delete route refuses a marker key server-side as well, and both bucket policies'
      `*/DO_NOT_DELETE.txt` Deny is what refuses it if the route ever does not. `e2e.md`
      check 2 — the bucket-policy Deny, still owed — becomes runnable through the API and is added to
      Phase 5.
- [ ] **The archive write lock (SPEC-172).** `isWriteLockedPrefix` / `writeLockRefusal` stay in the
      browser as the affordance, with their bucket asymmetry intact (root-anchored personal, any-depth
      shared). The write and delete routes enforce the same rule server-side, mirroring each bucket's
      own Deny rather than averaging them — a test runs both rules over the same keys.
- [ ] **`no-store`.** `s3Client.ts` set `cache: 'no-store'` on every S3 request so a stale JSON document
      could not be served from the HTTP cache. That client is deleted; SPEC-197 FR-002's per-API
      `Cache-Control: no-store` carries the same property. Stated because the reason lives in a comment
      in a file this spec removes, and the failure is silent — the first reader sees exactly the right
      answer.
- [ ] **The expired-credential retry.** `withCredentialRetry`'s refresh-and-retry-once wrapped **expired
      AWS credentials in the browser**, and that failure disappears with the browser's S3 client:
      SPEC-196 FR-006 re-assumes server-side when the API's own cached session has expired. A test
      asserts the ported services no longer call `getS3Client`. **An expired ID token is a different
      failure with a different owner** — a 401 from the API is SPEC-195 FR-008's contract, which this
      spec neither restates nor amends: one forced `getIdToken(true)`, one retry, and a second 401
      resolving to `SessionExpired`. The two were conflated in an earlier draft; a test here asserts
      only that this surface adds no retry of its own.

### FR-010: The error codes, and the five the SPA must keep minting

#### Description:

`lib/errorMessages.ts` carries eight `passthrough` rules whose behaviour is *render the service's own
`message` unchanged*, and **five of them belong to this surface**: `Collision`, `ProtectedObject`,
`InvalidName`, `InvalidDestination`, `TooLarge`. SPEC-197 FR-004 guards
`API_ERROR_CODES ∩ PASSTHROUGH_CODES = ∅`, so none of them may ever come back on the wire — which
means this spec is the first to need SPEC-197 Premise 4's typed `params`.

#### Acceptance Criteria:

- [ ] The API's new codes are drawn from SPEC-197's closed enum and **no new code is added to it**. A
      collision is `Conflict`, a protected location is `AccessDenied`, an oversized document or upload
      is `PayloadTooLarge`, an invalid name is `InvalidRequest`.
- [ ] `params` arrives as a **typed object on the error envelope**, declared in `contract.py` and
      generated into TypeScript like everything else — never a free-text field (SPEC-197 Premise 4).
      Every key is optional, and that is legal by declaration rather than by exception: SPEC-197 FR-005's
      vocabulary admits a `TypedDict` declared `total=False` (and `NotRequired[X]`), emitting `key?: X`.
      A test feeds `ErrorParams` to the generator and asserts the three optional keys emit as optional —
      the generator raising on it is the failure this criterion exists to catch early.
- [ ] **The five passthrough codes are minted client-side**, in the service, from `{code, params}`. A
      test drives each of the five through a real API failure and asserts the rendered message is
      **byte-identical to today's**, and that a distinctive marker placed in the server's `detail`
      appears in no `ServiceResult.error.message` and in no rendered DOM.
- [ ] The disjointness guard is exercised rather than trusted: a passthrough code is added to the
      Python contract during the build and the guard is confirmed red (SPEC-197 FR-004's own
      instruction, applied where the temptation first arises).
- [ ] `'Cancelled'`, `'SavedQueryNotFound'`, `'DataQualityReportNotFound'`,
      `'DataQualityReportUnreadable'`, `'QueryHistoryNewerVersion'` and `'QueryHistoryQuarantineFailed'`
      are all still produced by their own services from route outcomes; none moves to the wire.

### FR-011: Bucket CORS for the container origin

#### Description:

`aws_s3_bucket_cors_configuration.user_space` (`infra/modules/data/s3.tf`) and
`.shared_space` (`infra/modules/shared-spaces/s3.tf`) both allowlist
`var.app_url != "" ? ["http://localhost:5173", var.app_url] : ["http://localhost:5173"]`. Neither knows
the container origin, so every presigned redemption from it fails preflight.

#### Acceptance Criteria:

- [ ] Both configurations gain **`var.spa_origin`** (SPEC-193's module output, threaded as a variable —
      never a literal), keeping the same conditional idiom so an unset value contributes no entry.
- [ ] **The variable does not exist yet, so three files are edited, not two.** A repo-wide grep for
      `spa_origin` under `infra/` returns nothing today: `var.app_url` is declared four times
      (`infra/variables.tf`, `modules/data`, `modules/shared-spaces`, `modules/auth`) and `spa_origin`
      nowhere. This spec adds a `variable "spa_origin"` block to **`infra/modules/data/variables.tf`**
      and **`infra/modules/shared-spaces/variables.tf`** (both defaulting to `""`, matching `app_url`'s
      idiom) and passes SPEC-193's output into both module blocks in **`infra/main.tf`**. A spec that
      names only the two `s3.tf` files does not plan.
- [ ] **`var.app_url` stays** for the whole arc. CloudFront is the rollback until SPEC-202 retires it,
      and removing it here would make the rollback broken in exactly the way that is only discovered
      when it is needed.
- [ ] **`http://localhost:5173` stays**, and the reason is not the dev-unauth path FR-012 deletes: after
      this spec a developer running `npm run dev` against a deployed API still redeems presigned URLs
      from `localhost`. Removing it "because dev-unauth is gone" breaks local uploads with an opaque
      browser error.
- [ ] **`allowed_methods` is unchanged — `["GET","PUT","POST","DELETE","HEAD"]` — and narrowing it is
      SPEC-202's, for the same reason `var.app_url` stays.** The two criteria are one decision: the
      rollback the CloudFront entry preserves is a rollback to the **current bundle**, which issues
      `HEAD` (`objectExists`, `getObjectMetadata` and every collision pre-check — three `HeadObjectCommand`
      sites in `fileBrowser.service.ts` alone), `DELETE` (`DeleteObjectCommand`, `DeleteObjectsCommand`)
      and multipart `POST` (`lib-storage`'s `Upload` above 5 MiB). Narrowing to `["GET","PUT"]` here
      keeps the rollback origin allowlisted while breaking every method it uses, which is a rollback
      that fails only when it is needed. SPEC-202 narrows the list in the same merge that retires the
      distribution, and **both specs state the same end state** so neither can drift.
- [ ] `allowed_headers = ["*"]` is **deliberately not narrowed**, and the reason is recorded: the header
      set a presigned `PUT` carries depends on what the signer signed, and a missing entry fails the
      *preflight*, which the browser reports as a generic network error (SPEC-197 FR-007). Narrowing it
      is a change whose failure mode is an opaque error at the first upload.
- [ ] `expose_headers` and `max_age_seconds` (3000) are unchanged on both buckets.
- [ ] **No bucket policy changes, and here is why from the code:** a presigned URL is signed by the
      **portal role's** assumed session, so `aws:PrincipalArn` at redemption resolves to the portal
      role's IAM ARN — already in the user-space bucket policy's allowlist (SPEC-196 FR-008 AC2). The
      API's own execution role signs nothing that reaches these buckets and must **not** be added. A
      test asserts the allowlist is unchanged, because "it needed no expansion" and "we forgot to check"
      are indistinguishable in a diff.
- [ ] The archive, admin, artifacts, static-assets and trail buckets have no CORS configuration and gain
      none. Stated because "add CORS for the new origin" reads as a fleet-wide change.

### FR-012: Retiring the dev-unauth path and the browser's S3 client

#### Description:

`VITE_S3_DEV_UNAUTH` works by calling S3 from the browser, which is the thing this arc removes. It
supersedes a CLAUDE.md Key Decision.

#### Acceptance Criteria:

- [ ] All three read sites go: `fileBrowser.service.ts`'s `devUnauthenticated` const and `listFiles`'s
      branch, `ProtectedLayout.tsx`'s `devBypass` and its `if (devBypass) return <AppShell><Outlet /></AppShell>`
      auth-gate bypass, and `FilesPage.tsx`'s `devUnauthenticated`, `devBucket`, `devPrefix`,
      `devConnections`, `noopSelect` and the read-only target it substitutes.
- [ ] Five variables leave `apps/portal/.env.example` and the repo entirely: `VITE_S3_DEV_UNAUTH`,
      `VITE_S3_BUCKET_NAME`, `VITE_S3_ROOT_PREFIX`, `VITE_AWS_ACCESS_KEY_ID`,
      `VITE_AWS_SECRET_ACCESS_KEY`. A repo grep for each returns nothing outside `docs/`.
- [ ] **`lib/support.test.ts`'s `devUnauthBypass` block is deleted whole, and it is what catches a
      partial removal on the way out.** The block is two layers: an `it.each` over a three-entry
      `BYPASS_SITES` list asserting the literal `import.meta.env.DEV && import.meta.env.VITE_S3_DEV_UNAUTH
      === 'true'` form and exactly one read per file, and — the load-bearing one — a guard-the-guard that
      globs every non-test module through Vite's `import.meta.glob(… {query: '?raw'})` and asserts
      **set equality** between the modules containing `VITE_S3_DEV_UNAUTH` and `BYPASS_SITES`. So
      removing two of the three sites and leaving one turns that set-equality red; the block does not
      quietly keep passing. It is deleted because its **subject** is gone, not because it was weak, and
      it is deleted only once the grep below returns nothing — the glob guard is strictly stronger than
      the grep while the block exists, and the grep is what remains after it.
- [ ] `lib/s3Client.ts` is deleted, with `s3Client`, `getS3Client`, `CHECKSUM_OPTS` and
      `REQUEST_HANDLER`. `lib/s3Errors.ts` is deleted if its last caller went with it, kept otherwise —
      decided by a call-count test, not by inspection.
- [ ] **`lib/clients.test.ts` and `lib/clientAdapters.test.ts` are this spec's, and they are consolidated
      multi-subject files rather than companions that travel with their module.** `clients.test.ts` holds
      four `describe`s — `athenaClient`, `glueClient`, `s3Client`, `awsCredentials`; `clientAdapters.test.ts`
      holds two — `sqsClient` and `s3Json`. This spec **deletes the `s3Client` describe** and **rewrites the
      `s3Json` one against the document routes**, because `lib/s3Json.ts` survives with its innards
      re-pointed and its four exports and eight consumers unchanged (FR-003) — a rewrite, never a deletion.
      The `awsCredentials` describe stays (FR-012 keeps `getIdToken`). **SPEC-199** removes the `athenaClient`
      and `glueClient` describes, **SPEC-200** the `sqsClient` one, and **SPEC-202** verifies what is left
      rather than deleting further. Naming the owner per describe is the point: a file with no owner is
      deleted by whoever gets there first, taking the surviving subjects with it.
- [ ] **Three dependencies leave `apps/portal/package.json`: `@aws-sdk/client-s3`,
      `@aws-sdk/lib-storage` and `@aws-sdk/s3-request-presigner`**, with a sweep asserting no module
      under `apps/portal/src` imports any of them. **`@aws-sdk/client-athena`, `-glue`, `-sqs` and
      `aws-amplify` all stay** — SPEC-199 and SPEC-200 port their callers, the Identity Pool still
      mints browser credentials for them (through `aws-amplify/auth`'s `fetchAuthSession`; there is no
      `@aws-sdk/credential-providers` dependency and nothing here adds one), and **SPEC-202** removes
      the dependency class and adds the enumerating lint rule. Three of the six `@aws-sdk/*` entries
      leave here; this spec's sweep names those three and claims nothing about the other three.
- [ ] `lib/awsCredentials.ts` and `lib/credentialRetry.ts` are **kept**: `getIdToken` is the bearer's
      source (SPEC-195) and `withCredentialRetry` still serves Athena, Glue and SQS.
- [ ] Local development points the SPA at a locally-run or deployed API. `.env.example` and the README
      say how, and the dev story is written down rather than implied by the absence of the old one.
- [ ] A `decisions/` entry records the supersession, and a **superseded marker** lands at every site
      still stating the old claim — CLAUDE.md's *Dev-unauth path* Key Decision line,
      `architecture.md`, and `.env.example`'s section comment.

### FR-013: The isolation proof

#### Description:

SPEC-196 FR-010 shipped a probe route to prove isolation; SPEC-197 FR-014 removed it and recorded
explicitly that `GET /v1/user-directory` **cannot** demonstrate isolation — its grant is unconditioned
and its bytes are identical for every caller — passing the obligation here, to the arc's first
prefix-scoped routes.

**The obligation splits, and saying so is part of the requirement.** A correctly built route refuses a
foreign prefix *before* reaching AWS (FR-001), and from outside that refusal is indistinguishable from
an IAM denial. So the two layers need two different demonstrations — and **only one of them is this
spec's**, for a reason that is a fact about the account rather than a judgement call.

**There is no observation surface for the credential layer here, and no spec in this arc creates one.**
The account's only CloudTrail trail (`infra/modules/verification/cloudtrail.tf`, SPEC-186 FR-004) is a
single advanced event selector: `eventCategory = Data`, `resources.type = AWS::S3::Object`, and
`resources.ARN starts_with` the **archive** bucket, with `is_multi_region_trail = false` and management
events recorded for nothing. So there are no S3 data events for the user-space or shared-space buckets
and no `AssumeRole` events at all, and any criterion phrased as "CloudTrail shows the call was issued
and denied" **cannot fail** — it returns nothing whether the call happened or not, which is the SPEC-186
FR-004 trap (an empty result from a trail that is off reads exactly like a call that never happened)
arriving one layer up. **This spec adds no CloudTrail selector**: that is unbudgeted infra in a spec
whose only infra item is bucket CORS, and if it is ever wanted it is a spec of its own.

#### Acceptance Criteria:

- [ ] **Route layer, live against the deployed API — this is the proof this spec records.** As user A,
      `GET /v1/objects` naming user B's personal space, and again naming a shared space A is not a
      member of, each returns **403 `AccessDenied`**. The load-bearing assertion is the negative one and
      it is taken **offline, by call count**, exactly as FR-001's own criterion states it: the route
      issues **zero** botocore calls and no `AssumeRole` on the refusing path. A route that resolved the
      prefix from the request and let IAM refuse would return the same 403 with the same body, and
      nothing observable from outside the process separates the two.
- [ ] **The live half of the route-layer proof is the 403 itself and its envelope** — code
      `AccessDenied`, `detail` carrying no AWS text, and **no re-login** (SPEC-197 FR-003). Recorded as
      what it is: the deployed route refusing, with the zero-call property proved offline against the
      same handler. Claiming the live 403 proves *where* the refusal happened is the error this AC
      exists to prevent.
- [ ] **The credential layer stays with SPEC-196 and is cited, never re-run here.** The proof is
      SPEC-196 Phase 5 item 6's `GET /_identity/self` returning
      `ownPrefixListable: true, foreignPrefixListable: false` — a real call through the assumed session,
      whose `false` half is IAM refusing and whose `true` half is the paired `allowed` control — beside
      its deployed-role policy simulation. This spec **cites that recorded result by the date SPEC-196's
      script records it** (`docs/testing/arc-b-api-container-e2e.md`) rather than repeating it, and adds
      no probe of its own.
- [ ] **The `archive/` write is NOT the credential-layer proof, and the reason is written down.**
      FR-007 AC4 and FR-009 AC4 both require the write route to refuse `archive/` **server-side, in the
      route**, so a `PUT /v1/objects/content` under `{root}archive/` returns the route's own 403 —
      byte-identical to an IAM denial and issued before IAM sees anything. An earlier draft staged
      exactly that as "the one denial the route cannot fake"; it is the denial the route *always* fakes,
      and with no data-event trail on that bucket nothing distinguishes the two. It stays in Phase 5 as
      a **route-layer** check.
- [ ] **What stays owed, recorded rather than assumed discharged:** (a) an end-to-end "user A read user
      B's bytes and was refused by IAM" is **not reachable from this API**, because no route accepts a
      foreign prefix; (b) an observation that the IAM Deny under `archive/` fires against the assumed
      session, which needs a data-event trail on the space buckets that this arc deliberately does not
      create; and (c) the principal tag on the session that made a successful call, which SPEC-196 FR-004
      owns and which no assertion here restates. `ARCS.md` records all three, and records that a
      temporary foreign-prefix probe route was **declined** — a route that grants a foreign-prefix read
      in order to test that foreign-prefix reads are refused is the shape of the defect it tests for.

### FR-014: The request reaches the handler — and the invariant that stops it carrying an identity

#### Description:

**Added 2026-08-28, when the implementation plan's review found that this spec's nine endpoints cannot
be built at all.** `router.py` validates a request body against the declared type and then **discards
it**: a handler is called as `handler(RequestContext(caller, acting_as, asked_for, request_id))`, and
`RequestContext` carries `principal`, `acting_as`, `route` and `request_id` — no body, no query.
`handler.py` states the omission deliberately: *"the query string and the body never leave this
function."* There is also no contract vocabulary for query parameters, so `Route.request` describes a
body only and a `GET` route has nowhere to declare its inputs.

That omission is not an oversight to be undone. **It is SPEC-196 Premise 3 enforced by shape**: a
handler that cannot read a request field naming a user cannot be talked into trusting one. This FR
opens the channel without losing the property, and the property — not the plumbing — is what the
acceptance criteria are about.

**This FR is built FIRST, before FR-001.** It carries a high number only because renumbering thirteen
FRs would break every cross-reference in this spec and in SPEC-199 through SPEC-202.

#### Acceptance Criteria:

- [ ] A route handler receives the **validated** request body. It never receives the raw event, and
      `validate_request`'s result is what reaches it — a handler that re-parses is a second validator
      and the one nobody regenerates.
- [ ] Query parameters are **declared in the contract** and generated into TypeScript like every other
      shape, so a `GET` route's inputs are typed on both sides. `apiRequest`'s existing untyped
      `query?: Record<string, string>` is narrowed to the declared shape; a route whose query does not
      match its declaration fails at `tsc -b`, not at runtime.
- [ ] The closed type vocabulary is **not widened** to admit this. If a query declaration needs a
      shape `walk()` refuses, the answer is a different declaration, never a fallback type — SPEC-197
      FR-005's rule holds here exactly as it does everywhere.
- [ ] **The invariant is asserted, not preserved by intention.** A test submits a request body and a
      query string each carrying a field that names a *different* user (`username`, `actor`,
      `acting_as`, `space.name` pointing at a foreign personal space) and asserts the resolved identity
      is unchanged and the request is refused where FR-001 AC7 says it is refused. The assertion is on
      the **resolved identity**, never on the absence of a field name, because the next field is called
      something else.
- [ ] A sweep asserts no module under `lambdas/api/routes/` reads `event`, `headers`, or any request
      value other than the one the framework hands it. `handler.py`'s comment is rewritten to say what
      is now true — that the body reaches a handler **validated**, and that identity never does.
- [ ] The existing `/healthz` and `GET /v1/user-directory` routes are unchanged in behaviour, and
      their tests are unmodified. A framework change that quietly alters the two shipped routes is the
      failure this criterion exists to catch.

---

## Data Model

```python
# lambdas/api/apicommon/contract.py — additions (SPEC-197 FR-005 owns the mechanism)

class SpaceRef(TypedDict):
    kind: Literal["personal", "shared"]
    name: str

class ObjectEntry(TypedDict):
    kind: Literal["folder", "file"]
    key: str
    size: int | None          # None for a folder
    lastModified: str | None  # ISO-8601 UTC

class ListObjectsResponse(TypedDict):
    items: list[ObjectEntry]
    nextToken: str | None     # S3's NextContinuationToken, opaque and unmodified

class ObjectContentResponse(TypedDict):
    body: str                 # RAW bytes decoded as UTF-8 — never parsed (FR-003)
    etag: str

class PresignedUrlResponse(TypedDict):
    url: str                  # a BEARER TOKEN — never logged (FR-007)
    expiresAt: str            # <= the signing session's own expiry (FR-006)

class FreeNameResponse(TypedDict):
    name: str

# The error envelope gains ONE typed field, declared here and generated like the rest.
# It is never free text and the SPA never renders it directly (SPEC-197 Premise 4).
# `total=False` is inside SPEC-197 FR-005's closed vocabulary — optional keys are declared
# members of it, emitting as `key?: X` — so this declaration is generated, not a special case.
class ErrorParams(TypedDict, total=False):
    name: str                 # the colliding leaf name — Conflict
    attempts: int             # the free-name bound — Conflict
    limit: int                # the byte cap — PayloadTooLarge
```

```python
# lambdas/api/apicommon/s3_config.py  (values computed by tests, never literals)

MAX_DOCUMENT_BYTES: int            # against Lambda's 6 MB response / APIGW's 10 MB request
S3_SINGLE_PUT_MAX_BYTES: int       # 5 GiB — the S3 PutObject limit that clamps MAX_UPLOAD_BYTES
DOWNLOAD_URL_EXPIRY_SECONDS: int   # 900, clamped to the credential's remaining lifetime
UPLOAD_URL_EXPIRY_SECONDS: int
FREE_NAME_MAX_ATTEMPTS: int        # 999 — the shipped bound, carried across, not re-derived
```

## API / Interface Contract

Every signature below is **unchanged**; only the innards move from an SDK command to `apiRequest`.
That is the property FR-003 AC6 and FR-008 AC1 exist to make checkable.

```ts
// apps/portal/src/features/file-browser/fileBrowser.service.ts — kept, ported
export async function listFiles(bucket: string, prefix?: string, continuationToken?: string,
                                abortSignal?: AbortSignal): Promise<ServiceResult<FileListPage>>;
export async function uploadFile(params: {bucket: string; key: string; body: Blob | File;
  contentType: string; overwrite?: boolean;
  onProgress?: (loaded: number, total: number) => void;   // XMLHttpRequest — FR-005
  signal?: AbortSignal}): Promise<ServiceResult<UploadResult>>;
export async function getDownloadUrl(params: {bucket: string; key: string; fileName?: string;
  expiresInSeconds?: number}): Promise<ServiceResult<DownloadUrl>>;
// also kept: ensurePrefixMarker, isPrefixMarkerKey, deleteObject, copyObject, moveObject,
// objectExists, createFolder, getObjectMetadata, uploadPercent, validateLeafName, validateFolderName

// DELETED — Arc A owns these (FR-002)
// deleteObjects, deleteFolder, moveFolder, copyFolder

// apps/portal/src/lib/s3Json.ts — all four exports unchanged, all eight consumers untouched
export function classifyDocument<T>(opts: {...}): DocumentParse<T>;
export async function readJsonDocument<T>(opts: {...}): Promise<ServiceResult<T>>;
export async function writeJsonDocument(opts: {...}): Promise<ServiceResult<void>>;
export async function quarantineDocument(opts: {...}): Promise<ServiceResult<{quarantineKey: string}>>;
```

## Environment Variables

No new `VITE_*`, and no new runtime-config key. **Five are removed** (FR-012): `VITE_S3_DEV_UNAUTH`,
`VITE_S3_BUCKET_NAME`, `VITE_S3_ROOT_PREFIX`, `VITE_AWS_ACCESS_KEY_ID`, `VITE_AWS_SECRET_ACCESS_KEY`.

`userSpaceBucket` and `sharedSpaceBucket` stay in `REQUIRED_CONFIG`/`OPTIONAL_CONFIG` — the browser
still names a bucket in every ported service signature, and SPEC-199 removes the last non-S3 reader.
Removing them here would be a promotion-time hard failure for a value something still reads.

The API Lambda gains one required variable, on SPEC-196's convention (no default, raises at first read):

```
SHARED_SPACE_BUCKET=<the shared-space bucket name>   # var.shared_space_bucket_name
```

## File & Folder Structure

```
lambdas/api/
├── apicommon/
│   ├── s3_config.py                  # NEW — the computed caps
│   ├── spaces.py                     # NEW — verified-claim → (bucket, rootPrefix); Premise 4
│   └── protected.py                  # NEW — the marker + archive rules, server side
├── routes/
│   ├── objects_list.py               # NEW
│   ├── objects_head.py               # NEW — metadata + exists
│   ├── objects_content.py            # NEW — get/put, the byte cap
│   ├── objects_mutate.py             # NEW — copy, move, delete
│   ├── objects_free_name.py          # NEW
│   └── objects_presign.py            # NEW — upload-url, download-url
├── test_objects_routes.py            # NEW
├── test_objects_content.py           # NEW — the never-parsed assertions
├── test_presign.py                   # NEW — FR-007's field-rule + stack-scrub tests
├── test_free_name.py                 # NEW
└── test_api_thinness.py              # NEW — Premise 1's derived sweep

apps/portal/src/
├── lib/
│   ├── s3Client.ts                   # DELETED
│   └── s3Json.ts                     # innards over the document routes; exports unchanged
├── components/ProtectedLayout.tsx    # − devBypass
├── routes/FilesPage.tsx              # − the dev-unauth branch
└── features/
    ├── file-browser/
    │   ├── fileBrowser.service.ts     # ported; four folder functions deleted
    │   ├── fileBrowser.types.ts       # − MULTIPART_PART_SIZE, − PART_CONCURRENCY; clamped cap
    │   ├── useCopy.ts                 # − firstFreeName, − numberedName
    │   └── index.ts                   # barrel narrowed
    └── saved-queries/savedQueries.service.ts   # ported; filter unchanged

infra/modules/data/variables.tf             # + variable "spa_origin" (default "")
infra/modules/data/s3.tf                    # + spa_origin on the CORS allowlist; methods UNCHANGED
infra/modules/shared-spaces/variables.tf    # + variable "spa_origin" (default "")
infra/modules/shared-spaces/s3.tf           # + spa_origin on the CORS allowlist; methods UNCHANGED
infra/main.tf                               # + spa_origin passed into both module blocks
```

## Implementation Phases

### Phase 1: The routes and the caps

- `spaces.py` (Premise 4), `protected.py`, `s3_config.py`'s computed caps.
- The seven object routes, the two document routes, their contract rows, `ROUTE_PLANES` entries and
  `idempotent` flags; SPEC-197 FR-006's set-equality guards stay green.
- FR-002 AC4's thinness sweep, verified by a deliberate paginating handler.

### Phase 2: Bytes

- The two presign routes, the credential-lifetime clamp, the `ResponseContentDisposition` escaping.
- FR-007: the field rule, the `X-Amz-Signature` assertion, the inherited stack scrub, the
  deliberate-violation pair on protected locations.
- FR-004's free-name route, `numberedName` moved, exhaustion separated from failure.

### Phase 3: The browser

- `s3Json.ts` over the document routes; the eight consumers confirmed unedited.
- `fileBrowser.service.ts` and `savedQueries.service.ts` ported; the four folder functions deleted.
- `uploadFile` over `XMLHttpRequest`, the intermediate-progress assertion, the clamped cap, the widened
  sweep; per-file minting in the queue.
- FR-010: `params`, the five client-side passthrough codes, the disjointness guard exercised.

### Phase 4: CORS and the retirement

- The `spa_origin` variable in both module `variables.tf` files, its wiring in `infra/main.tf`, and the
  origin on both bucket CORS configurations. `allowed_methods` is left alone (FR-011) and the
  unchanged-bucket-policy test is what says the allowlist needed nothing.
- FR-012: three read sites, five variables, `support.test.ts`'s registry deleted, `s3Client.ts` gone,
  three packages out of `package.json`, the local-dev story written down.

### Phase 5: Verification

Real invocations, as a new section of `docs/testing/arc-b-api-container-e2e.md`. **What nothing
offline can
prove:** that a browser's preflight against the deployed bucket CORS actually succeeds from the
container origin (a CORS failure is an opaque `TypeError` and presents as "the API is down"); that a
presigned URL signed inside a Lambda by an assumed session is honoured by S3; that the expiry is
evaluated at request receipt rather than at completion; and that the `cpcommon` layer attaches at cold
start (SPEC-137 shipped instrumented code whose attachment was missing while every offline gate passed).

- **Start signed out.** A signed-in pass never tests the token path.
- Browse, page a folder past 25 entries, open details, rename, copy a file, delete a file, create a
  folder — each once, confirming one API call per gesture in the network panel and **zero** direct AWS
  calls from the browser other than presigned S3 bytes.
- **Upload a small file and watch the progress bar move.** Assert on an intermediate percentage, not on
  completion: a `fetch` implementation completes correctly and never moves the bar.
- **Upload a multi-GiB file** and confirm it completes past the 900 s window — FR-005's expiry premise,
  and the only way to settle it.
- Cancel an in-flight upload; confirm `Cancelled` and that S3 holds no partial object.
- Download a file whose name contains `"` and a space; confirm the saved filename is exact.
- A same-folder copy: **one** free-name call, and the proposed name is `{name} (1)`.
- The SPEC-159 sequence: corrupt `query-history.json` by hand, load the Query workspace, confirm the
  quarantine object appears with its random token and the app recovers.
- **`owed.md` §2.1**, still owed since SPEC-186: delete `{root}saved_queries/DO_NOT_DELETE.txt`
  through the API with `curl` and confirm the bucket-policy `AccessDenied`. It needs portal-role
  credentials, which the API now holds — this is the first time the check is runnable.
- FR-013, in order: the two foreign-space `GET /v1/objects` refusals (403 `AccessDenied`, envelope-shaped,
  no re-login), and the `PUT /v1/objects/content` under `{root}archive/` issued with `curl` rather than
  through the UI, recorded as the **route-layer** refusal it is. No CloudTrail step: there are no data
  events for these buckets and no management events at all, so a trail query here proves nothing (FR-013).
  The credential-layer citation is SPEC-196 Phase 5 item 6's dated `_identity/self` result.
- `curl` the preflight from a foreign `Origin` → no `access-control-allow-origin`; from the SPA origin
  → allowed, and from the CloudFront origin → **also allowed**, which is the rollback FR-011 preserves.
  `DELETE` and `HEAD` are still in `access-control-allow-methods`; SPEC-202 is where that changes.
- One record in `logs/service=api/`: `env`, a real build sha, `route_id`, `actor`; and **absent** — any
  `X-Amz-Signature`, any bearer substring, any email, any object body.
- **Safari** at desktop and a **400px** pass (not reachable by window resize on macOS, and
  `resize_window` reports success while changing nothing the page sees — use the device toolbar and
  assert on `matchMedia`). A Chromium pass corroborates and cannot discharge.
- **Recorded as OWED:** part-level retry behaviour (there is none — nothing to check), and the
  end-to-end foreign-prefix IAM denial, which FR-013 AC4 records as unreachable from this API.

### Phase 6: Completion ritual

- `Status: Completed`; the `INDEX.md` row; the delivery doc at
  `docs/spec-delivery/SPEC-198-the-s3-surface-and-presigned-bytes.md`, carrying the ported/deleted
  disposition of all nineteen `fileBrowser.service.ts` exports — the artefact SPEC-199 and SPEC-200 copy.
- **`decisions/` entries**, then **one line each** in CLAUDE.md's Key Decisions: (1) *bytes go to S3
  presigned and small text goes through the API*, with the document byte cap as the thing that holds
  the line, the single-`PUT` 5 GiB ceiling that does not move, the lost part-level retry, and the
  `XMLHttpRequest` requirement that keeps a shipped progress bar; (2) *a presigned URL is a bearer
  token* — signed by the caller's own session, never logged, minted only after the authorization the
  direct call would have had; (3) *the dev-unauth path is retired*, **superseding the existing Key
  Decision line**, with superseded markers in `architecture.md` and `.env.example`; (4) *the free-name
  probe moved to the API*, amending the `ARCS.md` residual note and SPEC-187's table row in place.
- A superseded marker on **SPEC-155 FR-006**'s "stops the request on the wire" guarantee (FR-001 AC8).
- `ARCS.md`: the arc entry gains what this spec found — the isolation obligation's two halves, the
  declined probe route, and that SPEC-196's `_identity/self` result is the citation for the half this
  API cannot reach.
- Component-inventory rows in the area file matching each path: `file-browser-feature.md` for the
  reshaped `fileBrowser.service.ts` and the four deletions, `foundations.md` for `s3Json.ts`'s new
  transport and `s3Client.ts`'s removal, `saved-queries-feature.md` for the ported store.
- **Help sweep: two things change and both need copy.** The upload guide gains the single-`PUT`
  consequence only if a user can see it (a dropped upload restarts rather than resumes), and the
  dev-unauth path has no user-facing surface. Everything else — every label, every message, every
  flow — is byte-identical by construction, so record that explicitly.

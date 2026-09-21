# Completed Spec — SPEC-200: The Enqueue Paths & the Delegated Actor Contract

## What was completed?

The browser's last privileged AWS writes — ten enqueues over eight FIFO control-plane queues — moved
behind the API, and every message now carries the arc's identity block. No plane's trust changed: the
raw ID token still travels in the field each plane already verifies, alongside the block rather than
in place of it. Delivered in two PRs: the server side, inert for users (#550), then the switchover
with the IAM change in the same commit (#551).

- **`apicommon/contract.py`** — `EnqueueRoute` (adding `queue`, `token_field` and `stamped` to
  `Route`), the `QUEUES` registry, and the ten routes. Registry and routes are held to set equality
  in both directions, and each queue's environment variable is joined to the API function's
  Terraform environment — a renamed variable or a swapped pair used to pass `tofu validate` and the
  whole suite.
- **`apicommon/fifo.py`** — every `MessageGroupId` and `MessageDeduplicationId`, and the only module
  that computes one (an AST sweep holds that). Both derived keys are length- and charset-checked
  before the send: a 200-character source table name or a 5000-character `requestId` became a queue
  key verbatim and came back as a generic SQS failure naming nothing, and is now a 400 saying which
  key and why.
- **`apicommon/identity_block.py`** — `{actor, delegated_by, assurance}`, nested under one top-level
  `identity` key, `delegated_by` present-and-null rather than omitted, `assurance` a closed set of one
  (`interactive`).
- **`apicommon/enqueue.py`** — the sender: stamp, serialize, refuse oversize, send.
  `MAX_MESSAGE_BYTES` is computed from SQS's 262 144 less the bearer and block allowances, and
  measured on the **serialized body after stamping**; over it is `PayloadTooLarge` (413), with nothing
  enqueued. An `AccessDenied` from SQS on this plane is this function's own misconfiguration, so it
  maps to a fault, never to a 403.
- **`apicommon/context.py`** — `RequestContext.bearer` is a `Redacted` whose `__str__`, `__repr__`
  and `__format__` render `<redacted>`, readable only through `reveal()` at one call site.
  `test_bearer_containment.py` asserts the rendering paths rather than an intention not to log.
- **`routes/enqueue.py`** — ten handlers built from one factory. None makes an AWS call, reads
  membership or assembles a message; every authorization question stays in the plane's own
  validate-authorize verb.
- **Four plane allowlists gained `identity`** (`arcommon.restore`, and the archive, file-ops and
  file-send validate-authorize verbs). `lambdas/test_plane_envelope_agreement.py` derives both
  directions — the planes' published sets, and an AST-extracted read set for the planes that have no
  allowlist — against the API's own declaration plus what the sender stamps.
- **The browser** — ten services rewritten onto `apiRequest`, signatures unchanged;
  `lib/enqueueFifo.ts`, `lib/sqsClient.ts`, `lib/spaceDigest.ts` and `@aws-sdk/client-sqs` deleted, so
  the app now ships **no `@aws-sdk/*` package at all**; the eight `VITE_*_QUEUE_URL` keys out of the
  runtime configuration and every one of its wiring sites; `discardPayload` added to
  `serviceResult.ts` so six `ServiceResult<void>` signatures did not have to widen for a `requestId`
  no caller reads.
- **IAM** — one `EnqueueControlPlaneRequests` statement on the API's execution role over the eight
  request-queue ARNs, and the portal role's eight `sqs:SendMessage` grants removed in the same change.
  There is no `aws_sqs_queue_policy` anywhere in the tree, so that identity grant is the entire access
  model; `lambdas/test_queue_writers.py` enumerates the queue-owning modules from the filesystem
  rather than from a hand-kept list.

### The ten routes

Taken from `ENQUEUE_ROUTES` in `lambdas/api/apicommon/contract.py` and the derivation map in
`apicommon/fifo.py`, not from the spec. `sha(s)` is SHA-256 of UTF-8 `s`, lower-case hex; `b(kind)` is
`USER_SPACE_BUCKET` for `personal` and `SHARED_SPACE_BUCKET` for `shared`, read from the API's own
configuration and never from a body; `norm(l)` is `l.strip()` with **both** ends' slashes removed.
A space name is trimmed and stripped of trailing slashes before the digest's slash is appended.

| Route id (path) | Queue (env var) | CBD | `MessageGroupId` | `MessageDeduplicationId` | Token field |
|---|---|---|---|---|---|
| `sharedSpace.enqueue` (`/v1/enqueue/shared-space`) | `shared-space` (`SHARED_SPACE_QUEUE_URL`) | true | the constant `shared-space` | body `requestId` | `idToken` |
| `notifications.enqueue` (`/v1/enqueue/notifications`) | `notifications` (`NOTIFICATIONS_QUEUE_URL`) | true | `principal.username`, **verified** | a fresh UUID — the only id this service mints | `idToken` |
| `tableBuild.create` (`/v1/enqueue/table-build`) | `table-builder` (`TABLE_BUILD_QUEUE_URL`) | true | `space.database`, raw | body `requestId` | `idToken` |
| `tableBuild.refresh` (`/v1/enqueue/table-refresh`) | `table-builder` | true | `space.database`, raw | body `requestId` | `idToken` |
| `tableShare.enqueue` (`/v1/enqueue/table-share`) | `table-share` (`TABLE_SHARE_QUEUE_URL`) | false | `{source.database}.{source.table}`, raw | `sha([actor, {database,table}, tableName, sorted(kind:name), floor(now/60000)])` | `actor` |
| `dataQuality.enqueue` (`/v1/enqueue/data-quality`) | `data-quality` (`DATA_QUALITY_QUEUE_URL`) | false | `sha("{b(kind)}/{norm(location)}")` — **no trailing slash** | body `requestId` | `idToken` |
| `fileSend.enqueue` (`/v1/enqueue/file-send`) | `file-send` (`FILE_SEND_QUEUE_URL`) | false | `sha("{b(kind)}/{space.name}/")`, space read under `source` | body `requestId` | `actor` |
| `archive.archive` (`/v1/enqueue/archive`) | `archive` (`ARCHIVE_QUEUE_URL`) | false | `sha("{b(kind)}/{space.name}/")` | body `requestId` | `actor` |
| `archive.restore` (`/v1/enqueue/restore`) | `archive` | false | `sha("{space.kind}/{space.name}/archive/{archiveId}/")` — **no bucket** | body `requestId` | `actor` |
| `fileOps.enqueue` (`/v1/enqueue/file-ops`) | `file-ops` (`FILE_OPS_QUEUE_URL`) | false | `sha("{b(kind)}/{space.name}/")` | body `requestId` | `actor` |

A dedup id is set **explicitly on every route**, including the three queues whose
`content_based_deduplication` is `true`: omitting it there does not error — SQS falls back to hashing
the body, which still mostly collapses double-submits — so the guard each plane was specified with
would be gone with nothing going red.

**Where this differs from the spec's own table.** The queue's registry id for table build is
`table-builder`, not `table-build` (the environment variable is `TABLE_BUILD_QUEUE_URL` either way).
Two things the spec's table has no column for shipped as well: each route declares the top-level keys
the **sender** stamps and a caller may not — `schemaVersion` and the advisory `actor` username on
shared-space, `mode` on the table refresh and on both archive routes — and every derived key is
bounds-checked, which is a review finding rather than a spec item. Otherwise the derivations are the
spec's, including the three that look like transcription slips and are not: data-quality strips both
ends where the space-keyed planes end in `/`, archive-restore carries no bucket, and four planes group
on a raw string where three hash (a raw group id over an S3 key would breach SQS's 128-character cap
for exactly the users with the deepest prefixes).

### The golden vectors, and the mistake the first attempt made

`lambdas/api/fifo_vectors.json` is the artifact SPEC-201 reads to know what it may remove. It holds
**24 vectors over all ten routes**, both space kinds and both file-ops operations, plus the two pinned
tokens and the bucket names the capture ran under.

It was captured by driving the ten **exported** TypeScript services against a stubbed SQS client from
a temporary vitest harness and recording the whole `SendMessageCommand` input — queue URL, body, group
id and dedup id — at commit **`b4344599`**, before any of the outgoing code was touched. The harness
was deliberately **not committed**: it imports the TypeScript that the second PR deletes, so it would
have been dead the moment it was useful, and the vectors it produced are the durable artifact.

**The mistake the first attempt made is the part worth carrying forward.** The harness fed the
services invented request objects, the API's request types were then written from those, and each
agreed with the other — while four of the ten routes could not have served a single real request:
`onConflict` was `skip`/`replace` where the plane takes `refuse`/`overwrite`; data-quality and
table-build carried a `name` where the planes require `bucket` and `prefix`; the shared-space actions
were camelCase against a snake_case vocabulary; file-ops sent nulls where the plane tests for a key's
presence. A fresh-context review caught it. The fix was to type **every** request object in the
harness against the app's own types, so `tsc` refuses a shape the services do not take, and to build
the route tests' bodies from the captured messages rather than from literals — which is also how
`submittedAt` and `targetName` were found.

`test_fifo_derivations.py` replays every vector and asserts the file still covers all ten routes: a
vector file that lost a route is a failure, not a smaller run. Two recorded values are deliberately
not reproduced and each has its own test rather than a quiet exemption — notifications' dedup id (a
fresh UUID on both sides) and table-share's, below.

### Deliberate deviations

- **Table-share's dedup id is the one derivation deliberately changed.** It hashed the raw ID token in
  position 0; it now hashes the **verified actor**, keeping the array's shape and its one-minute
  bucket. Table-share is the only plane with no `requestId`, so this digest is the entire
  double-submit guard, and the token made it lapse silently. Two binary properties evidence it, both
  asserted: the browser's digest **moves** across a token refresh where the new one does **not** (the
  vectors carry a second, refreshed token for exactly this), and **two different users** submitting
  the identical share in the same minute still get **different** ids — dropping the actor entirely,
  the obvious simplification, would collapse one user's share into another's and deliver nothing. The
  canonical array is rebuilt in a fixed key order, and `ensure_ascii` is off so it matches
  `JSON.stringify` byte for byte for a non-ASCII space name — a divergence no ASCII fixture could show.
- **`partitionKeys` is flattened** into one object whose per-kind fields are optional, rather than the
  three variants the browser models, because the contract's type vocabulary has no union of object
  shapes. What was accepted with it: this service no longer refuses a date field on an integer key, so
  a wrong combination comes back as a **notification** from the plane's own `_validate_partition_keys`
  rather than as an immediate 400. Projection bounds travel as **strings** for both the integer and
  the date kind, which is safe rather than lossy — the DDL builder interpolates them into one `lo,hi`
  property without arithmetic, asserted against the real builder rather than argued.
- **The notifications group id is now the verified username**, where the browser sent a
  caller-supplied one. Byte-identical for every real call, and it removes a caller's ability to
  interleave into another user's FIFO group.

## What changed from earlier specs?

- **SPEC-197's Premise 6 — "the bearer never reaches a handler" — is narrowed**, not broken:
  `apicommon/enqueue.py` holds it, wrapped, with a single `reveal()`. SPEC-201 deletes both.
- **SPEC-190 FR-003's browser-computed `MessageGroupId` is gone.** The async-submit shape it describes
  is now one `apiRequest`; the digest is derived in Python.
- **`errorMessages.ts`' `NotConfigured` has no producer any more.** The rule is kept because
  `PASSTHROUGH_CODES` is computed from that list, but the ten "… is not configured" sentences are
  gone. **A finding this spec measured and recorded rather than fixed:** an unset queue variable now
  reaches the user as *"Can't reach the server. Check your connection and try again."* — marked
  user-fixable, for a deploy fault, where the old wording named the plane and did not blame the caller.
  `ConfigError` classifies to `ApiUnavailable`, which is SPEC-197's error contract rather than this
  spec's.
- **`test_portal_role_preservation` was defanged and is not any more.** It exempted the shared-space
  template from its byte pin and compared statement *names*, so deleting the `Condition` from
  `SharedSpaceList` — turning "list the spaces your principal tags name" into "list the whole
  shared-space bucket" for every signed-in user — left the Sid set unchanged and the suite green. It
  compares whole statements now, and that mutation reddens it.
- **`.env.example`, `deploy-app.yml` and `runtimeConfig.types.ts`** lost the eight queue keys
  together. The eight `VITE_*_QUEUE_URL` **repository variables are deliberately left in place** until
  SPEC-202: they are unreferenced, but a revert needs them and re-reading eight values from
  `tofu output` is the only recovery step that is not `git revert`.

## What SPEC-201 inherits

`dlq_drain.SOURCES` and its flat `_redacted` lose their subject when the token stops being sent.
Shared-space carries an **advisory** top-level `actor` username that `_redacted` also blanks and that
`identity.actor` now supersedes. And `notifications_writer._resolve_username` branches on
`USER_ACTIONS = {markRead, markAllRead}`: the `create` arm is the trusted-producer path, written by
the seven notifying execution roles, carrying `username` in the body with no actor and no token. It is
not an enqueue route of this spec and it must survive the collapse — a `trusted_actor` applied to
every path would refuse every notification the fleet produces.

## What is owed

**Phase 5 in full. It was written up but NOT RUN**, because no browser was connected to the session
that shipped it. The steps were the arc script's
§G (deleted when Arc B closed; see [`owed.md`](../testing/owed.md) §1 for where it lives now) — ten submissions judged on the outcome, the per-plane double-submit including table-share's
across a forced token refresh, one log record per plane with four things asserted absent, the three
`curl` refusals, and the IAM simulation against both deployed roles — and the owed rows are filed in
[`owed.md`](../testing/owed.md). Nothing offline can settle that a group id computed in Python is the one the deployed queue receives (ordering has no
error path — it is visible only as *work happening*), that the widened envelope is accepted by the
deployed verbs, that the `cpcommon` layer attaches at cold start, or that the removed portal-role
grant actually denies. This also leaves **SPEC-196 FR-005's plane-declaration mechanism still without
a live subject**, which `owed.md` says these queue writes were to be.

Two operational notes for whoever runs it. `Deploy App` and `Deploy Infrastructure` **race on the
merge of #551** — the first has no path filter, the second does, neither waits — so enqueues fail
visibly and self-heal in that window; the live checks must not start until every workflow that merge
triggered is green for its sha, because an IAM simulation run before the apply lands reads exactly the
inverse of the truth on both roles. The check that needed a **second account**, a shared space
where the submitter is a non-owner member, ran on 2026-09-21 (`docs/testing/sessions.md`, 2026-09-21
night). The malformed-body DLQ path stays owed.

## Help & guides

**Nothing user-facing changed.** Every dialog, label and outcome notification is identical. The one
wording that disappears is the ten "… is not configured" refusals, unreachable in a correctly deployed
environment and now resolving to the generic administrator message — recorded above as a deliberate,
accepted loss rather than a Help edit. Swept and skipped.

## Verification

Green locally by exit code on each PR: `pytest lambdas/` (1774, then 1782), mypy, ruff,
`validate_docs.py`, `tofu fmt`/`validate`, and the portal's `build` / `test` (2174) / `lint` /
`format:check`, with the contract regenerating byte-identical. 88 browser `it`s were removed and 31
added, every removed name given a disposition — kept, rewritten at the new boundary, moved to a named
Python test that was opened and verified, or dropped with a reason. Two fresh-context diff reviews per
PR, on different frames, each finding defects worth the round. Deferred to a signed-in session:
everything under *What is owed*.

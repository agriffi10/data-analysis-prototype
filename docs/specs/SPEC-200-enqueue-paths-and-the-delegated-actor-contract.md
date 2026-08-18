# Spec: The Enqueue Paths & the Delegated Actor Contract

**ID:** SPEC-200
**Status:** Draft
**Last Updated:** 2026-08-18
**Depends On:** SPEC-195 (the verified bearer, `Principal.username`, and the `error.stack` treatment this spec extends to a module that holds the raw token), SPEC-196 (the credential planes — every route here is `Plane.API`, and the failure mapping this spec deliberately diverges from), SPEC-197 (the transport contract: route ids, the envelope, the generated TS, `apiRequest`, the retry rule, the correlation trap, `PASSTHROUGH_CODES`), SPEC-011 (the identity is a verified claim, never a caller assertion), SPEC-126 (the DLQ drain's per-plane `token_field` table and its flat `_redacted`), SPEC-157 (FIFO orders **delivery**, not executions — no AC here may say otherwise), SPEC-164/165/166/167 (the file-send envelope: flat `actor` as the raw token, and the per-submit `requestId`), SPEC-168/170 (the archive plane's two modes and its per-mode allowed-field set), SPEC-187/190 (Arc A's file-ops plane, its queue, its FIFO rules and the browser submit path this spec re-routes), SPEC-106 (`toUserMessage` is the only source of user-facing wording), SPEC-127/137/186 (`cpcommon.observability`, the field rule, `env`/`version`)

## Overview

Eight FIFO queues are the browser's only privileged writes. Every one of them is reached the same
way: `lib/enqueueFifo.ts` fetches the caller's Cognito ID token, puts it **in the message body**, and
sends with a `MessageGroupId` and a `MessageDeduplicationId` the calling service computed itself. The
control plane on the other end verifies that token and takes the actor from the verified claim.

This spec moves all ten of those sends behind the API, and adds to the message the contract the arc
settled: one top-level `identity` key holding `{actor, delegated_by, assurance}`, written by the API
from the verified bearer. It does **not** change what any plane trusts. The token keeps travelling in
the field each plane already reads, every plane keeps verifying it, and the new block rides
alongside, accepted and ignored. **SPEC-201 is what flips the planes onto `identity.actor` and stops
the token being sent, and that order is a requirement of this spec, not a note** (FR-005): reversed,
all eight planes fail closed on the first request after the API stops forwarding a token.

The block's shape and its one `assurance` value are a single contract shared with SPEC-201, and both
specs pin the same literals. They are **nested permanently** — there is no later migration to a flat
shape — because on table-share, file-send, archive and file-ops the top-level field named `actor`
**is the raw ID token today** (FR-004).

Two things make this more than a transport swap. The FIFO keys were computed in the browser and must
now be computed in Python, **byte for byte** — they are four different derivations by design, one of
them hashes the ID token itself, and a wrong one is silent: ordering and dedup have no error path,
they just stop grouping. And the API becomes the only principal that may write these queues, which
means the browser's `sqs:SendMessage` grants come off **here** — before SPEC-201 makes a forged
`actor` believable, not after.

## Scope

### In Scope

- **Ten enqueue routes over eight queues** — one per browser enqueue function, because the FIFO
  derivations differ per operation (FR-001).
- **Server-side FIFO key derivation**, preserved byte-for-byte against golden vectors captured from
  the outgoing TypeScript (FR-002), and the one derivation that cannot be preserved (FR-003).
- **The identity block** — one top-level `identity` key holding `{actor, delegated_by, assurance}`,
  its placement, why it is nested and why it stays nested (FR-004).
- **The two-step rollout**: the token keeps travelling; SPEC-201 removes it (FR-005).
- **Every plane's acceptance of the block**, including the three planes that reject unknown top-level
  fields today (FR-006).
- **The bearer's path from the router to the message body**, and the wrapper that keeps it out of
  every log record and stack trace on the way (FR-007).
- **Queue access**: the API role becomes the only writer; the portal role's eight `Enqueue*`
  statements are removed **in this spec** (FR-008).
- **The browser half**: ten services keep their signatures, `lib/enqueueFifo.ts` and
  `lib/sqsClient.ts` are deleted, the per-submit `requestId` mint stays (FR-009).
- **The envelope byte cap and the failure mapping** for a plane whose credential is the API's own
  (FR-010).
- **Observability** for a request that carries both a bearer and a user's file selection (FR-011).

### Out of Scope

Everything a reader would reasonably assume travels with "the queues moved behind the API":

- **The Lambda trust flip.** No plane drops JWKS verification, no plane reads `identity.actor` for
  authorization, the five `cognito:username` readers are not collapsed, and no plane's `token_field`
  changes. SPEC-201, and it must land after this one.
- **Stopping the token being sent.** The API keeps writing the bearer into every message for the
  whole of this spec, and FR-005 AC2's tripwire asserts it. **SPEC-201 owns the API-side drop** — the
  enqueue writer's token field, the `Redacted` wrapper, `RequestContext.bearer` and that tripwire —
  and performs it only after its own plane-side half is deployed.
- **The machine-facing door.** No non-human authorizer, no credential issuance, no
  may-this-client-act-as-X model, no rate limiting, no second value of `assurance`. `delegated_by` is
  `null` on every message this spec can produce, and the only reason the field exists now is that
  adding it later re-opens eight message contracts, eight parsers, SPEC-126's redaction and their log
  records.
- **Any change to what a plane does.** No verb is edited except to widen an allowed-field set
  (FR-006). No state machine, no IAM on any execution role, no new plane, no notification wording.
- **Any authorization decision moving into the API.** The API authenticates and stamps; every
  membership, ownership, containment and active-space check stays in the plane's validate-authorize
  verb, where it is today (FR-001 AC6).
- **The Identity Pool and the browser's other AWS calls.** S3 is SPEC-198, the catalog SPEC-199,
  retirement SPEC-202. `lib/awsCredentials.ts` and `lib/credentialRetry.ts` survive this spec.
- **Queue resource policies.** There is no `aws_sqs_queue_policy` anywhere in `infra/` today and this
  spec adds none — see FR-008 AC5 for the decision and what stands in for it.
- **The notifications DLQ.** Still deliberately undrained (circular), unchanged.

### What the browser does today, and which spec replaces it

| Today | Owner |
|---|---|
| `lib/enqueueFifo.ts` — token fetch, `SendMessageCommand`, `NotConfigured` refusal | **Deleted**, FR-009 |
| `lib/sqsClient.ts` — the SQS client and its Identity Pool credentials | **Deleted**, FR-009 |
| Ten `*.service.ts` enqueue functions computing their own group/dedup ids | **This spec**, FR-002 — same signatures, one `apiRequest` inside |
| The ID token in the message body — `idToken` on **four** planes (five of the ten routes: shared-space, notifications, table-build ×2, data-quality), flat `actor` on **four** (five routes: table-share, file-send, archive ×2, Arc A's file-ops) | **Unchanged until SPEC-201.** FR-005 |
| The plane's `verified_username(req.get(...))` at the head of every machine | **Unchanged.** SPEC-201 |
| `_ALLOWED_FIELDS` on file-send, archive (per mode) and file-ops | **Widened by one key**, FR-006 |
| SPEC-126's `SOURCES` `token_field` table and `_redacted` | **Unchanged.** SPEC-201 owns the rewrite that follows the token's removal |
| Seven `Enqueue*` portal-role statements + Arc A's eighth | **Removed**, FR-008 |
| Seven `VITE_*_QUEUE_URL` build variables + Arc A's eighth | **Removed** from the SPA; re-appear as API Lambda variables, FR-011 |

### Arc A is a merge precondition

**SPEC-187 → 191 must be complete and merged before this spec's branch opens**, the way this spec is
SPEC-201's precondition. Two of its guards are set-equality assertions that hard-fail on a missing
plane rather than passing over a smaller set: FR-001 AC2's `{route.queue} == set(QUEUES)`, and
FR-008 AC3's enumerated `.tftpl` sweep, which walks the modules on the filesystem. Neither can be
written against nine queues and later widened to ten without the widening being a second contract
change; and the file-ops allowlist FR-006 widens does not exist until SPEC-187 ships it. Every
"eight"/"ten" figure in this spec is stated post-Arc-A and none of them is a forecast.

### Premises later specs must honour

1. **The API stamps identity; it does not authorize.** A route here refuses on shape and size and
   nothing else. The day an enqueue handler checks membership, two authorities exist for one question
   and they will diverge.
2. **The FIFO keys are derived in exactly one module** (`apicommon/fifo.py`) and never in a handler.
   SPEC-165's one-builder rule, for the same reason: the tests can only prove the one builder right.
3. **`requestId` is minted in the browser, per submit, and the API mints none.** It keys the plane's
   plan, its prefix, its record and its receipt (SPEC-169), and reusing it makes a retry a silent
   no-op (SPEC-167 FR-003). A server-minted id would make every retry a new request and defeat the
   queue's only double-submit guard.
4. **The body's `requestId` and the transport's `x-request-id` are different fields and stay
   different.** SPEC-197 FR-011 forbids the client-supplied correlation header from building a key, a
   path or a dedup token; this spec's `requestId` is exactly such a key. Unifying them would put a
   caller-chosen value into the correlation field the router stamps — the trap SPEC-197 already
   found and closed.
5. **The identity block carries nothing secret**, because SPEC-126's `_redacted` is a shallow
   top-level replace: anything nested reaches CloudWatch verbatim on a dead-letter.
6. **`assurance` is a closed set and a plane may only add a value after every plane accepts it.**
   This spec ships one value; SPEC-201 owns what a plane does with one it does not accept.

---

## Functional Requirements

### FR-001: Ten routes over eight queues

#### Description:

One route per browser enqueue function, not per queue: archive and restore compute different group
ids, and table-build create and refresh carry different bodies. A route per queue would have to
declare a union the contract's closed vocabulary (SPEC-197 FR-005) cannot express, and would hide
exactly the difference that matters.

#### Acceptance Criteria:

- [ ] The ten routes of the Data Model table exist in `apicommon/contract.py`, each declaring
      `idempotent: false` and `plane: "api"`. A test asserts **every** enqueue route declares both —
      `false` because a retried enqueue is either a duplicate request or a silent no-op depending on a
      field the transport does not control (SPEC-197 FR-008), and `api` because the queue grant is on
      the API's execution role, not on the user's assumed role.
- [ ] `QUEUES` is a registry of the **eight** queues (id, env var, `content_based_deduplication` as
      deployed). A guard asserts `{route.queue for route in ENQUEUE_ROUTES} == set(QUEUES)` — both
      directions, so a queue with no route and a route naming no queue both fail (SPEC-163's set
      equality, verified by a violation in each direction during the build).
- [ ] Every enqueue route returns **200** with `{"requestId": string | null}`. Not 202: SPEC-197
      FR-001 closes the status set, and "accepted, not processed" is what every one of these call
      sites has always meant by success. `requestId` is `null` on exactly one route
      (`notifications.enqueue`, the only plane with no request id) and is otherwise the value the
      caller sent, echoed — a test asserts both, and asserts the API mints **no request id**. The one
      id it does mint is the notifications route's dedup UUID (Data Model), which is a queue key and
      never reaches a response or a body.
- [ ] `MessageDeduplicationId` is set explicitly on **all ten** sends, including the **three** request
      queues deployed with `content_based_deduplication = true` — shared-space, notifications and
      table-build, and no others (data-quality's *DLQ* is content-based, its request queue is not;
      counting DLQs gives four and is the easy mistake). This is the requirement that silently
      succeeds: on those three, omitting the explicit id does not error — SQS falls back to hashing the
      body, which still mostly collapses double-submits, so nothing goes red while the guard the plane
      was specified with is gone. A test asserts a non-empty `MessageDeduplicationId` on every send,
      and `QUEUES`' `content_based_deduplication` values are read out of the eight modules' `sqs.tf`
      **request-queue** resources rather than transcribed.
- [ ] The handlers make **zero** AWS calls other than `SendMessage` — no Cognito, no S3, no registry
      read, no membership check — asserted by client call count per route. Authorization stays in each
      plane's validate-authorize verb (Premise 1).
- [ ] A route's request type is the plane's envelope **minus** the identity fields and minus the
      token: neither is a caller input, and `validate_request` (SPEC-197 FR-005) refuses an unknown
      key, so a body attempting to supply `actor`, `identity` or a token field is a **400
      `InvalidRequest`** rather than an accepted forgery. A test sends each of those three keys and
      asserts 400 with no `SendMessage` issued.

### FR-002: The FIFO keys move to Python, byte for byte

#### Description:

Four derivation families, ten routes, and no error path: a wrong `MessageGroupId` still sends. It
changes which requests serialize behind each other and which run in parallel, and the only symptom is
a race nobody can reproduce. A wrong `MessageDeduplicationId` stops collapsing double-submits, and the
symptom is two shares, two archives, two builds.

#### Acceptance Criteria:

- [ ] `apicommon/fifo.py` owns every derivation and is the only module that computes one. An AST sweep
      asserts no module under `lambdas/api/routes/` calls `sha256`, and that `group_id_for` /
      `dedup_id_for` have exactly one definition each (SPEC-165's one-builder rule, exempted by node
      identity rather than by name).
- [ ] The derivations are exactly those in the Data Model table, including the three differences that
      look like typos and are not: data-quality's canonical string has **no trailing slash** (its
      `normalize_location` strips leading *and* trailing `/` after a `strip()`) where file-send,
      archive and file-ops end in `/`; archive-restore's canonical string carries **no bucket** at all
      (`{kind}/{name}/archive/{archiveId}/`, deliberately diverging from SPEC-170 FR-001's wording and
      from the still-live comment at `infra/modules/archive/sqs.tf`); and four planes group on a
      **raw** string (a constant, a username, a database, a `database.table`) where three hash,
      because a raw group id over an S3 key would exceed SQS's 128-character cap for exactly the users
      with the deepest prefixes.
- [ ] **Golden vectors**, captured by running the outgoing TypeScript before it is deleted — not
      written from this spec — and committed as `lambdas/api/fifo_vectors.json`. The Python must
      reproduce every vector byte-identically. A test asserts the file covers all ten routes and both
      space kinds; a vector file that lost a route is a failure, not a smaller run.
- [ ] The two bucket names that feed three derivations come from the API's own configuration
      (`USER_SPACE_BUCKET`, `SHARED_SPACE_BUCKET`), resolved from the request's `space.kind` exactly as
      `fscommon.authz` and `arcommon.authz` resolve it — **never from the request body**. Today the
      browser reads them from build-time env and falls back to `''` when unset, which silently digests
      `/{name}/`; the API's variables are required and raise at first read (SPEC-196's convention), so
      the same misconfiguration is a 500 rather than a wrong group.
- [ ] **Exactly one** group id is now derived from the **verified actor** rather than from the body —
      `notifications.enqueue`, today `input.username`, a caller-supplied string. It is the only route
      whose group id reads a username at all, so there is no second one to convert; a test asserts
      the notifications group id equals `principal.username`, that the request type has no username
      field, and that **no other route's group-id derivation reads the actor** (table-share's *dedup*
      id does, by FR-003, and is the only other one that may) — the latter half is what
      makes "exactly one" a measurement rather than a count written here. For every real call this is
      byte-identical to today; it also removes a caller's ability to interleave into another user's
      FIFO group.
- [ ] Data-quality's group id takes its bucket from the space kind, not from `space.bucket`, and the
      request type drops that field. A vector proves the resulting digest equals today's for both
      kinds — the change is a tightening whose *output* must not move.

### FR-003: table-share's dedup id — the one derivation that cannot be preserved

#### Description:

`dedupId(token, req)` hashes `[token, source, tableName, sortedRecipients, floor(now/60000)]`. The ID
token is an input. After SPEC-201 there is no token to hash, and even today the guard silently stops
collapsing across a token refresh — two submits a minute apart with a refresh between them are two
shares. Table-share is also the only plane with **no `requestId`** to fall back on, so the digest is
the entire double-submit guard.

#### Acceptance Criteria:

- [ ] The canonical array keeps its shape and its one-minute bucket, with the **verified actor**
      substituted for the token in position 0: `[actor, source, tableName, sortedRecipients, bucket]`.
      Recipients are still `kind:name`, still sorted, still `json.dumps`-ed with a separator convention
      that matches `JSON.stringify` byte-for-byte (a vector proves it; `json.dumps` defaults insert
      spaces and would produce a different digest that no test asserting "a 64-char hex string" could
      catch).
- [ ] A test asserts two submits of the same request by the same user in the same minute produce the
      **same** dedup id **when the bearer differs between them** — the case that produced two shares
      before. It is a binary assertion and it fails against the old derivation, which is the only way
      to show the change is real.
- [ ] A test asserts two different users submitting the identical share in the same minute produce
      **different** dedup ids. Dropping the actor from the canonical form entirely — the obvious
      simplification — would collapse one user's share into another's and deliver nothing.
- [ ] The divergence is recorded in `decisions.md` and in the delivery doc as the one derivation this
      spec deliberately changed, with the two properties above as its evidence. A "preserved exactly"
      claim covering all ten would be false.

### FR-004: The identity block

#### Description:

The contract the arc settled — `{actor, delegated_by, assurance}` — written by the API from the
verified bearer. It is **nested under one top-level key**, and that is forced rather than stylistic:
on table-share, file-send, archive and file-ops the top-level field named `actor` **is the raw ID
token today**. A flat verified `actor` would overwrite the token those four planes verify, which is
precisely the ordering failure this spec exists to avoid.

**It stays nested after the cutover.** SPEC-201 removes the token field rather than moving the block
into its place, so there is no second migration and no window in which one plane's `actor` is a
username while another's is still a JWT. Both specs' parsers and both specs' tests are written
against the same nested shape and the same literals.

#### Acceptance Criteria:

- [ ] Every message carries exactly `{"identity": {"actor": str, "delegated_by": null, "assurance":
      "interactive"}}` as one additional top-level key, with those three field names verbatim.
      The names are the arc's settled contract and SPEC-201's parser is written against them; renaming
      them to match the envelope's camelCase would desync the two specs, so the inconsistency is
      deliberate and pinned by a test.
- [ ] `actor` is `principal.username` (SPEC-195's verified claim) and comes from nowhere else. A test
      posts a body carrying `actor`, `identity` and `username` keys and asserts the stamped value is
      the token's, and that the request was refused at validation anyway (FR-001 AC6).
- [ ] `delegated_by` is `None` on every message this spec can produce, and is present rather than
      omitted — an absent key and a null key are different to a strict parser, and SPEC-201's planes
      refuse the absent one (SPEC-201 FR-003).
- [ ] `assurance` is `Literal["interactive"]` — a closed set of one. A test asserts the literal
      has exactly one member, so widening it is a deliberate edit that a reviewer sees. The value
      names the assurance **kind**, not the mechanism that produced it: `verified-id-token` would have
      to be renamed the day the provider changes or the machine-facing door mints `delegated`, and
      SPEC-201's `ACCEPTED_ASSURANCE` already reserves and refuses that second value. **The literal is
      one contract across the two specs, and this spec is where it is declared** — SPEC-201's
      `cpcommon.actor.ASSURANCE_INTERACTIVE` is asserted equal to the value minted here, from the
      module that mints it (`conftest.py` puts every layer on `sys.path`, so one test can import
      both), rather than restated on the plane side where the two could drift.
- [ ] The block contains no token, no email and no claim other than the username. Asserted by key set,
      not by inspection: SPEC-126's `_redacted` replaces **top-level** keys only, so everything nested
      here is written to CloudWatch verbatim on a dead-letter (Premise 5).
- [ ] The block is stamped in `apicommon/enqueue.py`, once, for every route. A test asserts a route
      cannot send without it — the send helper is the only path to `SendMessage` (FR-002 AC1's sweep
      covers the same module).

### FR-005: The two-step rollout, and the order it must land in

#### Description:

The control-plane Lambdas verify a JWT from the message body today. This spec writes the `identity`
block **in addition to** the token, changes no plane's trust, and leaves every `verified_username`
call working on the field it already reads. SPEC-201 is what flips them, and then — as its own second
step, after the flip is deployed — stops the token being sent. Reversed at either boundary, the first
request after deploy fails on **all eight planes** with `TerminalError("unauthorized")`: no archive,
share, send, table build, quality check, shared-space change or notification action completes, and
each user gets a notification saying their request could not be started. Both specs' suites pass
through that outage, because each is written against its own half of the envelope.

#### Acceptance Criteria:

- [ ] The message carries the raw bearer in **the field that plane already reads** — `idToken` on
      shared-space, notifications, table-build (both routes) and data-quality; `actor` on table-share,
      file-send, archive (both modes) and file-ops — taken from SPEC-126's `SOURCES` table and each
      plane's verifier call site, not from a list written here. A test joins the API's per-route
      `token_field` against `dlq_drain.SOURCES` and fails on a disagreement, so a plane whose field is
      wrong is caught in CI rather than by a dead-letter.
- [ ] **The join has a stated rule for the queue that is deliberately absent from `SOURCES`.**
      `SOURCES` is keyed by domain segment and holds **six** rows today — data-quality, table-builder,
      table-share, shared-space, file-send, archive — becoming seven with Arc A's file-ops.
      **Notifications is not a row and must not be added one**: it is in `UNDRAINED_QUEUES` by
      SPEC-126's circularity decision, because the drain's only delivery channel is that very queue.
      So the join asserts three things and not set equality: every `SOURCES` key names a plane with at
      least one enqueue route and the token fields agree; every route's plane is either a `SOURCES`
      key **or** a member of `UNDRAINED_QUEUES`; and `UNDRAINED_QUEUES` is exactly `{"notifications"}`.
      Plain set equality between the ten routes and `SOURCES` fails on notifications and the repair a
      build session reaches for — adding the row — silently re-opens the circularity.
- [ ] **A tripwire test asserts the token is still being sent** on every route: `MessageBody` contains
      a non-empty string at the plane's token field. It exists to fail if someone implements SPEC-201's
      half of the change inside this spec, and **SPEC-201 deletes it in the same commit that stops
      sending** — which is the second of that spec's two internal steps, not this one's.
- [ ] The `identity` block is **not read by any plane** after this spec. A test
      greps `lambdas/` for `identity` outside `lambdas/api/` and asserts no verb reads it — the claim
      "nothing on the plane side breaks" is only checkable if nothing on the plane side has started
      depending on it.
- [ ] **The ordering is a requirement, stated in this spec and asserted in SPEC-201's preconditions:**
      SPEC-200 merges and deploys before SPEC-201 begins. The two changes may not ship in one PR, and
      a live check on this spec (Phase 5) is what makes the API's write real before any plane stops
      verifying. **SPEC-201 then has a second order inside itself** — its planes accept and require the
      nested block while the token is still travelling, and only once *that* is deployed does its
      final commit stop the API sending the token. Collapsing either boundary fails all eight planes
      closed on the first request after deploy.
- [ ] The second ordering requirement is FR-008's: **the portal role's `sqs:SendMessage` is removed in
      this spec**, so that at the moment SPEC-201 makes `actor` authoritative no browser credential can
      write a queue. An enforced order of *201 before the grant removal* would let any signed-in tab —
      the Identity Pool survives until SPEC-202 — enqueue a message naming any actor.

### FR-006: Every plane accepts the block

#### Description:

Three planes reject unknown top-level fields rather than ignoring them —
`file_send_validate_authorize._ALLOWED_FIELDS`, `archive_validate_authorize._ALLOWED_FIELDS` (per
mode, whose `restore` entry **is** `arcommon.restore.ALLOWED_FIELDS`), and Arc A's file-ops
(SPEC-187 FR-003). On those, the identity block is a `malformed_event` refusal, not a harmless
addition. This is the whole plane-side content of this spec.

Because the block is nested, the widening is the **single key `"identity"`** on each set — which is
why **SPEC-201 changes no allowlist at all**: it removes a field rather than adding one, and an
allowed-but-absent field is not a refusal. It also must not *tighten* them by dropping the token
field, which is what keeps a stale pre-cutover message refusing as `unauthorized` rather than
`malformed_event` (SPEC-201 FR-006).

#### Acceptance Criteria:

- [ ] `"identity"` is added to `_ALLOWED_FIELDS` on file-send, to **both** archive modes and to
      file-ops — four sets, three files, one key each, verified against the live values:
      `file_send_validate_authorize._ALLOWED_FIELDS` is
      `{"requestId", "actor", "source", "recipients"}`, `archive_validate_authorize._ALLOWED_FIELDS`
      is a per-mode dict whose `archive` entry is `{"requestId", "mode", "actor", "source"}` and
      whose `restore` entry is `arcommon.restore.ALLOWED_FIELDS`
      (`{"requestId", "mode", "actor", "space", "archiveId"}`). A test per plane sends a real envelope
      carrying the block and asserts the verb reaches its normal outcome; the same test **without**
      the widening fails, and that is recorded in the delivery doc rather than asserted from the
      source.
- [ ] The five planes with no allowlist (shared-space, notifications, table-build, table-share,
      data-quality) are asserted to **ignore** the block: a test per plane runs its parser over an
      envelope with and without `identity` and asserts an identical result object. "It will be ignored"
      is exactly the kind of claim that is true until one parser iterates keys.
- [ ] A **fleet test** — the discipline `test_deploy_matrix.py` and SPEC-152's `NotifyFailure` sweep
      already use — enumerates the planes from the filesystem and asserts, for each one publishing an
      allowed-field set, that the set equals the API's declared request fields **plus** `identity`,
      **plus** the plane's token field, **plus** the fields the route stamps itself. Derived on both
      sides; a hand-copied list would agree with itself.
- [ ] **The stamped-field term is not an escape hatch and archive is why it exists.** Archive's two
      allowed-field sets both contain `mode`, and `mode` is **not** a caller input: it is the route
      (`archive.archive` / `archive.restore`), and the handler stamps the matching literal, so a body
      supplying it is a 400 by FR-001 AC6. Without that term the equality is off by one on both
      archive modes and on nothing else, and the repair a build session reaches for — adding `mode` to
      the request type — hands the caller the branch that chooses between archiving and restoring.
      The term is therefore a **declared, per-route set the test reads from the route declaration**,
      and it is non-empty on exactly **four** routes, enumerated so a fifth is a visible edit:
      `archive.archive` and `archive.restore` stamp `mode`; `tableBuild.refresh` stamps
      `mode: "refresh"` where `tableBuild.create` stamps nothing; and `sharedSpace.enqueue` stamps
      `schemaVersion: 1` (`validate.py` refuses any other value) together with the advisory top-level
      `actor` username. A test asserts the other six routes declare an empty set.
- [ ] For the planes with no allowlist, the same fleet test derives the keys the verb actually reads
      (the string literals in its `req.get(...)` / `req[...]` calls, by AST) and asserts they are a
      subset of the API's declared request fields plus `identity`, the token field and the route's
      stamped fields. This catches the real failure — the API refusing at the door a field the plane
      needs — which no plane-side test can see. Shared-space is the one to check by hand first: its
      envelope carries an **advisory** top-level `actor` username beside the `idToken` it verifies,
      and `validate.py` reads the token and **not** the advisory field — so the subset holds while the
      field is stamped, and it is stamped because dropping it changes the wire for no gain and
      SPEC-201's `identity.actor` is what supersedes it.
- [ ] No other verb file is edited. Asserted in the diff: the widening is one frozenset per plane, and
      anything else is SPEC-201's.

### FR-007: The bearer's path to the message body

#### Description:

SPEC-197 Premise 6 says the router verifies the bearer and discards it before dispatch, and FR-011's
sweep forbids `lambdas/api/routes/` from even naming it. That premise was written when nothing
downstream needed the token. This spec needs it — transitionally — and **narrows the premise rather
than dropping it**: the raw token never reaches a handler, and exactly one module may read it.

#### Acceptance Criteria:

- [ ] `RequestContext` gains `bearer: Redacted`, where `Redacted` is a frozen wrapper whose `__str__`,
      `__repr__` and `__format__` all return `<redacted>` and whose value is obtainable only through
      the module-level `reveal()`. A test asserts an f-string, a `%r`, a `json.dumps(default=str)` and
      an exception message built from one all render `<redacted>` — which is what keeps the token out
      of `error.stack`, the trap SPEC-195 FR-007 re-opened for a token-handling service.
- [ ] An AST sweep asserts **exactly one** call to `reveal()` in `lambdas/api/`, inside
      `apicommon/enqueue.py`. A second call anywhere fails CI.
- [ ] SPEC-197 FR-011's sweep over `lambdas/api/routes/` is unchanged and still passes: no handler
      names `authorization`, `bearer` or a token field, and no handler builds a message body — handlers
      return a payload and the send helper stamps identity, the token and the FIFO keys.
- [ ] A test issues a request whose bearer is a distinctive literal, forces a failure inside the send
      helper, and asserts the literal appears in **no** emitted record, no envelope and no `detail` —
      including `error.stack`.
- [ ] The `Redacted` wrapper, the `bearer` field and the sweep are **deleted by SPEC-201** and this
      spec says so, so the narrowing has an end date rather than becoming the shape.

### FR-008: The API's role becomes the only writer

#### Description:

Identity-based grants are the whole access model here: there is no `aws_sqs_queue_policy` anywhere in
`infra/` today. So "only the API may write" is achieved by adding one grant and removing eight.

#### Acceptance Criteria:

- [ ] The API Lambda's execution role gains `sqs:SendMessage` on exactly the eight request-queue ARNs
      — never a wildcard, never a DLQ, never the notifications queue's *writer* path. SPEC-139's
      rendered-plan IAM scan covers it and a test asserts no `Resource: "*"` in the rendered statement.
- [ ] The eight portal-role statements are removed: the seven single-statement policies
      (`EnqueueDataQualityCheck`, `NotificationsEnqueue`, `EnqueueTableBuild`, `EnqueueTableShare`,
      `EnqueueFileSend`, `EnqueueArchive`, and Arc A's file-ops one) together with their
      `aws_iam_role_policy` resources, `.tftpl` files and now-unused `portal_role_name` wiring; and the
      `SharedSpaceEnqueue` **statement only** from
      `shared-spaces/policies/portal-role-shared-space.json.tftpl`, whose other statements are the
      membership grants and stay.
- [ ] A `.tftpl` test enumerates the modules from the filesystem and asserts **no** rendered policy
      attached to the portal role contains `sqs:SendMessage` on any request queue. Enumerated, not
      listed: a hand-kept list is exactly what would miss the ninth plane.
- [ ] Removal and grant land in **one** change. Split, either half is a broken deploy: grants first
      leaves two writers (harmless but unasserted), removal first breaks every enqueue between the two
      applies.
- [ ] **No queue resource policy is added, and that is a decision — the arc's, not just this spec's.**
      The precedent for a resource-side
      allowlist is the user-space bucket policy, whose own recorded failure mode (SPEC-164 FR-006) is
      that it is hand-maintained and a missing plane half-works. The identity grant is the only path a
      principal has to these queues, and AC3's enumerated sweep is what stops one being re-added
      unnoticed.
- [ ] **The API is the only writer of the eight *request* queues, which is not the same as the only
      writer of every queue, and the notifications queue is where the two get confused.** Its request
      queue has **eight** writers today, and this spec removes exactly one of them: the portal role.
      The other seven are execution roles that notify — the shared-spaces orchestrator
      (`EmitNotifications`), table-builder, table-share, data-quality (`EmitOutcomeNotifications`),
      file-send, archive, and the DLQ drain (`NotifyTheActor`) — each an `sqs:SendMessage` statement
      on `notifications_queue_arn` in its own `.tftpl`, with Arc A's file-ops plane an eighth. **None
      of them is touched**, and a test asserts each is still present after the portal-role removal.
      This is stated as a criterion because the shape a reader reaches for — one blanket `Deny` with a
      `StringNotEquals` on the API's role ARN — silences every one of them, and silently: SPEC-172's
      producer runs with `ResultPath: null` and a `Catch` leading onward and deliberately cannot fail
      its run, and the other planes notify best-effort, so archives, shares and sends would complete
      and no user would ever be told.
- [ ] **No deploy-role expansion is needed and that claim is asserted, not assumed**: this spec adds no
      new AWS resource *type* — the API role exists (SPEC-193/196) and the queues exist — so a test
      asserts the diff touches no `.tftpl` under `infra/modules/base/policies/`. Saying it out loud is
      the point; the arc's rule is that a new resource type expands the deploy role as in-scope work,
      and a reader needs to see this was checked rather than skipped.

### FR-009: The browser half

#### Description:

Ten services keep their exported signatures and their `ServiceResult<T>` (SPEC-197 FR-009), and lose
their AWS imports. Nothing above the service boundary changes: no hook, no dialog, no test of either.

#### Acceptance Criteria:

- [ ] `lib/enqueueFifo.ts` and `lib/sqsClient.ts` are deleted, `@aws-sdk/client-sqs` is removed from
      `apps/portal/package.json`, and a sweep asserts no module under `apps/portal/src/` imports it.
      `lib/credentialRetry.ts` and `lib/awsCredentials.ts` stay (other clients still use them until
      SPEC-202).
- [ ] Each of the ten enqueue functions issues **exactly one** `apiRequest` for its declared route and
      no other network call, keeps its exact signature (`ServiceResult<void>` stays `void`,
      `ServiceResult<{requestId}>` stays that), and still never throws.
- [ ] The `requestId` mint stays exactly where it is — `useFileSend`, `useArchive`,
      `useDataQualityCheck`, the two table-build services, `sharedSpaces.service.ts`, and SPEC-190's
      file-ops submit — one per **submit** (Premise 3). A test asserts two submits of one dialog
      produce two ids and that a retry of a failed submit produces a third.
- [ ] Every consuming hook, dialog and test is unchanged, asserted in the diff. That is the property
      SPEC-197 FR-009 exists to make checkable, at ten services instead of one.
- [ ] **The `NotConfigured` refusal disappears**, and it must: SPEC-197 FR-004's disjointness guard
      forbids the API returning any `PASSTHROUGH_CODES` member, and `NotConfigured` is one — a server
      that returned it would put server-authored text into `error.message` through a rule written to
      uphold SPEC-106. An unset queue URL is now an operator fault: the API's variables are required
      and raise at first read, and the user sees SPEC-106's generic administrator message. The
      **seven** `notConfiguredMessage` rows leave `lib/support.test.ts`'s `CALL_SITES` registry — one
      per enqueue *function* rather than per queue, so table-build contributes two (create and
      refresh) over one env var — and the registry's `describe` block goes with them.
- [ ] **Both env-var guards are satisfied in the same change, and they fail in opposite directions.**
      `CALL_SITES` covers **six** queue variables in seven rows and has **no archive row**: the archive
      plane's two services carry `notConfiguredMessage`s that no test reaches, and this spec deletes
      the services rather than adding the rows. `lib/env.ts`'s `OPTIONAL_ENV` covers **seven**,
      `VITE_ARCHIVE_QUEUE_URL` included since #467, and that PR also replaced the hand-kept membership
      claim with a **derived sweep** — a `?raw` glob asserting every `VITE_*` name read outside a test
      file is registered. That sweep reddens if a name leaves `OPTIONAL_ENV` while any source still
      reads it, so the seven `OPTIONAL_ENV` entries, the seven `.env.example` lines, the
      `deploy-app.yml` build env and the ten service rewrites land together. Arc A's file-ops variable
      is the eighth and is removed the same way.

### FR-010: The size cap, and a failure mapping this plane must not inherit

#### Description:

Two conditions this spec is the first to produce. A message too large for SQS is refused at the door
instead of dead-lettering minutes later; and an `AccessDenied` here is the API's own role failing, not
the user's isolation working — the opposite of SPEC-196 FR-007's user-plane rule.

#### Acceptance Criteria:

- [ ] An envelope whose serialized `MessageBody` would exceed `MAX_MESSAGE_BYTES` is refused with
      **413 `PayloadTooLarge`** — the code SPEC-197 FR-003 reserved and no route produced until now —
      before any `SendMessage`.
- [ ] `MAX_MESSAGE_BYTES` is **computed by a test**, not written as a literal: SQS's 256 KB limit,
      minus the identity block at its maximum, minus `MAX_BEARER_BYTES` (the transitional token
      allowance, itself measured from a real Cognito ID token with the largest claim set this pool
      issues). The bound must be measured against the **serialized** body after stamping — a cap
      applied to the caller's payload permits a request the send cannot make (SPEC-164's chain).
- [ ] The refusal is measured on the body the API will send, so it is **tighter** than the browser's
      existing client-side caps (`SEND_MAX_ITEMS`, `ARCHIVE_MAX_ITEMS`, …), which stay where they are
      as fast-fail affordances and are not moved.
- [ ] A downstream `AccessDenied` from `SendMessage` maps to **500 `InternalError`**, never 403
      `AccessDenied`. On the `api` plane the credential is the API's own execution role, so a 403 would
      tell a user they may not do something when in fact the deployment is misconfigured — and it would
      be read as isolation working. A test asserts the two planes map the same botocore error to
      different statuses; a shared mapper passes any test that exercises one plane at a time.
- [ ] An SQS throttle maps to **429 `RateLimited`**, a timeout or 5xx to **503 `ApiUnavailable`**, and
      neither is retried by the client (FR-001 AC1 — `idempotent: false`).

### FR-011: Observability for a request carrying a bearer and a selection

#### Description:

One span per enqueue through `cpcommon.observability`, inheriting SPEC-197 FR-011's stamping and
correlation rules. The field rule binds hard here: the request body holds a bearer, a user's file
keys, recipient usernames, and — on table-share — a digest computed from all of them.

#### Acceptance Criteria:

- [ ] Each enqueue stamps `route_id`, `queue`, `actor`, `message_group_id`, `dedup_id`, the body's
      `request_id` and `body_bytes`. A group id is user metadata (a username, a space, a digest) and is
      allowed; a **dedup id** is stamped for table-share too, and is a digest, not a token.
- [ ] The **body is never stamped**, whole or in part: no `items`, no `recipients`, no `location`, no
      `prefix`. Object keys are user metadata and would be allowed by the letter of the field rule;
      they are excluded because the obvious helper — stamp the validated request — is one edit away
      from stamping the token with it, and because a selection of 20,000 keys is a log record nobody
      can read. `body_bytes` is the field a `WHERE` clause wants.
- [ ] The correlation field is the API Gateway request id (SPEC-197 FR-011), **not** the body's
      `requestId`. This is the exact shape of the trap SPEC-197 found: `_extract_request_id` falls back
      to parsing `body` as JSON, and every body here carries a browser-supplied `requestId`. A test
      posts a body whose `requestId` is a known literal and asserts no record carries it as the
      correlation field — while the same literal **is** present as the stamped `request_id` field, so
      the test distinguishes "stamped correctly" from "leaked into correlation".
- [ ] No bearer substring and no email appears in any record on any path, including the failure paths
      of FR-010 (FR-007 AC4 is the same assertion at the wrapper; this one is at the span).

---

## Data Model

### The eight queues and ten routes — the contract artifact

`b(space)` = `USER_SPACE_BUCKET` for `kind == "personal"`, else `SHARED_SPACE_BUCKET`.
`sha(s)` = SHA-256 of UTF-8 `s`, lower-case hex. `norm(l)` = `l.strip()` with leading and trailing
`/` removed. All `MessageDeduplicationId`s are set explicitly, including on the three request queues
whose `content_based_deduplication` is `true`.

| Route id | Queue (env var) | CBD | `MessageGroupId` | `MessageDeduplicationId` | Token field (transitional) |
|---|---|---|---|---|---|
| `sharedSpace.enqueue` | shared-space (`SHARED_SPACE_QUEUE_URL`) | true | the constant `shared-space` — one global group, so two users cannot create one name concurrently | body `requestId` | `idToken` |
| `notifications.enqueue` | notifications (`NOTIFICATIONS_QUEUE_URL`) | true | `principal.username` (was the caller-supplied `input.username`) | a fresh UUID minted by the API — the only id this spec mints, because the plane's actions are idempotent and have no request id | `idToken` |
| `tableBuild.create` | table-build (`TABLE_BUILD_QUEUE_URL`) | true | `space.database` (raw; ≤63 chars by `CATALOG_IDENTIFIER_RE`) | body `requestId` | `idToken` |
| `tableBuild.refresh` | table-build | true | `space.database` | body `requestId` | `idToken` |
| `tableShare.enqueue` | table-share (`TABLE_SHARE_QUEUE_URL`) | false | `{source.database}.{source.table}` (raw) | `sha([actor, source, tableName, sorted(kind:name), floor(now/60000)])` — FR-003 | `actor` |
| `dataQuality.enqueue` | data-quality (`DATA_QUALITY_QUEUE_URL`) | false | `sha("{b(space)}/{norm(location)}")` — **no trailing slash** | body `requestId` | `idToken` |
| `fileSend.enqueue` | file-send (`FILE_SEND_QUEUE_URL`) | false | `sha("{b(space)}/{space.name}/")` | body `requestId` | `actor` |
| `archive.archive` | archive (`ARCHIVE_QUEUE_URL`) | false | `sha("{b(space)}/{space.name}/")` | body `requestId` | `actor` |
| `archive.restore` | archive | false | `sha("{space.kind}/{space.name}/archive/{archiveId}/")` — **no bucket**, by SPEC-168's isolation decision | body `requestId` | `actor` |
| `fileOps.enqueue` | file-ops (`FILE_OPS_QUEUE_URL`) | false | `sha("{b(space)}/{space.name}/")` (SPEC-187 FR-003) | body `requestId` | `actor` |

FIFO orders **delivery** per group. It does not serialize executions — the Pipes start their machines
`FIRE_AND_FORGET` (SPEC-157, restated by SPEC-187 FR-003). Nothing in this spec changes that, and no
criterion above may be read as claiming it.

### The wire

```jsonc
// POST /v1/enqueue/file-send  — request (the identity block and the token are NOT caller inputs)
{"requestId": "…", "source": {"space": {"kind": "personal", "name": "alice"}, "items": [/* … */]},
 "recipients": [{"kind": "user", "name": "bob"}]}

// 200
{"requestId": "…"}

// What reaches the queue (transitional — SPEC-201 removes the flat `actor` token field, and the
// `identity` block below is the permanent shape rather than a staging post)
{"requestId": "…", "actor": "<the raw ID token>", "source": {/* … */}, "recipients": [/* … */],
 "identity": {"actor": "alice", "delegated_by": null, "assurance": "interactive"}}
```

```python
# lambdas/api/apicommon/identity_block.py

Assurance = Literal["interactive"]                # closed set of one — FR-004

class IdentityBlock(TypedDict):
    actor: str                                     # principal.username, verified. Never from a body.
    delegated_by: str | None                       # always None in this arc; PRESENT, never omitted
    assurance: Assurance

# lambdas/api/apicommon/contract.py — the enqueue routes' extra declarations
@dataclass(frozen=True)
class EnqueueRoute(Route):
    queue: str                                     # a key of QUEUES; guarded for set equality
    token_field: Literal["idToken", "actor"]       # transitional; joined against dlq_drain.SOURCES

class EnqueueAccepted(TypedDict):
    requestId: str | None                          # echoed, never minted; None only on notifications

# lambdas/api/apicommon/context.py
class Redacted:                                    # __str__/__repr__/__format__ -> "<redacted>"
    ...                                            # value readable only via reveal(), one call site
```

## API / Interface Contract

```ts
// apps/portal/src/features/file-send/fileSend.service.ts — signature UNCHANGED
export async function enqueueFileSend(req: FileSendRequest): Promise<ServiceResult<void>>;

// …and inside, the whole of it:
const result = await apiRequest('fileSend.enqueue', {body: {requestId: req.requestId, source: …}});
```

```python
# lambdas/api/apicommon/enqueue.py — the ONLY path to SendMessage, and the only reveal() call site.
def enqueue(ctx: RequestContext, route: EnqueueRoute, payload: dict) -> EnqueueAccepted: ...
```

## Environment Variables

The eight `VITE_*_QUEUE_URL` variables — the seven that exist today plus Arc A's file-ops one — are
**removed** from `apps/portal/.env.example`, `lib/env.ts`'s `OPTIONAL_ENV` and `readEnv()` table,
`deploy-app.yml`'s build env and the GitHub repository variables. They re-appear on the API Lambda,
required with no default, raising at first read (SPEC-196's convention), wired through Tofu from each
module's queue-URL output:

```
SHARED_SPACE_QUEUE_URL  NOTIFICATIONS_QUEUE_URL  TABLE_BUILD_QUEUE_URL  TABLE_SHARE_QUEUE_URL
DATA_QUALITY_QUEUE_URL  FILE_SEND_QUEUE_URL      ARCHIVE_QUEUE_URL      FILE_OPS_QUEUE_URL
SHARED_SPACE_BUCKET     # new: the second bucket name three FIFO derivations need (FR-002)
```

`USER_SPACE_BUCKET` already exists (SPEC-197). A key-set test asserts the eight names equal
`{q.env_var for q in QUEUES}` — derived on both sides.

## File & Folder Structure

```
lambdas/api/
├── apicommon/
│   ├── contract.py                    # + EnqueueRoute, QUEUES, the ten routes
│   ├── context.py                     # + Redacted, RequestContext.bearer
│   ├── enqueue.py                     # NEW — the send helper: identity block, token, FIFO keys
│   ├── fifo.py                        # NEW — every group/dedup derivation, and only here
│   └── identity_block.py              # NEW
├── routes/enqueue_*.py                # NEW — ten thin handlers, no AWS call but the send
├── fifo_vectors.json                  # NEW — golden vectors captured from the outgoing TS
├── test_fifo_derivations.py           # NEW — FR-002/003
├── test_enqueue_routes.py             # NEW — FR-001/004/010
└── test_bearer_containment.py         # NEW — FR-007

lambdas/
├── test_plane_envelope_agreement.py   # NEW — FR-006's fleet test, both directions
├── file-send-validate-authorize/…     # + "identity" in _ALLOWED_FIELDS
├── archive-validate-authorize/…       # + "identity", BOTH modes
└── archive-common/arcommon/restore.py # + "identity" in ALLOWED_FIELDS

apps/portal/src/
├── lib/enqueueFifo.ts                 # DELETED
├── lib/sqsClient.ts                   # DELETED
└── features/*/…service.ts             # ten functions: same signature, one apiRequest inside
```

## Implementation Phases

### Phase 1: The derivations and their vectors

- Capture the golden vectors from the current TypeScript **before touching it**; commit
  `fifo_vectors.json`.
- `apicommon/fifo.py`, all four families; the one-builder sweep; the data-quality and archive-restore
  divergences with their own tests.
- FR-003's table-share substitution and its two binary assertions.

### Phase 2: The contract, the block and the send helper

- `EnqueueRoute`, `QUEUES`, the ten routes, the set-equality guards verified by violation in both
  directions; the generated TS regenerates (SPEC-197 FR-005 gate one).
- `identity_block.py`, `apicommon/enqueue.py`, `Redacted` and the single `reveal()` sweep.
- FR-010's computed `MAX_MESSAGE_BYTES`, the 413, and the 500-not-403 mapping.
- FR-011's stamping, including the correlation test that distinguishes stamped from leaked.

### Phase 3: The planes accept it

- Widen the three allowlists (four sets); the with/without tests; the fleet agreement test in both
  its forms.
- FR-005's tripwire and the `dlq_drain.SOURCES` join.

### Phase 4: The browser, the IAM, and the grant removal

- Ten services rewritten; `enqueueFifo.ts`, `sqsClient.ts` and `@aws-sdk/client-sqs` deleted; the
  `CALL_SITES` rows removed; the env variables moved.
- The API role's eight-ARN grant and the eight portal-role removals, in one change; the enumerated
  `.tftpl` sweep; the no-deploy-role-change diff assertion.

### Phase 5: Verification

Written as a runnable script at `docs/testing/enqueue-paths-e2e.md`. **Sign in fresh, signed out to
start** — a signed-in pass never tests the token path. What nothing offline can prove: that a group
id computed in Python is the one the deployed queue receives (ordering has no error path, so this is
only visible as *work happening*), that the widened envelope is accepted by the deployed verbs, that
the `cpcommon` layer attaches at cold start (SPEC-137 shipped instrumented code whose attachment was
missing while every offline gate passed), and that the removed portal-role grant actually denies.

- **One request per plane, ten in all**, submitted from the portal UI, each one arriving and being
  **processed**: a shared space created, a notification marked read, a table built, a table refreshed,
  a table shared, a quality check reporting, files sent, an archive made, a restore *started* (the
  archive arc's own 3–5 h check is not repeated here — `restore_started` arriving is the assertion),
  and a folder copy through Arc A's plane. The load-bearing part is the outcome, not the 200: an
  enqueue that returns 200 and lands in the wrong FIFO group still succeeds.
- **The double-submit guard, per plane.** Submit the same gesture twice: one outcome, not two. On
  **table-share** do it with a **forced token refresh between the two submits** (`fetchAuthSession({
  forceRefresh: true})` from the console) — one share is the new behaviour and two is the old one,
  and this is the only place the FR-003 divergence is observable live.
- Read one record from `logs/service=api/…/data.jsonl` per plane: `route_id`, `queue`, `actor`,
  `message_group_id`, `request_id`, `env: "prod"`, a `version` equal to the build sha and neither
  empty nor `0.0.0`; and **absent**: any bearer substring, any email, any object key, any recipient.
  Records arrive on the 10-minute sweep — wait for it rather than concluding from an empty query.
- `curl` an enqueue route with **no** `Authorization` → 401, envelope-shaped, and **zero**
  `SendMessage` (a 401 issued after a successful send looks identical from outside).
- `curl` an enqueue route with a body carrying `actor`, `identity` and the plane's token field → 400
  `InvalidRequest`, and nothing enqueued.
- **An IAM policy simulation against the DEPLOYED portal role**: `sqs:SendMessage` on all eight
  request-queue ARNs → **implicitDeny**, each row paired with an `allowed` control on a grant the role
  still holds (an `s3:GetObject` under the caller's own prefix), because an `implicitDeny` alone
  cannot tell an ungranted action from a wrong ARN. Then the same simulation against the **API's**
  execution role → `allowed` on all eight.
- One deliberately oversized selection → **413**, with nothing on the queue.
- **Safari** at desktop, since that is the browser in use; a Chromium pass corroborates and cannot
  discharge — record it as such.
- **Recorded as OWED, not discharged:** anything requiring a second account (a shared space where the
  submitter is a non-owner member), and the malformed-body DLQ path, which still belongs to SPEC-126's
  own owed check.

### Phase 6: Completion ritual

- `Status: Completed`; the `INDEX.md` row; the delivery doc — carrying the ten-route table and the
  golden-vector procedure, which is the artefact SPEC-201 reads to know what it may remove.
- `decisions.md` entries, then **one line each** in CLAUDE.md's Key Decisions: (1) the identity block
  is **nested and stays nested**, because `actor` is already the raw token on four planes and a flat
  verified `actor` would overwrite the field they verify — and `assurance` is `interactive`, naming
  the assurance *kind* so the machine-facing door can add `delegated` without renaming anything;
  (2) the rollout order — the API writes both the token and the
  block, SPEC-201 flips the planes and only then stops the token being written, and **the browser's
  `sqs:SendMessage` comes off here**,
  because the Identity Pool survives until SPEC-202 and a trusted `actor` plus a browser grant is
  impersonation; (3) table-share's dedup id is keyed on the **verified actor** rather than on the
  token, which strengthens a guard that silently lapsed across a token refresh; (4) **the identity
  grant is the only path to these queues and no resource policy is added** (FR-008 AC5) — this is the
  arc's position and SPEC-201 does not restate or reverse it.
- A **superseded marker** narrowing SPEC-197 Premise 6 (`the bearer never reaches a handler`) to name
  `apicommon/enqueue.py` and its single `reveal()`, with the note that SPEC-201 deletes both; and a
  note on SPEC-190 FR-003 that the `MessageGroupId` digest is no longer computed in the browser, so
  the async-submit shape it describes is now one `apiRequest`.
- A note in SPEC-201's brief covering what this spec found and does not own: `dlq_drain.SOURCES` and
  `_redacted` lose their subject when the token stops being sent; shared-space carries an **advisory**
  top-level `actor` username that `_redacted` also blanks and that `identity.actor` now supersedes;
  and **`notifications_writer._resolve_username` branches on `USER_ACTIONS = {markRead, markAllRead}`**
  — the `create` arm is the trusted-producer path, written by the seven notifying execution roles, and
  carries `username` in the body with **no actor and no token**. It is not an enqueue route of this
  spec and it must survive SPEC-201's collapse: a `trusted_actor` applied to every path refuses every
  notification the fleet produces.
- Component-inventory rows: `foundations.md` loses `lib/enqueueFifo.ts` and `lib/sqsClient.ts`; the
  seven feature area files each get their enqueue-service row rewritten.
- Help sweep: **nothing user-facing changes.** Every dialog, label and outcome notification is
  identical. The one wording that disappears is the ten "… is not configured" refusals — one per
  enqueue function: the nine in `features/` today, of which seven have a `CALL_SITES` row and
  archive's two have none, plus Arc A's file-ops one — which are
  unreachable in a correctly deployed environment and now resolve to SPEC-106's generic administrator
  message — recorded here as a deliberate, accepted loss rather than a Help edit.

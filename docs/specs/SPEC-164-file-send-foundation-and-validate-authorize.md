# Spec: Send Files — Foundation Infrastructure, Request Contract & validate-authorize

**ID:** SPEC-164
**Status:** Draft
**Last Updated:** 2026-08-10
**Depends On:** SPEC-088/089 (the table-share plane as the pattern), SPEC-107/125/156 (`cpcommon`), SPEC-126 (DLQ drain), SPEC-152 (`NotifyFailure` on every plane), SPEC-160 (`cpcommon.transfer`)

## Overview

A user can copy and move files anywhere **inside** a space they can reach, and can share a *table*
with anyone. What they cannot do is hand a colleague a file. The browser has no permission to write
into another user's prefix — that is the isolation model working — so "send these files to Bob" needs
a privileged path, exactly as table share does.

This spec builds the plane and its front door: the queue, the pipe, the state machine, the execution
role, the domain layer, and the first real verb — **validate-authorize**, which proves from the
verified ID token that the sender may read what they are sending, and that every recipient exists.
Nothing copies yet; the machine ends in a placeholder terminal.

The plane is its own, not a mode of table share. The two features share an *algorithm*
(`cpcommon.transfer`), not a request contract, a DLQ or a failure surface — and a malformed file-send
message must never dead-letter someone's table share.

## Scope

### In Scope

- `infra/modules/file-send/`: a **FIFO** request queue + DLQ, an EventBridge Pipe, a **Standard**
  state machine, one shared execution role, and the `fscommon` domain layer beside `cpcommon`.
- The **request contract** the browser enqueues, and its FIFO `MessageGroupId` / dedup rules.
- **validate-authorize**: verify the ID token, take `username` from the verified claim, authorize the
  **source**, validate every recipient, enforce the request-shape caps.
- A skeleton machine — validate-authorize → placeholder states → terminal — carrying its
  `NotifyFailure` state before `Fail` on every failure path from day one.
- Browser IAM: `sqs:SendMessage` on the new queue **only**, plus `VITE_FILE_SEND_QUEUE_URL` and its
  deploy wiring.
- **Deploy-role IAM expansion** as in-scope work — this adds new resource types, so
  `architecture.md` → *Deploy-role IAM — adding a new resource type* and *Lambda code/infra split*
  are required reading before the first `.tf` line.
- **Adding the new execution role to the user-space bucket policy's principal allowlist** (FR-006) —
  without it the role is denied by the bucket, whatever its identity policy says.
- Registering the new request DLQ with SPEC-126's drain sweep list.

### Out of Scope

- Listing, planning or copying anything — SPEC-165/166.
- Any UI, and any notification other than the SPEC-152 pre-verb failure path — SPEC-167.
- A consent or accept flow. Sending is a **push**, matching table share; the recipient is told after
  the fact.
- Sending *out* of the portal (email, presigned links, external destinations).
- Moving rather than copying. A send never deletes the sender's copy.
- Overwriting anything at the destination — the conflict rule lands in SPEC-166.

---

## Functional Requirements

### FR-001: The plane

#### Description:

The infrastructure, following the shared control-plane pattern.

#### Acceptance Criteria:

- [ ] A FIFO request queue and FIFO DLQ exist, with content-based dedup **off** (the request supplies
      an explicit `MessageDeduplicationId`), and a redrive policy onto the DLQ.
- [ ] An EventBridge Pipe delivers to a **Standard** state machine; `REQUEST_RESPONSE` is not used
      (impossible for a Standard machine — settled in SPEC-157).
- [ ] One execution role serves every verb; a `fscommon` layer holds file-send wording and key
      layout, with `cpcommon` supplying the algorithm — no algorithm is forked into `fscommon`
      (SPEC-156).
- [ ] The machine carries a `NotifyFailure` state before `Fail`, reached on **every** failure path,
      decoding the raw `{Error, Cause}` through `cpcommon.errors.failure_reason` — the SPEC-152 fleet
      test covers the new machine with no exemption.
- [ ] Every catch carries `ResultPath` so the verified actor is not discarded (the shared-space
      defect SPEC-152 fixed).
- [ ] The new request DLQ is in SPEC-126's swept list, so a dead-lettered send becomes a user
      notification.
- [ ] `lambdas/test_deploy_matrix.py` covers every new function: the deploy matrix and what each
      function imports agree.

### FR-002: The request contract

#### Description:

One envelope, validated before anything else runs.

#### Acceptance Criteria:

- [ ] The message carries `requestId`, `actor` (**the raw ID token, at the top level**), `source`
      (space kind + name + the selected items) and `recipients[]`; unknown top-level fields are
      rejected, not ignored.
      **Amended during PR2 (2026-08-11) — this AC originally said `actor.idToken`, nested.** The
      envelope must match what SPEC-126's shared DLQ drain reads, and that reader is flat:
      `dlq_drain._notify_one` does `body.get(token_field)` and hands the result straight to
      `verified_username_ignoring_expiry`. A nested token would make the drain fail to derive a
      recipient on every dead-lettered send — silently, since it swallows and returns — which is
      FR-001 AC6 unmet. It is also the *redaction* contract: `_redacted` replaces top-level keys
      only, so a nested token would be written to CloudWatch verbatim, and an expired token is
      still a signed assertion about a real user. Flattening keeps one envelope shape across all
      five planes instead of teaching a shared security path a second one.
- [ ] `MessageGroupId` is the **SHA-256 hex digest** of `{bucket}/{sourceSpaceRoot}` — a hash, never
      the raw path (SQS caps the group id at 128 characters while S3 keys reach 1024, the reason
      recorded for data quality).
- [ ] `MessageDeduplicationId` is `requestId`; content dedup is off on the queue, so that id is the
      only double-submit guard.
- [ ] A malformed or unparseable body fails before any AWS call and reaches `NotifyFailure`.
- [ ] Nothing from the untrusted body is used to identify the sender.

### FR-003: Actor identity and source authorization

#### Description:

The sender must actually be able to read what they are sending.

#### Acceptance Criteria:

- [ ] The ID token is verified against the pool's JWKS through the single `cpcommon` path
      (SPEC-156); an expired, unsigned or wrong-audience token is a terminal failure.
- [ ] `username` comes from the **verified claim** and from nowhere else.
- [ ] A `personal` source is authorized only when its name equals the verified username.
- [ ] A `shared` source is authorized only when the verified username is an **active** member of that
      space in the registry — `pending`, `leaving`, absent, or a non-existent space all fail.
- [ ] Every selected item's key is confirmed to sit **inside** the authorized source root. The check
      is **two rules, not one**, because either alone leaves a hole:
      (a) the root comparison is on a **trailing-slash-normalised** prefix — this is what refuses
      `alice2/…` against root `alice/`, which a raw `startswith` accepts; and
      (b) any key containing a `.` or `..` **path segment** is refused outright — normalisation does
      nothing about dot segments, and `"alice/../bob/secrets.csv".startswith("alice/")` is `True`.
      S3 keys are opaque bytes and neither `ListObjectsV2` nor `GetObject` resolves `..`, so (b) is
      not an exploitable read today; it is required because the same string becomes `itemName` in
      `fscommon.paths.destination_key`, where a dot segment produces a legal-but-nonsense
      destination.
- [ ] Each rule has its own test, including the `alice2/` case and the `alice/../bob/` case.
- [ ] The space's own `athenaresults/` is refused as a source. **This is a new rule for this plane,
      not an existing one being reused:** `protectedFolders.ts` deliberately keeps three divergent
      lists, in which `athenaresults/` is never a paste *destination* and never a move *source*,
      while copying *out* of it is permitted in the browser today. A send is a copy (see Out of
      Scope), so no existing list answers this question — and that file's own note warns that
      unioning the lists is the wrong repair.

### FR-004: Recipient validation

#### Acceptance Criteria:

- [ ] A `user` recipient must exist in the User Pool (`admin_get_user`); an unknown user is annotated
      `unknown_user` and carried forward — it fails **that recipient**, not the request.
- [ ] A `space` recipient must exist in the registry; an unknown space is annotated `unknown_space`
      the same way. **Membership is not required** — any space by name is a valid target, matching
      table share's recorded decision, because the execution role does the write.
- [ ] Duplicate recipients are collapsed; sending to oneself is permitted (it lands in the sender's
      own `shared_files/` inbox and conflicts naturally if repeated).
- [ ] The username directory is **not** consulted — it is advisory and never an authorization input
      (SPEC-146); existence checks stay `admin_get_user`.
- [ ] More than `SEND_MAX_RECIPIENTS` recipients, or more than `SEND_MAX_ITEMS` selected items, is a
      whole-request terminal failure naming the count and the cap.

### FR-005: Browser IAM and enqueue surface

#### Acceptance Criteria:

- [ ] The portal role's only file-send privilege is `sqs:SendMessage` on the new queue ARN — no
      cross-prefix S3 write is granted to any user, ever.
- [ ] `VITE_FILE_SEND_QUEUE_URL` is documented in `.env.example`, wired into `deploy-app.yml`'s build
      env, and set as a GitHub Actions repo variable (the recorded `VITE_*` trap).
- [ ] A rendered-policy test asserts no new `Resource: "*"` statement, keeping the SPEC-139 plan
      scan's IAM findings flat.

### FR-006: The user-space bucket policy must admit the new role

#### Description:

`user-space-bucket-policy.json.tftpl` is a `"Principal": "*"` **Deny** on
`GetObject`/`PutObject`/`DeleteObject`/`ListBucket`, conditioned `StringNotLike aws:PrincipalArn`
against a hand-maintained allowlist of every principal permitted to touch the bucket — portal,
deploy, LF registration, and each control plane's role by name. **An explicit resource-policy Deny
beats an identity-policy Allow**, so a new execution role that is not on the list is denied no matter
how correct SPEC-166's grants are. Every `space` recipient would work (the shared-space bucket has no
bucket policy) and every `user` recipient would fail `AccessDenied` — a half-working feature that
reads like a code bug.

#### Acceptance Criteria:

- [ ] The file-send execution role ARN is threaded into the allowlist: a new `variable` in
      `modules/data`, the `templatefile()` argument, and the root wiring — the same three-part change
      every existing plane's role made.
- [ ] The role ARN is derived the way its siblings are (constructed from `project_name` +
      `environment` in root locals), so no cycle is introduced between `modules/data` and the new
      module.
- [ ] A rendered-policy test asserts the new ARN appears in the allowlist; a plane whose role is
      absent must fail the test rather than fail at runtime.
- [ ] The delivery doc names this as a required step for **any** future plane touching the
      user-space bucket — the allowlist is hand-maintained, which is exactly the shape that rots.

---

## Data Model

```python
# The enqueued request
{
  "requestId": "9f2c…",
  # The RAW token, top-level — see FR-002 AC1. The shared DLQ drain reads and redacts
  # this field flatly, and table-share's envelope has the same shape.
  "actor": "eyJ…",
  "source": {
    "space": { "kind": "personal", "name": "alice" },      # or {"kind":"shared","name":"marketing"}
    "items": [ { "kind": "file",   "key": "alice/reports/q1.csv" },
               { "kind": "folder", "key": "alice/reports/2026/" } ]
  },
  "recipients": [ { "kind": "user", "name": "bob" },
                  { "kind": "space", "name": "finance" } ]
}

# validate-authorize output
{
  "requestId": "9f2c…",
  "actor": { "username": "alice" },
  "source": { "bucket": "dat-prod-user-space", "root": "alice/", "items": [ … ] },
  "recipients": [ { "kind": "user",  "name": "bob" },
                  { "kind": "space", "name": "finance", "invalid": "unknown_space" } ]
}
```

```python
# lambdas/file-send/common/fscommon
#   config.py    SEND_MAX_ITEMS, SEND_MAX_RECIPIENTS, SHARED_FILES_FOLDER
#   authz.py     authorize_source(username, space) -> root prefix   (raises on denial)
#   paths.py     assert_inside_root(root, key)  — trailing-slash-normalised containment
#   messages.py  file-send wording on cpcommon's Resolver
```

## Implementation Phases

### Phase 1: Infrastructure

- The module (queue, DLQ, Pipe, Standard machine skeleton with `NotifyFailure`, execution role,
  layers), the deploy-role IAM expansion, the **user-space bucket-policy allowlist entry** (FR-006),
  DLQ registration with the drain sweep.

### Phase 2: The contract + validate-authorize

- `fscommon` config/authz/paths/messages; the verb; token verification through `cpcommon`.

### Phase 3: Browser grant

- Portal-role `sqs:SendMessage`, `.env.example`, `deploy-app.yml` and the repo variable.

### Phase 4: Verification

- Unit tests for every authorization branch, especially the containment cases (`alice2/` against
  `alice/`, a `..`-shaped key, `athenaresults/`).
- **Live check (owed):** enqueue one hand-crafted valid request and one with an unauthorized source;
  confirm the first reaches the placeholder terminal, the second notifies the sender, and both appear
  in `logs/service=file-send/`. A shared layer's import-time failure only shows at **cold start**
  (PR #196), so this must be a real invocation, not a unit test.

### Phase 5: Completion ritual

- Delivery doc, INDEX status, an `architecture.md` → *Control Planes → Send Files* section, a
  `decisions.md` entry (its own plane, push semantics, any-space targets, no directory in
  authorization), and one Key Decisions line. No user-facing surface yet — no Help change.

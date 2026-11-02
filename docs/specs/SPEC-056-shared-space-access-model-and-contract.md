---
type: Spec
id: SPEC-056
title: "Shared-Space Access Model & Request Contract (Membership Tags + Portal Slots + LF)"
description: "Gives operators the shared-space access model: ten membership slots mapped to principal tags and portal-role policies scoping S3 and Glue, Lake Formation setup, and a trusted-actor request contract for the control plane."
spec_status: Completed
depends_on: [SPEC-050, SPEC-032, SPEC-033, SPEC-011, SPEC-013, SPEC-006]
arc: shared-connections
arc_order: 2
---

**Dependency notes:** SPEC-050 (shared bucket, registry storage, SQS/Pipe/Step Function + orchestrator role, provisioner Lambda infra), SPEC-032 (LF enforcement bootstrap + hybrid registration pattern; admin bucket), SPEC-033 (per-DB LF grant pattern; catalog-safe identifier rule), SPEC-011/013 (shared portal role + `username` principal tag), SPEC-006 (Cognito User Pool + Identity Pool)
> **Reference:** `docs/shared-spaces-architecture.md` §3 (membership principal tag), §4 (registry), §5 (results
> layout), §6. This is the **access-model half** of the original SPEC-050 split: it adds the membership-tag
> machinery, the portal-role membership slots, Lake Formation registration of the shared bucket, and the
> **request-message contract + trusted-actor binding** on top of SPEC-050's plumbing. It still ships **no
> per-action behavior** — create/add/remove/leave/delete are SPEC-051→055; this spec makes their access model and
> message contract exist and proves an authorized request flows through the (still no-op) pipeline.

## Overview

With SPEC-050's bucket + control plane in place, wire the **access model** that lets specific users reach specific
shared spaces while everyone still shares one portal role. Per `shared-spaces-architecture.md` §3, access is gated by
a **membership principal tag**: ten bounded Cognito attribute slots `custom:shared_space_1..10`
(`MAX_SHARED_MEMBERSHIPS = 10`) mapped to Identity-Pool principal tags `shared_space_1..10`, and ten matching
templated statement-pairs on the portal role scoping S3 + Glue to `${aws:PrincipalTag/shared_space_k}`. This spec also
registers `dat-prod-shared-space` in Lake Formation (hybrid) and makes the SPEC-050 orchestrator role an LF admin,
defines the **request-message contract** every shared-space mutation uses, and establishes **trusted-actor binding**
so a user can't act as someone else. The Step Function gains a real **validate** step (authorize the actor against the
registry); the actual provisioning verbs remain stubs until SPEC-051→055.

## Scope

### In Scope

- **Membership attributes + principal-tag mappings:** ten mutable Cognito custom attributes `custom:shared_space_1 …
  custom:shared_space_10` (string), and ten Identity-Pool `aws_cognito_identity_pool_provider_principal_tag` mappings
  to principal tags `shared_space_1..10` (added to the existing single-map resource alongside `username`); the tag
  value is the slot's space name or empty. `MAX_SHARED_MEMBERSHIPS = 10` defined once and referenced everywhere
- **Portal-role membership slots:** ten templated statement-pairs (per `shared-spaces-architecture.md` §3) — S3 object
  CRUD + multipart on `dat-prod-shared-space/${aws:PrincipalTag/shared_space_k}/*`, a `ListBucket` statement
  conditioned on `s3:prefix = ${aws:PrincipalTag/shared_space_k}/*`, and Glue on
  `database/${aws:PrincipalTag/shared_space_k}` (+ its tables) — plus **`sqs:SendMessage`** to the SPEC-050 request
  queue (only), and **delete-denies** on `dat-prod-shared-space/*/athenaresults/*` and
  `dat-prod-shared-space/*/DO_NOT_DELETE.txt`
- **Lake Formation:** register `dat-prod-shared-space` in **hybrid** access mode (as the user-space bucket, SPEC-032);
  add the SPEC-050 orchestrator role as an **LF data-lake admin** (so it can later `GrantPermissions` on shared DBs +
  `DATA_LOCATION_ACCESS` on the shared location), via the `compact()`-safe admin-list pattern (SPEC-032/033)
- **Request contract:** the SQS message schema for all shared-space actions (`create`/`add_members`/`remove_members`/
  `leave`/`delete`), versioned (`schemaVersion`); the registry object + per-user cache shapes
- **Trusted-actor binding:** the mechanism that ties a request's `actor` to the authenticated caller (SQS message
  attributes derived from the session) + the Step Function **validate** state that authorizes against the registry
  (owner/membership checks) and rejects forged/unauthorized requests with no side effects
- **Deploy-role IAM** additions for the resources introduced here (Cognito attribute + identity-pool changes; LF
  registration/admin if not already covered by SPEC-032's deploy grants — verify)
- **Validation:** `simulate-custom-policy` proving slot allow (set tag) / deny (unset tag) and the portal
  `sqs:SendMessage`; an authorized **no-op** request flows SQS→Pipe→SF→validate→(stub) and is actor-bound; an
  unauthorized/forged request fails cleanly

### Out of Scope

- **Per-action provisioning behavior** — create (SPEC-051), add/remove members (SPEC-053), leave/delete (SPEC-054),
  results routing (SPEC-055); the Step Function's create/grant/cascade bodies are stubs here
- **App/UI** (SPEC-051+)
- The **plumbing** itself (bucket, queue, Pipe, machine, orchestrator role, Lambda infra) — SPEC-050
- Changing the **personal** model — untouched

---

## Functional Requirements

### FR-001: Membership attributes + principal-tag mappings

#### Acceptance Criteria:

- [ ] The User Pool gains ten mutable custom attributes `custom:shared_space_1 … custom:shared_space_10` (string),
  writable by the orchestrator role via `AdminUpdateUserAttributes`
- [ ] The Identity Pool maps each `custom:shared_space_k` claim to principal tag `shared_space_k`
  (`aws_cognito_identity_pool_provider_principal_tag` — the existing single `principal_tags` map gains ten keys
  alongside `username`); the tag value is the claim verbatim (slot's space name or empty)
- [ ] `MAX_SHARED_MEMBERSHIPS = 10` is defined once (module variable / documented constant) and drives the slot
  count, the policy generation (a `for`/loop), and later the app (SPEC-052/053); changing it is a single edit

### FR-002: Portal-role membership slots + SendMessage + delete-denies

#### Acceptance Criteria:

- [ ] The portal role's permission policy gains **ten** templated statement-pairs, one per slot `k ∈ 1..10`: S3
  object CRUD + multipart on `arn:aws:s3:::dat-prod-shared-space/${aws:PrincipalTag/shared_space_k}/*`, a `ListBucket`
  statement conditioned on `s3:prefix = ${aws:PrincipalTag/shared_space_k}/*`, and Glue on
  `database/${aws:PrincipalTag/shared_space_k}` (+ its tables) — per `shared-spaces-architecture.md` §3
- [ ] An **unset** slot tag results in the templated statement matching **nothing** (implicit deny) — verified with
  `aws iam simulate-custom-policy` for both a set and an unset slot (no bucket-root or cross-space leak), per the
  existing `username`-tag precedent (architecture.md Authorization Model)
- [ ] A **delete-deny** on `dat-prod-shared-space/*/athenaresults/*` (mirrors the personal `athenaresults/` lock,
  SPEC-032) and on `dat-prod-shared-space/*/DO_NOT_DELETE.txt` (space marker, SPEC-014 pattern)
- [ ] The portal role gains `sqs:SendMessage` to the SPEC-050 request queue **only** (no other SQS action, no other
  queue) — the entire privileged surface the browser receives

### FR-003: Lake Formation registration + admin

#### Acceptance Criteria:

- [ ] `dat-prod-shared-space` is registered as a Lake Formation location in **hybrid** access mode (as the user-space
  bucket, SPEC-032) so the file browser keeps direct-IAM S3 while Athena reads via LF
- [ ] The SPEC-050 orchestrator role is added as an **LF data-lake admin** (so it can later `GrantPermissions` on
  shared DBs + `DATA_LOCATION_ACCESS` on the shared location), via the `compact()`-safe constructed-string admin-list
  pattern (SPEC-032/033 — no unknown ARN in the list)

### FR-004: Request contract

#### Description:

Define the message every shared-space mutation places on the queue; SPEC-051→055 produce these, the Step Function
consumes them.

#### Acceptance Criteria:

- [ ] A documented JSON message shape (Data Model) with `schemaVersion`, `requestId` (idempotency), `action`, `actor`
  (requesting username), `space` (name), and an action `payload`
- [ ] The registry object shape (`shared-spaces/{name}.json`: `owner`, `members[]`, `status`, timestamps) and the
  per-user cache shape (`{username}/user_settings/shared-connections.json`) are defined here (first written in
  SPEC-051)
- [ ] The contract is versioned so future message changes are non-breaking

### FR-005: Trusted-actor binding + validate state

#### Acceptance Criteria:

- [ ] `actor` is **never trusted from the message body** for authorization: the browser can only `sqs:SendMessage`
  (FR-002) and the request carries the caller's identity in **SQS message attributes derived from the authenticated
  session**; the Step Function **validate** state binds/authorizes `actor` against that, rejecting mismatches
- [ ] The validate state authorizes each action against the **registry** (owner-only actions verify
  `registry[space].owner == actor`; member actions verify membership); an unauthorized/forged request terminates in
  the **failure** state with a recorded reason and **no** side effects
- [ ] The per-action verbs invoked after validate remain stubs in this spec (SPEC-051→055 implement them); validate +
  the failure path are real and tested

### FR-006: Deploy IAM + validation

#### Acceptance Criteria:

- [ ] `infra/modules/base/policies/` is extended for the Cognito attribute + identity-pool changes and any LF
  registration/admin actions not already granted to the deploy role by SPEC-032 (verify); non-scopable actions in
  their own `"*"` statements
- [ ] `tofu validate` + `plan` succeed; `simulate-custom-policy` proves slot allow/deny (set/unset) + portal
  `sqs:SendMessage`; an authorized no-op request flows end-to-end and is actor-bound, a forged/unauthorized one fails
  cleanly — documented in `docs/testing/e2e.md`

---

## Data Model

```jsonc
// SQS request message (FR-004). schemaVersion guards future changes.
{
  "schemaVersion": 1,
  "requestId": "uuid",
  "action": "create | add_members | remove_members | leave | delete",
  "actor": "alice",                     // ADVISORY ONLY — never trusted (FR-005)
  "space": "salesdata",                 // catalog-safe name == prefix == Glue DB
  "payload": { "members": ["bob","cara"] },
  "idToken": "<cognito id token>"       // transport auth: Lambda verifies (JWKS) → trusted actor = cognito:username
}
```

```jsonc
// Registry object  s3://<admin-bucket>/shared-spaces/{name}.json  (source of truth)
{ "version": 1, "name": "salesdata", "owner": "alice", "members": ["alice","bob"],
  "status": "active | provisioning | failed | deleting", "createdAt": "ISO", "lastRequestId": "uuid" }
```

```hcl
# infra/modules/shared-spaces/variables.tf
variable "max_shared_memberships" { default = 10 }   # FR-001; single source for the slot count
```

(The per-user cache shape `SharedConnectionsCache`/`SharedConnectionEntry` is the app type defined in SPEC-051.)

## File & Folder Structure

```
infra/modules/shared-spaces/
├── cognito.tf            # custom:shared_space_1..10 attributes + identity-pool principal-tag mappings (FR-001)
├── lakeformation.tf      # hybrid registration of the shared bucket + orchestrator as LF admin (FR-003)
├── policies/             # .tftpl: portal-role membership slots + sqs:SendMessage + delete-denies (FR-002)
├── stepfunction.tf       # + the real `validate` state + actor binding (FR-005); action verbs stay stubs
└── variables.tf          # + max_shared_memberships

infra/modules/data/policies/portal-role-permissions.json.tftpl   # + 10 membership slots + sqs:SendMessage + denies
lambdas/shared-space-provisioner/shared_space_provisioner.py      # + validate/authorize (actor binding); verbs stubbed
infra/modules/base/policies/                                       # deploy-role additions (FR-006)
docs/testing/e2e.md                                  # access + authorized/forged request tests (FR-006)
```

## Implementation Phases

### Phase 1: Membership tags + portal slots + LF

- Cognito attributes + identity-pool mappings (FR-001); portal-role ten slots + `sqs:SendMessage` + delete-denies,
  proven with `simulate-custom-policy` (FR-002); LF hybrid registration + orchestrator LF admin (FR-003); deploy IAM
  (FR-006 partial)

#### Checkpoint

`simulate-custom-policy` shows a set `shared_space_k` tag allows that space's S3/Glue and an unset slot denies (no
leak); the portal role can `sqs:SendMessage` to the queue only; `dat-prod-shared-space` is LF-registered (hybrid) and
the orchestrator is an LF admin. `tofu validate`/`plan` clean (expect one self-grant re-run).

### Phase 2: Request contract + actor binding + validate

- Request/registry/cache shapes (FR-004); trusted-actor binding + the Step Function `validate`/authorize state +
  failure path (FR-005); end-to-end authorized-vs-forged request test (FR-006)

#### Checkpoint

An authorized no-op request flows SQS→Pipe→SF→validate (actor bound, registry-authorized) and a forged/unauthorized
request lands in the failure state with no side effects. Documented in `docs/testing/e2e.md`.

## Implementation Decisions (in-session, 2026-06-26)

Reversible/technical choices made during build (per `docs/process/session-rhythm.md`):

- **Trusted-actor binding = verified Cognito ID token** (user decision, over the spec's
  "message attributes" default). The request body carries `idToken`; the provisioner
  Lambda verifies its RS256 signature against the pool **JWKS** + claims (iss, aud =
  SPA client, exp, `token_use=id`) and derives the trusted `actor` from
  `cognito:username`. The body `actor` is advisory and ignored. Genuinely unspoofable
  (the browser can't mint a Cognito-signed token); consistent with the notifications
  arc (058). Adds `PyJWT[crypto]` to `lambdas/requirements.txt`.
- **ID token in the message body, not a message attribute** — robust through the
  EventBridge Pipe (the Lambda already parses the body JSON; avoids depending on the
  Pipe's messageAttribute passthrough shape).
- **Validate lives in the provisioner Lambda** (the single Dispatch task), not a
  separate Step Function state — consistent with SPEC-050's one-Lambda-with-an-action-
  switch decision. The Lambda validates first and raises `AuthorizationError` on a
  forged/unauthorized request; that error is **not** in the Retry list (only Lambda
  *service* errors retry), so it goes straight to the existing `Catch (States.ALL) →
  Fail` with no side effects (verbs haven't run). `authorize()` is a pure function,
  unit-tested directly.
- **Authorization rules:** `create` = any verified actor (name uniqueness is SPEC-051's
  atomic conditional PutObject, not an authz concern); `add_members`/`remove_members`/
  `delete` = owner-only (`registry.owner == actor`); `leave` = a member who isn't the
  owner. Registry read from `shared-spaces/{space}.json` (orchestrator role already has
  `s3:GetObject` there, SPEC-050).
- **Membership slots consolidated** into resource-list statements (not 10×3 separate
  statements) and kept as a **third inline** policy on the portal role (fixed 10 slots,
  aggregate 6,491 < 10,240 — no managed policy needed).
- **LF orchestrator-admin coupling:** `module.analytics` gains `depends_on
  [module.shared_spaces]` so the orchestrator role exists before it's added to the LF
  admins list (constructed-string ARN, compact()-safe).

## Open Questions

- [x] **Resolved (2026-06-21, user decision):** **`MAX_SHARED_MEMBERSHIPS = 10`** bounded Cognito attribute slots;
  grant/revoke applies on the next token refresh (`shared-spaces-architecture.md` §3), forced by the SPEC-052
  Refresh-connections control.
- [x] **Resolved (2026-06-21):** enforcement is the **membership principal tag** on the shared role; LF grants the
  role per shared DB and IAM is the gate (not LF-Tags, not per-user roles) — same shape as the personal `username`-tag
  model.
- [x] **Resolved (2026-06-21, default):** trusted-actor binding (FR-005) uses **SQS message attributes derived from
  the authenticated session** plus a **registry owner/membership check** in the validate state; the body `actor` is
  advisory only. Confirm during design if you want a stricter binding (e.g. a signed token in the message).

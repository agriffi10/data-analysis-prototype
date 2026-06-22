# Spec: Notifications Foundation Infrastructure (Write Pipeline + IAM)

**ID:** SPEC-058
**Status:** Draft
**Last Updated:** 2026-06-22
**Depends On:** SPEC-010 (user-space bucket conventions), SPEC-011 (Identity Pool ABAC + portal role + module wiring), SPEC-012 (Lambda code/infra split + `deploy-lambdas.yml`), SPEC-006 (Cognito User Pool — token issuer for actor binding)

> **First of the notifications arc (058 → 059 → 060).** This spec builds the **write side only**:
> the dedicated async control plane (SQS → EventBridge Pipe → Step Function → notifications-writer
> Lambda) and a single privileged **notifications-writer role** that is the **only writer** of each
> user's `notifications.json`, plus the deploy-role IAM and the portal-role `sqs:SendMessage` grant.
> It ships **no browser/UI behavior** (the read service + hook are SPEC-059; the drawer + header button
> are SPEC-060). The pipeline pattern intentionally mirrors the shared-spaces control plane (SPEC-050)
> but stands up its **own dedicated** queue / pipe / state machine / Lambda / role — the two domains
> stay decoupled. All IaC is OpenTofu; IAM is `.tftpl`; Lambda code/infra are split.

## Overview

Give the portal a per-user notifications inbox. A notification is a short message addressed to one user;
notifications live as a single JSON document in that user's settings prefix
(`{username}/user_settings/notifications.json`). Because notifications are produced both by **system
events** (some upstream process wants to tell a user something) and by the **user's own actions**
(marking read, deleting), and because the user-space bucket has versioning **off**, having two
independent writers race on one object would silently lose updates. This spec therefore establishes a
**single-writer** model: every mutation — create, mark-read, mark-all-read, delete, delete-all — is a
message on one SQS queue, drained by an EventBridge Pipe into a Step Function that invokes one
**notifications-writer Lambda**, which read-modify-writes the target user's `notifications.json` under a
privileged role. The browser **never writes** the file (it only reads it, in SPEC-059). When this spec is
done, a message placed on the queue flows Pipe → Step Function → Lambda and produces/updates the correct
user's `notifications.json`, end to end — with no UI yet.

## Scope

### In Scope

- **Notifications storage convention** — the document lives at
  `{username}/user_settings/notifications.json` in the **existing user-space bucket** (SPEC-010); no new
  bucket. The writer role's S3 access is scoped to `…/*/user_settings/notifications.json`. The portal
  role's existing `user_settings/*` **DeleteObject deny** (analytics `portal-role-analytics.json.tftpl`)
  already prevents the browser from deleting it; this spec adds that the browser also never **writes** it.
- **Control plane (dedicated)** — an **SQS** request queue + **DLQ** (redrive `maxReceiveCount`); an
  **EventBridge Pipe** (SQS source → Step Function target) + its role; a **Step Function** (Standard) with
  explicit **entry → (Lambda invoke) → success/failure** states; the **notifications-writer Lambda** infra
  (placeholder zip + `ignore_changes`, Python 3.12) + a `deploy-lambdas.yml` matrix row; CloudWatch log
  groups (14-day retention) for the Lambda and the machine.
- **Notifications-writer role** — the single privileged IAM role the Step Function / Lambda run under,
  with a `.tftpl` permission policy: `s3:GetObject`/`s3:PutObject` on
  `${user_space_bucket_arn}/*/user_settings/notifications.json`; `states`/`logs`; (for actor binding,
  FR-005) `cognito-idp:GetUser`/token-verify needs no Cognito call if verifying the JWT signature offline,
  so no Cognito IAM is required by default — see FR-005. Scoped to the relevant ARNs, non-scopable actions
  isolated to their own `"*"` statements (architecture.md trap list), verified with
  `aws iam simulate-custom-policy`.
- **The message contract** — a single JSON envelope with an `action` discriminator
  (`create` | `markRead` | `markAllRead` | `delete` | `deleteAll`) plus the fields each action needs
  (FR-003). The Lambda is an `action`-switch (one Lambda, not one-per-action).
- **The writer's read-modify-write + cap semantics** — read current doc (missing/corrupt → empty array),
  apply the action, **cap to the most-recent `NOTIFICATIONS_MAX` by timestamp**, `PutObject` the whole
  document (FR-004). Notifications carry a server-assigned `id` and `timestamp`.
- **Producer access** — the **portal role** gains `sqs:SendMessage` to the queue (user-action messages);
  **trusted system producers** (whatever upstream emits `create`s) also need `sqs:SendMessage` — granting
  *those* identities is out of scope here (this spec only exposes the queue ARN/URL as an output and
  documents the contract).
- **Actor binding (anti-spoofing)** — for **user-originated** actions the message must carry the caller's
  Cognito **ID token**; the writer verifies it against the User Pool and derives the target `username`
  from the verified `cognito:username` claim, **ignoring any client-supplied username** for those actions
  (FR-005). `create` is a system/trusted-producer action and uses the body `username`.
- **New bounded-context module** `infra/modules/notifications/`, **standalone-deployable** like
  `module.analytics` (cross-module ARNs as `compact()`-safe constructed-string locals — architecture.md
  "unknown ARN in list" trap).
- **Deploy-role IAM** expanded for every new resource type (SQS queue + DLQ, Pipes, Step Functions, the new
  Lambda + its exec/writer role incl. scoped `iam:PassRole`, the log groups).
- A **control-plane smoke test** (`docs/testing/notifications-e2e.md`): a `create` message on the queue
  reaches the writer and produces the correct user's `notifications.json` (CloudWatch shows the
  execution + the write).

### Out of Scope

- **Browser read path** — `notifications.service.ts`, the `useNotifications` hook, the SQS-send helpers,
  the `@aws-sdk/client-sqs` dependency — all **SPEC-059**.
- **Any UI** — header button, unread indicator, slide-out drawer, pagination, action buttons — **SPEC-060**.
- **Granting trusted system producers** `sqs:SendMessage` and wiring real upstream event sources — out of
  scope (this spec defines the contract + exports the queue; who may create notifications is a later
  decision). The smoke test sends a `create` using the deploy/admin identity.
- Changing the personal-space model (user-space bucket, `username`-tag scoping) beyond adding the
  notifications key convention — untouched. No relation to the shared-spaces control plane (SPEC-050).

---

## Functional Requirements

### FR-001: Dedicated control plane (SQS → Pipe → Step Function → Lambda)

#### Description:

Stand up a dedicated async pipeline that serializes all notification mutations through one writer.

#### Acceptance Criteria:

- [ ] An **SQS** request queue + **DLQ** (redrive `maxReceiveCount`, e.g. 3) is created in a new
  `infra/modules/notifications/` module; queue URL + ARN are module outputs.
- [ ] An **EventBridge Pipe** consumes the queue and targets the **Step Function**; the pipe's role can
  `sqs:ReceiveMessage`/`DeleteMessage`/`GetQueueAttributes` on the queue and `states:StartExecution` on
  the machine.
- [ ] A **Step Function** (Standard) is created with explicit **entry → (Lambda invoke) → success/failure**
  states; a failed write surfaces in the failure state and (after retries) the message lands in the DLQ.
- [ ] The **notifications-writer Lambda** source lives at
  `lambdas/notifications-writer/notifications_writer.py` (Python 3.12, underscores in filename); Terraform
  owns only the function infra with the placeholder-zip + `ignore_changes` pattern; `deploy-lambdas.yml`
  gains a matrix row.
- [ ] CloudWatch log groups (14-day retention, as SPEC-012/033) exist for the Lambda and the state machine.

### FR-002: Notifications-writer role (single privileged writer)

#### Description:

The Step Function / Lambda run under one role that may read and write **any** user's notifications doc and
nothing else app-relevant.

#### Acceptance Criteria:

- [ ] A `.tftpl` permission policy grants `s3:GetObject` + `s3:PutObject` **only** on
  `${user_space_bucket_arn}/*/user_settings/notifications.json` (the `*` is the per-user prefix segment),
  plus `states`/`logs` for its own execution/logging.
- [ ] The role grants **no** `s3:DeleteObject` anywhere (deletes are document rewrites, never S3 deletes —
  consistent with saved-queries/history) and no access to the admin or shared buckets.
- [ ] Non-scopable actions (if any) are isolated to their own `"*"` statements; the policy is verified with
  `aws iam simulate-custom-policy` (an `s3:PutObject` to one user's `notifications.json` is `allowed`; a
  `PutObject` to another key under the same prefix is `implicitDeny`).

### FR-003: Message contract

#### Description:

One envelope shape for every mutation, with an `action` discriminator.

#### Acceptance Criteria:

- [ ] The queue accepts a JSON body matching the envelope in **Data Model** below; `action` is one of
  `create` | `markRead` | `markAllRead` | `delete` | `deleteAll`.
- [ ] `create` carries `username` (target) + `message`; `markRead`/`delete` carry the target notification
  `id`; `markAllRead`/`deleteAll` carry no item id. User-originated actions
  (`markRead`/`markAllRead`/`delete`/`deleteAll`) additionally carry an `idToken` (FR-005).
- [ ] A message that fails schema validation is rejected by the writer (logged + routed to failure → DLQ
  after retries); it never partially writes the document.
- [ ] The contract is documented in `docs/testing/notifications-e2e.md` (or a sibling doc) so SPEC-059's
  send-helpers and any system producer build to the same shape.

### FR-004: Writer read-modify-write + cap

#### Description:

The Lambda applies the action against the current document atomically (per message) and caps growth.

#### Acceptance Criteria:

- [ ] The writer reads `{username}/user_settings/notifications.json`; a missing or corrupt object is
  treated as an **empty array** (never an error that blocks a `create`).
- [ ] `create` prepends a new `Notification` with a **server-assigned** `id` (uuid) and `timestamp`
  (ISO-8601, writer clock) and `read: false`; `markRead` sets `read: true` on the matching `id` (no-op if
  absent); `markAllRead` sets `read: true` on all; `delete` removes the matching `id` (no-op if absent);
  `deleteAll` writes an empty array.
- [ ] After applying, the document is **capped to the most-recent `NOTIFICATIONS_MAX` (default 200) by
  `timestamp`** before `PutObject` (newest kept); the whole document is written in one `PutObject`
  (`application/json`).
- [ ] Two messages for the same user processed in sequence both land (Step Function executions for the same
  user do not interleave a lost update — document the Step Function/queue ordering assumption and, if
  needed, the per-user concurrency control in the e2e doc).

### FR-005: Actor binding (anti-spoofing) for user-originated actions

#### Description:

A user must not be able to mutate another user's notifications by putting a different `username` on the
wire.

#### Acceptance Criteria:

- [ ] For `markRead` / `markAllRead` / `delete` / `deleteAll`, the writer **requires** an `idToken`,
  verifies it against the User Pool (issuer, signature via the pool JWKS, expiry, audience), and uses the
  verified `cognito:username` claim as the target — **any `username` field in the body is ignored** for
  these actions.
- [ ] A user-originated message with a missing/expired/invalid token is rejected (failure → DLQ); no write
  occurs.
- [ ] `create` is a **trusted-producer** action: it uses the body `username` (only identities explicitly
  granted `sqs:SendMessage` can enqueue, and the portal role's grant is scoped so the browser cannot forge
  a `create` for another user — see FR-006 note). The token-verification approach mirrors the existing
  "unspoofable, server-side username from the verified token claim" decision (CLAUDE.md Auth; pre-signup /
  post-confirmation Lambdas).

### FR-006: Producer access (portal role `sqs:SendMessage`)

#### Description:

The browser (portal role) must be able to enqueue user-action messages.

#### Acceptance Criteria:

- [ ] The portal role's IAM (a `.tftpl` statement, co-located with the analytics/data portal-role policies
  or a new notifications fragment) gains `sqs:SendMessage` on the notifications queue ARN **only**.
- [ ] The portal role gets **no** other notifications-pipeline permissions (no Lambda invoke, no Step
  Function, no DLQ). The queue ARN is wired to the app as a `VITE_*` var in SPEC-059 (this spec exports it).
- [ ] **CONFIRM (Open Question):** whether the portal role may enqueue `create` at all. Default: **no** —
  the browser sends only the four user-action types; `create` comes exclusively from trusted system
  producers. If product wants user-self-created notes, revisit.

### FR-007: Deploy-role IAM expansion + standalone module

#### Acceptance Criteria:

- [ ] `infra/modules/base/policies/` is extended for every new resource type: SQS (queue + DLQ), Pipes,
  Step Functions (machine + execution), the new Lambda + its exec/writer role (incl. scoped
  `iam:PassRole`), the log groups.
- [ ] Non-scopable actions isolated to `"*"` statements; document the expected first-apply
  self-grant-propagation failure → clean re-run for any first-use-gated resource (architecture.md
  `time_sleep` caveat).
- [ ] The module is **standalone-deployable** (`compact()`-safe constructed-string locals for any
  cross-module ARN — user-space bucket ARN, User Pool id/JWKS — so no unknown-ARN-in-list drop);
  `tofu -chdir=infra validate` + `plan` succeed.

### FR-008: Control-plane smoke test

#### Acceptance Criteria:

- [ ] `docs/testing/notifications-e2e.md` documents: placing a `create` message on the queue drives
  Pipe → Step Function → writer Lambda and produces `{username}/user_settings/notifications.json` with the
  expected `Notification` (CloudWatch shows the execution + the write); a `markRead` then flips `read` on
  that id; a malformed/forged user-action message lands in the DLQ with no write.

---

## Data Model

No app TypeScript here (SPEC-059 defines the shared TS types; they must match this contract). Wire shapes:

```jsonc
// The stored document: {username}/user_settings/notifications.json
// A plain array, newest-first, capped to NOTIFICATIONS_MAX.
[
  {
    "id": "b3f1…",            // server-assigned (uuid), set on create
    "message": "Your export finished.",
    "read": false,
    "timestamp": "2026-06-22T14:03:11.482Z"  // ISO-8601, writer clock
  }
]
```

```jsonc
// SQS message body — one envelope, `action`-discriminated.
// create (trusted producer):
{ "action": "create", "username": "alice", "message": "Your export finished." }

// user-originated (browser); idToken REQUIRED, username DERIVED from the token:
{ "action": "markRead",     "id": "b3f1…", "idToken": "<cognito id token>" }
{ "action": "markAllRead",                  "idToken": "<cognito id token>" }
{ "action": "delete",       "id": "b3f1…", "idToken": "<cognito id token>" }
{ "action": "deleteAll",                    "idToken": "<cognito id token>" }
```

```hcl
# infra/modules/notifications/variables.tf
variable "notifications_max"        { default = 200 }   # writer-side cap (newest kept)
variable "user_space_bucket_arn"    {}                  # constructed-string local from root
variable "user_pool_id"             {}                  # for JWKS issuer/audience (FR-005)
variable "dlq_max_receive_count"    { default = 3 }
```

## API / Interface Contract

The writer Lambda is internal; its only contract is the SQS envelope above. The exported Terraform outputs
are the integration surface for SPEC-059:

```hcl
# infra/modules/notifications/outputs.tf
output "notifications_queue_url"  { value = aws_sqs_queue.requests.url }   # → VITE_NOTIFICATIONS_QUEUE_URL (SPEC-059)
output "notifications_queue_arn"  { value = aws_sqs_queue.requests.arn }   # → portal-role SendMessage (FR-006)
output "notifications_writer_role_arn" { value = aws_iam_role.writer.arn }
output "notifications_state_machine_arn" { value = aws_sfn_state_machine.writer.arn }
```

## Environment Variables

No new `VITE_*` in this spec — the queue URL is **exported** here and **consumed** (as
`VITE_NOTIFICATIONS_QUEUE_URL`) in SPEC-059. Document the export in `infra` outputs so SPEC-059 wires it.

## File & Folder Structure

```
infra/modules/notifications/
├── sqs.tf                # request queue + DLQ (+ redrive)
├── pipe.tf               # EventBridge Pipe (SQS → Step Function) + pipe role
├── stepfunction.tf       # state machine (entry → Lambda invoke → success/failure) + log group
├── lambda.tf             # notifications-writer function infra (placeholder + ignore_changes) + log group
├── iam.tf                # writer role + pipe role + sfn execution role wiring
├── policies/             # .tftpl: writer role, pipe role, sfn execution role; portal-role SendMessage fragment
├── variables.tf          # names + cross-module ARNs (constructed-string locals) + notifications_max
└── outputs.tf            # queue URL/ARN, writer role ARN, state-machine ARN

lambdas/notifications-writer/
└── notifications_writer.py          # action-switch read-modify-write + JWT verify (FR-004/005)

infra/modules/base/policies/          # deploy-role expansion (FR-007)
infra/modules/<portal-role module>/   # portal-role sqs:SendMessage statement (FR-006)
.github/workflows/deploy-lambdas.yml  # + notifications-writer matrix row
docs/testing/notifications-e2e.md     # contract + control-plane smoke test (FR-003/FR-008)
```

## Implementation Phases

### Phase 1: Module scaffold + control plane skeleton

- New `infra/modules/notifications/` module; SQS queue + DLQ; EventBridge Pipe + role; Step Function
  skeleton (entry → Lambda invoke → success/failure); writer Lambda infra (placeholder zip +
  `ignore_changes`) + `deploy-lambdas.yml` row; log groups; deploy-role IAM for these resource types
  (FR-001, FR-007 partial). Writer Lambda is a dispatch/echo stub at this point.

#### Checkpoint

(Expect one self-grant re-run.) `tofu -chdir=infra validate`/`plan`/`apply` clean. A message placed on the
queue reaches the Step Function and the stub Lambda (CloudWatch shows the execution + the echo). No JSON
written yet.

### Phase 2: Writer logic + actor binding + smoke test

- Implement the `action`-switch read-modify-write + cap (FR-004); JWT verification for user-originated
  actions (FR-005); writer-role S3 policy scoped to `…/user_settings/notifications.json` verified with
  `simulate-custom-policy` (FR-002); portal-role `sqs:SendMessage` (FR-006); message-contract + smoke-test
  doc (FR-003, FR-008); finish deploy-role IAM (FR-007).

#### Checkpoint

A `create` on the queue produces the correct `{username}/user_settings/notifications.json`; a `markRead`
flips `read` on that id; `deleteAll` empties it; a forged/expired user-action message lands in the DLQ with
no write. `simulate-custom-policy` confirms the writer role can write only the notifications key. All
documented in `docs/testing/notifications-e2e.md`.

## Open Questions

- [x] **Resolved (2026-06-22, user decision):** all mutations (create + user actions) go through the
  pipeline — the browser never writes `notifications.json` (single-writer; avoids lost updates with
  versioning off).
- [x] **Resolved (2026-06-22, user decision):** a **dedicated** notifications pipeline (its own
  SQS/Pipe/Step Function/Lambda/role), not an extension of the shared-spaces control plane.
- [ ] **FR-006 CONFIRM:** may the portal (browser) enqueue `create`, or are creates trusted-producer-only
  (default)? Affects whether the browser can self-create notifications.
- [ ] **FR-004:** is per-user write serialization adequate via the Step Function + standard queue, or is an
  explicit guard (e.g. a per-user lock / FIFO message-group-id = username) needed to fully prevent
  interleaved lost updates under burst? Decide before Phase 2.
- [ ] Who are the **trusted system producers** of `create` messages, and how are they granted
  `sqs:SendMessage`? (Out of scope to build here, but name them so the contract/IAM are sized right.)
- [ ] **FR-005:** verify the Cognito ID-token JWKS offline in the Lambda (no Cognito API call) vs.
  `cognito-idp:GetUser` — default to offline JWKS verification (no extra IAM). Confirm at implementation.

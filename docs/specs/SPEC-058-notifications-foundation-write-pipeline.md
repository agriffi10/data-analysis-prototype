---
type: Spec
id: SPEC-058
title: "Notifications Foundation Infrastructure (Write Pipeline + IAM)"
description: "Gives operators a per-user notifications write pipeline, using a FIFO queue and single-writer Lambda that updates each user's notifications.json for create, mark-read, and mark-all-read without lost updates."
spec_status: Completed
depends_on: [SPEC-010, SPEC-011, SPEC-012, SPEC-006]
arc: notifications
arc_order: 1
---

**Dependency notes:** SPEC-010 (user-space bucket conventions), SPEC-011 (Identity Pool ABAC + portal role + module wiring), SPEC-012 (Lambda code/infra split + `deploy-lambdas.yml`), SPEC-006 (Cognito User Pool — token issuer for actor binding)
> **First of the notifications arc (058 → 059 → 060 → 061).** This spec builds the **write side only**:
> a dedicated **FIFO SQS queue that triggers the notifications-writer Lambda directly** (an SQS event-source
> mapping — **no EventBridge Pipe, no Step Function**) and a single privileged **notifications-writer role**
> that is the **only writer** of each user's `notifications.json`, plus the deploy-role IAM and the
> portal-role `sqs:SendMessage` grant. It ships **no browser/UI behavior** (the read service + hook are
> SPEC-059; the header bell + page are SPEC-060; the first real `create` producer is SPEC-061). The write
> path is intentionally **simple** — a single small Lambda doing one task behind a FIFO queue
> (`lambdas/info/best-practices/lambdas/lambdas.md` §1/§10: no Step Function for a one-task write) — and **dedicated**
> (its own queue / Lambda / role), decoupled from the shared-spaces control plane (SPEC-050). All IaC is
> OpenTofu; IAM is `.tftpl`; Lambda code/infra are split.

## Overview

Give the portal a per-user notifications inbox. A notification is a short message addressed to one user;
notifications live as a single JSON document in that user's settings prefix
(`{username}/user_settings/notifications.json`). Because notifications are produced both by **system
events** (some upstream process wants to tell a user something) and by the **user's own actions**
(marking read, deleting), and because the user-space bucket has versioning **off**, having two
independent writers race on one object would silently lose updates. This spec therefore establishes a
**single-writer** model: every mutation — create, mark-read, mark-all-read — is a
message on one **FIFO** SQS queue that **triggers** one **notifications-writer Lambda** directly (SQS
event-source mapping), which read-modify-writes the target user's `notifications.json` under a privileged
role. The **FIFO queue + per-user message group + batch-size-1** delivery guarantees the writer processes a
given user's messages **one at a time, in arrival order** — so there is no lost update and no need for a
Step Function to serialize. The browser **never writes** the file (it only reads it, in SPEC-059). When this
spec is done, a message placed on the queue invokes the Lambda and produces/updates the correct user's
`notifications.json`, end to end — with no UI yet.

## Scope

### In Scope

- **Notifications storage convention** — the document lives at
  `{username}/user_settings/notifications.json` in the **existing user-space bucket** (SPEC-010); no new
  bucket. The writer role's S3 access is scoped to `…/*/user_settings/notifications.json`. The portal
  role's existing `user_settings/*` **DeleteObject deny** (analytics `portal-role-analytics.json.tftpl`)
  already prevents the browser from deleting it; this spec adds that the browser also never **writes** it.
- **Write path (dedicated, no Step Function)** — a **FIFO SQS** request queue (`.fifo`) + a **FIFO DLQ**
  (redrive `maxReceiveCount`); an **SQS event-source mapping** that invokes the **notifications-writer
  Lambda** directly (**batch size 1**, so one message → one invocation); the writer Lambda infra
  (placeholder zip + `ignore_changes`, Python 3.12) + a `deploy-lambdas.yml` matrix row; a CloudWatch log
  group (14-day retention) for the Lambda. **No EventBridge Pipe and no Step Function** — the queue triggers
  the Lambda. **Ordering/serialization** comes from FIFO: producers set **`MessageGroupId` = the target
  username**, so all of one user's messages are delivered in order and a group's next message isn't released
  until the prior one is processed (single-writer per user); different users' groups may process in parallel
  (different files, no contention).
- **Notifications-writer role** — the single privileged IAM role the Lambda runs under, with a `.tftpl`
  permission policy: `s3:GetObject`/`s3:PutObject` on
  `${user_space_bucket_arn}/*/user_settings/notifications.json`; the SQS receive actions the event-source
  mapping needs on the queue (`sqs:ReceiveMessage`/`DeleteMessage`/`GetQueueAttributes`); `logs`; (for actor
  binding, FR-005) token verification is **offline JWKS** so **no Cognito IAM** is required by default — see
  FR-005. Scoped to the relevant ARNs, non-scopable actions isolated to their own `"*"` statements
  (architecture.md trap list), verified with `aws iam simulate-custom-policy`.
- **The message contract** — a single JSON envelope with an `action` discriminator
  (`create` | `markRead` | `markAllRead`) plus the fields each action needs
  (FR-003). The Lambda is an `action`-switch (one Lambda, not one-per-action). **There is no
  `delete`/`deleteAll`** — notifications are never removed; the inbox only grows (capped writer-side) and
  the user's only mutations are mark-read / mark-all-read (user decision, 2026-06-27).
- **The writer's read-modify-write + cap semantics** — read current doc (missing/corrupt → empty array),
  apply the action, **cap to the most-recent `NOTIFICATIONS_MAX` by timestamp**, `PutObject` the whole
  document (FR-004). Notifications carry a server-assigned `id` and `timestamp`.
- **Producer access** — the **portal role** gains `sqs:SendMessage` to the queue (user-action messages);
  **trusted system producers** (whatever upstream emits `create`s) also need `sqs:SendMessage` — granting
  *those* identities is out of scope here (this spec only exposes the queue ARN/URL as an output and
  documents the contract).
- **Actor binding (anti-spoofing)** — for **user-originated** actions (`markRead` / `markAllRead`) the
  message must carry the caller's Cognito **ID token**; the writer verifies it against the User Pool and
  derives the target `username` from the verified `cognito:username` claim, **ignoring any client-supplied
  username** for those actions (FR-005). `create` is a system/trusted-producer action and uses the body
  `username` (the first producer is the shared-workspace control plane — SPEC-061).
- **New bounded-context module** `infra/modules/notifications/`, **standalone-deployable** like
  `module.analytics` (cross-module ARNs as `compact()`-safe constructed-string locals — architecture.md
  "unknown ARN in list" trap).
- **Deploy-role IAM** expanded for every new resource type (FIFO SQS queue + DLQ, the SQS event-source
  mapping, the new Lambda + its writer role incl. scoped `iam:PassRole`, the log group). **No Pipes / Step
  Functions** to grant for.
- A **smoke test** (`docs/testing/e2e.md`): a `create` message on the queue invokes the writer
  and produces the correct user's `notifications.json` (CloudWatch shows the Lambda invocation + the write).

### Out of Scope

- **Browser read path** — `notifications.service.ts`, the `useNotifications` hook, the SQS-send helpers,
  the `@aws-sdk/client-sqs` dependency — all **SPEC-059**.
- **Any UI** — header bell link, unread indicator, notifications page, pagination, action buttons — **SPEC-060**.
- **Granting trusted system producers** `sqs:SendMessage` and wiring real upstream event sources — out of
  scope here (this spec defines the contract + exports the queue). The **first** producer — the
  shared-workspace control plane emitting the seven lifecycle events — is wired in **SPEC-061**. The smoke
  test in this spec sends a `create` using the deploy/admin identity.
- Changing the personal-space model (user-space bucket, `username`-tag scoping) beyond adding the
  notifications key convention — untouched. No relation to the shared-spaces control plane (SPEC-050).

---

## Functional Requirements

### FR-001: Dedicated write path (FIFO SQS → writer Lambda, no Step Function)

#### Description:

Stand up a dedicated FIFO queue that triggers one writer Lambda, serializing each user's mutations.

#### Acceptance Criteria:

- [ ] A **FIFO SQS** request queue (`.fifo`, **content-based or explicit** message dedup) + a **FIFO DLQ**
  (redrive `maxReceiveCount`, e.g. 3) is created in a new `infra/modules/notifications/` module; queue URL +
  ARN are module outputs.
- [ ] An **SQS event-source mapping** invokes the **notifications-writer Lambda** directly with **batch size
  1** — **no EventBridge Pipe and no Step Function**. (Best-practices §10: don't add a Step Function for a
  single-task write.)
- [ ] **Per-user serialization:** producers set **`MessageGroupId` = the target username**; FIFO then
  delivers a user's messages strictly in arrival order, one at a time (the next isn't released until the
  prior is deleted), so the writer never races itself on one user's file. (Different users = different groups
  = may process concurrently.)
- [ ] The **notifications-writer Lambda** source lives at
  `lambdas/notifications-writer/notifications_writer.py` (Python 3.12, underscores in filename); Terraform
  owns only the function infra with the placeholder-zip + `ignore_changes` pattern; `deploy-lambdas.yml`
  gains a matrix row.
- [ ] A CloudWatch log group (14-day retention, as SPEC-012/033) exists for the Lambda. A message whose
  processing fails is retried by the event-source mapping and, after `maxReceiveCount`, lands in the DLQ.

### FR-002: Notifications-writer role (single privileged writer)

#### Description:

The Lambda runs under one role that may read and write **any** user's notifications doc and nothing else
app-relevant.

#### Acceptance Criteria:

- [ ] A `.tftpl` permission policy grants `s3:GetObject` + `s3:PutObject` **only** on
  `${user_space_bucket_arn}/*/user_settings/notifications.json` (the `*` is the per-user prefix segment),
  the queue receive actions (`sqs:ReceiveMessage`/`DeleteMessage`/`GetQueueAttributes`) for the event-source
  mapping, plus `logs` for its own logging.
- [ ] The role grants **no** `s3:DeleteObject` anywhere (the document is only ever read-modify-rewritten
  via `PutObject`, never S3-deleted — consistent with saved-queries/history) and no access to the admin or
  shared buckets.
- [ ] Non-scopable actions (if any) are isolated to their own `"*"` statements; the policy is verified with
  `aws iam simulate-custom-policy` (an `s3:PutObject` to one user's `notifications.json` is `allowed`; a
  `PutObject` to another key under the same prefix is `implicitDeny`).

### FR-003: Message contract

#### Description:

One envelope shape for every mutation, with an `action` discriminator.

#### Acceptance Criteria:

- [ ] The queue accepts a JSON body matching the envelope in **Data Model** below; `action` is one of
  `create` | `markRead` | `markAllRead`.
- [ ] `create` carries `username` (target) + `message`; `markRead` carries the target notification
  `id`; `markAllRead` carries no item id. User-originated actions
  (`markRead`/`markAllRead`) additionally carry an `idToken` (FR-005).
- [ ] Every message is sent with **`MessageGroupId` = the target username** (the recipient for `create`; the
  caller's own username for user-actions) so FIFO serializes per user (FR-001), plus a `MessageDeduplicationId`
  (or content-based dedup) so an accidental duplicate send is collapsed by FIFO.
- [ ] A message that fails schema validation is rejected by the writer (logged → the invocation fails so the
  message retries and, after `maxReceiveCount`, lands in the DLQ); it never partially writes the document.
- [ ] The contract is documented in `docs/testing/e2e.md` (or a sibling doc) so SPEC-059's
  send-helpers and any system producer build to the same shape.

### FR-004: Writer read-modify-write + cap

#### Description:

The Lambda applies the action against the current document atomically (per message) and caps growth.

#### Acceptance Criteria:

- [ ] The writer reads `{username}/user_settings/notifications.json`; a missing or corrupt object is
  treated as an **empty array** (never an error that blocks a `create`).
- [ ] `create` prepends a new `Notification` with a **server-assigned** `id` (uuid) and `timestamp`
  (ISO-8601, writer clock) and `read: false`; `markRead` sets `read: true` on the matching `id` (no-op if
  absent); `markAllRead` sets `read: true` on all. (There is no `delete`/`deleteAll` — see Scope.)
- [ ] After applying, the document is **capped to the most-recent `NOTIFICATIONS_MAX` (default 200) by
  `timestamp`** before `PutObject` (newest kept); the whole document is written in one `PutObject`
  (`application/json`).
- [ ] Two messages for the same user both land without a lost update: the **FIFO group (`MessageGroupId` =
  username) + batch-size-1** event-source mapping processes them strictly in order, one at a time (FR-001) —
  no Step Function or external lock needed. (Document this ordering guarantee in the e2e doc.)

### FR-005: Actor binding (anti-spoofing) for user-originated actions

#### Description:

A user must not be able to mutate another user's notifications by putting a different `username` on the
wire.

#### Acceptance Criteria:

- [ ] For `markRead` / `markAllRead`, the writer **requires** an `idToken`,
  verifies it against the User Pool (issuer, signature via the pool JWKS, expiry, audience), and uses the
  verified `cognito:username` claim as the target — **any `username` field in the body is ignored** for
  these actions.
- [ ] A user-originated message with a missing/expired/invalid token is rejected (the invocation fails →
  retried → DLQ); no write occurs.
- [ ] `create` is a **trusted-producer** action: it uses the body `username` (only identities explicitly
  granted `sqs:SendMessage` can enqueue; the portal role is **not** granted `create` so the browser cannot
  forge a `create` for another user — see FR-006. The first trusted producer is the shared-workspace
  orchestrator role, granted in SPEC-061). The token-verification approach mirrors the existing
  "unspoofable, server-side username from the verified token claim" decision (CLAUDE.md Auth; pre-signup /
  post-confirmation Lambdas).

### FR-006: Producer access (portal role `sqs:SendMessage`)

#### Description:

The browser (portal role) must be able to enqueue user-action messages.

#### Acceptance Criteria:

- [ ] The portal role's IAM (a `.tftpl` statement, co-located with the analytics/data portal-role policies
  or a new notifications fragment) gains `sqs:SendMessage` on the notifications queue ARN **only**.
- [ ] The portal role gets **no** other notifications permissions (no Lambda invoke, no DLQ, no writer-role
  access). The queue ARN is wired to the app as a `VITE_*` var in SPEC-059 (this spec exports it). Because the
  queue is FIFO, the browser's send must include `MessageGroupId` (its own username) + dedup id (FR-003).
- [ ] The browser sends only the two user-action types (`markRead`/`markAllRead`); `create` comes
  **exclusively** from trusted system producers (the writer ignores a `create` whose enqueuer is the portal
  role is enforced by IAM scoping, not body inspection — the portal grant cannot carry the producer's
  identity). Resolved: the portal role may **not** enqueue `create`.

### FR-007: Deploy-role IAM expansion + standalone module

#### Acceptance Criteria:

- [ ] `infra/modules/base/policies/` is extended for every new resource type: FIFO SQS (queue + DLQ), the
  SQS **event-source mapping** (`lambda:CreateEventSourceMapping` etc.), the new Lambda + its writer role
  (incl. scoped `iam:PassRole`), the log group. (**No Pipes / Step Functions.**)
- [ ] Non-scopable actions isolated to `"*"` statements; document the expected first-apply
  self-grant-propagation failure → clean re-run for any first-use-gated resource (architecture.md
  `time_sleep` caveat).
- [ ] The module is **standalone-deployable** (`compact()`-safe constructed-string locals for any
  cross-module ARN — user-space bucket ARN, User Pool id/JWKS — so no unknown-ARN-in-list drop);
  `tofu -chdir=infra validate` + `plan` succeed.

### FR-008: Control-plane smoke test

#### Acceptance Criteria:

- [ ] `docs/testing/e2e.md` documents: placing a `create` message (with `MessageGroupId` =
  username) on the FIFO queue invokes the writer Lambda and produces `{username}/user_settings/notifications.json`
  with the expected `Notification` (CloudWatch shows the invocation + the write); a `markRead` then flips
  `read` on that id; a `markAllRead` flips all; two rapid messages for one user both land in order (no lost
  update); a malformed/forged user-action message lands in the DLQ with no write.

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
// Sent to the FIFO queue with MessageGroupId = target username + a MessageDeduplicationId (FR-003).
// create (trusted producer — e.g. a shared-workspace verb Lambda, SPEC-061): MessageGroupId = "alice"
{ "action": "create", "username": "alice", "message": "Your shared workspace \"salesdata\" is ready." }

// user-originated (browser); idToken REQUIRED, username DERIVED from the token; MessageGroupId = caller's username:
{ "action": "markRead",     "id": "b3f1…", "idToken": "<cognito id token>" }
{ "action": "markAllRead",                  "idToken": "<cognito id token>" }
// No delete / deleteAll — notifications are never removed (only marked read).
```

```hcl
# infra/modules/notifications/variables.tf
variable "notifications_max"        { default = 200 }   # writer-side cap (newest kept)
variable "user_space_bucket_arn"    {}                  # constructed-string local from root
variable "user_pool_id"             {}                  # for JWKS issuer/audience (FR-005)
variable "dlq_max_receive_count"    { default = 3 }
# FIFO queue (.fifo); content-based dedup on unless producers always supply MessageDeduplicationId.
```

## API / Interface Contract

The writer Lambda is internal; its only contract is the SQS envelope above. The exported Terraform outputs
are the integration surface for SPEC-059:

```hcl
# infra/modules/notifications/outputs.tf  (FIFO queue → .fifo URL/ARN)
output "notifications_queue_url"  { value = aws_sqs_queue.requests.url }   # → VITE_NOTIFICATIONS_QUEUE_URL (SPEC-059); ends in .fifo
output "notifications_queue_arn"  { value = aws_sqs_queue.requests.arn }   # → portal-role + producer SendMessage (FR-006)
output "notifications_writer_role_arn" { value = aws_iam_role.writer.arn }
# (no state-machine output — there is no Step Function)
```

## Environment Variables

No new `VITE_*` in this spec — the queue URL is **exported** here and **consumed** (as
`VITE_NOTIFICATIONS_QUEUE_URL`) in SPEC-059. Document the export in `infra` outputs so SPEC-059 wires it.

## File & Folder Structure

```
infra/modules/notifications/
├── sqs.tf                # FIFO request queue (.fifo) + FIFO DLQ (+ redrive)
├── lambda.tf             # writer function infra (placeholder + ignore_changes) + SQS event-source mapping (batch size 1) + log group
├── iam.tf                # writer role wiring
├── policies/             # .tftpl: writer role (S3 + SQS receive + logs); portal-role SendMessage fragment
├── variables.tf          # names + cross-module ARNs (constructed-string locals) + notifications_max
└── outputs.tf            # queue URL/ARN, writer role ARN

lambdas/notifications-writer/
└── notifications_writer.py          # action-switch read-modify-write + JWT verify (FR-004/005); follows lambdas/info/best-practices/lambdas/lambdas.md

infra/modules/base/policies/          # deploy-role expansion (FR-007)
infra/modules/<portal-role module>/   # portal-role sqs:SendMessage statement (FR-006)
.github/workflows/deploy-lambdas.yml  # + notifications-writer matrix row
docs/testing/e2e.md     # contract + control-plane smoke test (FR-003/FR-008)
```

## Implementation Phases

### Phase 1: Module scaffold + FIFO queue + Lambda trigger

- New `infra/modules/notifications/` module; **FIFO** SQS queue (`.fifo`) + FIFO DLQ; writer Lambda infra
  (placeholder zip + `ignore_changes`) + the **SQS event-source mapping** (batch size 1) + log group +
  `deploy-lambdas.yml` row; deploy-role IAM for these resource types (FR-001, FR-007 partial). Writer Lambda
  is a dispatch/echo stub at this point.

### Phase 2: Writer logic + actor binding + smoke test

- Implement the `action`-switch read-modify-write + cap (FR-004); JWT verification for user-originated
  actions (FR-005); writer-role S3 + SQS-receive policy scoped to `…/user_settings/notifications.json` + the
  queue, verified with `simulate-custom-policy` (FR-002); portal-role `sqs:SendMessage` (FR-006);
  message-contract (incl. `MessageGroupId`) + smoke-test doc (FR-003, FR-008); finish deploy-role IAM
  (FR-007).

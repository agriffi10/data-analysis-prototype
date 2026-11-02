---
type: Spec
id: SPEC-061
title: "Shared-Workspace Notification Producer"
description: "Makes each shared-space lifecycle Lambda (create, add members, remove members, leave, delete) send a notification to the affected users through the notifications queue, so people hear about space events."
spec_status: Completed
depends_on: [SPEC-058, SPEC-050, SPEC-051, SPEC-053, SPEC-054, SPEC-062]
arc: notifications
arc_order: 4
---

**Dependency notes:** SPEC-058 (notifications queue + `create` contract + writer), SPEC-050 (shared-space control plane: orchestrator role + Step Function), SPEC-051 (create path), SPEC-053 (add/remove members path), SPEC-054 (leave + delete-cascade path), SPEC-062 (control-plane decomposition: the single-task **verb Lambdas** + shared `notify` helper that host the emit calls)
> **Structure note (SPEC-062):** the control plane is **single-task verb Lambdas** orchestrated by the Step
> Function (`validate-authorize → Choice(action) → create-space | add-members | remove-members | leave |
> delete-space`). The emit happens **inline in each verb Lambda** via a shared `emit_notification` helper in
> the common module (user decision). If SPEC-062 has not yet landed when this is built, the same emit calls
> live at the corresponding terminal branches of the monolithic provisioner; either way the call sites and
> behavior are identical.

> **Fourth and final of the notifications arc (058 → 059 → 060 → 061).** SPEC-058 built the write pipeline
> but explicitly granted **no** trusted producer of `create` messages. This spec wires the **first**
> producer: the shared-workspace control plane. At the terminal outcome of its lifecycle actions, the
> **relevant verb Lambda** (SPEC-062) enqueues a `create` notification (SPEC-058 contract) addressed to the
> right user, so a person learns — in their notifications inbox (SPEC-060) — that their workspace was
> created, failed, that they were added, that an add they requested couldn't complete, that someone left, or
> that the space was deleted.
> It is **producer-side only**: no UI (SPEC-060) and no new notifications infra (SPEC-058) — it grants the
> emitting verb Lambdas' roles `sqs:SendMessage` on the notifications queue, passes the queue URL to those
> Lambdas, and adds the inline emit calls via a shared helper.

## Overview

Notifications are only useful once something produces them. The shared-workspace control plane is the
natural first source: it already runs trusted, server-side, under the orchestrator role (SPEC-050), and its
lifecycle actions are exactly the events a user wants to hear about. This spec makes each **verb Lambda**
(SPEC-062: create-space / add-members / remove-members / leave / delete-space) emit a `create` notification at
its terminal point by placing a message on the **SPEC-058 notifications queue**. Each emitting verb Lambda's
role gains `sqs:SendMessage` to that queue (it is a SPEC-058 "trusted producer"), and the notifications queue
URL is passed to the verb Lambdas as an environment variable. Because `create` is a trusted-producer action
(SPEC-058 FR-005), the emitting Lambda sets
the recipient via the message body `username` — letting it notify whichever user each event concerns (the
creator, an added member, the owner, or **every member** of a deleted space). No browser code, no UI, and no
change to the notifications storage or writer are involved.

## Scope

### In Scope

- **Seven notification events**, emitted by the action's verb Lambda at the **terminal** outcome of the
  corresponding control-plane action (one `create` message per event, per affected user):

  1. **Shared workspace created** → notify the **creator/owner**: e.g. `Your shared workspace "salesdata" is ready.`
  2. **Shared workspace creation failed** → notify the **creator**: e.g. `We couldn't create shared workspace "salesdata": name already taken.`
  3. **A user was added to a workspace** → notify the **added user**: e.g. `You've been added to the shared workspace "salesdata".` (see Open Questions on the "invitation/accept" model + optionally notifying the owner)
  4. **A user couldn't be added — membership limit** → notify the **owner who requested the add**: e.g. `Couldn't add "bob" to "salesdata": they've reached their workspace limit.`
  5. **A user couldn't be added — user doesn't exist** → notify the **owner who requested the add**: e.g. `Couldn't add "typo_user" to "salesdata": no such user.`
  6. **A user left a workspace** → notify the **owner**: e.g. `"bob" left the shared workspace "salesdata".`
  7. **A workspace was deleted** → notify the **deleter/owner** *and* **every member** of that workspace (fan-out): the deleter gets e.g. `You deleted the shared workspace "salesdata".`; every other member gets e.g. `The shared workspace "salesdata" was deleted.`

- **Verb-role grant** — each emitting verb Lambda's `.tftpl` role policy (SPEC-062; pre-062, the single
  orchestrator role) gains `sqs:SendMessage` on the **notifications queue ARN only** (a SPEC-058 trusted
  producer).
- **Cross-module wiring** — the notifications queue URL/ARN (SPEC-058 outputs) is passed into the
  shared-space module: the orchestrator policy (ARN) and the verb Lambdas' environment
  (`NOTIFICATIONS_QUEUE_URL`). Constructed-string/`compact()`-safe locals so the module still validates
  standalone (architecture.md "unknown ARN in list" trap).
- **Shared emit helper** — a small, **best-effort** `emit_notification(username, message)` in the
  shared-space **common module** (`notify.py`, SPEC-062) that builds the SPEC-058 `create` envelope and
  `SendMessage`s it; each verb Lambda calls it inline. A failure to emit is **logged but does not fail the
  action** (the workspace operation already succeeded/failed on its own terms — a missed notification must
  not roll back a real provisioning result).
- **Message templating** — short, human-readable messages per event (above), with the space name and (for
  the add-failure/left events) the subject username interpolated; failure messages carry the recorded
  reason.
- **Tests** — verb-Lambda unit tests asserting each terminal path emits the **correct recipient + message**
  (and emits **nothing** on non-terminal/retryable steps); an emit failure does not change the action's
  result. The e2e docs (the notifications and shared-space acceptance scripts, both folded into
  `docs/testing/e2e.md` §4.8 and §4.12 on 2026-08-18) gain the producer flow.

### Out of Scope

- **The notifications infra** (queue, pipe, state machine, writer Lambda, writer role, cap) — **SPEC-058**.
- **The browser read/UI** (`useNotifications`, bell, page) — **SPEC-059/060**.
- **Member fan-out on events other than delete** — only event 7 (delete) fans out to every member; events 1–6
  each notify the single recipient named above (e.g. "bob left" goes to the owner only, not to all members).
  Broader fan-out is a future enhancement.
- **An invitation/accept workflow** — the current model adds members directly (SPEC-053, owner-driven, no
  acceptance step). Event 3 fires on a **successful add**, not on an acceptance action (see Open Questions).
- **Producers other than shared spaces** (file ops, query results, etc.) — future specs reuse this same
  trusted-producer grant pattern.

---

## Functional Requirements

### FR-001: Emitting Lambdas' role may send to the notifications queue

#### Description:

The Lambdas that emit notifications must be allowed to enqueue `create` messages.

#### Acceptance Criteria:

- [ ] The `.tftpl` permission policy of every **verb-Lambda role that emits** (SPEC-062: create-space /
  add-members / remove-members / leave / delete-space — i.e. all verbs; pre-062, the single orchestrator
  role) gains a statement allowing `sqs:SendMessage` on the **notifications queue ARN only** (no other
  notifications-pipeline action: no Lambda invoke, no Step Function, no DLQ, no writer-role access).
- [ ] The notifications queue ARN reaches the shared-space module as a constructed-string/`compact()`-safe
  local (or explicit variable) so the module still `validate`s/`plan`s standalone (no unknown-ARN-in-list
  drop).
- [ ] `aws iam simulate-custom-policy` (or an equivalent assertion) confirms an emitting role can
  `SendMessage` to the notifications queue and **cannot** to any unrelated queue.

### FR-002: Verb Lambdas receive the queue URL + share an emit helper

#### Acceptance Criteria:

- [ ] Each emitting verb Lambda's environment gains `NOTIFICATIONS_QUEUE_URL` (the SPEC-058 queue URL
  output), documented alongside the shared-space Lambda config.
- [ ] The shared-space **common module** (`notify.py`, SPEC-062) provides `emit_notification(username,
  message)` that builds the SPEC-058 `create` envelope `{ "action": "create", "username": <recipient>,
  "message": <text> }` and `SendMessage`s it to `NOTIFICATIONS_QUEUE_URL`; each verb Lambda imports and calls
  it inline.
- [ ] Because the notifications queue is **FIFO** (SPEC-058 FR-001), the send sets **`MessageGroupId` = the
  recipient's username** (so each user's create's serialize with their own actions) and a
  `MessageDeduplicationId` derived from the source request (e.g. `requestId` + event + recipient) so a
  pipeline replay doesn't duplicate the row.
- [ ] `emit_notification` is **best-effort**: an exception/error is **caught + logged** and never propagates
  — emitting a notification must not change or fail the surrounding control-plane action's outcome.
- [ ] If `NOTIFICATIONS_QUEUE_URL` is unset (e.g. notifications not yet deployed), emit is a no-op + a single
  log line (the shared-space action still completes) — keeps the modules independently deployable.

### FR-003: Create success / failure events (1, 2)

#### Acceptance Criteria:

- [ ] On a **terminal `active`** outcome of a `create` action (SPEC-051 FR-005), the verb Lambda emits one
  notification to the **creator** (`actor`): `Your shared workspace "{name}" is ready.`
- [ ] On a **terminal `failed`** outcome of a `create` action (collision, slot-full, or any provisioning
  failure — SPEC-051), the verb Lambda emits one notification to the **creator**: `We couldn't create shared
  workspace "{name}": {reason}.` (reason = the recorded failure reason).
- [ ] Exactly **one** notification per terminal create outcome; no notification is emitted for intermediate
  retries or non-terminal steps.

### FR-004: Member-add events (3, 4, 5)

#### Acceptance Criteria:

- [ ] When an `add_members` request **successfully adds** a user (SPEC-053 FR-004 — registry/slot/cache
  updated), the verb Lambda emits one notification to the **added user**: `You've been added to the shared
  workspace "{name}".`
- [ ] When an add is **skipped because the target is at the membership limit** (SPEC-053 "skippedAtLimit"),
  the verb Lambda emits one notification to the **owner/actor who requested the add**: `Couldn't add "{user}"
  to "{name}": they've reached their workspace limit.`
- [ ] When an add names a **user who doesn't exist** (SPEC-053 "ignoredUnknown" — validated against the User
  Pool), the verb Lambda emits one notification to the **owner/actor**: `Couldn't add "{user}" to "{name}":
  no such user.`
- [ ] A **bulk** add emits per affected user: one "added" to each newly-added member, and one failure
  notification to the owner per at-limit/unknown entry (i.e. the owner may receive several from one bulk
  request); already-members (idempotent no-ops) emit **nothing**.

### FR-005: Leave event (6)

#### Acceptance Criteria:

- [ ] When a `leave` request **successfully** removes a member (SPEC-054 FR-003), the verb Lambda emits one
  notification to the **owner** (registry `owner`): `"{user}" left the shared workspace "{name}".`
- [ ] No notification is emitted for an idempotent no-op leave (a non-member leaving), and **none** is sent
  to the leaving user themselves.
- [ ] The owner is resolved from the registry at the time of the leave (the leaving user is never the owner —
  SPEC-054).

### FR-006: Delete event — fan-out to deleter + all members (7)

#### Description:

On a successful workspace deletion, notify the person who deleted it and everyone who belonged to it.

#### Acceptance Criteria:

- [ ] On a **terminal successful `delete`** (SPEC-054 FR-004 cascade complete), the verb Lambda emits one
  notification **per member** of the space — the recipient set is the registry `members` **including the
  owner/deleter** (owner ∈ members), deduplicated so each user gets exactly one.
- [ ] The **deleter/owner** (`actor`) receives `You deleted the shared workspace "{name}".`; **every other
  member** receives `The shared workspace "{name}" was deleted.`
- [ ] The member list is **captured before** the cascade clears the registry/slots (SPEC-054 removes
  `members` + the registry object), and notifications are emitted **after** the delete reaches its terminal
  success state — so a partial/failed delete (status `failed`/`deleting`) emits **nothing**.
- [ ] A per-recipient emit failure is swallowed (FR-002) and does not abort the fan-out to the remaining
  members.

### FR-007: Idempotency / at-least-once tolerance

#### Description:

The control plane is replay-safe; notification emission is at-least-once and may rarely duplicate.

#### Acceptance Criteria:

- [ ] Emission happens **after** the action's terminal state is recorded, so a notification is only sent for
  a real outcome (never for a step that later rolls back / re-runs to a different terminal state).
- [ ] A pipeline **replay** of an already-terminal request may re-emit (at-least-once); this is acceptable —
  a duplicate is a duplicate inbox row, not a correctness problem. (If de-duplication is later wanted, it is
  a follow-up; document the decision.)
- [ ] No event emits more than once **per terminal outcome per recipient** within a single (non-replayed)
  execution.

### FR-008: Tests + lint

#### Acceptance Criteria:

- [ ] Pipeline (Python) unit tests: each of the seven events emits the **correct recipient(s) + message**
  with the right interpolation; bulk add emits per-user; **delete fans out to every member (incl. the
  deleter) deduplicated, with the deleter's distinct message**; idempotent no-ops emit nothing; an
  `emit_notification` failure is swallowed and does **not** change the action result (the workspace op still
  succeeds/fails as before).
- [ ] IaC: `tofu -chdir=infra validate` + `plan` clean; the emitting roles' SendMessage statement is
  present and scoped to the notifications queue ARN; the verb Lambdas' env has `NOTIFICATIONS_QUEUE_URL`.
- [ ] The acceptance scripts document the end-to-end producer
  flow: a real create/add/leave/delete drives the control plane and a `create` lands on the notifications
  queue → the writer appends the row → the recipient(s) see it in their notifications page (SPEC-060).

---

## Data Model

No new persisted types. The emitted message is the SPEC-058 `create` envelope:

```jsonc
// SendMessage body — SPEC-058 create contract (trusted producer = the emitting verb Lambda)
// Sent to the FIFO queue with MessageGroupId = <recipient> and a MessageDeduplicationId from the source request.
{ "action": "create", "username": "<recipient>", "message": "<event text>" }
```

Recipient + message per event:

| # | Control-plane action / outcome | Recipient (`username`) | Message |
|---|---|---|---|
| 1 | `create` → active | creator (`actor`) | `Your shared workspace "{name}" is ready.` |
| 2 | `create` → failed | creator (`actor`) | `We couldn't create shared workspace "{name}": {reason}.` |
| 3 | `add_members` → user added | the added user | `You've been added to the shared workspace "{name}".` |
| 4 | `add_members` → at-limit skip | owner (`actor`) | `Couldn't add "{user}" to "{name}": they've reached their workspace limit.` |
| 5 | `add_members` → unknown user | owner (`actor`) | `Couldn't add "{user}" to "{name}": no such user.` |
| 6 | `leave` → member removed | owner (registry `owner`) | `"{user}" left the shared workspace "{name}".` |
| 7 | `delete` → cascade success | **every member** (incl. owner), deduped | deleter (`actor`): `You deleted the shared workspace "{name}".`; others: `The shared workspace "{name}" was deleted.` |

## API / Interface Contract

```python
# lambdas/shared-space-common/notify.py  (shared module/layer — SPEC-062)

def emit_notification(username: str, message: str, dedup_id: str | None = None) -> None:
    """Best-effort: SendMessage a SPEC-058 `create` envelope to the FIFO NOTIFICATIONS_QUEUE_URL
    with MessageGroupId=username and MessageDeduplicationId=dedup_id (derived from the source
    request when given). Catches and logs all errors; never raises (a missed notification must
    not fail the action). Imported and called inline by each verb Lambda."""
```

## Environment Variables

Each emitting verb Lambda (server-side, **not** a `VITE_` var):

```
NOTIFICATIONS_QUEUE_URL=<SPEC-058 notifications queue URL>   # target for create notifications
```

## File & Folder Structure

```
infra/modules/shared-spaces/ (orchestrator role + verb Lambdas live here, SPEC-050/062)
├── policies/<verb-role>.tftpl             ← + sqs:SendMessage on the notifications queue ARN, per emitting verb role (FR-001)
├── lambda.tf                              ← + NOTIFICATIONS_QUEUE_URL env on each verb Lambda (FR-002)
└── variables.tf                           ← + notifications_queue_arn / _url (constructed-string locals) (FR-001/002)

lambdas/shared-space-common/
└── notify.py                              ← emit_notification (shared helper — SPEC-062) + tests

lambdas/shared-space-<verb>/               ← create / add-members / remove-members / leave / delete (SPEC-062)
├── <verb>.py                              ← + inline emit_notification call(s) at the terminal outcome (FR-002–007)
└── test_<verb>.py                         ← + emit assertions per event incl. delete fan-out (FR-008)

docs/testing/e2e.md          ← + producer flow (FR-008)
```

## Implementation Phases

### Phase 1: Wiring (grant + env + helper)

- Pass the notifications queue ARN/URL into the shared-space module (constructed-string locals); add
  `sqs:SendMessage` to each emitting verb role scoped to the notifications queue ARN; set
  `NOTIFICATIONS_QUEUE_URL` on each verb Lambda; add `emit_notification` to the common module (best-effort,
  no-op if unset) (FR-001, FR-002, FR-008 IaC).

### Phase 2: Emit at each terminal outcome

- Add the emit calls to the `create`, `add_members`, `leave`, and `delete` terminal paths with the
  recipient(s) + message per the table — for `delete`, capture the member list before the cascade clears it
  and fan out (deduped, distinct deleter message); unit-test each event (recipient, message, bulk fan-out,
  delete fan-out, no-op silence, swallowed emit failure) (FR-003–FR-008 pipeline). Update the e2e doc.

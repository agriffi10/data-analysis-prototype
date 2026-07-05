# Spec: Table Share — Notification Producer (sender + recipients)

**ID:** SPEC-094
**Status:** Draft
**Last Updated:** 2026-07-04
**Depends On:** SPEC-058 (notifications write pipeline + `create` contract), SPEC-092 (per-recipient outcomes + shared role), SPEC-061/072 (emit-pattern precedents)

> **Read `docs/table-share-architecture.md` §8 first.**

## Overview

Wire table-share outcomes into the notifications inbox (SPEC-058→060). The **sender (actor)** is told how each recipient fared (success or the specific failure reason). On **success**, the recipient party is also told: a **user** recipient in their own inbox; a **shared-space** recipient via the space's **owner** (resolved from the registry) — never the space broadly and never its non-owner members. **Failures notify the sender only.** This mirrors the SPEC-061/072 emit pattern (trusted-producer `create` messages on the notifications FIFO queue via a best-effort shared helper), extended to a **multi-recipient fan-out** (actor + the per-recipient success target).

## Scope

### In Scope

- On each recipient's terminal outcome, emit a **`create` notification to the actor**:
  - success — *"Shared '{source.table}' to {kind} {name} as '{tableName}'."*
  - failure — *"Couldn't share '{source.table}' to {kind} {name}: {reason}."* (reasons: unknown user/space, name conflict, copy failed, create failed).
- On a recipient **success**, emit a **`create` notification to the success target**:
  - **user** recipient → **that user**: *"{actor} shared table '{tableName}' with you in '{recipientDatabase}'."*
  - **shared-space** recipient → **the space's owner** (from the registry `owner`): *"{actor} shared table '{tableName}' into your space '{spaceName}'."* — the owner only; non-owner members are **not** notified.
- On any recipient **failure**, emit a notification to the **actor only** — no recipient/owner notification.
- On a **whole-request** failure (auth/inspect — before any recipient), emit a single failure notification to the actor with the reason.
- Grant the **shared execution role** `sqs:SendMessage` on the **notifications** queue only + `NOTIFICATIONS_QUEUE_URL` env; use the shared best-effort `emit_notification` helper (a notification failure never fails the share).
- Emits happen from the verb Lambda that owns each terminal branch (validate-authorize for whole-request; create-table/copy/check for per-recipient), consistent with SPEC-072.

### Out of Scope

- Any new notifications infrastructure — SPEC-058 owns the queue/writer/inbox; this is a **producer** only.
- Batching multiple recipient outcomes into one digest notification (one per recipient outcome is the v1 shape; a summary digest is a future enhancement).
- Notifying **non-owner members** of a recipient shared space — a space-share success notifies **only the space owner** (resolved from the registry); members simply see the new table in the shared DB.
- UI changes — the inbox/bell already render `create` notifications (SPEC-060).

---

## Functional Requirements

### FR-001: Actor per-recipient notifications

#### Acceptance Criteria:

- [ ] A successful recipient produces one actor notification naming the recipient + result name.
- [ ] A failed recipient produces one actor notification naming the recipient + the specific reason.
- [ ] A request with N recipients produces N actor notifications (one per outcome), regardless of mixed success/failure.

### FR-002: Recipient-side success notifications

#### Acceptance Criteria:

- [ ] A **user** recipient whose table was created gets one notification in their own inbox identifying the actor, the table name, and the recipient database.
- [ ] A **shared-space** recipient success notifies **the space's owner** (resolved from the registry `owner`) — exactly one notification, to the owner only; non-owner members are not notified.
- [ ] A failed recipient produces **no** recipient/owner notification — only the actor is told of failures (FR-001).
- [ ] The owner lookup degrades safely: if the space record or its `owner` can't be read, the owner notification is skipped (best-effort) without failing the share or the actor's own notification.

### FR-003: Whole-request failure + delivery guarantees

#### Acceptance Criteria:

- [ ] An auth/inspect (pre-fan-out) failure emits exactly one actor notification with the reason and no recipient notifications.
- [ ] Emission is best-effort via the shared helper — a notifications-queue error is logged and never fails the share or the Step Function.
- [ ] The execution role can `sqs:SendMessage` to **only** the notifications queue; `NOTIFICATIONS_QUEUE_URL` is wired as env.

---

## Data Model

```python
# tscommon.notify (reuses the SPEC-058 create contract; trusted-producer)
#   notify_actor(actor, message)                 -> best-effort SendMessage (MessageGroupId=actor)
#   notify_success_target(recipient, message)    -> resolves the target inbox:
#                                                     user  -> recipient.name
#                                                     space -> registry.load_space(name).owner  (best-effort; skip if unresolved)
# Message: { type:'create', username:<targetUser>, message:<text> }   # writer trusts 'create' producers
# Failures never call notify_success_target (actor-only, per FR-001).
```

## Implementation Phases

### Phase 1: Emit helper + role grant

- `tscommon.notify` (best-effort SendMessage); execution-role `sqs:SendMessage` on the notifications queue + `NOTIFICATIONS_QUEUE_URL` env.

### Phase 2: Wire emits at terminal branches

- Actor per-recipient (success/failure) + success-target emit (user → the user; space → the owner via `registry.load_space().owner`) + whole-request failure emit, at the owning verb Lambdas. Failures never emit to the recipient/owner.

### Phase 3: Completion ritual

- Delivery doc, INDEX status, component-inventory row (`tscommon.notify`), SPEC-074 Help sweep (note that share outcomes arrive as notifications).

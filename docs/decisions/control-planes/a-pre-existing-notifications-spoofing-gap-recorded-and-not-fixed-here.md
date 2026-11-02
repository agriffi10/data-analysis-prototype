---
type: Decision
title: "A pre-existing notifications spoofing gap, recorded and not fixed here (SPEC-191)"
description: "Closed: the portal role holds no grant on the notifications queue and the writer refuses a `create` naming it as sender, so a signed-in browser can no longer plant a notification; this entry keeps the gap's record."
---

> **Superseded by SPEC-206 (2026-08-24).** The gap below is closed: the writer refuses a `create`
> whose SQS-stamped `SenderId` names the portal role. ~~The grant is still unconditioned — that part
> stays true, and is why the control is a runtime one.~~ **— superseded by SPEC-200:** the grant is
> gone, so the portal role cannot send to this queue at all, and the runtime check stays behind that.
> See [the SPEC-206 entry](the-notifications-create-boundary-is-a-runtime-check-because-iam-cannot.md).

The portal role holds an **unconditioned** `sqs:SendMessage` on the notifications request queue, and
the writer takes the body's `username` verbatim for a `create`. A signed-in browser can therefore
already plant a notification — message and clickable in-app link — in another user's inbox. The
comment directly above that IAM grant asserts the opposite, which is the dangerous combination: a
reader checking the IaC is told the hole is closed. IAM cannot condition on a message body, so the
fix is a second queue or a token on `create`, and it changes a plane seven features share. Recorded
rather than absorbed into this spec; the [payload ceiling](a-notification-payload-is-bounded-by-bytes-and-the-binding-case-is-the.md) is the only part of it this spec owes.

## History

### 2026-08-24

- **Changed:** SPEC-206 closed the gap with the writer's `SenderId` refusal of a `create` from the portal role.

### 2026-08-17

- **Settled:** SPEC-191.

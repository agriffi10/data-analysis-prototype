---
type: Decision
title: "The notifications `create` boundary is a runtime check, because IAM cannot express it (SPEC-206)"
description: "**The notifications `create` boundary is IAM and the API first, a RUNTIME check behind the grant.** The portal role holds no grant on the queue, and the API's route accepts only `markRead` and `markAllRead`. The writer's check names only the portal role, so against the API's own role the route is the only fence; the check is runtime because no SQS condition key reaches a message body. It compares the **role-id half** of the `SenderId`, and a refusal **logs and drops, never raises** — dead-lettering per forged request would drown its undrained DLQ. The actor reader replaces the `USER_ACTIONS` arm **only**: `create` is the trusted producer (body username, no actor, no token), and hoisting the reader above that branch refuses **every notification the fleet produces**, silently."
---

The plane has said since SPEC-058 that `create` is trusted-producer-only, and the writer takes the
body's `username` on that action — correctly, because a plane notifying a *recipient* holds no token
for the person it is telling **— and since SPEC-201,** because a plane writes a `create` itself, not
through the API, so it carries no `identity` block, and the person it tells need not be the caller
it acted for. **The IAM policy never implemented it.** The portal role's
`sqs:SendMessage` on the notifications queue was unconditioned, so any signed-in user could enqueue a
`create` naming anybody and saying anything, including a clickable in-app link. The comment above that
grant asserted the opposite, which is the dangerous combination: a reader checking the IaC was told the
question had been answered.

**IAM cannot express this rule at all, and that is the argument — not a preference for runtime checks.**
No SQS condition key reaches a field inside a message body, so a queue or identity policy could only
deny the portal role `sqs:SendMessage` outright: the same principal on the same action that `markRead`
and `markAllRead` ~~need~~ **— superseded by SPEC-200:** needed then; they reach the queue through the
API now. There is no policy that permits two of the three actions. So the boundary is the
`SenderId` SQS stamps on every message — a message *system* attribute the service sets and a
`SendMessage` cannot — compared on the **role-id half**, the substring before the first `:`. Not
equality against the whole value (which never matches, and a control that never matches reads exactly
like one that works) and not `startswith` (which would refuse an unrelated role whose unique ID merely
shares an opening). The session-name half is never examined: ~~Cognito's enhanced flow does not document
what it puts there~~ **— superseded by SPEC-202:** the Identity Pool is gone, and the API assumes the
portal role with the username verbatim as its session name, which says which user it is and nothing
about whether the role may send.

**The rule is a DENY of one principal, not an ALLOW of the rest.** ~~The grant is held by every
control-plane execution role, the DLQ drain and the portal role — and exactly one of them is
user-reachable, which is what makes a single-principal refusal complete rather than partial.~~
**— superseded by SPEC-200:** the portal role no longer holds the grant. The user-reachable sender
is now the API's execution role, and its `notifications.enqueue` request model accepts only
`markRead` and `markAllRead`, so a user's `create` is refused at the API (400) before the queue. The
count of the grant's holders is deliberately not written here: it moved with the eighth plane, and it will move again. An allow-list would be a
hand-maintained list of role IDs that fails closed on the day a plane is added: that plane's
notifications would stop, drop or dead-letter unnoticed and nobody would connect the two. One
environment variable beats eight, and the deny direction fails open only toward principals that require
an explicit IAM change to exist.

**A refusal LOGS AND DROPS; it does not raise.** Raising would cost three invocations and one permanent
dead-letter message per forged request, on the queue whose DLQ SPEC-126 deliberately leaves undrained
and which is this plane's only operator-facing signal — handing ~~every signed-in user~~ **— superseded
by SPEC-200:** whoever could send as the portal role, which no signed-in user now can, a way to drown it.
The structured `observability.error` therefore *is* the signal, and has to be, precisely because nothing
accumulates to notice. It carries the reason code and the SQS `messageId` (both service-stamped) and
**nothing from the body**: echoing it would move the injection from the victim's inbox to the operator's
log rather than remove it. The guard sits **above** `_resolve_username` rather than inside the `create`
branch, because that call runs before any branch — lower, a forged create that simply omits `username`
would reach `create requires a username` and raise, which is the vector the drop exists to close.

**Three reason codes, not two.** `untrusted-sender`, `sender-id-absent` and
`sender-check-unconfigured`. A check that cannot run must not report a pass, and the cases are
operationally opposite: one is somebody trying it on, one is the control having broken, one is the
deploy being wrong. Splitting the third out is also load-bearing, and two guards carry it: the
empty role-id half is refused **before** the comparison, so an absent sender never compares equal to an
unset variable and gets logged as a forgery; and the configuration is tested **first**, so an unset
variable reports itself even when the sender is absent, rather than returning `sender-id-absent` and
blaming the message for a broken deploy.

**Do NOT split `create` onto a second queue.** It is the obvious fix — IAM could then enforce this with
no runtime check — and it is rejected. The single-writer guarantee is *one FIFO queue, one message group
per user, batch size 1*, and FIFO ordering is per `(queue, group)`. Two queues means two event-source
mappings and two concurrent invocations read-modify-writing one user's `notifications.json`: a mark-read
and an arriving notification can lose each other. It trades a spoofing bug for a data-loss bug, and
closing that would mean putting the inbox write under ETag CAS first.

**Two limits, stated rather than implied.** This decides who may send a `create`, not who may reach the
queue — a non-JSON body or an unknown action still raises from `_parse_record` and dead-letters. And it
is the **interim** fix: ~~Arc B removes the browser's grant (SPEC-200) and after SPEC-196 the denied
principal becomes a *service* principal, harmless because every `create` is emitted by execution roles.
The check stays regardless; that removal is eleven specs out and reversible.~~ **— superseded by
SPEC-200:** the browser's grant is gone, and the check stays behind that. It still names only the
portal role, so a `create` from the API's execution role would pass it — the API's route refusing
the action is the fence against that sender. Detail:
`spec-delivery/SPEC-206`.

The actor reader replaces the `USER_ACTIONS` arm only: `create` is the trusted producer (body username, no actor, no token), and hoisting the reader above that branch refuses every notification the fleet produces, silently.

## History

### 2026-08-24

- **Settled:** SPEC-206.

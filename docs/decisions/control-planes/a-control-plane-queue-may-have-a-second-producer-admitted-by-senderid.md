---
type: Decision
title: "A control-plane queue may have a second producer, admitted by SenderId (SPEC-208)"
description: "**The planes do not verify — they read the API's `identity` block**, whose writers are enumerated: the API, and one reader by `SenderId`. Dropping a verification is NOT dropping an authorization: `authorize`/`authorize_source` have **zero diff**. `cpcommon.actor` **cannot verify** (no `jwt`, `auth`, network or env — import sweep), and the flat `actor` is **never** read: it carried a raw JWT, and a JWT and a username are both non-empty, so the guard is the **shape rule**. `assurance` fails closed on an unknown value **including an absent one**. Do **NOT** add a queue resource policy — a blanket `Deny` there silences EVERY notifying role in the fleet, invisibly, and the fleet grows. A pre-cutover message is `unauthorized` and does **not** dead-letter (`FIRE_AND_FORGET`), so plane allowed-field sets stay untightened."
---

Until now one sentence covered the whole fleet: only the API writes a request queue, and every
plane's trust in the `identity` block rests on that. The shared-space queue now has two writers.
The second is `shared-space-transfer-reader`, a scheduled Lambda that turns an operator's CSV into
ordinary requests — the path for the case the UI cannot serve, an owner who has already left.
(SPEC-217 widened that CSV from ownership transfers alone to adds and removals as well; the fence
described here is unchanged, and the threat model it now stands in front of is not — see *The
operator door widens to member management*.)

**The reuse is the point, and it is what forces the fence.** An operator-driven transfer and a
user-driven one are the same verb, the same authorization and the same notifications; only the
door differs. But an operator has no bearer to present, so their message carries **no identity
block** and declares `origin: 'operator'` instead — and the only attributable fact left is the
`SenderId` SQS stamps on the record, a message SYSTEM attribute a `SendMessage` cannot set. That
comparison is the boundary. It is the mechanism SPEC-206 established, inverted: that one refuses a
sender it recognises, this one accepts *only* a sender it recognises.

**What makes the comparison mean anything is that the reader has its OWN execution role.** The
plane's verb Lambdas are a Terraform `for_each` whose `role` is hard-coded to the orchestrator, and
a reader riding that map would make the boundary read "any verb on this plane may forge an operator
request" — true of the running system, and invisible to every test, because a test supplies the
`SenderId` itself. So the reader is a separate resource with its own role, its own environment and
its own log group, and a test asserts it is not in that map.

**`origin` is undeclarable through the API, and that is the first fence rather than a detail.** The
contract refuses a body key it does not declare, so a signed-in caller cannot put `origin` on the
wire at all. Adding it to `SharedSpaceEnqueueRequest` — the obvious way to satisfy the envelope
sweep, which asserts a plane reads nothing the API refuses — would delete that property to make a
test pass, leaving the runtime comparison as the sole fence. The sweep is answered instead by a
named exemption asserting the shape that makes it safe: the plane reads **exactly one** field the
API cannot send, that field is undeclarable, and everything else is still a subset. Same repair the
notifications writer already carries, for the same reason.

**Rejected: a queue resource policy.** It is the obvious way to say "these two principals and no
others" and it is the trap the notifications queue already documents — a blanket `Deny` there
silences every notifying role, invisibly. The access model here stays identity-based.

**Rejected: an in-app admin surface.** The operator path is a file in a bucket and a scheduled
reader precisely so that *no admin group, admin role or admin route* is created. `CLAUDE.md`'s
*no admin UI* fence is unmoved.

**One residual, named rather than left to be found:** an operator gets no notification. Both parties
to the transfer do, and neither names the operator — but the operator themselves has no inbox in
this product, so their only feedback channel is the reader's structured log, one line per enqueued
row. That is recorded in `docs/testing/owed.md` rather than solved.

**The planes do not verify; they read the API's `identity` block.** Dropping a verification is not dropping an authorization: `authorize` and `authorize_source` have zero diff. `cpcommon.actor` cannot verify (no `jwt`, `auth`, network or env, held by an import sweep), and the flat `actor` is never read: it carried a raw JWT, and a JWT and a username are both non-empty, so the guard is the shape rule. `assurance` fails closed on an unknown value, including an absent one. A pre-cutover message is `unauthorized` and does not dead-letter (`FIRE_AND_FORGET`), so plane allowed-field sets stay untightened.

## History

### 2026-09-01

- **Settled:** SPEC-208.

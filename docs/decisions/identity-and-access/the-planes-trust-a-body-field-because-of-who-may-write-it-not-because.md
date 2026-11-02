---
type: Decision
title: "The planes trust a body field because of who may WRITE it, not because of cryptography (SPEC-201)"
description: "Planes trust the `identity` block because only the API may write their queues, so they verify no token and still authorize membership and ownership themselves; `cpcommon.actor` may not verify, and the flat top-level `actor` is never consulted."
---

Eight control planes each verified a Cognito ID token out of the queue message. That was correct
while the browser was the sender: the queue was writable by every signed-in user's credentials, so
the body proved nothing and only a signature could say who was asking.

SPEC-200 changed the sender. The API verifies the bearer at the edge, writes a nested `identity`
block carrying the verified actor, and — because SPEC-200 FR-008 also removed the browser's
`sqs:SendMessage` grants — is the only principal that may write those queues. From that point the
per-plane verification is a second answer to a question already answered, and it is the last reason
a raw JWT travels through eight queues, sits in eight state-machine execution inputs, and lands in
CloudWatch whenever a message dead-letters.

**The provenance is a grant, and it is enumerated rather than asserted:** the API's execution role
holds `sqs:SendMessage` on ~~exactly the eight request-queue ARNs~~ **— superseded by SPEC-211 and
SPEC-221:** every request-queue ARN, feedback's (SPEC-211) and results-conversion's (SPEC-221)
having joined the eight, from a list whose length the module pins, and a `.tftpl` sweep derived
from the modules on the filesystem fails if any policy attached to the ~~browser's role~~ **—
superseded by SPEC-202:** portal role, which the browser no longer holds, grants it again.
If that grant is ever widened, no amount of verification in the plane would help — a principal that
can write the queue can write the block.

**Dropping a VERIFICATION is not dropping an AUTHORIZATION, and the distinction is the whole
spec.** The token answered "is this really alice?"; membership, ownership, containment, a space's
active status and the recipient checks answer "may alice do this?". The API answers the first.
Nothing but the plane answers the second, and `authorize` / `authorize_source` have **zero diff** —
their inputs always took a plain username, and only where that string comes from changed.

**Do NOT add a queue resource policy** to "make it structural". On the notifications queue it is
destructive: that queue has eight writers, of which SPEC-200 removes one; the other seven are
execution roles that notify. A blanket `Deny` denies all of them and presents as nothing at all —
every plane notifies best-effort, so archives, shares and sends would complete and users would
simply never be told. Enumerating the seven exceptions is the hand-maintained allowlist whose
failure mode SPEC-164 FR-006 already records, arriving before the policy shipped. SPEC-200 FR-008
AC5 settled this for the arc.

**The reader may not verify, and that prohibition is the interesting half.** `cpcommon.actor`
imports neither `jwt` nor `cpcommon.auth`, makes no network call and reads no environment variable,
asserted by an import sweep. A reader that could fall back to verifying looks like defence in depth
and is the opposite: a second answer to a settled question, in a module whose premise is that it was
settled elsewhere. The fleet had five such readers and they had drifted; the cost was never that any
one was wrong, it was that nobody could say which one a request had used.

**The flat top-level `actor` is never consulted.** On four planes that field holds the raw token in
any message enqueued before the API stopped sending one, and a raw JWT and a username are both
non-empty strings — so a reader shaped "take the block, fall back to the field" passes every
well-formed fixture ever written and builds an S3 prefix, a Glue database name and a notification
recipient out of a 900-character token on the first message carrying the token and no block. The
actor is checked against `config.CATALOG_IDENTIFIER_RE` (with `fullmatch`, since `$` also matches
before a trailing newline), which is what makes the JWT case *fail* rather than merely look odd.
Measured: mutating that check to a truthiness test reddens seven cases in the reader's own suite and
leaves **every plane's suite green**.

## History

### 2026-08-18

- **Settled:** SPEC-201.

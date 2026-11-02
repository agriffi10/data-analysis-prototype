---
type: Decision
title: "One producer says every per-recipient outcome, and the link carries the recipient's own root (SPEC-167)"
description: "One verb at the end of the machine sends every per-recipient message, never a guard or a collector, and a failed recipient is told nothing; the recipient's link must carry their own root in `?prefix=`, or `FilesPage` silently discards it."
---

**Decision.** A single verb at the end of the machine turns SPEC-166's terminal summary into
messages: one to the sender per recipient outcome, one to each recipient who actually received
something — a ``user`` directly, a ``space`` through its registered OWNER, never its membership.
Its link is `/files?prefix={recipientRoot}shared_files/{sender}/`, with `?space=` as well for a
space.

**Why one producer rather than a decorator per verb.** Table share notifies from its guard, its
collector and its create verb because each is the only place its own outcome is known. Here every
per-recipient outcome reaches one flat list before anything is said, so one place can say each
thing once — and a decorator on the guard would make a conflict two messages. It is also what
lets the guard return its expected refusals as records: the colliding item name has to reach the
producer, and a `TerminalError` cannot carry one there. The whole-REQUEST verbs still notify
from their decorators, and must: a request that dies before this state never reaches it.

**A failed recipient is told nothing.** They have no part in the send, nothing to do about it, and
being told would leak that the sender tried.

**Why the link carries the recipient's root.** `FilesPage` keeps a `?prefix=` only when it starts
with the resolved space's `rootPrefix` and ends in `/`, so a root-relative prefix is silently
discarded and the recipient lands at their space root — a link that looks like it worked. A test in
`test_file_send_notify.py` drives the handler, reads the route's path, parameters and gate,
`rootPrefix`'s own definition, and the literals `NotificationRow` and `isSafeInAppPath` test a link
with, out of the TypeScript rather than restating them, and checks that each recipient's prefix is
the inbox the copy writes to, since a link to the space root survives the route too. The check's
first version, in SPEC-167's build, pinned only the gate and compared against a hardcoded value,
which would have stayed green through the rename it existed to catch. The two tests SPEC-167
shipped, one on the route rule and one on `isSafeInAppPath`, were deleted with their file when the
suites were cut to their entry points (`a41bda69d`), which is why this one drives the handler. The
same cut took the handler test's own link assertions, and coverage could not notice, because the
handler still ran the function.

**The link is feature-gated, and that was a review finding.** With `files` off it was a live anchor
into the unavailable page; with `sharedWorkspaces` off the space link resolved the personal space
and dropped the prefix — the exact failure the full-key rule exists to prevent, reachable from flag
state alone. ~~`NotificationRow` now gates a MAP of flag→match rather than one hard-coded prefix, with registry rows for both — and the space arm matches on `?space=`, because that variant differs in its query rather than its path.~~ **— superseded 2026-09-25:** the map missed a `/query` producer, and the row now derives its gate from the destination (`docs/decisions/browser/`, *A link is gated by its destination's flags*); the two registry rows stand.

**The double-submit guard is the in-flight ref, NOT the queue's dedup id.** FR-003 AC5 said
otherwise and was amended in build: the `requestId` is minted per SUBMIT, because it is also what
makes a retry possible — reused across a failed attempt, the second send is swallowed by the queue
and the user gets an error, presses the button again, and nothing at all happens. The trade is a
first send whose response was lost being retried as a new request, which the conflict guard then
refuses per recipient and tells the sender about.

**A refusal must be reachable to be a refusal.** The dialog's Send control stays ENABLED with no
recipients: `submitDisabled` made the inline refusal dead code where an acceptance criterion was
supposed to be, and a test asserting only "the button is disabled" passed over it. A disabled
button also explains nothing to the user who typed a name and forgot to commit it.

## History

### 2026-09-25

- **Changed:** `NotificationRow`'s map of flag to match missed a `/query` producer, so the row now derives its gate from the link's destination; the two registry rows stand.

### 2026-08-11

- **Settled:** SPEC-167.

---
type: Decision
title: "The trust flip is two deploys, and the second cannot be rolled back (SPEC-201)"
description: "The trust flip took two deploys and recovery is forward only; a pre-cutover message, flat token and no block, is refused `unauthorized` with no notification and no drain record, and the plane allowed-field sets stay untightened to keep that reason."
---

Step one: the eight consumers require `identity` and stop calling `cpcommon.auth`, while the API is
**still writing the token beside the block**. Step two, only once step one is deployed and
exercised: the API stops writing it. Collapsing them into one merge fails all eight planes closed on
the first request after deploy — and **both suites still pass**, because the planes' tests are
written against `identity` and the API's against its own output, and nothing in either sees the
other's envelope.

**Rollback has a shape rather than a direction, and step one's is the inverse of the forward
order.** Reverting step one's Lambdas restores token verification while the producer is still
sending a token, so the revert is clean — *but only if the infra is reverted first*. The env comes
out with the code, so redeploying the previous zips alone restores a verifier reading
`config.USER_POOL_ID`, which is gone: a `RuntimeError` on the first request of every plane, worse
than what is being rolled back. **Infra, then code.** After step two there is no backward path at
all; recovery is forward.

**The window between step one's deploy and the queue draining is real and its outcome is
deliberate.** A message the API enqueued before step one carries the block beside the token and
is served as usual. A pre-cutover message — the browser's envelope, a flat token and no block — is
refused `unauthorized` with **no notification**: there is no trustworthy recipient and nothing in
the message may be believed. It does **not** dead-letter: every plane's Pipe is `FIRE_AND_FORGET`, so
`StartExecution` succeeds, the Pipe deletes the message, and the refusal happens inside the
execution. A request DLQ only ever receives what the Pipe could not *deliver*. The spec asked for a
drain record for this case; there cannot be one, and looking for it reads as the drain being broken.

**The plane allowed-field sets are NOT tightened**, and this is the easy thing to get wrong while
making everything else green. Removing the legacy flat token field turns a pre-cutover message into
`malformed_event` before the reader ever sees it — a different reason code, a different notification
decision, and a criterion that silently stops testing what it names. The sets are pinned **per
plane**; a fleet-level "at least one still admits it" passes while any single plane regresses.

## History

### 2026-08-18

- **Settled:** SPEC-201.

---
type: Decision
title: "The identity grant is the only path to a request queue; no resource policy (SPEC-200)"
description: "Request queues are guarded by identity grants alone, with no `aws_sqs_queue_policy` in `infra/` and a sweep keeping `sqs:SendMessage` off the portal role; do NOT add a blanket `Deny` on the API's role ARN, which silences every outcome notification."
---

There is no `aws_sqs_queue_policy` anywhere in `infra/`, and SPEC-200 adds none. "Only the API may
write" is achieved by adding one grant and removing eight.

The precedent for a resource-side allowlist is the user-space bucket policy, whose own recorded
failure mode is that it is hand-maintained and a missing plane half-works. What stands in its place is
an **enumerated** sweep — the portal-role templates are globbed from the filesystem and asserted to
carry no `sqs:SendMessage` — because a hand-kept list is exactly what would miss the ninth plane.

**Do NOT add a blanket `Deny` with a `StringNotEquals` on the API's role ARN.** It is the shape a
reader reaches for, and it silences every outcome notification this product sends: the notifications
request queue has eight writers and SPEC-200 removes exactly one. The other seven are execution roles
that notify, plus the dead-letter drain. The shared-spaces producer runs with `ResultPath: null` and a
`Catch` leading onward so it deliberately cannot fail its run, and the other planes notify
best-effort — so archives, shares and sends would all complete and no user would ever be told.

## History

### 2026-08-29

- **Settled:** SPEC-200.

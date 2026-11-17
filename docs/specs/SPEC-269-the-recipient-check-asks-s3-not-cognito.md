---
type: Spec
id: SPEC-269
title: "The Recipient Check Asks S3, Not Cognito"
description: "Would have moved the control planes' 'does this user exist?' check off Cognito and onto the user's provisioned prefix marker in S3; cancelled before it was built, and the design moved into the transition plan."
spec_status: Cancelled
depends_on: []
---

**Dependency notes:** None to build on.
**Transition context:** `docs/transition_plan.md`. This spec was cancelled while still Draft; nothing
was built.

## Why this spec was cancelled

**User decision, 2026-11-17: work meant for after the move into the client environment gets no spec;
it lives in [`docs/transition_plan.md`](../transition_plan.md).** This repeats the rule of 2026-09-01
(SPEC-204's tombstone): a spec that can only be built or proved in another environment is a spec
whose claims drift with no test to catch them. Unlike its siblings it could have been built and checked in this account, and it says the current environment would move too. It is cancelled anyway because its only purpose is the successor account's bridge pool, which keys Cognito on the Entra object id; in this account the Cognito check works. If the order of work ever needs it before the move, the plan carries everything needed to do it here.

**The design was not discarded. It is now [`transition_plan.md` §6.1, *The recipient check moves
to the prefix marker*](../transition_plan.md#the-recipient-check-moves-to-the-prefix-marker)**, with
the marker-first atomic write in §3.12 item 1, the leaver's marker in §3.12's de-provisioning
paragraph, and the ordering in *The bridge pool as designed*. What moved: the problem, the three
refused sources, the lookup semantics (fullmatch first, 404 only as unknown, `403` as a fault and why
each reader needs `ListBucket`), add-members checking every name before its slot loop, why the marker
is not fenced by IAM, and the two-way reconciliation if the current environment moves first.

## What validating it against the built code found, 2026-11-17

Recorded because the corrections are the reason a client-environment design should not sit in
`docs/specs/` unbuilt.

- **Its premises hold.** `cpcommon/cognito.py`'s `user_exists` calls `admin_get_user`, returns False
  on `UserNotFoundException` and raises anything else as transient; both planes carry a
  `RecipientUserCheck` Sid; both already hold `GetObject` on the bucket and an unconditioned
  `ListBucket`; post-confirmation may import only `observability` from `cpcommon`, its timeout is 3
  seconds, and its role is not on the bucket policy's allowlist; nested `DO_NOT_DELETE.txt` writers
  exist in saved queries and "New folder".
- **It surfaced an unrelated defect.** The username-directory decision says a tripwire test fails if
  any other Lambda references the directory. That test, `test_no_other_lambda_references_the_directory`,
  was removed in the suite cut (#540) and nothing replaced it. That was current-environment work, so
  it went to a change of its own, which restored the guard (#1034).

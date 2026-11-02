---
type: Decision
title: "A transfer's refusals are RETURN VALUES, because a raise in the validator reaches nobody (SPEC-208)"
description: "**Past the `Catch`, a raised refusal keeps its reason and loses its `tokens`**, which never reach a `Cause`. So a raise names what its verb found — a column, a colliding item, for a refusal of the whole request — only when that verb tells it on the way out, as `columns_removed` does; a name told further down, by an end producer or `NotifyFailure`, travels on the state as a RETURN VALUE. And most planes' `NotifyFailure` drop a `TerminalError` as already told, so one its verb did not tell reaches nobody, and so can a validator's untold raise, since not every notifier recovers the actor from `raw`. Collapse what a REQUESTER reads, or it is an oracle."
---

> **Widened by SPEC-217:** `add_members` and `remove_members` now decide the same way, through
> `auth.member_refusal`, for the same reason and through the same `RefusedSeed` arm — the branch
> was written action-independent, so it needed no change. Read every "a transfer" below as "any of
> the three actions that return", and "every other refusal" as the ones that still raise.

The refusals that still raise on this plane raise `AuthorizationError` from `shared-space-validate`.
That is correct for them and would be silently wrong for a transfer, for a reason that is a property
of the state machine rather than of the code: the validator's `Catch` carries **no `ResultPath`** — you
cannot merge a key into the raw SQS array it was handed — so the state is *replaced* by the error,
and `ValidateFailureSeed` seeds `actor: null` and `space: null`. The notifier treats a null actor as
no trustworthy recipient and stays silent. **A raised transfer refusal is a refusal nobody is ever
told about.**

A transfer's refusals also have to name things the composed failure wording cannot reach. The
notifier is handed an action and a space; "that person is not a member" is useless without saying
*which* person. So the refusal travels as a `(code, message)` pair on the validated context, its
sentence composed in the domain layer at the point that has the name to hand, and a new first
`Choice` branch routes it to a seed that reaches `NotifyFailure` before `Fail`.

**Three traps in that branch, each of which ships green:**

- **`IsPresent` is TRUE for a field that is present and null.** This plane's own
  `ValidateFailureSeed` teaches the opposite habit — "a null VALUE is fine; a missing key is fatal"
  — so seeding `refusal: None` is the natural thing to write, and it would route *every* request on
  the plane into the refusal branch. The validator sets the key only when there is a refusal, the
  rule pairs `IsPresent` with `IsNull: false` so it is right either way, and the happy-path test
  asserts the key is absent. `file-ops` had already paid for this exact trap.
- **The seed cannot go through `RecordFailure`.** That state projects a fixed six-key shape shared
  by all seven verb `Catch` arms, and a `Pass` state's JSONPath hard-fails on an absent key — so
  adding `message` there would raise an uncatchable `States.Runtime` on every one of them.
- **The verb refuses a context carrying a refusal, and the router is not the only fence.** The
  compare-and-swap's expected-owner check is a *lost-update* guard: it asks whether the owner
  changed since authorization, and for a forged operator message nothing about the owner has
  changed, so it passes. Without a check in the verb, any failure of the `Choice` to select the
  refusal branch completes a real transfer. That is this project's named failure shape — the
  failure fails **open**.

**Who the refusal names, and why it is not the operator.** The context's `actor` decides who is
notified, and `notifications-writer` builds an S3 key straight out of it with no validation — while
`"operator"` satisfies the catalog rule that would otherwise catch it. A sentinel there would
address a prefix a real user could own. So an operator-origin request carries the space's **current
owner** as `actor`, with `origin: "operator"` recorded beside it: for a forged message they are the
named victim, and for a fault mid-transfer it is their space. A space with no owner yields no
recipient, which is honest — there is nobody to tell.

**The owner check is skipped by passing `requester=None`, not by a flag.** Written as a flag it
would be untestable: the acting identity for an operator IS the owner, so the check would pass
anyway and the skip could be deleted with every test still green. `None` equals no owner, so
removing the guard makes every operator transfer refuse — loudly.

**Past the `Catch`, a raised refusal keeps its reason and loses its `tokens`**, which never reach a `Cause`. So a raise names what its verb found only when that verb tells it on the way out, as `columns_removed` does; a name told further down, by an end producer or `NotifyFailure`, travels on the state as a return value.

## History

### 2026-09-01

- **Settled:** SPEC-208.

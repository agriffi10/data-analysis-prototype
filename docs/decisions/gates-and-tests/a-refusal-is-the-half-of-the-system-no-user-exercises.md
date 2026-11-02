---
type: Decision
title: "A refusal is the half of the system no user exercises (2026-08-28)"
description: "**A refusal is the half of the system no user exercises**, and a coverage number is blind to it: a `raise` is one line, so deleting its test barely moves the percentage while the happy path — which runs on every dev run and every real action — keeps the function covered. Assert the **reason code by name**, never that \"something raised\". The check is mechanical: enumerate the codes raised against the codes asserted. A review samples this; a sweep counts it. **Mutation-test the guard whose failure would be SILENT** — not every assertion. This project ships assertions that pass while the thing they name is false, so one targeted break-and-revert when the guard is written is worth it. A **sweep** of every guard afterwards is not: it costs a full suite run each and finds what writing the test carefully already would. The cheaper habit that catches the same class: assert the **reason** — the message, the named item — never just an exit code or a count, since the neighbouring path usually returns the same code."
---

A control-plane verb is mostly its checks, and each one is a `raise TerminalError("<reason>", …)`
whose first argument is a closed vocabulary driving the user-facing wording. **That reason code is
the thing a test must assert by name** — "something raised" passes against the neighbouring path,
and against an `ImportError` at cold start.

**Refusals are the half of the system nothing else exercises.** The happy path is self-policing: it
runs on every dev run, every live check and every real user action, so it fails loudly and
immediately. A refusal path runs only when something is already wrong. When one stops working the
system does not error — it **proceeds**, does the thing the check existed to prevent, and reports
success.

**A coverage number is close to blind to them, and a coverage-driven cleanup eats them first.** A
`raise` is one line; delete the test that drives it and the surrounding function is still executed
by the happy-path test, so the percentage barely moves. Measured on the suite reduction that
produced this entry: reason codes with a test asserting them fell **62 → 34 of 85** while total
coverage stayed above its floor throughout.

**The check is mechanical, so run it rather than reviewing for it.** Enumerate the reason codes
raised across `lambdas/`, enumerate the ones a test compares against, and diff. It answers in
seconds and returns the whole population. Three fresh-context review frames over the same change
returned 4, then 7, then 17 findings — diverging, because a review samples where an enumeration
counts.

> The 28 codes this project knowingly stopped asserting are listed on the PR that reduced the
> suites. Restoring one is `git show <ref>:<path>` plus a prune; the decision to leave them was
> deliberate, not an oversight.

Mutation-test the guard whose failure would be silent, not every assertion. This project ships assertions that pass while the thing they name is false, so one targeted break-and-revert when the guard is written is worth it. A sweep of every guard afterwards is not: it costs a full suite run each and finds what writing the test carefully already would. The cheaper habit that catches the same class is to assert the reason, the message or the named item, never just an exit code or a count, since the neighbouring path usually returns the same code.

## History

### 2026-08-28

- **Settled:** entered the register.

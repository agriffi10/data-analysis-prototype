---
type: Decision
title: "`assurance` fails closed on an unknown value, including an absent one (SPEC-201)"
description: "A plane refuses terminally as `unsupported_assurance` any `identity.assurance` but `interactive`, including `delegated`, empty or absent; the accepted set is defined once in `cpcommon.actor`, and `delegated_by` must be present and null."
---

`identity.assurance` says how strongly the API established the actor, and today exactly one value is
minted. A plane presented with anything else — including the reserved-but-unminted `delegated`, an
empty string, a non-string, or **no value at all** — refuses the message terminally under a distinct
reason code, `unsupported_assurance`. It does not downgrade, ignore, or treat an unrecognised value
as the default. `identity.delegated_by` must be *present* and null, because SPEC-200 stamps an
explicit null and an absent key is therefore a malformed block.

Nothing mints anything but `interactive`, so the refusal is unreachable in production — **and that
is its purpose.** When a later arc mints a machine principal, every plane refuses it until that
plane is deliberately widened, rather than silently treating a service as a person at a keyboard.
The absent case is refused for the same reason: a missing assurance reading as `interactive` makes
the field's fail-closed property decorative, and an omitted field is the shape most likely to arrive
first.

The set is defined **once**, in `cpcommon.actor`, and a sweep fails if a second module declares its
own — the widening must be one edit in one place, not whichever plane relaxed first. The literal
agrees with the one the API mints **by import**, not by restatement: two hand-written copies of one
string in two suites is exactly the shape that lets a contract disagree while both suites pass.

**Its reason code does not survive on two planes**, and that is worth knowing before relying on it.
shared-space and notifications-writer pass their own exception type, which carries a string and no
code, so the refusal is prefixed into the detail for a human reading a log line. It does **not** come
back through `errors.failure_reason`, which gates on `errorType == "TerminalError"`. A live check for
an unaccepted assurance must therefore aim at a plane taking the default exception.

## History

### 2026-08-18

- **Settled:** SPEC-201.

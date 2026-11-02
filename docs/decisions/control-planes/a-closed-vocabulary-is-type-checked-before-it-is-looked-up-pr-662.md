---
type: Decision
title: "A closed vocabulary is type-checked before it is looked up (PR #662, control-plane-wide)"
description: "**A closed vocabulary is TYPE-CHECKED before it is looked up** — `cpcommon.events.in_vocabulary`, never a bare `value not in VOCAB`. `in` **hashes its left operand**, so a request field holding a list or a dict raises `TypeError` out of the membership test itself, before the plane can raise its named refusal, and `notifies_on_failure` records that instead of a reason code. It is a **predicate, not a raise**, because the wording is the domain's; it is a `TypeGuard[str]`, so a caller that refuses on False keeps its narrowing. Its vocabulary is typed as a **set or mapping, never `Container`** — `in` on a `str` is a SUBSTRING test, so a string vocabulary would admit every infix of itself. A **positive-form** test (`x if x in V else …`) hashes exactly the same, and one hid in each of the two mode readers that pick a plane's wording (`_wording_mode`, `_mode_from_raw_request`) — including the notifier of last resort, documented as raising nothing."
---

`if value not in SOME_FROZENSET:` reads as a total check and is not one. `in` **hashes its left
operand**, so a request field carrying a list or a dict raises `TypeError` out of the membership
test itself — before the plane reaches the refusal it wrote for exactly this case. The
`@notifies_on_failure` decorator then reports an unexpected error, and the Step Functions record
carries a `TypeError` where a reason code the actor could be told about should be.

**The population was nineteen sites across nine planes, and finding it took three sweeps.** The
first fixed the four `SPACE_KINDS` lookups inline. The second, working from a hand-listed
population, converted the obvious `not in UPPERCASE` forms — and a plane test written for that
change immediately failed on a site the list did not contain, because a **positive-form** test
(`return mode if mode in ARCHIVE_MODES else ""`) hashes exactly the same and no negated-form sweep
can see it. The third missed `action not in config.VALID_ACTIONS` because the vocabulary is reached
through a module and the pattern required an uppercase first character. What settled it was
abandoning regex for an **AST walk over every `Compare` node with an `In`/`NotIn` operator** whose
right-hand side names a constant, which is the only sweep here that cannot be defeated by how the
expression is spelled. The lesson is the sweep, not the fix: a matcher shaped like the examples you
already have finds the examples you already have.

**The remedy is one predicate, `cpcommon.events.in_vocabulary`, not an inline clause repeated.**
At this population size the inline form is how a site gets missed, and each repetition needs its own
test row; one predicate owns one test — including the unhashable case — and every call site's
existing wrong-value test still catches an inverted conversion. It returns a **`TypeGuard[str]`**
rather than a bool, which restores the narrowing the inline `isinstance` gave its callers: without
that, `focommon.authz` stopped type-checking where it passes the kind onward. **Do not read either
type as a fleet-wide guard.** `[tool.mypy] files` lists the shared LAYERS only, so the per-verb
directories — where most call sites live — are not type-checked at all; both annotations bite in
`arcommon`/`focommon`/`fscommon`/`rccommon`/`cpcommon`/`shared-space-common` and nowhere else.
Verified by planting a `str` vocabulary in each: it is an `arg-type` error in a layer and silent in
a verb, where even `_x: int = "s"` passes. It is a **predicate
rather than a raise** because the wording is the domain's — the same bad field means different
things on different planes, and `cpcommon` owns the algorithm while a domain layer owns its wording.

**Five sites that look identical are unreachable and stay as they are**, each checked by tracing
every caller rather than by reading the site: `arcommon.paths` and `focommon.paths` receive the kind
their plane's `authorize_source` already validated; `fscommon.authz.recipient_location` — which is
NOT that plane's `authorize_source` — has one caller, passing a recipient `_normalize_recipients`
built; `feedback-writer`'s category is guarded by the `REQUIRED_FIELDS` loop above it; and
`dq_byte_scan`'s format is derived by `inspect-source` from a file extension and never comes off a
body at all. Converting them would state a defensive intent the callers make false.

**One reachable site is deliberately NOT converted.** `backfill_ever_active` reads `mode` off a
raw invoke payload, so `{"mode": ["stamp"]}` raises `TypeError` where its `ValueError` belongs. It
is an operator-invoked maintenance function on no plane and behind no notifier, so the harm this
fence exists to prevent — a `TypeError` on an execution where the actor's reason code should be —
cannot occur there. Recorded rather than fixed, so the next sweep does not read it as a miss.

**The worst instance was not on a validator.** `ar_notify_failure._mode_from_raw_request` reads the
mode off the untrusted body on the EventBridge timeout door — the only door that must, since a
top-level timeout leaves nothing recorded — under a docstring promising it raises nothing. A
`TypeError` there is an async Lambda failure EventBridge retries, so the notifier of last resort
tells the actor nothing, three hours into a restore. Its sibling reader on the ASL door already
type-checked, which is why the first test written for it passed while exercising nothing: **the two
readers are different doors, and a case driven on one says nothing about the other.**

The predicate's vocabulary is typed as a set or mapping, never `Container`: `in` on a `str` is a substring test, so a string vocabulary would admit every infix of itself. A positive-form test hid in each of the two mode readers that pick a plane's wording, `_wording_mode` and `_mode_from_raw_request`.

## History

### 2026-09-06

- **Settled:** entered the register.

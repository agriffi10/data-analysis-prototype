---
type: Decision
title: "A partial teardown never frees the space name (SPEC-151)"
description: "A teardown that could not finish leaves the registry record intact, because that record is the lock on the space name; per-item `delete_objects` and `batch_delete_table` errors raise rather than pass as HTTP 200."
---

`delete_objects` and `batch_delete_table` both answer **HTTP 200 with a per-item `Errors` array** — a
key or table that failed individually does not raise. Both return values were discarded, so a
partially-failed teardown was indistinguishable from a complete one, and `delete_space` went on to
`reg.delete(space)` — the line commented "LAST — the name is now free to reuse". The next space
created with that name would inherit another tenant's objects.

Both helpers now raise `teardown.TeardownIncompleteError`, and the rule is: **a teardown that could
not finish must leave the registry record intact.** The record is what reserves the name, so keeping
it is what stops reuse; the caller's existing `except` already records a terminal `failed`, and
`reg.delete` is inside the `try` it never reaches. `forget-space` inherits this for free — both verbs
share the helpers.

Three details that are decisions rather than implementation:

- **Counts, never keys.** The message reaches logs and the registry's `failed` record, and the field
  rule binds what a call site chooses to emit. "3 object(s) under `sales/` could not be deleted" is
  enough to tell a partial failure from a total one.
- **Every page is attempted before raising.** A denial on one key must not strand the rest of the
  space's objects, and the count is only meaningful whole.
- **The Glue raise lands BEFORE `delete_database`.** Dropping a database whose tables survived is how
  the catalog and the bucket start disagreeing.

This meets **SPEC-054**'s written acceptance criterion — teardown leaves "never a dangling …
half-deleted resource" — which had been recorded and never implemented. **Do NOT "improve" this by
deleting the record and reporting the failure elsewhere:** the record IS the lock.

## History

### 2026-08-05

- **Settled:** SPEC-151.

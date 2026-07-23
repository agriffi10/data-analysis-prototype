# Completed Spec — SPEC-136: Instrument the Table-Share Control Plane

## What was completed?

Five verbs join the pipe as `service="table-share"`. No behaviour change. Two PRs: infra, then
code.

**Registering the plane needed no new harness machinery** — one `Plane()` row, and SPEC-135's
handler-based module discovery meant there was no filename convention to declare. This is the
first plane to land without touching the harness at all, which is what it was built for.

## What each verb says

- **validate-authorize** — recipients **requested vs valid**, and *which* were invalid. The two
  diverge silently: a share to five recipients where two resolve to nothing is neither a failure
  nor a clean success, and a count alone cannot say which. Recipient names are space/user names —
  permitted metadata, and the whole question when someone asks why they did not receive a table.
- **inspect-source** — the copy **plan** (objects, bytes, partitioned), not the objects. Counts
  and totals separate a share that was too large from one that was mis-scoped; the keys already
  ride in the state payload.
- **check-target-absent** — the verdict as an **explicit boolean**. This plane is a *push with no
  consent step*, so "the destination was empty before we wrote to it" is the only record that a
  share did not silently land on top of something.
- **copy-objects** — **per recipient, never per object.** It already runs inside the SFN's
  recipient `Map`, and a folder can hold thousands of objects.
- **create-table** — the recipient **database**. This plane creates tables in databases it does
  not own, through the same TBAC grant whose absence caused table-builder's silent-create
  incident (SPEC-070/111).

## Verification

`ruff check lambdas/` clean; `pytest lambdas/` 1418 passed / 2 skipped at merge. The harness runs
196 assertions across four planes.

Five mutations, all observed to fail: `verb_count` too low; a service name that would route to
`logs/_unrouted/`; `copy-objects` losing `@traced`; `create-table` silenced; a contents-shaped
field in `validate-authorize`.

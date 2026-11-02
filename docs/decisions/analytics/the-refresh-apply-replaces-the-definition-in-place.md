---
type: Decision
title: "The refresh apply replaces the definition in place (SPEC-149, supersedes SPEC-144's apply)"
description: "`apply-refresh` issues one `glue:UpdateTable` as a read-modify-write on the live table, changing only columns and `projection.*` parameters, never rebuilding from the capture; a read-back failing after the update raises `update_unconfirmed`."
---

`apply-refresh` issues **one `glue:UpdateTable`**, not two Athena statements. There is no moment at
which the user's table does not exist, no new catalog entry, and therefore no loss of table identity,
`Description`, `Owner` or table-level Lake Formation grants. A **failed update changes nothing**,
which is what retires SPEC-144's "a committed drop followed by exhausted retries notifies nobody"
exposure: there is no committed destructive step left to be silent about. It also stops the portal
entrenching a pattern it would have to unpick for Iceberg, where drop-and-recreate destroys the
snapshot history that is most of the reason to adopt it.

**A read-back failing AFTER the update cannot say nothing changed.** The
post-condition runs once the update has committed, so a Glue fault on that read, or a catalog
reporting other columns than were written, leaves a table whose columns may already be retyped,
removed or reordered. It raises `update_unconfirmed`, whose message sends the user to check the
table before refreshing again — never `update_failed`, whose "Nothing was changed" would be false
there.

**The one thing to understand before touching this verb: it is a READ-MODIFY-WRITE on the live table,
never a rebuild from SPEC-143's capture.** `UpdateTable` replaces the WHOLE definition — a
`TableInput` omitting a field does not leave that field alone, it **clears it** — and
`clone_definition` never carried `Description` or `Owner` and deliberately strips `EXTERNAL`. Building
the input from the capture would delete exactly what the change exists to preserve. The verb reads the
live table immediately before writing it and mutates only the **columns** and the **`projection.*`
parameters**.

**Three mechanism points are load-bearing.** (1) The `TableInput` is an **allowlist projection** of
the live `Table`, pinned against botocore's service model by a test — `Table` returns 25 members and
`TableInput` accepts 14, so a denylist of the extras goes stale whenever AWS adds a field, and four of
today's eleven already postdate the obvious set. (2) **Column names are lowercased on write**, because
AWS documents that Athena folds names created through DDL — the create path gets the fold for free and
this path, bypassing Athena, must reproduce it or leave a mixed-case entry the create path could never
produce. (3) **`portal.managed` is re-asserted through `ddl.mark_managed`, never named in the verb**,
so SPEC-143's guard against a verb branching on a user-writable marker stays strict.

**IAM moved the right way: `glue:DeleteTable` was REMOVED, `glue:UpdateTable` added.** No verb on this
plane deletes a table any more, and a test greps the table-builder modules to keep it so. The explicit
`Deny s3:DeleteObject` is untouched — it never depended on the drop, and it outlives the mechanism
that prompted it. Lake Formation needed no change: the `portal-managed` table tag policy already
grants `ALTER`.

**What is NOT fixed, and must not be claimed:** the concurrent-refresh race is **reduced, not
closed**. The Pipe still starts executions `FIRE_AND_FORGET`, and **Glue offers no compare-and-set on
`UpdateTable`** — `VersionId` is documented only as "the version ID at which to update the table
contents", with no precondition-failure error. The worst case degrades from "one run sees no table" to
last-write-wins between two definitions. A real fix is a serialization change to the Pipe.

> **Superseded in part by SPEC-157 (2026-08-09).** The race is now serialized by a per-table lock
> outside Glue, so the second refresh is refused rather than raced — the paragraph above stands as
> the state SPEC-149 left, not as the state today. What it says about Glue is still true and is
> exactly why the lock exists: `UpdateTable` has no compare-and-set, and `VersionId` is still not a
> precondition. The fix was NOT a Pipe change — see *A per-table lock serializes refresh* below.

Full account: `docs/spec-delivery/SPEC-149-refresh-table-in-place-rebuild.md`.

## History

### 2026-08-09

- **Changed:** The concurrent-refresh race is serialized by a per-table lock outside Glue, so the second refresh is refused rather than raced.

### 2026-08-04

- **Settled:** SPEC-149, supersedes SPEC-144's apply.

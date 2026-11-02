---
type: Decision
title: "Refresh eligibility turns on SHAPE, never on a marker (SPEC-143)"
description: "**A refresh is judged by SHAPE, not by a marker** — never by the `portal.managed` property it also writes, which pre-existing tables lack and users can set. Removing a column needs an opt-in, and **the refusal is the warning**. The apply is a read-modify-write on the live table, serialized by a per-table lock whose loser is **refused with a notification**, never queued."
---

A refresh reads a table this run did not create, so before re-deriving anything it must answer *can
this be faithfully rebuilt from its own definition plus a fresh look at its files?* **It answers from
what Glue reports, never from a `portal.managed` marker** — and the marker exists anyway, written by
`cpcommon.ddl.build_create_table_ddl` from this spec onward. Both halves of that are deliberate.

**Why not the marker.** Every table created before SPEC-143 lacks it, so a marker test refuses the
entire existing estate. Worse, `TBLPROPERTIES` are user-writable through `ALTER TABLE SET
TBLPROPERTIES` from the query workspace — so it can be trusted neither as a permission nor as a
fact, and the moment a verb branches on it a user can grant themselves whatever that branch guards.
A test scans the whole Lambda tree and fails if anything outside `ddl.py` (which writes it) and
`glue.py` (which excludes it) so much as references it. That scan reads the **parsed AST**: a
literal-only grep waves through `from cpcommon.ddl import PORTAL_MANAGED`, and a text scan flags the
comments that warn against confusing `portal.managed` with `portal-managed`. **Those two names are
one character apart and unrelated** — the dotted one is a table TBLPROPERTY that records and grants
nothing; the hyphenated one is the Lake Formation tag on DATABASES that is how control-plane roles
get `CREATE_TABLE` at all (`infra/modules/analytics/lakeformation.tf`). Every site of both carries a
comment saying so.

**What the shape checks are.** `cpcommon.glue.clone_definition` — moved here from `tscommon.glue`
because table-share asks the identical question — refuses views, non-external tables, catalog-
partitioned tables and unusable locations. The refresh path **maps** its four codes to its own
vocabulary at its call site rather than parameterising them (the stems differ, so no substitution
produces both sets), and asserts its mapping covers `clone_definition`'s whole set. That assertion
is load-bearing: `cpcommon.glue` now registers those codes itself, because `TerminalError` validates
at the raise site and they were previously registered only as an import side effect of
`tscommon.messages`, which a table-builder Lambda never imports. Registration is what lets the
refresh path speak — and its cost is that an **unmapped** code no longer explodes; it would sail
through as a valid terminal and resolve to the generic `unexpected_error`.

**Beyond the shape: the reconstruction needs two guards, and neither suffices alone.** SPEC-069's
declared partition keys are recorded nowhere but on the table, as `projection.*` properties, and
`build_create_table_ddl` requires the declared shape (it raises a bare `ValueError` on a Glue-shaped
key). So the verb rebuilds them and then **re-renders each one through the create path's own
renderer, demanding exact equality** — which catches a dropped property, a rewritten one (a
zero-padded bound), and any extra `projection.*` option. What it structurally cannot see is the
**column type**: Athena permits a projection over a wider set than this builder writes, and an
`integer` projection on a `string` column is precisely how a zero-padded partition gets declared.
That table round-trips *perfectly* and would be rebuilt as `int`, retyping the column while
reporting success. Table-level `storage.location.template` is refused for the same reason — it sits
outside the namespace the per-key round-trip compares. **The rule: a reconstruction that cannot be
performed is a refusal, not a guess.**

**Three ASL/marker traps worth carrying.** (1) **A `Choice` rule whose `Variable` path is ABSENT
raises `States.Runtime`, which no Catch anywhere can catch — it does not fall through to `Default`,
which covers only a value that is present and matching no rule.** So the one input `Default` exists
for is the one a bare `StringEquals` kills; both rules are `And` + `IsPresent`. (2) The same hazard
on the success side — `RecordSuccess` reads `$.mode` and a `Pass` state's JSONPath hard-fails the
same way — is closed by `execute-ddl` defaulting the field, since only a create reaches it; the
window is an execution starting after the state machine deploys but before the Lambda code does,
which would otherwise die *after* the table was created and the actor notified. (3) **Marking is an
explicit `mark` argument, never inferred from `storage is None`.** That inference reads correctly
against today's two callers and is wrong for the next: SPEC-144's `apply-refresh` is a `DROP` +
`CREATE` supplying a rebuilt `Storage`, so inference would strip the marker from every table a
refresh touched. Full account: `docs/spec-delivery/SPEC-143-refresh-table-contract-and-eligibility.md`.

## History

### 2026-08-04

- **Settled:** SPEC-143.

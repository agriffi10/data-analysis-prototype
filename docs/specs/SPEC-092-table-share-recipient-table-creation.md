# Spec: Table Share — Recipient Table Creation & Terminal States (create-table)

**ID:** SPEC-092
**Status:** Completed
**Last Updated:** 2026-07-04
**Depends On:** SPEC-091 (copied data + per-recipient item), SPEC-090 (cloned definition), SPEC-070 (Athena-DDL + LF-admin precedent), SPEC-032 (workgroup + LF)

> **Read `docs/table-share-architecture.md` §6, §7 first.**

## Overview

Complete the recipient `Map` with **create-table**: from the cloned source definition (SPEC-090) with its `LOCATION` repointed to the recipient's `shared_tables/{tableName}/` prefix, run `CREATE EXTERNAL TABLE IF NOT EXISTS …` via **Athena** against the **recipient database**, polling to a terminal state. This makes each recipient's copied data queryable as a real table — an exact clone of the source (projection props carried, so no `MSCK`). This spec also finalizes the Step Function's success/failure terminal states and the **shared execution role's** LF/Glue/Athena/S3/Cognito grants (the role is a **Lake Formation admin**), delivering end-to-end sharing (sans notifications/UI polish).

## Scope

### In Scope

- **create-table** (third Map state): render DDL from `tableDefinition` (columns, partition keys, SerDe/format, `TBLPROPERTIES` incl. `projection.*`) with `LOCATION` = the recipient dest prefix; run via Athena `StartQueryExecution` against the recipient DB in the shared workgroup; poll to terminal.
- `IF NOT EXISTS` + the SPEC-091 conflict guard ⇒ replay-safe; projection ⇒ **no `MSCK REPAIR`**; a flat table is immediately queryable.
- Per-recipient terminal outcome finalized (`ok` once the table is created; `create_failed` with Athena's reason otherwise) — siblings unaffected.
- **SFN terminal states**: a `Succeed` carrying a **per-recipient summary** (`[{name, kind, status, reason?}]`); the top-level `Catch` for a whole-request failure (auth/inspect) records `{status:'failed', reason}`.
- The **shared execution role** finalized as a **table-share LF admin** with: Glue `GetTable` (source + recipient) + `CreateTable` path via Athena, LF `CREATE_TABLE` on recipient DBs + `DATA_LOCATION_ACCESS` on recipient locations, Athena run/poll + results S3, S3 read/write across both buckets under the copy/results prefixes, Cognito `ListUsers`/`AdminGetUser`, registry `GetObject`. `module.analytics depends_on module.table_share` for the LF-admin ordering.

### Out of Scope

- Notifications (actor + recipient) — SPEC-094 (this spec records outcomes in the SFN execution).
- UI — SPEC-093.
- Catalog-partition metadata copy — deferred (SPEC-090 rejects such sources).

---

## Functional Requirements

### FR-001: Clone DDL with repointed LOCATION

#### Acceptance Criteria:

- [ ] The generated DDL reproduces the source columns, partition keys, SerDe/format, and carried `TBLPROPERTIES` (projection props included), with `LOCATION` set to the recipient's `shared_tables/{tableName}/` prefix and the table created in the recipient DB.
- [ ] A **projection-partitioned** clone is queryable immediately after `CREATE` with no partition-load step.
- [ ] A **flat** clone selects the copied rows immediately.

### FR-002: Execute via Athena + terminal outcome

#### Acceptance Criteria:

- [ ] The DDL runs via Athena against the recipient DB and is polled to a terminal state; success marks the recipient `ok`.
- [ ] An Athena failure marks that recipient `create_failed` with the `stateChangeReason`; siblings still complete.
- [ ] `IF NOT EXISTS` + the SPEC-091 conflict guard make a retry safe (no duplicate-create error path).

### FR-003: SFN terminal states + execution role

#### Acceptance Criteria:

- [ ] The machine's `Succeed` output carries a per-recipient summary array; a whole-request failure (auth/inspect) lands in a recorded-failure state with a reason.
- [ ] The shared execution role is a table-share LF admin and holds exactly the Glue/LF/Athena/S3/Cognito/registry grants enumerated in Scope — nothing broader; `iam:PassRole` scoped to this role.
- [ ] `module.analytics depends_on module.table_share`; the LF-admin/`CREATE_TABLE`/`DATA_LOCATION_ACCESS` grants apply (expect the first-apply `time_sleep` self-grant-propagation caveat; one re-run tolerated).
- [ ] An end-to-end test (or documented manual proof) shares a flat table + a projection-partitioned table to a user and a space recipient; both become queryable; a conflicting recipient is reported `conflict` while the others succeed.

---

## Data Model

```python
# create-table input: the SPEC-091 Map item (recipient + plan + copied)
# create-table output: {recipient, request} threaded through; an Athena failure raises
#   TerminalError("create_failed"|"create_timeout", detail) → the per-item Catch records it.
# Per-recipient summary entry (RecipientSucceeded / RecipientFailed Pass states — as built,
#   uniform with the SPEC-091 verbs: status is ok|failed, the reason slug lives in `reason`):
#   { kind, name, status:'ok' } | { kind, name, status:'failed', reason:'<slug>: <detail>' }
# SFN Succeed output (ShapeSummary Pass):
{ "actor":"...", "source":{...}, "tableName":"...",
  "results": [ { "kind":"user","name":"alice","status":"ok" },
               { "kind":"space","name":"salesteam","status":"failed","reason":"conflict: a table named 'orders' already exists in 'salesteam'" } ] }
```

```python
# tscommon
#   ddl.py     render_create_external(tableDefinition, database, tableName, location) -> sql
#   athena.py  run_ddl(database, sql) -> execution result  (reuse tbcommon/analytics pattern)
```

## Implementation Phases

### Phase 1: DDL render + Athena execute (create-table)

- `render_create_external` from the cloned definition; run+poll via Athena on the recipient DB; per-recipient outcome.

### Phase 2: Terminal states + execution-role finalization

- SFN Succeed summary + top-level Catch; finalize the shared LF-admin execution role grants + `analytics depends_on`.

### Phase 3: End-to-end proof + completion ritual

- Flat + projection-partitioned share to user + space; conflict isolation. Delivery doc, INDEX status, component-inventory rows (`tscommon.ddl`, `tscommon.athena`), CLAUDE.md Key Decision line (pointer to the architecture doc).

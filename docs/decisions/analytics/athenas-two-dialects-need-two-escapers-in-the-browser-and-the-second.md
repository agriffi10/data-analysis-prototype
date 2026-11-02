---
type: Decision
title: "Athena's two dialects need two escapers in the browser, and the second was missing (2026-08-19)"
description: "Browser identifiers take their engine's escaper: `sqlIdentifier` for Trino's `CREATE VIEW` and `DROP VIEW`, `sqlDdlIdentifier` for Hive's `DROP TABLE`, and a shared space's name is quoted too, since only a new space is held to `CATALOG_IDENTIFIER_RE`."
---

`CREATE VIEW` is Trino (double quotes); `DROP TABLE` / `DROP VIEW` is Hive (backticks, an inner
backtick doubled). The browser had only `lib/sql.ts` `sqlIdentifier`, the Trino one, so both
statements interpolated their identifiers raw.

**Superseded for `DROP VIEW` on 2026-09-27:** it is Trino too, so this entry's `DROP` escaper is the
right one for `DROP TABLE` only. A backticked `DROP VIEW` was refused at submit while the bare and
double-quoted forms parsed, so the browser's Drop view could not have dropped any view from this
entry until this fix; it takes `sqlIdentifier` now ([`sessions.md`](../../testing/sessions.md), 2026-09-27). The sweep
this entry calls for stopped at the statement's verb, not its engine.

The identifier that matters is the **database**. A view or table name is typed into a dialog held
to `CATALOG_IDENTIFIER_RE`; a shared space's name was held to nothing the browser cannot
bypass, because the SPA talks to its queue directly and `shared-space-validate` applied **no format
check** to `space`. It holds `CATALOG_IDENTIFIER_RE` there now — and **the refusal is
create-only**, so every space named before it keeps whatever it was given (`live0922 odd` is one).
A name already in a member's space list still reaches DDL under their own Athena credentials, which
is why the escapers below are not made redundant by that rule.

Both statements are quoted now, each with its own dialect's escaper (`sqlIdentifier` /
`sqlDdlIdentifier`). The lesson that generalises is the ordering: `buildCreateViewSql` was fixed
first and `DROP` two functions down was left live for a commit — **a quoting fix is not done until
every statement built from the same value is swept**, because the second one is the one nobody
tests against a real engine.

## History

### 2026-09-27

- **Changed:** `DROP VIEW` is Trino, so it takes `sqlIdentifier`; the Hive escaper is right for `DROP TABLE` only.

### 2026-08-19

- **Settled:** entered the register.

---
type: Decision
title: "Every DDL literal goes through `literal()` (SPEC-151)"
description: "**Every DDL literal goes through `literal()`** — `TBLPROPERTIES` and `LOCATION` included — and the escapers split on **two axes that are easy to conflate**. *Values:* `ddl.literal` backslash-escapes (Hive/DDL), `sql._literal_dml` and the browser's `sqlLiteral` double the quote (Trino/DML). *Identifiers:* `sqlIdentifier` (Trino, `CREATE VIEW`, `DROP VIEW`), `sqlDdlIdentifier` and `ddl.quote` (Hive, `DROP TABLE`, inner backtick doubled — data-quality partition keys come from S3 folder names). **The wrong one fails SILENTLY, as a predicate that never matches**, and it matters because a space created before that rule carries a name no server path checked. A quoting fix is not done until every statement built from the same value is swept."
---

`cpcommon.ddl` renders **every** string literal in a `CREATE EXTERNAL TABLE` through `literal()` —
`TBLPROPERTIES` keys and values and the `LOCATION`, alongside the column comments that already did.
Raw `f"'{value}'"` is forbidden in DDL construction.

The demonstrated consequence of the old form: a partition enum value of
`eu','projection.enabled'='false` rendered as
`'projection.region.values'='eu','projection.enabled'='false'`, **injecting a property that switched
partition projection off**. Blast radius is **self-scoped** — a user can only reach a table in their
own database and Athena rejects multi-statement DDL — so this is robustness, not cross-tenant
escalation. The sharper everyday path is data-quality, where the `LOCATION` and the partition values
both come from **S3 key segments**: a folder named `year=2024'` or `o'brien` broke the temp-table DDL
and killed the whole check as `query_failed`.

**Two escapers exist and must not be confused.** `cpcommon.ddl.literal` escapes with a **backslash**,
which is Hive's rule and what Athena parses `CREATE`/`DROP` with. `dqcommon.sql._literal_dml` **doubles
the quote**, which is Trino's rule and what Athena parses `SELECT` with. Using the Hive form in a
query would render a backslash into the S3 path being matched, and the predicate would silently match
nothing. Each lives in its own module with a docstring saying so; `tscommon.ddl._lit` is the
table-share twin of the DDL one and has always done this.

Ordinary values render **byte-identically** to the old form, which is why the golden-DDL tests are
untouched — a rendering change that moved any existing statement would have been a different and much
riskier decision.

**Corroborated, not demonstrated:** the escaped form has never been exercised against Athena itself.
The tests assert the rendered string. If a `'` in a partition segment ever still fails, suspect the
engine's acceptance of `\'` before suspecting the renderer.

## History

### 2026-08-05

- **Settled:** SPEC-151.

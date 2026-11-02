---
type: Decision
title: "Query workspace has NO active database (SPEC-077)"
description: "**The query workspace has NO active database.** Every base table is fully qualified `database.table`; the rail is browse-only. A space maps to exactly one database, so the picker has no database step."
---

Supersedes SPEC-047/076. Database *selection* is removed entirely — no "current database" anywhere. Queries carry **no** `QueryExecutionContext.Database`, so every base table must be **fully-qualified `database.table`** (an unqualified name fails); this enables cross-database joins in one statement. The schema rail (`useConnections` seam) is **browse-only** (no radio/active); per-table actions (View DDL/data/Drop) take the DB from the rail node; Create view **derives** its target DB from the body's qualified tables; autocomplete (`useAllSchemas`) spans **all** accessible databases with fully-qualified suggestions. The rail no longer inserts into the editor (FR-004 dropped, user decision). Results always land in the personal prefix; shared save destinations stay a Save-time choice (SPEC-049/055).

## History

### 2026-07-03

- **Settled:** SPEC-077.

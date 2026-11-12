---
type: Decision Area
title: "Analytics, the catalog, and two SQL dialects"
governs: [lambdas/table-builder-*/**, lambdas/table-share-*/**, lambdas/data-quality-*/**, infra/modules/analytics/**, infra/planes/table-builder/**, infra/plane-table-builder.tf, infra/planes/table-share/**, infra/plane-table-share.tf, apps/portal/src/features/query/**, apps/portal/src/features/catalog/**, apps/portal/src/features/data-explorer/**, apps/portal/src/features/table-builder/**, apps/portal/src/features/table-share/**]
---

The register's decisions on the Athena/Glue/Lake Formation workspace, TBAC table creation, the two escaper axes, refresh and the data explorer.

An in-app Athena/Glue/Lake Formation workspace. Isolation is the `username` principal tag on the
Glue database ARN — **not** LF-Tags. Table creation is **TBAC**: LF admin does **not** grant
`CREATE_TABLE`; a `portal-managed` LF-Tag plus one tag-policy grant per execution role does.

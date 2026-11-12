---
type: Decision Area
title: "Storage, and the fact S3 is not a filesystem"
governs: [lambdas/file-ops-*/**, lambdas/file-send-*/**, infra/modules/data/**, infra/planes/file-ops/**, infra/plane-file-ops.tf, infra/planes/file-send/**, infra/plane-file-send.tf, apps/portal/src/features/file-browser/**, apps/portal/src/features/file-send/**, apps/portal/src/features/saved-queries/**, apps/portal/src/features/connections/**]
---

The register's decisions on filesystem UX over a store with no move or rename, the file-send and file-ops rules, saved queries, the settings document.

The product presents filesystem UX over a store with **no move or rename**: every one is
`CopyObject` + `DeleteObject`, folder operations are recursive and **non-atomic**, and collisions
warn and confirm. Versioning is off, which is what makes a failure between those two steps
unrecoverable — revisit before real user data lands.

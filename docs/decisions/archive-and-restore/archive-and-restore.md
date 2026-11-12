---
type: Decision Area
title: "Archive and restore — the only place a mistake is unrecoverable"
governs: [lambdas/archive-*/**, infra/modules/archive-vault/**, infra/planes/archive/**, infra/plane-archive.tf, apps/portal/src/features/archive/**]
---

The register's decisions on the GLACIER vault, the commit gate, the destination guard that runs twice, and the surface built to refuse its own affordance.

A separate `GLACIER` vault the browser has no relationship with. A restore is `RestoreObject` + a
3–5 hour wait + a copy.

---
type: Decision Area
title: "Infrastructure, IAM and delivery"
governs: [infra/**, .github/**, lambdas/docker/**]
---

The register's decisions on OpenTofu layout, the deploy role, CSP and caching, the runtime configuration document, the container platform.

OpenTofu, bounded-context modules under `infra/modules/`, IAM policies as `.tftpl` rendered by
`templatefile()`. Notifications are a **single-writer** FIFO queue → writer Lambda; the browser
only reads; the API enqueues on its behalf.

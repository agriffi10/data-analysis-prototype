---
paths:
  - "lambdas/file-ops-*/**"
  - "lambdas/file-send-*/**"
  - "infra/modules/data/**"
  - "infra/modules/file-ops/**"
  - "infra/modules/file-send/**"
  - "apps/portal/src/features/file-browser/**"
  - "apps/portal/src/features/file-send/**"
  - "apps/portal/src/features/saved-queries/**"
  - "apps/portal/src/features/connections/**"
---

This file is in the **Storage, and the fact S3 is not a filesystem** area of the Key Decisions register.
Before changing it, read `docs/decisions/storage.md#fences` — the traps there apply green and fail later.

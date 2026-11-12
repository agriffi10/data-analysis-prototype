---
paths:
  - "lambdas/file-ops-*/**"
  - "lambdas/file-send-*/**"
  - "infra/modules/data/**"
  - "infra/planes/file-ops/**"
  - "infra/plane-file-ops.tf"
  - "infra/planes/file-send/**"
  - "infra/plane-file-send.tf"
  - "apps/portal/src/features/file-browser/**"
  - "apps/portal/src/features/file-send/**"
  - "apps/portal/src/features/saved-queries/**"
  - "apps/portal/src/features/connections/**"
---
Files matching these paths are governed by the **Storage, and the fact S3 is not a filesystem** decisions in `docs/decisions/storage/`.
Read the area's fences in `docs/decisions/index.yaml` first — they are not loaded with CLAUDE.md.

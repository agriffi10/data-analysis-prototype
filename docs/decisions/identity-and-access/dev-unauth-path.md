---
type: Decision
title: "Dev-unauth path"
description: "`VITE_S3_DEV_UNAUTH` no longer exists: the unsigned, no-auth local browsing path is gone, and no browser call to S3 runs unsigned."
---

`VITE_S3_DEV_UNAUTH=true` browses a test bucket read-only without auth (local only); production `/files` always uses the authenticated user-space bucket (SPEC-013).

> **SUPERSEDED 2026-08-29 by SPEC-198 FR-012.** The path is gone. It worked by calling S3 unsigned
> from the browser, and after the object surface moved behind the API there is no unsigned call left
> to make. Full entry: [*The dev-unauth path is retired*](the-dev-unauth-path-is-retired.md).

## History

### 2026-08-29

- **Changed:** SPEC-198 FR-012 removed the path, because the object surface moved behind the API and no unsigned call was left.

### 2026-08-03

- **Settled:** entered the register.

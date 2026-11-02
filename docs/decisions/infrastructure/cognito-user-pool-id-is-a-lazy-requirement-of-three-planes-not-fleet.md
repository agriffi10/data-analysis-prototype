---
type: Decision
title: "`COGNITO_USER_POOL_ID` is a lazy requirement of three planes, not fleet-wide configuration"
description: "**`COGNITO_USER_POOL_ID` is no longer fleet-wide** — a lazy `config.require` on the three planes resolving a recipient, so a missing one raises **mid-request**, not at cold start."
---

`COGNITO_USER_POOL_ID` is no longer fleet-wide. It is a lazy `config.require` on the three planes resolving a recipient, so a missing one raises mid-request, not at cold start.

## History

### 2026-11-02

- **Settled:** carried over from the area's Fences when the register was split.

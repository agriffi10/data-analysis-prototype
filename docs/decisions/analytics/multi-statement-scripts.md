---
type: Decision
title: "Multi-statement scripts (SPEC-078)"
description: "**Multi-statement scripts** split client-side on `;`, run sequentially, stop on first failure. No transactions."
---

The editor splits `;`-separated statements client-side and runs them **sequentially, stop-on-first-failure**, one history entry each; three run scopes — **Run Statement** (⌘⏎, selection/cursor), **Run Script single-result** (⌘⇧⏎), **Run Script tab-per-statement** (⌘⌥⏎, ephemeral per-run **result tabs**; DDL/DML earn none). No transactions (Athena has none); statements never run in parallel. Detail: SPEC-078 + delivery doc.

## History

### 2026-07-03

- **Settled:** SPEC-078.

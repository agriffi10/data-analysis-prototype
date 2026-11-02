---
type: Decision
title: "State"
description: "TanStack Query owns server state and Context with `useReducer` owns UI state; Redux is not used."
---

TanStack Query owns server state (caching/invalidation); Context+`useReducer` owns UI state. No Redux. (SPEC-015)

## History

### 2026-07-08

- **Settled:** entered the register.

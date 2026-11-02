---
type: Decision Area
title: "The browser"
governs: [apps/portal/src/**]
---

The register's decisions on state split, dialogs, the shared-layer import rule, the measured palette, grid geometry, error wording.

TanStack Query for server state, Context + `useReducer` for UI state, no Redux. Mobile-first, with
only `tablet:` (≥900) and `desktop:` (≥1300) compiled; one tree reflows — a `*Mobile`/`*Desktop` twin
is a smell.

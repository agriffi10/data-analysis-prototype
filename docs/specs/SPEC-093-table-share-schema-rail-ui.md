---
type: Spec
id: SPEC-093
title: "Table Share — \"Share table\" UI (Query Schema Rail)"
description: "Adds a Share table action to the per-table menu in the Query schema rail, opening a modal where users choose users or shared spaces as recipients, name the resulting table and enqueue the request."
spec_status: Completed
depends_on: [SPEC-089, SPEC-044, SPEC-052, SPEC-063]
arc: table-share
arc_order: 6
---

**Dependency notes:** SPEC-089 (enqueue contract), SPEC-044 (schema-rail table options menu), SPEC-052 (`useConnections` — known spaces), SPEC-063 (schema-rail tree)
> **Read `docs/table-share-architecture.md` §1, §8 first.** Server-side validation (SPEC-089→092) owns eligibility; the UI is a thin, forgiving front door.

## Overview

Add a **"Share table"** action to the per-table options menu in the Query schema rail (SPEC-044), available on **any table in any database the user can browse**. It opens a modal to choose recipient kind (**users** or **shared spaces**), enter one or more recipient names, and name the **resulting table**; submitting enqueues a share request (SPEC-089) and shows a pending toast. Outcomes arrive via the notifications inbox (SPEC-094).

## Scope

### In Scope

- A **Share table** item in the SPEC-044 table options menu (base tables only; disabled/absent for **views**, matching the server rejection).
- A **Share modal**:
  - a **recipient-kind** toggle — **Users** vs **Shared spaces**;
  - a **multi-entry recipient** input (add several names; chips/removable; free-text; shared-space entries may offer typeahead from `useConnections`, but arbitrary names are allowed since any space is a valid target);
  - a **result table name** field (defaulted to the source table name; validated client-side against `CATALOG_IDENTIFIER_RE` for fast feedback);
  - source shown read-only (`database.table`).
- **Enqueue** via `enqueueTableShare` using the selected node's `database.table` + the chosen recipients + result name; a transient "Sharing '{table}'…" toast on submit; disable submit while sending.
- Accessible modal (focus trap, labels, keyboard) reusing the shared Modal/Dialog primitives; passes the SPEC-045 axe suite.

### Out of Scope

- Blocking/validating recipient existence or conflicts client-side — the server owns that (results come back as notifications, SPEC-094). The client only does the cheap catalog-name-format check.
- A progress/status view of the share — outcomes are notifications, not a live tracker.
- Sharing from the **file browser** — the entry point is the schema rail (a table is a catalog object, not a folder).
- Any data-layer/IAM/infra change beyond calling the SPEC-089 enqueue service.

---

## Functional Requirements

### FR-001: Share action in the table options menu

#### Acceptance Criteria:

- [ ] Every base table in the schema rail (any accessible DB) shows a **Share table** action in its options menu; views do not.
- [ ] Invoking it opens the Share modal preloaded with that table's `database.table` and a default result name = the source table name.

### FR-002: The Share modal

#### Acceptance Criteria:

- [ ] A recipient-kind toggle switches between **Users** and **Shared spaces**; the entered recipients are tagged with the selected kind.
- [ ] The recipient input accepts **multiple** names (removable chips); an empty list disables submit.
- [ ] The result-name field validates against `CATALOG_IDENTIFIER_RE`, showing inline guidance on a bad name and disabling submit until valid.
- [ ] Submit is disabled while a request is in flight; the modal is fully keyboard-operable and screen-reader-labeled (axe clean).

### FR-003: Enqueue + pending UX

#### Acceptance Criteria:

- [ ] Submitting calls `enqueueTableShare({ source, tableName, recipients })`; on success the modal closes and a "Sharing '{table}'…" toast appears.
- [ ] An enqueue failure (e.g. `sqs:SendMessage` error) surfaces a danger toast/banner and keeps the modal open with entered values intact.
- [ ] The UI makes no eligibility promises — copy notes that recipients will be notified and outcomes appear in notifications.

---

## Data Model

```ts
// features/table-share/ (new)
//   TableShareMenuItem.tsx   — menu entry (from SPEC-044 options menu)
//   TableShareDialog.tsx     — modal (kind toggle, recipient chips, result name)
//   useTableShare.ts         — wraps enqueueTableShare + toast + validation
//   tableShare.types.ts      — ShareRecipient, ShareFormState
// Reuses: Modal, Input, Badge/Chip, Button, Toast (SPEC-028), enqueueTableShare (SPEC-089),
//         CATALOG_IDENTIFIER_RE (query.constants), useConnections (SPEC-052, typeahead only).
```

## Implementation Phases

### Phase 1: Menu action + modal shell

- Add the Share item to the SPEC-044 options menu (base tables only); build the modal shell (source read-only, kind toggle) with a11y.

### Phase 2: Recipient entry + name validation + enqueue

- Multi-entry recipient chips (+ optional space typeahead from `useConnections`); catalog-name validation; wire `useTableShare` → `enqueueTableShare` + toasts.

### Phase 3: Completion ritual

- Delivery doc, INDEX status, component-inventory rows (`features/table-share`), and the SPEC-074 Help sweep (new user-facing "Share a table" guide).

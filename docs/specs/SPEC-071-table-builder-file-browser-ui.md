---
type: Spec
id: SPEC-071
title: "Table Builder — \"Create Table from this Folder\" (File Browser UI)"
description: "Lets users create a queryable table from a folder in the file browser by naming it and declaring any Hive partition keys, with the outcome delivered later to their notifications inbox."
spec_status: Completed
depends_on: [SPEC-067, SPEC-057, SPEC-066, SPEC-016, SPEC-028]
arc: table-builder
arc_order: 6
---

**Dependency notes:** SPEC-067 (request contract + portal-role `sqs:SendMessage` + `VITE_TABLE_BUILD_QUEUE_URL`), SPEC-057 (file-browser space model — `useFileSpace` / `FileSpaceTarget`: bucket/rootPrefix/kind/label), SPEC-066 (queue), SPEC-016/028 (dialog + UI primitives), `lib/sqsClient` + `lib/awsCredentials.getIdToken`
> **Reference:** `docs/table-builder-architecture.md` §1/§4/§5/§6. Sixth of the arc — the **only** browser
> surface. Adds a **"Create table from this folder"** action to the file browser that prompts for a table name
> **and (optionally) the partition keys**, then **enqueues** a create-table request (SPEC-067 contract) for the
> folder the user is viewing, in the database the current space maps to. Provisioning is async; the durable
> outcome arrives via notifications (SPEC-072). The browser only **sends** a message — it never creates the
> table. Follows the React/accessibility rulebooks (`docs/best-practices/INDEX.md`).

## Overview

Let users turn a folder of data files into a queryable table without leaving the file browser. While viewing a
folder in their personal space or a shared space (SPEC-057), the user clicks **"Create table from this folder"**,
is prompted for a **table name** and — if the data is Hive `key=value/` partitioned — for the **partition keys in
granularity order** (each with a projection type + range), and on confirm the app enqueues a request describing
the current **space + folder prefix + target database**, the name, and the declared `partitionKeys`, carrying the
caller's Cognito **ID token** (SPEC-067). A transient toast confirms the request was submitted; because creation
is asynchronous and validated server-side, the actual result (ready / failed-with-reason) is delivered to the
user's **notifications inbox** (SPEC-072) — the UI does not block or poll. Eligibility (data files present, single
supported format, name available, declared keys match the layout) is enforced **server-side**, so the button is
available for any folder and invalid cases come back as a clear notification rather than being pre-judged in the
browser. **Partition keys are always user-declared** (decided 2026-06-30) — the browser never auto-detects them;
an empty partition section means a flat (unpartitioned) table.

## Scope

### In Scope

- **"Create table from this folder" action** — a toolbar button in the file browser, acting on the **current
  folder** (the active `FileSpaceTarget` bucket + the current prefix). Available in both personal and shared
  spaces (for a shared space, only when the space is an **active** member space — same gating as browsing it,
  SPEC-057). Enabled at **any** folder, including the space root.
- **Table-name prompt dialog** — a `Modal`/`ConfirmDialog`-based prompt with an `Input`: validates the name
  **client-side** against `CATALOG_IDENTIFIER_RE` (lowercase, leading letter, `[a-z0-9_]`, 3–63 chars) with an
  inline error; pre-fills a **suggested name** derived from the folder name (sanitized to the rule); confirm is
  disabled until valid. Confirm = enqueue; Cancel/Escape closes.
- **Partition-keys section (optional)** — within the same dialog, an **"Add partition keys"** affordance reveals an
  **ordered, removable list** of key rows (order = **granularity, coarsest first**, with reorder controls + helper
  text). Each row collects: **name** (`Input`, validated `CATALOG_IDENTIFIER_RE` + unique), **type** (`Select`:
  Integer / Date / String), and the type's projection config — Integer → min/max (+ optional digit width); Date →
  range start/end (`NOW` allowed) + format (e.g. `yyyy-MM-dd`); String → comma-separated **values** (enum). Empty
  section = **flat table** (no keys sent). Helper copy warns that values outside a declared integer/date range are
  excluded from query results (architecture §10). Confirm is disabled until the name **and** every key row are
  valid. (Reuse shared `Input`/`Select`/`Button` primitives; follow the accessibility rulebook for the dynamic
  field list — labelled rows, focus management on add/remove.)
- **Enqueue service** — `tableBuild.service.ts` `enqueueTableBuild({ space, prefix, tableName, partitionKeys })`
  that builds the SPEC-067 envelope (incl. `partitionKeys`, `[]` when flat), attaches the **ID token**
  (`getIdToken`), and `SendMessage`s to `VITE_TABLE_BUILD_QUEUE_URL` via `getSqsClient` — **FIFO**:
  `MessageGroupId = space.database`, `MessageDeduplicationId = requestId` (a generated id). Returns
  `ServiceResult<void>` (never throws; the services convention).
- **Space → request mapping** — derive `space` from the active `FileSpaceTarget` (SPEC-057): `kind`, `bucket`,
  `database` = the space label (personal username | shared name), and `prefix` = the current folder key; the
  `location` is computed server-side (SPEC-067) — the browser sends bucket+prefix+database.
- **Submit feedback** — on success, a `Toast` ("Creating table '{name}'… you'll be notified when it's ready");
  on a send error (e.g. SQS failure), a `Banner`/`Toast` error. No blocking spinner, no result polling.
- **Tests** — name validation + suggestion; the enqueue service builds the correct envelope (incl. token,
  `MessageGroupId`, dedup id) and surfaces a `ServiceResult`; the button/dialog flow (open → invalid blocks →
  valid enqueues → toast); the action respects the active space (personal vs shared) + current prefix.

### Out of Scope

- **All server-side work** (validation, inspection, inference, DDL execution, notifications) — SPEC-067→070, 072
  (the browser only enqueues; it does not detect data files or schema).
- **A pre-flight "is this folder eligible?" check** in the browser — eligibility is server-side (button always
  enabled); a future enhancement could grey it out by peeking contents.
- **A progress/status surface** for in-flight builds beyond the submit toast — the outcome is the notifications
  inbox (SPEC-072); a dedicated "table builds" status list is out of scope.
- **Editing/refreshing the schema rail** when a table is created — the schema rail picks it up on its normal
  refresh (SPEC-046/063); no live push here.

---

## Functional Requirements

### FR-001: The action

#### Acceptance Criteria:

- [ ] The file browser shows a **"Create table from this folder"** action (toolbar button, labelled + accessible)
  acting on the current `FileSpaceTarget` + prefix; it appears in the personal space and in **active** shared
  spaces (not for `provisioning`/`failed` spaces, which aren't selectable anyway, SPEC-057). It is available at
  **any** folder, **including the space root** (eligibility is enforced server-side, SPEC-067/068).
- [ ] Activating it opens the table-name prompt (FR-002); it does not navigate away or block the browser.

### FR-002: Table-name prompt + validation

#### Acceptance Criteria:

- [ ] The dialog has an `Input` pre-filled with a **suggested** name derived from the current folder name,
  sanitized to `CATALOG_IDENTIFIER_RE` (lowercase, non-conforming chars → `_`, trimmed to length, leading letter
  ensured); the user can edit it.
- [ ] The name is validated **client-side** against `CATALOG_IDENTIFIER_RE` with an inline error; **Confirm** is
  disabled until valid (the server re-validates authoritatively, SPEC-067 — client validation is UX only).
- [ ] An **optional partition-keys section** lets the user add ordered key rows (granularity order, coarsest
  first; reorder + remove controls). Each row validates **name** (`CATALOG_IDENTIFIER_RE` + unique), **type**
  (Integer/Date/String), and the type's config (integer min<max; date format non-empty; string ≥1 value), with
  inline errors. An empty section sends **no** partition keys (flat table). **Confirm** stays disabled until the
  name and **all** key rows are valid.
- [ ] Cancel/Escape/backdrop closes without sending; the dialog traps focus and is screen-reader-labelled, and the
  dynamic key rows manage focus on add/remove (accessibility rulebook).

### FR-003: Enqueue service

#### Acceptance Criteria:

- [ ] `enqueueTableBuild({ space, prefix, tableName, partitionKeys })` builds the SPEC-067 envelope `{ idToken,
  space:{kind, bucket, prefix, database}, tableName, partitionKeys, requestId }` (`partitionKeys` defaults to
  `[]`), fetches the ID token via `getIdToken`, and `SendMessage`s to `VITE_TABLE_BUILD_QUEUE_URL` via
  `getSqsClient` with **`MessageGroupId = space.database`** and **`MessageDeduplicationId = requestId`**.
- [ ] It returns `ServiceResult<void>` and **never throws** (SQS/credential errors → `{success:false,error}`);
  it goes through the credential-retry helper like the other authenticated services.
- [ ] It is the **only** new browser AWS call; the portal role's `sqs:SendMessage` grant (SPEC-067) is what
  authorizes it; no other table-builder permission is used client-side.

### FR-004: Submit feedback

#### Acceptance Criteria:

- [ ] On a successful send, the dialog closes and a `Toast` confirms submission ("Creating table '{name}'… you'll
  be notified when it's ready"); the file browser is otherwise unchanged (no blocking state).
- [ ] On a send failure, the user sees a clear error (`Toast`/`Banner`) and can retry; no silent failure.
- [ ] The UI does **not** poll for the build result — the outcome is delivered via notifications (SPEC-072).

### FR-005: Tests + lint

#### Acceptance Criteria:

- [ ] `npm run test` + `npm run lint` pass; tests cover: name suggestion from a folder name + client validation
  (valid/invalid); **partition-keys section** — add/remove/reorder rows, per-row name+type+config validation
  (integer min<max, date format required, string ≥1 value, duplicate name blocked), empty section → `[]`;
  `enqueueTableBuild` builds the correct envelope (token attached, **`partitionKeys` included**, `MessageGroupId`
  = database, dedup id present) for both a flat and a partitioned request and returns a `ServiceResult` on success
  + on a stubbed SQS error; the dialog flow (open → invalid blocks Confirm → valid sends → toast); the action uses
  the **active space** (personal vs shared) + current prefix; no axe violations in the dialog incl. the dynamic
  key rows (SPEC-045 suite).

---

## Data Model

```ts
// apps/portal/src/features/table-builder/tableBuild.types.ts (NEW)
export type PartitionKey =
  | { name: string; type: 'integer'; range: [number, number]; digits?: number }
  | { name: string; type: 'date'; range: [string, string]; format: string; interval?: number; intervalUnit?: string }
  | { name: string; type: 'string'; values: string[] };   // → Athena projection enum

export type TableBuildRequest = {
  space: { kind: 'personal' | 'shared'; bucket: string; prefix: string; database: string };
  tableName: string;
  partitionKeys: PartitionKey[];   // [] = flat (unpartitioned); order = granularity, coarsest first
};
// The wire envelope (SPEC-067) adds idToken + requestId, set inside the service.
```

## API / Interface Contract

```ts
// apps/portal/src/features/table-builder/tableBuild.service.ts
export function enqueueTableBuild(req: TableBuildRequest): Promise<ServiceResult<void>>;
// Builds { idToken: await getIdToken(), space, tableName, partitionKeys: req.partitionKeys ?? [],
//          requestId: crypto.randomUUID() },
// SendMessage to VITE_TABLE_BUILD_QUEUE_URL via getSqsClient,
// MessageGroupId = req.space.database, MessageDeduplicationId = requestId.

// Derive the request space from the active FileSpaceTarget (SPEC-057) + current prefix:
//   { kind, bucket, prefix: currentPrefix, database: spaceTarget.label }
```

## Environment Variables

```
# apps/portal/.env.example
VITE_TABLE_BUILD_QUEUE_URL=<table-build FIFO queue URL>   # exported SPEC-066, granted SPEC-067
```

## File & Folder Structure

```
apps/portal/src/features/table-builder/
├── CreateTableButton.tsx        ← toolbar action (current folder) → opens the dialog
├── CreateTableDialog.tsx        ← name prompt + partition-keys section: suggestion + CATALOG_IDENTIFIER_RE validation + confirm→enqueue
├── PartitionKeysField.tsx       ← ordered key rows (name + type + projection config); add/remove/reorder + validation
├── CreateTableDialog.test.tsx   ← NEW
├── tableBuild.service.ts        ← enqueueTableBuild (envelope + idToken + partitionKeys + FIFO send) → ServiceResult
├── tableBuild.service.test.ts   ← NEW
├── tableBuild.types.ts          ← TableBuildRequest + PartitionKey
└── index.ts                     ← barrel

apps/portal/src/features/file-browser/
└── FileBrowser.tsx              ← mount CreateTableButton in the toolbar (current space + prefix)
apps/portal/.env.example         ← + VITE_TABLE_BUILD_QUEUE_URL
```

## Implementation Phases

### Phase 1: Service + dialog

- `tableBuild.service.enqueueTableBuild` (envelope + token + `partitionKeys` + FIFO send, `ServiceResult`);
  `CreateTableDialog` (name suggestion + validation + confirm) + `PartitionKeysField` (ordered rows, per-type
  projection config, validation) (FR-002, FR-003).

### Phase 2: Button + feedback + wiring

- `CreateTableButton` in the file-browser toolbar wired to the active space + current prefix; success/error toast;
  `.env.example`; tests + a11y (FR-001, FR-004, FR-005).

# Spec: Refresh Table — Menu Item, Dialog & Notifications

**ID:** SPEC-145
**Status:** Draft
**Last Updated:** 2026-08-03
**Depends On:** SPEC-143 (the `mode` field, the `TableBuildSpace` type, and the eligibility rules the dialog's copy must match), SPEC-144 (`allowRemovals`, the `columns_removed` outcome, and the notification **link** this spec parses), SPEC-044 (`TableActionsMenu` and the `TableActions` prop contract), SPEC-067 (`enqueueTableBuild` and `VITE_TABLE_BUILD_QUEUE_URL`), SPEC-060 (the notifications surface these outcomes arrive on)

> **Reference:** third and last of the refresh-table arc (143 → 144 → **145**). This is the only spec in the arc a user can see.
>
> **Browser-side only: no new IAM, no new AWS call, no new Lambda change, no new env var.** The portal role already holds `sqs:SendMessage` on the table-builder request queue (SPEC-067), the queue URL is already wired, and `enqueueTableBuild` already sends the envelope this spec extends.
>
> **Two things a reader will assume and should not.** First, **a `Notification` carries no structure** — it is `{id, message, read, timestamp, link?}` and nothing else, so the dialog cannot "read the outcome" out of the inbox. What it *can* read is the `link` SPEC-144 FR-009 mints, whose query string names the removed columns. FR-003 is built on that and on nothing else. Second, **`useTableShare` is not the shape it sounds like** — it lives in `features/table-share/`, is constructed as `useTableShare(notify)`, returns `{target, busy, error, open, close, submit}` rather than a single state object, and its `open` takes **`(database: string, table: string)`** — the table as a name string, not a `GlueTableSummary`. This spec follows that shape rather than a tidied-up version of it (its own `open` takes the summary because FR-004 needs `location`).
>
> **Design:** the menu item follows SPEC-044's existing item pattern; the dialog follows SPEC-026's confirm pattern and reuses `ConfirmDialog`'s `busy` / `busyLabel` / `confirmDisabled` / `irreversible` affordances. No new design pass is needed.

## Overview

The pipeline is built; this is the button. A **Refresh table** item joins the table options menu in the Query schema rail, opens a confirmation dialog explaining what a refresh will and will not do, and enqueues the request. The outcome arrives as a notification, as every other control-plane outcome does.

The interesting part is the removals confirmation. SPEC-144 refuses a refresh that would remove columns, names them in the notification, and attaches an in-app link carrying those names. So the dialog has two modes. Opened normally, it offers an unchecked **Allow columns to be removed** box with explicit consequence copy — the user is told what removal means before they can tick it, and confirm stays disabled until they do. Opened from the notification's link, it additionally names the specific columns, so the confirmation is against `legacy_id` and `region_code` rather than against an abstraction.

The box is present in both modes rather than only in the second, and that is a deliberate trade. Hiding it until the user has been blocked once would guarantee the names are always shown, but it would also mean that a user who *knows* a column is going away has to trigger a failed run to get the option — and the failed run's notification is the only thing that would tell them why. An always-present, always-unchecked box with honest copy is the better shape; the guarantee it gives up is one SPEC-144 FR-003 already declines to overclaim.

---

## Scope

### In Scope

- **A `Refresh table` item** in the table options menu, built in `DatabaseNode.tsx`, hidden for views and disabled for a table with no `location`.
- **`RefreshTableDialog`** — a confirm dialog with the always-present removals opt-in and the link-borne column names when available.
- **`useTableRefresh(notify)`** — dialog state, enqueue and toasts, following `useTableShare`'s actual shape.
- **`enqueueTableRefresh`** in `tableBuild.service.ts` — a thin wrapper over the existing FIFO send with `mode: 'refresh'`.
- **Deriving `space` from `GlueTableSummary.location`**, which is the only place in the Query workspace that knows where a table's files live.
- **Parsing SPEC-144's `columns_removed` link** off the URL, with every name re-validated.
- **Toasts** for enqueue accepted and enqueue failed, per the SPEC-044 drop-table precedent.
- **A schema-rail invalidate** when a refresh outcome arrives, so the rail's columns update.
- **Help & guides content** — the first user-visible thing in the arc, so SPEC-074's sweep lands here.
- **Responsive and accessibility** coverage at 400px with `vitest-axe` assertions.

### Out of Scope

- **A schema preview or diff view in the browser.** SPEC-144 FR-003 records why this cannot be built without a synchronous inference path that does not exist. The dialog explains; it does not predict.
- **Changing the `Notification` type or the notifications pipeline.** If this spec adds a field to a notification, it has gone wrong — SPEC-144 owns the message layer and already added the link.
- **A progress indicator beyond the enqueue toast.** The control plane is fire-and-forget; the notification is the completion channel (SPEC-114). Do not add polling.
- **A refresh entry point anywhere but the table options menu.**
- **Refreshing more than one table at a time.**
- **Persisting anything.** No writes to `user_settings/`, no `localStorage`, no remembered opt-in.

---

## Functional Requirements

### FR-001: The menu item

#### Acceptance Criteria:

- [ ] `TableActions` gains `onRefreshTable: (database: string, table: GlueTableSummary) => void`. Note the existing member `canViewSourceFiles` is **`(table: GlueTableSummary) => boolean`**, not a boolean — the new member is added without disturbing it.
- [ ] `DatabaseNode.tsx`'s `TableRow` renders a `refresh` item labelled **Refresh table**, positioned after `view-data` and before the `share` item.
- [ ] The item is **omitted** when `tableType === 'VIRTUAL_VIEW'`, exactly as `share` is.
- [ ] The item is **disabled** when `table.location` is absent, because FR-004 cannot build a request without it. The disabled reason is not surfaced as an error; the item simply does not act.
- [ ] Otherwise the item is present for every table in every database the rail shows, personal and shared alike. The browser does not attempt SPEC-143's eligibility checks; the server is the authority and its refusals carry user-facing wording (SPEC-144 FR-009). A comment records this division so a later reader does not add a client-side gate that drifts.
- [ ] `QueryWorkspace.tsx` wires `onRefreshTable` to the hook's `open`.
- [ ] The menu's existing keyboard behaviour, roving focus and `aria-label` are unchanged; the new item is reachable by arrow keys and Enter.

### FR-002: The dialog explains what a refresh does

#### Description

The copy is the feature's honesty budget. A user clicking Refresh should not be surprised afterwards, and there are four things worth saying because each has surprised somebody in a comparable tool.

#### Acceptance Criteria:

- [ ] The dialog names the database and table it will refresh, and the S3 location the table points at, so a user can confirm it is the folder they just added files to.
- [ ] The body states that the table's **files are not modified** and that only the table's column list is updated.
- [ ] The body states that **partition keys are not changed**, and that changing them means creating the table again.
- [ ] The body states that the table is **briefly unavailable** while it is rebuilt.
- [ ] The body states that the **result arrives as a notification**, not in the dialog.
- [ ] Confirm is labelled **Refresh table**; the dialog uses `ConfirmDialog`'s `busy` / `busyLabel` while the enqueue is in flight and is not dismissible during it.
- [ ] Escape and the backdrop dismiss when not busy; focus is trapped and returns to the menu trigger on close.
- [ ] `vitest-axe` reports no violations in the plain and link-borne dialog states.

### FR-003: The removals opt-in

#### Description

Always present, never remembered, always explicit — with the specific column names shown when SPEC-144's link supplied them.

#### Acceptance Criteria:

- [ ] The dialog renders a checkbox labelled to name the consequence: that removed columns are dropped from the table and any query or view referencing them will stop working.
- [ ] The checkbox is **unchecked on every open.** It is never remembered, never defaulted, never pre-checked because a previous attempt was blocked.
- [ ] Confirm is **enabled** with the checkbox unchecked — an additive refresh is the common case and must not require ticking anything. `allowRemovals` is simply omitted from the request.
- [ ] When the dialog was opened from a `columns_removed` link, it **additionally** renders the column names the link carried, above the checkbox, with wording explaining that a previous refresh was stopped because these columns are no longer in the data.
- [ ] In that link-borne state, confirm is **disabled until the checkbox is ticked** via `ConfirmDialog`'s `confirmDisabled` — the user arrived here because a removal is pending, so proceeding without acknowledging it is not a meaningful action.
- [ ] Nothing is persisted on any path — a test asserts no write to `user_settings/` and no `localStorage` access occurs in this feature.

### FR-004: Building the request

#### Description

The Query workspace has no `space` object. `Connection` carries `database` and `kind` only, and `tablePrefix()` returns `null` for any table outside the user's own prefix — i.e. for every shared-space table, which FR-001 says must show the item. The one thing that does know is `GlueTableSummary.location`, which `glue.service.ts` already maps from `StorageDescriptor.Location`.

#### Acceptance Criteria:

- [ ] A pure helper parses `s3://{bucket}/{prefix}` from `table.location` into `{bucket, prefix}`, normalising a missing trailing slash, and returns `null` on anything unparseable.
- [ ] `space` is assembled as `{kind, bucket, prefix, database}` — `kind` and `database` from the rail's connection, `bucket` and `prefix` from the parsed location. The prefix is what SPEC-143 FR-002 authorizes and SPEC-143 FR-004 then re-checks against the catalog, so a stale rail cache cannot widen access.
- [ ] `enqueueTableRefresh(req)` builds the envelope with `mode: 'refresh'`, `partitionKeys: []`, and — matching `enqueueTableBuild` — mints `requestId` and attaches the ID token **inside the service**, not on the request type.
- [ ] `allowRemovals` is included only when `true`; the field is absent otherwise.
- [ ] The send goes through the existing `enqueueFifoRequest` helper with `MessageGroupId = space.database` and `MessageDeduplicationId = requestId`.
- [ ] The service returns `ServiceResult<void>` and never throws.
- [ ] On success the dialog closes and a toast reads that the refresh has started and the result will arrive in notifications.
- [ ] On failure the dialog stays open and surfaces the error through `toUserMessage` — never `error.message` (SPEC-106).
- [ ] The queue URL is read from `import.meta.env` **at call time**, not at module load.
- [ ] A test asserts the envelope shape field by field, including `partitionKeys: []` and the location-derived bucket and prefix.

### FR-005: The link, and the rail update

#### Description

Two consumers of the notification, both narrow. The link is parsed from the URL, not from the inbox; the rail invalidation is driven by the user returning to the workspace, not by inspecting notification text.

#### Acceptance Criteria:

- [ ] `/query?refreshTable={database}.{table}&removed={names}` opens the refresh dialog for that table, in the link-borne state, with the parsed names.
- [ ] `database` and `table` are validated against `CATALOG_IDENTIFIER_RE` on read; a failure means the query parameters are ignored entirely and the workspace renders normally. The link is user-controllable text in a URL and is treated as such.
- [ ] **`removed` names are NOT validated against `CATALOG_IDENTIFIER_RE`, and must not be.** *(Corrected while building SPEC-144, 2026-08-04.)* Column names are **not** catalog-safe: `infer-schema` takes them verbatim from a CSV header or a polars schema and `load-table-definition` copies them out of Glue, so nothing in the plane ever validates them. `CATALOG_IDENTIFIER_RE` (`^[a-z][a-z0-9_]{2,62}$`) rejects `id`, `ts`, `Amount` and `first name` — all ordinary column names — so applying it here would discard the **whole** link for most real tables and silently fall back to the abstract copy, defeating the criterion below. SPEC-144 percent-encodes each name individually; decode them, cap at 20, and render them as **text** (never as HTML, never re-used as an identifier).
- [ ] A `refreshTable` naming a database or table the rail does not have opens nothing and shows nothing — no error, no empty dialog.
- [ ] The query parameters are cleared from the URL once consumed, so a reload does not reopen the dialog.
- [ ] **The rail invalidation is deliberately coarse:** on a successful enqueue, and again when the Query route regains focus after the dialog was used, `invalidateSchema(queryClient, database)` is called for the affected database. It does **not** try to detect the outcome, because the notification carries no structure to detect it with, and a stale rail after a successful refresh is the same bug this feature exists to fix.
- [ ] Invalidation is bounded — a test asserts repeated focus events do not invalidate more than once per dialog use.

### FR-006: Help and guides

#### Acceptance Criteria:

- [ ] `helpContent.ts` gains a guide for refreshing a table: where the action is, what it updates, that files are untouched, that partition keys are not changed, that the result arrives as a notification, what happens when columns are removed and how to proceed, and that views and catalog-partitioned tables cannot be refreshed.
- [ ] The guide documents only behaviour shipped and wired end to end (SPEC-074 FR-005) — written after 143 and 144 have merged.
- [ ] The existing Table Builder guide is amended to point at it, since "the table is missing my new columns" is the question that brings a user to either page.

### FR-007: Responsive

#### Acceptance Criteria:

- [ ] The dialog reflows on one tree using `tablet:` / `desktop:` only, per SPEC-095; a `*Mobile` twin is a smell.
- [ ] At 400px the dialog is viewport-capped with the panel scrolling, the column list scrolls rather than pushing the confirm control off-screen, and the checkbox and its label have a full-width touch target.
- [ ] `useIsMobile` is used for mount-gating only, never for styling.

### FR-008: Tests and lint

#### Acceptance Criteria:

- [ ] `npm run test` and `npm run lint` pass.
- [ ] Tests cover: the item present for a table, absent for a view, disabled with no `location`; the location parser including the unparseable case; the envelope shape for both `allowRemovals` states; the plain dialog with confirm enabled and the box unchecked; the link-borne dialog with names rendered and confirm disabled until ticked; the box never pre-checked; every link-validation rejection; the URL cleared after consumption; the failure path keeping the dialog open with a `toUserMessage` string; the bounded invalidation; and `vitest-axe` clean in both dialog states.
- [ ] Tests are integration-style per the repo rule — render the real hook and children, mock only the AWS service boundary, via `renderWithProviders`.

---

## Data Model

```ts
// apps/portal/src/features/table-builder/tableRefresh.types.ts — NEW

import type { TableBuildSpace } from './tableBuild.types';       // named by SPEC-143
import type { GlueTableSummary } from '../query/query.types';

export type TableRefreshRequest = {
  space: TableBuildSpace;
  tableName: string;
  /** Omitted unless the user ticked the opt-in. */
  allowRemovals?: boolean;
};

/** Parsed from SPEC-144's notification link. Never stored. */
export type PendingRemoval = {
  database: string;
  tableName: string;
  columns: string[];
};

export type TableRefreshTarget = {
  database: string;
  table: GlueTableSummary;
  /** Present ⇒ opened from a columns_removed link; render the names, gate confirm. */
  pending: PendingRemoval | null;
};
```

---

## API / Interface Contract

```ts
// apps/portal/src/features/table-builder/tableBuild.service.ts — extended
export async function enqueueTableRefresh(
  req: TableRefreshRequest,
): Promise<ServiceResult<void>>;

// apps/portal/src/features/table-builder/tableRefresh.location.ts — pure
export function parseTableLocation(
  location: string | undefined,
): { bucket: string; prefix: string } | null;

// apps/portal/src/features/table-builder/useTableRefresh.ts
// Follows useTableShare's ACTUAL shape — flat fields, a notify callback, not a
// single state object — so the two dialogs in the same menu are wired alike.
// The notify signature matches useTableShare's exactly, so both are wired as
// `useTableRefresh(toast.push)` in QueryWorkspace.
export function useTableRefresh(
  notify: (t: { variant: 'success' | 'error'; message: string }) => void,
): {
  target: TableRefreshTarget | null;
  busy: boolean;
  error: string | null;
  open: (database: string, table: GlueTableSummary, pending?: PendingRemoval) => void;
  close: () => void;
  submit: (allowRemovals: boolean) => Promise<void>;
};

// apps/portal/src/features/query/SchemaBrowser.tsx — TableActions gains one member.
// Reproduced in full because canViewSourceFiles is a FUNCTION, and a spec that
// quoted it as a boolean would send an implementer to change the wrong thing.
export type TableActions = {
  onViewSourceFiles: (database: string, table: GlueTableSummary) => void;
  onViewDdl: (database: string, table: GlueTableSummary) => void;
  onViewData: (database: string, table: GlueTableSummary) => void;
  onRefreshTable: (database: string, table: GlueTableSummary) => void; // NEW
  onShareTable: (database: string, table: GlueTableSummary) => void;
  onDropTable: (database: string, table: GlueTableSummary) => void;
  canViewSourceFiles: (table: GlueTableSummary) => boolean;
};
```

## Environment Variables

None. `VITE_TABLE_BUILD_QUEUE_URL` already exists and already points at the queue this feature sends to.

## File & Folder Structure

```
apps/portal/src/features/
├── table-builder/
│   ├── RefreshTableDialog.tsx           # NEW
│   ├── RefreshTableDialog.test.tsx      # NEW
│   ├── RefreshTableDialog.a11y.test.tsx # NEW
│   ├── useTableRefresh.ts               # NEW
│   ├── useTableRefresh.test.ts          # NEW
│   ├── tableRefresh.types.ts            # NEW
│   ├── tableRefresh.location.ts         # NEW — pure s3:// parser
│   ├── tableRefresh.location.test.ts    # NEW
│   ├── tableBuild.service.ts            # + enqueueTableRefresh
│   └── index.ts                         # + barrel exports
├── query/
│   ├── DatabaseNode.tsx                 # + the refresh menu item
│   ├── SchemaBrowser.tsx                # + onRefreshTable on TableActions
│   └── QueryWorkspace.tsx               # + wiring, + link consumption, + invalidation
└── help/
    └── helpContent.ts                   # + the refresh guide, + the Table Builder cross-link
```

## Implementation Phases

### Phase 1: Service, parser and hook

- `parseTableLocation`, `enqueueTableRefresh`, `tableRefresh.types.ts`, `useTableRefresh`.
- **Tests:** the parser including unparseable input; the envelope for both `allowRemovals` states; call-time env read; failure returns a `ServiceResult` error.

### Phase 2: Dialog and menu

- `RefreshTableDialog` in both states; the menu item and its `TableActions` wiring, including the disabled-without-location case.
- **Tests:** item present/absent/disabled; both dialog states and their confirm gating; the box never pre-checked; axe clean.

### Phase 3: Link consumption, invalidation, responsive, completion

- The `/query?refreshTable=…&removed=…` parse with full re-validation and URL clearing.
- The bounded schema invalidation.
- Responsive pass at 400px.
- Help content (FR-006).
- Completion ritual for the spec **and the arc**: `INDEX.md` statuses, delivery doc, component-inventory rows in `table-builder-feature.md` and `query-feature.md`, and — since 143's shape-not-marker eligibility rule and 144's removal opt-in are both genuinely new architectural decisions — confirm their `decisions.md` entries and one-line `CLAUDE.md` rows are in place, then prune `CLAUDE.md`'s Current-work block of everything the arc made stale.

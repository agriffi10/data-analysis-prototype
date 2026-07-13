# Spec: Data Quality — Runs Dashboard (the parent page)

**ID:** SPEC-123
**Status:** Draft
**Last Updated:** 2026-07-13
**Depends On:** SPEC-112 (`assemble-report` — this spec adds the index write to it), SPEC-113 (the report view this drills into), SPEC-114 (notifications), SPEC-085 (side nav), SPEC-095 (responsive), SPEC-045 (a11y), SPEC-106 (error messaging), SPEC-074 (help)

> Dependency note: this spec has **no direct `cpcommon` dependency** — its Lambda-side work rides `dqcommon` (`index_store`) inside the already-shipped `assemble-report` verb; everything else is browser-side. SPEC-107's absence from Depends On is deliberate.

> **Read `docs/data-quality-architecture.md` §6 first.** This spec closes a real gap: today a report is reachable **only** from its notification, so a dismissed notification effectively loses the report.

## Overview

A **Data quality** destination in the app's navigation, listing every quality check the user can see — newest first, paginated — with a click through to the full report (SPEC-113).

The storage model is the one the arc already uses: **a hidden folder of JSON, one object per run.** What is missing is an **index**, and it is missing for a concrete reason.

**Why the obvious implementation does not work.** Listing `{space}/_data-quality-reports/` and fetching each `report.json` to build a row means **one S3 GET per row**, and — worse — S3 lists **lexicographically by key**, so ordering by `requestId` (a UUID) yields **no chronology whatsoever**. A "recent checks" page would return runs in effectively random order. Sorting properly would require fetching *every* report in the space on every page load, at which point the page gets slower the more the feature is used.

**So each run also appends a small entry to a per-space `index.json`.** One GET renders the whole list. The entry carries only what a row needs; the heavy findings stay in the per-run report, fetched on drill-down.

**The write is a read-modify-write, and it races.** Two checks of *different* locations run in parallel (the request queue's `MessageGroupId` is the hashed location, so only same-location checks serialize), which means two `assemble-report` invocations can append to the same `index.json` at once and one would silently lose the other's entry. This is the **same lost-update race SPEC-082 already fixed** in the shared-space registry, with the **same fix**: optimistic **ETag compare-and-swap with retry**. It is a precedented pattern in this codebase, not a new one.

## Scope

### In Scope

- **`assemble-report` appends an index entry** to `{space}/_data-quality-reports/index.json`, with **ETag CAS + bounded retry** and a **capped** entry count.
- A **`/data-quality` list page**: every check the user can see, **newest first**, paginated 10 per page, with a verdict chip and a filter.
- The page **aggregates across spaces** — the user's personal space plus every shared space they belong to — so it is "my checks", not "checks in one folder".
- **Navigation**: a primary nav entry at `tablet:`/`desktop:` and an `AppNavDrawer` destination on mobile.
- **Responsive** (SPEC-095), **a11y** (SPEC-045), **error wording** (SPEC-106), **help content** (SPEC-074).

### Out of Scope

- **Failed checks.** A run that fails before `assemble-report` never writes an index entry, so the dashboard lists **completed checks only** — accepted by the user on 2026-07-12, **on one explicit condition: a failed check must always reach the user with a concrete reason.** That condition is not a hope; it is discharged by **SPEC-114 FR-004** (a dedicated `NotifyFailure` state on the failure path, so notification does not depend on the failing verb being able to emit it — it survives a Lambda import error and a Step Functions-level error) and **SPEC-114 FR-005** (DLQ and `ExecutionsFailed` alarms for the residual class where *nothing ran*, so no notification is possible at all). **SPEC-123 must not ship before SPEC-114 FR-004 and FR-005 do** — without them, "completed checks only" degrades into a list that lies by omission.
- **Deleting a check from the dashboard.** The pipeline holds no `s3:DeleteObject`; the user's own role can delete the report objects, but a delete affordance here would need to also rewrite the index under CAS, and the value is low. Deferred.
- **Any new shared component.** The page is `PageLayout` + the existing row/pager/filter primitives, exactly as SPEC-113 FR-007 requires of the report view.
- A converter runs dashboard. If this pattern proves useful, that is a follow-up — but symmetry is not a reason to build a second one now.
- Cross-space search or filtering by column/finding. The list filters by verdict only.

---

## Functional Requirements

### FR-001: The index object, written under CAS

#### Description

**This FR owns the whole mechanism**: `dqcommon.index_store`, the ETag-CAS read-modify-write, the `DQ_INDEX_MAX_ENTRIES` and `DQ_INDEX_CAS_RETRIES` constants, **and the amendment of the shipped `assemble-report` verb** to call it — mirroring the SPEC-072 precedent of amending the shipped `execute-ddl` verb. SPEC-112 FR-004 deliberately left only a documented seam (report-before-index ordering; a summary payload carrying everything an entry needs); everything past that seam is delivered — and tested — here.

#### Acceptance Criteria:

- [ ] On a successful check, `assemble-report` (SPEC-112, amended here) **appends an entry** to `{space}/_data-quality-reports/index.json` and writes the entry **after** the report object, so the index never references a report that does not exist.
- [ ] The entry is `{ requestId, location, format, verdict, fileCount, hasApproximateFigures, timestamp }` — **and nothing else** (`timestamp` = the report's `completedAt`, SPEC-112 FR-003). A comment records why it is deliberately small: this file is fetched on every dashboard load, and putting findings in it would make the list page pay for detail it does not render.
- [ ] The write is a **read-modify-write under optimistic ETag CAS**, retried on a mismatch — the same mechanism as the shared-space registry (SPEC-082, `lambdas/shared-space-common/registry.py`). A comment records the race it prevents: checks of **different** locations run in parallel (the queue serializes only same-location checks), so two `assemble-report` invocations can append at once and one would **silently lose the other's run**.
- [ ] A test runs two concurrent appends and asserts **both entries survive**.
- [ ] The index is capped at `DQ_INDEX_MAX_ENTRIES` (default **200**), oldest entries dropped first. A comment records why: an uncapped index grows forever and the dashboard's single GET gets slower the more the feature is used — the exact failure the index exists to avoid.
- [ ] Exhausting the CAS retries is **logged and swallowed** — it does **not** fail the check. The report is written and the notification still fires; the run is simply missing from the dashboard. A comment records this ordering: **the report is the artefact, the index is a convenience**, and a convenience must never fail the thing it indexes.
- [ ] A missing or unparseable `index.json` is treated as an **empty index** and rebuilt, never as an error.

### FR-002: The list page

#### Acceptance Criteria:

- [ ] Route **`/data-quality`**, inside `<ProtectedLayout>`, rendered with `PageLayout` (title "Data quality", `contentClassName="max-w-[920px] gap-2"`, `stackActionsOnMobile`) — so it is the `<main id="main">` landmark. Route wrapper is a thin `routes/DataQualityPage.tsx` re-export, per the Notifications convention.
- [ ] It reads `index.json` from the user's **personal space and every shared space they belong to**, in parallel (TanStack Query), **merges** the entries, and sorts **newest first**. A comment records why it aggregates rather than making the user pick a space first: this is "my checks", and forcing a space selection before showing anything makes the common case (one personal space) worse for no gain.
- [ ] A space whose index cannot be read (deleted, permissions changed) is **skipped with a logged warning** — one unreadable space never blanks the whole page. A test asserts a partial failure still renders the readable spaces.
- [ ] **No new IAM** — the existing membership-tag read policy already covers `{space}/_data-quality-reports/index.json` (and the personal-prefix grant covers the personal one); the implementation plan confirms it.
- [ ] **Pagination is client-side, 10 per page**, using the existing `Pager` — the same shape as `NotificationsPage.tsx:15,46-56`, including the clamped page index and the `{start+1}–{end} of {total}` label with its `sr-only` page number.
- [ ] A **filter** (All / Issues found / Clean) uses the existing segmented control pattern (`NotificationsPage.tsx:174-198`): `role="group"`, `aria-pressed` on each button, active state `bg-surface font-semibold text-accent-text shadow-sm`. The filter resets the page index.
- [ ] A **refresh** `IconButton` re-fetches; its busy state is the existing `animate-spin` SVG, not a new spinner component.

### FR-003: The row

#### Acceptance Criteria:

- [ ] Each row is a link to `/data-quality/{space}/{requestId}` (SPEC-113). The **whole row** is the link target, and its accessible name names the location — never "view" or "here".
- [ ] The row shows: the **location** (`font-mono`, truncated from the left so the *folder* stays visible when the path is long), the **space** it belongs to, **when** it ran, the **file count**, and a **verdict chip**.
- [ ] The verdict chip follows the `ConnectionsPage.tsx:506-520` `StatusBadge` pattern — a `bg-current` dot **plus a text label** (`Clean` / `Issues found`), tone `bg-success-soft text-success` / `bg-warning-soft text-warning`. **Never colour-only.**
- [ ] When `hasApproximateFigures` is true, the row also carries a **`Sampled`** chip. A test asserts a sampled run **never renders as an unqualified `Clean`** — the same rule SPEC-112 and SPEC-114 enforce, applied at the list level, because the list is where a user forms a quick impression.
- [ ] Row card classes follow `NotificationRow.tsx:26-30` (`flex items-start gap-3 rounded-md border p-4`, `border-border bg-surface`).

### FR-004: Navigation

#### Acceptance Criteria:

- [ ] A **"Data quality"** entry is added to `PrimaryNav`'s `TABS` (`components/PrimaryNav.tsx`), after Connections — so the tab bar reads Files, Query, Connections, Data quality.
- [ ] The same destination is added to `AppNavDrawer`'s `DESTS` (`components/AppNavDrawer.tsx`), which already carries five entries, so it is reachable on mobile.
- [ ] The active state uses the existing `NavLink` underline treatment (`border-accent text-accent-text`) — no new styling.
- [ ] The **report view** (`/data-quality/:space/:requestId`) does **not** get its own nav entry; it is reached from this list or from a notification deep link (SPEC-113 FR-008).
- [ ] A test asserts the tab is present at `tablet:` width and in the drawer at mobile width.

### FR-005: Empty, loading, and error states

#### Acceptance Criteria:

- [ ] **Empty** (no checks ever run) uses the existing two-line dashed-border empty state (`NotificationsPage.tsx:133-140`): a headline naming the space ("No quality checks yet") and a one-line body telling the user **where to start one** — from a file or folder in the Files browser. It is an invitation, not an apology.
- [ ] **Empty after filtering** says so distinctly ("No checks match this filter"), so the user does not think their history vanished.
- [ ] **Loading** is a `role="status"` text line (`<p role="status" className="px-1 py-10 text-center text-sm text-text-3">`), not a bare spinner.
- [ ] **Failed to load** renders a `Banner variant="danger"` with an inline "Try again" button **above** the list, never replacing it — the `NotificationsPage.tsx:111-123` pattern. Wording comes from `toUserMessage` (SPEC-106); `error.message` is never rendered.

### FR-006: Responsive, accessible, and honest about what it omits

#### Acceptance Criteria:

- [ ] Rows reflow at mobile: the location stays on line one and the metadata (space, time, file count) wraps to line two — **one** component tree with responsive utilities, not a `*Mobile`/`*Desktop` twin.
- [ ] Header actions (filter, refresh) use `stackActionsOnMobile` and wrap rather than overflowing.
- [ ] The page never scrolls horizontally at the mobile breakpoint.
- [ ] A11y tests are a co-located `DataQualityPage.a11y.test.tsx` using `expectNoA11yViolations` with **`ROUTE_AXE_OPTIONS`**, re-run at `window.innerWidth = 400`, asserting exactly one `heading level 1` and one `main` (mirroring `NotificationsPage.a11y.test.tsx:65-83`).
- [ ] The page states, in a `text-xs text-text-3` footer line, that it lists **completed checks** and that a check that **failed** appears in **notifications** instead — linking to `/notifications`. A comment records why this line is a requirement: a history page that silently omits failures teaches the user to trust a list that is lying to them by omission, and the line is what converts an omission into a **signpost**.
- [ ] The line is only honest because **SPEC-114 FR-004 guarantees the notification always arrives** — including for failures no verb can catch. A comment records the dependency explicitly, so nobody weakens the notification guarantee later without realizing it silently breaks this page's contract with the user.

---

## Data Model

```jsonc
// {space}/_data-quality-reports/index.json   — one per space, capped at 200 entries
{
  "entries": [
    {
      "requestId": "…",
      "location": "alice/sales/",
      "format": "csv",
      "verdict": "issues_found",          // | "clean"
      "fileCount": 3,
      "hasApproximateFigures": true,
      "timestamp": "2026-07-12T14:32:11Z"
    }
  ]
}
```

```python
# lambdas/data-quality-common/dqcommon/config.py
DQ_INDEX_MAX_ENTRIES: int = 200
DQ_INDEX_CAS_RETRIES: int = 5
```

```ts
// apps/portal/src/features/data-quality/dataQuality.types.ts  (extended)
export type DataQualityRunSummary = {
  requestId: string;
  space: string;                 // CLIENT-DERIVED from which space's index was fetched — NOT stored in the
                                 // entry; the row links to /data-quality/{space}/{requestId}
  location: string;
  format: string;
  verdict: 'clean' | 'issues_found';
  fileCount: number;
  hasApproximateFigures: boolean;
  timestamp: string;
};
```

## API / Interface Contract

```ts
// apps/portal/src/features/data-quality/useDataQualityRuns.ts
export function useDataQualityRuns(): {
  runs: DataQualityRunSummary[];   // merged across spaces, newest first
  isLoading: boolean;
  error: string | undefined;       // already through toUserMessage
  refresh: () => Promise<void>;
};
```

## File & Folder Structure

```
apps/portal/src/routes/DataQualityPage.tsx              # thin re-export
apps/portal/src/features/data-quality/
├── DataQualityPage.tsx                                 # the list
├── DataQualityPage.test.tsx
├── DataQualityPage.a11y.test.tsx
├── DataQualityRunRow.tsx                          (+ test)
├── useDataQualityRuns.ts                          (+ test)
└── dataQualityRuns.service.ts                     (+ test)   # reads index.json per space
apps/portal/src/components/PrimaryNav.tsx                # + the tab
apps/portal/src/components/AppNavDrawer.tsx              # + the destination
apps/portal/src/App.tsx                                  # + /data-quality route
lambdas/data-quality-assemble-report/assemble_report.py  # + the CAS index append
lambdas/data-quality-common/dqcommon/index_store.py      # the CAS read-modify-write
```

## Implementation Phases

### Phase 1: The index write

- `dqcommon.index_store` — read-modify-write under ETag CAS with bounded retry, the entry cap, the empty/unparseable rebuild, and the **swallow-on-exhaustion** behaviour.
- Wire it into `assemble-report`, **after** the report write.
- **Tests: two concurrent appends both survive; an exhausted CAS does not fail the check; a corrupt index rebuilds.**

### Phase 2: The list page

- The read service (parallel per-space index fetches, partial-failure tolerance), `useDataQualityRuns`, the page with its filter, `Pager`, rows, and the four states from FR-005.
- Tests including the sampled-run-never-reads-as-clean assertion.

### Phase 3: Navigation, responsive, completion ritual

- `PrimaryNav` + `AppNavDrawer` entries; the route; reflow at all three breakpoints; `*.a11y.test.tsx`.
- Help & guides entry (SPEC-074): where to find past checks, what "sampled" means on a row, and that failed checks live in notifications.
- Delivery doc, INDEX status, component-inventory rows.

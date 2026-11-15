---
type: Spec
id: SPEC-259
title: "Query Moves Onto the App Router"
description: "Serves the Query workspace from an App Router page instead of the react-router catch-all, with its editor, its runs and its hand-offs unchanged."
spec_status: Completed
depends_on: [SPEC-256]
arc: nextjs
arc_order: 5
---

**Dependency notes:** SPEC-256 (the shell in the root layout, which holds the Query workspace's
runs; the navigation seam and its hand-off state; the area records, the area modules that export
each area's views, the route table built from the records, the record-and-page guard, the page
sweep and `renderApp`). The arc's charter and its per-area contracts are in `ARCS.md` → *Next.js
arc (SPEC-255 → 263)*. This spec is one of four area moves that may build in parallel; it shares no source file with the other three, and none with 262's rewrite
(*Files this spec does not touch*, below).

## Overview

The Query workspace leaves the catch-all for an App Router page that loads the same view, so the
editor, the tabs, the runs and the links into and out of Query behave as they do today. Two of
those links cross into another feature: *Open in Query* from the Data Explorer arrives as a
hand-off, and a `columns_removed` notification arrives as a `?refreshTable=` link that opens the
refresh dialog for its table. Both keep their rules on the seam, whichever router serves the page
that sent them, because Explore may still be in the catch-all when Query moves, or may have moved
first.

## Scope

### In Scope

- `src/app/(signed-in)/query/page.tsx`, loading the Query view through `next/dynamic` with
  `ssr: false`; the view keeps loading the workspace lazily, as it does today.
- The Query record flipped to `'app'`.
- New tests in `src/routes/areas/query.test.tsx` that only the App Router page can pass.
- The live checks below, on the web tier switched on through CI and off afterwards.

### Out of Scope

- **Any change to the view, the workspace, the editor or the run engine.** The run engine lives in
  the shell and does not move.
- **The other areas** (258, 260, 261) and the landing page and 404 (263).
- **The route table**, which stops building Query's route because its record says `'app'`.
- **Next's file conventions beyond `page.tsx`.**

### Files this spec does not touch

`src/routes/table.tsx`, `src/routes/areas/*.tsx`, and every other area's record, pages and split
tests. Nothing SPEC-262 rewrites, which is `src/lib/amplify.ts`, `src/lib/idToken.ts`,
`src/lib/apiClient.ts`, `src/features/auth/`, the token registration in `AppFrame`, `PortalBoot`,
`src/features/connections/useConnections.ts`,
`src/features/file-browser/useSharedSpaceAccessRecovery.ts`, and their tests
(`FileBrowser.test.tsx` and `features/shared-spaces/ConnectionsPage.test.tsx` among them), nor the
`aws-amplify` and `lib/idToken` mocks the split test files inherit, which 262 removes; new tests go
below those mocks without editing them and need neither. At completion the spec regenerates
`docs/specs/index.yaml`, which a rebase resolves by running `gen-index.sh` again, and writes its live
checks into its own areas' sections of `docs/testing/e2e.md`, cross-router steps included, rather
than into a section another move also writes.

---

## Functional Requirements

### FR-001: Query is served by an App Router page

#### Description:

The page file is a client component that renders the Query view and nothing else, reached through
`next/dynamic` with `ssr: false` and no loading fallback; the view's own `Suspense` shows the loading
state while the workspace's chunk arrives, as today. The page takes no props. The Query record
changes `router` to `'app'`.

#### Acceptance Criteria:

- [x] The page file exists, the page sweep and the record-and-page guard pass, and the Query record
      says `'app'`.
- [x] A new test renders `/query` through `renderApp` and finds the workspace's editor region; with
      the page file deleted it turns red on the catch-all's 404. Because `renderApp` serves every
      area from the catch-all unless a test names it, every `renderApp` call in Query's split file
      names Query's router `'app'`, the runs that outlive the page among them, and they pass; with
      Query's page broken, those runs tests turn red too.
- [x] `next build` lists `/query` as a dynamic route, and `next start` answers it with status 200.

### FR-002: The links into Query keep their rules

#### Description:

*Open in Query* delivers its statement once, under `StrictMode`, and nothing on Back, Forward or a
reload, from an Explore page on either router. A `?refreshTable=` link opens the refresh dialog
read from the address, and confirming or dismissing it drops the parameters with a replace the
seam writes natively, so the page is neither fetched again nor remounted.

#### Acceptance Criteria:

- [x] Through `renderApp`, *Open in Query* from Explore opens one tab with the statement, with
      Explore served by the catch-all and then by the App Router through the `routers` option
      (supplying Explore's page through `pages` while it has none on disk); Back then Forward opens
      nothing.
- [x] A `?refreshTable=` link opens the refresh dialog for its table; dismissing it leaves `/query`
      with no parameter, and dropping them calls neither `router.push` nor `router.replace`.

### FR-003: Checked live, on the tier

#### Description:

The build switches the web tier on through the repository variable and CI, runs these checks
signed in, and switches it off again, saying so in its report. When another area move's live checks
may overlap, it agrees the window with the arc's orchestrator first, so that one move switching the
tier off does not end another's checks. *As built, the tier was already on and held by other moves,
so the build added a line to the arc's holder list and removed it after the checks, and did not
switch the tier itself; the delivery doc's Deliberate deviations says so.*

#### Acceptance Criteria:

- [x] The editor opens and highlights SQL, a statement runs, and the page records no
      `securitypolicyviolation` event while it does.
- [x] A running query keeps running across Query to Files and back, and its results are on screen
      on return without running again.
- [x] *Open in Query* from the Data Explorer opens one tab with the statement; Back and then Forward
      opens no second tab.
- [x] The skip link, then Files, then Back shows Query, and Query keeps its own tab title.

---

## API / Interface Contract

```tsx
// src/app/(signed-in)/query/page.tsx
'use client';
import dynamic from 'next/dynamic';

const QueryView = dynamic(() => import('../../../routes/areas/query').then((m) => m.QueryView), {ssr: false});

export default function QueryPage() {
  return <QueryView />;
}
```

## File & Folder Structure

```
apps/portal/src/
├── app/(signed-in)/query/page.tsx   new
├── lib/navigation/areas/query.ts    router: 'app'
└── routes/areas/query.test.tsx      new tests below the existing ones
```

## Implementation Phases

### Phase 1: The page and the record

- The page file and the record flip, together, and the new tests.

### Phase 2: The production build and the live checks

- `next build` and `next start` locally, then the live checks on the tier, switched on and off
  through CI.

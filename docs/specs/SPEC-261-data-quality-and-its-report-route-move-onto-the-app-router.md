---
type: Spec
id: SPEC-261
title: "Data Quality and Its Report Route Move Onto the App Router"
description: "Serves the data-quality runs page and the report route from App Router pages instead of the react-router catch-all, with the report still gated before it reads anything and its space link still waiting for a fresh read."
spec_status: In Progress
depends_on: [SPEC-256]
arc: nextjs
arc_order: 7
---

**Dependency notes:** SPEC-256 (the shell in the root layout, the navigation seam with its decoded
route params and link waits, the area records, the area modules that export each area's views, the
route table built from the records, the record-and-page guard, the page sweep and `renderApp`). The
arc's charter and its per-area contracts are in `ARCS.md` → *Next.js arc (SPEC-255 → 263)*, which
fixes this area's two page paths. This spec is one of four area moves that may build in parallel;
it shares no source file with the other three, and none with 262's rewrite
(*Files this spec does not touch*, below).

## Overview

The data-quality runs page and the report page leave the catch-all for App Router pages that load
the same views. The report is the one route in the portal with parameters in its path
(`/data-quality/<space>/<requestId>`), so it is the first to read them from Next rather than from
react-router, and the seam decodes them so an encoded character in a space name reads as it does
today. Two of the report's rules matter more than its looks: the feature flag must resolve before
the page mounts, because a report read before the flag answers would let a disabled feature confirm
that someone else's report exists, and a space the cached connections list lacks must wait for a
read after the link before the report is refused.

## Scope

### In Scope

- `src/app/(signed-in)/data-quality/page.tsx` and
  `src/app/(signed-in)/data-quality/[space]/[requestId]/page.tsx`, each loading its view through
  `next/dynamic` with `ssr: false`.
- The Data quality record flipped to `'app'`; its two path patterns are unchanged.
- New tests in `src/routes/areas/data-quality.test.tsx` that only the App Router pages can pass.
- The live checks below, on the web tier switched on through CI and off afterwards.

### Out of Scope

- **Any change to a view, the runs page, the report page or the flag gate.**
- **The other areas** (258, 259, 260) and the landing page and 404 (263).
- **The route table**, which stops building both routes because the record says `'app'`.
- **Next's file conventions beyond `page.tsx`**, and no `generateStaticParams`: the report renders
  per request like every page.

### Files this spec does not touch

`src/routes/table.tsx`, `src/routes/areas/*.tsx`, and every other area's record, pages and split
tests. Files' split tests use a Data quality stand-in for their throwing-page scenarios, and pass
unchanged with this area on either router. Nothing SPEC-262 rewrites, which is `src/lib/amplify.ts`, `src/lib/idToken.ts`,
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

### FR-001: The runs page and the report are served by App Router pages

#### Description:

Each page file is a client component that renders its view and nothing else, reached through
`next/dynamic` with `ssr: false` and no loading fallback. Neither takes props: the report reads
`space` and `requestId` through the seam's `useParams`, which returns Next's values decoded. The
report's folders are named `[space]` and `[requestId]`, so Next's parameter names are the ones the
report already reads. The Data quality record changes `router` to `'app'`.

#### Acceptance Criteria:

- [ ] Both page files exist, the page sweep and the record-and-page guard pass, and the record says
      `'app'`.
- [ ] A new test renders the runs page through `renderApp` and finds its runs list, and another
      renders a report through it and finds the report's heading; with either page file deleted,
      its test turns red on the catch-all's 404. The inherited split tests pass unchanged.
- [ ] Through `renderApp`, with shared workspaces on and a connection whose database is `a@b c`,
      `/data-quality/a%40b%20c/req-1` renders the report for space `a@b c` and request `req-1`.
- [ ] `next build` lists `/data-quality` and `/data-quality/[space]/[requestId]` as dynamic routes,
      and `next start` answers both with status 200.

### FR-002: The report's gate and link wait keep their rules

#### Description:

The view still puts the flag gate outside the report page, so with the data-quality flag off the
report renders the unavailable page and reads nothing. A report link naming a space the cached
connections list lacks still waits for one read settled after the link, then opens the report or
refuses it, and a traversal back to the entry is not a follow.

#### Acceptance Criteria:

- [ ] With the data-quality flag off, the report path renders the unavailable page and the report
      service is never called; with the flag on and resolving late, the service is not called
      before the flag answers.
- [ ] A report link to a space the cached list lacks waits for a read settled after the link before
      it refuses, and Back onto the entry starts no read.
- [ ] A notification's link to a report opens it from the Notifications page, with Notifications
      served by the catch-all and then by the App Router through the `routers` option.

### FR-003: Checked live, on the tier

#### Description:

The build switches the web tier on through the repository variable and CI, runs these checks
signed in, and switches it off again, saying so in its report. When another area move's live checks
may overlap, it agrees the window with the arc's orchestrator first, so that one move switching the
tier off does not end another's checks.

#### Acceptance Criteria:

- [ ] The runs page lists runs, and a run's report opens from it and from its completion
      notification; Back from the report returns to where the user came from.
- [ ] A report deep link pasted into a second tab opens the report.
- [ ] The skip link, then the runs page, then Back shows the report, and each page keeps its own
      tab title.

---

## API / Interface Contract

```tsx
// src/app/(signed-in)/data-quality/[space]/[requestId]/page.tsx
'use client';
import dynamic from 'next/dynamic';

const DataQualityReportView = dynamic(
  () => import('../../../../../routes/areas/data-quality').then((m) => m.DataQualityReportView),
  {ssr: false}
);

export default function DataQualityReportPage() {
  return <DataQualityReportView />;
}
```

## File & Folder Structure

```
apps/portal/src/
├── app/(signed-in)/data-quality/
│   ├── page.tsx                          new
│   └── [space]/[requestId]/page.tsx      new
├── lib/navigation/areas/data-quality.ts  router: 'app'
└── routes/areas/data-quality.test.tsx    new tests below the existing ones
```

## Implementation Phases

### Phase 1: The pages and the record

- The two page files and the record flip, together, and the new tests.

### Phase 2: The production build and the live checks

- `next build` and `next start` locally, then the live checks on the tier, switched on and off
  through CI.

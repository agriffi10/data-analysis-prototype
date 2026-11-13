---
type: Spec
id: SPEC-260
title: "Explore and Connections Move Onto the App Router"
description: "Serves the Data Explorer and the Connections page from App Router pages instead of the react-router catch-all, with the Explorer's deep links and hand-offs unchanged."
spec_status: Draft
depends_on: [SPEC-256]
arc: nextjs
arc_order: 6
---

**Dependency notes:** SPEC-256 (the shell in the root layout, the navigation seam with its hand-off
state and link waits, the area records, the area modules that export each area's views, the route
table built from the records, the record-and-page guard, the page sweep and `renderApp`). The arc's
charter and its per-area contracts are in `ARCS.md` → *Next.js arc (SPEC-255 → 263)*. This spec is
one of four area moves that may build in parallel; it shares no source file with the other three, and none with 262's rewrite
(*Files this spec does not touch*, below). Connections is in 262's way more than any
other area, because its list (`useConnections.ts`) is one of the files 262 rewrites; nothing here
edits it.

## Overview

The Data Explorer and the Connections page leave the catch-all for App Router pages that load the
same views. The Explorer is the area most bound up with navigation: a deep link names a table in its
search (`?space=&db=&table=`) and is dropped from the address once read; *Explore in Data Explorer*
arrives from Query as a hand-off; and a `?space=` the cached connections list lacks waits for one
read of the list before it is refused. All three keep their rules on the seam, whichever router
serves the page that sent them. The Connections page is gated by the shared-workspaces flag and has
no navigation rules of its own beyond that.

## Scope

### In Scope

- `src/app/(signed-in)/explore/page.tsx` and `src/app/(signed-in)/connections/page.tsx`, each
  loading its area's view through `next/dynamic` with `ssr: false`; each view keeps loading its
  page lazily, as it does today.
- The Explore and Connections records flipped to `'app'`.
- New tests in `src/routes/areas/explore.test.tsx` and `src/routes/areas/connections.test.tsx`
  that only the App Router pages can pass.
- The live checks below, on the web tier switched on through CI and off afterwards.

### Out of Scope

- **Any change to a view, the Explorer, the Connections page or the connections list.**
- **The other areas** (258, 259, 261) and the landing page and 404 (263).
- **The route table**, which stops building both areas' routes because their records say `'app'`.
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

### FR-001: Explore and Connections are served by App Router pages

#### Description:

Each page file is a client component that renders its area's view and nothing else, reached through
`next/dynamic` with `ssr: false` and no loading fallback; each view's own `Suspense` shows the
loading state while the page's chunk arrives, as today. The pages take no props. Both records change
`router` to `'app'`.

#### Acceptance Criteria:

- [ ] Both page files exist, the page sweep and the record-and-page guard pass, and both records say
      `'app'`.
- [ ] A new test per area renders its page through `renderApp` and asserts something only that page
      shows (the Explorer's table picker, the Connections heading); with that page file deleted, it
      turns red on the catch-all's 404. The inherited split tests pass unchanged.
- [ ] With the shared-workspaces flag off, `/connections` renders the unavailable page, and a
      pass-through counter wrapping the Connections page's default export records no render; with
      the Data Explorer flag off, `/explore` does the same for the Explorer's page. The counters are
      reset per test, so the inherited tests that render those pages still pass.
- [ ] `next build` lists `/explore` and `/connections` as dynamic routes, and `next start` answers
      each with status 200.

### FR-002: The Explorer's deep links, hand-offs and link waits keep their rules

#### Description:

A deep link opens its table and then drops its parameters with a replace the seam writes natively,
so a reload opens no second tab and the page is neither fetched again nor remounted. *Explore in Data
Explorer* delivers its statement once, under `StrictMode`, and nothing on Back, Forward or a
reload, from a Query page on either router. A `?space=` the cached list lacks waits until a read
after the link settles, then opens the space or refuses it, and Back onto the entry is not a
follow.

#### Acceptance Criteria:

- [ ] Through `renderApp`, a deep link to a table opens it and leaves `/explore` with no
      parameters, and dropping them calls neither `router.push` nor `router.replace`; a reload of
      the entry opens no second tab.
- [ ] *Explore in Data Explorer* from Query opens one tab, with Query served by the catch-all and
      then by the App Router through the `routers` option (supplying Query's page through `pages`
      while it has none on disk); Back then Forward opens nothing.
- [ ] A `?space=` link to a space the cached list lacks waits for one read settled after the link,
      and the skip link followed on the waiting page does not start another read.

### FR-003: Checked live, on the tier

#### Description:

The build switches the web tier on through the repository variable and CI, runs these checks
signed in, and switches it off again, saying so in its report. When another area move's live checks
may overlap, it agrees the window with the arc's orchestrator first, so that one move switching the
tier off does not end another's checks.

#### Acceptance Criteria:

- [ ] A deep link to a table, pasted into the address bar, opens the table and leaves `/explore`
      with no parameters, and a reload afterwards does not open it again.
- [ ] *Explore in Data Explorer* from Query and *Open in Query* from the Explorer each open one tab;
      Back and then Forward opens no second tab.
- [ ] The Connections page lists the user's spaces with shared workspaces on, and keeps its own tab
      title.
- [ ] The skip link, then Files, then Back shows the Explorer.

---

## API / Interface Contract

```tsx
// src/app/(signed-in)/explore/page.tsx — the shape of both
'use client';
import dynamic from 'next/dynamic';

const ExploreView = dynamic(() => import('../../../routes/areas/explore').then((m) => m.ExploreView), {ssr: false});

export default function ExplorePage() {
  return <ExploreView />;
}
```

## File & Folder Structure

```
apps/portal/src/
├── app/(signed-in)/
│   ├── explore/page.tsx               new
│   └── connections/page.tsx           new
├── lib/navigation/areas/
│   ├── explore.ts                     router: 'app'
│   └── connections.ts                 router: 'app'
└── routes/areas/
    ├── explore.test.tsx               new tests below the existing ones
    └── connections.test.tsx           new tests below the existing ones
```

## Implementation Phases

### Phase 1: The pages and the records

- The two page files and the two record flips, together, and the new tests.

### Phase 2: The production build and the live checks

- `next build` and `next start` locally, then the live checks on the tier, switched on and off
  through CI.

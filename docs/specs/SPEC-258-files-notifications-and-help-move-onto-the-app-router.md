---
type: Spec
id: SPEC-258
title: "Files, Notifications and Help Move Onto the App Router"
description: "Serves the Files, Notifications and Help pages from App Router pages instead of the react-router catch-all, with nothing a user does on them changing."
spec_status: In Progress
depends_on: [SPEC-256]
arc: nextjs
arc_order: 4
---

**Dependency notes:** SPEC-256 (the shell in the root layout, the navigation seam, the area records
in `src/lib/navigation/areas/`, the area modules in `src/routes/areas/` that export each area's
views, the route table built from the records, the guard that keeps records and pages in agreement,
the page sweep, and `renderApp`, which selects pages from the file system). The arc's charter and
its per-area contracts are in `ARCS.md` → *Next.js arc (SPEC-255 → 263)*. This spec is one of four
area moves that may build in parallel; it shares no source file with the other three, and none with 262's rewrite
(*Files this spec does not touch*, below).

## Overview

Files, Notifications and Help are the first areas to leave the catch-all. Each becomes an App Router
page that loads the same view it renders today, so what a user sees and does on them does not change:
uploads, folder and space navigation, notifications and their links, and Help's sections and guides
all behave as before. What changes underneath is which router serves the page, which is the point
of the arc. Two things a user can notice come from the App Router itself, and SPEC-256 already
states them: moving to a different page scrolls to the top (Back restores the position), and while
an upload is unfinished a reload asks first.

## Scope

### In Scope

- `src/app/(signed-in)/files/page.tsx`, `src/app/(signed-in)/notifications/page.tsx` and
  `src/app/(signed-in)/help/page.tsx`, each loading its area's view through `next/dynamic` with
  `ssr: false`.
- The three area records flipped to `'app'`.
- New tests in the three areas' split test files that only the App Router pages can pass.
- The live checks below, on the web tier switched on through CI and off afterwards.

### Out of Scope

- **Any change to a view, a feature or a page component.** The area modules and everything they
  render are unchanged; a defect found in one is a separate change.
- **The other areas** (259, 260, 261) and the landing page and 404 (263).
- **The route table** (`src/routes/table.tsx`). It stops building these areas' routes because their
  records say `'app'`, without being edited.
- **Next's file conventions beyond `page.tsx`**: no `layout.tsx`, `loading.tsx`, `error.tsx` or
  `metadata` in these folders.

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

### FR-001: The three areas are served by App Router pages

#### Description:

Each page file is a client component that renders its area's view and nothing else, reached through
`next/dynamic` with `ssr: false` and no loading fallback (the shell and the header stay on screen
while the view's chunk loads, and a lazy view shows its own loading state as today). It takes no
props, because the seam, not the page, carries the address. The Files, Notifications and Help
records change `router` from `'catch-all'` to `'app'`, so the seam sends a navigation to them
through `router.push`, the table stops building their routes, and the gate still treats their paths
as signed in.

#### Acceptance Criteria:

- [ ] The three page files exist, the page sweep and the record-and-page guard pass, and the three
      records say `'app'`.
- [ ] A new test per area renders its page through `renderApp` and asserts something only that area
      shows (the Files listing, the Notifications heading, a Help section's heading); with that
      page file deleted, the test turns red on the catch-all's 404, since the table no longer
      builds the route. The inherited split tests pass unchanged.
- [ ] `next build` lists `/files`, `/notifications` and `/help` as dynamic routes beside
      `/[[...slug]]`, and `next start` answers each with status 200.

### FR-002: What users do on the three pages behaves as before

#### Description:

Each area keeps the behaviours that depend on navigation, now that its page is the App Router's.
Files: uploads and in-flight operations outlive the page; switching space from the sidebar is a
search-only navigation the seam writes natively, so the page is neither fetched nor remounted (the
file browser inside it still remounts on a space change, by design); and a `?space=` link waits for
a read of the connections list as before. A folder click changes no address, so it is not a
navigation at all. Notifications: the bell's count and the page's
links reach their destinations on either router. Help: a section chip pushes a `#section` entry,
Back returns to the previous section, and a contextual help link from another page opens Help at
its section.

#### Acceptance Criteria:

- [ ] Through `renderApp`, an upload started on Files survives a round trip to Query and back, with
      Query served by the catch-all through the `routers` option.
- [ ] With shared workspaces on, switching space from the sidebar calls neither `router.push` nor
      `router.replace`, and a pass-through counter on the Files page component records no second
      mount.
- [ ] A notification's link to a Files folder lands on Files with that folder open, and its link to
      a data-quality report lands on the report, with Data quality served by the catch-all and by
      the App Router in turn through the `routers` option.
- [ ] On Help, choosing a section and then going Back shows the previous section; a contextual help
      link from Files opens Help at the linked section.

### FR-003: Checked live, on the tier

#### Description:

The build switches the web tier on through the repository variable and CI, runs these checks
signed in, and switches it off again, saying so in its report. When another area move's live checks
may overlap, it agrees the window with the arc's orchestrator first, so that one move switching the
tier off does not end another's checks.

#### Acceptance Criteria:

- [ ] An upload started on Files keeps going across Files to Query and back, a reload during it
      raises the leave confirmation, and each page keeps its own tab title.
- [ ] On Files, switching space from the sidebar makes no request for the page (Resource Timing),
      and the skip link, then Query, then Back shows Files.
- [ ] A folder whose name holds a space opens from a Query table action, and Back returns to Query.
- [ ] A notification's link opens its folder; Help's sections and Back behave as in FR-002.

---

## API / Interface Contract

```tsx
// src/app/(signed-in)/files/page.tsx — the shape of all three
'use client';
import dynamic from 'next/dynamic';

const FilesView = dynamic(() => import('../../../routes/areas/files').then((m) => m.FilesView), {ssr: false});

export default function FilesPage() {
  return <FilesView />;
}
```

## File & Folder Structure

```
apps/portal/src/
├── app/(signed-in)/
│   ├── files/page.tsx            new
│   ├── notifications/page.tsx    new
│   └── help/page.tsx             new
├── lib/navigation/areas/
│   ├── files.ts                  router: 'app'
│   ├── notifications.ts          router: 'app'
│   └── help.ts                   router: 'app'
└── routes/areas/
    ├── files.test.tsx            new tests below the existing ones
    ├── notifications.test.tsx    new tests below the existing ones
    └── help.test.tsx             new tests below the existing ones
```

## Implementation Phases

### Phase 1: The pages and the records

- The three page files and the three record flips, together, so the guard never sees one without
  the other.
- The new tests in the three split test files.

### Phase 2: The production build and the live checks

- `next build` and `next start` locally, then the live checks on the tier, switched on and off
  through CI.

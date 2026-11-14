---
type: Decision
title: "react-router inside the catch-all is a matcher the navigation seam feeds (SPEC-256)"
description: "**Every navigation goes through one seam, `lib/navigation/`, and react-router inside the catch-all is a `<Router>` it feeds, never a router owning its own history.** A `BrowserRouter` there renders the 404 on every return from an App Router page once its chunk is cached, because Next renders a page before it writes the address. The seam decides by the COMMITTED address (`window.location`), never its own render; writes same-page and catch-all-to-catch-all navigations with `history.pushState` and the rest with Next's router; classifies a traversal while rendering, never in a popstate listener; holds state in memory, never in history; refuses an off-site target; and matches paths case-sensitively. Each rule rests on a Next 16.4.6 behaviour the Vitest stand-in (`src/test/nextNavigation.ts`) models with a test of its own; re-measure them on a Next upgrade."
---

During the move to the App Router, two routers serve the portal's pages: react-router inside the
optional catch-all (`src/app/[[...slug]]/`) for every area not yet moved, and the App Router for the
rest. Three features depend on what only react-router provides (history state, the navigation type and
a per-entry key: `lib/routeHandoff.ts`'s receivers and `useSpaceLinkPending`), and `linkFlags.ts` and
the gate need its path matcher. So `src/lib/navigation/` is the one navigation surface every feature
imports, with the whole of react-router's that the app uses — `useNavigate`, `Link`, `NavLink`,
`useLocation`, `useSearchParams`, `useParams`, `useNavigationType`, `Navigate`, `matchPath` — and one
adapter, `NavigationProvider`, over Next's `usePathname`, `useSearchParams` and `useRouter`. A lint
rule and a source sweep hold react-router to the seam, the route table and the test harness.

**react-router is fed, not free.** The migration guide's `BrowserRouter` inside the catch-all reads
`window.location` as it mounts. Next renders a new page before its `HistoryUpdater` writes the address,
so once the catch-all's chunk is cached, every navigation from an App Router page back to a catch-all
page rendered react-router's 404 under an address bar showing the right page (measured). The catch-all
renders `CatchAllRouter`: react-router's `<Router>` with the seam's location and navigation type, and a
navigator that sends every push and replace back through the seam.

**What the seam rests on, each measured on Next 16.4.6 while SPEC-256 was authored:**

1. A router push or replace renders before it writes the address.
2. A traversal renders with the address already moved, inside Next's popstate dispatch, before any
   listener the app adds, capture phase included.
3. An external `pushState` or `replaceState` moves the pathname and search without changing the page,
   and copies Next's state into the entry; data that already carries `__NA` passes through untouched.
4. A popstate whose state is null is ignored.
5. `useSearchParams` re-serializes the search (`%20` comes back as `+`).
6. A router push or replace to the current address fetches the page and replaces the entry.
7. A router push can stay uncommitted while the user clicks again.
8. `useParams` returns values percent-encoded.

**The rules, and the behaviour each answers.**

- **Which router performs a navigation.** A target that keeps the committed path (hash-only, search-only,
  the same address), and one whose source and target the catch-all both serve, is written natively:
  Next syncs `usePathname` and `useSearchParams` without fetching or rendering a segment (3), so the
  page stays mounted and keeps its scroll. Measured, the same search-only change through `router.push`
  fetched the page, scrolled to the top, and with the server down raised the leave prompt instead of
  navigating. Everything else is `router.push`/`replace`. Because a native navigation leaves a page's
  `params` and `searchParams` props as they were, no page reads them; pages read the seam, and the page
  sweep holds that.
- **The source is the committed address.** A second click during a slow push (7) must not read the
  push in flight as where the user is: measured, reading the seam's render showed the Files page under
  `/data-quality`. The stand-in's held push and the seam's test go red if the source becomes the seam's
  pending navigation. For the same reason a navigation the seam started is taken as the one rendering
  only while it can be: a native one once its own entry is written, a router one before Next writes the
  address. Next drops a push still in flight when a traversal arrives, and taking the dropped push for
  a Back to the same address called the Back a push, with the dropped push's key and state.
- **A page a router navigation is leaving does not correct its own address** (3, 7). The page stays
  mounted while the push waits on the server, and a native write then makes Next restore, which
  discards the push (`app-router-instance.js` marks the pending action `discarded` on a NAVIGATE or
  RESTORE): a deep link's `clear()` or a conflict review closing after a round trip would lose the
  user's click once the area moves make those exits router pushes (found reviewing the Explore move).
  So a native replace on the same path is dropped while both the committed address and the seam's
  entry are the ones the router navigation left. The seam cannot tell a click from a page's own write,
  so it drops only that shape, how a page corrects its address; a push, or a replace to another page,
  is the user leaving again and goes through, and the last click wins as it does without a leave. The
  address ends the leave on arrival before the destination's first layout effect (a child's layout
  effects run before the seam's), and the entry ends it on a Back to an entry at the same address. A
  target's trailing slash is dropped as Next's router drops it, so no router navigation can land where
  it started and leave the page's writes dropped.
- **A traversal is classified while rendering** (1, 2): a change the seam did not start, with the
  address already moved, is a `'POP'` and reads its key from the entry. A popstate listener cannot do
  this, because React renders the traversal before the listener runs; measured, that called a Back a
  `'PUSH'` with a fresh key for one commit and stamped the wrong key on the entry. The listener handles
  only a traversal that leaves path and search unchanged, an in-page anchor.
- **An in-page anchor's entry is stamped** with the Next state the seam last saw on that page, because
  a native anchor makes a null-state entry and Next ignores its popstate (4): a later Back onto it left
  the page it came from on screen, measured on both routers.
- **Addresses are compared normalized** (5), both searches through `URLSearchParams`; compared raw, a
  hand-off to a folder whose name holds a space never arrived and Back was called a push. The seam's
  location keeps the raw search, because `useRefreshLink` reads names encoded around a literal comma.
- **State lives in the seam's memory**, for the entry its navigation made, never in history; a reload
  or traversal delivers none. **Every push or replace gets a fresh key**, a link to the address shown
  included (a replace, as react-router's `Link` makes it), stamped beside Next's state so a traversal
  reads it again; an entry with none reads `'default'`.
- **`useParams` is react-router's inside the catch-all and Next's decoded elsewhere** (8), so a page
  reads `a@b c` under either router.
- **Off-site targets are refused**: `navigate` and `Link` refuse any `to` whose
  `new URL(to, location.href).origin` is not the portal's, as written or once resolved, logging once,
  and `Link` renders no `href`. Both, because a dot segment before a doubled slash (`/.//host/x`) is a
  path as written and protocol-relative once the URL parser resolves it; the resolution collapses
  doubled slashes as react-router's does, so it stays in the portal.
  `router.push` sends every off-site form but `javascript:` and `data:` to a document navigation on the
  other site (measured), and react-router 7.18.2's open-redirect fix would otherwise have left with
  react-router. A link to another site is a plain `<a>`.
- **Paths match case-sensitively**, as Next routes: the seam's `matchPath`, the chrome's reading of the
  area records and the table's routes all treat `/Files` as no area, a 404 outside the shell. Kept
  case-insensitive, a moved area would have shown a 404 inside the shell at `/Files`. The chrome reads
  the records against the decoded path, as the table matches it, so `/fil%65s` is Files to both and
  never Files outside the gate.

**How it is proved.** `src/test/nextNavigation.ts` replaces `next/navigation` in Vitest (an alias in
`vite.config.ts`) and models all eight behaviours on jsdom's own history, one test each; `renderApp`
renders the real chrome around the page its router state selects. `lib/navigation/navigation.test.tsx`
runs every rule above through it, under both routers wherever the router decides the outcome, and a
planted defect for each (a listener
classifier, no stamping, a raw comparison, the source read from the pending push, a `BrowserRouter`,
no origin check, case-insensitive matching) turns its test red. The cross-router scenarios are live
checks for each area move, since until one lands there is no App Router page to drive.

**Do NOT build:** a `BrowserRouter`, `MemoryRouter` or `HashRouter` anywhere under `src/` (a sweep
fails one); a navigation type read from a popstate listener; `router.push` for a same-page change; a
page that reads `params` or `searchParams` props; Next's `<Link>` or prefetching (the seam's links are
plain anchors); history state as a carrier.

## History

### 2026-11-14

- **Changed:** a page a router navigation is leaving does not correct its own address, because the
  area moves make leaving an App Router page a router push, and a same-page replace in flight loses
  the click; a target's trailing slash is dropped, as Next's router drops it.

### 2026-11-13

- **Settled:** SPEC-256.

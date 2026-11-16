---
type: Decision
title: "Navigation goes through one seam on Next's App Router, which fed react-router inside the catch-all until it retired (SPEC-256, SPEC-263)"
description: "**Every navigation goes through one seam, `lib/navigation/`, on Next's App Router alone: a navigation that keeps the committed pathname is written with `history.pushState`, every other one is Next's `router.push`, and one to a path no page serves Next turns into a document load.** Written natively, a move between two pages leaves the first on screen under the second's address. The seam decides by the COMMITTED address (`window.location`), never its own render; classifies a traversal while rendering, never in a popstate listener; holds state in memory, never in history; refuses an off-site target; and matches paths case-sensitively with its own `matchPath`. Each rule rests on a Next 16.4.6 behaviour the Vitest stand-in (`src/test/nextNavigation.ts`) models with a test of its own; re-measure them on a Next upgrade."
---

Three features depend on what the App Router lacks: history state, the navigation type and a per-entry
key (`lib/routeHandoff.ts`'s receivers and `useSpaceLinkPending`), and `linkFlags.ts` and the gate
need a path matcher. So `src/lib/navigation/` is the one navigation surface every feature imports —
`useNavigate`, `Link`, `NavLink`, `useLocation`, `useSearchParams`, `useParams`, `useNavigationType`,
`Navigate`, `matchPath` — with one adapter, `NavigationProvider`, over Next's `usePathname`,
`useSearchParams` and `useRouter`. Its `matchPath` is its own: static segments, `:name` parameters and
prefix matching, case-sensitive, decoding nothing but `%2F`, matched as react-router's did on a corpus
and on generated paths before the package went (SPEC-263, #1018). A source sweep and a manifest
check (`src/test/reactRouterSweep.test.ts`) keep react-router out of `src/` and the manifests.

**Until SPEC-263, react-router was a matcher the seam fed** (history). During the move, react-router
inside the optional catch-all (`src/app/[[...slug]]/`) served every area not yet moved. The migration
guide's `BrowserRouter` there read `window.location` as it mounted, and Next renders a new page before
its `HistoryUpdater` writes the address, so once the catch-all's chunk was cached every return from an
App Router page rendered react-router's 404 under the right address (measured); the catch-all rendered
a `<Router>` fed the seam's location instead. SPEC-263 moved the landing page and the 404 onto the App
Router and deleted the catch-all, react-router, the route table and the harness's choice of router.

**What the seam rests on, each measured on Next 16.4.6 while SPEC-256 was authored:**

1. A router push or replace renders before it writes the address.
2. A traversal renders with the address already moved, inside Next's popstate dispatch, before any
   listener the app adds, capture phase included.
3. An external `pushState` or `replaceState` moves the pathname and search without changing the page,
   and copies Next's state into the entry; data that already carries `__NA` passes through untouched.
4. A popstate whose state is null is ignored.
5. `useSearchParams` re-serializes the search (`%20` comes back as `+`).
6. A router push or replace to the current address fetches the page and replaces the entry.
7. A router push can stay uncommitted while the user clicks again; a later router navigation
   supersedes it, and an outside `pushState` or `replaceState` without `__NA`, or a traversal,
   discards it.
8. `useParams` returns values percent-encoded.
9. A router navigation or a traversal to a path no page serves is a document load: the page's fetch
   answers 404 and Next loads the document there instead (measured with SPEC-263).

**The rules, and the behaviour each answers.**

- **Which navigations are native.** A target that keeps the committed path (hash-only, search-only,
  the same address) is written natively: Next syncs `usePathname` and `useSearchParams` without fetching or rendering a segment (3), so the
  page stays mounted and keeps its scroll. Measured, the same search-only change through `router.push`
  fetched the page, scrolled to the top, and with the server down raised the leave prompt instead of
  navigating. Everything else is `router.push`/`replace`, which renders the page the new path selects.
  The coexistence also wrote a navigation between two paths the catch-all served natively, which was
  right while one catch-all page rendered both; with the landing page and the 404 separate pages,
  that rule left the 404 on screen under `/` (measured), so SPEC-263 narrowed it to the pathname. Because a native navigation leaves a page's
  `params` and `searchParams` props as they were, no page reads them; pages read the seam, and the page
  sweep holds that.
- **The source is the committed address.** A second click during a slow push (7) must not read the
  push in flight as where the user is: measured, reading the seam's render showed the Files page under
  `/data-quality`. The stand-in's held push and the seam's test go red if the source becomes the seam's
  pending navigation. For the same reason a navigation the seam started is taken as the one rendering
  only while it can be: a native one once its own entry is written, a router one before Next writes the
  address. Next drops a push still in flight when a traversal arrives, and taking the dropped push for
  a Back to the same address called the Back a push, with the dropped push's key and state.
- **A page a router navigation is leaving corrects its address without cancelling it** (3, 7). The
  page stays mounted while the push waits on the server, and a native write then makes Next restore,
  which discards the push (`app-router-instance.js` marks the pending action `discarded` on a NAVIGATE
  or RESTORE): a deep link's `clear()` or a conflict review closing after a round trip would lose the
  user's click once the area moves make those exits router pushes (found reviewing the Explore move).
  Dropping the write instead keeps the click but leaves a one-shot parameter on the entry, which Back
  then acts on again. So a page's replace on the same path, while both the committed address and the
  seam's entry are the ones the router navigation left, is written onto that entry carrying Next's own
  state, which Next's history patch passes through (3): the push survives, Back finds the corrected
  address, and the page does not re-render with it, since it is leaving; a second correction builds on
  the committed search, which is why `useSearchParams`' functional setter reads it, and the entry keeps
  its key and gets no state. An in-page anchor meanwhile makes an entry Next ignores (4), so the leave
  goes on from the anchor's address and the anchor's entry gets Next's state for the corrected page.
  Measured against real Next on 2026-11-14 (standalone build, Chrome): a write carrying `__NA` left a
  held push intact, the same write without it discarded the push, and Back found the corrected
  address with no reload or refetch. That shape is how a page
  corrects its address; a link the user clicks (the seam's `follow`, which `Link` uses), a push, or a
  replace to another page is the user leaving again and goes through, and the last click wins as it
  does without a leave. Any move of the address ends the leave, arrival included, before the
  destination's first layout effect (a child's layout effects run before the seam's); a new entry
  ends it on a Back to an entry at the same address. A target's trailing slash is dropped as Next's
  router drops it, so no seam navigation differing from the address only by that slash goes to the
  router. The leave outlasts its navigation only if Next discards it while neither moves: an outside
  write to the very same URL, or a server redirect back to where it started. Nothing in `src/` does
  either today; if something comes to, the page's corrections stay unrendered until the next
  navigation.
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
- **`useParams` is Next's, decoded once** (8), so a page reads `a@b c`, and `a%2541` reads `a%41`.
- **Off-site targets are refused**: `navigate` and `Link` refuse any `to` whose
  `new URL(to, location.href).origin` is not the portal's, as written or once resolved, logging once,
  and `Link` renders no `href`. Both, because a dot segment before a doubled slash (`/.//host/x`) is a
  path as written and protocol-relative once the URL parser resolves it; the resolution collapses
  doubled slashes, as react-router's did, so it stays in the portal.
  `router.push` sends every off-site form but `javascript:` and `data:` to a document navigation on the
  other site (measured). This rule is the portal's open-redirect protection now that react-router,
  whose 7.18.2 fix it replaced, is gone. A link to another site is a plain `<a>`.
- **Paths match case-sensitively**, as Next routes: the seam's `matchPath` and the chrome's reading of
  the area records treat `/Files` as no area, a 404 outside the shell. Kept case-insensitive, a moved
  area would have shown a 404 inside the shell at `/Files`. The chrome reads the records against the
  path decoded segment by segment, so `/fil%65s` is Files to the gate and never anything outside it,
  although Next answers that spelling with the not-found page (a static segment is not decoded): a
  gate that claims more than Next serves costs a 404 inside the shell for a spelling nobody builds,
  and one that claimed less would render a page outside the gate.

**How it is proved.** `src/test/nextNavigation.ts` replaces `next/navigation` in Vitest (an alias in
`vite.config.ts`) and models every behaviour above on jsdom's own history, one test each; `renderApp`
renders the real chrome around the page its router state selects, or the root not-found page at an
address no page serves. `lib/navigation/navigation.test.tsx` runs every rule above through it, and a
planted defect for each (a listener classifier, no stamping, a raw comparison, the source read from
the pending push or from the last render, every navigation written natively, no origin check,
case-insensitive matching) turns its test red.

**Do NOT build:** react-router, or any router that owns a history, anywhere under `src/` (the sweep
and the manifest check fail one); a navigation type read from a popstate listener; `router.push` for a same-page change; a
page that reads `params` or `searchParams` props; Next's `<Link>` or prefetching (the seam's links are
plain anchors); history state as a carrier.

## History

### 2026-11-15

- **Changed (SPEC-263):** react-router retired with the catch-all. The seam runs on Next's App Router
  alone, a navigation is native only when it keeps the committed pathname, `useParams` is Next's, and
  `matchPath` is the seam's own; a navigation to a path no page serves is a document load, measured,
  and modelled as the stand-in's tenth behaviour. Rewritten in place under this file's name,
  whose title still records where the seam began.

### 2026-11-14

- **Changed:** a page a router navigation is leaving corrects its address onto the entry it left,
  carrying Next's state, because the area moves make leaving an App Router page a router push, and a
  native write in flight would lose the click; a link always navigates; a target's trailing slash is
  dropped, as Next's router drops it.

### 2026-11-13

- **Settled:** SPEC-256.

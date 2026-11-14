---
type: Spec
id: SPEC-256
title: "The App Router Owns the Shell, and Navigation Goes Through One Seam"
description: "Moves the providers and the signed-in shell into the root layout behind the boot, puts every navigation behind one seam that works under both routers, and splits the route table and its cross-area tests into one module per area, so the area moves that follow each edit only their own files."
spec_status: Draft
depends_on: [SPEC-255]
arc: nextjs
arc_order: 2
---

**Dependency notes:** SPEC-255 (the portal is a Next.js app on a Node server). What this spec
builds on, by 255's names: the root layout `src/app/layout.tsx`, which imports `index.css` and opts
every route into dynamic rendering; the optional catch-all `src/app/[[...slug]]/page.tsx`, whose
client component `PortalMount.tsx` loads `src/PortalBoot.tsx` through `next/dynamic` with
`ssr: false`; `PortalBoot`, which fetches `/config.json`, configures Amplify and then imports
`AppRoot` (with its `BrowserRouter`), its order and static imports held by `bootstrap.test.tsx`;
the source sweep that keeps the catch-all's directory from importing the application graph
statically; the development fallback that answers only under Vitest (`MODE === 'test'`), so
`next dev` throws on an early configuration read as production does; and `vite.config.ts`, now
Vitest's alone, with an alias for `server-only`. The arc's charter, the contracts this spec must
keep and the decisions it rewrites are in `ARCS.md` → *Next.js arc (SPEC-255 → 263)*. This spec
refines three of those contracts, and its dated note there says how.

## Overview

After SPEC-255 the portal runs on Next.js, but only as a host: one catch-all route mounts the old
single-page app, and react-router still owns every page, the providers and the signed-in shell.
The areas cannot move onto the App Router one at a time until three things hold. The signed-in
shell (the upload queue, the in-flight file operations and the Query workspace's runs) must sit
above every signed-in page, whichever router renders it, so that leaving Files for a page the App
Router serves does not cancel an upload. Every feature must navigate through one seam that works
under both routers, because the App Router has no history state, no navigation type and no
per-entry key, and three features depend on all three. And the route table and the tests that span
areas must be split one module per area, so that each of the four area moves edits only its own
files and the moves can run in parallel. Nothing changes for the user except one thing: while an
upload is unfinished, the browser asks before the page is reloaded or closed, because under the
App Router a navigation can become a reload.

## Scope

### In Scope

- **The boot moves into the root layout.** `PortalMount` moves up from the catch-all to the root
  layout and wraps every page, so `PortalBoot` loads the runtime document and configures Amplify
  before anything else, and renders no page until then. The providers live in `AppFrame`, which
  `PortalBoot` reaches only through a dynamic import, around `AppChrome`: `RootLayout`, the gate
  and the signed-in shell. `PortalBoot`'s static-import sweep stays with it, and 255's sweep of the
  catch-all's directory widens to every page under `src/app/`.
- **The signed-in shell lives above every page, and the chrome decides by path.** `AppChrome`
  decides from the address, through the area records, whether a page is public or signed in, and
  renders a signed-in page inside the gate that today is the `ProtectedLayout` layout route. The optional catch-all stays where 255
  puts it, at `src/app/[[...slug]]/`, and the `(signed-in)` route group gets no layout of its own.
- **The navigation seam** at `src/lib/navigation/`, with the whole surface the charter names, its
  App Router adapter, and the rule for which router performs each navigation.
- **react-router inside the catch-all becomes a matcher fed by the seam**: a `<Router>` whose
  location, navigation type and navigator all come from the seam, replacing 255's `BrowserRouter`.
- **Features stop importing react-router**, tests included, held by a lint rule.
- **Hand-offs and the link waits on the seam**: `lib/routeHandoff.ts`'s senders and receivers and
  `useSpaceLinkPending` keep their rules, now on the seam's state, key and navigation type.
- **One module per area**: each area's views in `src/routes/areas/<area>.tsx`, from which the
  react-router table builds its routes, the record of which router serves each area in
  `src/lib/navigation/areas/<area>.ts`, and `App.test.tsx`,
  `App.navigation.test.tsx`, `App.queryNavigation.test.tsx` and `routes/routes.test.tsx` split the
  same way.
- **Tests under either router**: `src/test/renderWithProviders.tsx` provides the seam rather than a
  `MemoryRouter`, and a test App Router renders the real chrome around the page the file system
  selects, so the decision's proof keeps rendering the real route table.
- **Unfinished uploads ask before the document goes.**
- Rewriting the three `browser/` decisions the charter assigns to this spec, and a new decision for
  why react-router inside the catch-all cannot own its own history.

### Out of Scope

- **Moving any area onto the App Router.** That is 258 to 261. After this spec every area's record
  still says the catch-all serves it, and no `src/app/(signed-in)/` page exists yet.
- **The landing page, the 404 and retiring react-router.** That is 263, which also replaces the
  seam's react-router-backed path matcher. This spec leaves `/` and every unknown path in the
  catch-all's table.
- **Anything about sessions or sign-in.** The auth provider stays Amplify's (257 and 262).
- **Next's file conventions beyond pages and layouts.** No `error.tsx`, `not-found.tsx`,
  `loading.tsx` or `template.tsx` is added; the error boundaries stay the React ones the decision
  describes.
- **Next's `<Link>` and prefetching.** The seam's links are plain anchors. An App Router page's
  payload is fetched when it is navigated to.
- **Keeping an old build serving after a deploy.** The leave confirmation covers unfinished uploads;
  nothing makes a navigation after a deploy stay in the old build.
- **The cross-router live checks.** With no App Router page until an area moves, the scenarios of
  FR-003 that cross the two routers are proved here against the test stand-in, and each area move
  (258 to 261, in whatever order they land) runs them live on its own pages.
- **A leave confirmation for anything but uploads.** A running query and an in-flight file operation
  carry on server-side through a reload, as today; only what `UploadsAtRiskNotice` counts asks.

---

## Functional Requirements

### FR-001: The boot runs in the root layout, ahead of every provider and every page's own code

#### Description:

255's `PortalMount.tsx` moves from the catch-all's directory to `src/app/PortalMount.tsx`, and the
root layout renders `<PortalMount>{children}</PortalMount>`. It still loads `PortalBoot` through
`next/dynamic` with `ssr: false`, now passing the page through, so `PortalBoot` is never evaluated
on the server. `PortalBoot` keeps its order (load the runtime document once per page, configure
Amplify) and then reaches the frame, `src/AppFrame.tsx`, through `await import()`, rendering
`<AppFrame>{children}</AppFrame>`. Until then it renders nothing of the app and never its children;
on a failed load or a rejected import it renders `BootFailure`, as today. The frame replaces
`AppRoot.tsx` and holds everything that reads configuration at render: the providers, the API
client's token registration and the `QueryClient`, which the frame now creates per mount rather than
importing as a module-scope instance. `lib/queryClient.ts` stays the one home of the client's
defaults, now exporting a factory the frame calls inside `useState`, so the API contract guard that
exempts that file keeps holding. The catch-all's page gets a client entry of its own,
`src/app/[[...slug]]/CatchAllMount.tsx`, which loads the react-router table through `next/dynamic`
with `ssr: false`.

Three facts measured against Next.js 16.4.6 while authoring set the rules. A provider that reads
configuration, placed directly in a layout, builds green and then answers 500 on every page under
`next start`, because the layout is rendered on the server where no document was loaded; Vitest
stays green because its fallback answers. A module that a page file imports statically is
evaluated in the browser at hydration, before `/config.json` arrives, even when the boot keeps the
page from rendering; reached through `next/dynamic` with `ssr: false`, it is evaluated after the
boot. And a layout that wraps its children in a client-only mount keeps every invariant of FR-002:
the whole scenario set passed with a boot module that throws if it is ever evaluated on the
server, and it never threw.

#### Acceptance Criteria:

- [ ] `PortalBoot`'s static imports are exactly the set 255's sweep pins, asserted by equality, and
      it reaches `AppFrame` only through `await import`; adding a static import of `AppFrame`, or of
      any provider, fails the sweep.
- [ ] With the mode stubbed to production and a document that fails to load, `PortalBoot` renders
      `BootFailure`, never evaluates `AppFrame`, never configures Amplify and never renders its
      children.
- [ ] Amplify is configured before the frame's first render, asserted by call order; the document
      is fetched exactly once per page load under `StrictMode`.
- [ ] No module under `src/` creates a `QueryClient` at module scope; the frame's client is made in
      `useState`, and a source check names any `new QueryClient(` outside a function body.
- [ ] 255's source sweep of the catch-all's directory widens to every `page.tsx` under `src/app/`
      and the directory beside it: none statically imports anything under `src/features/`,
      `src/components/`, `src/routes/` or `AppFrame`, each reaches its view through
      `dynamic(..., {ssr: false})`, and none declares a parameter, so none reads the `params` or
      `searchParams` props a native navigation leaves stale. The `(signed-in)` folder has no page
      until the first area move adds one, so the sweep is also proved against a fixture corpus asserting its reason: a page importing a
      feature statically fails naming that import, a page using `next/dynamic` without
      `ssr: false` fails naming the option, and a conforming page passes.
- [ ] The root layout's static imports reach nothing under `src/features/`, `src/components/`,
      `src/routes/`, `src/lib/` or `PortalBoot`; it reaches the boot only through `PortalMount`,
      and `PortalMount` reaches `PortalBoot` only through `dynamic(..., {ssr: false})`. The sweep
      covers `src/app/PortalMount.tsx`, and its fixture corpus has a mount without `ssr: false`,
      which fails naming the option.
- [ ] `vite.config.ts`'s coverage exclusion of `src/AppRoot.tsx` names `src/AppFrame.tsx` instead,
      the one module the proof does not render.
- [ ] The root layout writes the document title as a `<title>` in its `<head>` (the one
      `index.html` carried), replacing a `metadata` title if 255's layout set one that way, and a
      source check fails when any file under `src/app/` exports `metadata` or `generateMetadata`. Measured: with the layout's title set through `metadata` instead, three of
      five App Router navigations ended with the tab titled "Data Quarry" rather than the page's own
      title, because Next reapplied it after the page's effect; with the `<title>` in `<head>`,
      every navigation kept the page's title, in two runs.
- [ ] `next build` followed by `next start` serves every signed-in path, `/` and an unknown path
      with status 200, checked against the production build before the push.

### FR-002: The signed-in shell lives above every page and ends only with the session or on a public page

#### Description:

`AppFrame` renders, in order, `StrictMode`, the auth provider, the `QueryClientProvider`, the
seam's `NavigationProvider` and the `ToastProvider`, around `AppChrome`. `AppChrome`
(`src/AppChrome.tsx`) is `RootLayout` (the header, the skip link, the nav-rail provider and the
outer boundary with its `resetKey`) around the page, and it decides by the address, not by which
route matched. A path that no area record claims (`/` and every unknown path) is public: the page
renders bare, outside the gate, as today. A path an area claims is signed in: the page renders
inside the gate, `ProtectedLayout`, now taking `children` instead of rendering an `Outlet`. The
decision sits above `ProtectedLayout` rather than inside it, so its hooks (the flags read, the
notifications prefetch, the exploration eviction and the catalog catch-up) still run on signed-in
pages only. The gate waits on auth, sends a signed-out user to `/` with the return path saved, and
otherwise renders the shell with its inner boundary around the page. The split between `AppFrame`
and `AppChrome` is what lets the proof render the real chrome under the test harness's providers,
as today's proof renders the real `<App />`. `AppFrame` lives in the root layout, the
one layout Next never remounts, so the shell is above both the catch-all and every page the area
moves will add.

Because a navigation to or from an App Router page fetches that page from the server, Next turns
it into a document load when the server cannot be reached or a new build has been deployed since
the page loaded, and a document load ends the shell. Both were measured while authoring. So while
an upload is unfinished (running, queued or waiting on a name decision, the set
`UploadsAtRiskNotice` counts), the shell asks the browser to confirm before the document unloads.
On "Stay" the document, the shell, the uploads and the page the user was on all remain, measured
for both causes. Andrew chose this on 2026-11-13 over accepting the loss as a known limit, knowing
it also prompts on a reload or a closed tab mid-upload, which today cancel the uploads silently.

Signing out is deliberate, and it stays as it is today: it aborts the uploads and asks nothing.
Measured, Amplify's sign-out moves the document to the provider's logout page in the same task that
announces the signed-out status, before React has unmounted the shell, so the guard would ask, and
"Stay" would keep nothing because the shell unmounts anyway. So the auth provider's `signOut`
disarms the guard synchronously, through a flag the guard reads, before it starts the provider's
sign-out.

#### Acceptance Criteria:

- [ ] Through the real chrome and the real route table, an upload started on Files keeps running and
      stays listed after the user leaves Files by a header link and comes back by the Files tab,
      and an in-flight folder operation stays on screen with its space gated, each waiting for its
      destination before asserting (the scenarios `App.navigation.test.tsx` holds today).
- [ ] The same survival holds when the navigation goes through the seam's App Router path: a test
      that serves Files from the App Router through `renderApp`'s `routers` option, with a page at
      `src/app/(signed-in)/files/page.tsx` rendering the real Files view through its `pages` option,
      keeps the upload across a round trip to a catch-all page and back.
- [ ] Signing out aborts the upload and drops the operations; following a link to `/` or to an
      unknown path unmounts the shell, and both render with no shell and no redirect for a
      signed-out user.
- [ ] A signed-in page that throws is caught inside the shell, keeps the uploads going and shows the
      notice; a page that throws only behind a query string recovers when its own tab drops it.
- [ ] Adding a React `key` derived from the path to any element between `AppChrome` and the shell
      turns the survival tests red on their reasons (an aborted signal, the in-progress region
      gone), and moving the shell's providers above the gate turns the sign-out test red.
- [ ] A source check fails when any file between the root layout and `AppChrome` (`layout.tsx`,
      `PortalMount.tsx`, `PortalBoot.tsx`, `AppFrame.tsx`) sets a React `key`, since the proof
      renders from `AppChrome` down.
- [ ] With one upload running, a `beforeunload` event is cancelled (`defaultPrevented`); with every
      upload finished, cancelled or failed, it is not, and with no shell mounted no listener is
      registered.
- [ ] With an upload running, signing out raises no leave confirmation (a `beforeunload` dispatched
      after `signOut` is called and before the status flips is not cancelled) and aborts the
      upload; without the disarm, that assertion fails.
- [ ] Checked live on the web tier: an upload survives Files to Query and back, signing out aborts
      it without a leave confirmation, and reloading during it raises one.

### FR-003: Every navigation goes through one seam, under either router

#### Description:

`src/lib/navigation/` exports what every feature uses: `useNavigate`, `Link`, `NavLink`,
`useLocation`, `useSearchParams`, `useParams`, `useNavigationType`, `Navigate` and `matchPath`, in
the shapes the Interface Contract gives, plus the `NavigationProvider` the frame mounts and the
`CatchAllRouter` the catch-all mounts. The provider is the seam's one adapter: it reads Next's
`usePathname` and `useSearchParams`, and the seam itself owns what the App Router lacks.

- **Which router performs a navigation.** The source is the committed address, `window.location`,
  never the seam's latest render, which may be a transition Next has not committed; measured, a
  second click during a slow push rendered the Files page under `/data-quality`. A navigation whose
  target keeps the committed pathname (hash-only, search-only, or the same address), on either
  router, is written with `history.pushState` or `replaceState`: Next moves `useSearchParams`
  without fetching or rendering anything. Measured, the same change through `router.push` on an App
  Router page fetched the page from the server, scrolled to the top, and with the server down raised
  the leave prompt instead of navigating; written natively it made no request and kept the scroll,
  as Next's own documentation recommends. A navigation whose source and target are both served by
  the catch-all goes the same way: Next copies its own state into the entry and moves `usePathname`
  without rendering a new segment, so the catch-all page stays mounted. Every other navigation goes
  through Next's `router.push` or `router.replace`. Because a native navigation leaves a page's
  `params` and `searchParams` props as they were, no page reads them: pages read the seam.
- **In-app only.** A `to` is refused when `new URL(to, location.href).origin` is not the portal's
  own origin, the check `notificationLink.ts` already uses: that catches every form that leaves the
  site (`//host`, `/\host`, `\\host`, a leading space or tab, `https:host`, an absolute URL), and
  `javascript:` and `data:` through their null origin. The seam logs a refusal once and navigates
  nowhere, and its `Link` given such a `to` renders no `href`; a link to another site is authored as
  a plain `<a>`, not through the seam. react-router 7.18.2 fixed an open redirect through the
  backslash form (`docs/security-baseline.md`), and measured on Next 16.4.6, `router.push` sends
  every one of those forms but `javascript:` and `data:` to a document navigation on the other
  site, so the protection would otherwise go with react-router.
- **Paths match case-sensitively, as Next routes them.** The seam's `matchPath`, the gate's reading
  of the area records and the table's routes (`caseSensitive`) all treat `/Files` as no area, so it
  is a 404 outside the shell under either router. react-router matches case-insensitively, so today
  `/Files` opens Files; kept that way, an area that has moved would show a 404 inside the shell at
  `/Files`, because Next routes it elsewhere while the gate still calls it signed in (measured on a
  harness with no catch-all, where the not-found page rendered inside the shell). The app builds no mis-cased link, and `linkFlags.test.ts`'s `/Files` row
  becomes a link with no flags. A trailing slash never reaches the seam: Next answers `/files/`
  with a redirect to `/files`.
- **Scroll.** A navigation through `router.push` scrolls to the top, as Next does by default, and a
  traversal back restores the position; a native one leaves the scroll where it was, as every
  navigation does today. Measured on both routers. The first area move is the first place a user
  can see the difference, and it is the expected one when the page changes.
- **Addresses are compared normalized.** Next's `useSearchParams` re-serializes the search
  (`%20` comes back as `+`), so every comparison of two addresses parses both searches through
  `URLSearchParams` first. Measured with a folder name holding a space, the shape
  `useTableActions.tsx` builds: compared raw, a hand-off's state never arrived and a Back was called
  a `'PUSH'` with a fresh key.
- **The key.** Every push or replace through the seam gets a fresh key, a navigation to the current
  address included, which `Link` makes a replace as react-router's does. The key is written onto
  the history entry beside Next's own state, and a traversal back to that entry reads it again. An
  entry with no key, such as an in-page anchor's, reads as `'default'`.
- **The navigation type.** A push or replace is what the seam's own call said. A traversal is
  `'POP'`, classified while it renders: a change the seam did not start, with the address already
  moved, is a traversal, because Next writes the address of its own navigations only after
  rendering them. A popstate listener cannot do this, because React renders a traversal inside
  Next's popstate dispatch before any listener the app adds, capture phase included; measured,
  that order called a Back a `'PUSH'` with a fresh key for one commit and wrote the wrong key onto
  the entry. The listener covers only a traversal that leaves the path and search unchanged, an
  in-page anchor.
- **An in-page anchor's entry is made restorable.** A native anchor creates an entry with no
  history state, and Next ignores a popstate whose state is null, so a later Back onto that entry
  left the page it came from on screen: measured, `/query#main` showing the Data Quality page, on
  both routers. When the seam's listener sees such an entry it stamps it, through `replaceState`,
  with the Next state it last saw on that page, which Next passes through untouched, so a traversal
  back to it is one Next restores.
- **State.** The state a navigation carries is held in the seam's memory for the entry that
  navigation created, never written to history, so a reload or a traversal sees none.
- **How a `to` resolves.** As react-router resolves it today, so nothing changes for a caller: a
  hash-only `to` keeps the current pathname, drops the search and sets the hash (only the Help page
  sends one, and it reads only the hash). `useNavigate` takes no history delta; the two tests that
  call `navigate(-1)` (`fileBrowserPure.test.ts` and `helpPanel.test.tsx`) call
  `window.history.back()` and await the destination instead.
- **Route params.** Inside `CatchAllRouter`, which provides a context saying so, `useParams` returns
  react-router's match; elsewhere it returns Next's `useParams()` decoded with
  `decodeURIComponent`, since Next returns them percent-encoded (measured: `a%40b%20c` for
  `a@b c`) and react-router decodes. Both hooks are always called.
- **What the seam rests on.** Every rule above leans on a behaviour of Next 16.4.6, each measured
  while authoring: (1) a router push or replace renders before it writes the address; (2) a
  traversal renders with the address already moved, inside Next's popstate dispatch, before the
  app's listeners; (3) an external `pushState` or `replaceState` moves the pathname and search
  without changing the page, and copies Next's state into the entry; (4) a popstate with null state
  is ignored; (5) `useSearchParams` re-serializes the search; (6) a router push or replace to the
  current address fetches the page and replaces the entry rather than adding one; (7) a router push
  can stay uncommitted while the user clicks again; (8) `useParams` returns encoded values. The
  test stand-in models all eight (FR-006), and the live checks below exercise the ones a catch-all
  page can reach.

`CatchAllRouter` is react-router's `<Router>` with the seam's location and navigation type, and a
navigator that sends `push` and `replace` back through the seam. It replaces 255's `BrowserRouter`,
which cannot stay: measured, once its chunk is cached, every navigation from an App Router page back
to a catch-all page rendered react-router's 404 under an address bar showing the right page,
because the `BrowserRouter` read `window.location` as it mounted, before Next wrote the new
address.

#### Acceptance Criteria:

- [ ] Each export of `src/lib/navigation/` behaves as the Interface Contract states, proved through
      the test App Router: a push, a replace, a same-address `Link` click (a `'REPLACE'` with a new
      key), a hash-only push, Back to a pushed entry (`'POP'` with that entry's own key) and an
      in-page anchor (`'POP'` with `'default'`).
- [ ] A push to another page with a hash (`/help#files` from Files' help panel) renders the
      destination with that hash on its first render, from and to either router.
- [ ] A navigation between two catch-all paths, and a search-only or hash-only one on a page the
      App Router serves, call neither `router.push` nor `router.replace` and do not remount the
      page; one whose target the App Router serves at another pathname calls `router.push`. Each is
      asserted on the call made.
- [ ] An in-page anchor, then a link to another page, then Back, shows the anchor's page as a
      `'POP'` with `'default'`, from a catch-all page and from a page the App Router serves; with
      the stamping removed, the test shows the wrong page.
- [ ] A link whose search holds an encoded space (`?prefix=My%20Reports%2F`) and carries state
      delivers the state, and Back onto its entry is a `'POP'` with that entry's own key; with the
      comparison made on raw strings, both fail.
- [ ] With the stand-in holding an App Router push uncommitted, a second click to a catch-all page
      ends on that page with that page rendered; reading the source from the seam's render instead
      turns the test red.
- [ ] Each of `//evil.example/x`, `/\\evil.example/x`, `\\\\evil.example/x`, `' //evil.example/x'`,
      `'/\t/evil.example/x'`, `https:evil.example/x`, `https://evil.example/`, `javascript:alert(1)`
      and `data:text/html,x`, given to `navigate`, calls neither `router.push` nor
      `history.pushState`, leaves the address unchanged and logs once, and given to `Link`, renders
      an anchor with no `href`; `navigate('/files')` and `<Link to="/help#files">` still work.
- [ ] `/Files` signed in renders the 404 with no shell, and `matchPath('/files', '/Files')` returns
      `null`.
- [ ] `useParams` returns `{space: 'a@b c'}` for `/data-quality/a%40b%20c/r1` both inside the
      catch-all and on a page the App Router serves.
- [ ] Checked live on the web tier, on catch-all pages: the skip link, then another page, then Back
      shows the right page; a Files folder whose name holds a space opens from a Query table action
      and Back returns to Query; and a search-only change makes no request for the page.
- [ ] A navigation's state reaches the destination's first render, and is gone after Back and
      Forward and after a reload.
- [ ] No commit during a traversal reports a navigation type other than `'POP'`, asserted by
      recording every value the seam provides while the stand-in replays Next's order (the page
      rendered before any popstate listener runs); classifying by a popstate listener instead turns
      the assertion red.
- [ ] `CatchAllRouter` renders the route that matches the seam's location on its first render
      after a navigation from an App Router page, with the catch-all's chunk already loaded;
      substituting `BrowserRouter` turns the test red, the stand-in rendering the destination
      before writing the address as Next does.
- [ ] No file under `src/` renders `BrowserRouter`, `MemoryRouter` or `HashRouter`.

### FR-004: Features cannot reach react-router

#### Description:

Every import of `react-router` outside the seam moves to the seam: the features, `components/`,
the route pages under `src/routes/`, and their tests. A `no-restricted-imports` pattern forbids
`react-router` in every file under `src/` except the seam (`src/lib/navigation/**`), the route
table (`src/routes/table.tsx`, and not its test) and the test harness (`src/test/**`). The area
modules need no exemption: they export views, and only the table turns them into routes. The catch-all's entry needs no exemption: it renders
the seam's `CatchAllRouter` around the table. Tests elsewhere are not exempt: they reach routes
through the harness's options, not by composing react-router themselves. The pattern is spread into
every `no-restricted-imports` clause, 255's `src/server/` clause included, because flat config
replaces a rule's value at the last matching entry rather than merging it.

The exemption is two clauses, not one, for the same flat-config reason. The seam's clause
(`src/lib/navigation/**`) keeps every other group the clauses it overrides carry: the layering ban
on importing features, 255's `src/server/` ban and the AWS SDK ban. Measured, a single exemption
clause carrying only the SDK group let a file in the seam import a feature and lint clean. The
table's and the harness's clause keeps the SDK group only, because the harness imports features.

The rule sees only static imports. `await import('react-router')`, `vi.mock('react-router', …)`
and `typeof import('react-router')` all lint clean (measured on ESLint 10.10.0), and two of them
exist today (`App.navigation.test.tsx` and `DataQualityReportPage.test.tsx`). A source sweep
therefore holds the bare `'react-router'` literal to the exempt places as well. The sweep lives in
`src/test/`, which is exempt, and the shape test imports the pattern constant from
`eslint.config.js` rather than spelling the literal.

#### Acceptance Criteria:

- [ ] `npm run lint` passes, and a source sweep finds the string `'react-router'` in no file under
      `src/` outside the three exempt places, in any form: a static import, a dynamic import, a
      `vi.mock` or a type query.
- [ ] Committing an import of `react-router` in a feature, in a component, in a route page, in a
      feature's test, in an area module and in an area's test each fails lint naming the seam in its
      message; the same import in the seam and in the route table passes. A `vi.mock('react-router', …)` in a
      feature's test fails the sweep. Each observed, not read from the config.
- [ ] `eslintConfigShape.test.ts` fails when any `no-restricted-imports` clause other than the two
      exemptions omits the new pattern (255's `src/server/` clause included), when the two
      exemptions' file lists differ from the places above, and when an exemption clause lacks any
      group, other than `react-router`, of a clause it overrides.
- [ ] A file in the seam that imports a feature fails lint with the layering message.

### FR-005: Hand-offs and link waits keep their rules on the seam

#### Description:

`lib/routeHandoff.ts`'s builders and readers are unchanged. Senders navigate with the seam's
`navigate(to, {state})`; receivers read `location.state` once per `location.key` and replace the
entry with no state, so the read-once rule, the `StrictMode` guard and "a link on the same entry
goes first" hold as written. Because the seam never writes state to history, a reload or a
traversal can no longer deliver a hand-off at all; the receiver's replace stays, and the decision
says it is now belt and braces. `useSpaceLinkPending` reads the seam's `useNavigationType()` and
`location.key`, so a traversal is still not a follow, an in-page anchor reads as a traversal with
`'default'`, and following the same link again is a replace with a new key that re-arms the wait.
All three behaviours, and a hand-off read once with nothing on Back, Forward or reload in each of
the four pairings of the two routers, were measured while authoring.

#### Acceptance Criteria:

- [ ] The hand-off suites (`openSqlHandoff`, `exploreHandoff`, `openInQuery`, `filterRow`,
      `savedViewRefusal`) pass on the seam unchanged in what they establish. Their eleven reads of
      `window.history.state.usr`, which the seam never writes, become reads of the seam's location
      through the render result's `location()`; a hand-off arriving on the first entry is seeded
      before `ui` mounts, so the `StrictMode` test still doubles the receiving effect, and deleting
      the `location.key` guard turns it red.
- [ ] Back and then Forward to an entry whose hand-off was read opens nothing and raises no limit
      dialog, and a reload of it opens nothing.
- [ ] `useSpaceLinkPending`'s tests pass on the seam, including the skip link, which must not re-arm
      the wait, and the same link followed twice, which must; making the hook treat `'POP'` as a
      follow turns the skip-link test red.

### FR-006: One module per area, and tests under either router

#### Description:

Each area module, `src/routes/areas/<area>.tsx` (`files`, `notifications`, `help`, `query`,
`explore`, `connections`, `data-quality`), exports its views, one per path pattern: the
composition each route element holds today (`FeatureRoute`, then for a lazy page its keyed
`ErrorBoundary` and `Suspense`, then the page), with no react-router in it. Each area's record,
`src/lib/navigation/areas/<area>.ts`, names its path patterns and which router serves it, and
`areas/index.ts` composes them; every record says `'catch-all'` after this spec. `App.tsx` becomes
`src/routes/table.tsx`, which renders the landing route, then a `<Route>` for each path of each
area whose record says `'catch-all'`, with the view the area module exports for that path, then the
`*` route. The layout routes leave the table, since the frame now holds both layouts.

That shape is what lets the four area moves run in parallel without sharing a file. A move adds its
App Router pages, which reach the same views through `next/dynamic`, and flips its own record to
`'app'`; the table then stops building the area's routes without being edited, and the area module
does not change. A guard keeps the two halves together: it fails when a record says `'app'` and a
path of it has no page under `src/app/(signed-in)/`, when a page there serves a path whose record
says `'catch-all'`, or when a page there serves a path no record claims. The first would send the
seam's `router.push` to the optional catch-all, which would match the path and render the 404,
since the table no longer builds it; the last would render outside the sign-in gate, since the
chrome treats a path no record claims as public. The views are named for the moves to import:
`FilesView`, `NotificationsView`, `HelpView`, `QueryView`, `ExploreView`, `ConnectionsView`,
`DataQualityView` and `DataQualityReportView`.

Which router serves an area is read, by the seam, the chrome and the table alike, through a context
whose default is the records. Nothing in production provides it; `renderApp` does, so a test can
serve an area from either router whatever is on disk, and a test that crosses the two routers holds
in whatever order the area moves land. Two other guards read `App.tsx`'s source today and move to
the records: `features/help/helpSurfaces.test.ts` (every help surface names a routed path) and
`features/notifications/NotificationsPage.test.tsx` (the report's path pattern is one the app
serves).

The four cross-area test files split into `src/routes/areas/<area>.test.tsx`, each holding the
scenarios whose subject is that area: Files keeps the upload survival, the throwing-page tests and
the sign-out test; Query keeps the runs that outlive the page; each area keeps its own route-block
and page checks; `src/routes/table.test.tsx` keeps the 404, the landing route, the check that no two
areas' boundaries share a key, read across every area module, and the lazy route that fails to load,
whose file-wide mock makes the Query page throw and so must not sit in Query's file.

The proof renders the real route table through `renderApp`, a test App Router in
`src/test/appRouter.tsx`. It renders the real `AppChrome` (`RootLayout`, the gate and the shell)
under the harness's providers (the test `QueryClient` with retries off, the auth context, the
seeded flags and the seam, without the harness's `CatchAllRouter`, since the catch-all page brings
its own and react-router refuses one router inside another), the way today's proof renders the
real `<App />`. Its `auth` is a fixed value or, for a test whose subject is the status changing (the
sign-out test, today's `SignOutable`), a component that provides the auth context. It renders this
around the page the stand-in's router state selects from the file system, as Next's does: that
state changes on a router push or replace and on a traversal, and a native `pushState` moves the
address without changing the page (behaviour 3 below), so `renderApp` must not select by the
address. The pages come from `import.meta.glob` over `src/app/**/page.tsx`, matched by
Next's rules for the segment kinds the app uses, static before dynamic before optional catch-all,
with route groups transparent. What sits above `AppChrome` is composition held by FR-002's source
check. Next's `next/navigation` is replaced in Vitest by an alias in `vite.config.ts`, beside 255's
`server-only` alias, to `src/test/nextNavigation.ts`, which runs on jsdom's own history and models
each of the eight behaviours FR-003 lists, with a test of its own for each. An area move adds its
page file and flips its record, and the proof covers it without being edited.

`renderWithProviders` and `renderHookWithProviders` provide the seam through the same stand-in,
with a `CatchAllRouter` inside it so a component that reads route params resolves them. `route`
seeds the address and, in its object form, the first entry's state, which the seam holds before `ui`
mounts. The render result gains `location()`, the seam's location as it stands, which is how a test
asserts where a navigation went and what it carried. Two options replace a test
composing react-router itself: `path`, the pattern `ui` renders at, and `routes`, other patterns
and what renders there for a test whose subject navigates away. `browserRouter` goes, since jsdom's
history is now the only mode; the address is restored after each test. The shell's providers stay
out of the harness, as the decision requires.

#### Acceptance Criteria:

- [ ] `src/routes/table.tsx` and the seven area modules exist, `App.tsx` and `AppRoot.tsx` do not,
      and every path the table served before is served now, each asserted by rendering it through
      `renderApp`, so an area move changes which router serves it without reddening the test.
- [ ] Rendered directly under `renderWithProviders`, with an area served by the App Router through
      the override context, the table builds none of that area's routes and renders the 404 at its
      path.
- [ ] The record-and-page guard fails for a record saying `'app'` with a path that has no page, for a
      page whose record says `'catch-all'`, and for a page whose path no record claims, each against
      a fixture naming the area and path; it passes on the tree as this spec leaves it.
- [ ] `helpSurfaces.test.ts` and `NotificationsPage.test.tsx` read the area records instead of
      `App.tsx`, and flipping a record leaves both green.
- [ ] `renderApp`'s `routers` option serves a named area from the catch-all with its page on disk
      ignored, and from the App Router with the page its `pages` option supplies; a `pages` entry at a
      path that has a page on disk replaces it.
- [ ] Each area's checks that read route source (`FeatureRoute`, then `ErrorBoundary`, then
      `Suspense`, with the right flag, for each lazy route) read that area's module; the key
      uniqueness check reads every area module through a glob and fails on a block copied with its
      key.
- [ ] The test names collected from the runner before and after the split are the same set apart
      from the renames the plan lists, diffed from a JSON run on both refs.
- [ ] `renderApp`'s page selection resolves each `page.tsx` on disk from the address it serves, and
      a fixture corpus of segment shapes asserts the precedence order and that a route group adds
      nothing to the address.
- [ ] `src/test/nextNavigation.ts` has a test for each of FR-003's eight behaviours, asserting the
      behaviour itself (for example, that a pushed page has rendered while `window.location` still
      shows the old address, and that a popstate with null state changes nothing).
- [ ] A test renders a component that navigates with the seam under `renderWithProviders` with no
      router option, and the same component as a catch-all page through `renderApp`, and both
      reach the destination; no test outside `src/test/` imports `react-router`.
- [ ] The harness carries none of the shell's providers: removing `QueryRunsProvider` from the shell
      turns the Query runs proof red. (Amended while building: the mutant first written here, adding
      the shell's providers to the harness, cannot go red, because the shell's own provider is the
      nearest and stays in charge; what the rule protects against is the proof passing with the
      shell's provider deleted, which this mutant is.)

---

## Data Model

```ts
// src/lib/navigation/areas/area.types.ts

/** Which router serves an area's pages during the coexistence. */
export type AreaRouter = 'catch-all' | 'app';

export type AreaRecord = {
  /** The URL segment, which is also the App Router folder: `src/app/(signed-in)/<area>/`. */
  area: 'files' | 'notifications' | 'help' | 'query' | 'explore' | 'connections' | 'data-quality';
  /** The path patterns the area serves, matched whole (a trailing segment is a 404, as today). */
  paths: readonly string[];
  router: AreaRouter;
};

// src/lib/navigation/navigation.types.ts

export type NavigationType = 'PUSH' | 'REPLACE' | 'POP';

export type NavLocation = {
  pathname: string;
  search: string;
  hash: string;
  /** What the navigation that made this entry carried; never read back from history. */
  state: unknown;
  /** Fresh per push or replace; the same on a traversal back; 'default' for an entry with none. */
  key: string;
};

export type To = string | {pathname?: string; search?: string; hash?: string};
export type NavigateOptions = {replace?: boolean; state?: unknown};
```

---

## API / Interface Contract

```ts
// src/lib/navigation/index.ts — the only module a feature imports for navigation

export function useNavigate(): (to: To, options?: NavigateOptions) => void;
export function useLocation(): NavLocation;
export function useNavigationType(): NavigationType;
export function useSearchParams(): [
  URLSearchParams,
  (next: URLSearchParams | ((prev: URLSearchParams) => URLSearchParams), options?: NavigateOptions) => void
];
export function useParams<T extends Record<string, string | undefined>>(): T;
export function matchPath(
  pattern: string | {path: string; end?: boolean},
  pathname: string
): {params: Record<string, string | undefined>} | null;

/** A plain anchor; a primary click with no modifier navigates through the seam. */
export function Link(props: {to: To; replace?: boolean; state?: unknown} & AnchorProps): JSX.Element;
/** As react-router's: `aria-current="page"` when active, `className` and `children` may be functions of `{isActive}`. */
export function NavLink(props: NavLinkProps): JSX.Element;
/** Navigates from an effect, as react-router's does. */
export function Navigate(props: {to: To; replace?: boolean}): null;

/** Mounted by AppFrame. `initialState` seeds the first entry's state before anything below mounts; only the test harness passes it. */
export function NavigationProvider(props: {children: ReactNode; initialState?: unknown}): JSX.Element;
export function CatchAllRouter(props: {children: ReactNode}): JSX.Element; // mounted by the catch-all

// src/lib/navigation/areas/index.ts
export const AREAS: readonly AreaRecord[];
export function areaOf(pathname: string): AreaRecord | null; // null: public (`/`, or no area claims it)
export function routerFor(pathname: string): AreaRouter; // public paths are the catch-all's

// src/test/appRouter.tsx — the real AppChrome under the harness's providers, around the file system's page
export function renderApp(
  route: TestRoute,
  options?: Omit<ProviderOptions, 'route' | 'path' | 'routes' | 'auth'> & {
    /** A fixed auth value, or a component providing the auth context for a test whose subject is the status changing. */
    auth?: AuthContextValue | ComponentType<{children: ReactNode}>;
    /** Page files keyed by their path under src/app/, added beside those on disk or replacing one at the same path. */
    pages?: Record<string, ComponentType>;
    /** Which router serves an area in this test, whatever is on disk; an area set to 'catch-all' has its pages ignored. */
    routers?: Partial<Record<AreaRecord['area'], AreaRouter>>;
  }
): RenderWithProvidersResult;

// Both render entry points' results gain the seam's location as it stands.
type RenderWithProvidersResult = ReturnType<typeof render> & {
  user: UserEvent;
  queryClient: QueryClient;
  location: () => NavLocation;
};

// src/test/renderWithProviders.tsx — options added and removed
type ProviderOptions = {
  route?: TestRoute;
  /** The pattern `ui` renders at, so its params resolve, e.g. '/data-quality/:space/:requestId'. */
  path?: string;
  /** Other patterns and what renders there, for a test whose subject navigates away. */
  routes?: Record<string, ReactElement>;
  // `browserRouter` is removed: jsdom's history is the only mode.
  // auth, queryClient, seedFeatureFlags and featureFlags are unchanged.
};
```

```tsx
// A sender and a receiver, unchanged except for the import
import {useLocation, useNavigate} from '../../lib/navigation';

navigate('/query', {state: buildOpenSqlHandoff({sql, label})});

const location = useLocation();
useEffect(() => {
  if (consumed.current === location.key) return;
  const handoff = readOpenSqlHandoff(location.state);
  if (!handoff) return;
  consumed.current = location.key;
  openTab(handoff);
  navigate({pathname: location.pathname, search: location.search, hash: location.hash}, {replace: true});
}, [location.key, location.state]);
```

## File & Folder Structure

```
apps/portal/src/
├── AppFrame.tsx                      # replaces AppRoot.tsx: the providers around AppChrome; reached only by PortalBoot's dynamic import
├── AppChrome.tsx                     # RootLayout, the path decision and the gate: what renderApp renders for real
├── PortalBoot.tsx                    # 255's boot; now renders <AppFrame>{children}</AppFrame>
├── bootstrap.test.tsx                # 255's, retargeted to the frame and the children
├── app/
│   ├── layout.tsx                    # 255's; now renders <PortalMount>{children}</PortalMount>
│   ├── PortalMount.tsx               # 255's, moved up from [[...slug]]/; loads PortalBoot with ssr: false
│   ├── pageSweep.test.ts             # 255's catch-all sweep, widened to every page under src/app/
│   └── [[...slug]]/
│       ├── page.tsx                  # 255's; now renders <CatchAllMount />
│       └── CatchAllMount.tsx         # loads the table, inside CatchAllRouter, with ssr: false
├── components/
│   ├── RootLayout.tsx                # takes children, no Outlet
│   └── ProtectedLayout.tsx           # the gate: takes children, decides by path
├── lib/navigation/
│   ├── index.ts
│   ├── navigation.types.ts
│   ├── NavigationProvider.tsx
│   ├── CatchAllRouter.tsx
│   ├── Link.tsx  NavLink.tsx  Navigate.tsx  matchPath.ts
│   ├── navigation.test.tsx
│   └── areas/
│       ├── area.types.ts
│       ├── index.ts
│       └── files.ts  notifications.ts  help.ts  query.ts  explore.ts  connections.ts  data-quality.ts
├── routes/
│   ├── table.tsx                     # was App.tsx
│   ├── table.test.tsx
│   └── areas/
│       ├── files.tsx  files.test.tsx
│       ├── notifications.tsx  notifications.test.tsx
│       ├── help.tsx  help.test.tsx
│       ├── query.tsx  query.test.tsx
│       ├── explore.tsx  explore.test.tsx
│       ├── connections.tsx  connections.test.tsx
│       └── data-quality.tsx  data-quality.test.tsx
└── test/
    ├── appRouter.tsx                 # renderApp: the real chrome around the file system's page
    ├── reactRouterSweep.test.ts      # the bare 'react-router' literal, held to the exempt places
    ├── nextNavigation.ts             # Vitest's next/navigation, on jsdom's history
    └── renderWithProviders.tsx       # the seam instead of MemoryRouter
```

Deleted: `src/App.tsx`, `src/AppRoot.tsx`, `src/App.test.tsx`, `src/App.navigation.test.tsx`,
`src/App.queryNavigation.test.tsx` and `src/routes/routes.test.tsx`. Moved: 255's
`src/app/[[...slug]]/PortalMount.tsx` to `src/app/PortalMount.tsx`.

## Implementation Phases

### Phase 1: The seam and the test router

- `src/lib/navigation/` with its adapter, `CatchAllRouter`, the area records and `matchPath`
  (react-router's, behind the seam, until 263).
- `src/test/nextNavigation.ts` and its alias in `vite.config.ts`, with a test per modelled
  behaviour; the seam's own tests against the stand-in, including the traversal-order and
  `BrowserRouter` mutants.
- `renderWithProviders` and `renderHookWithProviders` on the seam, with `path`, `routes`,
  `location()` and the seeded first state.

### Phase 2: The boot, the frame and the chrome

- `PortalMount` in the root layout, `PortalBoot` rendering `AppFrame` in place of `AppRoot`,
  `AppChrome` split from it, the `QueryClient` from the factory per mount, the token registration
  in the frame module.
- `RootLayout` and `ProtectedLayout` as components taking children, the path decision in
  `AppChrome` above the gate, the leave confirmation in the shell and its disarm on sign-out.
- The route table split into `table.tsx` and the area modules; the catch-all's page on
  `CatchAllMount` and `CatchAllRouter`.
- `bootstrap.test.tsx` retargeted to the frame; 255's page sweep widened, with its fixture corpus;
  `src/test/appRouter.tsx`.

### Phase 3: Every caller onto the seam, and the split tests

- Move every `react-router` reference outside the exempt places to the seam: features,
  components, route pages and tests alike, retiring `browserRouter` from its callers and
  `navigate(-1)` from its two tests.
- The four cross-area test files split per area onto `renderApp`, the runner's test names diffed,
  and the survival mutants run.

### Phase 4: The fence and the record

- The two exemption clauses and the pattern in every other clause, the shape test, the literal
  sweep, and the violations observed each way. Last, because the rule fails on every file the
  earlier phases have not yet moved.
- The production build served by `next start` and the live checks on the tier, switched on and off
  through the repository variable and CI.
- The decisions rewritten in place with History entries: the layout boundaries (the shell in the
  root layout, the path decision above the gate, the proof on the file system's table), the
  sibling hand-off (state in the seam's memory, read once per seam key), and the space link (a
  traversal read from the seam). A new `browser/` decision for why react-router in the catch-all is
  fed by the seam rather than owning its history, carrying the eight Next behaviours the seam rests
  on.

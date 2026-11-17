---
type: Decision
title: "Layout boundaries reset by prop, never by `key`; a signed-in page's sits inside the shell (2026-09-10)"
description: "**The signed-in shell outlives every signed-in page, and no ancestor may remount it.** It holds the upload queue, the in-flight file operations and the Query workspace's runs, so it lives in the ROOT layout, under the chrome, which decides by the address through the area records whether a page is signed in. A per-page React `key` above it aborts the uploads on a nav-tab click — and passes every test that composes its own layouts. Boundaries reset by **`resetKey`**; a page's throw is caught **inside** the shell. While an upload is unfinished the shell asks before the document unloads, and sign-out disarms that first. The proof renders the **real chrome around the page the file system selects** (`renderApp`)."
---

`RootLayout` sits above every page, so the `ErrorBoundary` around the page outlives every page
change, and without a reset one throwing page pins the fallback after the user navigates away. (It
was a react-router layout route until 2026-11-13; it is now in the root layout, below.) The
first fix was `key={pathname}`. It reset the boundary — and on every route change it also remounted
**everything** beneath it, which includes `ProtectedLayout` and its shell. The shell
holds the upload queue and the in-flight file operations because both are meant to outlive the page,
so every nav-tab click aborted the uploads in progress (the provider's unmount cleanup) and dropped
the in-progress cards and the per-space submit gate. Measured live on 2026-09-10: two part `PUT`s
aborted 126 ms after a Query click, then a `POST /v1/objects/upload/abort`. Every test was green:
the only one that rendered the real route table never navigated, and the rest composed their own
layouts under a router with no key above them.

**The fix is a `resetKey` prop.** The boundary clears its error in `componentDidUpdate` when the key
changes, so the subtree renders again instead of remounting. The layouts pass the path **and query
string**: the path alone would miss the page's own tab when a query string is what broke it, and the
location's own `key` — which changes on every navigation, even to the same address — was tried and
dropped. With it, a page that re-navigates to its own URL on mount while a child throws resets into
the throw for as long as it keeps mounting; routed through transitions, that never trips React's
update-depth limit. Nothing here does that today, and the address-based key cannot do it at all. The
cost is that a click to the identical address does not recover a page, which the panel's advice to
open another page already covers. Both halves of the condition are load-bearing. The
update that *caught* the error is skipped (`prevState.hasError`): a navigation INTO a broken page is
also a change of key, and resetting on it renders the page into a second throw. And the key must
actually have changed: a reset that renders ANOTHER broken page never commits, so the catch after it
still finds the error in `prevState`, and without the comparison the boundary resets into the throw
until React stops it with *Maximum update depth exceeded*.

**There are two such boundaries, and the page's is inside the shell.** `ProtectedLayout` wraps the
page in one, below both providers: caught at `RootLayout`, a signed-in page's throw swaps the
whole shell for the fallback, and the providers' unmount aborts the uploads exactly as the key did.
`RootLayout`'s stays, because nothing sits above it — it is the only boundary for the landing page,
the 404 page and a throw from the shell or `ProtectedLayout`'s own hooks. What still unmounts the
shell is sign-out, leaving for a public page (the landing page, or any path no area claims, such as
the 404), and the document itself going.

**The shell lives in the root layout (2026-11-13).** It was put there while the areas moved onto the
App Router one at a time, so the shell would not notice which router served a page; since SPEC-263
every page is an App Router page, and the root layout is still the one layout Next never remounts: the root layout
renders `PortalMount`, which loads the boot client-only; the boot renders `AppFrame` (the providers)
around `AppChrome`, which is `RootLayout` around either the bare page or `ProtectedLayout` around it.
**The chrome decides by the address, through the area records** (`lib/navigation/areas/`), never by
which page matched: the root layout sits above the landing page, the not-found page and every
signed-in page alike, so where it sits says nothing. A path no record claims is public. The decision sits above the gate rather than in it,
so the gate's hooks run on signed-in pages only, and the `(signed-in)` route group has no layout of
its own. *(Since SPEC-264, 2026-11-17, each gated area has a server layout below the shell — see
below; the group itself still has none.)* Nothing between the root layout and `AppChrome` (`layout.tsx`, `PortalMount`, `PortalBoot`,
`AppFrame`) may carry a `key`, and the page sweep (`src/app/pageSweep.test.ts`) refuses one, because
the proof renders from `AppChrome` down.

**Two measured traps decide where a provider can go.** A provider that reads configuration, placed
straight in a layout, builds green and then answers 500 on every page under `next start`, because a
layout is rendered on the server where no runtime document was loaded; Vitest stays green because its
fallback answers. And a module a page file imports statically is evaluated in the browser at
hydration, before `/config.json` arrives. So every provider renders client-only behind the boot, the
query client is made per mount, and a page reaches its view only through `next/dynamic` with
`ssr: false` and reads no `params` or `searchParams` prop, all held by the page sweep, and what a
page hydrates is held on the build by `npm run check:pages`.

**The gated areas have server layouts below the shell (SPEC-264, 2026-11-17).** `/files`, `/query`,
`/connections`, `/explore` and `/data-quality` each have a `layout.tsx` that answers a disabled area
with the "not available" page from the flag set the server holds when it is under five minutes old,
and otherwise returns its
`children` untouched. They sit below the shell, which lives in the root layout, so moving between
areas never remounts it, and **they carry no `key`**. **They never throw**: there is no `error.tsx`
between them and the root, so a throw in one answers 500; their gate answers `open` on any fault and
does no I/O. They read no session and no `params`, and the page sweep holds each to importing only
the server's flag module, the unavailable mount and React's types.

**A document load is now a way to lose the shell, so the shell asks first.** A navigation to or from
an App Router page fetches that page, and Next turns it into a document load when the server cannot
be reached or a new build has been deployed since the page loaded; both were measured. While an
upload is unfinished (the set `UploadsAtRiskNotice` counts) the shell's `UnloadGuard` cancels
`beforeunload`, so the browser asks; on "Stay" the document, the shell, the uploads and the page all
remain. It also asks on a reload or a closed tab mid-upload, which before cancelled the uploads
silently (Andrew's ruling, 2026-11-13, over accepting the loss). It listens only while something would
be lost. **A download is not the document going**: it is a navigation to the presigned URL, and
Chrome raises `beforeunload` inside its click before it learns the response is an attachment, so
mid-upload a download asked "Leave site?" and on "Stay" never happened (measured). Both download
helpers run their click through `withoutLeaveGuard`, which restores the guard as it was. **Signing out asks nothing**, as before: the sign-out moves the document to the provider's
logout page while the shell is still mounted (Amplify's did, until SPEC-262), so the auth provider's `signOut`
disarms the guard synchronously (`lib/leaveGuard.ts`) before it starts, and re-arms it if the
sign-out fails.

**Keeping the uploads alive gave the panel's one button a cost.** The fallback advises a reload,
and a reload ends every upload the shell just kept — before, the crash had already ended them, so
the button cost nothing. The shell's panel therefore carries a `notice`, `UploadsAtRiskNotice`, that
says how many uploads a reload would cancel and that opening another page keeps them, and says
nothing while every upload has finished. It counts what is running, queued or waiting on a name
decision, because a reload loses all three. It sits outside the panel's alert: an alert re-announces
its whole content when any of it changes, and this line changes each time an upload finishes. The
user chose the notice over a confirm dialog on the button, and over leaving the panel as it was.

**Removing the key exposed a second defect it had been hiding.** The three lazy routes render the
same element shape — `FeatureRoute`, then `ErrorBoundary`, then `Suspense` — into the same slot, so
React reuses ONE boundary instance across them: a chunk that failed on `/query` stayed on screen after
a click to `/explore`, and a reused `Suspense` shows no loading state on the way in. Each now carries
a static key of its own, so switching lazy routes remounts only the page's subtree, which it did
anyway. Since each area became a view component of its own, each route's element is a different
type, so React remounts the boundary on a route change whatever its key; the keys hold only for the
day two routes render one view component. Measured 2026-11-14 on a cleared Vitest cache: the
behaviour test went red only with one view type shared AND a key shared, never on either alone, and
stayed green with Query's own boundary removed, since the shell's page boundary catches the failed
chunk and resets on the route change. So it was deleted. **The keys themselves went with SPEC-263**
(2026-11-15): each area is an App Router page segment of its own, so no two routes render into one
slot, and the source check that held them distinct went with the route table.

**What the proof has to be.** `routes/areas/files.test.tsx` renders the real chrome through
`renderApp` (`src/test/appRouter.tsx`): the real `AppChrome` under the harness's providers, around the
page Next's stand-in selects from the file system, the way Next does. It starts an upload and a folder operation through the real Files page, and
navigates with links the header really renders — the bell, then the Files tab — waiting for each
destination before asserting; one scenario keeps the upload across a round trip to another page
through Next's router, another follows a link to `/` and requires the shell gone, and a link to an
unknown path is a document load (Next loads the not-found page's document rather than rendering it),
which the unload guard asks about first while an upload runs.
The Help control on `/files` is a panel button and not a link, so it would have "navigated" without
changing the route. Restoring the key fails the survival tests on their reasons: an aborted signal,
and the in-progress region gone. Others drive a throwing page mid-upload, the same-path recovery,
and sign-out — which must still abort the upload, or a fix that hoisted the providers above the auth
gate would pass the rest. Removing the disarm turns the sign-out-without-asking test red, and so
does moving the shell's providers above the gate in `AppChrome`.

**The Query workspace's runs moved into the shell on 2026-11-06.** They lived in the Query page,
which unmounts on every nav-tab click, so a run's results were gone on the way back and a running
query lost its poller: its batch stopped advancing and its history never settled. The shell's
`QueryRunsProvider` now holds the run engine and its pollers, and the page binds them to its active
tab. **The mobile surface's state had to move with them**: it names its own run by a token, and a
counter restarted on each visit matched the previous visit's run, dressing a new query in the old
one's rows; its reset on crossing up out of mobile moved too, since a page that is away misses the
crossing and a page-held reset of shell state is an update during another component's render. On
mount the page drops any run whose tab did not come back, which happens when session storage
failed; left in place, that run went on polling with nothing able to stop it. A saved query whose
body arrives after the user left opens nothing and runs nothing: its tab would have landed in a
store nothing persists, and the run would have been dropped on return. Its proof, `routes/areas/query.test.tsx`, renders the real chrome like the uploads' and **the
provider must not go into the shared test harness**: placed there it sits above the chrome too, and
the proof passes with the shell's own provider deleted. The workspace suites wrap themselves
instead, as the upload suites do. Removing the shell's provider turns all three of its tests red, and
keying it on the page turns both survival tests red.

## History

### 2026-11-17

- **Changed (SPEC-264):** the gated areas gained server layouts below the shell, with no `key`, and a
  gate that never throws.

### 2026-11-15

- **Changed (SPEC-263):** the catch-all and react-router retired, so every page is an App Router page
  under the same root layout; the lazy views' static keys and the source check that held them went,
  since each area is its own page segment.

### 2026-11-14

- **Changed:** the lazy-route behaviour test was deleted as vacuous: with each route rendering its
  own view component, it could not fail on a shared key, nor without the view's own boundary. The
  source check keeps the keys distinct.

### 2026-11-13

- **Changed (SPEC-256):** the shell moved into the root layout, under a chrome that decides by the
  address through the area records, so it outlives a page whichever router serves it; a leave
  confirmation guards unfinished uploads against a document load, disarmed by sign-out; the proof
  moved to `renderApp`, which renders the real chrome around the file system's page.

### 2026-11-06

- **Extended:** the Query workspace's runs joined the shell.

### 2026-09-10

- **Settled:** entered the register.

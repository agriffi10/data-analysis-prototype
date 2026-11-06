---
type: Decision
title: "Layout boundaries reset by prop, never by `key`; a signed-in page's sits inside the shell (2026-09-10)"
description: "**The signed-in shell outlives every signed-in page, and no ancestor may remount it.** It holds the upload queue, the in-flight file operations and the Query workspace's runs, so a per-route React `key` above it aborts the uploads on a nav-tab click — and passes every test that composes its own layouts. Boundaries reset by **`resetKey`**; a page's throw is caught **inside** the shell, since caught above it the fallback replaces the shell. The proof renders the **real route table**."
---

`RootLayout` is a layout route, so the `ErrorBoundary` around its `Outlet` outlives child-route
changes, and without a reset one throwing page pins the fallback after the user navigates away. The
first fix was `key={pathname}`. It reset the boundary — and on every route change it also remounted
**everything** beneath it, which includes the `ProtectedLayout` layout route and its shell. The shell
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

**There are two such boundaries, and the page's is inside the shell.** `ProtectedLayout` wraps its
`Outlet` in one, below both providers: caught at `RootLayout`, a signed-in page's throw swaps the
whole shell for the fallback, and the providers' unmount aborts the uploads exactly as the key did.
`RootLayout`'s stays, because nothing sits above it — it is the only boundary for the landing page,
the 404 page and a throw from the shell or `ProtectedLayout`'s own hooks. What still unmounts the
shell is sign-out, and leaving the protected routes altogether (a link to the 404 page).

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
anyway.

**What the proof has to be.** `App.navigation.test.tsx` renders the real route table (`<App />`),
starts an upload and a folder operation through the real Files page, and navigates with links the
header really renders — the bell, then the Files tab — waiting for each destination before asserting.
The Help control on `/files` is a panel button and not a link, so it would have "navigated" without
changing the route. Restoring the key fails the survival tests on their reasons: an aborted signal,
and the in-progress region gone. Others drive a throwing page mid-upload, the same-path recovery,
and sign-out — which must still abort the upload, or a fix that hoisted the providers above the auth
gate would pass the rest. A source check in `App.test.tsx` keeps the lazy routes' keys present and
distinct, since a block copied with its key is the likely way two of them come to share one.

**The Query workspace's runs moved into the shell on 2026-11-06.** They lived in the Query page,
which unmounts on every nav-tab click, so a run's results were gone on the way back and a running
query lost its poller: its batch stopped advancing and its history never settled. The shell's
`QueryRunsProvider` now holds the run engine and its pollers, and the page binds them to its active
tab. Its proof, `App.queryNavigation.test.tsx`, renders `<App />` like the uploads' and **the
provider must not go into the shared test harness**: placed there it sits above `<App />` too, and
the proof passes with the shell's own provider deleted. The workspace suites wrap themselves
instead, as the upload suites do. Keying the shell's provider on the route turns both of its tests
red.

## History

### 2026-11-06

- **Extended:** the Query workspace's runs joined the shell.

### 2026-09-10

- **Settled:** entered the register.

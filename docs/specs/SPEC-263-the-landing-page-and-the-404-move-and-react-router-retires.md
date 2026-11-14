---
type: Spec
id: SPEC-263
title: "The Landing Page and the 404 Move, and React Router Retires"
description: "Serves the landing page and the 404 from the App Router, deletes react-router and the optional catch-all, collapses the navigation seam and the test harness onto Next.js alone, and stops a malformed percent-escape in a path from answering 500, closing the arc."
spec_status: Draft
depends_on: [SPEC-262]
arc: nextjs
arc_order: 9
---

**Dependency notes:** SPEC-262 (the browser signs in through the server: the auth provider on the
session routes, so the landing page's sign-in and sign-up start `GET /auth/login`, and a failed or
cancelled sign-in comes back to `/?signin=failed`; this spec moves the landing page as 262 leaves
it and follows whatever 262 settled for those two routes: the auth provider reads `?signin=failed`,
shows the message and drops the parameter). Through 262 it rests on SPEC-256, as built in #977 (the
shell in the root layout; the navigation seam in `src/lib/navigation/`; the area records in
`src/lib/navigation/areas/` and the views in `src/routes/areas/`; the record-and-page guard in
`areas/areas.test.ts`; the page sweep `src/app/pageSweep.test.ts`; `renderApp` with its `routers` and
`pages`; the stand-in `src/test/nextNavigation.ts` with `hold`, `requests()` and `external()`; the
fence's tests `eslintConfigShape.test.ts`, `navigationFence.test.ts` and `reactRouterSweep.test.ts`),
whose delivery doc is `docs/spec-delivery/SPEC-256-…`, and on SPEC-258 to 261, which leave every
signed-in area on the App Router, so the catch-all serves only `/` and unknown paths. It also rests on
SPEC-255's image (`apps/portal/Dockerfile`) and its matrix (`.github/scripts/spa-image-matrix.sh`),
which FR-006 changes. The arc's charter is `ARCS.md` →
*Next.js arc (SPEC-255 → 263)*.

## Overview

After the four area moves and the session cutover, react-router renders two pages: the landing page
and the 404, both through the optional catch-all that SPEC-255 mounted to host the old app. This
spec moves those two pages onto the App Router and then removes everything the coexistence needed:
the catch-all, react-router itself, the route table, the half of the navigation seam that decided
between two routers, the per-area record of which router serves an area, and the test machinery
that let a test choose a router. What a user sees does not change, with two exceptions that are
corrections: an address that matches no page now answers with status 404 instead of a 200 that
rendered the not-found page, and a request whose path carries a malformed percent-escape answers
400 instead of a 500 that carried no security headers and logged nothing. The arc ends here.

## Scope

### In Scope

- `src/app/page.tsx` (the landing page) and `src/app/not-found.tsx` (the 404), each loading its
  page through `next/dynamic` with `ssr: false`, outside the sign-in gate and without the shell.
- Deleting `src/app/[[...slug]]/`, `src/routes/table.tsx` and its test, the seam's
  `CatchAllRouter`, and `react-router` from `apps/portal/package.json` and the lockfile.
- The seam on `next/navigation` alone: one rule for which navigations are native, `useParams` from
  Next only, its own path matcher, and the area records without a `router` field.
- The test harness without react-router: `renderWithProviders`' `path` and `routes` on the seam's
  matcher, and `renderApp` without its `routers` option.
- The lint and source guards that held react-router to the seam, replaced by a source sweep with no
  exemption and a manifest check.
- The lazy views' static keys and the check that no two share one, which existed only because
  react-router rendered sibling routes into one slot.
- 255's image matrix row that pins the catch-all's trap (a removed root-level file answering 200
  HTML, `.github/scripts/spa-image-matrix.sh`) rewritten to the 404 it now gets, and every document
  or decision 255 wrote that records that 200.
- A request whose path carries a malformed percent-escape answers 400 with the security headers
  and logs a line, whichever page, route handler or not-found would serve it, with or without a
  body: a guard ahead of Next in the image, and 255's image matrix row that pins the 500 reversed
  (FR-006).
- At completion: the decisions and documents that describe the coexistence, named in Phase 4.

### Out of Scope

- **Any change to sign-in, sign-up or the session.** The landing page's buttons and its failure
  message are 262's; this spec moves them unchanged.
- **Any change to a signed-in page, a view or the shell**, beyond removing the lazy views' static
  keys (FR-002).
- **255's `/_next/` route handler.** It stays. Measured with no catch-all and no handler, a missing
  file under `/_next/static/` already answers `404 text/plain`, so the handler now matters only for
  a non-static `/_next/` path, which would otherwise get the not-found page's HTML; retiring it
  would also change what 255's image matrix asserts about its `Cache-Control`.
- **The `next/navigation` stand-in's eight modelled behaviours.** Every one is still a behaviour the
  seam rests on, since same-page navigations stay native.
- **Next's file conventions beyond `page.tsx` and the root `not-found.tsx`.**

---

## Functional Requirements

### FR-001: The landing page and the 404 are App Router pages

#### Description:

`src/app/page.tsx` loads the landing page and `src/app/not-found.tsx` loads the not-found page, each
through `next/dynamic` with `ssr: false`, under the page sweep's rules (no static import of the app
graph, no props). The chrome already treats `/` and every path no record claims as public, so both
render bare, outside the gate, with the header suppressed on `/` as today. The landing page keeps
every behaviour it has: signed out, it offers sign-in and sign-up through the session routes as 262
left them and shows "Sign-in failed or was cancelled." on `/?signin=failed`; signed in after a
sign-in, it sends the user on to the saved return path with a replace; signed in with no return
path, it offers the first enabled destination; and with every feature off, it shows the unavailable
page. Next answers an address that matches no page with the not-found page and status 404, where
the catch-all answered 200. `src/app/page.tsx` cannot coexist with the optional catch-all at the
same level, so this FR and the catch-all's deletion (FR-002) land in one change.

#### Acceptance Criteria:

- [ ] Through `renderApp`, `/` signed out renders the landing page with its sign-in and sign-up
      controls and no shell; 262's failure signal, as 262 left it, shows "Sign-in failed or was
      cancelled." on the new page; an unknown path renders the not-found page with no shell, signed
      in or out.
- [ ] Through `renderApp`, a signed-in user arriving at `/` with a saved return path of
      `/files?space=finance` lands on Files at that address by a `'REPLACE'`, and the saved path is
      cleared; with none saved, the first enabled destination's control navigates to it.
- [ ] With either page file deleted, its test turns red, and the page sweep covers both files.
- [ ] `next start` answers `/` with 200 and `/no-such-page` and `/files/extra` with 404, each
      carrying the not-found page and the request's CSP nonce. Measured while authoring on a
      harness with no catch-all and a nonce-setting proxy: both paths, `/Files` and `/nope.svg`
      answered 404 with the not-found page outside the shell, signed in and out, every script
      carried the response's nonce, and a client-side `not-found.tsx` loading its page through
      `next/dynamic` rendered without error.
- [ ] 255's image matrix asserts 404 for a removed root-level file, and passes against the image.

### FR-002: React Router and the catch-all are gone

#### Description:

`src/app/[[...slug]]/` (its page and `CatchAllMount`), `src/routes/table.tsx` and its test,
`CatchAllRouter` and `react-router` itself are deleted, and the page sweep loses its case for the
catch-all's directory (it keeps every other). The lint pattern that held react-router to the seam
and its two exemption clauses come out of every `no-restricted-imports` clause, since there is
nothing left to exempt, and `navigationFence.test.ts`, which lints a planted import in each place to
prove the seam, the table and the harness were the only ones allowed it, goes with them. What holds
the removal is `reactRouterSweep.test.ts`, now with no exempt place, and a check that `package.json`
names no package whose name begins `react-router`. The sweep matches any module specifier beginning
`react-router` (so `react-router-dom` and `react-router/dom` too), and both guards build that name at
runtime rather than spelling it, so neither finds itself. The lazy views keep their `ErrorBoundary`
and `Suspense` but lose their static keys, because each area is its own App Router segment and Next
remounts a page's subtree when the segment changes, measured while authoring 256; the check that no
two keys collide, and its planted copy, go with them. Of `table.test.tsx`'s other tests, the
override-context one (no route built for an area the App Router serves) goes with the override, and
the rest move rather than vanish: the landing page, the 404, the chunk failure, `/Files` answering
the not-found page signed in and signed out with no redirect, and `/fil%65s` sending a signed-out
user to `/`, since the gate still matches the decoded path.

#### Acceptance Criteria:

- [ ] None of the deleted files exist, `npm ls react-router` reports nothing, and the source sweep
      finds no module specifier beginning `react-router` under `src/`, its own file included.
- [ ] Adding `react-router` or `react-router-dom` to `package.json` fails the manifest check, and
      adding an import of `react-router` or `react-router/dom`, a dynamic import or a `vi.mock` of
      it to any file fails the sweep, each observed.
- [ ] `eslintConfigShape.test.ts` passes with the react-router pattern gone from every clause and
      every other group intact, and fails if an exemption clause 256 added survives.
- [ ] The production build's `.next/static` contains no react-router `Router`: a string only it
      ships ("You cannot render a <Router> inside another <Router>") is found in a build made before
      the package is removed and in none after. A one-off check by the builder, not a standing
      rule: the manifest check and the sweep are what hold the removal.
- [ ] After a lazy page's chunk fails to load, navigating to another lazy page shows that page and
      no stale error, through `renderApp`.
- [ ] `/Files` renders the not-found page signed in and signed out, the signed-out one staying at
      `/Files`, and `/fil%65s` sends a signed-out user to `/`, through `renderApp` on the App Router;
      each turns red with the gate matching case-insensitively or on the undecoded path.

### FR-003: The seam runs on `next/navigation` alone

#### Description:

The seam keeps every rule 256 gave it that concerns the App Router (the committed address as a
navigation's source, normalized comparison, the per-entry key, traversals classified while they
render, an expected navigation accepted only while it can still be the one rendering, so a push Next
dropped is never taken for Back, an in-page anchor's entry made restorable, state held in memory,
decoded params, in-app targets only, checked as written and once resolved with doubled slashes
collapsed, and the scroll statement) and loses the one that concerned react-router: a navigation
is written natively when it keeps the committed pathname, and goes through `router.push` or
`router.replace` otherwise. The old rule cannot survive the catch-all: it wrote a navigation between
two paths no record claims natively, which was right while one catch-all page rendered both, and is
wrong once `/` and the 404 are separate App Router pages. Measured while authoring, with the
catch-all gone and the old rule kept, a link from the 404 to `/` left the not-found page on screen
under `/`; with the new rule, every navigation among `/`, the 404 and a signed-in page, and Back
through them, showed the right page. `useParams` returns Next's parameters, decoded once.
`matchPath` is the seam's own: static segments, `:name` parameters and `end: false` prefix matching,
the three shapes `linkFlags.ts` and the gate's `areaOf` use. It matches case-sensitively, as 256
already made the seam do, and returns each parameter as it stands in the path it was given except
that `%2F` becomes `/`, exactly as react-router's `matchPath` does today (read in its source:
`a%40b` comes back as `a%40b`). It decodes nothing itself: `linkFlags.ts` and `areaOf` hand it the
path `decodePath` has already decoded segment by segment, keeping an encoded slash as `%2F`, so what
they read does not change. The area records keep `area` and `paths` and lose
`router`, so `routerFor`, the override context behind it and the record-and-page guard's
`'catch-all'` clauses go; the guard now fails when a record's path has no page under
`src/app/(signed-in)/`, or a page there serves a path no record claims.

#### Acceptance Criteria:

- [ ] `matchPath` agrees with every case `linkFlags.ts`'s tests and the gate exercise, and with a
      fixture corpus of static, parameterized, encoded (`%40`, `%2F`), mis-cased and prefix patterns,
      asserted on the params it returns as well as on whether it matched; the corpus is run once
      against react-router's `matchPath` with `caseSensitive: true` before the package goes, and
      every row agrees.
- [ ] A navigation between two pages calls `router.push`; a search-only, hash-only or same-address
      one calls neither `router.push` nor `router.replace`, each asserted on the call made.
- [ ] From the not-found page, a link to `/` shows the landing page, and Back shows the not-found
      page again; with both public paths written natively instead, the landing page never renders,
      observed red, which `renderApp` can show only because it selects the page from the stand-in's
      router state as 256 requires.
- [ ] The seam's tests from 256 that do not mention the catch-all pass unchanged in what they
      assert: the committed address as source, keys, navigation types, state, traversals, the
      anchor, normalization, decoding, case-sensitive matching and in-app targets. Three of them
      mix the two routers and are retargeted to App Router pages, each still red under its mutant:
      the dropped push read as Back (accepting an expectation without checking it can still be
      rendering), the router navigation whose state survives a native one rendering ahead of it,
      and the in-flight push, whose second navigation becomes a search-only change to the pending
      target, so a seam that took the pending navigation rather than the committed address as its
      source would write it natively and leave the first page on screen.
- [ ] The record-and-page guard fails for a record path with no page and for a page no record
      claims, each against a fixture, and passes on the tree.

### FR-004: The test harness has one router

#### Description:

`renderWithProviders` and `renderHookWithProviders` drop their `CatchAllRouter`. `path` keeps its
meaning, now by setting the pattern the stand-in matches the address against, so its
`useParams` returns that match's raw values, encoded as Next's are, and the seam decodes them once;
`routes` renders, for the current address, the element whose pattern the seam's matcher accepts, so
a test whose subject navigates away still sees where it went. `renderApp` loses `routers` (its
`'as-recorded'` with it) and the harness its `CATCH_ALL_RECORDS` fixture, keeps
`pages`, and renders `src/app/not-found.tsx` when no page matches, as Next does. Every test that
used `routers`, or ran on the fixture's catch-all by default, runs on the App Router: a test that ran in both routers keeps its App
Router half, a test that ran on the catch-all alone or crossed the two runs between App Router
pages, and one left duplicating another is deleted. The seam's tests of the catch-all go: the move
between two catch-all pages, the first render of a catch-all page after an App Router page, and the
sweep for a `BrowserRouter`, `MemoryRouter` or `HashRouter` under `src/`, which the react-router
sweep now covers whole. The `ROUTERS` rows of the seam's `it.each` tests keep their App Router row.

#### Acceptance Criteria:

- [ ] A test using `path: '/data-quality/:space/:requestId'` at `/data-quality/50%2525/r1` reads
      `{space: '50%25', requestId: 'r1'}` through the seam's `useParams`, decoded once and without a
      `URIError`, and one using `routes` sees the destination element after a navigation, with no
      react-router in `src/test/`.
- [ ] `renderApp` at an address no page serves renders the not-found page.
- [ ] The test names collected from the runner before and after this spec differ by exactly the
      removals, moves and additions the plan lists, diffed from a JSON run on both refs.
- [ ] `vite.config.ts`, `src/test/` and the split test files name no `[[...slug]]`,
      `CatchAllRouter`, `CatchAllMount` or `routers` option, and the test-utilities inventory no
      longer offers `routers`.

### FR-006: A malformed percent-escape answers 400, not 500

#### Description:

A request whose path has a percent-escape that does not decode, a `%` not followed by two hex digits
(`/%ZZ`, `/files%`) or bytes that are not UTF-8 (`/%E0`, `/nope/%E0%A4`), answers 400 with the
security headers and the lockdown policy, and writes one log line, whichever page, route handler or
not-found would serve the path, with or without a body. Measured on `main`'s standalone server while
authoring: every such path answered 500 with a plain body, no policy and none of the security
headers, and logged nothing, `/data-quality/%E0/r1` on 261's report page and `/_next/%E0` among them,
GET and POST with a body alike; `/data-quality/a%40b/r1` (escapes that decode) and `/query?x=%E0` (the
escape in the query, which no router decodes) answered 200. 255's image matrix pins that 500 as an
accepted residual, and this FR reverses it. Next means to answer these 400, as its source reads: its
router catches the decode failure and renders the pages router's `/_error` at 400. An App Router-only
build has no `/_error` (its `server/pages/` holds only `500.html`), so the answer is 500 instead.

A guard ahead of Next answers them: `apps/portal/server-guard.cjs`, which the image starts in place of
`server.js`. It wraps the request listener Next's standalone server creates, by replacing
`http.createServer` before it requires `server.js`. It tests the request target's path segment by
segment, and when one does not decode it answers 400 with `SECURITY_HEADERS`, `LOCKDOWN_POLICY` as the
`Content-Security-Policy`, a plain-text body and `Connection: close`, and writes `request: refused a
path with a malformed percent-escape (<method>)`. The line names the method and not the path, since
the path is the caller's text. It reads no body, so a request with a body is answered at once and
never held, and everything else passes to Next untouched. Measured while authoring with that wrapper
around `main`'s standalone server: the GET corpus, `/_next/%E0` and `/_next/static/%E0` included, and
POSTs with a body to `/api/%E0`, `/auth/%E0` and `/data-quality/%E0/r1` each answered 400 with the
policy and `nosniff`, and one line each. The valid paths answered as before. A request declaring a
gigabyte to `/files/%E0` and sending one byte was refused at once, and `/healthz` answered beside it.
The proxy cannot be the guard: it runs only for requests without a body, as the CSP decision
requires, since a proxy-matched request with a body holds every path until its body arrives. A pages
router `_error` and `_document`, added to make Next's own 400 work, did not build here (`next build`
stopped on "Cannot find module for page: /_document"), and would bring back a second router as this
spec removes one.

The guard's headers come from `src/lib/securityHeaders.ts`, the one definition `next.config.ts` and
the proxy read, held equal by a unit test, since the guard is plain JavaScript outside the build. It
depends on Next's standalone server creating its listener through `http.createServer`, which the image
matrix holds: a Next upgrade that stops doing so turns the matrix's 400 rows red rather than silently
restoring the 500. `next start` does not run the guard; the proof is the standalone server the image
runs.

#### Acceptance Criteria:

- [ ] A unit test of the guard's check passes `/`, `/files`, `/data-quality/a%40b/r1`, `/files/a%2Fb`,
      `/%2e`, `/query?x=%E0` and an absolute-form target, refuses `/%ZZ`, `/files%`, `/%E0`,
      `/nope/%E0%A4`, `/_next/%E0` and `/data-quality/%E0/r1`, and goes red with the check removed or
      with the whole path decoded at once.
- [ ] A unit test asserts that the guard's 400 carries every `SECURITY_HEADERS` entry and
      `LOCKDOWN_POLICY` as they stand in `securityHeaders.ts`, and that its log line names the method
      and contains no part of the path; changing a header in either place turns it red.
- [ ] 255's image matrix row for `/%zz` asserts 400, the lockdown policy and `nosniff`, with rows for
      `/data-quality/%E0/r1`, `/_next/%E0` and a POST with a body to `/api/%E0`, and a row that
      `/data-quality/a%40b/r1` still answers 200. The matrix goes red against an image built with the
      `CMD` back on `server.js`, observed once.
- [ ] The image matrix's bodied-request section gains a row in which a request declaring a large body
      to a malformed path and sending one byte is answered 400 at once, while the health probe
      answers.

### FR-007: Checked live, on the tier

#### Description:

The build switches the web tier on through the repository variable and CI, runs these checks, and
switches it off again, saying so in its report; it agrees the window with the arc's orchestrator if
another session's live checks may overlap.

#### Acceptance Criteria:

- [ ] Signed out, `/` offers sign-in; signing in from a deep link to a Files folder returns to that
      folder; a cancelled sign-in comes back to `/` with "Sign-in failed or was cancelled.".
- [ ] `/no-such-page` shows the not-found page with status 404, outside the shell, signed in and
      out.
- [ ] `/data-quality/%E0/r1` answers 400, and its log line reaches the web tier's log group.
- [ ] Every area opens from the header, Back and Forward move between them without a document
      reload, and each page keeps its own tab title.

---

## API / Interface Contract

```tsx
// src/app/page.tsx — and src/app/not-found.tsx, the same shape around the not-found page
'use client';
import dynamic from 'next/dynamic';

const LandingPage = dynamic(() => import('../routes/LandingPage'), {ssr: false});

export default function Page() {
  return <LandingPage />;
}
```

```ts
// src/lib/navigation/matchPath.ts — the seam's own; same signature 256 gave it
export function matchPath(
  pattern: string | {path: string; end?: boolean},
  pathname: string
): {params: Record<string, string | undefined>} | null;

// src/lib/navigation/areas/area.types.ts — `router` is gone
export type AreaRecord = {
  area: 'files' | 'notifications' | 'help' | 'query' | 'explore' | 'connections' | 'data-quality';
  paths: readonly string[];
};
```

## File & Folder Structure

```
.github/scripts/spa-image-matrix.sh  the malformed-escape rows at 400 (FR-006)
apps/portal/
├── Dockerfile                        copies the guard; CMD starts it instead of server.js
├── server-guard.cjs                  new: refuses a malformed escape ahead of Next (FR-006)
└── src/
apps/portal/src/
├── app/
│   ├── page.tsx                      new: the landing page
│   ├── not-found.tsx                 new: the 404
│   ├── publicPages.test.tsx          new: the landing, 404, `/Files`, `/fil%65s` and chunk-failure
│   │                                 tests moved from table.test.tsx
│   └── [[...slug]]/                  deleted
├── lib/navigation/
│   ├── CatchAllRouter.tsx            deleted
│   ├── navigationFence.test.ts       deleted
│   ├── NavigationProvider.tsx        one native rule, no router lookup
│   ├── matchPath.ts                  the seam's own matcher
│   └── areas/                        records without `router`; the guard without 'catch-all'
├── routes/
│   ├── table.tsx                     deleted
│   ├── table.test.tsx                deleted
│   └── areas/*.tsx                   views without static keys
└── test/
    ├── reactRouterSweep.test.ts      no exempt place, plus the manifest check
    ├── renderWithProviders.tsx       no CatchAllRouter; `path` and `routes` on the seam's matcher
    └── appRouter.tsx                 no `routers`
```

## Implementation Phases

### Phases 1 and 2 land as one change

Deleting the catch-all with the old native rule still in place is the measured state in which a
link from the 404 to `/` leaves the 404 on screen, and every `routers: {…: 'catch-all'}` test loses
the page it renders; so the two phases below are built together and land in one change.

### Phase 1: The two pages, and the catch-all gone

- `src/app/page.tsx` and `src/app/not-found.tsx`, with the catch-all's directory deleted in the same
  change; the landing, 404, `/Files`, `/fil%65s` and chunk-failure tests moved out of
  `table.test.tsx` into `src/app/publicPages.test.tsx`.

### Phase 2: The seam and the harness on one router

- The native rule, `useParams`, the seam's `matchPath` and the records without `router`; the guard
  simplified; `CatchAllRouter` and the table deleted.
- `renderWithProviders`' `path` and `routes` on the matcher; `renderApp` without `routers`; the
  catch-all halves and tests removed, and the runner's test names diffed.

### Phase 3: react-router removed

- The package and lockfile entry, the lint pattern and its exemption clauses with
  `navigationFence.test.ts`, the views' static keys and their check; the source sweep without
  exemptions and the manifest check; the bundle check.

### Phase 4: The malformed escape

- On `main` first, against the standalone server, the 500 measured again for the FR-006 corpus;
  then the guard, its unit tests and the Dockerfile, and the same corpus against the standalone
  server under the guard answering 400 with the headers and one log line each; then the image
  matrix's rows, run against the image.

### Phase 5: The production build, the live checks and the record

- `next build` and `next start` locally, then the live checks on the tier.
- The decisions rewritten in place with History entries:
  `browser/layout-boundaries-reset-by-prop-never-by-key-a-signed-in-pages-sits.md` (no keyed lazy
  routes; the proof's table is the file system alone);
  `browser/react-router-in-the-catch-all-is-a-matcher-the-navigation-seam-feeds.md`, whose
  react-router half becomes history while the eight Next behaviours the seam rests on stay its live
  claim, since the seam still rests on all eight (rewritten in place under its name, as every
  reversal is); and `infrastructure/response-headers-csp.md`, which gains the guard. `CLAUDE.md`'s
  routing row, `docs/architecture.md`'s routing sentence, the foundations inventory's seam rows and
  the notifications inventory's `NavLink` row, the test-utilities inventory's `renderApp` row,
  `react.md` §21's harness line, the cross-router steps 256 to 261 wrote into `docs/testing/e2e.md`
  (256's block in §4.1 among them), 255's records of the catch-all's 200, and
  `docs/security-baseline.md`'s react-router passages (the open-redirect protection is now the
  seam's in-app rule) and its "answered before routing" row, which loses the malformed escape (a
  trailing slash's 308 and `OPTIONS *` stay in it), brought up to date, and the arc's entry in
  `ARCS.md` closed.

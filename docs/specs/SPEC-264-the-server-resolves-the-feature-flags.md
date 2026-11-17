---
type: Spec
id: SPEC-264
title: "The Server Resolves the Feature Flags"
description: "The Next.js server resolves the feature flags and sends them with the page, so a signed-in tab starts with its flags instead of fetching them after sign-in, and a disabled area's page is decided on the server without loading its code."
spec_status: In Progress
depends_on: [SPEC-162, SPEC-163, SPEC-262, SPEC-263]
---

**Dependency notes:** SPEC-162 (the flag document, its resolver and `useFeatureFlags`). SPEC-163 (the
registry of gated surfaces, `GATED_SURFACES`, whose `route` rows this spec reads, and `FeatureRoute`,
which stays). SPEC-262 (the browser signs in through the server, so every signed-in request carries
the session cookie and the server holds an ID token to read the document with; before it, the browser
holds the tokens and the server has no session to read with). SPEC-263 (the arc's last move: the
landing page on the App Router and react-router gone, so the pages, `PortalBoot` and `AppFrame` this
spec edits have stopped moving). The arc's charter is `ARCS.md` → *Next.js arc (SPEC-255 → 263)*;
this spec relaxes one line of it (FR-005).

## Overview

Today a signed-in tab learns its feature flags late. The page loads, the browser asks the server who is
signed in, and only then asks the API for the flag document, so every gated tab, control and page
waits on a second round trip to an API Lambda that may be cold after a quiet spell. A page whose feature is
turned off downloads its code and then shows the "not available" page in its place. After this spec
the Next.js server resolves the flags and sends them with the page. A signed-in tab renders its
navigation and its gated controls from the first frame, makes no request for the flags when it
starts, and a page whose feature is off is answered by the server with the "not available" page,
without the browser loading that area's view. A flag is still presentation and never
authorization: the API enforces access exactly as it does today, and nothing here gates a request.

## Scope

### In Scope

- One resolver for the flag document, used by the browser's service and by the server (FR-001).
- A server-only module that holds the resolved flags, refreshes them in the background through the
  existing API route with the requesting session's token, and never makes a page wait on the API or
  on Cognito (FR-002).
- The root layout sends the held flags with the page, and the boot seeds them into the browser's
  query cache, so `useFeatureFlags` is `'ready'` from the first render (FR-003).
- A server layout per gated area that answers a disabled area with the "not available" page instead
  of the area's page, read from the registry's `route` rows (FR-004).
- The flag decision and the arc charter rewritten where this spec makes them false (FR-005).
- A live check on the tier (FR-006).

### Out of Scope

- **Any change to the API, the flag document, its publishing workflow or its route.** The server reads
  `GET /v1/feature-flags` as the browser does; no route, IAM, CSP or infrastructure changes.
- **Sending the signed-in user with the page.** The shell still waits on `/auth/session` before it
  renders a signed-in page. That is SPEC-262's surface, and the round trip this spec removes is the one
  after it.
- **Server rendering of any area's data or view.** Pages stay client components reached through
  `next/dynamic` with `ssr: false`; the only thing the server resolves is the flag document.
- **Gating nav items, controls or Help guides on the server.** They stay in the browser and read the
  seeded set through `useFeature`, `FeatureGate` and `useCanFollowLink`, as today.
- **Per-user flags.** The document is the same for every signed-in user, which is what lets one held
  set serve all of them.
- **`FeatureRoute` retiring.** It stays as the browser's gate for a page rendered without a server
  answer (FR-002's cases), and for a tab whose own set has changed since the page loaded.
- **The client's one-hour `staleTime`, and telling an open tab that a flag changed.** An open tab
  picks up a published change as it does today.
- **An HTTP status for a disabled page.** It answers 200 with the "not available" page, as today.

---

## Functional Requirements

### FR-001: One resolver, two callers

#### Description:

The parsing and resolution in `featureFlags.service.ts` (the version check, the defaults block, the
named environment's overrides, the per-key fallback to the compiled-in defaults, and the reading of an
empty body as no document) moves unchanged into
a pure module, `resolveFeatureFlags.ts`, beside it. That module imports only the flag types, the
defaults and `lib/serviceResult`, and nothing that reaches the network, React or configuration. The
browser's `getFeatureFlags` calls it on the body the API returned. The server calls the same function,
so a document can never resolve one way in the browser and another way on the server.

#### Acceptance Criteria:

- [ ] `resolveFeatureFlagDocument(body, environment)` returns exactly what `getFeatureFlags` returned
      before the move for every case in `featureFlags.service.test.ts`: the test file's cases pass
      against the pure function, and the service's own tests still pass against the service.
- [ ] `resolveFeatureFlags.ts` imports nothing outside `featureFlags.types.ts`,
      `featureFlagDefaults.ts` and `lib/serviceResult`, asserted by a test over its source.
- [ ] The server resolves a body only through `resolveFeatureFlagDocument`: with that function mocked
      in `src/server/featureFlags.test.ts` to return a sentinel set, the held set after a refresh is
      the sentinel, and with it mocked to refuse, nothing is held.

### FR-002: The server holds the resolved flags and never waits on the API for them

#### Description:

`src/server/featureFlags.ts` (beginning `import 'server-only'`) holds one resolved set per server
process, shared by every user because the document is bucket-wide. The set holds the resolved flags
and the time the API answered, and never a token. Only the root layout reads a session for it, once
per document load; the area layouts (FR-004) read the held set and do no I/O, so moving between areas
costs the server nothing it does not cost today.

**`serverFeatureFlags()`, for the root layout.** It reads the session cookie with `readCookie`'s own
parsing (which refuses the padding that would spoof the `__Host-` prefix), run over
`headers().get('cookie')`, never Next's `cookies()` parser: `readCookie` is split so its loop takes a
header string. It gets its store and configuration from `environmentDeps()`, and reads the session
with a new `peekSession` in `session.ts`: one store `get`, the same `createdHere` and session-expiry
checks `loadSession` makes, and no refresh, no delete and no write. Because it never refreshes, it also
answers no session when the stored ID token has expired or names no user (`userOf`), which is how a
user the provider has revoked stops getting flags without a Cognito call. A peek that finds no
session, an expired one or a fault answers no session. So the time a document load spends here is bounded by one
store read and its existing 2-second cap, and never a Cognito call. **It never rejects:** anything
that throws, `environmentDeps()`'s `SessionConfigError` included, becomes `undefined` after one log
line, because a throw in the root layout answers 500 on every page. A request with no session gets
`undefined`: no flags are sent to a signed-out visitor.

For a request with a session, by the held set's age:

- **Younger than 60 seconds:** answered as is.
- **Between 60 seconds and one hour:** answered as is, and a background refresh starts.
- **Older than one hour, or no set held** (a task that has just started): no answer, and a background
  refresh starts. One hour is the browser's own `staleTime`, so the server never sends a set staler
  than a tab would already hold.

**A background refresh** is never awaited by the render. It starts only when the session's ID token
has at least 60 seconds left (a peek never refreshes one), and otherwise waits for the next request.
It calls `GET <apiOrigin>/v1/feature-flags` with that token as the bearer, the target checked to have
the API's origin as `apiTarget` does, `cache: 'no-store'` (Next patches `fetch`), a 10-second
deadline, and redirects not followed. A 2xx answer is the API's envelope, `{body: string, etag}`: the
refresh takes `body`, refuses an answer that is not an object with a string `body`, and hands `body`
to FR-001's resolver for the server's environment (`CONFIG_environment`, the value the browser's
runtime document carries). Only one refresh is in flight per process: a request arriving during one
starts no other.

**What lives in module scope** is the held set, the time of the last failure and a boolean saying a
refresh is in flight, and nothing else. The token is a local of the refresh function, never captured
by a module-scope promise or closure. None of these is session state: the set is the same document
for every user, which is why the session decision's "nothing about a session lives in module scope"
still holds (FR-005 says so).

A refresh that fails keeps the held set as it was, logs one line naming the reason and never the
token or the body, and no new refresh starts until 60 seconds after the failure. Failing means no
answer, a non-2xx, a redirect, an envelope it refuses, or a body the resolver refuses. A 404, the
document never published, is a failure like the others: the browser's service already calls a missing
document a deploy defect, and the 60-second pause is what bounds its log to one line a minute per task.
The API reads the document under the calling user's own grants, so one user whose read is refused
pauses refreshes for every user on that task for a minute, which costs only freshness.

**`heldFeatureFlags()`, for the area layouts.** Synchronous, no I/O: the held set if it is younger
than one hour, `undefined` otherwise. It starts no refresh, having no token to start one with.

Nothing on the API pass-through may consult the flags: no route handler, the request proxy or any
module under `src/server/session/` imports this one, because a flag gating a request would be
authorization.

#### Acceptance Criteria:

- [ ] `serverFeatureFlags()` given no session cookie, a cookie `peekSession` finds absent or expired,
      or a store that throws, returns `undefined` and makes no API request; with `environmentDeps`
      throwing `SessionConfigError` it returns `undefined` and logs one line.
- [ ] A cookie padded with U+00A0 before `__Host-` is not read as the session cookie (the case
      `cookies.test.ts` already asserts for `readCookie`, run through the header-string path).
- [ ] `peekSession` on a session whose token expires within 300 seconds returns it as found and makes
      no Cognito call and no store write (both counted). It answers `none` for a stored token that has
      expired, for a token that names no user, and for a session another client created.
- [ ] With a session and no held set, the first call returns `undefined` and starts exactly one API
      request with `Authorization: Bearer <that session's ID token>` and `cache: 'no-store'`; once it
      answers `{body, etag}`, the next call returns the set resolved from `body`.
- [ ] With a session whose token has 30 seconds left and no held set, no API request starts.
- [ ] Ten concurrent calls with no held set start one API request, not ten.
- [ ] On a fake clock: a set 30 seconds old is returned with no API request; one 5 minutes old is
      returned and starts one refresh; one 61 minutes old returns `undefined` and starts one refresh.
- [ ] Each of a 500, a 404, a timeout, a 302, an answer `{}` and a body with `version: 2` leaves a held
      set unchanged and logs one line naming the reason that contains neither the token nor the body.
      After each, a call 59 seconds after the failure starts no request and one 61 seconds after it
      starts one; for the timeout, the 60 seconds count from the deadline.
- [ ] With the API stubbed never to answer, `serverFeatureFlags()` settles without waiting on it.
- [ ] After a successful refresh, `serverFeatureFlags()` returns a value equal (`toEqual`) to
      `{flags, readAt}` and nothing more, and its `JSON.stringify` does not contain the refreshing
      session's ID token.
- [ ] `heldFeatureFlags()` returns a 30-minute-old set, returns `undefined` for a 61-minute-old one,
      and makes no request and no store read in either case.
- [ ] No file a request to the API passes through imports `src/server/featureFlags.ts`: every
      `route.ts` under `src/app/`, `src/proxy.ts`, and everything under `src/server/session/`, asserted
      by a test over their sources whose fixture corpus includes a `route.ts` that imports it and must
      fail. The module begins with `import 'server-only'`, which `serverOnly.test.ts` already enforces.

### FR-003: The page carries the flags and the boot seeds them

#### Description:

The root layout awaits `serverFeatureFlags()` and passes the result, the flags and the time the API
answered, to `PortalMount` as a `flags` prop, which passes it through `PortalBoot` to the frame.
`PortalBoot` types the prop inline, because its import sweep counts type imports too. When a set is
present, `AppFrame` calls `seedServerFlags(queryClient, environment, seeded)` before its first render.
That function, in `features/feature-flags/`, writes the set under
`featureFlagKeys.resolved(environment)` with `updatedAt` set to the time the API answered, and is the
one place the seed is written. The set passes from server to client as a prop and through no
module-scope read, so the boot's rule that nothing of the application graph evaluates before the
runtime document arrives still holds.

`useFeatureFlags` reports `'ready'` while auth is still resolving whenever the query holds data, so a
seeded tab renders its gated surfaces from the first frame rather than waiting for `/auth/session`.
Every other state is unchanged: with no data, auth resolving is still `'loading'`; a signed-out tab is
still `'fallback'`. Because the seeded data is fresh, the query does not fetch when the tab starts. A
page sent with no set (FR-002's `undefined`) starts exactly as today.

#### Acceptance Criteria:

These run on a real `QueryClient` built with `AppFrame`'s own defaults, seeded by
`seedServerFlags` and not by the test harness: the harness's own seed sets an infinite `staleTime` on
the flag keys, under which a wrong key or a missing `updatedAt` would still pass.

- [ ] Seeded and with auth still resolving, `useFeature('query')` returns the seeded value on the
      first render and `useFeatureFlags().status` is `'ready'`; seeded under a different environment's
      key, it does not (the control that proves the key is read).
- [ ] Seeded with `readAt` now, no `featureFlags.get` request is made after auth resolves
      (`apiRequest` mocked and counted).
- [ ] Seeded with `readAt` 61 minutes ago, one `featureFlags.get` request is made once auth resolves.
- [ ] With no seed, the hook's states and requests match today's tests in `useFeatureFlags.test.ts`,
      which pass unchanged.
- [ ] `AppFrame` given a `flags` prop calls `seedServerFlags` with it before its first render, and given
      none does not call it (the function mocked and counted).
- [ ] Called directly with `serverFeatureFlags` mocked, the root layout passes the set to `PortalMount`
      as its `flags` prop when one is held and passes `undefined` when none is, asserted on the element
      tree the layout returns. FR-006 checks the same thing in the deployed HTML.
- [ ] `PortalBoot.tsx` gains no import, and the sweep that fails if its import list grows passes
      unchanged.

### FR-004: A disabled area is answered by the server

#### Description:

Each signed-in area that a `route` row in `GATED_SURFACES` names gets a server `layout.tsx` beside its
page: `/files`, `/query`, `/connections`, `/explore` and `/data-quality` (whose layout also covers the
report route beneath it). The layout calls `serverRouteGate(path)` in `src/server/featureFlags.ts`,
which is synchronous, reads `heldFeatureFlags()` and nothing else, finds the flag from the registry's
`route` row for that path (never from a constant in the layout), and never throws. It answers `open`
or `unavailable`.

- **`unavailable`** (a held set with that flag off): the layout renders `UnavailableMount` in place of
  its children, passing the flag and the fallback's flag key. The fallback is computed on the server by
  `firstEnabledDestination`, a helper extracted from `FeatureRoute` that both now call: the first key
  in flag order that is enabled and has a nav destination, or none. `UnavailableMount` is a client
  component beside the pages that reaches `routes/areas/unavailable.tsx` only through `next/dynamic`
  with `ssr: false`, as a page reaches its view, and renders `FeatureUnavailablePage` for that
  feature with that fallback. The area's page is not rendered, so its view is never imported.
- **`open`** (the flag on, or no held set): the layout returns its children unchanged, and the page's
  own `FeatureRoute` still decides in the browser.

The layouts read no session. A signed-out visitor never sees the "not available" page, because the
shell's sign-in gate wraps every signed-in path and sends them to `/`, but the response that carries
it names one flag that is off and its fallback, which is the first enabled key in flag order and so
also says every key before it is off. Across the five area paths a signed-out visitor can piece
together every gated flag. That is accepted: a flag is presentation, the document
is not secret from any signed-in user, and reading a session per area navigation would put a store
read on a path that does no server I/O today.

The layouts sit below the shell, which lives in the root layout, and carry no `key`, so moving
between areas never remounts the shell (the layout-boundary decision).

**One `route` row stays in the browser.** `sharedWorkspaces`' "Shared-space data quality report" row
gates `/data-quality/:space/:requestId` only when the space in the address is a shared one. A layout
reads no `params` (a native navigation leaves them stale, the arc's page rule), so the server cannot
decide that row, and the report page's own browser gate keeps deciding it as today. The registry walk
below names it as its one exemption, with this reason.

#### Acceptance Criteria:

- [ ] Called directly with a held set whose `query` flag is off, `/query`'s layout returns an
      `UnavailableMount` element for `query` and not its children, so the page and its view are never
      rendered; rendering that element shows the "not available" page naming Query.
- [ ] Called directly with the `dataQuality` flag off, `/data-quality`'s layout returns
      `UnavailableMount` for `dataQuality`, which covers the report route beneath it.
- [ ] With every flag off the layout passes no fallback and the rendered page offers no link; with
      only `files` on it passes `files` and the page offers Files; no `featureFlags.get` request is
      made in either case. `FeatureRoute`'s existing fallback tests pass unchanged on the shared helper.
- [ ] Called with the flag on, or with no held set, each layout returns the `children` it was given,
      the same element with no wrapper and no `key` (`toBe`), so the shell above it is untouched; each
      area's existing view tests pass unchanged.
- [ ] With the registry module it imports (`gatedSurfaces.ts`) mocked so the route-row lookup throws,
      `serverRouteGate` answers `open`; with its catch removed, the same test fails (run once during
      the build, then reverted). A same-module mock cannot reach the call, which is why the throw comes
      through the import.
- [ ] A test walks every `route` row of `GATED_SURFACES`. For each, except the one exemption named by
      its row name, a layout exists whose path covers the row's path and answers `unavailable` given a
      held set with the row's flag off and `open` with it on. A new `route` row with no server gate
      fails the walk; so does an exemption whose row has left the registry.
- [ ] `pageSweep.test.ts` changes in two ways. Its neighbour rule, which today holds every file beside
      a `page.tsx` to the page's import allowance, exempts a file named `layout.tsx` and nothing else.
      A new layout rule then holds each `layout.tsx` under `(signed-in)` to importing only
      `src/server/featureFlags.ts`, `UnavailableMount` and React's types, and `UnavailableMount` to
      reaching its view only through `dynamic(…, {ssr: false})`. The fixture corpus gains a failing
      case for each rule, a passing conforming layout, and a failing case for a neighbour named like a
      layout (`layout.ts`, `Layout.tsx`) that the exemption must not cover.

### FR-005: The records say where the flags resolve

#### Description:

Four records state as fact what this spec changes, so they are rewritten in place with a dated
History entry, not appended to.

- `docs/decisions/identity-and-access/a-feature-flag-is-presentation-never-authorization-and-it-lives-beside.md`:
  the flags resolve first on the server and are sent with the page; the browser's read is the second
  line, for a page sent with no set and for a stale tab. The fence keeps "presentation, never
  authorization" and gains the trap this spec creates: **the API pass-through never consults the
  flags**, and a held set shared by every user is correct only because the document is bucket-wide.
- `docs/specs/ARCS.md`, the Next.js arc's charter: "server components are used for layout shells only"
  and "no server rendering of data" gain a dated note that SPEC-264 lets server layouts read one
  document, the flags, after the arc closed, and nothing else.
- `docs/decisions/identity-and-access/the-portal-server-holds-the-session-and-only-the-provider-or-the-clock-ends-it.md`:
  its "nothing about a session lives in module scope" gains the one exception that is not session
  state, the held flag set, and the rule that no token is captured in module scope.
- `docs/decisions/browser/layout-boundaries-reset-by-prop-never-by-key-a-signed-in-pages-sits.md`:
  the signed-in areas now have server layouts below the shell. They carry no `key`, and they never
  throw, because there is no `error.tsx` between them and the root, so a throw in one would answer 500.

`architecture.md` gains an ADR row because a page now carries data the server read from the API.

#### Acceptance Criteria:

- [ ] The flag decision's fence names both the server-first resolution and the rule that the API
      pass-through never consults the flags, and its History has a dated entry citing this spec.
- [ ] The session decision's module-scope rule names the held set as not session state and forbids a
      token in module scope, with a dated History entry.
- [ ] The layout-boundary decision names the area layouts, their no-`key` and never-throw rules, and
      has a dated History entry.
- [ ] Every other place that states that the browser resolves the flags is marked superseded in
      place, found by a grep for `useFeatureFlags`, `featureFlags.get` and "resolved in the browser"
      across `docs/` and `CLAUDE.md`, and the grep's command is in the PR body.
- [ ] `python3 scripts/validate_docs.py` and `sh scripts/gen-index.sh` run clean.

### FR-006: Checked live, on the tier

#### Description:

On the deployed tier, signed in, in Andrew's Chrome, with the flags as published. A flag is not
switched off live: publishing one is a document change through `deploy-config.yml`, and the off path
is proved by FR-004's tests.

#### Acceptance Criteria:

- [ ] Reloading `/files` until a load's HTML carries the flag set (each task warms its own held set,
      so at most the number of running tasks plus one loads), that load's network log shows no
      `/api/v1/feature-flags` request at boot, and the nav rail's tabs are in the DOM on the first
      render after `/auth/session` answers.
- [ ] A signed-out load of `/` carries no flag set.
- [ ] The server's log for the check's window has no flag-refresh failure line.
- [ ] Each check is written into `docs/testing/e2e.md`'s feature-flags section with the date it ran.

---

## Data Model

```ts
// src/features/feature-flags/resolveFeatureFlags.ts
export function resolveFeatureFlagDocument(
  body: string | undefined,
  environment: string | undefined
): ServiceResult<FeatureFlags>;

// src/features/feature-flags/featureFlags.types.ts (added)
/** A set the server resolved, and when the API answered it, epoch milliseconds. */
export type SeededFeatureFlags = {flags: FeatureFlags; readAt: number};

// src/server/featureFlags.ts
export const HELD_FRESH_MS = 60_000;
export const HELD_MAX_AGE_MS = 60 * 60 * 1000;
export const REFRESH_DEADLINE_MS = 10_000;
export const REFRESH_FAILURE_PAUSE_MS = 60_000;
/** A refresh starts only on a token with at least this long left; a peek never refreshes one. */
export const REFRESH_TOKEN_MIN_LIFE_MS = 60_000;

/** For the root layout. Never rejects. */
export function serverFeatureFlags(): Promise<SeededFeatureFlags | undefined>;
/** For the area layouts. No I/O; never throws. */
export function heldFeatureFlags(): SeededFeatureFlags | undefined;

export type RouteGate =
  | {kind: 'open'}
  | {kind: 'unavailable'; flag: FeatureFlagKey; fallback: FeatureFlagKey | undefined};
export function serverRouteGate(path: string): RouteGate;

// src/server/session/session.ts (added)
/** One store read; no refresh, no delete, no write. */
export function peekSession(
  store: SessionStore,
  config: SessionConfig,
  cookieValue: string | undefined,
  now?: number
): Promise<{status: 'active'; idToken: string; tokenExpiresAt: number} | {status: 'none'}>;

// src/server/session/cookies.ts (split)
export function readCookieHeader(header: string | null, name: string): string | undefined;

// src/features/feature-flags/ (added)
export function seedServerFlags(client: QueryClient, environment: string | undefined, seeded: SeededFeatureFlags): void;
export function firstEnabledDestination(isEnabled: (key: FeatureFlagKey) => boolean): FeatureFlagKey | undefined;
```

## API / Interface Contract

```tsx
// src/app/layout.tsx
const seeded = await serverFeatureFlags();
<PortalMount flags={seeded}>{children}</PortalMount>

// src/app/(signed-in)/query/layout.tsx
export default function QueryLayout({children}: {children: ReactNode}) {
  const gate = serverRouteGate('/query');
  return gate.kind === 'unavailable' ? <UnavailableMount flag={gate.flag} fallback={gate.fallback} /> : children;
}

// src/app/(signed-in)/UnavailableMount.tsx ('use client')
const UnavailableView = dynamic(() => import('../../routes/areas/unavailable').then((m) => m.UnavailableView), {ssr: false});
export function UnavailableMount(props: {flag: FeatureFlagKey; fallback: FeatureFlagKey | undefined}) { … }
```

## File & Folder Structure

```
apps/portal/src/
├── app/
│   ├── layout.tsx                       # awaits serverFeatureFlags, passes the set
│   ├── PortalMount.tsx                  # passes `flags` through
│   └── (signed-in)/
│       ├── UnavailableMount.tsx         # new, client
│       ├── files/layout.tsx             # new, server
│       ├── query/layout.tsx             # new, server
│       ├── connections/layout.tsx       # new, server
│       ├── explore/layout.tsx           # new, server
│       └── data-quality/layout.tsx      # new, server; covers the report route
├── PortalBoot.tsx                       # passes `flags` to the frame
├── AppFrame.tsx                         # calls seedServerFlags
├── features/feature-flags/
│   ├── resolveFeatureFlags.ts           # new, pure
│   ├── seedServerFlags.ts               # new, the one writer of the seed
│   ├── gatedSurfaces.ts                 # gains firstEnabledDestination
│   ├── featureFlags.service.ts          # calls the resolver
│   └── useFeatureFlags.ts               # 'ready' with data while auth resolves
├── routes/
│   ├── FeatureRoute.tsx                 # calls firstEnabledDestination
│   └── areas/unavailable.tsx            # new view
└── server/
    ├── featureFlags.ts                  # new, server-only
    └── session/
        ├── session.ts                   # gains peekSession
        └── cookies.ts                   # readCookie split over a header string
```

## Implementation Phases

### Phase 1: The resolver and the server module (inert)

- Move the resolution into `resolveFeatureFlags.ts`; the service calls it (FR-001).
- `peekSession`, the header-string cookie reader, and `src/server/featureFlags.ts` with the held set,
  the background refresh, `heldFeatureFlags` and `serverRouteGate`, with their tests on a fake clock
  and a stubbed API (FR-002). Nothing calls them yet.

### Phase 2: The page carries the flags

- `seedServerFlags`; the root layout, `PortalMount`, `PortalBoot` and `AppFrame` carry and seed the
  set; `useFeatureFlags`'s one state change (FR-003).

### Phase 3: The server gates

- `firstEnabledDestination`, the five layouts, `UnavailableMount`, the unavailable view, the registry
  walk and the page sweep's two changes (FR-004).

### Phase 4: Records and the live check

- The decision and the charter (FR-005); the live check on the tier (FR-006).

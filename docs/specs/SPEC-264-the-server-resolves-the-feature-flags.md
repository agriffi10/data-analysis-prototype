---
type: Spec
id: SPEC-264
title: "The Server Resolves the Feature Flags"
description: "The Next.js server resolves the feature flags and sends them with the page, so a signed-in tab starts with its flags instead of fetching them after sign-in, and a disabled area's page is decided on the server without loading its code."
spec_status: Draft
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
without the browser ever loading that page's code. A flag is still presentation and never
authorization: the API enforces access exactly as it does today, and nothing here gates a request.

## Scope

### In Scope

- One resolver for the flag document, used by the browser's service and by the server (FR-001).
- A server-only module that holds the resolved flags, refreshes them in the background through the
  existing API route with the requesting session's token, and never makes a page wait on the API
  (FR-002).
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
named environment's overrides, the per-key fallback to the compiled-in defaults) moves unchanged into
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

`src/server/featureFlags.ts` (beginning `import 'server-only'`) exports `serverFeatureFlags()`, wrapped
in React's `cache()` so a request computes it once however many layouts ask. It reads the session
cookie through `next/headers` and calls `loadSession` with `forceRefresh: false`. A request whose
session is not `active` gets no answer (`undefined`): no flags are sent to a signed-out visitor.

For an active session it answers from a set held in the module, shared by every user because the
document is bucket-wide. The set holds the resolved flags and the time the API answered, and never a
token. The rules, by the held set's age:

- **Younger than 60 seconds:** answered as is.
- **Between 60 seconds and one hour:** answered as is, and a background refresh starts.
- **Older than one hour, or no set held** (a task that has just started): no answer, and a background
  refresh starts. One hour is the browser's own `staleTime`, so the server never sends a set staler
  than a tab would already hold.

A **background refresh** is never awaited by the render. It calls
`GET <apiOrigin>/v1/feature-flags` with the requesting session's ID token as the bearer, with the target
checked to have the API's origin as `apiTarget` does, a 10-second deadline, and redirects not followed.
It resolves the body with FR-001's resolver for the server's environment (`CONFIG_environment`, the
value the browser's runtime document carries). Only one refresh is in flight per server process: a
request arriving during one does not start another. A refresh that fails (no answer, a non-2xx, a
redirect, a body the resolver refuses) keeps the held set as it was, logs one line naming the reason
and never the token or the body, and no new refresh starts for 10 seconds. Neither the API's
concurrency nor a document load's time to first byte can be driven by page traffic.

Nothing on the API pass-through may consult the flags: `src/server/session/` does not import this
module, because a flag gating a request would be authorization.

#### Acceptance Criteria:

- [ ] A request with no session cookie, an `absent` session or an `unavailable` session gets
      `undefined`, and no API request is made.
- [ ] With an active session and no held set, the first call returns `undefined` and starts exactly
      one API request with `Authorization: Bearer <that session's ID token>`; once it answers, the
      next call returns the resolved set.
- [ ] Ten concurrent calls with no held set start one API request, not ten.
- [ ] A set 30 seconds old is returned with no API request; one 5 minutes old is returned and starts
      one refresh; one 61 minutes old returns `undefined` and starts one refresh (fake clock).
- [ ] A refresh answered 500, a refresh that times out, a 302, and a body with `version: 2` each leave
      a held set unchanged, log one line containing the reason and not the token, and a call 5
      seconds later starts no request while a call 11 seconds later starts one.
- [ ] A render never awaits the API: with the API stubbed to never answer, `serverFeatureFlags()`
      settles without waiting on it.
- [ ] Two calls within one request make one `loadSession` call (`cache()`), asserted by counting
      store reads.
- [ ] No file under `src/server/session/` imports `src/server/featureFlags.ts`, asserted by a test
      over their sources; the module begins with `import 'server-only'`, which
      `serverOnly.test.ts` already enforces.

### FR-003: The page carries the flags and the boot seeds them

#### Description:

The root layout awaits `serverFeatureFlags()` and passes the result, the flags and the time the API
answered, to `PortalMount` as a prop, which passes it through `PortalBoot` to the frame. When a set
is present, `AppFrame` writes it into its query client under
`featureFlagKeys.resolved(environment)`, with `updatedAt` set to the time the API answered, before its
first render. The set passes from server to client as a prop and through no module-scope read, so the
boot's rule that nothing of the application graph evaluates before the runtime document arrives still
holds.

`useFeatureFlags` reports `'ready'` while auth is still resolving whenever the query holds data, so a
seeded tab renders its gated surfaces from the first frame rather than waiting for `/auth/session`.
Every other state is unchanged: with no data, auth resolving is still `'loading'`; a signed-out tab is
still `'fallback'`. Because the seeded data is fresh, the query does not fetch when the tab starts. A
page sent with no set (FR-002's `undefined`) starts exactly as today.

#### Acceptance Criteria:

- [ ] Rendered with a seeded set and auth still resolving, `useFeature('query')` returns that set's
      value on the first render, and `useFeatureFlags().status` is `'ready'`.
- [ ] Rendered with a seeded set whose `updatedAt` is now, no `featureFlags.get` request is made
      after auth resolves (`apiRequest` mocked and counted).
- [ ] Rendered with a seeded set whose `updatedAt` is 61 minutes ago, one `featureFlags.get` request
      is made once auth resolves.
- [ ] Rendered with no seeded set, the hook's states and requests match today's tests in
      `useFeatureFlags.test.ts`, which pass unchanged.
- [ ] Called directly with `serverFeatureFlags` mocked, the root layout passes the set to
      `PortalMount` as its `flags` prop when one is held and passes `undefined` when none is, asserted
      on the element tree the layout returns. FR-006 checks the same thing in the deployed HTML.
- [ ] `PortalBoot.tsx` gains no static import, and the sweep that fails if its import list grows
      passes unchanged.

### FR-004: A disabled area is answered by the server

#### Description:

Each signed-in area that a `route` row in `GATED_SURFACES` names gets a server `layout.tsx` beside its
page: `/files`, `/query`, `/connections`, `/explore` and `/data-quality` (whose layout also covers the
report route beneath it). The layout calls `serverRouteGate(path)` in `src/server/featureFlags.ts`,
which finds the flag from the registry's `route` row for that path, never from a constant in the
layout, and answers `open` or `unavailable`.

- **`unavailable`** (a held set with that flag off): the layout renders `UnavailableMount` in place of
  its children. `UnavailableMount` is a client component beside the pages that reaches
  `routes/areas/unavailable.tsx` only through `next/dynamic` with `ssr: false`, as a page reaches its
  view. It renders `FeatureUnavailablePage` for that feature, with the fallback link computed from the
  set the server sent (the first enabled feature in flag order, omitted when none is) rather than from
  a browser read. The area's page is not rendered, so its view's code is never requested.
- **`open`** (the flag on, or no server answer): the layout renders its children unchanged, and the
  page's own `FeatureRoute` still decides in the browser.

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
- [ ] Rendered from a set with every flag off, `UnavailableView` offers no fallback link; from a set
      with only `files` on, it offers Files; no `featureFlags.get` request is made in either case.
- [ ] Called with the flag on, or with no held set, each layout returns the `children` it was given,
      the same element with no wrapper and no `key` (`toBe`), so the shell above it is untouched; each
      area's existing view tests pass unchanged.
- [ ] A test walks every `route` row of `GATED_SURFACES`. For each, except the one exemption named by
      its row name, a layout exists whose path covers the row's path and answers `unavailable` given a
      held set with the row's flag off and `open` with it on. A new `route` row with no server gate
      fails the walk; so does an exemption whose row has left the registry.
- [ ] `pageSweep.test.ts` is extended to the new layouts and `UnavailableMount`: a layout may import
      only `src/server/featureFlags.ts`, `UnavailableMount` and React's types, and `UnavailableMount`
      reaches its view only through `dynamic(…, {ssr: false})`. Its fixture corpus gains a failing
      case for each rule and a passing case for a conforming layout.

### FR-005: The records say where the flags resolve

#### Description:

Two records state as fact what this spec changes, so they are rewritten in place with a dated
History entry, not appended to.

- `docs/decisions/identity-and-access/a-feature-flag-is-presentation-never-authorization-and-it-lives-beside.md`:
  the flags resolve first on the server and are sent with the page; the browser's read is the second
  line, for a page sent with no set and for a stale tab. The fence keeps "presentation, never
  authorization" and gains the trap this spec creates: **the API pass-through never consults the
  flags**, and a held set shared by every user is correct only because the document is bucket-wide.
- `docs/specs/ARCS.md`, the Next.js arc's charter: "server components are used for layout shells only"
  and "no server rendering of data" gain a dated note that SPEC-264 lets server layouts read one
  document, the flags, after the arc closed, and nothing else.

`architecture.md` gains an ADR row because a page now carries data the server read from the API.

#### Acceptance Criteria:

- [ ] The decision's fence names both the server-first resolution and the rule that the API
      pass-through never consults the flags, and its History has a dated entry citing this spec.
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

- [ ] After a second document load of `/files` (the first warms the task's held set), the network log
      shows no `/api/v1/feature-flags` request at boot, and the nav rail's tabs are in the DOM on the
      first render after `/auth/session` answers.
- [ ] The page's HTML for that load carries the flag set; a signed-out load of `/` carries none.
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
export const REFRESH_FAILURE_PAUSE_MS = 10_000;

export const serverFeatureFlags: () => Promise<SeededFeatureFlags | undefined>;

export type RouteGate =
  | {kind: 'open'}
  | {kind: 'unavailable'; flag: FeatureFlagKey; flags: FeatureFlags};
export function serverRouteGate(path: string): Promise<RouteGate>;
```

## API / Interface Contract

```tsx
// src/app/layout.tsx
const seeded = await serverFeatureFlags();
<PortalMount flags={seeded}>{children}</PortalMount>

// src/app/(signed-in)/query/layout.tsx
export default async function QueryLayout({children}: {children: ReactNode}) {
  const gate = await serverRouteGate('/query');
  return gate.kind === 'unavailable' ? <UnavailableMount flag={gate.flag} flags={gate.flags} /> : children;
}

// src/app/(signed-in)/UnavailableMount.tsx ('use client')
const UnavailableView = dynamic(() => import('../../routes/areas/unavailable').then((m) => m.UnavailableView), {ssr: false});
export function UnavailableMount(props: {flag: FeatureFlagKey; flags: FeatureFlags}) { … }
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
├── AppFrame.tsx                         # seeds the query cache
├── features/feature-flags/
│   ├── resolveFeatureFlags.ts           # new, pure
│   ├── featureFlags.service.ts          # calls the resolver
│   └── useFeatureFlags.ts               # 'ready' with data while auth resolves
├── routes/areas/unavailable.tsx         # new view
└── server/featureFlags.ts               # new, server-only
```

## Implementation Phases

### Phase 1: The resolver and the server module (inert)

- Move the resolution into `resolveFeatureFlags.ts`; the service calls it (FR-001).
- `src/server/featureFlags.ts` with the held set, the background refresh, `serverRouteGate`, and
  their tests on a fake clock and a stubbed API (FR-002). Nothing calls it yet.

### Phase 2: The page carries the flags

- The root layout, `PortalMount`, `PortalBoot` and `AppFrame` carry and seed the set;
  `useFeatureFlags`'s one state change (FR-003).

### Phase 3: The server gates

- The five layouts, `UnavailableMount`, the unavailable view, the registry walk and the page sweep's
  extension (FR-004).

### Phase 4: Records and the live check

- The decision and the charter (FR-005); the live check on the tier (FR-006).

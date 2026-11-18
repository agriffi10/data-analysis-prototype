# Completed Spec — SPEC-264: The Server Resolves the Feature Flags

## What was completed?

- **One resolver.** The parsing and resolution moved unchanged from `featureFlags.service.ts` into
  `resolveFeatureFlags.ts` (`resolveFeatureFlagDocument`), a pure module the browser's service and
  the server both call.
- **The server holds the set.** `src/server/featureFlags.ts`: `serverFeatureFlags()` for the root
  layout, `heldFeatureFlags()` and `serverRouteGate(path)` for the area layouts. One set per process,
  refreshed in the background through `GET /v1/feature-flags` with the requesting session's token.
  A page costs one session-store read (`peekSession`, new in `session.ts`) and never waits on the
  API or Cognito. `readCookie` is split so `readCookieHeader` reads a header string.
- **The page carries the set.** The root layout passes it to `PortalMount`, which passes it through
  `PortalBoot` to `AppFrame`. `AppFrame` seeds it with `seedServerFlags` before its first render.
  `useFeatureFlags` is `'ready'` while auth resolves whenever the cache holds data.
- **Server gates.** `/files`, `/query`, `/connections`, `/explore` and `/data-quality` each have a
  server `layout.tsx` that renders `UnavailableMount` (and through it `routes/areas/unavailable.tsx`)
  when the held set has the area's flag off. `firstEnabledDestination` in `gatedSurfaces.ts` is the
  fallback rule `FeatureRoute` now shares.
- **Guards.** `featureFlagsFence.test.ts` walks every route handler, the proxy and the session
  modules through their imports and fails if one reaches the flag module. The page sweep exempts a
  file named exactly `layout.tsx` from the neighbour rule, and holds each area layout to the gate and
  the mount. A registry walk fails on a `route` row with no server gate, the shared-space report row
  excepted.

### Deliberate deviations

- **The held state lives on `globalThis`** under a `Symbol.for` key, not in module variables, so
  every route entry and a dev reload share the copy the root layout warmed. It is still process
  scope, and it still holds no token.
- **`PortalBoot` types its prop through a type-level `import('./AppFrame')`**, so the flag-key union
  has one source. The boot's import sweep counts `import … from` lines and passes unchanged.
- **The area gate answers only from a set under five minutes old** (`GATE_MAX_AGE_MS`), added after
  the execution review. A layout never refreshes the set, so another task's older "off" could have
  overridden a tab's newer "on" for up to an hour. Past the window, the page's own `FeatureRoute`
  decides.

## What changed from earlier specs?

- SPEC-162's resolver moved, and its fence now says the server resolves first; the browser's read is
  the second line.
- SPEC-257's "nothing about a session in module scope" names the held flag set as the one thing
  kept between requests, and says it holds no token.
- SPEC-256/263's layout boundary: the gated areas have server layouts below the shell, with no `key`,
  and they never throw.
- The arc charter (`ARCS.md`, Next.js arc) carries dated notes, and `architecture.md` has ADR row 60.

## Verification

All local gates passed by exit code: the portal suite at 3903 tests, pytest, mypy, lint, format,
`tsc`, the build with `check:bundle` and `check:pages`, and every validator `ci.yml` runs. Mutation
checks covered single-flight, the failure pause, the token-life check, the gate's catch, the gate
window, the seed's `updatedAt`, the auth-loading `'ready'`, PortalMount's pass-through and the
fallback's nav check. The execution review also ran the standalone build against a stubbed store and
API: the HTML carried the set, `/query` answered with the mount, and a signed-out load carried none.
The FR-006 live check was owed while the web tier was off, and ran on 2026-11-18 on `b8840ea7`: all
three checks and the real read passed but one clause, that the nav rail's tabs are in the DOM on the
first render after `/auth/session` answers, which no instrument measured and which stays owed
(`docs/testing/owed.md`, evidence in `docs/testing/sessions.md`).
Help and guides: nothing user-facing changed, since the same pages render and only sooner.

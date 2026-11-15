# Completed Spec — SPEC-260: Explore and Connections Move Onto the App Router

The spec merged as Draft in #970. The build landed in one PR on 2026-11-14, #985 (`7eb5f74d`),
after SPEC-256 read Completed and behind SPEC-261 in the queue; `main` was green on its merge, and
its Deploy SPA image run put it on the web tier, which SPEC-261 had switched on. The live checks ran
on 2026-11-15 between 02:20 and 02:25 UTC in Andrew's signed-in Chrome, on the tier serving `main` at
`a80c9b28` (#987), deployed at 17:04 UTC on 2026-11-14 and not redeployed during them. That build
holds this spec's pages, SPEC-259's Query page and the seam fix below, so Query was on the App Router
too. This spec released its hold on the tier when the checks ended and did not switch it; the
switch-off began at 02:31 UTC (the variable set to `false`, then Deploy Infrastructure run
43668180729).

## What was completed?

- **Two App Router pages.** `src/app/(signed-in)/explore/page.tsx` and `connections/page.tsx`, each
  a client component that reaches its area's view (`ExploreView`, `ConnectionsView`) through
  `next/dynamic` with `ssr: false`, with no loading fallback and no props.
- **Both area records say `'app'`**, so the route table no longer builds either area's route and the
  seam sends every navigation that changes the path into or out of them through Next's router.
- **App Router proofs in the split tests** (`src/routes/areas/explore.test.tsx`,
  `connections.test.tsx`), below the inherited mocks, which they do not need. Every test that renders
  either area names its router in `renderApp`'s `routers`. They cover the page served by its own
  file, the flag-off gate with a render counter and its positive control, the deep link's native
  drop and reload, *Explore in Data Explorer* under `StrictMode` from Query on either router with
  Back and Forward, *Explore data* from Query's schema rail, and the link wait with the skip link.
  Each was shown red against a planted mutation.

### Deliberate deviations

- **Two acceptance criteria were amended while building.** FR-001's page test names its area's
  router, because `renderApp` now serves every area from the catch-all unless a test names it.
  FR-002's link wait is proved on the refusal and from a followed link, because a read already in
  flight is reused, and a page loaded at the address already has the key `'default'` that the skip
  link produces.
- **A test beyond the criteria**: *Explore data* on Query's schema rail, the app's own source of
  deep links, from either router.

## What changed from earlier specs?

- **A leaving App Router page could drop the user's click** (found by this spec's diff review):
  `router.push` waits on Next's fetch, and the Explorer's deep link dropping its parameters natively
  in that window turned into a restore that discarded the pending navigation. The fix went to the
  seam rather than the Explorer, in #987 (`a80c9b28`), whose tests in `navigation.test.tsx` (*a page
  that is leaving*) prove it. A scratch reproduction with Explore on the App Router, never committed,
  failed before #987 and passes on `main` after it.
- **Navigations into and out of both pages now fetch the page** and scroll to the top, as SPEC-256
  said the first area moves would.

## Verification

Every local gate by exit code on the rebased commit (the formatter, both linters, both suites with
3,706 Vitest tests, mypy, `npm run build` with `ƒ /explore` and `ƒ /connections`, and every step
`ci.yml` runs); `next start` answered 200 on both pages and a deep link, and sent a signed-out
user from `/files` to `/`. The signed-in shell checks ran on the tier's production server. Live (FR-003),
each passed: the pasted deep link opened `orders` and left `/explore`, and a real reload kept one
tab; *Explore in Data Explorer* and *Open in Query* each added one tab, and Back then Forward added
none; Shared spaces listed `shared_dwb_team` and kept its title; the skip link, Files and Back showed
the Explorer. Through every in-app step one document, one `/config.json` fetch and the same shell
element held, across Files on the catch-all and Query, the Explorer and Connections on the App
Router. Rows are in `docs/testing/e2e.md` §4.5 and §4.8. Help & guides needed no change: the ways
into both pages they describe (their tabs, *Explore data*, *Explore in Data Explorer*) work as
before, and they say nothing about which router serves a page.

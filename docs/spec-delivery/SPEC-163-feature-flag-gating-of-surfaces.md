# Completed Spec — SPEC-163: Feature Flags — Gating Nav, Routes & Cross-Feature Entry Points

## What was completed?

SPEC-162 resolved four booleans nothing read. They now do their job: with a feature off, every
way into it disappears — its tab, its route, and every button that reaches it from another
feature.

- **The primitives.** `useFeature(key)` (boolean), `<FeatureGate flag>` (renders nothing when
  off — no wrapper, no `hidden`), and `useFeatureSet()` for the three consumers that need the
  whole set plus `status`.
- **The registry.** `gatedSurfaces.ts` — 26 rows across four flags, each naming the surface's
  **accessible name**, its kind and its owning route, plus `hiddenHelpIds()` and
  `NAV_PATH_FLAGS` derived from it.
- **The walking test.** `gatedSurfaces.test.tsx` renders every row twice — flag off, flag on —
  and asserts by accessible name. 54 assertions, both directions.
- **Nav.** `PrimaryNav` and `AppNavDrawer` take an `isPathEnabled` predicate; `Header` supplies
  the same one to both.
- **Routes.** `FeatureRoute` + `FeatureUnavailablePage`; every gated route keeps its path and
  swaps its element.
- **Cross-feature entry points.** Create table and Check quality in the file browser; Refresh /
  Share table and Create view in the Query surfaces; the spaces rail and `?space=` on Files; the
  Share-table kind toggle; the Help list.

### Deliberate deviations

- **`useFeatureSet()` exists, and it is not in the spec's file list.** FR-001 says nothing but
  `useFeature` may ask, and three places genuinely cannot ask one question: `Header` builds one
  predicate for two nav components, `FeatureRoute` must tell "off" from "not known yet", and
  `LandingPage` picks the first enabled destination. The alternative was letting all three reach
  into `useFeatureFlags`, which is what FR-001 is trying to prevent. **A tripwire test now
  asserts no module outside `features/feature-flags/` names `useFeatureFlags` at all** — a
  stronger boundary than the spec asked for, and the raw hook is internal.
- **The gating contract gained a row: shared databases in the Query schema rail** (your call,
  asked before building). Leaving `teamspace` browsable while the spaces list and `/connections`
  are gone reads as a bug rather than a policy. **Filtered at the view, never at the service** —
  `useConnections` still resolves every space, and a saved query naming a hidden database still
  runs, because a flag may not touch a service (SPEC-162 FR-006).
- **`FeatureRoute` renders `LoadingState`, not nothing, while the flags resolve.** FR-007's
  "render nothing while loading" is right for a tab and wrong for a whole viewport — an empty
  frame reads as a broken page. What matters is that the page does not MOUNT, because every
  gated page fetches on mount.
- **Recipes for the walk live in the test, not in the registry.** The registry stays declarative
  and reviewable by someone who has read no component; a guard asserts every row has a recipe
  and every recipe a row, so the two cannot drift.

## What changed from earlier specs?

- **`renderWithProviders` now seeds the flags all-on by default** (`seedFeatureFlags`, opt-out).
  Gating made every surface wait on a fetch, so without a seeded answer a test about something
  else asserts against a shell with no tabs and no Help sections. All-on is the same answer
  production reaches when the document is unreadable. **`setQueryDefaults` before `setQueryData`
  is load-bearing** — the harness client runs `gcTime: 0`, so an observer-less seed is evicted
  before a control that mounts after a click can read it. That bug passed every first-paint
  assertion and failed only inside a drawer.
- **`TestProviders` is now exported** for the axe renders that compose their own tree.
- **`PrimaryNav` / `AppNavDrawer` gained a required `isPathEnabled` prop.** Required, not
  defaulted: a default would make an unwired caller ship every tab while looking correct.
- **`useFileSpace` gained `ignoreSpaceParam`.** With shared workspaces off the `?space=`
  parameter is **not read**, rather than resolved-and-refused — routing it through `fellBack`
  would raise "That shared space is no longer available", which is false.
- **Help tests, landing a11y, `schemaUi` a11y and the Share-dialog a11y tests** now compose the
  provider stack, because the components they render read the flags.

## Two things the tests caught that review would have had to

- **The report-route "no S3 request" assertion was vacuous twice over** — the mock pointed at
  `dataQuality.service` when `getQualityReport` lives in `dataQualityReport.service`, and the
  page was rendered outside a `<Routes>` tree, so `useParams()` was empty and it declined to
  fetch anyway. A **positive control** (flag on ⇒ the report IS read) is what surfaced both.
- **The FR-001 tripwire's glob reported the feature to itself.** Vite keys a glob relative to the
  importing file, so siblings come back as `./useFeature.ts` and carry no `/feature-flags/` in
  the path.

**Help & guides: no content change, and that is the finding.** Nothing new is offered to a user
here — a flag is environment configuration with no control anywhere in the app, so there is no
flow to document (SPEC-074 FR-005 documents what is shipped and wired, and an admin surface is out
of scope repo-wide). What DID change is that guides now appear conditionally, which is recorded in
`component-inventory/help-feature.md` rather than in the guides themselves.

## Verification

Local, all green: `npm run lint` (the SPEC-155 `components/` → `features/` rule still passes —
the nav components take a prop rather than a hook), `format:check`, `npm run build` (`tsc -b`),
`npm run test:coverage` — **73 files / 1843 tests**.

**Live check (owed), Safari — see `docs/testing/feature-flags-e2e.md` → *SPEC-163*.** Publish a
document with `query` and `dataQuality` off; confirm at 400px and desktop that both tabs are
gone from the topbar and the hamburger, `/query` renders the unavailable page rather than the
404, the file browser offers neither "Create table" nor "Check quality", and Help lists neither
guide. Then flip both back on and confirm everything returns **without an app redeploy** — which
is also what finally discharges **SPEC-162 FR-007's runtime half** (that `VITE_ENVIRONMENT`
reached the bundle), owed since 162 and not dischargeable until a flag could visibly hide
something.

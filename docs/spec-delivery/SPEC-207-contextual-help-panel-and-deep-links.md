# Completed Spec — SPEC-207: Contextual Help — the Guide Panel and Per-Feature Deep Links

## What was completed?

- **The header help control is contextual.** On the six routes in the new registry it opens a
  guide panel over the current route; everywhere else — `/help`, the landing page, an unmatched
  path — it stays the link to `/help` it has always been. Its accessible name says which:
  `Help for this page` for the button, `Help & guides` for the link. **No control was added to the
  header**, so the mobile width budget is unchanged.
- **`HelpPanel`** renders one section's guides in the shared `Drawer` (`mobileVariant="full-height"`),
  with a footer link `Open the full guide` → `/help#<sectionId>`. Escape-by-depth, the focus trap,
  focus restoration, backdrop dismissal and the responsive presentation are all inherited from
  `Drawer`; nothing new was built for them.
- **`HELP_SURFACES`** (`helpSurfaces.ts`) maps a route path to a `HelpSectionId` and carries no flag
  information — asserted by sweeping the module's own import list.
- **`visibleHelpSections` / `useVisibleHelpSections`** (`visibleSections.ts`) lift the flag filtering
  out of `HelpPage` so the page and the panel cannot drift into filtering differently.
- **`useContextualHelp`** resolves the route's section, and closes the panel whenever the pathname
  changes.
- **Guide-level deep links.** `resolveHelpHash` (`helpDeepLink.ts`) resolves `/help#<guideId>` to the
  guide's own section and expands that card; section hashes are matched first and are unchanged.

### Deliberate deviations

- **`HelpGuideCard` was not modified.** The spec left the choice open and asked which was taken: the
  Help page wraps each card in a `<div id="help-guide-…">` that carries the scroll anchor. The
  consequence for FR-001's same-markup criterion, stated rather than hidden — the *card* markup is
  byte-identical (the test compares card roots with `useId` values normalised) and the page adds an
  anchor wrapper around it that the panel does not.
- **The close-on-route-change reset is adjusted during render, not from an effect.** FR-004's prose
  named an effect; `react-hooks/set-state-in-effect` is a blocking lint error on that shape. The
  render-time adjustment fires on the same event, closes the panel before the new route paints, and
  is mutation-tested against both journeys the criterion names. The spec's FR-004 wording was
  updated to state the requirement rather than the mechanism.
- **FR-004's "with a dialog open above the panel"** is inherited, not re-driven. The shipped panel
  contains no dialog and `HelpPanel` takes no children, so that state is unreachable in the app;
  adding a children prop with no production caller would be a test fixture wearing an API. `Drawer`
  wraps its children in `EscapeLayer` and `useEscapeKey` dispatches by depth, and that contract is
  pinned five ways in `hooks/hooks.test.tsx`.
- **FR-004's tab wrap asserts CONTAINMENT, not first↔last.** jsdom reports no layout boxes, so
  `tabbable` finds nothing inside the drawer and focus falls to the panel element itself. Without a
  trap the same Tab escapes to the control after the drawer, so the assertion still has teeth. The
  real wrap, and FR-008's "the page beneath does not scroll horizontally", are live checks in
  `docs/testing/e2e.md` §4.13.
- **`/data-quality/:space/:requestId` gets no panel.** Matching is on the whole pathname; the report
  view falls back to navigation. Permitted by FR-003 and left deliberate rather than silent.
- **`/data-quality` is the one row whose panel outlives its feature.** FR-007's derivation works
  because a gated route's *section* is filtered out — and there is no data-quality section, so with
  the flag off the panel still opens (headed Files) over the unavailable page. It discloses nothing
  and closing it would mean declaring the gate twice. Named in the register entry rather than left
  as a silent counterexample.
- **Nothing was added to `features/help/index.ts`.** Every new symbol is consumed inside the folder.

## What changed from earlier specs?

- `HelpLink` (SPEC-074) is no longer unconditionally a `NavLink`, and no longer renders outside the
  app's providers — it reads route context and the flags. `help.test.tsx`'s two bare-`MemoryRouter`
  renders of it now go through `TestProviders`; that inversion was named in the spec so it would not
  read as a regression.
- `HelpPage` (SPEC-074/103/163) keeps every behaviour: the filtering moved to `visibleSections.ts`
  and `sectionFromHash` became `resolveHelpHash`, with today's section-hash behaviour pinned first.
- `GATED_SURFACES` (SPEC-162/163) is **untouched**, by design — see the register entry.

## Verification

Locally green: `format:check`, `lint`, `test` (141 files / 2212 tests) and `npm run build`
(`tsc -b`), plus `scripts/validate_docs.py`. Six guards were mutation-tested and each reddened a
named test: the route-change reset, the pathname-keyed alternative the spec names as insufficient,
the FR-007 visibility conjunct, the card key that carries the addressed guide, the panel reading
`HELP_SECTIONS` instead of the filtered set, and — added after the diff review — an inline duplicate
of the filter inside `HelpPanel`, which agrees with the original today and is therefore caught by a
source sweep rather than by behaviour. Two criteria are deferred to a signed-in browser session and
recorded in `docs/testing/e2e.md` §4.13: the panel's real first↔last tab wrap, and no horizontal
scroll on the page beneath at mobile width.

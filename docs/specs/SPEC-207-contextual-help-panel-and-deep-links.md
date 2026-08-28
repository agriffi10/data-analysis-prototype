# Spec: Contextual Help — the Guide Panel and Per-Feature Deep Links

**ID:** SPEC-207
**Status:** Draft
**Last Updated:** 2026-08-28
**Depends On:** SPEC-074 (Help & guides — the sections, the guide cards, the header link, the hash-addressed section), SPEC-103 (Help responsive), SPEC-155 (`Drawer`, `IconButton`, and the Escape-by-depth registry), SPEC-162/163 (`hiddenHelpIds` and the guide→flag registry in `gatedSurfaces.ts`), SPEC-045 (the axe assertions)

**Interacts with:** SPEC-210 and SPEC-211 both add a header control. This spec adds **none** — it
changes what the existing help control does — so the header's mobile width budget is unchanged by it.
SPEC-211 FR-007 owns the measurement.

## Overview

Help exists, and it is in the wrong place. A user who wants to know how a shared workspace is
created has to leave whatever they were doing, open `/help`, pick the section, find the guide, read
it, and navigate back — and whatever was half-filled-in on the page they left is a separate worry.
The guides themselves are good; their distance from the work is the problem.

This spec brings the guide to the page. The help control already in the top bar stops being a
navigation and becomes contextual: it opens a panel over the current route, already showing that
page's guides. The user never leaves. From inside the panel one link goes on to the full Help page at
the same section, so nothing becomes unreachable.

`/help` already addresses a **section** by URL hash — `HelpPage.tsx` resolves `#query`, falls back to
the first visible section on an unrecognised hash, and writes the hash when the sidebar selection
changes. What it cannot address is a **guide**. This spec adds that half, so a single guide is
linkable and the panel's link can land on the one the user was reading.

**No new guide content is authored here.** `helpContent.ts` is the source of truth for what the
portal can do and it is deliberately code-grounded; this spec changes where its existing sections
can be read, and nothing about what they say.

## Scope

### In Scope

- A `HelpPanel` drawer rendering one help section's guides over the current route.
- Repointing the existing header help control at the panel, resolved from the current route.
- A registry mapping a route path to a help section id, with a test that walks every row.
- Guide-level URL deep links on the full Help page: `/help#<guideId>`.
- A link out of the panel into the full Help page at the same section.
- Escape handling at the panel's own tree depth, focus trapping and restoration, and axe coverage.

### Out of Scope

- **A real pop-out browser window.** `window.open` to a standalone route would need a second React
  root, a second runtime-config fetch, and it dies silently behind a popup blocker. Rejected in
  favour of the in-app panel; if a detachable window is ever wanted it is its own spec.
- **New or rewritten guide content.** Every section, guide, step and callout is used exactly as
  `helpContent.ts` already carries it.
- **A second help affordance per page.** An earlier draft put a button in each of six page headers.
  Three of those routes — `/files`, `/query`, `/explore` — have no page header at all (`PageLayout`
  is used by Connections, Data quality, Notifications and Help only; `QueryPage` and `ExplorePage`
  are eight-line wrappers and `FilesPage` renders a screen-reader-only `h1`), so that shape would
  have required three new product-visible placements to be invented mid-build. One control that
  already exists, in a bar that is on every route, is both smaller and better.
- **Section-level hash routing.** It ships. This spec does not rebuild it.
- **Help affordances on dialogs, drawers, menus or toolbars.**
- **Search across guides.**
- **Panel state in the URL.** The panel is component state; only the *full page* is addressable.
  Putting the panel in a search param would make every page's URL carry help state, and no producer
  in the app needs to link to an open panel. Reconsider when one does.
- **Persisting whether the panel was last open.** It opens closed, every time.

---

## Functional Requirements

### FR-001: The guide panel renders the section the user can actually see

#### Description:

A `HelpPanel` component renders a section inside the shared `Drawer`, over whatever route is mounted.
It renders the section's guides with the same `HelpGuideCard` the Help page uses.

**It renders the flag-filtered content, not the raw content.** `gatedSurfaces.ts` declares itself the
only home of the guide→flag mapping, and `HelpPage.tsx` already filters both sections and guides
through `hiddenHelpIds` before rendering. A panel that read `HELP_SECTIONS` directly would show, with
`asyncFileOperations` off, a guide that `/help` hides — which is exactly the fork that registry
exists to prevent.

#### Acceptance Criteria:

- [ ] The panel resolves its section through the same `hiddenHelpIds` filter `HelpPage` uses, from
      the same registry, and the filtering is applied in **one** shared helper the two call — not
      duplicated.
- [ ] With `asyncFileOperations` off, the Files panel renders no guide whose id that flag hides, and
      a test asserts the specific guide's absence by title.
- [ ] With every flag on, the panel for section `query` renders every guide in that section and no
      guide belonging to another section.
- [ ] The panel renders `HelpGuideCard`; a test asserts the panel and the Help page produce the same
      card markup for the same guide.
- [ ] The panel's accessible name is the section's `label`.
- [ ] The route beneath the panel stays mounted: a test that types into a form field on the page,
      opens the panel and closes it finds the typed value still present.
- [ ] The panel issues no network request — the content is bundled.

### FR-002: The existing header control becomes contextual

#### Description:

`HelpLink` in `components/Header.tsx` navigates to `/help` today. It becomes the control that opens
the panel for the current route. No control is added to the header.

#### Acceptance Criteria:

- [ ] On a route with a registry row, activating the control opens the panel at that row's section
      and performs no navigation.
- [ ] On a route with **no** registry row — `/help` itself, the landing page, an unmatched path — the
      control navigates to `/help`, exactly as today. A test asserts both behaviours.
- [ ] The control's accessible name changes with its behaviour, so a screen-reader user is not told
      it is a link to a page when it opens a panel.
- [ ] `AppNavDrawer`'s `/help` nav row is unchanged, so the full page keeps a direct route on mobile.
- [ ] The control behaves identically at every breakpoint; the panel's presentation differs (FR-008),
      the affordance does not.
- [ ] The header gains no element, asserted as **route invariance** — the header's control count on
      a route with a registry row equals the count on a route without one. Not "unchanged from before
      this spec", which can only be a pinned number that SPEC-210 and SPEC-211 each legitimately
      bump, leaving a guard that fails for the wrong reason.
- [ ] `help.test.tsx`'s existing render of `<HelpLink />` inside a bare `MemoryRouter` is updated:
      once the control reads route context it throws outside the app's providers. It is a trivial
      rewrite and it is named here so it is not mistaken for a regression.

### FR-003: One registry maps a route to its help section

#### Description:

A single `HELP_SURFACES` registry maps a route path to a `HelpSectionId`. This is a route→section
mapping and is **not** the guide→flag mapping — that stays in `gatedSurfaces.ts`, which FR-001
consumes rather than reproduces.

#### Acceptance Criteria:

- [ ] Every `sectionId` in the registry exists in `HELP_SECTIONS`; a test fails on one that does not.
- [ ] A test renders every registered path, activates the help control, and asserts the panel's
      heading is that row's section label — so a row whose surface it cannot drive fails.
- [ ] A path with no registry row renders the fall-back navigation of FR-002, and that is not an
      error.
- [ ] The registry contains no flag information of any kind; a test asserts it imports nothing from
      `features/feature-flags`.

### FR-004: The panel closes correctly and returns focus

#### Acceptance Criteria:

- [ ] **The panel closes on a route change**, and the reset is on the pathname, not on first paint.
      Two reachable failures otherwise, both of which ship green against a mount-only test: open the
      panel on `/files`, navigate away and come back, and it is open again — contradicting this
      spec's own "It opens closed, every time"; and open it on `/notifications`, press Back to
      `/files`, and a different section's content is silently substituted into a live modal. Keying
      the open state to the pathname does **not** fix the second one, because back-navigation
      restores the same pathname; an effect that closes on pathname change does.
- [ ] A test drives both journeys — forward-navigate-and-return, and browser Back — and asserts the
      panel is closed on arrival.
- [ ] Escape closes the panel and returns focus to the help control that opened it.
- [ ] With a dialog open above the panel, Escape closes the dialog and leaves the panel open.
- [ ] Tab from the last focusable element inside the panel returns to the first — focus does not
      escape to the page beneath.
- [ ] The axe assertion runs against the **driven container** with the panel open — not a re-render
      of the closed state — and uses the **component** options, not `ROUTE_AXE_OPTIONS`. The panel
      opens from the header, which reads as route-level, but the shared `Drawer` renders
      `<aside role="dialog">` and the route options' best-practice `aria-allowed-role` rule fails on
      it. Every existing container-level assertion in the suite uses the component options.

### FR-005: `/help` gains guide-level deep links

#### Description:

Section hashes already work. `HelpPage.tsx`'s `sectionFromHash` resolves `#query` and falls back to
the first visible section; the sidebar writes the hash on selection. This FR adds the guide half and
nothing else.

#### Acceptance Criteria:

- [ ] `/help#upload-files` mounts with the Files section selected, the "Upload files" card expanded
      and scrolled into view. `HelpGuideCard` takes `defaultOpen` into `useState` and so ignores a
      prop change, and it exposes neither an id nor a ref to scroll to — so this criterion changes
      that component or wraps it, and either way it is in scope. A wrapper carrying the id is the
      cheaper option and slightly weakens FR-001's same-markup criterion; whichever is chosen, say
      which.
- [ ] The guide scroll and `HelpPage`'s existing scroll-to-top on section change do not race. Both
      run on a hash-driven mount and the one declared second wins; jsdom has no layout, so **no test
      can catch this** — it is ordered deliberately in the code with a comment, or it is a bug
      nothing will report.
- [ ] A hash matching a guide id resolves to that guide's section; a hash matching a **section** id
      keeps behaving exactly as it does today, and a test pins the existing behaviour so this change
      cannot regress it.
- [ ] A hash matching a guide the current flags hide falls back to the section-level behaviour rather
      than expanding a card that is not rendered.
- [ ] Guide ids are unique across all sections; a test asserts it, because the lookup is by id alone
      and a duplicate would resolve to whichever section is walked first.
- [ ] A hash matching neither a section nor a guide continues to fall back to the first visible
      section, unchanged.
- [ ] Expanding a guide by hash does not write a new history entry.

### FR-006: The panel links out to the full page

#### Acceptance Criteria:

- [ ] The panel renders a link named `Open the full guide` whose href is `/help#<sectionId>`.
- [ ] Following it navigates to `/help` with that section selected, and the panel is closed on
      arrival.

### FR-007: A gated page's help is gated with the page, by construction

#### Description:

The control is contextual, so on a route the user cannot reach there is nothing to open. Nothing
declares that a second time.

#### Acceptance Criteria:

- [ ] With the `dataExplorer` flag off, `/explore` renders its gated element, and the help control on
      that route falls back to navigating to `/help` rather than opening a panel for a feature the
      user does not have.
- [ ] No new row is added to `GATED_SURFACES`; a test asserts the registry gained no help-panel row,
      so the gating stays derived rather than declared.

### FR-008: The panel is a full-height sheet on mobile

#### Acceptance Criteria:

- [ ] At mobile width the panel occupies the full viewport height and width, and the page beneath
      does not scroll horizontally.
- [ ] At `tablet` and above the panel is a right-side sheet with the page still visible beside it.
- [ ] The close control is reachable without scrolling at both widths.

---

## Data Model

```ts
// apps/portal/src/features/help/helpSurfaces.ts

import type {HelpSectionId} from './help.types';

/**
 * One route that offers contextual help. `path` is the route the header control resolves
 * against; `sectionId` is the section the panel opens at. Route → section only: the
 * guide→flag mapping stays in `gatedSurfaces.ts`.
 */
export type HelpSurface = {
  path: string;
  sectionId: HelpSectionId;
};

export const HELP_SURFACES: readonly HelpSurface[] = [
  {path: '/files', sectionId: 'files'},
  {path: '/query', sectionId: 'query'},
  {path: '/connections', sectionId: 'shared-connections'},
  {path: '/data-quality', sectionId: 'files'},
  {path: '/explore', sectionId: 'data-explorer'},
  {path: '/notifications', sectionId: 'notifications'}
];
```

> **The panel on `/data-quality` is therefore headed "Files"**, holding eleven Files guides of which
> two are about data quality. That is a real presentational cost of not inventing a seventh section,
> and it is accepted rather than hidden: the alternative is content work this spec has excluded.
>
> `/data-quality` maps to `files` because that is where its guides were authored —
> `check-data-quality` and `past-data-quality-checks` are in the Files section — and inventing a
> seventh section to hold them would be content work this spec has excluded. If the guides are ever
> regrouped, this row moves with them.

## API / Interface Contract

```ts
// apps/portal/src/features/help/visibleSections.ts
// EXTRACTED from HelpPage.tsx so the page and the panel filter identically (FR-001).
export function visibleHelpSections(isEnabled: (key: FeatureFlagKey) => boolean): HelpSection[];

// apps/portal/src/features/help/HelpPanel.tsx
export function HelpPanel(props: {sectionId: HelpSectionId; open: boolean; onClose: () => void}): JSX.Element;

// apps/portal/src/features/help/useContextualHelp.ts
export function useContextualHelp(): {
  /** null on a route with no row — the control navigates to /help instead. */
  sectionId: HelpSectionId | null;
  open: boolean;
  openPanel: () => void;
  closePanel: () => void;
};
```

## File & Folder Structure

```
apps/portal/src/features/help/
├── HelpPanel.tsx
├── helpSurfaces.ts
├── visibleSections.ts          # extracted from HelpPage, consumed by both
├── useContextualHelp.ts
├── helpDeepLink.ts             # hash → {sectionId, guideId} resolution (pure)
├── HelpLink.tsx                # repointed at the panel
├── HelpPage.tsx                # guide-level hash handling; filtering moved to visibleSections
├── helpPanel.test.tsx
├── helpSurfaces.test.tsx
├── helpDeepLink.test.ts
├── HelpGuideCard.tsx           # id/ref for the scroll anchor, or a wrapper (FR-005)
├── help.test.tsx               # HelpLink's existing bare-MemoryRouter render inverts
└── index.ts
```

## Implementation Phases

### Phase 1: Extract the filter, add the registry and the panel

- Extract `visibleHelpSections` out of `HelpPage.tsx` with its existing behaviour pinned first.
- `helpSurfaces.ts` and its walking test, including the no-flag-import assertion.
- `HelpPanel` on the existing `Drawer`, rendering the filtered section through `HelpGuideCard`.
- Escape-depth registration, focus restoration, axe against the driven container.

### Phase 2: Repoint the header control

- `useContextualHelp` and the two behaviours of `HelpLink`; the accessible-name change.
- The gated-route fall-back and the unchanged-control-count assertion.
- Mobile sheet behaviour and the responsive assertions.

### Phase 3: Guide-level deep links

- Pin today's section-hash behaviour, then add `helpDeepLink.ts` and the guide-id uniqueness test.
- Guide expansion and scroll on mount and on hash change; the hidden-guide fall-back.
- The panel's `Open the full guide` link.

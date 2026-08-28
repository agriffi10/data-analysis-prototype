# Spec: Contextual Help — the Guide Panel, Deep Links & Per-Page Help Buttons

**ID:** SPEC-207
**Status:** Draft
**Last Updated:** 2026-08-28
**Depends On:** SPEC-074 (Help & guides — the sections, the guide cards, the header link), SPEC-103 (Help responsive), SPEC-155 (`Drawer`, `IconButton`, and the Escape-by-depth registry), SPEC-162/163 (the feature-flag registry and the guide rows in `gatedSurfaces.ts`), SPEC-045 (the axe assertions)

## Overview

Help exists, and it is in the wrong place. A user who wants to know how a shared workspace is
created has to leave whatever they were doing, open `/help`, pick the section, find the guide, read
it, and navigate back — and whatever was half-filled-in on the page they left is a separate worry.
The guides themselves are good; their distance from the work is the problem.

This spec brings the guide to the page. Each primary page's header gains a help button that opens a
panel over the current route, already showing that page's guides — the user never leaves. The same
content also becomes addressable by URL, so `/help#query` and `/help#upload-files` open the full
page at a named section or a named guide, which is what makes a guide linkable from anywhere.

**No new guide content is authored here.** `helpContent.ts` is the source of truth for what the
portal can do and it is deliberately code-grounded; this spec changes where its existing sections
can be read, and nothing about what they say.

## Scope

### In Scope

- A `HelpPanel` drawer that renders one existing help section's guides over the current route.
- A help button in the page header of each of the six primary pages, opening the panel at that
  page's section.
- A registry mapping a route path to a help section id, with a test that walks every row.
- URL deep links on the full Help page: `/help#<sectionId>` and `/help#<guideId>`.
- A link out of the panel into the full Help page at the same section.
- Escape handling at the panel's own tree depth, focus trapping and restoration, and axe coverage.

### Out of Scope

- **A real pop-out browser window.** `window.open` to a standalone route would need a second React
  root, a second runtime-config fetch, and it dies silently behind a popup blocker. Rejected in
  favour of the in-app panel; if a detachable window is ever wanted it is its own spec.
- **New or rewritten guide content.** Every section, guide, step and callout is used exactly as
  `helpContent.ts` already carries it.
- **Help buttons on dialogs, drawers, menus or toolbars.** Six page headers is the whole first pass.
  A per-dialog pass is a separate spec, and this one must not quietly become it.
- **Search across guides.** The Help page's existing navigation is unchanged.
- **Panel state in the URL.** The panel is component state; only the *full page* is addressable.
  Putting the panel in a search param would make every page's URL carry help state, and no producer
  in the app needs to link to an open panel. Reconsider when one does.
- **Persisting whether the panel was last open.** It opens closed, every time.

---

## Functional Requirements

### FR-001: The guide panel renders an existing section over the current route

#### Description:

A `HelpPanel` component renders a section from `HELP_SECTIONS` inside the shared `Drawer`, over
whatever route is mounted. It renders the section's guides with the same `HelpGuideCard` the Help
page uses — one component, so a card cannot look or behave differently in the two places.

#### Acceptance Criteria:

- [ ] Opening the panel for section id `query` renders every guide in that section's `guides` array,
      by title, and renders no guide belonging to another section.
- [ ] The panel renders `HelpGuideCard`; a test asserts the panel and the Help page produce the same
      card markup for the same guide.
- [ ] The panel's accessible name is the section's `label`.
- [ ] The route beneath the panel stays mounted: a test that types into a form field on the page,
      opens the panel and closes it finds the typed value still present.
- [ ] The panel renders no network request of any kind — the content is bundled.

### FR-002: A help button in each primary page header

#### Description:

Each of the six primary pages gains a help button in its header, opening the panel at that page's
section.

#### Acceptance Criteria:

- [ ] `/files`, `/query`, `/connections`, `/data-quality`, `/explore` and `/notifications` each
      render exactly one control whose accessible name is `Help with this page`.
- [ ] Clicking it opens the panel at the section the registry (FR-003) names for that path.
- [ ] The button is an `IconButton` and carries a visible-on-focus ring, like every other header
      control.
- [ ] The button appears at every breakpoint — mobile included — since the mobile user is the one
      least able to afford a navigation away.
- [ ] The existing header `HelpLink` to `/help` is unchanged and still present.

### FR-003: One registry maps a route to its help section

#### Description:

A single `HELP_SURFACES` registry maps a route path to a `HelpSectionId`. It is the only home of
that mapping, for the same reason `gatedSurfaces.ts` is the only home of the guide→flag mapping: two
copies fork, and the one nobody regenerates is the one that ships.

#### Acceptance Criteria:

- [ ] Every `sectionId` in the registry exists in `HELP_SECTIONS`; a test fails on one that does not.
- [ ] A test renders every registered path, finds the help button, opens it, and asserts the panel's
      heading is that row's section label — so a row whose surface it cannot drive fails.
- [ ] Adding a row for a path that renders no help button fails that test rather than passing
      silently.
- [ ] A path with no registry row renders no help button, and that is not an error.

### FR-004: The panel closes correctly and returns focus

#### Description:

The panel participates in the existing Escape-by-depth registry and the `Drawer`'s focus trap.

#### Acceptance Criteria:

- [ ] Escape closes the panel and returns focus to the help button that opened it.
- [ ] With a dialog open above the panel, Escape closes the dialog and leaves the panel open.
- [ ] Tab from the last focusable element inside the panel returns to the first — focus does not
      escape to the page beneath.
- [ ] `expectNoA11yViolations` runs against the **driven container** with the panel open, not a
      re-render of the closed state.

### FR-005: `/help` deep-links to a section or a guide

#### Description:

The Help page reads the URL hash on mount and on change. A hash matching a section id selects that
section; a hash matching a guide id selects that guide's section, expands the guide and scrolls it
into view. An unrecognised hash is ignored.

#### Acceptance Criteria:

- [ ] `/help#query` mounts with the Query section selected.
- [ ] `/help#upload-files` mounts with the Files section selected, the "Upload files" card expanded
      and scrolled into view.
- [ ] `/help#nonsense` mounts on the default section with no error rendered and no console error.
- [ ] Changing the hash while the page is mounted moves the selection without a remount.
- [ ] Selecting a section by clicking the sidebar updates the hash, so the URL is copyable.
- [ ] Guide ids are unique across all sections; a test asserts it, because the lookup is by id
      alone and a duplicate would resolve to whichever section is walked first.

### FR-006: The panel links out to the full page

#### Description:

The panel carries one link into the full Help page at the section it is showing.

#### Acceptance Criteria:

- [ ] The panel renders a link named `Open the full guide` whose href is `/help#<sectionId>`.
- [ ] Following it navigates to `/help` with that section selected, and the panel is closed on
      arrival.

### FR-007: A gated page's help button is gated with the page, by construction

#### Description:

The help button lives inside the page it documents, so a page hidden by a feature flag takes its
help button with it. Nothing declares that a second time.

#### Acceptance Criteria:

- [ ] With the `dataExplorer` flag off, `/explore` renders its gated element and no control named
      `Help with this page`.
- [ ] No new row is added to `GATED_SURFACES` for a help button; a test asserts the registry gained
      no `Help with this page` row, so the gating stays derived rather than declared.

### FR-008: The panel is a full-height sheet on mobile

#### Description:

Below `tablet` the panel occupies the full viewport height and width rather than a side sheet.

#### Acceptance Criteria:

- [ ] At mobile width the panel's container carries the full-width classes and the page beneath does
      not scroll horizontally.
- [ ] At `tablet` and above the panel is a right-side sheet with the page still visible beside it.
- [ ] The close control is reachable without scrolling at both widths.

---

## Data Model

```ts
// apps/portal/src/features/help/helpSurfaces.ts

import type {HelpSectionId} from './help.types';

/**
 * One page that offers contextual help. `path` is the route the button renders on;
 * `sectionId` is the section the panel opens at.
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

> `/data-quality` maps to `files` because that is where its guides were authored — the data-quality
> guides live in the Files section, and inventing a seventh section to hold them would be content
> work this spec has excluded. If the guides are ever regrouped, this row moves with them.

## API / Interface Contract

```ts
// apps/portal/src/features/help/HelpPanel.tsx
export function HelpPanel(props: {sectionId: HelpSectionId; open: boolean; onClose: () => void}): JSX.Element;

// apps/portal/src/features/help/useHelpPanel.ts
// Resolves the current route's section from HELP_SURFACES and owns open/closed state.
export function useHelpPanel(): {
  sectionId: HelpSectionId | null; // null on a route with no row — render no button
  open: boolean;
  openPanel: () => void;
  closePanel: () => void;
};
```

## File & Folder Structure

```
apps/portal/src/features/help/
├── HelpPanel.tsx
├── HelpPanelButton.tsx
├── helpSurfaces.ts
├── useHelpPanel.ts
├── helpDeepLink.ts            # hash → {sectionId, guideId} resolution (pure)
├── helpPanel.test.tsx
├── helpSurfaces.test.tsx      # the registry walk
├── helpDeepLink.test.ts
└── index.ts                   # gains the panel, the button and the registry
```

## Implementation Phases

### Phase 1: The panel and the registry

- Add `helpSurfaces.ts` and its walking test.
- Build `HelpPanel` on the existing `Drawer`, rendering `HelpGuideCard`.
- Add `useHelpPanel` and `HelpPanelButton`.
- Escape-depth registration, focus restoration, axe against the driven container.

### Phase 2: The six page headers

- Wire the button into each primary page's header.
- Assert the gated case for `/explore` and the no-new-`GATED_SURFACES`-row guard.
- Mobile sheet behaviour and the responsive assertions.

### Phase 3: Deep links on the full Help page

- `helpDeepLink.ts` resolution and the guide-id uniqueness test.
- Hash read on mount and on change; sidebar selection writes the hash.
- The panel's `Open the full guide` link.

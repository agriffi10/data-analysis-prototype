---
type: Spec
id: SPEC-103
title: "Help & guides — responsive layout"
description: "Makes the Help & guides page responsive, replacing the hidden section rail with a scrollable chip selector on mobile and a narrower rail on tablet so sections and guide cards work at every width."
spec_status: Completed
depends_on: [SPEC-095]
arc: responsive-and-files-ux
arc_order: 9
---

## Overview

The Help & guides page (SPEC-074) ships desktop-only: a fixed 248px "Guides" rail
beside a column of accordion guide cards, with the active section driven by the URL
hash (`/help#query`). Below the `tablet` breakpoint the rail is simply hidden, leaving no
way to switch sections on a phone. This spec makes the Help page responsive across the
three SPEC-095 breakpoints — mobile-first — so the section navigation and the accordion
cards remain usable at every width. It is **presentation and reflow only**: the help
content, its data model, and routing are untouched; only how the existing rail and cards
lay out changes. On mobile the 248px rail is replaced by a horizontal, scrollable chip
selector under the page title; on tablet the rail narrows and its labels shorten; on
desktop the current layout is preserved exactly.

## Scope

### In Scope

- Responsive layout for the Help page across mobile (`< tablet`), tablet (`tablet`, 900–1299px),
  and desktop (`desktop`, ≥1300px), mirroring the Files/Query shell responsive behavior.
- Desktop (`desktop`) — preserve the current baseline: 248px "Guides" rail + accordion cards
  (first card open), content capped at ~820px.
- Tablet (`tablet`) — narrow the "Guides" rail and shorten its section labels (presentation
  only), keeping the accordion cards' full step lists and callouts.
- Mobile (`< tablet`) — replace the rail with a horizontal, `overflow-x-auto` chip/segment
  row of sections under the page title; the active chip is highlighted; tapping a chip
  drives the same URL-hash section state the rail uses.
- Accordion guide cards reflow on narrow widths (icon + text wrap into the available
  width) while keeping their numbered `<ol>` steps and Tip/Careful callouts intact.
- Component tests asserting the breakpoint behaviors (rail visibility, chip selector
  presence, shared hash-driven selection, cards retaining steps/callouts).

### Out of Scope

- **In-page Help search is explicitly NOT introduced.** The design mockup shows a
  page-header "Search guides" field that collapses to an icon on tablet/mobile, but no
  in-page Help search exists today, and this is a responsive-only spec. Per the mockup's
  own "only the features shipped today" principle, search is out of scope here — do not
  add a search field, icon, filtering, or any search state. Only the section rail and the
  accordion cards (the things that exist today) are reflowed.
- Any change to help content data (`helpContent.ts`), the `HelpSection`/`HelpGuide`
  content model/types, or the guide copy itself. Label shortening is achieved with a
  presentation-only mapping (see FR-002), not a new content-model field.
- Any change to routing, the URL-hash section scheme, or `HelpPage`'s selection logic
  (`sectionFromHash` / `selectSection` are reused as-is).
- Changes to the accordion card's open/close interaction, animation, or content rendering
  beyond the responsive reflow of its header (icon + text) and padding.
- The app-shell header, global nav, mobile hamburger drawer, or avatar — those are covered
  by their own SPEC-095-arc specs, not here.

---

## Functional Requirements

### FR-001: Desktop baseline preserved (`desktop`, ≥1300px)

#### Description:

At the `desktop` breakpoint the Help page renders exactly as it does today: the 248px "Guides"
rail sits to the left of the content, the content column is capped at ~820px, guide cards
render as accordions, and the first card of the active section is open by default. This
spec must not visually regress the desktop layout.

#### Acceptance Criteria:

- [ ] At `≥ desktop`, the "Guides" rail is visible and 248px wide (`w-[248px]`), with its right
      hairline border, to the left of the content region.
- [ ] At `≥ desktop`, each section rail item shows its full label (e.g. "Shared connections")
      plus the right-aligned guide count.
- [ ] The content column remains capped at `max-w-[820px]` and the first guide card of the
      active section is open on load.
- [ ] No horizontal section chip selector is rendered at `≥ desktop`.

### FR-002: Tablet rail narrows with shortened labels (`tablet`, 900–1299px)

#### Description:

At the `tablet` breakpoint the "Guides" rail remains a vertical rail but narrows (below the
standard 248px), and each section's label is shortened to a compact form (e.g. "Shared
connections" → "Shared") so it fits the narrower rail without truncation. Shortening is
presentation-only: a co-located, section-id-keyed short-label lookup inside the Help
presentation code — `helpContent.ts` and the `HelpSection` type are not modified. Guide
cards keep their full step lists and callouts.

#### Acceptance Criteria:

- [ ] At the `tablet` breakpoint the "Guides" rail is visible as a vertical rail narrower than
      248px (e.g. `w-[220px]`), retaining its right hairline border.
- [ ] Each rail item at `tablet` renders the section's short label (e.g. the section whose full
      label is "Shared connections" renders as "Shared").
- [ ] The short-label mapping lives in the Help presentation layer (component/constant),
      not in `helpContent.ts`, and does not alter the `HelpSection`/`HelpGuide` types.
- [ ] Guide cards at `tablet` still render every numbered step and any Tip/Careful callout of
      the active section's guides (no steps or callouts are dropped at this width).

### FR-003: Mobile horizontal chip section selector (`< tablet`)

#### Description:

Below `tablet`, the vertical "Guides" rail is not shown; instead a horizontal, scrollable row
of section chips renders under the page title. Each chip represents one section; the active
section's chip is visually highlighted; the row scrolls horizontally (`overflow-x-auto`)
when the chips overflow the viewport width. Selecting a chip changes the active section via
the same URL-hash mechanism the rail uses, so hash/back/forward behavior is unchanged.

#### Acceptance Criteria:

- [ ] At `< tablet`, the 248px vertical "Guides" rail is not rendered (or is hidden), and a
      horizontal section chip row is rendered beneath the page title instead.
- [ ] The chip row is horizontally scrollable (`overflow-x-auto`) and each chip stays on a
      single line (does not wrap to a second row).
- [ ] Exactly one chip — the active section's — is styled as active (highlighted); all
      others render as inactive.
- [ ] Tapping/activating a chip selects that section through the existing hash-driven
      `onSelect` path (`navigate('#<id>')`), and the active chip updates to match the hash.
- [ ] The chip row exposes accessible section navigation (a labelled nav/list of section
      controls, one per section), and keyboard activation selects the section.

### FR-004: Shared section state across rail and chips

#### Description:

The tablet/desktop rail and the mobile chip selector are two presentations of the same
section-selection state. Both read the active section from the URL hash and both write
selection back through the same handler, so switching breakpoints never loses or diverges
the active section, and only one selector is active at a given width.

#### Acceptance Criteria:

- [ ] At any width, the active section shown by the visible selector (rail or chips)
      matches the section derived from the URL hash.
- [ ] Selecting a section from either the rail or the chip row updates the URL hash and the
      rendered content panel identically (same `HelpSectionId`, same guides).
- [ ] Only one section selector is present in the DOM-visible layout per breakpoint (rail
      at `≥ tablet`, chips at `< tablet`); they are not both shown simultaneously at any width.
- [ ] Browser back/forward between two `/help#<section>` entries still moves between
      sections regardless of which selector performed the navigation.

### FR-005: Accordion cards reflow and retain content; no search added

#### Description:

At narrow widths the accordion guide cards reflow so the header icon tile and the title/
subtitle text fit the available width without overflow, and the numbered steps and any
Tip/Careful callout remain fully rendered. No search field, search icon, or search state
is introduced anywhere on the Help page at any breakpoint.

#### Acceptance Criteria:

- [ ] At `< tablet` and at `tablet`, expanded guide cards render every numbered `<ol>` step and any
      Tip/Careful callout for the active section's open card(s).
- [ ] Guide card headers reflow within the content width at `< tablet` (icon + text do not
      cause horizontal overflow of the card or the page).
- [ ] The card open/close accordion interaction still works at every breakpoint, with the
      first card of the active section open by default.
- [ ] No search input, search icon button, or search-related control is present in the Help
      page DOM at any breakpoint.

---

## Data Model

No new types or data. This spec reuses the existing SPEC-074 content model
(`apps/portal/src/features/help/help.types.ts`) unchanged: `HelpSection`, `HelpGuide`,
`HelpCallout`, `HelpSectionId`, `HelpIconName`. The tablet short-label mapping is a
presentation-only constant keyed by `HelpSectionId` (co-located with the rail/chips
component); it is not part of the content model and is not exported for content use.

```ts
// Presentation-only, co-located in the Help rail/chips component (NOT helpContent.ts):
// a compact label per section for the narrowed tablet rail.
const SHORT_SECTION_LABELS: Record<HelpSectionId, string> = {
  files: 'Files',
  query: 'Query',
  tables: 'Tables',
  'shared-connections': 'Shared',
  notifications: 'Notifications',
};
```

---

## File & Folder Structure

```
apps/portal/src/features/help/
├── HelpPage.tsx            # render both selectors; rail at md+, chips at <md (reflow only)
├── HelpPage.test.tsx       # breakpoint behaviors: rail vs chips, shared hash selection, no search
├── HelpSidebar.tsx         # md+ rail: narrows at md, short labels at md (presentation-only map)
├── HelpSidebar.test.tsx    # rail visibility ≥md, short-label rendering at md
├── HelpSectionChips.tsx    # NEW: <md horizontal overflow-x-auto chip selector, hash-driven
├── HelpSectionChips.test.tsx # NEW: active chip, scrollable single-row, onSelect drives hash
├── HelpGuideCard.tsx       # header reflow at narrow widths; steps + callouts retained
└── HelpGuideCard.test.tsx  # steps/callout present when reflowed
```

Notes:
- `apps/portal/src/routes/HelpPage.tsx` (the route wrapper) is unchanged.
- `helpContent.ts`, `help.types.ts`, and `helpIcons.ts` are unchanged.
- Only `HelpSectionChips.tsx` (+ its test) is net-new; the rest are edits/reflows.

## Implementation Phases

### Phase 1: Rail responsiveness (desktop + tablet)

- Keep the desktop `HelpSidebar` behavior intact (248px, full labels, right border) at
  `desktop`.
- Narrow the rail at the `tablet` breakpoint and render short section labels from a
  presentation-only `SHORT_SECTION_LABELS` map (full labels retained at `desktop`).
- Ensure the rail stays hidden below `tablet` (`hidden … tablet:flex` retained).
- Update/extend `HelpSidebar.test.tsx` for rail visibility and short-label rendering.

### Phase 2: Mobile chip section selector

- Add `HelpSectionChips.tsx`: a horizontal, `overflow-x-auto` single-row chip selector,
  one chip per section, active chip highlighted, shown only `< tablet`.
- Wire it in `HelpPage.tsx` beneath the page title, driven by the same `activeId` +
  `selectSection` (hash) path as the rail; ensure exactly one selector shows per breakpoint.
- Add `HelpSectionChips.test.tsx` and extend `HelpPage.test.tsx` for shared hash-driven
  selection and breakpoint exclusivity.

### Phase 3: Card reflow + guardrails

- Reflow the `HelpGuideCard` header (icon + title/subtitle) so it fits narrow widths
  without overflow while keeping steps and callouts fully rendered and the accordion
  interaction working; first card open by default.
- Assert (test) that no search control exists on the Help page at any breakpoint and that
  reflowed/expanded cards retain all steps and callouts.
- Run formatter, linter, and unit tests green.

---
type: Spec
id: SPEC-095
title: "Responsive Foundation & App Shell"
description: "Gives developers the shared responsive foundation, a breakpoint vocabulary, hamburger off-canvas nav drawer, responsive top bar, mobile bottom action bar and bottom-sheet Modal and Drawer, for later surface specs."
spec_status: Completed
depends_on: []
arc: responsive-and-files-ux
arc_order: 1
---

## Overview

The portal is desktop-only today: the top bar and primary tabs are always a single horizontal row,
the 248px rails simply hide below `tablet` (leaving no navigation), and dialogs/drawers are fixed-width.
The Claude Design responsive mockups (`docs/design/Responsive Breakpoints.dc.html`) reimagine every
surface at three widths. This spec establishes the **shared responsive foundation** all surface specs
(SPEC-099→104) build on: the canonical breakpoint vocabulary, an **off-canvas navigation drawer**
behind a hamburger for mobile, a responsive top bar, a **persistent mobile bottom action bar**
primitive, and responsive behavior for the shared `Modal` and `Drawer` primitives (drawer → full-width
bottom/side sheet on small screens). It introduces no data-layer, IAM, or infra changes — it is
presentation and app-shell chrome only, using tokens that already exist in `src/App.css`.

## Scope

### In Scope

- A documented, repo-wide **breakpoint convention** (mobile / tablet / desktop) with **two custom,
  self-documenting breakpoints** defined in `src/App.css` `@theme` — `--breakpoint-tablet: 900px` and
  `--breakpoint-desktop: 1300px`, with the Tailwind **defaults reset** (`sm`/`md`/`lg`/`xl`/`2xl` →
  `initial`) so only `tablet:` / `desktop:` compile — plus migrating the existing default-prefix usages
  (`CollapsibleRail`, `HelpSidebar`, `LandingPage`) to the new prefixes.
- A new **`AppNavDrawer`** off-canvas drawer (300px, scrim) exposing the primary destinations
  (Files / Query / Connections / Notifications / Help) plus a contextual slot the Files/Query pages
  fill with their rail content; opened by a hamburger button shown only on mobile.
- Responsive **`Header`**: on mobile the horizontal `PrimaryNav` tab strip is replaced by a hamburger
  that opens `AppNavDrawer`; brand, notifications bell, and avatar remain in the bar.
- A reusable **`MobileActionBar`** primitive — a fixed-to-viewport-bottom bar (safe-area aware,
  ≥44px targets) that surface specs mount their primary mobile actions into (Files uses it for
  New folder + Upload).
- Promote the existing query-only popover (`TableActionsMenu`) into a **shared, reusable `Menu`
  primitive** in `src/components/` so mobile overflow menus and kebabs across surfaces share one
  accessible implementation (no behavior change for its current caller).
- Responsive **`Modal`** (small-screen gutters / near-full-width, no change on desktop) and responsive
  **`Drawer`** (below `tablet`, render as a full-width sheet — bottom sheet for content panels, full-height
  for member/roster drawers — instead of a 440px right slide-over).
- Ensure the app shell's viewport math (`h-[calc(100dvh-3.5rem)]`, `h-14` header) stays correct if the
  header height is unchanged, and that the mobile bottom bar does not occlude scrollable content.

### Out of Scope

- Per-surface reflow of Files, Query, Connections, Notifications, Help, Landing — each is its own spec
  (SPEC-099→104); this spec only ships the shared chrome/primitives they consume.
- The three Files feature changes (SPEC-096/097/098).
- Any change to routing, auth, data fetching, services, IAM, or infra.
- Collapsible-rail behavior on desktop/tablet (SPEC-085 already owns the `CollapsibleRail` collapse
  control); this spec only governs the **mobile** (off-canvas) presentation of navigation.
- New design **color/spacing/radius** tokens — those already exist in `src/App.css` (`@theme`). (This
  spec *does* add custom `--breakpoint-*` values there, which is in scope above.)

---

## Functional Requirements

### FR-001: Breakpoint convention

#### Description:

Adopt one breakpoint vocabulary across the app with **project-custom thresholds** (the mockup's
390 / 820 / 1300px frames are illustrative device sizes; these are the authoritative cut lines):

| Tier | Prefix | Threshold |
|---|---|---|
| **Mobile** | base (no prefix) | `< 900px` |
| **Tablet** | `tablet:` | `900px – 1299px` (use `tablet:max-desktop:` for the tablet band only) |
| **Desktop** | `desktop:` | `≥ 1300px` |

These are **not** Tailwind's defaults (`sm` 640 / `md` 768 / `lg` 1024 / `xl` 1280). Rather than
remap the default prefix names (a `md:` that secretly means 900px is a footgun), we **reset the
defaults and define two self-documenting custom breakpoints** in `src/App.css` `@theme`:

```css
/* src/App.css — @theme */
--breakpoint-sm: initial;      /* remove all Tailwind default breakpoints… */
--breakpoint-md: initial;
--breakpoint-lg: initial;
--breakpoint-xl: initial;
--breakpoint-2xl: initial;
--breakpoint-tablet: 900px;    /* …and define only the two the app uses */
--breakpoint-desktop: 1300px;
```

This yields exactly two responsive prefixes — `tablet:` (≥900px) and `desktop:` (≥1300px) — plus the
unprefixed mobile base and the auto-generated `max-tablet:` / `max-desktop:` and stacked
`tablet:max-desktop:` (tablet-band-only) variants. We build **mobile-first**: unprefixed utilities are
the mobile (`< 900px`) layout, then `tablet:` / `desktop:` layer changes on top. Never use a
lower-breakpoint prefix to *target* mobile — mobile is the unprefixed base; a prefix means "at that
breakpoint **and up**". Because the default prefixes are removed, the existing **`md:` / `sm:` usages
in the current code** (`CollapsibleRail`'s `hidden md:flex`, `HelpSidebar`'s `md:flex`, `LandingPage`'s
`sm:` / `md:`) are **migrated to `tablet:` / `desktop:`** as part of this spec. Document all of this in
`docs/best-practices/react.md` (a new "Responsive design" section).

#### Acceptance Criteria:

- [ ] `src/App.css` `@theme` resets the default breakpoints (`sm`/`md`/`lg`/`xl`/`2xl` → `initial`) and
      defines `--breakpoint-tablet: 900px` and `--breakpoint-desktop: 1300px`, so the only responsive
      prefixes that compile are `tablet:` / `desktop:` (+ their `max-*` variants).
- [ ] `docs/best-practices/react.md` gains a "Responsive design" subsection stating: the
      mobile/tablet/desktop → base / `tablet:` / `desktop:` mapping with the thresholds (`tablet` 900px,
      `desktop` 1300px); the mobile-first rule (unprefixed = mobile, layer up, never use a prefix to mean
      "mobile"); the `tablet:max-desktop:` pattern for tablet-only styles; and the responsive-component
      rule (FR-008 below).
- [ ] All prior `md:` / `sm:` breakpoint usages in the codebase (`CollapsibleRail`, `HelpSidebar`,
      `LandingPage`) are migrated to `tablet:` / `desktop:`; no class references a removed default prefix.
- [ ] A build/lint check confirms no `sm:`/`md:`/`lg:`/`xl:`/`2xl:` breakpoint prefixes remain in `src/`.

### FR-002: Hamburger trigger in the top bar (mobile only)

#### Description:

On mobile the `Header` shows a hamburger `IconButton` (left of / replacing the brand-adjacent
`PrimaryNav`) that opens `AppNavDrawer`. On `tablet` and up the hamburger is hidden and the existing
horizontal `PrimaryNav` tab strip shows exactly as today.

#### Acceptance Criteria:

- [ ] At `< tablet`, a hamburger button (`aria-label="Open navigation"`, `aria-expanded`,
      `aria-controls` referencing the drawer) is visible and `PrimaryNav` is hidden.
- [ ] At `≥ tablet`, the hamburger is hidden (`tablet:hidden`) and `PrimaryNav` renders unchanged.
- [ ] The hamburger is only rendered for authenticated users (same gate as `PrimaryNav`); the
      unauthenticated header is unaffected.
- [ ] The brand mark, `NotificationsBell`, and avatar/sign-out cluster remain visible at all widths.
- [ ] The button has a visible focus ring and a ≥44px hit target on mobile.

### FR-003: `AppNavDrawer` off-canvas navigation

#### Description:

A 300px off-canvas drawer over a scrim (`bg-black/30 backdrop-blur`), sliding from the left, containing
(top→bottom): the five **primary destinations** as nav links — Files, Query, Connections,
Notifications, Help — each with its icon and active state, then a divider, then a **contextual slot**
that the current page fills (Files → its Spaces list; Query → its schema-rail; other pages → empty).
Dismisses on Escape, scrim tap, and link activation. Reuses `Drawer` mechanics (focus trap, scroll
lock) but docks left at 300px.

#### Acceptance Criteria:

- [ ] Opening the drawer traps focus, locks background scroll, and moves focus to the first
      interactive element; closing returns focus to the hamburger.
- [ ] The drawer lists all five primary destinations as links driven by the router; the destination
      matching the current route shows the active treatment (`aria-current="page"`, `accent-soft`
      fill) and is not color-only.
- [ ] Activating any link navigates and closes the drawer.
- [ ] Escape, a scrim tap, and a close control each dismiss the drawer.
- [ ] A page can pass contextual rail content into the drawer's contextual slot; when none is
      provided the slot renders nothing (no empty divider/label).
- [ ] The drawer is only mountable on mobile (`< tablet`); at `≥ tablet` it is not rendered and navigation is
      the top-bar tabs + on-page rail.

### FR-004: `MobileActionBar` primitive

#### Description:

A reusable bar fixed to the bottom of the viewport on mobile only, `surface` background with a top
hairline (`border-t`), safe-area-inset aware (`env(safe-area-inset-bottom)`), that hosts a surface's
primary mobile actions passed as children. Targets are ≥44px. It renders `null` at `≥ tablet`.

#### Acceptance Criteria:

- [ ] Rendered fixed at the viewport bottom for `< tablet`, hidden (`tablet:hidden` / not rendered) at
      `≥ tablet`.
- [ ] Honors `env(safe-area-inset-bottom)` so controls clear the home indicator on notched devices.
- [ ] All interactive children present ≥44px hit targets.
- [ ] The consuming page adds bottom padding to its scroll region equal to the bar height so the bar
      never occludes the last row of content.
- [ ] Contents are caller-supplied (this spec ships the shell only; Files supplies New folder +
      Upload in SPEC-099).

### FR-005: Shared `Menu` primitive

#### Description:

Extract the accessible popover in `src/features/query/TableActionsMenu.tsx` into a reusable
`src/components/Menu.tsx` (trigger + `role="menu"` popover: `aria-haspopup`/`aria-expanded`,
focus-into-menu, Escape + outside-click close, arrow-key roving). Re-point `TableActionsMenu` to
compose the shared primitive with **no behavioral change**. Other surface specs (mobile overflow menus,
kebabs) consume this primitive.

#### Acceptance Criteria:

- [ ] `src/components/Menu.tsx` exists with the popover behavior (keyboard nav, Escape/outside-click
      close, focus management) and a documented props contract.
- [ ] `TableActionsMenu` composes `Menu` and its existing tests still pass unchanged (behavior and
      a11y identical).
- [ ] The primitive supports a `danger`-toned item and a separator (parity with today's kebab).
- [ ] `vitest-axe` assertions on the menu pass (no violations).

### FR-006: Responsive `Modal`

#### Description:

`Modal` keeps its centered desktop presentation but adapts on small screens: near-full-width within
consistent edge gutters (it already has `p-4`), content scrolls within the viewport, and the footer
keeps Cancel + action right-aligned (never full-bleed), matching the mockup's MODAL frames.

#### Acceptance Criteria:

- [ ] At `< tablet` the modal panel sits within edge gutters (does not touch the screen edges) and never
      exceeds the viewport height (long bodies scroll inside the panel).
- [ ] At `≥ tablet` the modal is visually identical to today (same `max-w-*`, centering, scrim, blur).
- [ ] Footer actions remain right-aligned at every width; the destructive/primary action is not
      stretched full-width.
- [ ] Escape + backdrop dismiss and focus-trap behavior are unchanged.

### FR-007: Responsive `Drawer` (side slide-over → mobile sheet)

#### Description:

Below `tablet`, `Drawer` renders as a **full-width sheet** instead of a 440px right slide-over: content
detail drawers (Files details, upload) present as a bottom sheet; member/roster drawers present as a
full-height sheet. A prop selects the mobile presentation (`mobileVariant?: 'bottom-sheet' |
'full-height'`, default `bottom-sheet`). Desktop presentation (440px right slide-over) is unchanged.

#### Acceptance Criteria:

- [ ] At `≥ tablet`, `Drawer` is the existing 440px right slide-over (no visual change).
- [ ] At `< tablet` with `mobileVariant="bottom-sheet"`, the panel is full-width, docked to the bottom,
      with rounded top corners, and dismisses via Escape / scrim / close / backdrop tap.
- [ ] At `< tablet` with `mobileVariant="full-height"`, the panel is a full-width, full-height sheet.
- [ ] Focus trap, scroll lock, Escape/scrim/close dismissal, and the header (title/subtitle/accessory/
      close) work identically across variants and widths.
- [ ] Existing `Drawer` callers (query history/saved, manage-members, metadata) render without prop
      changes (default `bottom-sheet`); member/roster drawers opt into `full-height`.

### FR-008: Responsive by default; separate markup only when structurally warranted

#### Description:

**Default to responsive utility variants on a single component tree.** Restyling across breakpoints —
spacing, direction, column counts, alignment, ordering, showing/hiding individual cells — must be done
by changing utilities on **one** element (`flex` → `tablet:grid`, `flex-col` → `tablet:flex-row`, `grid-cols-1`
→ `tablet:grid-cols-3`, `order-*`, `gap-*`, `hidden`/`desktop:block` on individual cells), **not** by cloning a
component into `*Mobile`/`*Desktop` twins for what is really the same layout. This keeps behavior,
state, refs, and accessibility in one place and is the expected approach for most surfaces.

**A distinct component or a `hidden tablet:*` / `tablet:hidden` markup branch is permitted when the two
presentations are genuinely, structurally different** — different DOM/semantics, not just different
spacing — such that forcing them onto one element would produce contorted markup. The canonical example
is the Files listing: a **data table (grid of columns)** on desktop/tablet versus a **compact two-line
card list** on mobile are different enough to warrant separate markup / a dedicated mobile row component
(SPEC-099). When a surface takes this path it must **state the structural justification** in its spec
and still **reuse the same data and shared child components/handlers** (no forked business logic). Use
this allowance deliberately — reach for it when the layouts truly diverge, not to avoid writing a few
responsive utilities.

Two cases that always justify a branch, because CSS alone cannot express them:

1. **Mounting cost / distinct interaction** — e.g. not mounting the Monaco editor on phones (hiding it
   with `hidden` still loads/instantiates it), a browse-first mobile Query surface, or a disclosure
   `Menu` that only exists on mobile. These may use a small viewport hook and reuse shared children.
2. **Mobile-only chrome** — e.g. the `MobileActionBar` or the hamburger trigger (`tablet:hidden`), which
   render one element conditionally and don't duplicate a content component.

Where a viewport hook is genuinely needed (mount-gating), provide it once as a shared `useBreakpoint()`
/ `useIsMobile()` hook in `src/lib/`, not ad-hoc `matchMedia` per feature.

#### Acceptance Criteria:

- [ ] Pure restyling reflows (spacing/direction/columns/alignment/cell visibility) are implemented with
      responsive utilities on **one** element, not duplicated component trees.
- [ ] Any separate component or `tablet:hidden`/`hidden tablet:*` markup branch is justified in the consuming
      spec as a genuine structural divergence (e.g. table vs card list) and reuses the same data +
      shared child components/handlers (no forked logic).
- [ ] Any conditional mount uses the shared `useBreakpoint`/`useIsMobile` hook and reuses shared
      child components/data.
- [ ] No `*Mobile`/`*Desktop` twin exists for a layout that is only a restyle of the same DOM.

---

## Data Model

No new persisted data. New component contracts only:

```ts
// src/components/AppNavDrawer.tsx
export type AppNavDrawerProps = {
  open: boolean;
  onClose: () => void;
  contextualRail?: React.ReactNode; // Files → Spaces list; Query → schema rail
};

// src/components/MobileActionBar.tsx
export type MobileActionBarProps = {
  children: React.ReactNode; // primary mobile actions
  ariaLabel?: string;
};

// src/components/Menu.tsx (extracted from TableActionsMenu)
export type MenuItem =
  | { kind: 'action'; label: string; icon?: React.ReactNode; tone?: 'default' | 'danger'; onSelect: () => void; disabled?: boolean }
  | { kind: 'separator' };
export type MenuProps = {
  trigger: (p: { open: boolean; toggle: () => void; ref: React.Ref<HTMLButtonElement> }) => React.ReactNode;
  items: MenuItem[];
  ariaLabel: string;
};

// src/components/Drawer.tsx — added prop
export type DrawerMobileVariant = 'bottom-sheet' | 'full-height';

// src/lib/useBreakpoint.ts — the ONE viewport hook (exception-2 uses only)
// SSR-safe matchMedia wrapper reading the tablet/desktop thresholds; not for styling
// (styling is Tailwind variants) — only for conditional MOUNT decisions.
export function useBreakpoint(): { isMobile: boolean; isTablet: boolean; isDesktop: boolean };
export function useIsMobile(): boolean; // convenience: viewport < tablet (900px)
```

## File & Folder Structure

```
src/
├── lib/
│   ├── useBreakpoint.ts           # new — shared viewport hook (mount-gating only)
│   └── useBreakpoint.test.ts      # new
├── components/
│   ├── Header.tsx                 # + hamburger (tablet:hidden) wiring
│   ├── AppNavDrawer.tsx           # new
│   ├── AppNavDrawer.test.tsx      # new
│   ├── MobileActionBar.tsx        # new
│   ├── MobileActionBar.test.tsx   # new
│   ├── Menu.tsx                   # new (extracted primitive)
│   ├── Menu.test.tsx              # new
│   ├── Modal.tsx                  # responsive gutters/height
│   └── Drawer.tsx                 # + mobileVariant
└── features/
    └── query/
        └── TableActionsMenu.tsx   # re-pointed onto Menu (no behavior change)
```

## Implementation Phases

### Phase 1: Conventions + primitives extraction

- Add the breakpoint subsection to `docs/best-practices/react.md`.
- Extract `Menu` from `TableActionsMenu`; re-point the caller; keep tests green.
- Make `Modal` responsive (gutters/height); verify existing dialog callers.

### Phase 2: App-shell navigation

- Build `AppNavDrawer` (300px, primary links + contextual slot) reusing `Drawer` mechanics.
- Add the mobile hamburger to `Header` (`tablet:hidden`), wiring open/close state + `aria-*`.
- Verify `PrimaryNav` is untouched at `≥ tablet`.

### Phase 3: Mobile action bar + responsive Drawer

- Build `MobileActionBar` (fixed bottom, safe-area, `tablet:hidden`).
- Add `mobileVariant` to `Drawer` and its bottom-sheet / full-height presentations; migrate callers'
  intent (defaults keep current behavior).

### Phase 4: A11y + tests

- `vitest-axe` on `AppNavDrawer`, `Menu`, responsive `Modal`/`Drawer`.
- Unit tests for open/close/focus-return, breakpoint gating (render assertions), and safe-area padding.

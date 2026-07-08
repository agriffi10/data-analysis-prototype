# Spec: Landing / Sign-in Page — Responsive Reflow

**ID:** SPEC-104
**Status:** Draft
**Last Updated:** 2026-07-08
**Depends On:** None
<!-- May optionally reuse the SPEC-095 shared `Menu` primitive (`src/components/Menu.tsx`) if present; a lightweight local disclosure is an acceptable fallback. -->

## Overview

The public marketing landing page (`/`, `apps/portal/src/routes/LandingPage.tsx`) is the app's most
responsive surface today, but it degrades badly on narrow viewports: below `tablet` the primary-nav links
(Features / Security) simply vanish with no replacement, the hero headline stays fixed at 46px and
overflows, the CTAs wrap awkwardly instead of stacking, and the feature grid jumps straight from 3-up
to 1-col with no intermediate tablet layout. This spec brings the landing page up to the full
three-tier responsive mockup (mobile / tablet / desktop) described in the design source, changing
**layout and reflow only** — no auth, routing, sign-in flow, or copy changes. The page must look and
behave correctly, with every sign-in / create-account path reachable, at every width.

## Scope

### In Scope

- Three responsive tiers for the existing landing page sections: sticky nav, hero, app-preview card,
  feature grid, CTA strip, footer.
- A mobile nav menu (hamburger disclosure) that surfaces the Features / Security anchor links behind a
  toggle below `tablet`, replacing today's "links just disappear" behavior. Reuse the SPEC-095 shared
  `Menu` primitive (`src/components/Menu.tsx`) if present; otherwise a small local disclosure component.
- Fluid hero headline sizing across the three tiers (46 → 40 → 32px).
- Full-width, stacked CTAs below `tablet`; app-preview card sidebar hidden on the smallest widths; feature
  grid stepping 3-up → 2-up-with-third-spanning → 1-col.
- Optional extraction of the mobile-menu markup into a co-located `LandingNavMenu.tsx` with a test.

### Out of Scope

- **No** change to authentication, the Amplify `signInWithRedirect` flow, `useAuth`, routing, or the
  `takeReturnPath` redirect behavior.
- **No** copy/content changes (headlines, body text, feature descriptions, badges all stay verbatim).
- **No** new colors, tokens, or design primitives beyond what already exists in `App.css`.
- **No** new dependencies. No changes to the authenticated app shell (SPEC-095 owns that).
- **No** functional additions (analytics, new links/sections, dark mode).

---

## Functional Requirements

<!-- Breakpoints (per SPEC-095): mobile = base (`< tablet`), tablet = `tablet` (900–1299px),
     desktop = `desktop` (≥1300px). Mobile-first — base classes are the mobile layout; `tablet:` / `desktop:`
     progressively enhance. -->

### FR-001: Responsive sticky nav with mobile menu

#### Description:

Below `tablet` the Features / Security anchor links must be reachable behind a hamburger toggle instead of
disappearing. At `tablet` and up the links render inline exactly as today. The brand mark and the
Sign in / Create account (or "Go to Dashboard") buttons stay visible and reachable at every width; the
buttons must not overflow or wrap out of the 64px nav bar on the smallest viewport.

#### Acceptance Criteria:

- [ ] At `< tablet`: the inline Features / Security link group is hidden and a hamburger toggle button is
      visible in the nav (accessible name e.g. "Open menu" / "Menu", `aria-expanded` reflecting state,
      `aria-controls` pointing at the panel).
- [ ] Activating the toggle reveals a panel containing the same two anchors (`#features`, `#security`);
      each anchor, when clicked, navigates to its section **and** closes the panel.
- [ ] The panel closes on Escape and on outside-click (inherited if the SPEC-095 `Menu` primitive is
      used; implemented locally otherwise).
- [ ] At `≥ tablet`: the hamburger toggle is hidden and the Features / Security links render inline (current
      behavior), with no duplicate/visible mobile panel.
- [ ] The Sign in and Create account buttons (or "Go to Dashboard" when authenticated) are present and
      clickable at base, `tablet`, and `desktop`, and do not overflow the nav container at 360px width.

### FR-002: Fluid hero headline and lead

#### Description:

The hero `<h1>` scales down across the three tiers so it never overflows, and the lead paragraph and
badge reflow cleanly.

#### Acceptance Criteria:

- [ ] The hero `<h1>` renders at ~32px at base (`< tablet`), ~40px at `tablet`, and 46px at `desktop` (e.g.
      `text-[32px] tablet:text-[40px] desktop:text-[46px]`).
- [ ] At 360px width the `<h1>` and lead `<p>` do not cause horizontal overflow (no horizontal scrollbar
      on the page).
- [ ] The badge, headline, lead, and reassurance line remain centered and vertically ordered at all
      three tiers (no content reordering).

### FR-003: Full-width, stacked CTAs on mobile

#### Description:

The hero CTA group (Create your account / Sign in, or Go to Dashboard) stacks vertically and each button
spans the container width below `tablet`; at `tablet`+ it stays the current centered, side-by-side row.

#### Acceptance Criteria:

- [ ] At `< tablet`: the CTA group is a vertical stack (`flex-col`) and each button is full-width
      (fills the container, e.g. `w-full`), Create your account above Sign in.
- [ ] At `≥ tablet`: the CTA group is a horizontal, centered row (current `flex-wrap justify-center` layout),
      buttons sized to content.
- [ ] The same stack/row rule applies to the bottom CTA-strip buttons (`#security`) so they match the
      hero behavior; when authenticated the single "Go to Dashboard" button is full-width at `< tablet`.
- [ ] All CTA buttons remain wired to their existing handlers (`signUp` / `signIn` / `navigate('/files')`)
      — handlers unchanged.

### FR-004: App-preview card reflow

#### Description:

The decorative browser-chrome app-preview card drops its fake sidebar on mobile (showing the file
table only) and shows the two-column layout from tablet up, so it never overflows. Its current `sm:`
classes (`hidden sm:block`, `grid-cols-1 sm:grid-cols-[200px_1fr]`) are migrated to `tablet:` since the
`sm` prefix is removed by SPEC-095's breakpoint reset.

#### Acceptance Criteria:

- [ ] On mobile (`< tablet`): the preview sidebar is hidden (`hidden tablet:block`) and the file-table
      column occupies the full card body (`grid-cols-1 tablet:grid-cols-[200px_1fr]`).
- [ ] At `≥ tablet`: the two-column (sidebar + table) layout renders.
- [ ] No `sm:` (or other removed default) prefix remains on the preview card.
- [ ] The card stays within its container (`max-w-[920px]`, `mx-auto`) and does not cause horizontal
      overflow at base, `tablet`, or `desktop`.
- [ ] The card remains `aria-hidden="true"` (decorative) — no change to its semantics.

### FR-005: Feature grid three-tier stepping

#### Description:

The `#features` grid steps through three layouts: single column on mobile, 2-up with the third card
spanning the full row on tablet, and 3-up on desktop.

#### Acceptance Criteria:

- [ ] At `< tablet`: the three feature cards render in a single column (`grid-cols-1`).
- [ ] At `tablet` (tablet): the grid is 2 columns and the third card spans both columns (e.g.
      `tablet:grid-cols-2` with the third card carrying `tablet:col-span-2 desktop:col-span-1`).
- [ ] At `desktop`: the grid is 3 columns with each card in its own column (`desktop:grid-cols-3`, no span).
- [ ] Card content, order, and copy are unchanged across all tiers.

### FR-006: Docs / secondary link dropped at tablet (nav link set)

#### Description:

Per the design source, the tablet nav carries a reduced link set — the secondary "Docs"-style link is
not shown at `tablet` (only the primary Features / Security anchors remain inline). Because the current page
has no Docs link, this FR pins the intended behavior: any tertiary nav link introduced must be hidden at
`tablet` and only appear at `desktop`, and the mobile menu (FR-001) is the catch-all for links not shown inline.

#### Acceptance Criteria:

- [ ] At `tablet`: only the primary Features / Security anchors render inline in the nav; no tertiary/Docs
      link is visible.
- [ ] Any tertiary nav link present in the markup uses `hidden desktop:inline-flex` (or equivalent) so it
      appears only at `desktop`, and is included in the mobile menu panel at `< tablet`.
- [ ] If no tertiary link exists, the nav renders Features / Security inline at `tablet`+ and the criterion
      is satisfied vacuously (documented in the delivery doc).

---

## Data Model

No new data model. This is a presentation-only change. If a mobile-menu open/close state is introduced
locally, it is a single component-local boolean (`useState<boolean>`); if the SPEC-095 `Menu` primitive
is reused, it owns its own open state and no new state is added to `LandingPage`.

---

## API / Interface Contract

If the mobile menu is extracted, its component contract is:

```ts
// src/routes/LandingNavMenu.tsx  (or components/ — co-located with LandingPage)
export type LandingNavLink = {label: string; href: string};

export type LandingNavMenuProps = {
  links: LandingNavLink[]; // e.g. [{label: 'Features', href: '#features'}, {label: 'Security', href: '#security'}]
};

// Renders a hamburger toggle (< tablet only) that discloses `links`; each link closes the panel on click.
export function LandingNavMenu(props: LandingNavMenuProps): JSX.Element;
```

If the SPEC-095 shared `Menu` primitive is present, `LandingNavMenu` composes it; otherwise it
implements a lightweight disclosure (toggle button + panel, Escape + outside-click close).

## Environment Variables

None.

## File & Folder Structure

```
apps/portal/src/routes/
├── LandingPage.tsx            # modified — responsive classes on nav/hero/CTAs/preview/feature grid
├── LandingNavMenu.tsx         # new (optional extraction of the mobile menu; composes SPEC-095 Menu if present)
└── LandingNavMenu.test.tsx    # new (optional) — toggle reveals links, link click closes, Escape closes
apps/portal/src/routes/
└── LandingPage.test.tsx       # new or extended — asserts the responsive markers below
```

Tests assert the binary criteria via class presence / element visibility at the relevant breakpoints
(RTL — the hamburger toggle exists, `aria-expanded` flips on activation, the panel exposes both anchors,
and the responsive Tailwind classes are present on the hero `h1`, CTA group, preview sidebar, and feature
grid). Run `vitest-axe` on the rendered page and on `LandingNavMenu` to confirm no a11y regressions.

## Implementation Phases

### Phase 1: Mobile nav menu

- Add the hamburger toggle to the sticky nav, visible only at `< tablet`; hide the inline link group at `< tablet`
  and keep it inline at `tablet`+.
- Reuse the SPEC-095 `Menu` primitive if available (compose it); otherwise build a lightweight local
  disclosure (toggle + panel, `aria-expanded`/`aria-controls`, Escape + outside-click close).
- Optionally extract into `LandingNavMenu.tsx`; wire the Features / Security anchors so a click navigates
  and closes the panel. Add `LandingNavMenu.test.tsx`.

### Phase 2: Hero, CTAs, and app-preview reflow

- Make the hero `<h1>` fluid: `text-[32px] tablet:text-[40px] desktop:text-[46px]`; verify badge/lead reflow.
- Make the hero and CTA-strip button groups stack full-width at `< tablet` (`flex-col` + `w-full`) and stay
  the centered row at `tablet`+.
- Migrate the app-preview sidebar to `hidden tablet:block` and body to `grid-cols-1 tablet:grid-cols-[200px_1fr]`
  (off the removed `sm:` prefix); verify no overflow at any tier.

### Phase 3: Feature grid tiers, verification, and docs

- Step the feature grid `grid-cols-1 tablet:grid-cols-2 desktop:grid-cols-3`, with the third card
  `tablet:col-span-2 desktop:col-span-1`.
- Verify the whole page at base (360px), `tablet` (900px), and `desktop` (≥1300px): no horizontal overflow, all
  CTAs reachable, nav links reachable via the mobile menu at `< tablet`.
- Extend `LandingPage.test.tsx`; run `vitest-axe`; complete the completion ritual (delivery doc,
  component-inventory row if `LandingNavMenu` is extracted, Help-content sweep — likely "no user-facing
  content change, skip").

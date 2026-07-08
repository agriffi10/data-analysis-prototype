# Completed Spec — SPEC-104: Landing / Sign-in Responsive Reflow

## What was completed?

The public landing page (`/`) now reflows cleanly across mobile / tablet / desktop. Layout only — no auth/routing/copy change.

- **Mobile nav menu (FR-001):** new **`LandingNavMenu`** — a `tablet:hidden` hamburger composing the SPEC-095 `Menu` primitive; discloses the Features / Security anchors (each sets `window.location.hash` and closes; Escape/outside-click inherited). Inline link group stays `hidden tablet:flex`. Nav gaps/padding tightened on mobile and the Sign in / Create account buttons use `!px-3 tablet:!px-5` so nothing overflows at 360px.
- **Fluid hero (FR-002):** `<h1>` → `text-[32px] tablet:text-[40px] desktop:text-[46px]`.
- **Stacked CTAs (FR-003):** hero + CTA-strip button groups are `flex-col` + `w-full` below tablet, centered row (`tablet:flex-row … tablet:w-auto`) at ≥ tablet.
- **App-preview (FR-004):** already migrated to `tablet:` in SPEC-095 (sidebar `hidden tablet:block`, body `grid-cols-1 tablet:grid-cols-[200px_1fr]`) — verified, no `sm:` remains.
- **Feature grid (FR-005):** `grid-cols-1 tablet:grid-cols-2 desktop:grid-cols-3` with the third card `tablet:col-span-2 desktop:col-span-1`.
- **FR-006:** vacuous — the page has no tertiary/Docs link, so Features/Security render inline at ≥ tablet (documented here as the spec requires).

## What changed from earlier specs?

- `LandingPage` nav restructured (hamburger + `NAV_LINKS` array); its buttons gained responsive padding. No behavior change (handlers unchanged).

## Verification

`format` + `lint` + `tsc -b` + `build` clean; full suite green (1095, +11: `LandingNavMenu` toggle/reveal/navigate-close/Escape/outside-click/axe + `LandingPage` responsive markers). **Browser-verified** live at 360 / 1000 / 1400px: no horizontal overflow at any tier; hamburger↔inline-links swap, h1 32/40/46px, CTA stack↔row, feature grid 1→2(3rd spans)→3 all confirmed; hamburger opens the menu, a link navigates to `#features` and closes it; no console errors.

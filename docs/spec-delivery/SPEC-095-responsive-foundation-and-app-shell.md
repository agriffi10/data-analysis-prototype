# Completed Spec — SPEC-095: Responsive Foundation & App Shell

## What was completed?

The shared responsive foundation the surface specs (099→104) build on — presentation/chrome only, no data/IAM/infra change.

- **Breakpoint convention.** `src/index.css` `@theme` resets Tailwind's default breakpoints (`sm`/`md`/`lg`/`xl`/`2xl` → `initial`) and defines `--breakpoint-tablet: 900px` + `--breakpoint-desktop: 1300px`, so only mobile-first `tablet:` / `desktop:` (+ `max-*`) prefixes compile. Migrated every prior default-prefix usage (`CollapsibleRail`, `HelpSidebar`, `LandingPage`, **+`PartitionKeysField`** — needed to keep AC-4 "no default prefixes remain"). Documented as `react.md` §20 "Responsive design".
- **`useBreakpoint` / `useIsMobile`** (`src/lib/useBreakpoint.ts`) — `matchMedia`-backed, `useSyncExternalStore`, SSR-safe (defaults desktop). **Mount-gating only**, never styling.
- **`AppNavDrawer`** (`src/components/AppNavDrawer.tsx`) — 300px left off-canvas sheet: five primary links (Files/Query/Connections/Notifications/Help, active via `NavLink aria-current`) + a page-supplied `contextualRail` slot; focus trap + scroll lock + Escape/scrim/link dismiss.
- **`NavRailProvider` + `navRailContext`** (`useProvideNavRail`/`useNavRailContent`) — lets a page feed its rail into the Header-owned drawer (no page consumes it yet; wired in 099/100).
- **Header** — mobile hamburger (`tablet:hidden`, ≥44px, `aria-controls`) opening the drawer (mounted only when `useIsMobile`); `PrimaryNav` wrapped `hidden tablet:flex`.

  > **Correction (2026-09-14) — the "≥44px" above is false, and was false when written.** The
  > hamburger is `h-11 w-11`, whose px value was read off the class at an assumed 16px root. This
  > app's root is **14px**, so it draws **38.5px** square (11 × 0.25rem × 14px). Left there
  > deliberately, for the reason [SPEC-100's correction](SPEC-100-query-workspace-responsive.md)
  > records: 44×44 is SC 2.5.5, which is AAA, and this project targets A + AA.
- **`MobileActionBar`** (`src/components/MobileActionBar.tsx`) — fixed-bottom `tablet:hidden` toolbar, safe-area-inset aware; shell only.
- **`Menu`** (`src/components/Menu.tsx`) — accessible menu primitive extracted from `TableActionsMenu` (render-prop trigger + `role="menu"` popover, arrow roving, Escape/outside-click, danger tone + separators). `TableActionsMenu` now composes it, behavior unchanged.
- **Responsive `Modal`** (viewport-capped + scroll-in-panel) and **`Drawer`** (`mobileVariant: 'bottom-sheet' | 'full-height'`, default bottom-sheet; member/roster drawers opt into full-height). Desktop presentations unchanged.

## What changed from earlier specs?

- `TableActionsMenu` (SPEC-044) re-implemented on top of the new `Menu` — same props/DOM/tests, `aria-controls` on the trigger dropped (menu id is internal to `Menu`).
- `Drawer` (SPEC-035-era) gained `mobileVariant`; `ManageMembersDrawer`/`MemberRosterDrawer` pass `full-height`. All other callers keep the default.
- `test-setup.ts` gained a width-driven `matchMedia` stub (default 1024 → non-mobile, so existing tests are unaffected).

## Verification

`format` + `lint` + `tsc` clean; full suite green (1055 tests, +29 new incl. `useBreakpoint`, `Menu`, `AppNavDrawer`, `MobileActionBar`, `Header`, responsive `Modal`/`Drawer`, all with `vitest-axe`). `npm run build` compiles the custom breakpoints; browser-verified on the public landing page that `tablet:`/`desktop:` apply (nav links + feature grid reflow at 390/1400px). Authenticated mobile drawer covered by unit tests (preview can't hold a Cognito session).

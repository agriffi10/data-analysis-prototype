# Completed Spec - SPEC-029 Landing Page Full Design

## What was completed from this spec?

`LandingPage.tsx` was rewritten from the minimal auth-gate card (SPEC-022) into the full
five-section marketing page, and `RootLayout.tsx` now suppresses the app `Header` on `/`:

- **Route isolation**: `RootLayout` reads `useLocation().pathname`; when `=== '/'` the
  `<Header />` is not rendered and the `<Outlet />` fills the viewport. All other routes keep
  the header.
- **Sticky nav**: frosted `bg-white/80 backdrop-blur` bar, `<BrandMark />`, "Features"/"Security"
  anchor links (`md:flex`), ghost Sign in + primary Create account (`Button`, `!h-10 !px-5`).
- **Hero**: eyebrow pill (shield SVG + copy), 46px two-tone `<h1>` ("…scoped to you" in accent),
  lead paragraph, `lg` CTAs (Create your account / Sign in), reassurance line with a success
  checkmark.
- **AppPreview**: a decorative (`aria-hidden`) browser-chrome card — three dots, a sidebar
  (My Files → active "alice", Shared → Project Alpha/Beta), and a 4-row file grid (one folder +
  three files with sizes/dates). Sidebar hides on mobile (`sm:` grid collapse).
- **Features**: three cards (`md:grid-cols-3`) with accent icon blocks (upload / folder / link
  SVGs) and the spec copy.
- **CTA strip** (`#security`): `bg-accent` box with white/translucent raw `<button>` CTAs
  (FR-006 explicitly permits raw buttons here).
- **Footer**: `<BrandMark size="sm" />` + "© 2026 FilePortal · Privacy Terms".
- The SPEC-022 username-format hint was removed (FR-008).

`Button` gained a `lg` size (`h-[46px] px-6 text-md`) per FR-003.

Verified in the preview: sticky nav, hero, app preview, features, CTA strip, footer all render
correctly; nav `position: sticky`.

## What has changed?

- **RootLayout test updated (deliberate behaviour change).** The old test asserted the Header
  ("S3 File Portal") renders on `/`. Since the Header is now suppressed there, the test was
  rewritten: header + child content assert on a non-landing route (`/files`), and a second case
  asserts the header is absent on `/`. This is a required update for the changed behaviour, not
  a regression.
- **Nav button sizing uses `!h-10 !px-5`.** `Button` always applies a size token (`h-9` for md),
  so the FR-002 `h-10 px-5` nav sizing uses Tailwind `!important` to win over the token reliably
  (same rationale as SPEC-028's documented override approach).
- Styling/markup only — `signIn`/`signUp` handlers and the authenticated-redirect are unchanged.

`lint`, `test` (241, +1 RootLayout case), and `build` all green.

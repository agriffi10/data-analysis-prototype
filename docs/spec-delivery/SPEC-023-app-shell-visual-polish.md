# Completed Spec - SPEC-023 App Shell Visual Polish

## What was completed from this spec?

The persistent app chrome was restyled onto the design system:

- **`Header.tsx`**: 56px `h-14 bg-surface border-b border-border` topbar; full-width inner
  flex row (`px-4`, no `max-w-4xl`). Left: brand mark — `rounded-md bg-accent` 32×32 square
  with the 16×16 white upload-arrow SVG + "S3 File Portal" wordmark (`text-md font-semibold
  text-text`). A `flex-1` spacer separates brand from the user zone.
  - **Unauthenticated**: indigo "Sign in" primary button (`h-9 bg-accent hover:bg-accent-hover`).
  - **Authenticated**: username (`text-sm text-text-2`), a 32×32 gradient-circle avatar
    (`bg-gradient-to-br from-accent to-accent-hover`) showing the first two username chars
    uppercased, and a ghost "Sign out" button.
  - **Loading**: a single muted `…` (`text-text-3`).
  - **Error banner**: `border-danger-soft bg-danger-soft text-danger`.
- **`RootLayout.tsx`**: outer wrapper now `bg-bg` (was `bg-gray-50`).
- **`ProtectedLayout.tsx`**: loading indicator now `text-text-3` (was `text-gray-400`).

## What has changed?

Styling only — `signIn`/`signOut`/`status` logic, `role="status"`/`role="alert"`, and the
dev-bypass gate are all unchanged. Existing `RootLayout`/`ProtectedLayout` tests (which
assert text + ARIA roles, not classes) pass unmodified.

The brand-mark markup is duplicated between the Header and the SPEC-022 LandingPage; both
get extracted into a shared `BrandMark` component in SPEC-028 (noted inline in both files).

`lint`, `test` (225 passing), and `build` all green; header verified in the preview server.

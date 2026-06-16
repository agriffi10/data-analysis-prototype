# Completed Spec - SPEC-022 Landing Page Visual Polish

## What was completed from this spec?

`apps/portal/src/routes/LandingPage.tsx` was restyled onto the design-system tokens:

- Page root: `flex min-h-screen flex-col items-center justify-center bg-bg px-6`; content
  card `max-w-sm text-center`.
- **Brand mark**: a 32×32 `rounded-md bg-accent` square holding a 16×16 white upload-arrow
  SVG, with the "S3 File Portal" wordmark below in `text-md font-semibold text-text`. Per
  FR-003 the duplicate `<h1>` heading was dropped — the brand mark serves as the name.
- Description in `text-sm text-text-2`.
- **Sign in** (primary `bg-accent … hover:bg-accent-hover`) and **Create account**
  (default `border-border bg-surface … hover:bg-surface-2`) buttons, each
  `h-9 w-full max-w-[200px]`, stacked in `mt-8 flex flex-col items-center gap-3`.
- Username hint in `text-xs text-text-3 leading-relaxed` with the `. _ @ -` token in a
  styled `<code>` (`bg-surface-2 border border-border rounded-sm px-1 font-mono text-xs`).

Verified in the preview server: body bg `#f7f8fa`, indigo Sign in button, hairline-bordered
Create account, Inter at 14px base.

## What has changed?

Styling only — no change to auth logic, routing, `signIn`/`signUp` handlers, or copy. The
upload-arrow SVG defined inline here is the same mark used by the Header in SPEC-023; both
get extracted into a shared `BrandMark` component in SPEC-028.

`lint`, `test` (225 passing), and `build` all green.

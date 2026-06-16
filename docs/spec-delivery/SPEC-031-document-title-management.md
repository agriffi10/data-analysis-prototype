# Completed Spec - SPEC-031 Document Title Management

## What was completed from this spec?

- **`src/lib/formatPageTitle.ts`** — pure `formatPageTitle(page?)` returning
  `"{page} — S3 File Portal"` (em-dash) or `"S3 File Portal"` when omitted/empty. The app-name
  suffix is a single `APP_NAME` constant. Co-located `formatPageTitle.test.ts` covers the four
  spec cases.
- **`src/hooks/usePageTitle.ts`** — `usePageTitle(page?)` sets `document.title` via a single
  `useEffect` keyed on `[page]`; no unmount restore (the next page sets its own). First file in
  the new `src/hooks/` directory.
- **Page wiring** (called unconditionally at the top of each):
  - `LandingPage` → `usePageTitle()` → "S3 File Portal".
  - `FilesPage` → `usePageTitle('Files')` → "Files — S3 File Portal".
  - `NotFoundPage` → `usePageTitle('Not Found')` → "Not Found — S3 File Portal".
- **`index.html`** `<title>` changed from the scaffold `s3-upload-portal` to `S3 File Portal`
  (pre-hydration fallback).

Verified in the preview: title is "S3 File Portal" on `/` and updates to
"Not Found — S3 File Portal" on an unknown route, without a reload.

## What has changed?

Net-new additive feature — no existing behaviour altered. Test suite 241 → **243** (the two
`formatPageTitle` assertions). `lint`, `test`, and `build` all green.

New reusable surface added to the component inventory: `formatPageTitle` (`lib/`) and
`usePageTitle` (`hooks/`).

# Completed Spec — SPEC-081: Double-Click a File to Download

## What was completed?

Double-clicking a file row in the file browser now downloads it, matching the desktop gesture, reusing the
existing presigned-URL download path. Frontend-only; no IAM/infra/data-layer change.

- **`FileRow` gained `onActivate` (FR-001):** wired to the `<li>`'s `onDoubleClick`, passed to **every** file row
  (both the authenticated and read-only browse flows), invoking the browser's existing `handleDownload(file)`. The
  explicit Download controls (read-only row button / selection toolbar) are unchanged.
- **Exclusions (FR-001):** the checkbox wrapper and the actions wrapper `stopPropagation` on double-click, so
  double-clicking them keeps their own behavior and never triggers a download.
- **No-dupe (FR-002):** `handleDownload` now early-returns when the key is already downloading, so a rapid second
  double-click is a no-op; failures still surface the existing dismissible "Could not download …" banner.
- **No stray selection + affordance (FR-003/FR-004):** the row is `select-none cursor-pointer` with a
  `title="Double-click to download …"`; the handler also clears any selection range. The keyboard-accessible
  Download controls remain the a11y route (double-click is a mouse convenience).

## What changed from earlier specs?

`FileRow` (internal to `FileBrowser`) gained a required `onActivate` prop; no external call-site change. No service
or hook signatures changed.

## Verification

`format:check`, `tsc`/`build`, ESLint, and full Vitest green (new `FileBrowser` tests: double-click downloads in
both flows, checkbox/action-button double-click does not, busy no-dupe, error banner). Live browser deferred — the
authenticated `/files` flow needs Cognito + a real user-space bucket, and the dev-unauth read-only path points at a
placeholder bucket locally, so a real presigned download isn't exercisable here (same limitation as prior file-browser specs).

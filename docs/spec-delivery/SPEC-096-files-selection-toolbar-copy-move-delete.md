# Completed Spec — SPEC-096: Selection Toolbar Narrowed to Copy / Move / Delete

## What was completed?

The file-browser multi-select bar (`SelectionToolbar`, inline in `FileBrowser.tsx`) is now a focused **bulk-action** bar: it keeps the master checkbox, live "N selected" label, `accent-soft` styling, and **Copy / Move / Delete**. **Download and Rename were removed** — they are single-item actions and moved to the per-object details panel (SPEC-097).

- Dropped the `onRequestDownload` / `onRequestRename` toolbar props and the `single`/`canRename`/`canDownload` gating.
- `FileBrowser` no longer passes those handlers to the toolbar.

Shipped together with SPEC-097 in one PR so authenticated Rename is never left without an entry point between the two.

## What changed from earlier specs?

- The SPEC-018/019 selection toolbar's button set changed (Download/Rename gone). Toolbar Copy/Move/Delete flows are unchanged.

## Verification

`format` + `lint` + `tsc` clean; full suite green (1061). `FileBrowser.test` updated to assert the three-button toolbar and that Download/Rename are absent from it.

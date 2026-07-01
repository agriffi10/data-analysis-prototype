# Spec: Double-Click a File to Download

**ID:** SPEC-081
**Status:** Draft
**Last Updated:** 2026-07-01
**Depends On:** SPEC-015 (file download), SPEC-018 (selection model)

## Overview

In the file browser, opening a folder is a single click on its row, but downloading a
file requires finding the Download control — the row-level Download button (read-only
browse) or selecting the file and using the selection toolbar's Download (the
authenticated flow). Users expect the familiar desktop gesture: **double-click a
file to download it.** This spec adds double-click-to-download on file rows, reusing
the existing presigned-URL download path, so the gesture matches how single-click
already opens folders.

## Scope

### In Scope

- Double-clicking a **file** row triggers that file's download (the same presigned-
  URL + attachment flow used by the existing Download controls, `handleDownload`).
- Works in both the authenticated (writable) flow and the read-only (dev-unauth)
  browse flow.
- Preserves the existing per-file busy/error handling (the row shows the download in
  progress; a failure surfaces via the existing dismissible download-error banner).
- Suppresses the accidental text-selection that a double-click would otherwise cause
  on the filename.
- Leaves the explicit Download controls (row button / selection toolbar) in place —
  double-click is an addition, not a replacement.

### Out of Scope

- Double-clicking a **folder** to open it — folders already open on single click;
  this spec does not change folder interaction.
- Double-click to **rename** or open a details/preview view — download only.
- Multi-file download (double-click acts on the one row, not the selection).
- Changing the checkbox selection behavior, keyboard activation, or single-click
  semantics of file rows.
- Downloading protected/hidden items (the marker and hidden folders are already
  filtered from the listing).

---

## Functional Requirements

### FR-001: Double-click a file row downloads it

#### Description:

A double-click anywhere on a file row (outside the selection checkbox and the
existing action buttons) starts that file's download via the existing
presigned-URL flow.

#### Acceptance Criteria:

- [ ] Double-clicking a file row calls the same download path as the Download
      button (`handleDownload(file)`), producing the attachment download.
- [ ] It works in the authenticated flow (where the row has no inline Download
      button) and in read-only browse (where it does).
- [ ] Double-clicking the row's checkbox or an action button does **not** trigger a
      download (those retain their own behavior).

### FR-002: Busy + error handling preserved

#### Description:

A double-click download reuses the existing busy/error affordances: the row reflects
the in-flight download and a failure shows the existing non-blocking error banner.

#### Acceptance Criteria:

- [ ] While the presigned URL is being fetched, the row shows its busy state
      (as the button flow does today).
- [ ] A failed download shows the existing dismissible "Could not download …"
      banner; no unhandled throw.
- [ ] A second double-click while one is in flight does not start a duplicate
      download for the same key.

### FR-003: No accidental text selection

#### Description:

Double-clicking a file row must not leave the filename text highlighted/selected.

#### Acceptance Criteria:

- [ ] After a double-click, no stray text selection remains on the row.
- [ ] Normal single-click selection (checkbox) and folder single-click open are
      unaffected.

### FR-004: Discoverability affordance

#### Description:

The file row signals that it is double-click-actionable (e.g. a `cursor` affordance
and/or an accessible title), so the gesture is discoverable without changing the
row's primary layout.

#### Acceptance Criteria:

- [ ] A file row shows a pointer/affordance indicating it is interactive.
- [ ] The affordance does not remove or relabel the existing Details/Download
      controls.
- [ ] The explicit Download controls remain the keyboard-accessible path (double-
      click is a mouse convenience, not the only route — no a11y regression).

---

## Data Model

No new types. Reuses `S3FileItem` and the existing `handleDownload(file: S3FileItem)`
in `FileBrowser.tsx`.

## API / Interface Contract

```ts
// FileRow gains an onDoubleClick handler wired to the same download callback the
// browser already owns. handleDownload is passed to every file row (not only the
// read-only row button), guarded so it no-ops while that key is already downloading.
<FileRow ... onActivate={() => handleDownload(file)} /> // fires on row double-click
```

## File & Folder Structure

```
apps/portal/src/features/file-browser/
├── FileBrowser.tsx        # FileRow onDoubleClick → handleDownload; select-none on row
└── FileBrowser.test.tsx   # double-click downloads; checkbox/button double-click doesn't;
                           # busy no-dupe; read-only + authenticated flows
```

## Implementation Phases

### Phase 1: Wire double-click to download

- Add an `onDoubleClick` on the file row invoking the existing `handleDownload`
  (passed to all file rows, guarded against duplicate in-flight downloads); apply a
  `select-none` / selection-clear so no text stays highlighted; add the cursor/title
  affordance. Ensure the checkbox and action buttons don't bubble into it.

### Phase 2: Tests + completion ritual

- Component tests (both flows; checkbox/button exclusion; busy no-dupe; error
  banner); delivery doc + INDEX status.

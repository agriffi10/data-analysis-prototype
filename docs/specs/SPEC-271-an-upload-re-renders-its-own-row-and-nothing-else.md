---
type: Spec
id: SPEC-271
title: "An Upload Re-renders Its Own Row and Nothing Else"
description: "Narrows what an upload's progress costs the browser: the Files page no longer renders on a progress event, progress is coalesced and a repeat commits nothing, one row of the uploads list renders per tick, and a batch of files refreshes its folder at most once every two seconds; a render counter for tests lands with it."
spec_status: Draft
depends_on: []
arc: render-scope
arc_order: 1
---

## Overview

While a file uploads, the browser reports progress many times a second, and today every one of
those reports redraws the whole Files page: the toolbar, the listing, every dialog and every row of
the uploads list, whether or not anything on them changed. Each finished file also re-reads the
folder's listing, so a batch of three hundred small files reads it three hundred times. This spec
makes an upload cost what it changes: a progress report redraws the one row it belongs to, reports
arriving faster than a person can read are merged, and a batch refreshes its folder at most once
every two seconds. Nothing a user does changes, and the one thing they can see is that during a
burst of small files the listing fills in every two seconds rather than file by file.

It is the first spec of the render-scope arc, so it also delivers the tool the arc measures with: a
render counter for tests, which reads off React's committed tree which components rendered and how
many nodes were re-walked, without touching the components measured.

## Scope

### In Scope

- The upload queue's context, split so a consumer of the actions does not render when items change.
- Coalescing of progress reports, and a reducer that returns the same state for a report that
  changes nothing.
- A memoised uploads-list row.
- Coalescing of the folder refresh that follows a finished upload.
- `src/test/renderCounter.tsx`, and a render-scope suite for uploads whose budgets fail when any of
  the above regresses.

### Out of Scope

- **Where the provider is mounted.** It stays at the signed-in shell
  (`components/ProtectedLayout.tsx`); that placement is what keeps an upload alive across pages.
- **Windowing the uploads list.** Finished rows stay until cleared, as today. Once a tick renders
  one row the list's length no longer multiplies the cost of progress, and a user clears the list
  with one button.
- **`lastModified` as a `Date` in the listing.** It defeats TanStack's structural sharing, so a
  refetch hands every row a new object. A listing page holds at most `LISTING_PAGE_SIZE` (25) rows
  and, after this spec, is redrawn by a refetch at most once every two seconds, so the type change
  across the listing's fixtures buys nothing that can be measured.
- **Memoising the listing's rows.** For the same reason: the page no longer renders on progress.
- The Query workspace and the Data Explorer, which are SPEC-272 and SPEC-273.

---

## Functional Requirements

### FR-001: The Files page does not render on an upload's progress

#### Description:

`UploadQueueProvider` supplies the queue's actions and its items through two contexts. The actions
value is one object whose identity never changes for the life of the provider; the items value
changes when an item does. `FileBrowser` reads the actions alone. `useUploadQueue()` keeps
returning both, for a consumer that needs both.

#### Acceptance Criteria:

- [ ] With the Files page mounted over a listing and an upload in flight, a progress report that
      changes the item renders neither `FileBrowserContent` nor any `FileRow` (counted with the
      render counter; before this spec both render, the second once per listed file).
- [ ] `useUploadActions()` and `useUploadItems()` each throw outside a provider, naming the hook.
- [ ] An upload started from the dropzone still enqueues to the folder on screen, and
      `UnloadGuard` and `UploadsAtRiskNotice` still follow the queue: the existing file-browser
      and shell suites pass with no assertion weakened.

### FR-002: Progress is coalesced, and a report that changes nothing commits nothing

#### Description:

The provider merges progress reports per item and dispatches them together: the first report after
an idle period is dispatched at once, and reports arriving within `UPLOAD_PROGRESS_FLUSH_MS` (100)
of a dispatch are held, the latest per item winning, and dispatched together when that window
ends. The window is half the progress bar's 200 ms width transition, so the bar never waits on a
report. The reducer's `progress` arm returns the state it was given when no item's `loaded` or
`total` changes. A held report for an item that has since settled or been removed is dropped, so a
retry never shows the previous attempt's progress.

#### Acceptance Criteria:

- [ ] Sixty progress reports for one uploading item, delivered in separate tasks inside one window,
      cause at most two commits (the leading dispatch and the window's end), and the row then shows
      the last report's figures.
- [ ] A report repeating the item's current `loaded` and `total` causes no commit.
- [ ] A report for an item that is not `uploading` leaves the state object identical (`toBe`).
- [ ] A cancelled upload's bar does not move after the cancel, and an upload retried after a name
      collision starts from zero.
- [ ] Unmounting the provider with a window open dispatches nothing afterwards and leaves no timer.

### FR-003: A progress tick renders one row of the uploads list

#### Description:

The uploads-list row is memoised on its item, and reads its actions from the actions context. The
reducer already keeps the identity of every item an action does not touch.

#### Acceptance Criteria:

- [ ] With thirty items in the list and three uploading, a progress report for one item renders
      `UploadRow` exactly once (before this spec: thirty times).
- [ ] The list's header still counts uploads in progress and rows waiting on a name, and
      **Clear finished**, cancel, dismiss and both collision answers still work: the existing
      suites pass with no assertion weakened.

### FR-004: A batch of uploads refreshes its folder at most once every two seconds

#### Description:

A finished upload refreshes the listing of the folder it was written to. The first one to finish
in a folder refreshes it at once. Any others finishing in that folder within
`UPLOAD_LISTING_REFRESH_MS` (2,000) of a refresh share one refresh at the end of that window, and
that repeats for as long as files keep finishing, so the last finished file is always followed by
a refresh. Folders are coalesced separately, keyed by bucket and prefix. This is Andrew's decision
of 2026-11-27, chosen over refreshing once when the batch ends and over leaving it per file.

#### Acceptance Criteria:

- [ ] One finished upload invalidates its folder's listing before any timer runs.
- [ ] Thirty uploads to one folder finishing inside one window read the listing twice: once for
      the first, once when the window ends (before this spec: thirty times).
- [ ] Uploads finishing in two folders inside one window refresh each folder, independently.
- [ ] A file finishing after a window has closed with nothing pending refreshes at once.
- [ ] Unmounting the provider with a window open leaves no timer, and invalidates nothing
      afterwards.
- [ ] A failed, cancelled or colliding upload refreshes nothing.

### FR-005: A render counter measures what a gesture re-renders

#### Description:

`createRenderCounter()` returns a probe component and `reset`/`read` functions. Wrapped around a
tree in a test, it reports for the commits since the last reset: how many there were, which
components rendered and how many times each, by name, and how many fibers React created or cloned,
host elements included. It touches none of the components it measures.

#### Acceptance Criteria:

- [ ] Under the probe, a parent whose state changes over a memoised child with unchanged props
      reports the parent rendered once and the child not at all; with the memo removed from the
      fixture it reports the child once.
- [ ] A component that sets the state it already holds reports no render.
- [ ] Two state changes in separate tasks report two commits; two in one task report one.
- [ ] The uploads render-scope suite asserts FR-001's and FR-003's counts through it, and each of
      those assertions fails when the split context, or the row's memo, is reverted (mutation-tested
      once each, recorded in the delivery doc).

---

## Data Model

```ts
// src/features/file-browser/uploadQueueContext.ts

export type UploadQueueActions = {
  enqueue: (files: File[], dest: UploadDestination) => void;
  cancel: (id: string) => void;
  dismiss: (id: string) => void;
  resolveOverwrite: (id: string) => void;
  resolveRename: (id: string, newName: string) => void;
  clearFinished: () => void;
};

export type UploadQueueContextValue = UploadQueueActions & {items: UploadItem[]};

// One action carries every held report, so a window's end is one commit.
type ProgressAction = {type: 'progress'; updates: Record<string, {loaded: number; total: number}>};

// src/features/file-browser/upload.types.ts
export const UPLOAD_PROGRESS_FLUSH_MS = 100;
export const UPLOAD_LISTING_REFRESH_MS = 2_000;
```

## API / Interface Contract

```ts
// src/features/file-browser/uploadQueueContext.ts
useUploadActions(): UploadQueueActions; // identity stable for the provider's life
useUploadItems(): UploadItem[];
useUploadQueue(): UploadQueueContextValue; // both, unchanged for existing callers

// src/test/renderCounter.tsx
type RenderTally = {commits: number; rendered: Record<string, number>; reconciled: number; renderMillis: number};
createRenderCounter(): {Probe: (props: {children: ReactNode}) => ReactNode; reset: () => void; read: () => RenderTally};
```

## File & Folder Structure

```
apps/portal/src/
├── features/file-browser/
│   ├── UploadQueueProvider.tsx        (two contexts, coalesced progress and refresh)
│   ├── uploadQueueContext.ts          (the contexts, their hooks, the reducer's progress arm)
│   ├── upload.types.ts                (the two windows)
│   ├── UploadList.tsx                 (memoised row)
│   ├── FileBrowser.tsx                (reads the actions alone)
│   ├── index.ts                       (exports the two new hooks)
│   └── uploadRenderScope.test.tsx     (the budgets)
└── test/
    ├── renderCounter.tsx
    └── renderCounter.test.tsx
```

## Implementation Phases

### Phase 1: The render counter and the baseline

- `src/test/renderCounter.tsx` and its own suite (FR-005's first three criteria).
- The uploads render-scope suite, recording the baseline at the commit before any fix.

### Phase 2: Contexts, coalesced progress, memoised row

- Split the context; `FileBrowser` reads the actions (FR-001).
- Coalesce progress in the provider and make the reducer's `progress` arm identity-preserving
  (FR-002).
- Memoise the row (FR-003).

### Phase 3: Coalesced folder refresh, budgets, close-out

- Coalesce the listing refresh per folder (FR-004).
- Turn the render-scope suite's measurements into asserted budgets and mutation-test them
  (FR-005's last criterion).
- Completion ritual: the delivery doc carries the before and after counts, each anchored to its
  commit; the signed-in pass this arc and PR #1050 both owe goes to `docs/testing/owed.md`, since
  the web tier stays off by Andrew's decision of 2026-11-27.

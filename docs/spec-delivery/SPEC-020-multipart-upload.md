# Completed Spec — SPEC-020: Upload Queue (multi-file, concurrency, cancel)

## What was completed from this spec?

Turned uploading from a single-file action into a proper **multi-file queue** layered
on top of SPEC-016's `uploadFile` (managed `lib-storage` upload). **No new S3 or IAM
capability** — purely client-side state + UI, exactly as the spec scoped it.

Delivered (all under `apps/portal/src/features/file-browser/`):

- **`upload.types.ts`** — `UploadItem`, `UploadStatus`, `UPLOAD_CONCURRENCY = 3`,
  `TERMINAL_STATUSES`.
- **`uploadQueueContext.ts`** — pure `uploadQueueReducer` + `UploadQueueContext` +
  `useUploadQueue()` hook + `keyPrefix()` helper. (Pure reducer lives in this
  non-component module so it's unit-testable and the provider file exports only its
  component — same split as `selectionContext.ts`.)
- **`UploadQueueProvider.tsx`** — the side-effecting driver: a **concurrency gate**
  (≤ 3 files in flight; the rest stay `queued`), per-item `AbortController` for
  **cancel**, `onProgress` wiring, listing **invalidation** per completion, and
  abort-all on unmount. StrictMode-safe via a launched-id guard.
- **`UploadQueuePanel.tsx`** — a **non-blocking floating panel** (bottom-right) showing
  each file's chip, name, subtext, a 6px accent progress bar, right-aligned status,
  per-file cancel/dismiss (hover action), an inline collision prompt, and a
  "Clear finished" control. Built to design-system §5's queue-card treatment.
- **`UploadDropzone.tsx`** — upgraded from single-file (`onFile` + `progress`) to
  **multi-file** (`onFiles`, `multiple` input, drop-all); progress now lives in the
  panel, not the dropzone.
- Tests: `UploadQueueProvider.test.tsx` (12 — reducer transitions, concurrency gate
  proving ≤3 in flight + next-starts-as-slot-frees, abort path, oversize rejection,
  collision→overwrite), `UploadQueuePanel.test.tsx` (7 — progress bar, cancel/dismiss,
  failure subtext, collision prompt wiring, clear-finished).

### Behavior notes / FR mapping

- **FR-001** queue + concurrency: deterministic ids (`${seq}-${name}` from a reducer
  counter — **no `Math.random`** in shared code); destination key captured at enqueue
  time so navigating mid-upload never re-targets an in-flight file.
- **FR-002** cancel: in-flight → `AbortController.abort()` → `lib-storage` aborts the
  multipart upload (no orphaned parts) → item `cancelled`; queued/collision cancel just
  drops the item (nothing was written); terminal items are dismissable.
- **FR-003** UI: non-blocking floating panel; per-file collision (SPEC-016
  warn-and-confirm) reusing `CollisionPrompt`; files over `MAX_UPLOAD_BYTES` are
  rejected on enqueue as a `failed` item with the limit message (never enter the active
  queue / never call `uploadFile`).

## What has changed?

Changes that touched code delivered by earlier specs:

- **`UploadDropzone.tsx` (SPEC-016/025)** — API changed from single-file
  `onFile(file)` + `progress` to multi-file `onFiles(files)`. The in-dropzone progress
  bar was removed (progress is now per-file in the queue panel).
- **`FileBrowser.tsx` (SPEC-016)** — `useFileUpload` is now used for **create-folder
  only**; file uploads go through the new `useUploadQueue().enqueue`. The folder-name
  collision prompt and create-folder error banner moved **inline** (they no longer
  force the upload drawer open). The upload drawer is now just the "add files" surface
  and auto-closes on enqueue so the non-blocking queue panel takes over. The
  `FileBrowser` component now wraps its content in `UploadQueueProvider` (sibling to
  `SelectionProvider`), so the queue persists across prefix navigation.
- **`FileBrowser.test.tsx`** — mocks the queue (provider passthrough + stubbed
  `useUploadQueue` + no-op `UploadQueuePanel`); the obsolete `useFileUpload.progress`
  progress-bar assertion was replaced with an enqueue-on-select assertion; dropzone
  copy expectations updated (`choose a file` → `choose files`).
- **`index.ts`** — barrel now exports `UploadQueueProvider`, `UploadQueuePanel`,
  `useUploadQueue`, `UploadQueueContextValue`, `UploadItem`, `UploadStatus`,
  `UPLOAD_CONCURRENCY`.

### Deliberate deviations (worth knowing)

- **Added a `collision` status** beyond the spec's data-model list of five. Per-file
  warn-and-confirm needs a state the concurrency gate must *not* auto-start; `collision`
  is that pause. Also added `overwrite: boolean` to `UploadItem` so a resolved
  collision re-queues correctly (Overwrite → `overwrite:true`; Rename → new leaf key).
- **Queue placement.** Design-system §5 draws the queue *inside* the upload drawer, but
  FR-003 requires it be **non-blocking** while browsing, and the drawer is a modal
  scrim. Resolved by keeping the dropzone in the drawer for *adding* files and rendering
  the queue as a **non-modal floating panel** that reuses the §5 card visuals.

### Verification

`npm run lint`, `tsc --noEmit`, and `npm run build` are clean; the full suite passes
(266 tests, incl. 19 new). Interactive verification (dropping several/large files,
cancelling in flight, watching listing refresh) requires the **authenticated, writable**
flow (Cognito + scoped credentials) — the local dev-unauth path is read-only and never
mounts the upload UI — so hands-on verification happens on the deployed app, per the
spec's Phase 2 checkpoint.

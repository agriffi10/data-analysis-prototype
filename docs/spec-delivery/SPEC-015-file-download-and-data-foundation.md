# Completed Spec - File Download + File-Operations Data Foundation

## What was completed from this spec?

The first spec of the file-operations arc: it lays the shared TanStack Query
data layer every later operation builds on, paginates listings past the 1,000-key
ceiling, and ships the first user-facing capability — downloading a file via a
short-lived presigned S3 URL (direct browser → S3, no backend).

**Phase 1 — Data foundation (FR-001/FR-002):**
- **`src/lib/queryClient.ts`** — one app-wide `QueryClient` with documented
  defaults (`staleTime` 30s, `retry` 1, `refetchOnWindowFocus` false) plus an
  exported `invalidateListing(client, bucket, prefix)` for later mutation specs.
- **`src/features/file-browser/fileBrowserKeys.ts`** — `fileBrowserKeys.list(bucket, prefix)`
  as the single source of truth for listing query keys.
- **`main.tsx`** — `<QueryClientProvider>` placed **inside `AuthProvider`,
  outside `BrowserRouter`** per FR-001.
- **`fileBrowser.service.ts`** — `listFiles` now takes a `continuationToken`,
  sends `MaxKeys: 1000`, and returns a `FileListPage` (`isTruncated` +
  `nextContinuationToken`). New `FileListPage` type in `s3.types.ts`.
- **`useFileBrowser.ts`** — reimplemented on `useInfiniteQuery`: merges
  folders/files across loaded pages with the same global sort as SPEC-002,
  preserves the SPEC-014 marker filter, exposes `hasMore`/`loadMore`/`isLoadingMore`,
  and turns `refresh()` into a query invalidation.
- **`FileBrowser.tsx`** — a **"Load more"** control shown only when `hasMore`,
  disabled mid-fetch.

**Phase 2 — Presigned download (FR-003):**
- **`fileBrowser.types.ts`** (new) — `DownloadUrl` (`url` + `expiresAt`).
- **`fileBrowser.service.ts`** — `getDownloadUrl({ bucket, key, fileName?, expiresInSeconds? })`
  signs a `GetObjectCommand` via `@aws-sdk/s3-request-presigner` `getSignedUrl`;
  default expiry 900s **capped to the remaining credential TTL** (a presigned URL
  can't outlive its creds); `ResponseContentDisposition: attachment; filename="…"`
  forces a save with the real name; `fileName` defaults to the key's last segment;
  one transparent `getS3Client(true)` retry on no credentials before surfacing a
  `ServiceResult` error (never throws).
- **`FileBrowser.tsx`** — per-file **Download** button (folders / the hidden
  marker expose none), per-row busy state, dismissible inline error on failure;
  download is triggered by a programmatic anchor click so it survives the async
  signing step.

## What has changed?

- **New dependencies**: `@tanstack/react-query@^5.101.0`, `@aws-sdk/s3-request-presigner@^3.1068.0`
  (both already noted in the CLAUDE.md tech-stack table).
- **Listing contract**: `listFiles` signature/return changed (continuation token
  + `FileListPage`); `useFileBrowser` now returns pagination fields. Existing
  `FileBrowser`/service tests updated accordingly.
- **Provider tree**: `main.tsx` gains `QueryClientProvider` between `AuthProvider`
  and `BrowserRouter`.
- **No IaC/env change**: `s3:GetObject` from SPEC-013 already authorizes presigned
  downloads; no new environment variables.

## Verification

- **Unit/build**: 87 tests pass; `tsc`/`lint`/`build` clean. New coverage:
  `invalidateListing` + key factory; pagination/continuation-token service tests;
  the rewritten infinite-query hook (incl. a two-page merge + global re-sort);
  "Load more" component states; and download URL construction (params +
  disposition), filename defaulting, expiry cap, and the no-credentials
  retry/error path.
- **Live checkpoint — deferred (by decision).** The signed-in download checkpoint
  (click Download saves the file with its real name; URL presigned/expiring;
  signed-out surfaces the no-credentials error) and the >1,000-object "Load more"
  check will be exercised together with the SPEC-016 upload flow (so there's real
  user-written data to download). Code is complete and unit-verified; the spec is
  marked Completed on that basis with live verification tracked into SPEC-016.

### Follow-ups / notes

- The bundle now exceeds Vite's 500 KB warning threshold (~566 KB / ~182 KB
  gzip) from the added SDK/Query code — informational only; revisit with code
  splitting if it grows materially.
- `invalidateListing` is the contract later mutation specs (SPEC-016/018/019)
  call after a write to refresh the affected prefix.

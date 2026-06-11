# Spec: File Download + File-Operations Data Foundation

**ID:** SPEC-015
**Status:** Draft
**Last Updated:** 2026-06-11
**Depends On:** SPEC-011 (`getS3Client()`), SPEC-013 (browser on authenticated user-space bucket), SPEC-014 (marker filtering)

## Overview

This is the first spec of the file-operations arc (SPEC-015→020) that turns the
read-only file browser into a filesystem-like experience. It does two things:
(1) it lays the shared **data-layer foundation** every later file operation
builds on — server-state management with TanStack Query (caching, refetch, and
invalidation after mutations) and pagination for prefixes with more than 1,000
objects — and (2) it ships the first user-facing capability: **downloading a
file** via a short-lived presigned S3 URL generated in the browser. There is no
backend, so downloads are direct browser → S3.

## Scope

### In Scope

- Add `@tanstack/react-query` and wire a `QueryClientProvider` (inside `AuthProvider`, outside the router)
- Add `@aws-sdk/s3-request-presigner`
- Migrate the existing object listing from the bespoke `useFileBrowser` effect to a TanStack Query hook, with a shared query-key convention and an exported invalidation helper for later mutation specs
- Pagination of `ListObjectsV2` (>1,000 keys) via `useInfiniteQuery` and an explicit **"Load more"** control
- Download a single file via a presigned `GetObject` URL (default 15-minute expiry, never exceeding credential TTL), forcing a save dialog with `ResponseContentDisposition`
- Keep the SPEC-014 `DO_NOT_DELETE.txt` root marker hidden and non-downloadable in the UI

### Out of Scope

- Upload, create-folder (SPEC-016); metadata panel (SPEC-017); delete (SPEC-018); move/rename (SPEC-019); multipart/large-file upload (SPEC-020)
- Folder (multi-object) download or zip-on-the-fly — there is no backend to assemble archives
- Infinite auto-scroll (a manual "Load more" button is used for deterministic behavior)
- Any IAM change — `s3:GetObject` from SPEC-013 already covers presigned downloads

---

## Functional Requirements

### FR-001: TanStack Query Foundation

#### Description:

Server state (S3 reads/writes) is managed by TanStack Query so later specs get caching, refetch, and invalidation for free.

#### Acceptance Criteria:

- [ ] `@tanstack/react-query` added to `apps/portal/package.json` and recorded in the CLAUDE.md tech-stack table
- [ ] A single `QueryClient` is created in `src/lib/queryClient.ts`; `main.tsx` wraps the app in `<QueryClientProvider>` placed **inside** `<AuthProvider>` and **outside** `<BrowserRouter>`
- [ ] A query-key helper `fileBrowserKeys` (e.g. `fileBrowserKeys.list(bucket, prefix)`) is the single source of truth for listing keys
- [ ] An exported `invalidateListing(queryClient, bucket, prefix)` helper exists for later mutation specs to call; it is unit-tested
- [ ] Default query options set: `staleTime` 30s, `retry` 1, `refetchOnWindowFocus` false (documented in `queryClient.ts`)

### FR-002: Listing Migration + Pagination

#### Description:

The current listing moves onto TanStack Query and gains pagination so prefixes with >1,000 objects are fully browsable.

#### Acceptance Criteria:

- [ ] `useFileBrowser` is reimplemented on `useInfiniteQuery`; each page requests `ListObjectsV2` with `MaxKeys` 1000 and threads `ContinuationToken`/`NextContinuationToken`
- [ ] Folders (`CommonPrefixes`) and files (`Contents`) are merged across loaded pages; sorting and the `name`/`prefix` derivation match the current SPEC-002 behavior exactly
- [ ] A **"Load more"** control is shown only when `IsTruncated` is true; clicking it loads the next page; it is hidden when fully loaded
- [ ] The SPEC-014 root marker (`{root}/DO_NOT_DELETE.txt`) stays filtered from the merged listing (no regression)
- [ ] `refresh()` is replaced by a query invalidation; existing FileBrowser tests are updated and pass
- [ ] Loading, empty (no error), and error states render as before; a brand-new user's empty prefix shows the empty state

### FR-003: Presigned Download

#### Description:

A user downloads one of their files; the app generates a short-lived presigned URL and the browser saves the file.

#### Acceptance Criteria:

- [ ] `getDownloadUrl({ bucket, key, expiresInSeconds?, fileName? })` uses `getSignedUrl` with a `GetObjectCommand` and the client from `getS3Client()`; returns `ServiceResult<{ url: string; expiresAt: string }>`
- [ ] Default expiry is 900 seconds (15 min); the function caps the requested expiry to the remaining credential lifetime and documents this
- [ ] `ResponseContentDisposition` is set to `attachment; filename="<name>"` so the browser saves (not navigates to) the file with its real name
- [ ] Each file row exposes a "Download" action; invoking it opens the presigned URL to trigger the save; folders and the hidden marker expose no download action
- [ ] On `getS3Client()` returning no credentials (signed out / expired), the action surfaces a `ServiceResult` error rather than throwing; one transparent retry with `getS3Client(true)` is attempted first
- [ ] Unit tests cover URL construction (params + disposition), the expiry cap, and the no-credentials error path

---

## Data Model

```ts
// src/features/file-browser/fileBrowser.types.ts (additions)

export type DownloadUrl = {
  url: string;        // presigned GetObject URL
  expiresAt: string;  // ISO timestamp the URL stops working
};
```

---

## API / Interface Contract

```ts
// src/features/file-browser/fileBrowser.service.ts (additions)
getDownloadUrl(params: {
  bucket: string;
  key: string;
  fileName?: string;          // defaults to the last path segment
  expiresInSeconds?: number;  // default 900, capped to credential TTL
}): Promise<ServiceResult<DownloadUrl>>;

// src/features/file-browser/fileBrowserKeys.ts
export const fileBrowserKeys = {
  all: ['file-browser'] as const,
  list: (bucket: string, prefix: string) =>
    [...fileBrowserKeys.all, 'list', bucket, prefix] as const,
};
```

## Environment Variables

None new.

## File & Folder Structure

```
apps/portal/src/
├── lib/
│   ├── queryClient.ts            ← NEW: QueryClient + defaults
│   └── queryClient.test.ts       ← NEW: invalidateListing helper test
├── main.tsx                      ← + QueryClientProvider (inside AuthProvider)
└── features/file-browser/
    ├── fileBrowserKeys.ts        ← NEW: query-key factory
    ├── fileBrowser.service.ts    ← + getDownloadUrl
    ├── fileBrowser.service.test.ts
    ├── useFileBrowser.ts         ← reimplemented on useInfiniteQuery
    ├── useFileBrowser.test.ts    ← NEW/updated
    ├── FileBrowser.tsx           ← + "Load more", + per-file Download action
    └── FileBrowser.test.tsx
```

## Implementation Phases

### Phase 1: Data foundation (TanStack Query + pagination)

- Add the dependency, `queryClient.ts`, provider wiring, key factory, invalidation helper (FR-001)
- Reimplement `useFileBrowser` on `useInfiniteQuery` with "Load more" and marker filtering (FR-002)

#### Checkpoint

`npm run test` and `npm run lint` pass. In `npm run dev`, the file browser lists as before; a prefix with >1,000 objects shows a working "Load more"; the root marker is not shown.

### Phase 2: Presigned download

- Add `@aws-sdk/s3-request-presigner`, implement `getDownloadUrl`, and the per-file Download action (FR-003)

#### Checkpoint

Signed in against the user-space bucket, clicking Download on a file saves it with its correct filename; the URL is presigned and expires; signed out, the action surfaces the no-credentials error. Unit tests pass.

## Open Questions

None — all resolved before drafting:
- Download mechanism = **presigned URL** (`@aws-sdk/s3-request-presigner`); filename forced via `ResponseContentDisposition`; default expiry 15 min, capped to credential TTL.
- Server state = **TanStack Query**; UI state (later specs) = Context + reducer.
- Pagination = `useInfiniteQuery` with a manual **"Load more"** (page size 1,000).

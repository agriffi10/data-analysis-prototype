---
type: Spec
id: SPEC-037
title: "File Browser Pagination — 25 Items per Page"
description: "Changes the file browser's listing page size to 25 items so large folders load incrementally through the existing Load more button instead of fetching up to 1,000 keys at once."
spec_status: Completed
depends_on: [SPEC-015]
---

**Dependency notes:** SPEC-015 (TanStack `useInfiniteQuery` listing foundation + "Load more")
## Overview

The file browser already paginates with TanStack Query's `useInfiniteQuery` and a "Load more" control (SPEC-015), but each page requests up to 1,000 keys from S3 — so for any realistic folder the first request pulls the entire listing and "Load more" never appears. This spec changes the listing **page size to 25 items**, so the browser loads 25 entries at a time from S3 and the user pulls the rest on demand with the existing "Load more" button. The goal is to keep the amount fetched and rendered small and predictable rather than pulling a whole large folder at once.

This is a focused refinement of SPEC-015's data layer — no new feature surface, no new dependency, no IAM change.

## Scope

### In Scope

- Set the listing page size to **25** (a named constant) for `ListObjectsV2` `MaxKeys`, replacing SPEC-015's 1,000
- Keep the existing `useInfiniteQuery` + **"Load more"** control: each click fetches the next 25-item S3 page (append) and is shown only while the listing is truncated
- Preserve all SPEC-015 behavior: folder/file (`CommonPrefixes`/`Contents`) merge + sort across loaded pages, `DO_NOT_DELETE.txt` marker filtering, loading/empty/error states
- Update the affected tests

### Out of Scope

- Changing the *query-results* page size (SPEC-038 — separate, 20 rows)
- Infinite auto-scroll (the deterministic manual "Load more" stays)
- Virtualized rendering of huge lists (not needed — page size is now small)
- Any change to selection, upload, delete, move, or metadata behavior
- Any S3 IAM / CORS change (`ListBucket` from SPEC-013 already covers paginated listing)

---

## Functional Requirements

### FR-001: 25-Item Page Size

#### Description:

The listing fetches 25 items per S3 page instead of 1,000.

#### Acceptance Criteria:

- [ ] A named constant (e.g. `LISTING_PAGE_SIZE = 25` in `fileBrowser.constants.ts`) is the single source of truth; `useFileBrowser`'s `useInfiniteQuery` passes it as `MaxKeys` on every `ListObjectsV2` request (replacing the literal 1,000 from SPEC-015 FR-002)
- [ ] `MaxKeys` caps the combined response (folders via `CommonPrefixes` + files via `Contents`); the `ContinuationToken`/`NextContinuationToken` threading from SPEC-015 is unchanged
- [ ] A comment notes that 25 is a UI/UX page size, not an S3 limit, and is intentionally small so each request and render stays bounded

### FR-002: "Load more" Behavior

#### Acceptance Criteria:

- [ ] The existing "Load more" control fetches the next 25-item page and **appends** it to the rendered list (no replacement); it is shown only when `IsTruncated` is true and hidden once the listing is fully loaded
- [ ] Folders and files are merged and sorted across all loaded pages exactly as in SPEC-015 (folders-first, then alphabetical) — a comment acknowledges that because S3 returns keys in lexicographic order across pages, a folder can surface on a later page and the folders-first sort will re-order the already-loaded items when it does (inherent to client-side sorting over paginated S3 listings; acceptable for v1)
- [ ] The `DO_NOT_DELETE.txt` marker stays filtered from the merged listing (no regression); note that a filtered marker can make a rendered page show fewer than 25 visible rows — this is expected and not an error
- [ ] Loading (first page), empty (no error), and error states render as in SPEC-015; a brand-new user's empty prefix shows the empty state

### FR-003: Tests

#### Acceptance Criteria:

- [ ] `useFileBrowser` tests updated/added to assert `MaxKeys === LISTING_PAGE_SIZE` (25) and that "Load more" fetches and appends the next page, hiding when not truncated
- [ ] Existing `FileBrowser` tests updated for the new page size; `npm run test` + `npm run lint` pass

---

## Data Model

No new types. `LISTING_PAGE_SIZE` constant added to `fileBrowser.constants.ts`.

## File & Folder Structure

```
apps/portal/src/features/file-browser/
├── fileBrowser.constants.ts     ← + LISTING_PAGE_SIZE = 25
├── useFileBrowser.ts            ← MaxKeys = LISTING_PAGE_SIZE (was 1000)
└── useFileBrowser.test.ts       ← updated assertions
```

## Implementation Phases

### Phase 1: Page size + tests (single phase — small spec)

- FR-001, FR-002, FR-003

#### Checkpoint

`npm run dev`: a folder with >25 entries shows exactly 25 rows initially (minus any filtered marker) and a "Load more" button; clicking it appends the next 25; the button disappears when the folder is fully loaded; folders still sort ahead of files; a folder with ≤25 entries shows no "Load more". `npm run test` + `npm run lint` pass.

## Open Questions

- [x] **Resolved (2026-06-17):** page size = **25**, applied as `MaxKeys`; "Load more" appends (the SPEC-015 control), not a replace-style pager — matches the file-browser interaction the user specified.
- [ ] **Sort vs. pagination wrinkle.** Folders-first client-side sorting over paginated S3 listings means a folder appearing on a later page re-orders loaded rows. Acceptable for v1; if it proves jarring, a future option is to list folders (delimiter, prefixes-only) fully before files. Note only — no action this spec.

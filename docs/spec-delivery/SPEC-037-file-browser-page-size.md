# Completed Spec — SPEC-037: File Browser Pagination — 25 Items per Page

## What was completed?

- The file browser now fetches **25 entries per page** from S3 instead of pulling up to 1,000 at
  once, so the SPEC-015 "Load more" control actually engages for realistic folders.
- `LISTING_PAGE_SIZE = 25` added to `fileBrowser.constants.ts` as the single source of truth; the
  listing path (`listWithClient` in `fileBrowser.service.ts`) passes it as `ListObjectsV2` `MaxKeys`.
- No new feature surface, dependency, or IAM change — a focused refinement of SPEC-015's data layer.

## What changed from earlier specs?

- SPEC-015's listing `MaxKeys` dropped from 1,000 → `LISTING_PAGE_SIZE` (25). The SPEC-015 merge/sort,
  marker filtering, and "Load more" (`useInfiniteQuery`) behavior are unchanged.
- The recursive collect-all-keys pass used by delete/move (SPEC-018/019) was **not** touched — its
  page size is now the explicitly-named `BULK_KEY_PAGE_SIZE = 1000` (the S3 hard cap), split out from
  the old shared `PAGE_SIZE` so the two page sizes can't be conflated.

## Verification

`npm run lint`, `npm run test` (338 pass — service test asserts `MaxKeys === LISTING_PAGE_SIZE`;
`useFileBrowser` test already covers load-more append + hide-when-not-truncated), and `npm run build`
all pass locally. Live browser check (a >25-item folder showing 25 rows + "Load more") deferred to
deploy — it needs a populated authenticated bucket; the page size and append are unit-covered.

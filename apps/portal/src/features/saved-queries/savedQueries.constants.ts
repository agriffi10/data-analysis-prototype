// Named constants for the `.sql` store (moved out of `query.constants.ts`).

/**
 * Saved-queries rows per DISPLAY page. Unrelated to LISTING_PAGE_SIZE (25): an S3
 * listing page of 25 keys can yield 25 rows, three, or none at all, because the store
 * offers only the top-level `.sql` files of an otherwise ordinary folder (
 * FR-002). The pager counts filtered rows, never keys.
 */
export const SAVED_QUERIES_PAGE_SIZE = 10;

/**
 * sessionStorage key prefix for the per-user saved-queries space (full key: prefix +
 * username). The `query.` segment is a live storage key, not a description of where the
 * module lives — the module moved and the value was deliberately left alone.
 */
export const QUERY_SAVED_QUERY_SPACE_STORAGE_PREFIX = 's3portal.query.savedQuerySpace.';

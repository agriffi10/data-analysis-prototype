// Prefix-marker constants. The marker is a zero-content-significance object
// written at the root of each user's prefix so the prefix physically exists in
// S3 (S3 has no real folders — a prefix exists only while an object lives under
// it). It is hidden from the listing and protected from deletion at the service
// layer.

export const PREFIX_MARKER_FILENAME = 'DO_NOT_DELETE.txt';

export const PREFIX_MARKER_BODY =
  'This file keeps your personal storage space active. Deleting it may cause ' +
  'your folder to disappear from administrative tooling. It is hidden from ' +
  'your file browser and can be ignored.';

/**
 * Single source of truth for the marker's S3 key. The marker always lives at
 * the root of the user's own prefix: `{username}/DO_NOT_DELETE.txt`.
 */
export function prefixMarkerKey(username: string): string {
  return `${username}/${PREFIX_MARKER_FILENAME}`;
}

/**
 * Is this key a prefix marker, wherever it sits? Matched by BASENAME, not by an
 * exact key: both bucket policies deny `s3:DeleteObject` on a wildcard resource
 * ending in the marker's own basename, and `*` in an S3 resource ARN matches `/`,
 * so an object with that name at ANY depth in either bucket is already undeletable. Showing one offers an action this
 * application's own IAM refuses (SPEC-150 FR-007), so the listing hides them all.
 *
 * Exact and case-sensitive, as S3 keys are: `DO_NOT_DELETE.txt.bak` and
 * `do_not_delete.txt` are ordinary files.
 */
export function isMarkerName(key: string): boolean {
  return key.slice(key.lastIndexOf('/') + 1) === PREFIX_MARKER_FILENAME;
}

// SPEC-173: the saved-queries folder at a space root. Its own name and its own
// marker text — PREFIX_MARKER_BODY says the file keeps "your personal storage
// space" active, which is wrong in a shared space and wrong about this folder.
export const SAVED_QUERIES_FOLDER = 'saved_queries';

export const SAVED_QUERIES_MARKER_BODY =
  'This file keeps the saved queries folder in place. Deleting it may make the ' +
  'folder disappear until a query is saved into it again. It is hidden from ' +
  'your file browser and can be ignored.';

// Single source of truth for the listing page size: entries per ListObjectsV2
// page (MaxKeys); the user pulls the rest via "Load more". 25 is a UI/UX page
// size — intentionally small so each request and render stays bounded — NOT an
// S3 limit (S3's hard cap is 1000).
export const LISTING_PAGE_SIZE = 25;

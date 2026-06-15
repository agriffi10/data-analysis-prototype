// Prefix-marker constants (SPEC-014). The marker is a zero-content-significance
// object written at the root of each user's prefix so the prefix physically
// exists in S3 (S3 has no real folders — a prefix exists only while an object
// lives under it). It is hidden from the listing (FR-002) and protected from
// deletion at the service layer (FR-003).

export const PREFIX_MARKER_FILENAME = 'DO_NOT_DELETE.txt';

export const PREFIX_MARKER_BODY =
  'This file keeps your personal storage space active. Deleting it may cause ' +
  'your folder to disappear from administrative tooling. It is hidden from ' +
  'your file browser and can be ignored.';

// Single source of truth for the marker's S3 key. The marker always lives at the
// root of the user's own prefix: `{username}/DO_NOT_DELETE.txt`.
export function prefixMarkerKey(username: string): string {
  return `${username}/${PREFIX_MARKER_FILENAME}`;
}

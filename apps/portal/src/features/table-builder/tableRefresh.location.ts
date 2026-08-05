/**
 * Split a Glue table's `s3://{bucket}/{prefix}` location into the bucket and
 * folder key a refresh request's `space` needs, or `null` when it isn't an S3 URL
 * with both parts.
 *
 * This is the Query workspace's ONLY route to a table's folder: `Connection`
 * carries `database`/`kind` and nothing spatial, and the file-browser's own
 * prefix helper returns null for every shared-space table. The prefix is
 * normalised to a single trailing slash because that is what the control plane
 * authorizes against (`validate_authorize._normalize_prefix`); the server then
 * re-reads the location from the catalog anyway (SPEC-143 FR-004), so a stale
 * rail cache can never widen access.
 *
 * @example
 * parseTableLocation('s3://dat-prod-user-space/alice/sales'); // {bucket: 'dat-prod-user-space', prefix: 'alice/sales/'}
 */
export function parseTableLocation(location: string | undefined): {bucket: string; prefix: string} | null {
  const match = /^s3:\/\/([^/]+)\/(.+)$/.exec((location ?? '').trim());
  if (!match) return null;
  const [, bucket, key] = match;
  return {bucket, prefix: key.endsWith('/') ? key : `${key}/`};
}

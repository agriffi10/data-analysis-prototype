/**
 * Parse an `s3://bucket/key` URL into its parts; `null` when it isn't one.
 *
 * The single parser for every S3 URL the app reads back out of AWS — a query's Athena
 * `outputLocation`, a Glue table's `LOCATION`, the workspace's table actions. Each of
 * those had written the same regex, and one of the three then diverged on whitespace.
 *
 * Deliberately strict: both parts must be non-empty, so `s3://bucket` and `s3://` are
 * `null` rather than a bucket with an empty key. Input is trimmed — a `LOCATION` read
 * from the catalog can carry surrounding whitespace.
 *
 * @example
 * parseS3Url('s3://user-space/alice/athenaresults/q-1.csv');
 * // {bucket: 'user-space', key: 'alice/athenaresults/q-1.csv'}
 */
export function parseS3Url(url: string | undefined): {bucket: string; key: string} | null {
  const match = /^s3:\/\/([^/]+)\/(.+)$/.exec((url ?? '').trim());
  if (!match) return null;
  return {bucket: match[1], key: match[2]};
}

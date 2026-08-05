/**
 * Whether an AWS SDK v3 error means "the S3 object doesn't exist".
 *
 * Covers both surfacings: `GetObject` on a missing key throws `NoSuchKey`, `HeadObject`
 * throws `NotFound`, and either can present as a 404 in `$metadata`. Use to treat a
 * missing settings/cache/history object as an empty default rather than an error.
 *
 * @param err - The caught value (typed `unknown`; narrowed internally).
 *
 * @example
 * try {
 *   const {Body} = await s3.send(new GetObjectCommand({Bucket, Key}));
 *   return {success: true, data: parse(Body)};
 * } catch (err) {
 *   if (isNotFound(err)) return {success: true, data: EMPTY};
 *   return toServiceError(err, 'Failed to load');
 * }
 */
export function isNotFound(err: unknown): boolean {
  // Guarded for the same reason as `toServiceError`: this is called on a caught
  // value, and `throw null` would make the predicate throw instead of answering.
  if (typeof err !== 'object' || err === null) return false;
  const e = err as {name?: string; $metadata?: {httpStatusCode?: number}};
  return e.name === 'NoSuchKey' || e.name === 'NotFound' || e.$metadata?.httpStatusCode === 404;
}

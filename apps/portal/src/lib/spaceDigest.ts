/**
 * The FIFO group id every control plane keyed by a SPACE derives, in one place.
 *
 * Two planes hash `{bucket}/{spaceRoot}` to order their queue per space, and the file-operations
 * plane hashes the identical string again server-side to key its per-space lock. That makes this
 * one string a value three call sites must agree on — and disagreement is **silent**: nothing at
 * runtime reports that delivery is ordered on one key while the lock is held under another. The
 * operations simply stop being serialized.
 *
 * A HASH, NEVER THE RAW PATH. SQS caps `MessageGroupId` at 128 characters where an S3 key reaches
 * 1024, so the raw form is a length failure that appears only for the users with the deepest
 * prefixes.
 *
 * **Ordered delivery is not serialized execution.** The Pipe starts each machine and returns, so
 * two requests against one space can still run at once. This buys ordering and throughput
 * isolation; the serialization is the lock inside the machine that needs it.
 */

/**
 * The canonical string a space hashes to, normalised the way the plane normalises it.
 *
 * The trailing slash is part of what is hashed, and the name is trimmed and stripped of any
 * trailing slashes first — because the server-side twin does exactly that before hashing, and a
 * name arriving as `alice/` would otherwise produce `…/alice//` here against `…/alice/` there.
 *
 * @param bucket - The bucket the space lives in.
 * @param name - The space's name.
 * @returns The string to hash.
 * @throws If either part is empty. Hashing an empty bucket would put every space behind one group
 *   id — and the server-side twin raises for the same reason, so failing here keeps the two ends
 *   agreeing about which inputs are usable rather than silently diverging on one.
 */
function canonicalSpace(bucket: string, name: string): string {
  const trimmed = name.trim().replace(/\/+$/, '');
  if (!bucket || !trimmed) {
    throw new Error('a space digest needs a bucket and a name');
  }
  return `${bucket}/${trimmed}/`;
}

/**
 * The SHA-256 hex digest identifying one space, for use as a FIFO `MessageGroupId`.
 *
 * @param bucket - The bucket the space lives in.
 * @param name - The space's name.
 * @returns The 64-character lowercase hex digest.
 */
export async function spaceDigest(bucket: string, name: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canonicalSpace(bucket, name)));
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

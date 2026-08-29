import {sharedSpaceBucket, userSpaceBucket} from './userSpace';
import type {SpaceRef} from '../types/apiContract.generated';

/**
 * Turns a `(bucket, key)` pair into the space reference the API's routes take.
 *
 * Every ported service still names a bucket in its signature — that is what lets nineteen call
 * sites and seven document consumers stay untouched — but the API resolves a space from the
 * caller's verified claims and never from a bucket name. This is the one adapter between the two,
 * and it is deliberately dumb: the space NAME it derives is a hint the server re-checks, not an
 * assertion it trusts. A wrong name here is a 403, never someone else's data.
 *
 * The name is the key's first segment, which is what a space root is in both buckets: a personal
 * space is `{username}/` and a shared one is `{spaceName}/`.
 *
 * @param bucket - The bucket the caller named.
 * @param key - The object key, whose first segment is the space root.
 * @returns The space reference.
 * @throws Never. An unrecognised bucket resolves to `personal`, which the server refuses unless
 *   the name happens to be the caller's own — the safe direction, and the one that produces a
 *   refusal rather than a silent read of the wrong bucket.
 */
export function spaceFor(bucket: string, key: string): SpaceRef {
  const name = key.split('/')[0] ?? '';
  return {kind: bucket === sharedSpaceBucket() ? 'shared' : 'personal', name};
}

/**
 * The space for a bucket and a prefix that may be empty.
 *
 * A listing prefix can be `''` (the space root), which carries no first segment — so the space
 * name comes from the caller-supplied root instead. Separate from `spaceFor` because conflating a
 * prefix with a key is exactly the mistake the server's own two containment rules exist to keep
 * apart.
 *
 * @param bucket - The bucket the caller named.
 * @param rootPrefix - The space root, e.g. `alice/`.
 * @returns The space reference.
 */
export function spaceForRoot(bucket: string, rootPrefix: string): SpaceRef {
  return spaceFor(bucket, rootPrefix);
}

/**
 * Whether a bucket is one this app knows how to address as a space.
 *
 * @param bucket - The bucket name.
 * @returns True when it is the user-space or shared-space bucket.
 */
export function isAddressableBucket(bucket: string): boolean {
  return bucket === userSpaceBucket() || bucket === sharedSpaceBucket();
}

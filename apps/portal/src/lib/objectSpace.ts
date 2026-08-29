import {sharedSpaceBucket} from './userSpace';
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
 * @throws Never, and every way of getting it wrong FAILS CLOSED. An unrecognised bucket resolves to
 *   `personal`, and an empty key to the empty name — both of which the server refuses unless the
 *   name happens to be the caller's own. The safe direction: a refusal rather than a silent read of
 *   the wrong bucket.
 */
export function spaceFor(bucket: string, key: string): SpaceRef {
  const name = key.split('/')[0] ?? '';
  return {kind: bucket === sharedSpaceBucket() ? 'shared' : 'personal', name};
}

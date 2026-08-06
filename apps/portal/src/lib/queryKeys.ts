/**
 * The placeholder segment for a query key whose identifier isn't known yet.
 *
 * Every hook that keys off a username or an execution id is `enabled: false` until it
 * has one, but a `queryKey` must still be built on that render — this is the value it
 * is built with. Shared so the eight call sites cannot drift into two spellings and
 * cache under two different keys.
 *
 * IT LIVES ALONE, deliberately. Five file-browser test files replace `lib/queryClient`
 * wholesale with a factory mock exporting only `invalidateListing`; a constant sitting
 * in that module would read as `undefined` in any suite whose tree later reaches one of
 * these hooks, producing a key of `['saved-queries', undefined]` that nothing throws on
 * and no assertion catches.
 */
export const NO_KEY = '__none__';

/**
 * The placeholder segment for a query key whose identifier isn't known yet.
 *
 * Every hook that keys off a username or an execution id is `enabled: false` until it
 * has one, but a `queryKey` must still be built on that render — this is the value it
 * is built with. Shared so the eight call sites cannot drift into two spellings and
 * cache under two different keys.
 *
 * It used to live alone because `lib/queryClient` was module-mocked wholesale by
 * file-browser suites, and a constant sitting there would have read as `undefined` in any
 * tree that later reached one of these hooks — a key of `['saved-queries', undefined]`
 * that nothing throws on and no assertion catches. **That hazard is gone (2026-08-09):**
 * `invalidateListing` moved into `features/file-browser/`, the mocks moved with it, and
 * `AppRoot.tsx` is now the only importer of `lib/queryClient`. The original note also
 * overstated the count — two suites mocked it, not five.
 *
 * The hazard shape is still worth knowing before putting a constant in a module that
 * anything mocks wholesale; it just no longer applies to this pair.
 */
export const NO_KEY = '__none__';

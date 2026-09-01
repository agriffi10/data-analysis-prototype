/*
 * Resolves the stored theme and stamps it on <html> BEFORE the first paint, so the page never
 * flashes light on its way to dark.
 *
 * An external file, not an inline script: the CSP is `script-src 'self'` with no nonce and no
 * hash, so an inline initialiser would run in dev and be blocked in production — the worst
 * shape of failure available.
 *
 * It must throw on nothing. It is a blocking script in <head>, and an exception here would
 * stop the module script that follows from ever loading.
 *
 * The vocabulary and the storage key are duplicated from `src/lib/useTheme.ts`, because this
 * file cannot import. `useTheme.test.ts` reads this file and asserts the two agree.
 */
(function () {
  try {
    var stored = null;
    try {
      stored = window.localStorage.getItem('portal-theme');
    } catch (e) {
      stored = null;
    }
    var preference = stored === 'light' || stored === 'dark' ? stored : 'system';
    var effective = preference;
    if (preference === 'system') {
      var query = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)');
      effective = query && query.matches ? 'dark' : 'light';
    }
    document.documentElement.setAttribute('data-theme', effective);
    document.documentElement.style.colorScheme = effective;
  } catch (e) {
    /* A page painted in the light theme beats a page that never boots. */
  }
})();

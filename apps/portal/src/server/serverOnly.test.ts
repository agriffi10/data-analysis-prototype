import {describe, expect, it} from 'vitest';

/**
 * Every server module begins with `import 'server-only'`, which makes `next build` fail when a client
 * module imports it. The lint fence keeps browser layers from importing `src/server/`; this is what
 * catches a server module reached some other way, before its code or its AWS client ships to the
 * browser.
 */
const SOURCES = import.meta.glob(['./**/*.ts', '!./**/*.test.ts'], {
  query: '?raw',
  import: 'default',
  eager: true
}) as Record<string, string>;

describe('the server modules', () => {
  it('each begin with server-only', () => {
    const paths = Object.keys(SOURCES);
    expect(paths.length).toBeGreaterThan(10);
    expect(paths.filter((path) => !SOURCES[path].startsWith("import 'server-only';"))).toEqual([]);
  });
});

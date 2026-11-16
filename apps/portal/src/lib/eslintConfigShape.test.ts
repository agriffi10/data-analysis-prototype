import {describe, expect, it} from 'vitest';
import eslintConfig from '../../eslint.config.js';

/**
 * The `@aws-sdk/*` ban is one rule declared four times, and that is the hazard.
 *
 * ESLint flat config REPLACES a rule's value at the last entry matching a file rather than
 * merging it, so the layering clause, the exemption clause and the sibling-feature clause
 * each override the `src/**` clause for the files they match. Written once, the ban is
 * silently off for `src/lib/**`, `src/components/**`, every test in those trees, and the
 * four feature directories under the sibling rule — while the config reads as if it holds.
 *
 * So this enumerates rather than sampling: every entry that governs `src/` and declares
 * `no-restricted-imports` must carry the group. An entry added later without it reddens
 * here, which a review of that entry alone would not.
 */
/**
 * Whether an entry may govern a file under `src/`. A glob need not START with `src/` to govern it:
 * the base entry matches every TypeScript file, and an entry with no `files` at all governs everything. So
 * an entry is out of scope only if EVERY glob it names is demonstrably not under `src/`.
 */
function governsSrc(entry: (typeof eslintConfig)[number]): boolean {
  const globs = entry.files;
  if (globs === undefined || globs.length === 0) return true;
  return globs.some((glob) => glob.startsWith('src/') || !glob.startsWith('.'));
}

/** Every entry that declares `no-restricted-imports` and governs a file under `src/`, in config order. */
function governingEntries() {
  return eslintConfig.filter((entry) => entry.rules?.['no-restricted-imports'] !== undefined && governsSrc(entry));
}

/** The groups an entry's `no-restricted-imports` names, flattened; null for a shape this test cannot read. */
function groupsOf(entry: (typeof eslintConfig)[number]): string[] | null {
  const value = entry.rules?.['no-restricted-imports'];
  if (!Array.isArray(value)) return null;
  const options = value[1] as {patterns?: {group: string[]}[]} | undefined;
  return options?.patterns?.flatMap((pattern) => pattern.group) ?? null;
}

/** A flat-config glob as a regular expression: `**`, `*` and `{a,b}`, the forms this config uses. */
function globMatches(glob: string, file: string): boolean {
  let pattern = '';
  for (let index = 0; index < glob.length; index += 1) {
    const char = glob[index];
    if (char === '*' && glob[index + 1] === '*') {
      pattern += glob[index + 2] === '/' ? '(?:.*/)?' : '.*';
      index += glob[index + 2] === '/' ? 2 : 1;
    } else if (char === '*') pattern += '[^/]*';
    else if (char === '{') pattern += '(?:';
    else if (char === '}') pattern += ')';
    else if (char === ',') pattern += '|';
    else pattern += char.replace(/[.+?^$()|[\]\\]/g, '\\$&');
  }
  return new RegExp(`^${pattern}$`).test(file);
}

describe('the @aws-sdk ban survives every no-restricted-imports clause', () => {
  // Filtering on the `src/` prefix let an entry with no `files` declare the rule without the
  // group while this test passed and an `@aws-sdk` import in `features/` linted clean
  // (reproduced), which is why `governsSrc` inverts the question.
  const governing = governingEntries();

  it('is declared by every clause that governs a file under src/', () => {
    // Guard-the-guard: a filter that found nothing would agree with a config carrying no
    // ban at all. Four is what the file declares, and a fifth clause must opt in here.
    expect(governing.length).toBeGreaterThanOrEqual(4);

    const without = governing
      .filter((entry) => {
        const value = entry.rules?.['no-restricted-imports'];
        if (!Array.isArray(value)) return true; // 'off', or a shape this test cannot read
        const options = value[1] as {patterns?: {group: string[]}[]} | undefined;
        return !options?.patterns?.some((pattern) => pattern.group.includes('@aws-sdk/*'));
      })
      .map((entry) => entry.files);

    expect(without).toEqual([]);
  });
});

/**
 * The half the lint rule cannot see.
 *
 * A dependency nobody imports is invisible to every import rule, and to every one of the
 * six specs that each deleted one client: none of them could tell that the `package.json`
 * entry outlived its last importer, because nothing went red when it stayed. That leftover
 * entry is how the next `@aws-sdk` import arrives — already installed, already resolvable.
 *
 * READS package.json, NEVER node_modules. Any dependency may vendor `@aws-sdk/*` packages
 * transitively, as the browser's sign-in library once did, so an assertion over the installed tree
 * fails for something nobody imports, and is deleted inside a week — and a deleted guard and a
 * passing one look identical in CI.
 */
describe('the server holds the one exception to the ban', () => {
  const serverClauses = eslintConfig.filter((entry) => entry.files?.includes('src/server/**/*.{ts,tsx}'));

  it('admits @aws-sdk/client-dynamodb under src/server/ and nothing else, and nowhere else', () => {
    expect(serverClauses).toHaveLength(1);
    const options = (serverClauses[0].rules?.['no-restricted-imports'] as unknown[])[1] as {
      patterns: {group: string[]}[];
    };
    expect(options.patterns.map((pattern) => pattern.group)).toEqual([
      ['@aws-sdk/*', '@aws-sdk/**', '!@aws-sdk/client-dynamodb']
    ]);

    const negated = eslintConfig
      .filter((entry) => !serverClauses.includes(entry))
      .flatMap((entry) => {
        const value = entry.rules?.['no-restricted-imports'];
        const patterns = Array.isArray(value) ? ((value[1] as {patterns?: {group: string[]}[]})?.patterns ?? []) : [];
        return patterns.flatMap((pattern) => pattern.group.filter((glob) => glob.startsWith('!')));
      });
    expect(negated).toEqual([]);
    expect(eslintConfig.indexOf(serverClauses[0])).toBe(eslintConfig.length - 1);
  });
});

describe('the manifest names one @aws-sdk package, for the server', () => {
  const PACKAGE_JSON = Object.values(
    import.meta.glob('../../package.json', {query: '?raw', import: 'default', eager: true})
  )[0] as string;

  it('names exactly @aws-sdk/client-dynamodb in dependencies or devDependencies', () => {
    const manifest = JSON.parse(PACKAGE_JSON) as {
      dependencies?: Record<string, string>;
      devDependencies?: Record<string, string>;
    };
    const declared = [...Object.keys(manifest.dependencies ?? {}), ...Object.keys(manifest.devDependencies ?? {})];

    // Guard-the-guard: a parse that read nothing would agree with an empty manifest.
    expect(declared).toContain('next');
    expect(declared.filter((name) => name.startsWith('@aws-sdk/'))).toEqual(['@aws-sdk/client-dynamodb']);
  });
});

describe('the browser signs in through the server, so Amplify is gone', () => {
  // Built here, so this file does not name what it sweeps for.
  const RETIRED = ['aws', 'amplify'].join('-');
  const MANIFEST = Object.values(
    import.meta.glob('../../package.json', {query: '?raw', import: 'default', eager: true})
  )[0] as string;
  const SOURCES = import.meta.glob(['../**/*.{ts,tsx}', '!../**/*.d.ts'], {
    query: '?raw',
    import: 'default',
    eager: true
  }) as Record<string, string>;

  it('names it in no source or test file under src/, and not in the manifest', () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(100);
    expect(Object.keys(SOURCES)).toContain('./apiClient.ts');

    expect(
      Object.entries(SOURCES)
        .filter(([, text]) => text.includes(RETIRED))
        .map(([path]) => path)
    ).toEqual([]);
    expect(MANIFEST).not.toContain(RETIRED);
  });
});

/**
 * react-router is gone, and with it the two clauses that lifted its ban: one for the navigation seam,
 * one for the route table and the test harness. Either one left behind would re-state the clause it
 * overrides as it stood when it was written, and silently stop following every later change to it.
 * With them gone, the seam's tests fall to the lib-test clause like every other lib test, and the
 * harness to the `src/**` clause.
 */
describe('the retired router’s exemption clauses', () => {
  const EXEMPTED = ['src/lib/navigation/**/*.{ts,tsx}', 'src/routes/table.tsx', 'src/test/**/*.{ts,tsx}'];

  it('declare no import rule of their own any more', () => {
    const survivors = governingEntries().filter((entry) => entry.files?.some((glob) => EXEMPTED.includes(glob)));

    expect(governingEntries().length).toBeGreaterThanOrEqual(6);
    expect(survivors.map((entry) => entry.files)).toEqual([]);
  });

  it('leave the seam’s own files under the shared layers’ bans', () => {
    const seamFile = 'src/lib/navigation/index.ts';
    const last = governingEntries()
      .filter((entry) => entry.files?.some((glob) => globMatches(glob, seamFile)))
      .at(-1);

    expect(last?.files).toEqual(['src/lib/**/*.{ts,tsx}', 'src/hooks/**/*.{ts,tsx}']);
    expect(last && groupsOf(last)).toEqual(expect.arrayContaining(['**/features/*', '../server']));
  });

  it('reads a glob as flat config does', () => {
    expect(globMatches('src/**/*.{ts,tsx}', 'src/routes/table.tsx')).toBe(true);
    expect(globMatches('src/lib/**/*.test.{ts,tsx}', 'src/lib/navigation/navigation.test.tsx')).toBe(true);
    expect(globMatches('src/lib/**/*.test.{ts,tsx}', 'src/lib/navigation/index.ts')).toBe(false);
    expect(globMatches('src/routes/table.tsx', 'src/routes/table.test.tsx')).toBe(false);
  });
});

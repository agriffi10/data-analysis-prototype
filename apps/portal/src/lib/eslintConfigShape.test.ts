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
describe('the @aws-sdk ban survives every no-restricted-imports clause', () => {
  // A glob need not START with `src/` to govern it: the base entry is `**/*.{ts,tsx}`, and
  // an entry with no `files` at all governs everything. Filtering on the `src/` prefix let
  // exactly that shape — the one most likely to be added next — declare the rule without the
  // group while this test passed and an `@aws-sdk` import in `features/` linted clean
  // (reproduced). So the question is inverted: an entry is out of scope only if EVERY glob it
  // names is demonstrably not under `src/`.
  const governsSrc = (entry: (typeof eslintConfig)[number]): boolean => {
    const globs = entry.files;
    if (globs === undefined || globs.length === 0) return true;
    return globs.some((glob) => glob.startsWith('src/') || !glob.startsWith('.'));
  };

  const governing = eslintConfig.filter(
    (entry) => entry.rules?.['no-restricted-imports'] !== undefined && governsSrc(entry)
  );

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
 * READS package.json, NEVER node_modules. `aws-amplify` vendors `@aws-sdk/*` packages
 * transitively, so an assertion over the installed tree would fail permanently and be
 * deleted inside a week — and a deleted guard and a passing one look identical in CI.
 */
describe('no @aws-sdk dependency survives', () => {
  const PACKAGE_JSON = Object.values(
    import.meta.glob('../../package.json', {query: '?raw', import: 'default', eager: true})
  )[0] as string;

  it('names none in dependencies or devDependencies', () => {
    const manifest = JSON.parse(PACKAGE_JSON) as {
      dependencies?: Record<string, string>;
      devDependencies?: Record<string, string>;
    };
    const declared = [...Object.keys(manifest.dependencies ?? {}), ...Object.keys(manifest.devDependencies ?? {})];

    // Guard-the-guard: a parse that read nothing would agree with an empty manifest.
    expect(declared).toContain('aws-amplify');
    expect(declared.filter((name) => name.startsWith('@aws-sdk/'))).toEqual([]);
  });
});

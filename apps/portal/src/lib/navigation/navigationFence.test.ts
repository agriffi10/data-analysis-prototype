import {ESLint} from 'eslint';
import {describe, expect, it} from 'vitest';

/**
 * The navigation fence, asserted by LINTING an import rather than by reading the config.
 *
 * Flat config replaces a rule's value at the last entry matching a file, so whether a file is fenced
 * depends on which clause matches it last. Linting a planted import as each place's file asks the
 * only question that matters; the seam and the table are the negative controls, without which a
 * rule that refused every import would pass too.
 */
// The suite runs from apps/portal, as every file-reading test here assumes.
const PORTAL = `${process.cwd()}/`;
const eslint = new ESLint({cwd: PORTAL});

const IMPORT = "import {useLocation} from 'react-router';";

/** The rule's messages for one planted import, linted as if it lived at `file`. */
async function fenceMessages(file: string, source: string): Promise<string[]> {
  const [result] = await eslint.lintText(`${source}\nexport {useLocation};\n`, {filePath: `${PORTAL}${file}`});
  return result.messages.filter((m) => m.ruleId === 'no-restricted-imports').map((m) => m.message);
}

describe('react-router outside the seam', () => {
  it.each([
    // Two features, because flat config's last matching clause decides: the catalog siblings have
    // a clause of their own, and every other feature has the general one.
    ['a feature', 'src/features/file-browser/probe.ts'],
    ['a catalog sibling', 'src/features/query/probe.ts'],
    ['a component', 'src/components/probe.tsx'],
    ['a route page', 'src/routes/probe.tsx'],
    ['a feature’s test', 'src/features/file-browser/probe.test.tsx'],
    ['a catalog sibling’s test', 'src/features/query/probe.test.tsx'],
    ['an area module', 'src/routes/areas/probe.tsx'],
    ['an area’s test', 'src/routes/areas/probe.test.tsx'],
    ['the route table’s test', 'src/routes/table.test.tsx'],
    ['an App Router page', 'src/app/[[...slug]]/probe.tsx']
  ])('is refused in %s, naming the seam', async (_place, file) => {
    expect((await fenceMessages(file, IMPORT)).join('\n')).toContain('import it from src/lib/navigation');
  });

  it.each([
    ['the seam', 'src/lib/navigation/probe.ts'],
    ['the route table', 'src/routes/table.tsx'],
    ['the test harness', 'src/test/probe.tsx']
  ])('is allowed in %s', async (_place, file) => {
    expect(await fenceMessages(file, IMPORT)).toEqual([]);
  });

  it('leaves the seam under the layering ban', async () => {
    const messages = await fenceMessages(
      'src/lib/navigation/probe.ts',
      "import {useLocation} from '../../features/query';"
    );

    expect(messages.join('\n')).toContain('are the shared layers and must not import from features/');
  });
});

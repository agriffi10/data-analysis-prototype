import {ESLint} from 'eslint';
import {describe, expect, it} from 'vitest';

/**
 * The page fence, asserted by LINTING an import: an App Router page may import lib/ and hooks/
 * statically, so neither may import components/ or routes/, which a page reaches only client-only.
 * Linting a planted import as each tree's file asks which clause matches it last, which a shape test
 * over the config entries cannot.
 */
// The suite runs from apps/portal, as every file-reading test here assumes.
const PORTAL = `${process.cwd()}/`;
const eslint = new ESLint({cwd: PORTAL});

/** The rule's messages for one planted import, linted as if it lived at `file`. */
async function fenceMessages(file: string, source: string): Promise<string[]> {
  const [result] = await eslint.lintText(`${source}\nexport {x};\n`, {filePath: `${PORTAL}${file}`});
  return result.messages.filter((m) => m.ruleId === 'no-restricted-imports').map((m) => m.message);
}

describe('lib/ and hooks/ stay off what a page reaches only client-only', () => {
  it.each([
    ['src/hooks/probe.ts', "import {x} from '../components/LoadingState';"],
    ['src/lib/probe.ts', "import {x} from '../routes/table';"],
    ['src/lib/nested/probe.ts', "import {x} from '../../components/LoadingState.js';"],
    ['src/lib/navigation/probe.ts', "import {x} from '../../routes/areas/files';"]
  ])('refuses the import in %s', async (file, source) => {
    const messages = await fenceMessages(file, source);

    expect(messages.join('\n')).toContain('what an App Router page may import statically');
  });

  it('lets a type-only import through, and leaves components/ and tests to their own rules', async () => {
    expect(await fenceMessages('src/hooks/probe.ts', "import type {x} from '../components/LoadingState';")).toEqual([]);
    expect(await fenceMessages('src/components/probe.tsx', "import {x} from './LoadingState';")).toEqual([]);
    expect(await fenceMessages('src/hooks/probe.test.ts', "import {x} from '../components/LoadingState';")).toEqual([]);
  });
});
